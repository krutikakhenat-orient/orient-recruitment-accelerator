// Video EVIDENCE for the AI voice interview: records the candidate's camera + microphone and
// uploads it in ~10 s chunks while the interview runs. Nothing analyses the video; it is kept
// for a person to review. Pure browser APIs (getUserMedia + MediaRecorder), no dependencies.

const CHUNK_MS = 10_000;
// Small on purpose: 360p at ~350 kbit/s is enough to see who is taking the interview, and
// keeps every upload well under the server's per-request limit.
const VIDEO_BITS = 350_000;
const AUDIO_BITS = 32_000;
const MAX_RETRIES = 3;

const TYPES = ["video/webm;codecs=vp8,opus", "video/webm", "video/mp4"];

export function pickVideoType(): string | null {
  if (typeof MediaRecorder === "undefined") return null;
  return TYPES.find((t) => MediaRecorder.isTypeSupported(t)) ?? null;
}

/** Ask for the camera (and microphone, so the evidence has sound). Throws if refused. */
export async function openCamera(): Promise<MediaStream> {
  return navigator.mediaDevices.getUserMedia({
    video: { width: { ideal: 640 }, height: { ideal: 360 }, frameRate: { ideal: 15 } },
    audio: { echoCancellation: true, noiseSuppression: true },
  });
}

export interface EvidenceRecorder {
  /** Stop recording, upload what is left, and close the upload. */
  stop: () => Promise<void>;
}

export function startEvidenceRecording(
  stream: MediaStream,
  recordingToken: string,
  onProblem: (message: string) => void,
): EvidenceRecorder | null {
  const mimeType = pickVideoType();
  if (!mimeType) return null;
  const recorder = new MediaRecorder(stream, {
    mimeType,
    videoBitsPerSecond: VIDEO_BITS,
    audioBitsPerSecond: AUDIO_BITS,
  });
  const contentType = mimeType.split(";")[0] ?? "video/webm";
  let seq = 0;
  let queue: Promise<void> = Promise.resolve();
  let warned = false;

  const upload = async (blob: Blob, n: number): Promise<void> => {
    for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
      try {
        const resp = await fetch(`/api/v1/ai-interviews/public/recording/chunk?seq=${n}`, {
          method: "POST",
          // The upload token goes in a header, never the URL, so it stays out of logs.
          headers: { "X-Recording-Token": recordingToken, "Content-Type": contentType },
          body: blob,
        });
        if (resp.ok) return;
        if (resp.status < 500) break; // rejected: retrying will not help
      } catch {
        /* network blip: retry */
      }
      await new Promise((r) => setTimeout(r, 1000 * (attempt + 1)));
    }
    if (!warned) {
      warned = true;
      onProblem("Part of the video could not be saved. Your interview continues as normal.");
    }
  };

  recorder.ondataavailable = (e: BlobEvent) => {
    if (e.data.size === 0) return;
    const n = seq++;
    // Uploads run one after another so the server receives the pieces in order.
    queue = queue.then(() => upload(e.data, n));
  };
  recorder.start(CHUNK_MS);

  return {
    stop: async () => {
      if (recorder.state !== "inactive") {
        const stopped = new Promise<void>((resolve) => {
          recorder.onstop = () => resolve();
        });
        recorder.stop(); // fires a final dataavailable, then stop
        await stopped;
      }
      stream.getTracks().forEach((t) => t.stop());
      await queue;
      try {
        await fetch("/api/v1/ai-interviews/public/recording/finish", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ recording_token: recordingToken }),
          keepalive: true,
        });
      } catch {
        /* the server also closes the recording when its upload window ends */
      }
    },
  };
}
