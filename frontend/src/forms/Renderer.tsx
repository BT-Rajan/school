import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, openLink, uploadFile } from "../api";
import { DateField, ErrorMessage, useAction } from "../components";
import { formatDate } from "../format";
import type { Problem, UploadedFile } from "../types";
import { type Answers, type Column, type Option, type Question, type Section, text, visibleQuestions } from "./schema";

type Change = (key: string, value: unknown) => void;

interface Props {
  section: Section;
  answers: Answers;
  onChange?: (answers: Answers) => void;
  /** Form text language. Defaults to the screen's language; the builder preview can pick either. */
  locale?: string;
  /** Problems from the server, with "where" as "<section>.<question>[.<row>.<column>]". */
  problems?: Problem[];
}

/** Draws one section of a form from its definition (FR-F1). Read-only when there is no onChange. */
export default function SectionView({ section, answers, onChange, locale, problems = [] }: Props) {
  const { i18n } = useTranslation();
  const lang = locale ?? i18n.language;
  const t = i18n.getFixedT(lang);
  const readOnly = !onChange;
  const set: Change = (key, value) => onChange?.({ ...answers, [key]: value });
  const problemsFor = (key: string) =>
    problems.filter((p) => p.where === `${section.key}.${key}` || p.where.startsWith(`${section.key}.${key}.`));
  return (
    <section className="form-section" lang={lang} dir={lang === "ar" ? "rtl" : "ltr"}>
      <h2 dir="auto">{text(section.title, lang)}</h2>
      {section.description && <p className="hint" dir="auto">{text(section.description, lang)}</p>}
      {visibleQuestions(section, answers).map((q) => (
        <QuestionView key={q.key} q={q} value={answers[q.key]} set={set} lang={lang} readOnly={readOnly}
          problems={problemsFor(q.key)} sectionKey={section.key} t={t} />
      ))}
    </section>
  );
}

type T = ReturnType<ReturnType<typeof useTranslation>["i18n"]["getFixedT"]>;

function ProblemText({ problems, t }: { problems: Problem[]; t: T }) {
  if (!problems.length) return null;
  return (
    <div className="field-error" role="alert">
      {problems.map((p, i) => (
        <div key={i}>{t(`answers.${p.code}`, { defaultValue: t("answers.invalid") })}</div>
      ))}
    </div>
  );
}

function QuestionView({ q, value, set, lang, readOnly, problems, sectionKey, t }: {
  q: Question;
  value: unknown;
  set: Change;
  lang: string;
  readOnly: boolean;
  problems: Problem[];
  sectionKey: string;
  t: T;
}) {
  const id = useId();
  const label = `${text(q.label, lang)}${q.required ? " *" : ""}`;
  const help = q.help ? text(q.help, lang) : "";
  const invalid = problems.length > 0;
  const grouped = ["single_choice", "multi_choice", "yes_no", "rating", "table", "file", "date"].includes(q.type);
  const body = () => {
    if (readOnly) return <ReadOnlyAnswer q={q} value={value} lang={lang} t={t} />;
    switch (q.type) {
      case "long_text":
        return (
          <textarea id={id} rows={4} dir="auto" maxLength={q.max_length ?? 5000} aria-invalid={invalid}
            value={typeof value === "string" ? value : ""} onChange={(e) => set(q.key, e.target.value)} />
        );
      case "number":
        return <NumberInput id={id} q={q} value={value} set={set} invalid={invalid} />;
      case "date":
        return <DateField label="" value={typeof value === "string" ? value : ""} onChange={(v) => set(q.key, v)} />;
      case "single_choice":
        return <Choices name={id} options={q.options ?? []} lang={lang} value={value} onChange={(v) => set(q.key, v)} />;
      case "multi_choice":
        return <MultiChoices options={q.options ?? []} lang={lang} value={value} onChange={(v) => set(q.key, v)} />;
      case "yes_no":
        return (
          <Choices name={id} lang={lang} value={value} onChange={(v) => set(q.key, v)}
            options={[
              { code: true, label: t("common.yes") },
              { code: false, label: t("common.no") },
            ]} />
        );
      case "rating":
        return <Rating q={q} value={value} set={set} />;
      case "table":
        return <TableInput q={q} value={value} set={set} lang={lang} t={t} problems={problems} sectionKey={sectionKey} />;
      case "file":
        return <FileInput q={q} value={value} set={set} t={t} />;
      default:
        return (
          <input id={id} dir="auto" maxLength={q.max_length ?? 500} aria-invalid={invalid}
            value={typeof value === "string" ? value : ""} onChange={(e) => set(q.key, e.target.value)} />
        );
    }
  };
  if (grouped || readOnly) {
    return (
      <fieldset className="question" aria-invalid={invalid}>
        <legend dir="auto">{label}</legend>
        {help && <div className="hint" dir="auto">{help}</div>}
        {body()}
        <ProblemText problems={problems} t={t} />
      </fieldset>
    );
  }
  return (
    <div className="question field">
      <label htmlFor={id} dir="auto">{label}</label>
      {help && <div className="hint" dir="auto">{help}</div>}
      {body()}
      <ProblemText problems={problems} t={t} />
    </div>
  );
}

function NumberInput({ id, q, value, set, invalid }: { id: string; q: Question; value: unknown; set: Change; invalid: boolean }) {
  // Kept as typed text so "1." can be entered; sent as a number once it is one.
  const [draft, setDraft] = useState(value === undefined || value === null ? "" : String(value));
  return (
    <input id={id} dir="ltr" inputMode="decimal" aria-invalid={invalid} value={draft}
      min={q.min ?? undefined} max={q.max ?? undefined}
      onChange={(e) => {
        const raw = e.target.value.replace(",", ".");
        setDraft(raw);
        if (raw.trim() === "") set(q.key, null);
        else if (!Number.isNaN(Number(raw))) set(q.key, Number(raw));
        else set(q.key, raw);
      }} />
  );
}

function Choices<V extends string | boolean>({ name, options, lang, value, onChange }: {
  name: string;
  options: { code: V; label: Option["label"] | string }[];
  lang: string;
  value: unknown;
  onChange: (value: V | null) => void;
}) {
  return (
    <div className="choices">
      {options.map((o) => (
        <label key={String(o.code)} className="check">
          <input type="radio" name={name} checked={value === o.code} onChange={() => onChange(o.code)} />
          {typeof o.label === "string" ? o.label : text(o.label, lang)}
        </label>
      ))}
    </div>
  );
}

function MultiChoices({ options, lang, value, onChange }: {
  options: Option[];
  lang: string;
  value: unknown;
  onChange: (value: string[]) => void;
}) {
  const chosen = Array.isArray(value) ? (value as string[]) : [];
  return (
    <div className="choices">
      {options.map((o) => (
        <label key={o.code} className="check">
          <input type="checkbox" checked={chosen.includes(o.code)}
            onChange={(e) => onChange(e.target.checked ? [...chosen, o.code] : chosen.filter((c) => c !== o.code))} />
          {text(o.label, lang)}
        </label>
      ))}
    </div>
  );
}

function Rating({ q, value, set }: { q: Question; value: unknown; set: Change }) {
  const low = q.min ?? 1;
  const high = q.max ?? 5;
  const steps = Array.from({ length: Math.max(0, high - low + 1) }, (_, i) => low + i);
  return (
    <div className="rating" role="radiogroup">
      {steps.map((n) => (
        <button key={n} type="button" role="radio" aria-checked={value === n} className={value === n ? "primary" : ""}
          onClick={() => set(q.key, value === n ? null : n)}>
          {n}
        </button>
      ))}
    </div>
  );
}

function CellInput({ column, value, onChange, lang, t }: {
  column: Column;
  value: unknown;
  onChange: (value: unknown) => void;
  lang: string;
  t: T;
}) {
  const label = text(column.label, lang);
  switch (column.type) {
    case "number":
      return (
        <input aria-label={label} dir="ltr" inputMode="decimal" value={value === undefined || value === null ? "" : String(value)}
          onChange={(e) => onChange(e.target.value === "" ? null : Number.isNaN(Number(e.target.value)) ? e.target.value : Number(e.target.value))} />
      );
    case "yes_no":
      return (
        <select aria-label={label} value={value === true ? "yes" : value === false ? "no" : ""}
          onChange={(e) => onChange(e.target.value === "" ? null : e.target.value === "yes")}>
          <option value="" />
          <option value="yes">{t("common.yes")}</option>
          <option value="no">{t("common.no")}</option>
        </select>
      );
    case "single_choice":
      return (
        <select aria-label={label} value={typeof value === "string" ? value : ""} onChange={(e) => onChange(e.target.value || null)}>
          <option value="" />
          {(column.options ?? []).map((o) => (
            <option key={o.code} value={o.code}>{text(o.label, lang)}</option>
          ))}
        </select>
      );
    case "date":
      return <DateField label="" value={typeof value === "string" ? value : ""} onChange={onChange} />;
    default:
      return <input aria-label={label} dir="auto" value={typeof value === "string" ? value : ""} onChange={(e) => onChange(e.target.value)} />;
  }
}

function TableInput({ q, value, set, lang, t, problems, sectionKey }: {
  q: Question;
  value: unknown;
  set: Change;
  lang: string;
  t: T;
  problems: Problem[];
  sectionKey: string;
}) {
  const rows = Array.isArray(value) ? (value as Record<string, unknown>[]) : [];
  const columns = q.columns ?? [];
  const update = (index: number, key: string, cell: unknown) =>
    set(q.key, rows.map((row, i) => (i === index ? { ...row, [key]: cell } : row)));
  const full = q.max_rows != null && rows.length >= q.max_rows;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key}>{text(c.label, lang)}{c.required ? " *" : ""}</th>
            ))}
            <th><span className="visually-hidden">{t("common.actions")}</span></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td key={c.key}
                  className={problems.some((p) => p.where === `${sectionKey}.${q.key}.${i}.${c.key}`) ? "cell-invalid" : ""}>
                  <CellInput column={c} value={row[c.key]} lang={lang} t={t} onChange={(v) => update(i, c.key, v)} />
                </td>
              ))}
              <td>
                <button type="button" className="link" onClick={() => set(q.key, rows.filter((_, j) => j !== i))}>
                  {t("forms.removeRow")}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button type="button" disabled={full} onClick={() => set(q.key, [...rows, {}])}>
        {t("forms.addRow")}
      </button>
    </div>
  );
}

function FileInput({ q, value, set, t }: { q: Question; value: unknown; set: Change; t: T }) {
  const ids = Array.isArray(value) ? (value as number[]) : [];
  const [names, setNames] = useState<Record<number, string>>({});
  const upload = useAction(async (files: File[]) => {
    const added: number[] = [];
    for (const file of files) {
      const stored = await uploadFile<UploadedFile>(file);
      added.push(stored.id);
      setNames((n) => ({ ...n, [stored.id]: stored.name }));
    }
    set(q.key, [...ids, ...added]);
  });
  const limit = q.max_files ?? 5;
  return (
    <div>
      <ul className="file-list">
        {ids.map((id) => (
          <li key={id}>
            <FileName id={id} name={names[id]} t={t} />
            <button type="button" className="link" onClick={() => set(q.key, ids.filter((x) => x !== id))}>
              {t("forms.removeFile")}
            </button>
          </li>
        ))}
      </ul>
      {ids.length < limit && (
        <label className="button-like">
          {upload.busy ? t("common.loading") : t("forms.attach")}
          <input type="file" className="visually-hidden" multiple accept="application/pdf,image/*"
            disabled={upload.busy}
            onChange={(e) => {
              const files = Array.from(e.target.files ?? []);
              e.target.value = "";
              if (files.length) void upload.run(files);
            }} />
        </label>
      )}
      <ErrorMessage error={upload.error} />
    </div>
  );
}

function FileName({ id, name, t }: { id: number; name?: string; t: T }) {
  const open = useAction(() =>
    openLink(() => api<{ url: string }>(`/api/files/${id}/link`, { method: "POST", body: { disposition: "inline" } })),
  );
  return (
    <>
      <button type="button" className="link" onClick={() => void open.run()}>
        {name ?? t("forms.fileNumber", { id })}
      </button>
      <ErrorMessage error={open.error} />
    </>
  );
}

function ReadOnlyAnswer({ q, value, lang, t }: { q: Question; value: unknown; lang: string; t: T }) {
  if (value === undefined || value === null || value === "" || (Array.isArray(value) && value.length === 0)) {
    return <p className="hint">{t("forms.noAnswer")}</p>;
  }
  const option = (code: unknown, options: Option[] = []) => {
    const found = options.find((o) => o.code === code);
    return found ? text(found.label, lang) : String(code);
  };
  switch (q.type) {
    case "yes_no":
      return <p>{value ? t("common.yes") : t("common.no")}</p>;
    case "date":
      return <p className="ltr">{formatDate(String(value))}</p>;
    case "single_choice":
      return <p>{option(value, q.options)}</p>;
    case "multi_choice":
      return <p>{(value as unknown[]).map((v) => option(v, q.options)).join("، ")}</p>;
    case "table": {
      const columns = q.columns ?? [];
      return (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>{columns.map((c) => <th key={c.key}>{text(c.label, lang)}</th>)}</tr>
            </thead>
            <tbody>
              {(value as Record<string, unknown>[]).map((row, i) => (
                <tr key={i}>
                  {columns.map((c) => {
                    const cell = row[c.key];
                    const shown =
                      cell === undefined || cell === null ? "" :
                      c.type === "yes_no" ? (cell ? t("common.yes") : t("common.no")) :
                      c.type === "date" ? formatDate(String(cell)) :
                      c.type === "single_choice" ? option(cell, c.options) : String(cell);
                    return <td key={c.key}>{shown}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }
    case "file":
      return (
        <ul className="file-list">
          {(value as number[]).map((id) => (
            <li key={id}><FileName id={id} t={t} /></li>
          ))}
        </ul>
      );
    default:
      return <p className="answer" dir="auto">{String(value)}</p>;
  }
}
