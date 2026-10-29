import { describe, expect, it } from "vitest";

import { keyFrom, type Section, visibleAnswers, visibleQuestions } from "./schema";

const t = (en: string) => ({ en, ar: en });

const section: Section = {
  key: "visit",
  title: t("Visit"),
  respondent: "supervisor",
  questions: [
    { key: "met", type: "yes_no", label: t("Met?") },
    { key: "why", type: "short_text", label: t("Why not?"), visible_if: { question: "met", op: "equals", value: false } },
    { key: "why_more", type: "long_text", label: t("More"), visible_if: { question: "why", op: "answered" } },
    { key: "areas", type: "multi_choice", label: t("Areas"), options: [{ code: "a", label: t("A") }, { code: "b", label: t("B") }] },
    { key: "on_b", type: "number", label: t("B count"), visible_if: { question: "areas", op: "in", value: ["b"] } },
  ],
};

describe("visibility matches the server", () => {
  it("shows a question only when an earlier answer matches", () => {
    expect(visibleQuestions(section, {}).map((q) => q.key)).toEqual(["met", "areas"]);
    expect(visibleQuestions(section, { met: false }).map((q) => q.key)).toEqual(["met", "why", "areas"]);
    expect(visibleQuestions(section, { met: false, why: "busy" }).map((q) => q.key)).toContain("why_more");
    expect(visibleQuestions(section, { areas: ["a", "b"] }).map((q) => q.key)).toContain("on_b");
  });

  it("a hidden question's leftover answer neither counts nor unlocks later questions", () => {
    // "why" is hidden once met is true, so "why_more" is hidden too and both answers are dropped.
    const answers = { met: true, why: "busy", why_more: "x", areas: ["a"] };
    expect(visibleQuestions(section, answers).map((q) => q.key)).toEqual(["met", "areas"]);
    expect(visibleAnswers(section, answers)).toEqual({ met: true, areas: ["a"] });
  });
});

describe("keys", () => {
  it("are made from the English label and kept unique", () => {
    expect(keyFrom("Met the principal?", new Set(), "q_1")).toBe("met_the_principal");
    expect(keyFrom("Met the principal?", new Set(["met_the_principal"]), "q_1")).toBe("met_the_principal_2");
    expect(keyFrom("هل قابلت؟", new Set(), "q_3")).toBe("q_3");
  });
});
