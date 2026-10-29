import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type ReactNode } from "react";

import {
  fetchInductionCertificate,
  fetchInductionVideoBlob,
  getInductionStatus,
  getInductionVideoMeta,
  markInductionComplete,
} from "../api/resources";
import { useAuth } from "../app/auth-context";
import { Badge, Button, Card, Empty, ErrorNote, Loading } from "../components/ui";

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

/* Card 1: watch the induction video. Loads the video metadata, fetches the stream Blob with
   the bearer token, and plays it via an object URL. When the video ends (or the employee
   confirms completion) the completion is recorded and the status query is refetched. */
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

  const confirmCompletion = (): void => {
    if (!complete.isPending) complete.mutate();
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
              src={objectUrl}
              controls
              style={{ width: "100%", borderRadius: 8, background: "#000" }}
              aria-label={meta.data ? `Induction video: ${meta.data.title}` : "Induction video"}
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

          {!completed && (
            <div className="btn-row" style={{ marginTop: 12 }}>
              <Button
                variant="primary"
                onClick={confirmCompletion}
                disabled={complete.isPending || !objectUrl}
              >
                {complete.isPending ? "Recording…" : "I have completed the induction"}
              </Button>
              <span className="subtle">
                This unlocks your completion certificate.
              </span>
            </div>
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

  return (
    <Card
      title="Certificate"
      actions={completed ? <Badge tone="ok">Unlocked</Badge> : <Badge tone="warn">Locked</Badge>}
    >
      {!completed ? (
        <Empty>
          Your completion certificate unlocks once you finish watching the induction video.
        </Empty>
      ) : (
        <>
          <p className="subtle" style={{ marginTop: 0 }}>
            Your induction is complete. View or print your completion certificate.
          </p>
          {error && <ErrorNote>{error}</ErrorNote>}
          <div className="btn-row">
            <Button
              variant="primary"
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
