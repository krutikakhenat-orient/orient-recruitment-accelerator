import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setAccessToken } from "../src/api/client";
import { App } from "../src/app/App";
import { AuthProvider } from "../src/app/auth-context";
import { ToastProvider } from "../src/components/toast";

/* End-to-end-ish routing tests for the Excel "Download Resume" deep link.

   The hyperlink in the export opens {app_base_url}/resume/{applicationId}. These tests
   drive the REAL <App/> router at that path and prove:
     1. When authenticated, the route renders ResumeDownloadPage (NOT a redirect to
        /campaigns or the dashboard) and fetches the correct application's resume.
     2. When unauthenticated, the user is sent to login and, after signing in, is returned
        to the SAME /resume/{applicationId} route (destination preserved through login),
        then the correct resume is fetched.
   This guards the reported bug where the Excel link landed on the applications page. */

const APP_ID = "11111111-2222-3333-4444-555555555555";
const ME = {
  user_id: "u1",
  organisation_id: "o1",
  email: "recruiter.admin@example.com",
  role_names: ["recruiter_admin"],
  permissions: ["candidate.view", "campaign.edit"],
  assigned_campaign_ids: ["c1"],
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function fileResponse(): Response {
  return new Response(new Blob([new Uint8Array([1, 2, 3, 4])]), {
    status: 200,
    headers: {
      "Content-Type": "application/pdf",
      "X-Resume-Source": "original-file",
    },
  });
}

function renderAppAt(path: string): void {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <AuthProvider>
          <ToastProvider>
            <App />
          </ToastProvider>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Excel Download Resume deep link → /resume/:applicationId", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    setAccessToken(null);
    // A fresh object-URL + click are used by the page; stub them for jsdom.
    globalThis.URL.createObjectURL = vi.fn(() => "blob:mock");
    globalThis.URL.revokeObjectURL = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  });
  afterEach(() => setAccessToken(null));

  it("downloads the correct candidate's resume when already authenticated", async () => {
    setAccessToken("tok"); // simulate an authenticated session in this tab
    const calls: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const u = typeof input === "string" ? input : input.toString();
      calls.push(u);
      if (u.endsWith("/api/v1/auth/me")) return Promise.resolve(jsonResponse(ME));
      if (u.includes(`/api/v1/documents/applications/${APP_ID}/resume`)) {
        return Promise.resolve(fileResponse());
      }
      return Promise.resolve(jsonResponse({}, 200));
    });

    renderAppAt(`/resume/${APP_ID}`);

    // The resume-download landing page renders (not a redirect to campaigns/dashboard)...
    expect(await screen.findByText(/candidate resume download/i)).toBeInTheDocument();
    // ...and it fetched EXACTLY this application's resume, original-file only (no fallback).
    await waitFor(() => {
      expect(
        calls.some((u) => u.endsWith(`/api/v1/documents/applications/${APP_ID}/resume`)),
      ).toBe(true);
    });
    // No extracted-text fallback flag on the HR/export download path.
    expect(calls.some((u) => u.includes("fallback=text"))).toBe(false);
  });

  it("preserves the resume destination through login when unauthenticated", async () => {
    const calls: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const u = typeof input === "string" ? input : input.toString();
      calls.push(u);
      if (u.endsWith("/api/v1/auth/login")) {
        return Promise.resolve(
          jsonResponse({ access_token: "tok", refresh_token: "r", token_type: "bearer" }),
        );
      }
      if (u.endsWith("/api/v1/auth/me")) return Promise.resolve(jsonResponse(ME));
      if (u.includes(`/api/v1/documents/applications/${APP_ID}/resume`)) {
        return Promise.resolve(fileResponse());
      }
      return Promise.resolve(jsonResponse({}, 200));
    });

    renderAppAt(`/resume/${APP_ID}`);

    // Unauthenticated: we are sent to the sign-in page.
    expect(await screen.findByRole("heading", { name: /sign in/i })).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText(/email/i), "recruiter.admin@example.com");
    await userEvent.type(screen.getByLabelText(/password/i), "pw-correct-horse");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

    // After login we are returned to the SAME resume route and fetch THIS candidate's file.
    expect(await screen.findByText(/candidate resume download/i)).toBeInTheDocument();
    await waitFor(() => {
      expect(
        calls.some((u) => u.endsWith(`/api/v1/documents/applications/${APP_ID}/resume`)),
      ).toBe(true);
    });
  });
});
