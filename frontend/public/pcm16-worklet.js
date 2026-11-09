/* AudioWorklet: converts microphone audio to 16-bit PCM mono chunks of 1600 samples
   (100 ms at 16 kHz) and posts them to the main thread, which forwards them to the
   interview agent's WebSocket. Served from the app's own origin (no blob: URL needed). */
class Pcm16Processor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.chunk = new Int16Array(1600);
    this.filled = 0;
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) return true;
    for (let i = 0; i < channel.length; i++) {
      const s = Math.max(-1, Math.min(1, channel[i]));
      this.chunk[this.filled++] = s < 0 ? s * 32768 : s * 32767;
      if (this.filled === this.chunk.length) {
        const out = this.chunk.slice();
        this.port.postMessage(out.buffer, [out.buffer]);
        this.filled = 0;
      }
    }
    return true;
  }
}

registerProcessor("pcm16", Pcm16Processor);
