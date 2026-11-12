// "We are starting up": while the paused database resumes, the app shows a branded message
// (never a blank page) and requests retry by themselves. SYNTHETIC data only.

import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";

import { apiFetch } from "../src/api/client";
import { StartupGate } from "../src/components/StartupGate";
import { getStartupState, markReady, startupFetch } from "../src/lib/startup";

function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

const starting = (): Response =>
  json(
    { error: { code: "service_starting", message: "We are starting up.", correlation_id: "c1" } },
    503,
    { "Retry-After": "1" },
  );

describe("StartupGate", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    markReady();
    window.history.pushState({}, "", "/");
  });

  it("opens the app without a startup message when the backend is ready", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ status: "ready" }));
    render(
      <StartupGate>
        <p>App content</p>
      </StartupGate>,
    );
    expect(await screen.findByText("App content")).toBeInTheDocument();
    expect(screen.queryByText(/we are starting up/i)).not.toBeInTheDocument();
  });

  it("shows 'We are starting up' while the database resumes, then the app", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(starting())
      .mockResolvedValueOnce(json({ status: "ready" }));
    render(
      <StartupGate>
        <p>App content</p>
      </StartupGate>,
    );
    const status = await screen.findByRole("status");
    await waitFor(() => expect(status).toHaveTextContent(/we are starting up/i));
    expect(screen.queryByText("App content")).not.toBeInTheDocument();
    expect(await screen.findByText("App content", {}, { timeout: 4000 })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/system/status", expect.anything());
  });

  it("never locks users out if the status endpoint is missing (older backend)", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ detail: "Not Found" }, 404));
    render(
      <StartupGate>
        <p>App content</p>
      </StartupGate>,
    );
    expect(await screen.findByText("App content")).toBeInTheDocument();
  });

  it("does not hold back pages that need no backend", () => {
    window.history.pushState({}, "", "/guide");
    const fetchMock = vi.spyOn(globalThis, "fetch");
    render(
      <StartupGate>
        <p>Guide content</p>
      </StartupGate>,
    );
    expect(screen.getByText("Guide content")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("requests while the database resumes", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    markReady();
  });
  afterEach(() => markReady());

  it("apiFetch waits, retries and returns the data; the banner state clears", async () => {
    const states: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => {
      states.push(getStartupState());
      return states.length === 1 ? starting() : json({ id: "synthetic-1" });
    });
    const result = await apiFetch("/api/v1/projects/x", z.object({ id: z.string() }));
    expect(result).toEqual({ id: "synthetic-1" });
    expect(states).toEqual(["ready", "starting"]); // banner shown during the retry
    expect(getStartupState()).toBe("ready");
  });

  it("startupFetch does not retry other 503 errors", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        json({ error: { code: "service_unavailable", message: "x", correlation_id: null } }, 503),
      );
    const resp = await startupFetch("/api/v1/projects");
    expect(resp.status).toBe(503);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(getStartupState()).toBe("ready");
  });
});
