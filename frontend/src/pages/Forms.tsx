import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";

import { api, openLink, uploadFile } from "../api";
import { DateField, ErrorMessage, Modal, PageHeader, SelectField, StatusBadge, TextField, useAction } from "../components";
import { formatDate } from "../format";
import { useSession } from "../session";
import type { CatalogReport, CatalogVersion, FormSummary, UploadedFile } from "../types";

/** Ministry report catalog and its forms (FR-MR1 to FR-MR4). Form Authors build; District Admins review. */
export default function Forms() {
  const { t, i18n } = useTranslation();
  const { me } = useSession();
  const client = useQueryClient();
  const navigate = useNavigate();
  const isAuthor = me?.role === "form_author";
  const isAdmin = me?.role === "district_admin";
  const catalog = useQuery({ queryKey: ["catalog"], queryFn: () => api<CatalogReport[]>("/api/catalog") });
  const [dialog, setDialog] = useState<{ kind: "report" } | { kind: "version"; report: CatalogReport } | null>(null);
  const [filter, setFilter] = useState("");
  // FR-R1: a District Admin approves which ministry reports teachers can be asked to answer on their own.
  const standalone = useAction(async (reportId: number, allowed: boolean) => {
    await api(`/api/catalog/reports/${reportId}/standalone`, { method: "POST", body: { allowed } });
    await client.invalidateQueries({ queryKey: ["catalog"] });
  });
  const openSource = useAction((fileId: number) =>
    openLink(() => api<{ url: string }>(`/api/files/${fileId}/link`, { method: "POST", body: { disposition: "inline" } })),
  );
  const title = (v: CatalogVersion) => (i18n.language === "ar" ? v.title_ar || v.title_en : v.title_en || v.title_ar);
  const reports = (catalog.data ?? []).filter(
    (r) => !filter || r.versions.some((v) => v.status === filter),
  );

  return (
    <>
      <PageHeader title={t("forms.title")}>
        {isAuthor && (
          <button type="button" className="primary" onClick={() => setDialog({ kind: "report" })}>
            {t("forms.newReport")}
          </button>
        )}
      </PageHeader>
      <div className="filters">
        <SelectField label={t("common.status")} value={filter} onChange={setFilter} placeholder={t("common.anyStatus")}
          options={["draft", "in_review", "scheduled", "active", "closed"].map((s) => ({ value: s, label: t(`status.${s}`) }))} />
      </div>
      <ErrorMessage error={catalog.error ?? openSource.error ?? standalone.error} />
      {reports.map((r) => (
        <div key={r.id} className="card">
          <div className="page-header">
            <h2>
              <span className="ltr">{r.report_code}</span> · {t(`forms.subject.${r.subject_type}`)}
            </h2>
            {isAuthor && (
              <button type="button" onClick={() => setDialog({ kind: "version", report: r })}>{t("forms.newVersion")}</button>
            )}
            {isAdmin && (
              <label className="check">
                <input type="checkbox" checked={r.standalone_allowed} disabled={standalone.busy}
                  onChange={(e) => void standalone.run(r.id, e.target.checked)} />
                {t("forms.standaloneAllowed")}
              </label>
            )}
            {!isAdmin && r.standalone_allowed && <span className="badge">{t("forms.standaloneBadge")}</span>}
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t("forms.versionCode")}</th>
                  <th>{t("forms.catalogTitle")}</th>
                  <th>{t("forms.ministryDate")}</th>
                  <th>{t("forms.windowShort")}</th>
                  <th>{t("common.status")}</th>
                  <th>{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {r.versions.map((v) => (
                  <tr key={v.id}>
                    <td className="ltr">{v.version_code}</td>
                    <td>{title(v)}</td>
                    <td className="ltr">{formatDate(v.ministry_published_on)}</td>
                    <td className="ltr">{v.start_date ? `${formatDate(v.start_date)} – ${formatDate(v.end_date)}` : ""}</td>
                    <td><StatusBadge status={v.status} /></td>
                    <td>
                      <div className="row-actions">
                        <Link to={`/forms/${v.form_id}`}>{t("forms.open")}</Link>
                        {v.source_file_id && (
                          <button type="button" className="link" onClick={() => void openSource.run(v.source_file_id!)}>
                            {t("forms.ministrySource")}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
      {catalog.data && reports.length === 0 && <p className="hint">{t("forms.empty")}</p>}
      {dialog?.kind === "report" && (
        <ReportDialog onClose={() => setDialog(null)}
          onDone={async () => { setDialog(null); await client.invalidateQueries({ queryKey: ["catalog"] }); }} />
      )}
      {dialog?.kind === "version" && (
        <VersionDialog report={dialog.report} onClose={() => setDialog(null)}
          onDone={async (form) => {
            setDialog(null);
            await client.invalidateQueries({ queryKey: ["catalog"] });
            navigate(`/forms/${form.id}`);
          }} />
      )}
    </>
  );
}

function ReportDialog({ onClose, onDone }: { onClose: () => void; onDone: () => Promise<void> }) {
  const { t } = useTranslation();
  const [code, setCode] = useState("");
  const [subject, setSubject] = useState("school");
  const save = useAction(async () => {
    await api("/api/catalog/reports", { method: "POST", body: { report_code: code, subject_type: subject } });
    await onDone();
  });
  return (
    <Modal title={t("forms.newReport")} onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); void save.run(); }}>
        <TextField label={t("forms.reportCode")} value={code} onChange={setCode} required dir="ltr" hint={t("forms.reportCodeHint")} />
        <SelectField label={t("forms.subjectType")} value={subject} onChange={setSubject}
          options={[{ value: "school", label: t("forms.subject.school") }, { value: "teacher", label: t("forms.subject.teacher") }]} />
        <ErrorMessage error={save.error} />
        <div className="form-actions">
          <button type="button" onClick={onClose}>{t("common.cancel")}</button>
          <button type="submit" className="primary" disabled={save.busy}>{t("common.create")}</button>
        </div>
      </form>
    </Modal>
  );
}

function VersionDialog({ report, onClose, onDone }: {
  report: CatalogReport;
  onClose: () => void;
  onDone: (form: FormSummary) => Promise<void>;
}) {
  const { t } = useTranslation();
  const [code, setCode] = useState("");
  const [titleEn, setTitleEn] = useState("");
  const [titleAr, setTitleAr] = useState("");
  const [published, setPublished] = useState("");
  const [copyFrom, setCopyFrom] = useState(report.versions.length ? String(report.versions[report.versions.length - 1].form_id) : "");
  const [source, setSource] = useState<File | null>(null);
  const save = useAction(async () => {
    const stored = source ? await uploadFile<UploadedFile>(source) : null;
    const form = await api<FormSummary>(`/api/catalog/reports/${report.id}/versions`, {
      method: "POST",
      body: {
        version_code: code,
        title_en: titleEn,
        title_ar: titleAr,
        ministry_published_on: published || null,
        source_file_id: stored?.id ?? null,
        copy_from_form_id: copyFrom ? Number(copyFrom) : null,
      },
    });
    await onDone(form);
  });
  return (
    <Modal title={`${t("forms.newVersion")} · ${report.report_code}`} onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); void save.run(); }}>
        <TextField label={t("forms.versionCode")} value={code} onChange={setCode} required dir="ltr" />
        <TextField label={`${t("forms.catalogTitle")} (${t("lang.en")})`} value={titleEn} onChange={setTitleEn} dir="ltr" />
        <TextField label={`${t("forms.catalogTitle")} (${t("lang.ar")})`} value={titleAr} onChange={setTitleAr} dir="rtl" />
        <DateField label={t("forms.ministryDate")} value={published} onChange={setPublished} />
        <SelectField label={t("forms.copyFrom")} value={copyFrom} onChange={setCopyFrom} placeholder={t("forms.startEmpty")}
          options={report.versions.map((v) => ({ value: String(v.form_id), label: v.version_code }))} />
        <div className="field">
          <label htmlFor="source-file">{t("forms.ministrySource")} ({t("common.optional")})</label>
          <input id="source-file" type="file" accept="application/pdf" onChange={(e) => setSource(e.target.files?.[0] ?? null)} />
        </div>
        <ErrorMessage error={save.error} />
        <div className="form-actions">
          <button type="button" onClick={onClose}>{t("common.cancel")}</button>
          <button type="submit" className="primary" disabled={save.busy}>{t("common.create")}</button>
        </div>
      </form>
    </Modal>
  );
}
