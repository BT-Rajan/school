import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { api, ApiError } from "../api";
import { DateField, ErrorMessage, Modal, Notice, PageHeader, StatusBadge, TextField, useAction } from "../components";
import Builder from "../forms/Builder";
import SectionView from "../forms/Renderer";
import type { Answers, FormSchema, Respondent } from "../forms/schema";
import { formatDate, formatDateTime } from "../format";
import { useSession } from "../session";
import type { FormComment, FormDetail, Problem } from "../types";

const WIDTHS = { phone: 375, tablet: 768, desktop: 0 } as const;
type Width = keyof typeof WIDTHS;

/** FR-F10: see the form as each respondent will, in either language, at phone, tablet or desktop width. */
export function Preview({ schema }: { schema: FormSchema }) {
  const { t, i18n } = useTranslation();
  const [respondent, setRespondent] = useState<Respondent>("supervisor");
  const [locale, setLocale] = useState(i18n.language);
  const [width, setWidth] = useState<Width>("phone");
  const [answers, setAnswers] = useState<Record<string, Answers>>({});
  const sections = schema.sections.filter((s) => s.respondent === respondent);
  return (
    <div className="preview">
      <div className="filters">
        <label>
          {t("builder.respondent")}{" "}
          <select aria-label={t("builder.respondent")} value={respondent} onChange={(e) => setRespondent(e.target.value as Respondent)}>
            <option value="supervisor">{t("roles.supervisor")}</option>
            <option value="teacher">{t("roles.teacher")}</option>
          </select>
        </label>
        <label>
          {t("lang.label")}{" "}
          <select aria-label={t("lang.label")} value={locale} onChange={(e) => setLocale(e.target.value)}>
            <option value="en">{t("lang.en")}</option>
            <option value="ar">{t("lang.ar")}</option>
          </select>
        </label>
        <label>
          {t("builder.width")}{" "}
          <select aria-label={t("builder.width")} value={width} onChange={(e) => setWidth(e.target.value as Width)}>
            {(Object.keys(WIDTHS) as Width[]).map((w) => (
              <option key={w} value={w}>{t(`builder.widths.${w}`)}</option>
            ))}
          </select>
        </label>
        <button type="button" onClick={() => setAnswers({})}>{t("builder.clearPreview")}</button>
      </div>
      <div className="preview-frame" style={WIDTHS[width] ? { maxWidth: WIDTHS[width] } : undefined}>
        {sections.length === 0 && <p className="hint">{t("builder.noSectionsFor")}</p>}
        {sections.map((s) => (
          <SectionView key={s.key} section={s} locale={locale} answers={answers[s.key] ?? {}}
            onChange={(a) => setAnswers({ ...answers, [s.key]: a })} />
        ))}
      </div>
    </div>
  );
}

function problemsOf(error: unknown): Problem[] {
  return error instanceof ApiError && Array.isArray(error.detail) ? (error.detail as Problem[]) : [];
}

export default function FormEditor() {
  const { t, i18n } = useTranslation();
  const { id } = useParams();
  const { me, district } = useSession();
  const client = useQueryClient();
  const tz = district?.time_zone ?? "UTC";
  const form = useQuery({ queryKey: ["form", id], queryFn: () => api<FormDetail>(`/api/forms/${id}`) });
  const comments = useQuery({
    queryKey: ["form-comments", id],
    queryFn: () => api<FormComment[]>(`/api/forms/${id}/comments`),
    enabled: me?.role === "form_author" || me?.role === "district_admin",
  });
  const [schema, setSchema] = useState<FormSchema | null>(null);
  const [titleEn, setTitleEn] = useState("");
  const [titleAr, setTitleAr] = useState("");
  const [dirty, setDirty] = useState(false);
  const [tab, setTab] = useState<"edit" | "preview">("edit");
  const [dialog, setDialog] = useState<"return" | "publish" | "extend" | "close" | null>(null);
  const [notice, setNotice] = useState("");

  const data = form.data;
  useEffect(() => {
    if (data && !dirty) {
      setSchema(data.schema);
      setTitleEn(data.catalog.title_en);
      setTitleAr(data.catalog.title_ar);
    }
  }, [data, dirty]);
  // Unsaved builder changes survive a language switch, and the browser warns before they are lost.
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const refresh = async () => {
    await client.invalidateQueries({ queryKey: ["form", id] });
    await client.invalidateQueries({ queryKey: ["form-comments", id] });
    await client.invalidateQueries({ queryKey: ["forms"] });
    await client.invalidateQueries({ queryKey: ["catalog"] });
  };
  const save = useAction(async () => {
    if (!data || !schema) return;
    const saved = await api<FormDetail>(`/api/forms/${data.id}`, {
      method: "PATCH",
      body: { version: data.version, schema, title_en: titleEn, title_ar: titleAr },
    });
    // The saved version is used at once, so "Send for review" never sends a stale one.
    client.setQueryData(["form", id], saved);
    setDirty(false);
    setNotice(t("common.saved"));
    await refresh();
  });
  const submit = useAction(async () => {
    if (!data) return;
    await api(`/api/forms/${data.id}/submit`, { method: "POST", body: { version: data.version } });
    setNotice(t("forms.sentForReview"));
    await refresh();
  });

  if (form.error) return <ErrorMessage error={form.error} />;
  if (!data || !schema) return <p>{t("common.loading")}</p>;
  const isAuthor = me?.role === "form_author";
  const isAdmin = me?.role === "district_admin";
  const editable = isAuthor && data.status === "draft";
  const title = i18n.language === "ar" ? data.catalog.title_ar || data.catalog.title_en : data.catalog.title_en || data.catalog.title_ar;
  const problems = [...problemsOf(save.error), ...(dirty ? [] : data.problems)];

  return (
    <>
      <p><Link to="/forms">← {t("nav.forms")}</Link></p>
      <PageHeader title={`${data.report.code} · ${data.catalog.version_code}`}>
        <StatusBadge status={data.status} />
      </PageHeader>
      <div className="card">
        <p>{title}</p>
        {data.start_date && (
          <p>{t("forms.window", { start: formatDate(data.start_date), end: formatDate(data.end_date) })}</p>
        )}
        {data.closed_at && <p>{t("forms.closedAt", { at: formatDateTime(data.closed_at, tz) })}</p>}
        <div className="page-actions">
          {editable && (
            <>
              <button type="button" className="primary" disabled={save.busy || !dirty} onClick={() => void save.run()}>
                {t("common.save")}
              </button>
              <button type="button" disabled={submit.busy || save.busy || dirty} onClick={() => void submit.run()}
                title={dirty ? t("forms.saveFirst") : undefined}>
                {t("forms.submitForReview")}
              </button>
            </>
          )}
          {isAdmin && data.status === "in_review" && (
            <>
              <button type="button" className="primary" onClick={() => setDialog("publish")}>{t("forms.publish")}</button>
              <button type="button" onClick={() => setDialog("return")}>{t("forms.returnToAuthor")}</button>
            </>
          )}
          {isAdmin && (data.status === "scheduled" || data.status === "active") && (
            <>
              <button type="button" onClick={() => setDialog("extend")}>{t("forms.extend")}</button>
              <button type="button" className="danger" onClick={() => setDialog("close")}>{t("forms.closeEarly")}</button>
            </>
          )}
        </div>
        {notice && <Notice>{notice}</Notice>}
        <ErrorMessage error={save.error ?? submit.error} />
        {problems.length > 0 && data.status === "draft" && (
          <div className="alert alert-error" role="status">
            {t("forms.problemsCount", { count: problems.length })}
          </div>
        )}
      </div>

      {(comments.data?.length ?? 0) > 0 && (
        <div className="card">
          <h2>{t("forms.reviewHistory")}</h2>
          <ul className="timeline">
            {comments.data!.map((c, i) => (
              <li key={i}>
                <strong>{t(`forms.actions.${c.action}`, { defaultValue: c.action })}</strong> · {c.by} ·{" "}
                <span className="ltr">{formatDateTime(c.at, tz)}</span>
                {c.comment && <p dir="auto">{c.comment}</p>}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="tabs" role="tablist">
        <button type="button" role="tab" aria-selected={tab === "edit"} onClick={() => setTab("edit")}>
          {editable ? t("forms.edit") : t("forms.content")}
        </button>
        <button type="button" role="tab" aria-selected={tab === "preview"} onClick={() => setTab("preview")}>
          {t("forms.preview")}
        </button>
      </div>
      {/* Both stay mounted, so switching tabs keeps which questions are open. */}
      <div hidden={tab !== "preview"}>
        <Preview schema={schema} />
      </div>
      <div hidden={tab !== "edit"}>
        {editable ? (
          <>
            <div className="card form-grid">
              <TextField label={`${t("forms.catalogTitle")} (${t("lang.en")})`} value={titleEn} dir="ltr"
                onChange={(v) => { setTitleEn(v); setDirty(true); }} />
              <TextField label={`${t("forms.catalogTitle")} (${t("lang.ar")})`} value={titleAr} dir="rtl"
                onChange={(v) => { setTitleAr(v); setDirty(true); }} />
            </div>
            <Builder schema={schema} problems={problems} onChange={(s) => { setSchema(s); setDirty(true); }} />
          </>
        ) : (
          <div className="card">
            {schema.sections.map((s) => (
              <SectionView key={s.key} section={s} answers={{}} />
            ))}
          </div>
        )}
      </div>

      {dialog && <ReviewDialog kind={dialog} form={data} onClose={() => setDialog(null)}
        onDone={async (message) => { setDialog(null); setNotice(message); await refresh(); }} />}
    </>
  );
}

function ReviewDialog({ kind, form, onClose, onDone }: {
  kind: "return" | "publish" | "extend" | "close";
  form: FormDetail;
  onClose: () => void;
  onDone: (message: string) => Promise<void>;
}) {
  const { t } = useTranslation();
  const [comment, setComment] = useState("");
  const [start, setStart] = useState(form.start_date ?? "");
  const [end, setEnd] = useState(form.end_date ?? "");
  const [overlap, setOverlap] = useState<{ form_id: number; version_code: string; start_date: string; end_date: string }[] | null>(null);
  const action = useAction(async (confirmOverlap: boolean) => {
    const base = `/api/forms/${form.id}`;
    try {
      if (kind === "return") await api(`${base}/return`, { method: "POST", body: { version: form.version, comment } });
      if (kind === "publish")
        await api(`${base}/publish`, {
          method: "POST",
          body: { version: form.version, start_date: start, end_date: end, confirm_overlap: confirmOverlap },
        });
      if (kind === "extend") await api(`${base}/extend`, { method: "POST", body: { version: form.version, end_date: end, reason: comment } });
      if (kind === "close") await api(`${base}/close`, { method: "POST", body: { version: form.version, reason: comment } });
    } catch (error) {
      if (error instanceof ApiError && error.code === "window_overlap") {
        setOverlap((error.detail as { forms: typeof overlap }).forms ?? []);
        return;
      }
      throw error;
    }
    await onDone(t(`forms.done.${kind}`));
  });
  const titles = { return: "forms.returnToAuthor", publish: "forms.publish", extend: "forms.extend", close: "forms.closeEarly" };
  return (
    <Modal title={t(titles[kind])} onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); void action.run(false); }}>
        {kind === "publish" && (
          <div className="form-grid">
            <DateField label={t("forms.startDate")} value={start} onChange={setStart} />
            <DateField label={t("forms.endDate")} value={end} onChange={setEnd} />
          </div>
        )}
        {kind === "extend" && <DateField label={t("forms.newEndDate")} value={end} onChange={setEnd} />}
        {kind !== "publish" && (
          <div className="field">
            <label htmlFor="review-comment">{kind === "return" ? t("forms.comment") : t("common.reason")}</label>
            <textarea id="review-comment" dir="auto" rows={4} required value={comment} onChange={(e) => setComment(e.target.value)} />
          </div>
        )}
        {kind === "publish" && <p className="hint">{t("forms.publishHint")}</p>}
        {overlap && (
          <div className="alert alert-error" role="alert">
            <p>{t("forms.overlap")}</p>
            <ul>
              {overlap.map((o) => (
                <li key={o.form_id}>
                  <span className="ltr">{o.version_code}</span>: <span className="ltr">{formatDate(o.start_date)} – {formatDate(o.end_date)}</span>
                </li>
              ))}
            </ul>
            <button type="button" className="primary" onClick={() => void action.run(true)}>{t("forms.publishAnyway")}</button>
          </div>
        )}
        <ErrorMessage error={action.error} />
        <div className="form-actions">
          <button type="button" onClick={onClose}>{t("common.cancel")}</button>
          <button type="submit" className={kind === "close" ? "danger" : "primary"} disabled={action.busy}>
            {t(titles[kind])}
          </button>
        </div>
      </form>
    </Modal>
  );
}
