import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { Bilingual, Problem } from "../types";
import {
  COLUMN_TYPES,
  CONDITION_OPS,
  type Column,
  type Condition,
  type FormSchema,
  type Option,
  QUESTION_TYPES,
  type Question,
  type QuestionType,
  type Section,
  blankText,
  keyFrom,
  text,
} from "./schema";

/** Form Author's editor for the form definition (FR-F2 to FR-F9). Changes are saved by the page. */
export default function Builder({ schema, onChange, problems }: {
  schema: FormSchema;
  onChange: (schema: FormSchema) => void;
  problems: Problem[];
}) {
  const { t } = useTranslation();
  const sections = schema.sections;
  const setSections = (next: Section[]) => onChange({ ...schema, sections: next });
  const allKeys = () => new Set(sections.flatMap((s) => [s.key, ...s.questions.map((q) => q.key)]));
  const addSection = () =>
    setSections([
      ...sections,
      { key: keyFrom("", allKeys(), `section_${sections.length + 1}`), title: blankText(), respondent: "supervisor", questions: [] },
    ]);
  return (
    <div className="builder">
      {sections.map((s, i) => (
        <SectionEditor key={i} section={s} index={i} count={sections.length} allKeys={allKeys}
          problems={problems.filter((p) => p.where === s.key || p.where.startsWith(`${s.key}.`))}
          onChange={(next) => setSections(sections.map((x, j) => (j === i ? next : x)))}
          onMove={(delta) => setSections(move(sections, i, delta))}
          onRemove={() => window.confirm(t("builder.confirmRemoveSection")) && setSections(sections.filter((_, j) => j !== i))} />
      ))}
      <button type="button" onClick={addSection}>{t("builder.addSection")}</button>
    </div>
  );
}

function move<T>(items: T[], index: number, delta: number): T[] {
  const target = index + delta;
  if (target < 0 || target >= items.length) return items;
  const next = [...items];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

function Problems({ problems }: { problems: Problem[] }) {
  const { t } = useTranslation();
  if (!problems.length) return null;
  return (
    <ul className="field-error" role="alert">
      {problems.map((p, i) => (
        <li key={i}>
          <span className="ltr">{p.where}</span>: {t(`builder.problems.${p.code}`, { defaultValue: p.code })}
        </li>
      ))}
    </ul>
  );
}

function TextPair({ label, value, onChange, multiline }: {
  label: string;
  value: Bilingual | null | undefined;
  onChange: (value: Bilingual) => void;
  multiline?: boolean;
}) {
  const { t } = useTranslation();
  const v = value ?? blankText();
  const Input = multiline ? "textarea" : "input";
  return (
    <div className="text-pair">
      <label>
        {label} ({t("lang.en")})
        <Input dir="ltr" lang="en" value={v.en} onChange={(e) => onChange({ ...v, en: e.target.value })} />
      </label>
      <label>
        {label} ({t("lang.ar")})
        <Input dir="rtl" lang="ar" value={v.ar} onChange={(e) => onChange({ ...v, ar: e.target.value })} />
      </label>
    </div>
  );
}

function OrderButtons({ index, count, onMove, onRemove }: {
  index: number;
  count: number;
  onMove: (delta: number) => void;
  onRemove: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="row-actions">
      <button type="button" disabled={index === 0} onClick={() => onMove(-1)} aria-label={t("builder.moveUp")}>↑</button>
      <button type="button" disabled={index === count - 1} onClick={() => onMove(1)} aria-label={t("builder.moveDown")}>↓</button>
      <button type="button" className="danger" onClick={onRemove}>{t("builder.remove")}</button>
    </div>
  );
}

function SectionEditor({ section, index, count, allKeys, problems, onChange, onMove, onRemove }: {
  section: Section;
  index: number;
  count: number;
  allKeys: () => Set<string>;
  problems: Problem[];
  onChange: (s: Section) => void;
  onMove: (delta: number) => void;
  onRemove: () => void;
}) {
  const { t, i18n } = useTranslation();
  const set = (patch: Partial<Section>) => onChange({ ...section, ...patch });
  const questions = section.questions;
  const setQuestions = (next: Question[]) => set({ questions: next });
  const addQuestion = (type: QuestionType) => {
    const q: Question = { key: keyFrom("", allKeys(), `q_${allKeys().size + 1}`), type, label: blankText(), required: false };
    if (type === "single_choice" || type === "multi_choice") q.options = [];
    if (type === "rating") Object.assign(q, { min: 1, max: 5 });
    if (type === "table") q.columns = [];
    setQuestions([...questions, q]);
  };
  return (
    <fieldset className="card builder-section">
      <legend>
        {t("builder.section", { n: index + 1 })}: {text(section.title, i18n.language) || section.key}
      </legend>
      <OrderButtons index={index} count={count} onMove={onMove} onRemove={onRemove} />
      <div className="form-grid">
        <label className="field">
          {t("builder.key")}
          <input dir="ltr" value={section.key} onChange={(e) => set({ key: e.target.value })} />
        </label>
        <label className="field">
          {t("builder.respondent")}
          <select value={section.respondent} onChange={(e) => set({ respondent: e.target.value as Section["respondent"] })}>
            <option value="supervisor">{t("roles.supervisor")}</option>
            <option value="teacher">{t("roles.teacher")}</option>
          </select>
        </label>
      </div>
      <TextPair label={t("builder.title")} value={section.title} onChange={(title) => set({ title })} />
      <TextPair label={t("builder.description")} value={section.description} multiline
        onChange={(description) => set({ description: description.en || description.ar ? description : null })} />
      <Problems problems={problems.filter((p) => p.where === section.key || p.where === `${section.key}.description`)} />
      {questions.map((q, i) => (
        <QuestionEditor key={i} q={q} index={i} count={questions.length} earlier={questions.slice(0, i)}
          problems={problems.filter((p) => p.where === `${section.key}.${q.key}` || p.where.startsWith(`${section.key}.${q.key}.`))}
          onChange={(next) => setQuestions(questions.map((x, j) => (j === i ? next : x)))}
          onMove={(delta) => setQuestions(move(questions, i, delta))}
          onRemove={() => setQuestions(questions.filter((_, j) => j !== i))} />
      ))}
      <label className="field add-question">
        {t("builder.addQuestion")}
        <select value="" onChange={(e) => e.target.value && addQuestion(e.target.value as QuestionType)}>
          <option value="">{t("builder.chooseType")}</option>
          {QUESTION_TYPES.map((type) => (
            <option key={type} value={type}>{t(`builder.types.${type}`)}</option>
          ))}
        </select>
      </label>
    </fieldset>
  );
}

function NumberBox({ label, value, onChange }: { label: string; value: number | null | undefined; onChange: (v: number | null) => void }) {
  return (
    <label className="field">
      {label}
      <input dir="ltr" inputMode="decimal" value={value ?? ""}
        onChange={(e) => onChange(e.target.value === "" || Number.isNaN(Number(e.target.value)) ? null : Number(e.target.value))} />
    </label>
  );
}

function QuestionEditor({ q, index, count, earlier, problems, onChange, onMove, onRemove }: {
  q: Question;
  index: number;
  count: number;
  earlier: Question[];
  problems: Problem[];
  onChange: (q: Question) => void;
  onMove: (delta: number) => void;
  onRemove: () => void;
}) {
  const { t, i18n } = useTranslation();
  const set = (patch: Partial<Question>) => onChange({ ...q, ...patch });
  // New questions open for editing and stay open while typing; the author folds them away.
  const [open, setOpen] = useState(!q.label.en && !q.label.ar);
  // A question the server flags opens, so the problem is visible next to it.
  const flagged = problems.map((p) => p.code).join(",");
  useEffect(() => {
    if (flagged) setOpen(true);
  }, [flagged]);
  return (
    <details className="builder-question" open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>
        {index + 1}. {text(q.label, i18n.language) || q.key} <span className="badge">{t(`builder.types.${q.type}`)}</span>
        {q.required && <span className="badge">{t("builder.required")}</span>}
        {problems.length > 0 && <span className="badge badge-error">{t("builder.hasProblems")}</span>}
      </summary>
      <OrderButtons index={index} count={count} onMove={onMove} onRemove={onRemove} />
      <div className="form-grid">
        <label className="field">
          {t("builder.key")}
          <input dir="ltr" value={q.key} onChange={(e) => set({ key: e.target.value })} />
        </label>
        <label className="field">
          {t("builder.type")}
          <select value={q.type} onChange={(e) => set({ type: e.target.value as QuestionType })}>
            {QUESTION_TYPES.map((type) => (
              <option key={type} value={type}>{t(`builder.types.${type}`)}</option>
            ))}
          </select>
        </label>
        <label className="check">
          <input type="checkbox" checked={!!q.required} onChange={(e) => set({ required: e.target.checked })} />
          {t("builder.required")}
        </label>
      </div>
      <TextPair label={t("builder.label")} value={q.label} onChange={(label) => set({ label })} />
      <TextPair label={t("builder.help")} value={q.help}
        onChange={(help) => set({ help: help.en || help.ar ? help : null })} />
      <div className="form-grid">
        {(q.type === "number" || q.type === "rating") && (
          <>
            <NumberBox label={t("builder.min")} value={q.min} onChange={(min) => set({ min })} />
            <NumberBox label={t("builder.max")} value={q.max} onChange={(max) => set({ max })} />
          </>
        )}
        {(q.type === "short_text" || q.type === "long_text") && (
          <NumberBox label={t("builder.maxLength")} value={q.max_length} onChange={(max_length) => set({ max_length })} />
        )}
        {q.type === "table" && (
          <NumberBox label={t("builder.maxRows")} value={q.max_rows} onChange={(max_rows) => set({ max_rows })} />
        )}
        {q.type === "file" && (
          <NumberBox label={t("builder.maxFiles")} value={q.max_files} onChange={(max_files) => set({ max_files })} />
        )}
        <NumberBox label={t("builder.scoreWeight")} value={q.score_weight} onChange={(score_weight) => set({ score_weight })} />
      </div>
      {(q.type === "single_choice" || q.type === "multi_choice") && (
        <OptionsEditor options={q.options ?? []} onChange={(options) => set({ options })} />
      )}
      {q.type === "table" && <ColumnsEditor columns={q.columns ?? []} onChange={(columns) => set({ columns })} />}
      <ConditionEditor condition={q.visible_if ?? null} earlier={earlier} onChange={(visible_if) => set({ visible_if })} />
      <Problems problems={problems} />
    </details>
  );
}

function OptionsEditor({ options, onChange }: { options: Option[]; onChange: (o: Option[]) => void }) {
  const { t } = useTranslation();
  const update = (i: number, patch: Partial<Option>) => onChange(options.map((o, j) => (j === i ? { ...o, ...patch } : o)));
  return (
    <fieldset className="checks">
      <legend>{t("builder.options")}</legend>
      {options.map((o, i) => (
        <div key={i} className="option-row">
          <input aria-label={t("builder.code")} dir="ltr" value={o.code} onChange={(e) => update(i, { code: e.target.value })} />
          <input aria-label={`${t("builder.label")} (${t("lang.en")})`} dir="ltr" lang="en" value={o.label.en}
            onChange={(e) => update(i, { label: { ...o.label, en: e.target.value } })} />
          <input aria-label={`${t("builder.label")} (${t("lang.ar")})`} dir="rtl" lang="ar" value={o.label.ar}
            onChange={(e) => update(i, { label: { ...o.label, ar: e.target.value } })} />
          <button type="button" className="link" onClick={() => onChange(options.filter((_, j) => j !== i))}>
            {t("builder.remove")}
          </button>
        </div>
      ))}
      <button type="button" onClick={() => onChange([...options, { code: `opt${options.length + 1}`, label: blankText() }])}>
        {t("builder.addOption")}
      </button>
    </fieldset>
  );
}

function ColumnsEditor({ columns, onChange }: { columns: Column[]; onChange: (c: Column[]) => void }) {
  const { t } = useTranslation();
  const update = (i: number, patch: Partial<Column>) => onChange(columns.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  return (
    <fieldset className="checks">
      <legend>{t("builder.columns")}</legend>
      {columns.map((c, i) => (
        <div key={i} className="column-editor">
          <div className="option-row">
            <input aria-label={t("builder.key")} dir="ltr" value={c.key} onChange={(e) => update(i, { key: e.target.value })} />
            <select aria-label={t("builder.type")} value={c.type} onChange={(e) => update(i, { type: e.target.value as Column["type"] })}>
              {COLUMN_TYPES.map((type) => (
                <option key={type} value={type}>{t(`builder.types.${type}`)}</option>
              ))}
            </select>
            <label className="check">
              <input type="checkbox" checked={!!c.required} onChange={(e) => update(i, { required: e.target.checked })} />
              {t("builder.required")}
            </label>
            <button type="button" className="link" onClick={() => onChange(columns.filter((_, j) => j !== i))}>
              {t("builder.remove")}
            </button>
          </div>
          <TextPair label={t("builder.label")} value={c.label} onChange={(label) => update(i, { label })} />
          {c.type === "single_choice" && (
            <OptionsEditor options={c.options ?? []} onChange={(options) => update(i, { options })} />
          )}
        </div>
      ))}
      <button type="button"
        onClick={() => onChange([...columns, { key: `col${columns.length + 1}`, type: "short_text", label: blankText() }])}>
        {t("builder.addColumn")}
      </button>
    </fieldset>
  );
}

/** FR-F6: show a question only when an earlier answer in the same section matches. */
function ConditionEditor({ condition, earlier, onChange }: {
  condition: Condition | null;
  earlier: Question[];
  onChange: (c: Condition | null) => void;
}) {
  const { t, i18n } = useTranslation();
  const usable = earlier.filter((q) => q.type !== "table" && q.type !== "file");
  const source = usable.find((q) => q.key === condition?.question);
  const valueInput = () => {
    if (!condition || !source || condition.op === "answered") return null;
    if (source.type === "yes_no") {
      return (
        <select aria-label={t("builder.value")} value={condition.value === true ? "yes" : condition.value === false ? "no" : ""}
          onChange={(e) => onChange({ ...condition, value: e.target.value === "yes" })}>
          <option value="" />
          <option value="yes">{t("common.yes")}</option>
          <option value="no">{t("common.no")}</option>
        </select>
      );
    }
    if (source.type === "single_choice" || source.type === "multi_choice") {
      const options = source.options ?? [];
      if (condition.op === "in") {
        const chosen = Array.isArray(condition.value) ? (condition.value as string[]) : [];
        return (
          <span className="choices">
            {options.map((o) => (
              <label key={o.code} className="check">
                <input type="checkbox" checked={chosen.includes(o.code)}
                  onChange={(e) => onChange({ ...condition, value: e.target.checked ? [...chosen, o.code] : chosen.filter((c) => c !== o.code) })} />
                {text(o.label, i18n.language) || o.code}
              </label>
            ))}
          </span>
        );
      }
      return (
        <select aria-label={t("builder.value")} value={String(condition.value ?? "")}
          onChange={(e) => onChange({ ...condition, value: e.target.value })}>
          <option value="" />
          {options.map((o) => (
            <option key={o.code} value={o.code}>{text(o.label, i18n.language) || o.code}</option>
          ))}
        </select>
      );
    }
    const numeric = source.type === "number" || source.type === "rating";
    return (
      <input aria-label={t("builder.value")} dir="auto" value={condition.value === undefined || condition.value === null ? "" : String(condition.value)}
        onChange={(e) => onChange({ ...condition, value: numeric && e.target.value !== "" ? Number(e.target.value) : e.target.value })} />
    );
  };
  return (
    <div className="condition">
      <label className="check">
        <input type="checkbox" checked={!!condition} disabled={!usable.length && !condition}
          onChange={(e) => onChange(e.target.checked ? { question: usable[0]?.key ?? "", op: "equals", value: null } : null)} />
        {t("builder.showOnlyIf")}
      </label>
      {condition && (
        <span className="option-row">
          <select aria-label={t("builder.condQuestion")} value={condition.question}
            onChange={(e) => onChange({ ...condition, question: e.target.value, value: null })}>
            {usable.map((q) => (
              <option key={q.key} value={q.key}>{text(q.label, i18n.language) || q.key}</option>
            ))}
          </select>
          <select aria-label={t("builder.condOp")} value={condition.op}
            onChange={(e) => onChange({ ...condition, op: e.target.value as Condition["op"], value: e.target.value === "in" ? [] : null })}>
            {CONDITION_OPS.map((op) => (
              <option key={op} value={op}>{t(`builder.ops.${op}`)}</option>
            ))}
          </select>
          {valueInput()}
        </span>
      )}
      {!usable.length && !condition && <span className="hint">{t("builder.noEarlier")}</span>}
    </div>
  );
}
