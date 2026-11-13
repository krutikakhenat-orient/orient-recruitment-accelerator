import { describe, expect, it } from "vitest";

import { STAGES, candidatePath, nextStepFor, stageFor } from "../src/lib/candidateStage";

describe("candidate stages", () => {
  it("maps every application state to one of the seven stages, in order", () => {
    expect(STAGES.map((s) => s.number)).toEqual([1, 2, 3, 4, 5, 6, 7]);
    expect(stageFor("submitted").key).toBe("applied");
    expect(stageFor("manual_review").key).toBe("review");
    expect(stageFor("interview_recommended").key).toBe("shortlisted");
    expect(stageFor("checked_in").key).toBe("interviewing");
    // Assessed but not yet checked out is still with the panel.
    expect(stageFor("assessed").key).toBe("interviewing");
    expect(stageFor("checked_out").key).toBe("decision");
    expect(stageFor("selected").key).toBe("outcome");
    expect(stageFor("unknown_future_state").key).toBe("applied");
  });

  it("says what happens next and links to where it happens", () => {
    expect(nextStepFor("submitted").target).toEqual({ kind: "screen" });
    expect(nextStepFor("manual_review").target).toEqual({ kind: "page", to: "/reviews" });
    expect(nextStepFor("interview_recommended").target).toEqual({ kind: "candidate", section: "interviews" });
    expect(nextStepFor("checked_out").target).toEqual({ kind: "candidate", section: "decision" });
    expect(nextStepFor("selected").target).toEqual({ kind: "page", to: "/offers" });
    expect(nextStepFor("rejected").target).toEqual({ kind: "none" });
  });

  it("never labels the person in the wording", () => {
    for (const state of ["rejected", "no_show", "withdrawn", "manual_review"]) {
      const text = nextStepFor(state).text.toLowerCase();
      expect(text).not.toMatch(/unfit|bad candidate|reject(ed)? candidate/);
    }
  });

  it("builds candidate page links with an optional section", () => {
    expect(candidatePath("c1", "a1")).toBe("/campaigns/c1/candidates/a1");
    expect(candidatePath("c1", "a1", "decision")).toBe("/campaigns/c1/candidates/a1#decision");
  });
});
