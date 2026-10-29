import { useEffect, useRef, useState, type ReactNode } from "react";
import { useParams } from "react-router-dom";

import { downloadResume } from "../api/resources";
import { useAuth } from "../app/auth-context";
import { Card, ErrorNote, Loading } from "../components/ui";

/* Landing page for the "Download Resume" hyperlink embedded in the Excel export.

   The export cannot carry an Authorization header, so instead of a public/signed file URL
   (which this product forbids) the hyperlink points here, at an authenticated SPA route.
   RequireAuth guarantees the user is signed in before this renders (sending them through
   login first and back here afterwards). Once here, we fetch the ORIGINAL resume for the
   specific application using the bearer token and trigger a browser save. The actual
   object-level authorisation is still enforced server-side; this page only orchestrates the
   authenticated fetch for the exact candidate named in the link. */
export function ResumeDownloadPage(): ReactNode {
  const { applicationId = "" } = useParams();
  const { token } = useAuth();
  const [state, setState] = useState<"loading" | "done" | "missing" | "error">("loading");
  const [message, setMessage] = useState<string>("");
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return; // guard React 18 StrictMode double-invoke
    started.current = true;
    let objectUrl: string | null = null;

    // Original file only (no extracted-text fallback): the export link promises the real
    // uploaded resume, so a missing original must read as "unavailable", not silently a
    // text substitute.
    downloadResume(applicationId, token() ?? "")
      .then((res) => {
        if (res === null) {
          setState("missing");
          return;
        }
        const ext = res.contentType.includes("pdf")
          ? "pdf"
          : res.contentType.includes("word")
            ? "docx"
            : res.contentType.includes("text/plain")
              ? "txt"
              : "bin";
        objectUrl = URL.createObjectURL(res.blob);
        const a = document.createElement("a");
        a.href = objectUrl;
        a.download = `resume-${applicationId}.${ext}`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setState("done");
      })
      .catch((e: unknown) => {
        setMessage(e instanceof Error ? e.message : "Could not download the resume.");
        setState("error");
      });

    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [applicationId, token]);

  return (
    <Card title="Candidate resume download">
      {state === "loading" && <Loading label="Preparing the resume download…" />}
      {state === "done" && (
        <p className="subtle">
          The resume download has started. If nothing happened, your browser may have blocked
          it — reload this page to try again.
        </p>
      )}
      {state === "missing" && (
        <p className="subtle">
          The original resume file is not available for this candidate. It may not have been
          uploaded, or the stored file is unavailable.
        </p>
      )}
      {state === "error" && <ErrorNote>{message}</ErrorNote>}
    </Card>
  );
}
