// Browser audio plumbing for the AI voice interview: microphone -> 16 kHz PCM16 chunks, and
// gapless playback of the agent's PCM16 replies. Pure browser APIs, no dependencies.

export const SAMPLE_RATE_HZ = 16000;

export interface MicCapture {
  stop: () => void;
}

/** Start capturing the microphone. `onChunk` receives 100 ms of PCM16 mono audio. */
export async function startMicCapture(
  ctx: AudioContext,
  onChunk: (pcm: ArrayBuffer) => void,
): Promise<MicCapture> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
  });
  try {
    await ctx.audioWorklet.addModule("/pcm16-worklet.js");
    const source = ctx.createMediaStreamSource(stream);
    const node = new AudioWorkletNode(ctx, "pcm16");
    node.port.onmessage = (e: MessageEvent<ArrayBuffer>) => onChunk(e.data);
    source.connect(node);
    return {
      stop: () => {
        node.port.onmessage = null;
        source.disconnect();
        node.disconnect();
        stream.getTracks().forEach((t) => t.stop());
      },
    };
  } catch (err) {
    stream.getTracks().forEach((t) => t.stop());
    throw err;
  }
}

/** Plays consecutive PCM16 buffers back to back and can be cut off instantly (barge-in). */
export class PcmPlayer {
  private nextTime = 0;
  private playing: AudioBufferSourceNode[] = [];

  constructor(private readonly ctx: AudioContext) {}

  play(pcm: ArrayBuffer): void {
    const samples = new Int16Array(pcm);
    if (samples.length === 0) return;
    const floats = new Float32Array(samples.length);
    for (let i = 0; i < samples.length; i++) floats[i] = (samples[i] ?? 0) / 32768;
    const buffer = this.ctx.createBuffer(1, floats.length, SAMPLE_RATE_HZ);
    buffer.copyToChannel(floats, 0);
    const source = this.ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(this.ctx.destination);
    this.nextTime = Math.max(this.nextTime, this.ctx.currentTime + 0.05);
    source.start(this.nextTime);
    this.nextTime += buffer.duration;
    this.playing.push(source);
    source.onended = () => {
      this.playing = this.playing.filter((s) => s !== source);
    };
  }

  clear(): void {
    for (const s of this.playing) {
      try {
        s.stop();
      } catch {
        /* already stopped */
      }
    }
    this.playing = [];
    this.nextTime = 0;
  }
}
