import { type ReactNode, useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "./api";
import { formatDate, parseDate } from "./format";
import type { Locale } from "./i18n";
import { useSession } from "./session";
import type { CustomField, CustomValues, Ref } from "./types";

/** Translate an API error, including per-field and per-row details. */
export function useErrorText() {
  const { t } = useTranslation();
  return (error: unknown): string[] => {
    if (!(error instanceof ApiError)) return [t("errors.generic")];
    const main = t(`errors.${error.code}`, {
      defaultValue: t("errors.generic"),
      ...(typeof error.detail === "object" && error.detail && !Array.isArray(error.detail) ? error.detail : {}),
    });
    const lines = [main];
    if (Array.isArray(error.detail)) {
      for (const item of error.detail as { field?: string; code?: string; value?: string }[]) {
        const what = t(`fieldErrors.${item.code}`, { defaultValue: t(`errors.${item.code}`, { defaultValue: item.code ?? "" }) });
        lines.push(item.field ? `${item.field}: ${what}` : what);
      }
    }
    if (error.code === "columns_invalid" && error.detail && typeof error.detail === "object") {
      const { missing = [], unknown = [] } = error.detail as { missing?: string[]; unknown?: string[] };
      if (missing.length) lines.push(`− ${missing.join(", ")}`);
      if (unknown.length) lines.push(`? ${unknown.join(", ")}`);
    }
    return lines;
  };
}

export function ErrorMessage({ error }: { error: unknown }) {
  const text = useErrorText();
  if (!error) return null;
  return (
    <div className="alert alert-error" role="alert">
      {text(error).map((line, i) => (
        <div key={i}>{line}</div>
      ))}
    </div>
  );
}

export function Notice({ children }: { children: ReactNode }) {
  return (
    <div className="alert alert-ok" role="status">
      {children}
    </div>
  );
}

/** Wraps an async action with busy and error state. */
export function useAction<A extends unknown[], R>(action: (...args: A) => Promise<R>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const run = async (...args: A): Promise<R | undefined> => {
    setBusy(true);
    setError(null);
    try {
      return await action(...args);
    } catch (caught) {
      setError(caught);
      return undefined;
    } finally {
      setBusy(false);
    }
  };
  return { run, busy, error, setError };
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: (id: string) => ReactNode }) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children(id)}
      {hint && <div className="hint">{hint}</div>}
    </div>
  );
}

export function TextField({
  label,
  value,
  onChange,
  type = "text",
  required,
  hint,
  autoComplete,
  inputMode,
  dir,
  disabled,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  required?: boolean;
  hint?: string;
  autoComplete?: string;
  inputMode?: "numeric" | "text" | "email";
  dir?: "ltr" | "rtl" | "auto";
  disabled?: boolean;
}) {
  return (
    <Field label={label} hint={hint}>
      {(id) => (
        <input
          id={id}
          type={type}
          value={value}
          required={required}
          disabled={disabled}
          autoComplete={autoComplete}
          inputMode={inputMode}
          dir={dir ?? "auto"}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
    </Field>
  );
}

export function SelectField({
  label,
  value,
  onChange,
  options,
  placeholder,
  required,
  disabled,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  placeholder?: string;
  required?: boolean;
  disabled?: boolean;
}) {
  return (
    <Field label={label}>
      {(id) => (
        <select id={id} value={value} required={required} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
          {placeholder !== undefined && <option value="">{placeholder}</option>}
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      )}
    </Field>
  );
}

/** Date entry in D/MM/YYYY (FR-PB2). Holds the ISO value; shows and accepts the district format. */
export function DateField({ label, value, onChange }: { label: string; value: string; onChange: (iso: string) => void }) {
  const { t } = useTranslation();
  const [text, setText] = useState(formatDate(value));
  useEffect(() => setText(formatDate(value)), [value]);
  const valid = text === "" || parseDate(text) !== null;
  return (
    <Field label={label} hint={t("common.dateHint")}>
      {(id) => (
        <input
          id={id}
          value={text}
          dir="ltr"
          inputMode="numeric"
          placeholder="D/MM/YYYY"
          aria-invalid={!valid}
          onChange={(e) => {
            setText(e.target.value);
            const iso = parseDate(e.target.value);
            if (iso) onChange(iso);
          }}
        />
      )}
    </Field>
  );
}

export function useRefName() {
  const { i18n } = useTranslation();
  return (ref: Ref | { en: string; ar: string }) =>
    "name_en" in ref ? (i18n.language === "ar" ? ref.name_ar : ref.name_en) : i18n.language === "ar" ? ref.ar : ref.en;
}

export function CheckboxGroup({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { value: string; label: string }[];
  value: string[];
  onChange: (value: string[]) => void;
}) {
  return (
    <fieldset className="field checks">
      <legend>{label}</legend>
      {options.map((o) => (
        <label key={o.value} className="check">
          <input
            type="checkbox"
            checked={value.includes(o.value)}
            onChange={(e) => onChange(e.target.checked ? [...value, o.value] : value.filter((v) => v !== o.value))}
          />
          {o.label}
        </label>
      ))}
    </fieldset>
  );
}

/** Inputs for the admin-defined extra fields (FR-T5). */
export function CustomFieldInputs({
  fields,
  values,
  onChange,
}: {
  fields: CustomField[];
  values: CustomValues;
  onChange: (values: CustomValues) => void;
}) {
  const { t, i18n } = useTranslation();
  const set = (key: string, value: string | number | boolean | string[]) => onChange({ ...values, [key]: value });
  return (
    <>
      {fields.map((f) => {
        const label = `${i18n.language === "ar" ? f.label_ar : f.label_en}${f.required ? "" : ` (${t("common.optional")})`}`;
        const options = f.options.map((o) => ({ value: o.code, label: i18n.language === "ar" ? o.ar : o.en }));
        const current = values[f.key];
        switch (f.field_type) {
          case "single_choice":
            return (
              <SelectField key={f.key} label={label} value={String(current ?? "")} placeholder="" options={options}
                onChange={(v) => set(f.key, v)} />
            );
          case "multi_choice":
            return (
              <CheckboxGroup key={f.key} label={label} options={options}
                value={Array.isArray(current) ? current : []} onChange={(v) => set(f.key, v)} />
            );
          case "yes_no":
            return (
              <SelectField key={f.key} label={label} value={current === undefined ? "" : current ? "yes" : "no"}
                placeholder="" options={[{ value: "yes", label: t("common.yes") }, { value: "no", label: t("common.no") }]}
                onChange={(v) => set(f.key, v === "" ? "" : v === "yes")} />
            );
          case "date":
            return <DateField key={f.key} label={label} value={String(current ?? "")} onChange={(v) => set(f.key, v)} />;
          default:
            return (
              <TextField key={f.key} label={label} value={String(current ?? "")}
                inputMode={f.field_type === "number" ? "numeric" : undefined} onChange={(v) => set(f.key, v)} />
            );
        }
      })}
    </>
  );
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const { t } = useTranslation();
  const id = useId();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby={id}>
        <div className="modal-head">
          <h2 id={id}>{title}</h2>
          {/* The header's switch is behind the backdrop, so dialogs carry their own (FR-I3). */}
          <div className="page-actions">
            <LanguageSwitch />
            <button type="button" className="link" onClick={onClose} aria-label={t("common.close")}>
              ✕
            </button>
          </div>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Pager({ page, total, pageSize, onPage }: { page: number; total: number; pageSize: number; onPage: (p: number) => void }) {
  const { t } = useTranslation();
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="pager">
      <span>{t("common.total", { count: total })}</span>
      <button type="button" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        {t("common.previous")}
      </button>
      <span>{t("common.page", { page, pages })}</span>
      <button type="button" disabled={page >= pages} onClick={() => onPage(page + 1)}>
        {t("common.next")}
      </button>
    </div>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const { t } = useTranslation();
  return <span className={`badge badge-${status}`}>{t(`status.${status}`, { defaultValue: status })}</span>;
}

export function LanguageSwitch() {
  const { t, i18n } = useTranslation();
  const { changeLocale } = useSession();
  const other: Locale = i18n.language === "ar" ? "en" : "ar";
  return (
    <button type="button" className="lang-switch" lang={other} onClick={() => changeLocale(other)}
      aria-label={t("lang.label")}>
      {t(`lang.${other}`)}
    </button>
  );
}

export function PageHeader({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="page-header">
      <h1>{title}</h1>
      <div className="page-actions">{children}</div>
    </div>
  );
}
