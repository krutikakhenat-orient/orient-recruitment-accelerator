import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import { Button } from "./ui";

/* Pre-interview device check for the candidate: browser support, connection speed, microphone
   and (only if they opted in to video) camera.

   Advisory only: it helps the candidate fix problems before starting and never blocks the
   interview. It checks the DEVICE, not the person. There is deliberately no face, person,
   phone or "proctoring" detection (responsible-ai.md): the camera preview is shown to the
   candidate and nothing analyses it. */

type State = "pending" | "ok" | "warn" | "fail";

interface Check {
  key: string;
  label: string;
  state: State;
  detail: string;
}

const BASE = "/api/v1/ai-interviews/public/network-check";
const SAMPLE_BYTES = 256 * 1024;
// The interview sends about 0.3 Mbit/s of voice, plus about 0.4 Mbit/s when video is on.
const UPLOAD_GOOD_MBPS_VOICE = 0.5;
const UPLOAD_GOOD_MBPS_VIDEO = 1.0;
const DOWNLOAD_GOOD_MBPS = 1.0;
const DELAY_GOOD_MS = 400;
const DELAY_OK_MS = 1000;
const MIC_HEARD_LEVEL = 0.04;

const ICON: Record<State, string> = { pending: "…", ok: "✓", warn: "!", fail: "✕" };
const WORD: Record<State, string> = {
  pending: "Checking",
  ok: "OK",
  warn: "Check this",
  fail: "Problem",
};

function mbps(bytes: number, ms: number): number {
  return ms > 0 ? (bytes * 8) / (ms / 1000) / 1_000_000 : 0;
}

async function timed(run: () => Promise<Response>): Promise<number> {
  const t0 = performance.now();
  const resp = await run();
  await resp.arrayBuffer();
  if (!resp.ok) throw new Error(String(resp.status));
  return performance.now() - t0;
}

async function measureNetwork(wantVideo: boolean): Promise<Check> {
  const label = "Internet connection";
  if (!navigator.onLine) return { key: "net", label, state: "fail", detail: "You appear to be offline." };
  try {
    // Delay: best of three small requests (the first can include connection set-up).
    const delays: number[] = [];
    for (let i = 0; i < 3; i++) {
      delays.push(await timed(() => fetch(`${BASE}?size=ping&t=${Date.now()}`, { cache: "no-store" })));
    }
    const delay = Math.min(...delays);
    const down = mbps(
      SAMPLE_BYTES,
      await timed(() => fetch(`${BASE}?size=sample&t=${Date.now()}`, { cache: "no-store" })),
    );
    const up = mbps(
      SAMPLE_BYTES,
      await timed(() =>
        fetch(BASE, { method: "POST", body: new Uint8Array(SAMPLE_BYTES), cache: "no-store" }),
      ),
    );
    const needUp = wantVideo ? UPLOAD_GOOD_MBPS_VIDEO : UPLOAD_GOOD_MBPS_VOICE;
    const figures = `Delay ${Math.round(delay)} ms · download ${down.toFixed(1)} Mbit/s · upload ${up.toFixed(1)} Mbit/s`;
    if (delay > DELAY_OK_MS || up < needUp / 2) {
      return {
        key: "net",
        label,
        state: "fail",
        detail: `${figures}. This is likely too slow: the interviewer may cut out. Try another network.`,
      };
    }
    if (delay > DELAY_GOOD_MS || up < needUp || down < DOWNLOAD_GOOD_MBPS) {
      return {
        key: "net",
        label,
        state: "warn",
        detail: `${figures}. It should work, but close other downloads or move closer to your Wi-Fi.`,
      };
    }
    return { key: "net", label, state: "ok", detail: figures };
  } catch {
    return {
      key: "net",
      label,
      state: "fail",
      detail: "We could not reach the interview server. Check your connection and try again.",
    };
  }
}

function browserCheck(wantVideo: boolean): Check {
  const missing: string[] = [];
  if (!navigator.mediaDevices?.getUserMedia) missing.push("microphone access");
  if (typeof AudioContext === "undefined" || !("audioWorklet" in AudioContext.prototype)) {
    missing.push("audio processing");
  }
  if (typeof WebSocket === "undefined") missing.push("live connection");
  if (wantVideo && typeof MediaRecorder === "undefined") missing.push("video recording");
  return missing.length === 0
    ? { key: "browser", label: "Browser", state: "ok", detail: "Your browser supports the interview." }
    : {
        key: "browser",
        label: "Browser",
        state: "fail",
        detail: `Missing: ${missing.join(", ")}. Please use a recent Chrome, Edge or Firefox.`,
      };
}

export function DeviceCheck({ wantVideo }: { wantVideo: boolean }): ReactNode {
  const [checks, setChecks] = useState<Check[]>([]);
  const [running, setRunning] = useState(false);
  const [level, setLevel] = useState(0);
  const streamRef = useRef<MediaStream | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const rafRef = useRef<number | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  const release = useCallback(() => {
    if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    rafRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (ctxRef.current && ctxRef.current.state !== "closed") void ctxRef.current.close();
    ctxRef.current = null;
  }, []);

  const put = useCallback(
    (check: Check): void =>
      setChecks((prev) => [...prev.filter((c) => c.key !== check.key), check]),
    [],
  );

  const run = useCallback(async () => {
    release();
    setRunning(true);
    setLevel(0);
    const browser = browserCheck(wantVideo);
    setChecks([
      browser,
      { key: "net", label: "Internet connection", state: "pending", detail: "Measuring speed…" },
      { key: "mic", label: "Microphone", state: "pending", detail: "Waiting for permission…" },
      ...(wantVideo
        ? [{ key: "cam", label: "Camera", state: "pending" as State, detail: "Waiting for permission…" }]
        : []),
    ]);

    const network = measureNetwork(wantVideo).then(put);

    if (browser.state === "ok") {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true },
          video: wantVideo ? { width: { ideal: 640 }, height: { ideal: 360 } } : false,
        });
        streamRef.current = stream;
        if (wantVideo) {
          const cam = stream.getVideoTracks()[0];
          put(
            cam
              ? { key: "cam", label: "Camera", state: "ok", detail: "Camera works. This is what will be recorded." }
              : { key: "cam", label: "Camera", state: "fail", detail: "No camera found." },
          );
          if (videoRef.current) videoRef.current.srcObject = stream;
        }
        // Microphone level meter: "OK" once we have heard you speak.
        const ctx = new AudioContext();
        ctxRef.current = ctx;
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 1024;
        ctx.createMediaStreamSource(stream).connect(analyser);
        const buf = new Float32Array(analyser.fftSize);
        let heard = false;
        put({ key: "mic", label: "Microphone", state: "warn", detail: "Say a few words to test it." });
        const tick = (): void => {
          analyser.getFloatTimeDomainData(buf);
          let sum = 0;
          for (const v of buf) sum += v * v;
          const rms = Math.sqrt(sum / buf.length);
          setLevel(Math.min(1, rms * 8));
          if (!heard && rms > MIC_HEARD_LEVEL) {
            heard = true;
            put({ key: "mic", label: "Microphone", state: "ok", detail: "We can hear you." });
          }
          rafRef.current = requestAnimationFrame(tick);
        };
        tick();
      } catch {
        put({
          key: "mic",
          label: "Microphone",
          state: "fail",
          detail: "Permission was refused or no microphone was found. You can still type your answers.",
        });
        if (wantVideo) {
          put({
            key: "cam",
            label: "Camera",
            state: "fail",
            detail: "Camera unavailable. The interview will continue by voice only.",
          });
        }
      }
    }
    await network;
    setRunning(false);
  }, [put, release, wantVideo]);

  // Re-run when the video choice changes; always release the devices when leaving.
  useEffect(() => {
    void run();
    return release;
  }, [run, release]);

  const order = ["browser", "net", "mic", "cam"];
  const sorted = [...checks].sort((a, b) => order.indexOf(a.key) - order.indexOf(b.key));

  return (
    <section aria-labelledby="device-check-h" className="card device-check">
      <div className="btn-row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <h2 id="device-check-h" style={{ margin: 0, fontSize: "1.05rem" }}>
          Device check
        </h2>
        <Button small disabled={running} onClick={() => void run()}>
          {running ? "Checking…" : "Check again"}
        </Button>
      </div>
      <p className="subtle" style={{ margin: "4px 0 10px" }}>
        This only checks your device and connection. It does not stop you from starting.
      </p>
      <ul className="device-check__list" aria-live="polite">
        {sorted.map((c) => (
          <li key={c.key} className={`device-check__item device-check__item--${c.state}`}>
            <span className="device-check__icon" aria-hidden="true">
              {ICON[c.state]}
            </span>
            <span>
              <strong>{c.label}</strong> <span className="sr-only">{WORD[c.state]}:</span>
              <span className="device-check__word" aria-hidden="true">
                {WORD[c.state]}
              </span>
              <br />
              <span className="subtle">{c.detail}</span>
              {c.key === "mic" && c.state !== "fail" && (
                <span
                  className="device-check__meter"
                  role="meter"
                  aria-label="Microphone level"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={Math.round(level * 100)}
                >
                  <span style={{ width: `${Math.round(level * 100)}%` }} />
                </span>
              )}
            </span>
          </li>
        ))}
      </ul>
      {wantVideo && (
        <video
          ref={videoRef}
          autoPlay
          muted
          playsInline
          aria-label="Your camera preview"
          className="device-check__preview"
        />
      )}
    </section>
  );
}
