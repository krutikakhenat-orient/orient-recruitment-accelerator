import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
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
  };
});

const mocked = resources as unknown as {
  getInductionStatus: Mock;
  getInductionVideoMeta: Mock;
  fetchInductionVideoBlob: Mock;
  markInductionComplete: Mock;
  fetchInductionCertificate: Mock;
};

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

    // The Certificate card is present but locked (no view-certificate button yet).
    expect(await screen.findByText(/your completion certificate unlocks/i)).toBeInTheDocument();
    expect(screen.getByText("Locked")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /view certificate/i })).not.toBeInTheDocument();
  });

  it("unlocks the certificate after completion is recorded and the status refetches", async () => {
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

    // Wait for the video to be ready so the confirm button is enabled.
    const confirm = await screen.findByRole("button", {
      name: /i have completed the induction/i,
    });
    await waitFor(() => expect(confirm).toBeEnabled());

    // Certificate starts locked.
    expect(screen.getByText("Locked")).toBeInTheDocument();

    await userEvent.click(confirm);

    // Completion was recorded...
    await waitFor(() => expect(mocked.markInductionComplete).toHaveBeenCalledTimes(1));

    // ...and after the status refetch reports completed=true, the certificate unlocks.
    expect(await screen.findByRole("button", { name: /view certificate/i })).toBeInTheDocument();
    expect(screen.getByText("Unlocked")).toBeInTheDocument();

    // The view-certificate action fetches the certificate HTML with the token.
    await userEvent.click(screen.getByRole("button", { name: /view certificate/i }));
    await waitFor(() => expect(mocked.fetchInductionCertificate).toHaveBeenCalledTimes(1));
  });
});
