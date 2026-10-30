import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";

import { setAccessToken } from "../api/client";
import * as resources from "../api/resources";
import { AuthProvider } from "../app/auth-context";
import { EmployeePage } from "./EmployeePage";

/* Tests for the employee induction dashboard. They mock the induction resource wrappers and
   prove the two-feature behaviour:
     - the certificate action is LOCKED while completion status is false, and
     - it UNLOCKS after markInductionComplete resolves and the refetched status reports
       completed=true. */

// Mock only the induction wrappers the page uses; leave the rest of the module intact.
vi.mock("../api/resources", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/resources")>();
  return {
    ...actual,
    getInductionStatus: vi.fn(),
    getInductionVideoMeta: vi.fn(),
    fetchInductionVideoBlob: vi.fn(),
    markInductionComplete: vi.fn(),
    fetchInductionCertificate: vi.fn(),
    downloadInductionCertificate: vi.fn(),
  };
});

const mocked = resources as unknown as {
  getInductionStatus: Mock;
  getInductionVideoMeta: Mock;
  fetchInductionVideoBlob: Mock;
  markInductionComplete: Mock;
  fetchInductionCertificate: Mock;
  downloadInductionCertificate: Mock;
};

/* jsdom's <video> has no real media pipeline (duration is NaN, currentTime is a plain
   writable field, and no events fire on their own). These helpers simulate genuine,
   contiguous playback to the end so the full-watch enforcement can be exercised. */
function setVideoDuration(video: HTMLVideoElement, seconds: number): void {
  Object.defineProperty(video, "duration", { configurable: true, value: seconds });
  fireEvent.loadedMetadata(video);
}

// Simulate contiguous playback in small steps (<= the component's playback-step threshold),
// firing a timeupdate after each step, exactly as a playing <video> would.
function playThrough(video: HTMLVideoElement, duration: number, stepSeconds = 1): void {
  let t = 0;
  while (t < duration) {
    t = Math.min(duration, t + stepSeconds);
    video.currentTime = t;
    fireEvent.timeUpdate(video);
  }
}

const VIDEO_META = {
  id: "video-1",
  title: "Company induction",
  description: "Watch this before you start.",
  content_type: "video/mp4",
};

function renderPage(): void {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AuthProvider>
          <EmployeePage />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("EmployeePage induction dashboard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setAccessToken("tok");
    // Stub object-URL helpers (not implemented in jsdom) used to play the video / open the
    // certificate.
    globalThis.URL.createObjectURL = vi.fn(() => "blob:mock");
    globalThis.URL.revokeObjectURL = vi.fn();
    vi.spyOn(globalThis, "open").mockImplementation(() => null);

    mocked.getInductionVideoMeta.mockResolvedValue(VIDEO_META);
    mocked.fetchInductionVideoBlob.mockResolvedValue({
      blob: new Blob([new Uint8Array([0, 0, 0, 0])], { type: "video/mp4" }),
      contentType: "video/mp4",
    });
    mocked.fetchInductionCertificate.mockResolvedValue("<html><body>Certificate</body></html>");
    mocked.downloadInductionCertificate.mockResolvedValue({
      blob: new Blob(["<html><body>Certificate</body></html>"], { type: "text/html" }),
      filename: "induction-certificate.html",
    });
  });

  afterEach(() => {
    setAccessToken(null);
  });

  it("locks the certificate action until the induction is completed", async () => {
    mocked.getInductionStatus.mockResolvedValue({
      has_video: true,
      completed: false,
      completed_at: null,
    });

    renderPage();

    // The Certificate card is present but locked: the message tells the user to complete the
    // induction video first, and there is no view/download action yet.
    expect(
      await screen.findByText(/complete the induction video to unlock your certificate/i),
    ).toBeInTheDocument();
    expect(screen.getByText("Locked")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /view certificate/i })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /download certificate/i }),
    ).not.toBeInTheDocument();
  });

  it("keeps completion disabled until the whole video is watched", async () => {
    mocked.getInductionStatus.mockResolvedValue({
      has_video: true,
      completed: false,
      completed_at: null,
    });

    renderPage();

    // The complete button exists but is disabled while nothing (or only part) is watched.
    const complete = await screen.findByRole("button", {
      name: /mark induction complete/i,
    });
    expect(complete).toBeDisabled();
    expect(screen.getByText(/watch the full video to unlock/i)).toBeInTheDocument();

    const video = screen.getByLabelText(/induction video/i) as HTMLVideoElement;
    setVideoDuration(video, 10);

    // Watching only part of the video must NOT unlock completion.
    playThrough(video, 4);
    expect(complete).toBeDisabled();

    // Watching the rest contiguously reaches the end and unlocks completion.
    playThrough(video, 10);
    await waitFor(() => expect(complete).toBeEnabled());
  });

  it("snaps a forward seek back so the scrubber cannot shortcut completion", async () => {
    mocked.getInductionStatus.mockResolvedValue({
      has_video: true,
      completed: false,
      completed_at: null,
    });

    renderPage();

    const complete = await screen.findByRole("button", {
      name: /mark induction complete/i,
    });
    const video = screen.getByLabelText(/induction video/i) as HTMLVideoElement;
    setVideoDuration(video, 10);

    // Try to jump straight to the end: the component snaps currentTime back to the watched
    // marker (0) and completion stays locked.
    video.currentTime = 10;
    fireEvent.seeking(video);
    expect(video.currentTime).toBe(0);
    expect(complete).toBeDisabled();
  });

  it("unlocks the certificate after a full watch is recorded and the status refetches", async () => {
    // First status load: not completed. After completion, the refetch returns completed=true.
    mocked.getInductionStatus
      .mockResolvedValueOnce({ has_video: true, completed: false, completed_at: null })
      .mockResolvedValue({
        has_video: true,
        completed: true,
        completed_at: "2026-01-01T00:00:00Z",
      });
    mocked.markInductionComplete.mockResolvedValue({
      completed: true,
      completed_at: "2026-01-01T00:00:00Z",
    });

    renderPage();

    const complete = await screen.findByRole("button", {
      name: /mark induction complete/i,
    });

    // Certificate starts locked.
    expect(screen.getByText("Locked")).toBeInTheDocument();

    // Watch the whole video, then the complete button enables.
    const video = screen.getByLabelText(/induction video/i) as HTMLVideoElement;
    setVideoDuration(video, 10);
    playThrough(video, 10);
    await waitFor(() => expect(complete).toBeEnabled());

    await userEvent.click(complete);

    // Completion was recorded...
    await waitFor(() => expect(mocked.markInductionComplete).toHaveBeenCalledTimes(1));

    // ...and after the status refetch reports completed=true, the certificate unlocks with
    // both a download and a view action.
    expect(
      await screen.findByRole("button", { name: /download certificate/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /view certificate/i })).toBeInTheDocument();
    expect(screen.getByText("Unlocked")).toBeInTheDocument();

    // The download action fetches the certificate bytes with the token and triggers a save.
    await userEvent.click(screen.getByRole("button", { name: /download certificate/i }));
    await waitFor(() => expect(mocked.downloadInductionCertificate).toHaveBeenCalledTimes(1));
  });
});
