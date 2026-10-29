import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setAccessToken } from "../src/api/client";
import { downloadResume, resumeDownloadPath } from "../src/api/resources";

/* Focused tests for the authenticated resume download that backs the HR/recruiter
   "Download Resume" button in the Applications tab. The button reuses this exact helper, so
   these cover the security-critical behaviour:
     - the request is keyed by the APPLICATION id (not the candidate id);
     - it sends the bearer token to the existing authenticated endpoint (no duplicate API);
     - a 404 resolves to null so the UI can show a friendly "not available" message;
     - a non-OK/non-404 response raises so the UI can show a friendly failure message;
     - a successful response returns the blob + content type for the browser download.
   No database, schema, or backend behaviour is exercised or changed. */

describe("downloadResume (resume download helper)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    setAccessToken("test-token-123");
  });

  afterEach(() => {
    setAccessToken(null);
  });

  it("builds the download path from the APPLICATION id", () => {
    expect(resumeDownloadPath("app-abc")).toBe(
      "/api/v1/documents/applications/app-abc/resume",
    );
  });

  it("fetches the authenticated endpoint with the bearer token and application id", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        new Response(new Blob(["%PDF-1.4 fake"], { type: "application/pdf" }), {
          status: 200,
          headers: { "Content-Type": "application/pdf" },
        }),
      );

    const result = await downloadResume("application-42", "test-token-123");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const call = fetchMock.mock.calls[0];
    expect(call).toBeDefined();
    const [calledPath, init] = call!;
    expect(calledPath).toBe("/api/v1/documents/applications/application-42/resume");
    const headers = new Headers(init?.headers);
    expect(headers.get("Authorization")).toBe("Bearer test-token-123");
    expect(result).not.toBeNull();
    expect(result?.contentType).toContain("pdf");
  });

  it("returns null on 404 so the UI can show a friendly 'not available' message", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          error: {
            code: "not_found",
            message: "No resume is on file for this application",
            correlation_id: "x",
          },
        }),
        { status: 404, headers: { "Content-Type": "application/json" } },
      ),
    );

    const result = await downloadResume("application-no-resume", "test-token-123");
    expect(result).toBeNull();
  });

  it("throws a readable error on a non-404 failure so the UI can show a friendly message", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          error: {
            code: "permission_denied",
            message: "Actor is not assigned to this campaign",
            correlation_id: "x",
          },
        }),
        { status: 403, headers: { "Content-Type": "application/json" } },
      ),
    );

    await expect(downloadResume("application-forbidden", "test-token-123")).rejects.toThrow(
      /not assigned to this campaign/i,
    );
  });

  it("returns the blob and content type on success", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(new Blob(["resume text"], { type: "text/plain" }), {
        status: 200,
        headers: { "Content-Type": "text/plain; charset=utf-8" },
      }),
    );

    const result = await downloadResume("application-text", "test-token-123");
    expect(result).not.toBeNull();
    expect(result?.contentType).toContain("text/plain");
    // jsdom's Blob does not implement .text(); assert the returned blob's type/size instead.
    expect(result?.blob).toBeInstanceOf(Blob);
    expect(result?.blob.size).toBeGreaterThan(0);
    expect(result?.blob.type).toContain("text/plain");
  });
});
