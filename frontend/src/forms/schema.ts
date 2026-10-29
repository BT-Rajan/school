/**
 * Form definitions as the server stores them (backend/app/forms/schema.py).
 * The server alone decides whether answers are valid; the visibility rule is
 * repeated here only so the screen hides the same questions the server ignores.
 */

import type { Bilingual } from "../types";

export const QUESTION_TYPES = [
  "short_text",
  "long_text",
  "number",
  "single_choice",
  "multi_choice",
  "date",
  "yes_no",
  "rating",
  "table",
  "file",
] as const;
export type QuestionType = (typeof QUESTION_TYPES)[number];

export const COLUMN_TYPES = ["short_text", "number", "date", "yes_no", "single_choice"] as const;
export type ColumnType = (typeof COLUMN_TYPES)[number];

export const CONDITION_OPS = ["equals", "not_equals", "in", "answered"] as const;
export type ConditionOp = (typeof CONDITION_OPS)[number];

export interface Option {
  code: string;
  label: Bilingual;
}

export interface Condition {
  question: string;
  op: ConditionOp;
  value?: unknown;
}

export interface Column {
  key: string;
  type: ColumnType;
  label: Bilingual;
  required?: boolean;
  options?: Option[];
}

export interface Question {
  key: string;
  type: QuestionType;
  label: Bilingual;
  help?: Bilingual | null;
  required?: boolean;
  min?: number | null;
  max?: number | null;
  max_length?: number | null;
  max_rows?: number | null;
  max_files?: number | null;
  options?: Option[];
  columns?: Column[];
  visible_if?: Condition | null;
  score_weight?: number | null;
}

export type Respondent = "supervisor" | "teacher";

export interface Section {
  key: string;
  title: Bilingual;
  description?: Bilingual | null;
  respondent: Respondent;
  questions: Question[];
}

export interface FormSchema {
  sections: Section[];
}

export type Answers = Record<string, unknown>;

export function text(value: Bilingual | null | undefined, locale: string): string {
  if (!value) return "";
  return (locale === "ar" ? value.ar : value.en) || value.en || value.ar || "";
}

function empty(value: unknown): boolean {
  return (
    value === undefined ||
    value === null ||
    value === "" ||
    (Array.isArray(value) && value.length === 0) ||
    (typeof value === "object" && !Array.isArray(value) && Object.keys(value as object).length === 0)
  );
}

function same(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/** Same rule as the server's _visible: conditions look at earlier, visible answers in the section. */
export function visibleQuestions(section: Section, answers: Answers): Question[] {
  const accepted: Answers = {};
  const shown: Question[] = [];
  for (const q of section.questions) {
    const c = q.visible_if;
    let visible = true;
    if (c) {
      const given = accepted[c.question];
      if (c.op === "answered") visible = !empty(given);
      else if (c.op === "equals") visible = same(given, c.value);
      else if (c.op === "not_equals") visible = !same(given, c.value);
      else {
        const values = Array.isArray(c.value) ? c.value : [c.value];
        visible = Array.isArray(given) ? given.some((g) => values.some((v) => same(v, g))) : values.some((v) => same(v, given));
      }
    }
    if (!visible) continue;
    shown.push(q);
    if (!empty(answers[q.key])) accepted[q.key] = answers[q.key];
  }
  return shown;
}

/** Answers to hidden questions are not sent, as the server would drop them anyway. */
export function visibleAnswers(section: Section, answers: Answers): Answers {
  const out: Answers = {};
  for (const q of visibleQuestions(section, answers)) {
    if (answers[q.key] !== undefined) out[q.key] = answers[q.key];
  }
  return out;
}

export function blankText(): Bilingual {
  return { en: "", ar: "" };
}

/** A key from an English label: "Met the principal?" -> "met_the_principal". */
export function keyFrom(label: string, taken: Set<string>, fallback: string): string {
  let base = label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 40);
  if (!/^[a-z]/.test(base)) base = fallback;
  let key = base;
  for (let i = 2; taken.has(key); i++) key = `${base}_${i}`;
  return key;
}
