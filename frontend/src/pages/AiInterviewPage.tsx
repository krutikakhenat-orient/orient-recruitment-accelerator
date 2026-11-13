import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useParams } from "react-router-dom";

import {
  previewAiInterview,
  startAiInterview,
  type AiInterviewPreview,
} from "../api/aiInterviews";
import { ApiError } from "../api/client";
import { DeviceCheck } from "../components/DeviceCheck";
import { Logo } from "../components/Logo";
import { Button, Field } from "../components/ui";
import { PcmPlayer, SAMPLE_RATE_HZ, startMicCapture, type MicCapture } from "../lib/interviewAudio";
import {
  openCamera,
  pickVideoType,
  startEvidenceRecording,
  type EvidenceRecorder,
} from "../lib/interviewVideo";

/* Candidate-facing AI voice interview (public route /ai-interview/:token).

   The link token is the only credential. It is sent in a request BODY (never an API path),
   and consent is recorded before anything starts. The candidate never sees a score, ranking
   or assessment: when the interview ends they only see a thank-you. The agent is advisory;
   people review the transcript. Typed answers are always offered as an accessible fallback. */

type Phase = "loading" | "invalid" | "notice" | "starting" | "live" | "ended" | "error";

interface LogLine {
  id: number;
  who: "agent" | "you" | "system";
  text: string;
}

export function AiInterviewPage(): ReactNode {
  const { token = "" } = useParams();
  const [phase, setPhase] = useState<Phase>("loading");
  const [preview, setPreview] = useState<AiInterviewPreview | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [consent, setConsent] = useState(false);
  const [log, setLog] = useState<LogLine[]>([]);
  const [typed, setTyped] = useState("");
  const [textInput, setTextInput] = useState(false);
  const [micNote, setMicNote] = useState<string | null>(null);
  // Video evidence: a SEPARATE, optional consent. Saying no never blocks the interview.
  const [videoConsent, setVideoConsent] = useState(false);
  const [recording, setRecording] = useState(false);
  const [videoNote, setVideoNote] = useState<string | null>(null);
  const camRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<EvidenceRecorder | null>(null);
  const selfViewRef = useRef<HTMLVideoElement | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const micRef = useRef<MicCapture | null>(null);
  const playerRef = useRef<PcmPlayer | null>(null);
  const sawReady = useRef(false);
  const sawEnded = useRef(false);
  const lineId = useRef(0);

  const addLine = useCallback((who: LogLine["who"], text: string) => {
    lineId.current += 1;
    const id = lineId.current;
    setLog((prev) => [...prev, { id, who, text }]);
  }, []);

  const cleanup = useCallback(() => {
    // Upload the last piece of video and close the recording (fire and forget).
    const rec = recorderRef.current;
    recorderRef.current = null;
    if (rec) void rec.stop();
    else camRef.current?.getTracks().forEach((t) => t.stop());
    camRef.current = null;
    setRecording(false);
    playerRef.current?.clear();
    micRef.current?.stop();
    micRef.current = null;
    if (ctxRef.current && ctxRef.current.state !== "closed") void ctxRef.current.close();
    ctxRef.current = null;
    const ws = wsRef.current;
    wsRef.current = null;
    if (ws && ws.readyState <= 1) ws.close();
  }, []);

  // Load what the candidate needs to see before consenting.
  useEffect(() => {
    let cancelled = false;
    previewAiInterview(token)
      .then((p) => {
        if (cancelled) return;
        setPreview(p);
        setPhase("notice");
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setProblem(
          e instanceof ApiError
            ? e.message
            : "We could not open this interview link. Please contact the recruiter.",
        );
        setPhase("invalid");
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  // Always release the microphone and socket when leaving the page.
  useEffect(() => cleanup, [cleanup]);

  const begin = useCallback(async () => {
    if (!preview || !consent) return;
    setProblem(null);
    setPhase("starting");
    sawReady.current = false;
    sawEnded.current = false;
    try {
      // Audio and the microphone come FIRST, before the session is started: the permission
      // prompt can take a while, and the connection URL from the server is short-lived.
      const ctx = new AudioContext({ sampleRate: SAMPLE_RATE_HZ });
      await ctx.resume();
      ctxRef.current = ctx;
      playerRef.current = new PcmPlayer(ctx);

      try {
        micRef.current = await startMicCapture(ctx, (chunk) => {
          // The agent's first message must be the JSON "start"; never send audio before the
          // agent has accepted the session ("ready"), or it rejects the connection.
          const live = wsRef.current;
          if (sawReady.current && live && live.readyState === WebSocket.OPEN) live.send(chunk);
        });
      } catch {
        // Microphone denied/unavailable: the interview can still run with typed answers.
        setMicNote("Your microphone is not available, so please type your answers below.");
        setTextInput(true);
      }

      // Camera only if the candidate opted in. If it is refused or missing, carry on by voice.
      if (videoConsent && preview.video_recording_offered && preview.video_notice_version) {
        if (!pickVideoType()) {
          setVideoNote("This browser cannot record video, so the interview continues by voice only.");
        } else {
          try {
            camRef.current = await openCamera();
          } catch {
            setVideoNote("The camera is not available, so the interview continues by voice only.");
          }
        }
      }

      const started = await startAiInterview(
        token,
        preview.notice_version,
        camRef.current && preview.video_notice_version
          ? { noticeVersion: preview.video_notice_version }
          : null,
      );
      if (camRef.current && started.recording_token) {
        recorderRef.current = startEvidenceRecording(
          camRef.current,
          started.recording_token,
          setVideoNote,
        );
        setRecording(recorderRef.current !== null);
      } else if (camRef.current) {
        camRef.current.getTracks().forEach((t) => t.stop());
        camRef.current = null;
      }

      // Attach every handler synchronously after creating the socket so no event is missed.
      const ws = new WebSocket(started.ws_url);
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;

      ws.onopen = () =>
        ws.send(
          JSON.stringify({
            type: "start",
            interview_id: started.interview_id,
            join_token: started.join_token,
          }),
        );
      ws.onmessage = (e: MessageEvent<unknown>) => {
        if (typeof e.data !== "string") {
          if (e.data instanceof ArrayBuffer) playerRef.current?.play(e.data);
          return;
        }
        let msg: { type?: string; text?: string; final?: boolean; text_input?: boolean; code?: string };
        try {
          msg = JSON.parse(e.data) as typeof msg;
        } catch {
          return;
        }
        switch (msg.type) {
          case "ready":
            sawReady.current = true;
            if (msg.text_input) setTextInput(true);
            setPhase("live");
            break;
          case "agent_text":
            if (msg.text) addLine("agent", msg.text);
            break;
          case "transcript":
            if (msg.final && msg.text) addLine("you", msg.text);
            break;
          case "clear":
            playerRef.current?.clear();
            break;
          case "warning":
            addLine("system", "There was a small audio problem. You can type your answer instead.");
            setTextInput(true);
            break;
          case "error":
            setProblem("The interview could not continue. Please contact the recruiter.");
            break;
          case "ended":
            sawEnded.current = true;
            break;
          default:
            break;
        }
      };
      ws.onclose = () => {
        cleanup();
        if (sawEnded.current || sawReady.current) setPhase("ended");
        else {
          setProblem((p) => p ?? "We could not connect to the interview. Please try again.");
          setPhase("error");
        }
      };
    } catch (e) {
      cleanup();
      setProblem(
        e instanceof ApiError ? e.message : "We could not start the interview. Please try again.",
      );
      setPhase("error");
    }
  }, [addLine, cleanup, consent, preview, token, videoConsent]);

  // Show the candidate their own camera while it records (they must always know).
  useEffect(() => {
    const el = selfViewRef.current;
    if (el) el.srcObject = recording ? camRef.current : null;
  }, [recording, phase]);

  const endInterview = (): void => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "end" }));
  };

  const sendTyped = (): void => {
    const text = typed.trim();
    const ws = wsRef.current;
    if (text && ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "utterance", text }));
      setTyped("");
    }
  };

  return (
    <div
      className={`apply-shell ${phase === "notice" || phase === "starting" || phase === "error" || phase === "live" ? "apply-shell--wide" : ""}`}
    >
      <div className="apply-brandbar apply-brandbar--center">
        <Logo size={44} title="Orient" />
        <span className="apply-brandbar__name">Orient Recruitment</span>
      </div>

      <div className="card apply-card">
        {phase === "loading" && (
          <p className="subtle" role="status">
            Opening your interview…
          </p>
        )}

        {phase === "invalid" && (
          <>
            <h1>This interview link can&rsquo;t be used</h1>
            <p role="alert">{problem}</p>
            <p className="subtle">
              Links expire and can only be used a limited number of times. Please contact the
              recruiter for a new link.
            </p>
          </>
        )}

        {(phase === "notice" || phase === "starting" || phase === "error") && preview && (
          <div className="ai-iv-grid">
          <div>
            <h1>Voice interview: {preview.role_title}</h1>
            <p>
              This takes up to {preview.max_minutes} minutes. Find a quiet place and use headphones
              if you can, so the assistant doesn&rsquo;t hear itself.
            </p>
            <section aria-labelledby="notice-h" className="card" style={{ marginBottom: 12 }}>
              <h2 id="notice-h" style={{ marginTop: 0, fontSize: "1.05rem" }}>
                Before you begin
              </h2>
              <p>{preview.notice_text}</p>
              <p className="subtle">Notice version: {preview.notice_version}</p>
            </section>
            {problem && (
              <div className="error-summary" role="alert">
                {problem}
              </div>
            )}
            <label
              htmlFor="ai-consent"
              style={{ display: "flex", gap: 8, alignItems: "flex-start", margin: "12px 0" }}
            >
              <input
                id="ai-consent"
                type="checkbox"
                checked={consent}
                onChange={(e) => setConsent(e.target.checked)}
                disabled={phase === "starting"}
              />
              <span>
                I have read the notice above. I agree to take this AI-assisted interview and to my
                answers being recorded as a transcript for human review.
              </span>
            </label>
            {preview.video_recording_offered && preview.video_notice_text && (
              <section
                aria-labelledby="video-notice-h"
                className="card"
                style={{ margin: "12px 0" }}
              >
                <h2 id="video-notice-h" style={{ marginTop: 0, fontSize: "1.05rem" }}>
                  Video recording (optional)
                </h2>
                <p>{preview.video_notice_text}</p>
                <p className="subtle">Notice version: {preview.video_notice_version}</p>
                <label
                  htmlFor="ai-video-consent"
                  style={{ display: "flex", gap: 8, alignItems: "flex-start" }}
                >
                  <input
                    id="ai-video-consent"
                    type="checkbox"
                    checked={videoConsent}
                    onChange={(e) => setVideoConsent(e.target.checked)}
                    disabled={phase === "starting"}
                  />
                  <span>
                    I agree to my camera and microphone being recorded as evidence of this
                    interview. This is optional: leave it unticked to take the interview by voice
                    only.
                  </span>
                </label>
              </section>
            )}
            <Button
              variant="primary"
              disabled={!consent || phase === "starting"}
              onClick={() => void begin()}
            >
              {phase === "starting" ? "Connecting…" : "Start interview"}
            </Button>
          </div>
          <aside>
            {/* Unmounted while connecting so the check releases the mic and camera first. */}
            {phase !== "starting" && (
              <DeviceCheck
                wantVideo={
                  videoConsent && !!preview.video_recording_offered && !!preview.video_notice_version
                }
              />
            )}
          </aside>
          </div>
        )}

        {phase === "live" && (
          <div className="ai-iv-grid ai-iv-grid--live">
          <div>
            <h1>Interview in progress</h1>
            <p className="subtle" role="status">
              Speak when the assistant finishes asking. You can stop at any time.
            </p>
            {problem && (
              <div className="error-summary" role="alert">
                {problem}
              </div>
            )}
            <div
              aria-live="polite"
              aria-label="Conversation"
              className="card ai-iv-log"
            >
              {log.length === 0 && <p className="subtle">The assistant is about to speak…</p>}
              {log.map((l) => (
                <p key={l.id} style={{ margin: "6px 0" }}>
                  <strong>
                    {l.who === "agent" ? "Interviewer: " : l.who === "you" ? "You: " : ""}
                  </strong>
                  {l.text}
                </p>
              ))}
            </div>
            {textInput && (
              <div style={{ marginBottom: 12 }}>
                <Field label="Type your answer (optional)" htmlFor="ai-typed">
                  <div style={{ display: "flex", gap: 8 }}>
                    <input
                      id="ai-typed"
                      value={typed}
                      onChange={(e) => setTyped(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") sendTyped();
                      }}
                      style={{ flex: 1 }}
                    />
                    <Button onClick={sendTyped} disabled={!typed.trim()}>
                      Send
                    </Button>
                  </div>
                </Field>
              </div>
            )}
          </div>
          <aside className="ai-iv-side">
            {recording ? (
              <>
                <video
                  ref={selfViewRef}
                  autoPlay
                  muted
                  playsInline
                  aria-label="Your camera, being recorded"
                  className="ai-iv-selfview"
                />
                <p role="status" className="ai-iv-rec">
                  <span aria-hidden="true" className="ai-iv-rec__dot" />
                  <strong>Recording video</strong>
                </p>
              </>
            ) : (
              <p className="subtle">Voice interview (no video).</p>
            )}
            {micNote && <p role="note">{micNote}</p>}
            {videoNote && <p role="note">{videoNote}</p>}
            <Button variant="danger" onClick={endInterview}>
              End interview
            </Button>
          </aside>
          </div>
        )}

        {phase === "ended" && (
          <>
            <h1>Thank you</h1>
            <p>
              Your interview is complete. The hiring team will review it and be in touch. Nothing
              about your result is decided automatically.
            </p>
            <p className="subtle">You can safely close this page.</p>
          </>
        )}
      </div>
    </div>
  );
}
