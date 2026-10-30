import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type ReactNode } from "react";

import {
  downloadInductionCertificate,
  fetchInductionCertificate,
  fetchInductionVideoBlob,
  getInductionStatus,
  getInductionVideoMeta,
  markInductionComplete,
} from "../api/resources";
import { useAuth } from "../app/auth-context";
import { Badge, Button, Card, Empty, ErrorNote, Loading, MatchBar } from "../components/ui";

/* The employee induction dashboard. It renders EXACTLY two features and nothing else from
   the staff portal:
     1. "Watch induction video" — the developer-provisioned video, fetched as a Blob with the
        bearer token and played via an object URL (tokens are in-memory only, so a plain
        <video src> cannot authenticate). Completing the video records the completion.
     2. "Certificate" — locked until the induction is marked complete, then unlocks a button
        that fetches the certificate HTML and opens it in a new tab for viewing/printing. */
export function EmployeePage(): ReactNode {
  const { token } = useAuth();
  const queryClient = useQueryClient();

  const status = useQuery({ queryKey: ["induction-status"], queryFn: getInductionStatus });

  return (
    <>
      <div className="page-head">
        <h1>Welcome to your induction</h1>
        <p>Watch the induction video, then download your completion certificate.</p>
      </div>

      {status.isLoading && <Loading label="Loading your induction…" />}
      {status.error && <ErrorNote>Could not load your induction. Please try again.</ErrorNote>}

      {status.data && (
        <>
          <InductionVideoCard
            token={token}
            hasVideo={status.data.has_video}
            completed={status.data.completed}
            onCompleted={() => {
              void queryClient.invalidateQueries({ queryKey: ["induction-status"] });
            }}
          />
          <CertificateCard token={token} completed={status.data.completed} />
        </>
      )}
    </>
  );
}

// The video is considered fully watched once contiguous playback reaches this fraction of
// the total duration (just short of 1.0 to tolerate the final frame / rounding).
const FULLY_WATCHED_FRACTION = 0.98;
// A normal "timeupdate" tick advances by a fraction of a second; a jump larger than this is
// treated as a seek (not genuine playback) and does NOT advance the watched marker.
const MAX_PLAYBACK_STEP_SECONDS = 1.5;
// Forward seeks beyond the watched marker by more than this tolerance are snapped back, so
// dragging the scrubber to the end cannot shortcut completion. Re-watching is always allowed.
const SEEK_TOLERANCE_SECONDS = 1;

/* Card 1: watch the induction video. Loads the video metadata, fetches the stream Blob with
   the bearer token, and plays it via an object URL. Completion is gated on genuinely watching
   the whole video: forward seeks past the furthest point reached through real playback are
   snapped back, and completion only unlocks once contiguous playback reaches the end. */
function InductionVideoCard({
  token,
  hasVideo,
  completed,
  onCompleted,
}: {
  token: () => string | null;
  hasVideo: boolean;
  completed: boolean;
  onCompleted: () => void;
}): ReactNode {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [videoError, setVideoError] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  // Furthest point (seconds) reached through normal, contiguous playback.
  const [watchedUpTo, setWatchedUpTo] = useState(0);
  // Video duration once known (finite). Null while unknown/streaming-unbounded.
  const [duration, setDuration] = useState<number | null>(null);

  const fullyWatched =
    duration !== null &&
    Number.isFinite(duration) &&
    duration > 0 &&
    watchedUpTo >= duration * FULLY_WATCHED_FRACTION;

  const watchedPct =
    duration !== null && Number.isFinite(duration) && duration > 0
      ? Math.min(100, (watchedUpTo / duration) * 100)
      : 0;

  const meta = useQuery({
    queryKey: ["induction-video-meta"],
    queryFn: getInductionVideoMeta,
    enabled: hasVideo,
  });

  // Fetch the video bytes with the bearer token and expose them as an object URL. The URL is
  // revoked on cleanup (dependency change or unmount) so we never leak object URLs.
  useEffect(() => {
    if (!hasVideo) return;
    const bearer = token();
    if (!bearer) return;
    let revoked = false;
    let createdUrl: string | null = null;
    setVideoError(null);
    fetchInductionVideoBlob(bearer)
      .then(({ blob }) => {
        if (revoked) return;
        createdUrl = URL.createObjectURL(blob);
        setObjectUrl(createdUrl);
      })
      .catch((err: unknown) => {
        if (revoked) return;
        setVideoError(err instanceof Error ? err.message : "Could not load the induction video.");
      });
    return () => {
      revoked = true;
      if (createdUrl) URL.revokeObjectURL(createdUrl);
      setObjectUrl(null);
    };
  }, [hasVideo, token]);

  const complete = useMutation({
    mutationFn: markInductionComplete,
    onSuccess: onCompleted,
  });

  // Completion is only ever recorded once the video has genuinely been watched to the end.
  const confirmCompletion = (): void => {
    if (!fullyWatched || completed || complete.isPending) return;
    complete.mutate();
  };

  // Track the furthest contiguous playback position. Only advance while playback is
  // progressing normally (a small step); larger jumps are seeks and must not advance it.
  const handleTimeUpdate = (): void => {
    const video = videoRef.current;
    if (!video) return;
    const current = video.currentTime;
    setWatchedUpTo((prev) => {
      if (current <= prev) return prev; // re-watching earlier content: keep the marker.
      if (current - prev <= MAX_PLAYBACK_STEP_SECONDS) return current; // normal playback.
      return prev; // a forward jump (seek): do not credit unwatched content.
    });
  };

  // Prevent skip-ahead: if the user seeks forward past the watched marker (beyond a small
  // tolerance), snap back to the marker. Seeking backwards to re-watch is always allowed.
  const handleSeeking = (): void => {
    const video = videoRef.current;
    if (!video) return;
    if (video.currentTime > watchedUpTo + SEEK_TOLERANCE_SECONDS) {
      video.currentTime = watchedUpTo;
    }
  };

  const handleLoadedMetadata = (): void => {
    const video = videoRef.current;
    if (video && Number.isFinite(video.duration)) setDuration(video.duration);
  };

  return (
    <Card
      title="Watch induction video"
      actions={
        completed ? (
          <Badge tone="ok">Completed</Badge>
        ) : (
          <Badge tone="warn">Not completed</Badge>
        )
      }
    >
      {!hasVideo && (
        <Empty>
          No induction video is available yet. Please check back later or contact your
          administrator.
        </Empty>
      )}

      {hasVideo && (
        <>
          {meta.data && (
            <div style={{ marginBottom: 12 }}>
              <h3 style={{ margin: 0 }}>{meta.data.title}</h3>
              {meta.data.description && (
                <p className="subtle" style={{ marginTop: 4 }}>
                  {meta.data.description}
                </p>
              )}
            </div>
          )}

          {videoError && <ErrorNote>{videoError}</ErrorNote>}

          {!videoError && !objectUrl && <Loading label="Loading the video…" />}

          {objectUrl && (
            <video
              ref={videoRef}
              src={objectUrl}
              controls
              style={{ width: "100%", borderRadius: 8, background: "#000" }}
              aria-label={meta.data ? `Induction video: ${meta.data.title}` : "Induction video"}
              onLoadedMetadata={handleLoadedMetadata}
              onDurationChange={handleLoadedMetadata}
              onTimeUpdate={handleTimeUpdate}
              onSeeking={handleSeeking}
              onEnded={confirmCompletion}
            >
              Your browser does not support the video element.
            </video>
          )}

          {complete.isError && (
            <ErrorNote>
              {complete.error instanceof Error
                ? complete.error.message
                : "Could not record your completion. Please try again."}
            </ErrorNote>
          )}

          {!completed && objectUrl && (
            <>
              {/* Progress hint — numeric label so the locked state is never conveyed by
                  colour alone (accessibility.md). */}
              <div style={{ marginTop: 12 }}>
                <MatchBar
                  label="Induction watched"
                  value={watchedPct}
                  tone={fullyWatched ? "ok" : "info"}
                />
              </div>
              <div className="btn-row" style={{ marginTop: 12 }}>
                <Button
                  variant="primary"
                  onClick={confirmCompletion}
                  disabled={!fullyWatched || complete.isPending}
                  aria-disabled={!fullyWatched || complete.isPending}
                  aria-describedby="induction-complete-hint"
                >
                  {complete.isPending ? "Recording…" : "Mark induction complete"}
                </Button>
                <span id="induction-complete-hint" className="subtle">
                  {fullyWatched
                    ? "This unlocks your completion certificate."
                    : "Watch the full video to unlock. You cannot skip ahead."}
                </span>
              </div>
            </>
          )}
        </>
      )}
    </Card>
  );
}

/* Card 2: the completion certificate. Locked (with an explanatory badge) until the induction
   is complete. When unlocked, a button fetches the certificate HTML with the bearer token
   and opens it in a new tab so the employee can view and print it. */
function CertificateCard({
  token,
  completed,
}: {
  token: () => string | null;
  completed: boolean;
}): ReactNode {
  const [error, setError] = useState<string | null>(null);
  // Track object URLs we open so they can be revoked on unmount.
  const openedUrls = useRef<string[]>([]);

  useEffect(() => {
    return () => {
      for (const url of openedUrls.current) URL.revokeObjectURL(url);
      openedUrls.current = [];
    };
  }, []);

  const certificate = useMutation({
    mutationFn: async () => {
      const bearer = token();
      if (!bearer) throw new Error("Your session has expired. Please sign in again.");
      return fetchInductionCertificate(bearer);
    },
    onSuccess: (html) => {
      setError(null);
      // Open the certificate HTML in a new tab via a Blob object URL so the employee can
      // view and print it. The URL is revoked when this card unmounts.
      const blob = new Blob([html], { type: "text/html" });
      const url = URL.createObjectURL(blob);
      openedUrls.current.push(url);
      window.open(url, "_blank", "noopener,noreferrer");
    },
    onError: (err: unknown) => {
      setError(err instanceof Error ? err.message : "Could not load your certificate.");
    },
  });

  // Download the certificate to the user's local disk. Fetches the bytes with the bearer
  // token, then triggers a browser save via a temporary <a download> (same pattern as
  // downloadResume/downloadCampaignExport). Works after deployment, not just locally.
  const download = useMutation({
    mutationFn: async () => {
      const bearer = token();
      if (!bearer) throw new Error("Your session has expired. Please sign in again.");
      return downloadInductionCertificate(bearer);
    },
    onSuccess: ({ blob, filename }) => {
      setError(null);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    },
    onError: (err: unknown) => {
      setError(err instanceof Error ? err.message : "Could not download your certificate.");
    },
  });

  return (
    <Card
      title="Certificate"
      actions={completed ? <Badge tone="ok">Unlocked</Badge> : <Badge tone="warn">Locked</Badge>}
    >
      {!completed ? (
        <Empty>
          Complete the induction video to unlock your certificate. You must watch the whole
          video before your certificate becomes available.
        </Empty>
      ) : (
        <>
          <p className="subtle" style={{ marginTop: 0 }}>
            Your induction is complete. Download your certificate to your device, or view and
            print it.
          </p>
          {error && <ErrorNote>{error}</ErrorNote>}
          <div className="btn-row">
            <Button
              variant="primary"
              onClick={() => download.mutate()}
              disabled={download.isPending}
            >
              {download.isPending ? "Preparing…" : "Download certificate"}
            </Button>
            <Button
              variant="ghost"
              onClick={() => certificate.mutate()}
              disabled={certificate.isPending}
            >
              {certificate.isPending ? "Preparing…" : "View certificate"}
            </Button>
          </div>
        </>
      )}
    </Card>
  );
}
