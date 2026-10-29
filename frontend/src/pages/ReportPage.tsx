import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { api, openLink } from "../api";
import { DateField, ErrorMessage, Modal, Notice, PageHeader, StatusBadge, TextField, useAction } from "../components";
import { formatDate, formatDateTime, formatNumber } from "../format";
import PagePicker, { type Picked, readyIds } from "../reports/PagePicker";
import { useSession } from "../session";
import type { AccessEvent, DocumentDetail } from "../types";
import { newKey } from "./Evaluations";

type Dialog = "acknowledge" | "return" | "forward" | "version" | "edit" | "submit" | null;

export default function ReportPage() {
  const { t, i18n } = useTranslation();
  const { id } = useParams();
  const { me, district } = useSession();
  const tz = district?.time_zone ?? "UTC";
  const client = useQueryClient();
  const doc = useQuery({ queryKey: ["document", id], queryFn: () => api<DocumentDetail>(`/api/documents/${id}`) });
  const d = doc.data;
  const isAdmin = me?.role === "district_admin";
  const own = !!d?.mine;
  const history = useQuery({
    queryKey: ["document-access", id],
    queryFn: () => api<AccessEvent[]>(`/api/documents/${id}/access`),
    enabled: !!d && (own || isAdmin),
  });
  const [dialog, setDialog] = useState<Dialog>(null);
  const [notice, setNotice] = useState("");

  const refresh = async (message?: string) => {
    if (message) setNotice(message);
    await client.invalidateQueries({ queryKey: ["document", id] });
    await client.invalidateQueries({ queryKey: ["document-access", id] });
    await client.invalidateQueries({ queryKey: ["documents"] });
    await client.invalidateQueries({ queryKey: ["dashboard"] });
  };
  const view = useAction(async (versionId: number, disposition: "inline" | "attachment") => {
    await openLink(() =>
      api<{ url: string }>(`/api/documents/${id}/link`, { method: "POST", body: { disposition, version_id: versionId } }),
    );
    await refresh();
  });
  const simple = useAction(async (action: string, body?: unknown, confirmText?: string) => {
    if (confirmText && !window.confirm(confirmText)) return;
    await api(`/api/documents/${id}/${action}`, { method: "POST", body });
    await refresh(t(`reports.done.${action}`));
  });

  if (doc.error) return <ErrorMessage error={doc.error} />;
  if (!d) return <p>{t("common.loading")}</p>;
  const status = d.status;
  const editable = own && ["draft", "withdrawn", "returned"].includes(status);
  const underReview = status === "submitted" || status === "viewed";
  const activeForward = d.forwards?.find((f) => !f.revoked_at);
  const reportTitle = i18n.language === "ar" ? d.report.title_ar : d.report.title_en;

  return (
    <>
      <p><Link to="/reports">← {isAdmin ? t("reports.inbox") : own ? t("reports.mine") : t("reports.forwarded")}</Link></p>
      <PageHeader title={d.title}>
        <StatusBadge status={status} />
        {d.overdue && <span className="badge badge-warn">{t("reports.overdue")}</span>}
        {d.archived && <span className="badge">{t("reports.archived")}</span>}
      </PageHeader>
      {status === "returned" && d.review_comment && (
        <div className="alert alert-error" role="status">
          <strong>{t("reports.returnedBy", { name: d.returned_by ?? "" })}</strong>
          <p dir="auto">{d.review_comment}</p>
        </div>
      )}
      {notice && <Notice>{notice}</Notice>}
      <ErrorMessage error={view.error ?? simple.error} />

      <div className="card">
        <dl className="facts">
          <dt>{t("reports.reportVersion")}</dt>
          <dd><span className="ltr">{d.report.code} / {d.report.version_code}</span> · {reportTitle}</dd>
          <dt>{t("schools.school")}</dt>
          <dd><span className="ltr">{d.school.code}</span> · {d.school.name}</dd>
          <dt>{t("roles.supervisor")}</dt>
          <dd>{d.supervisor.name}</dd>
          <dt>{t("reports.reportDate")}</dt>
          <dd className="ltr">{formatDate(d.report_date)}</dd>
          {d.submitted_at && (<><dt>{t("reports.submittedAt")}</dt><dd className="ltr">{formatDateTime(d.submitted_at, tz)}</dd></>)}
          {d.first_viewed_at && (
            <><dt>{t("reports.firstViewed")}</dt><dd>{d.first_viewed_by} · <span className="ltr">{formatDateTime(d.first_viewed_at, tz)}</span></dd></>
          )}
          {d.acknowledged_at && (
            <><dt>{t("reports.acknowledgedAt")}</dt><dd>{d.acknowledged_by} · <span className="ltr">{formatDateTime(d.acknowledged_at, tz)}</span></dd></>
          )}
          {d.evaluation_id && (<><dt>{t("reports.evaluation")}</dt><dd><Link to={`/evaluations/${d.evaluation_id}`}>#{d.evaluation_id}</Link></dd></>)}
          {d.notes && (<><dt>{t("reports.notes")}</dt><dd dir="auto">{d.notes}</dd></>)}
          {d.tags.length > 0 && (<><dt>{t("reports.tags")}</dt><dd>{d.tags.join(", ")}</dd></>)}
          {d.file && (
            <>
              <dt>{t("reports.file")}</dt>
              <dd>
                {d.file.pages ? t("reports.pageCount", { count: d.file.pages }) : ""} · {formatNumber(Math.ceil(d.file.size / 1024))} KB
                {d.file.status === "pending" && <span className="badge badge-warn">{t("reports.scanning")}</span>}
                {d.file.status === "quarantined" && <span className="badge badge-error">{t("reports.quarantined")}</span>}
              </dd>
            </>
          )}
        </dl>
        {!own && <p className="hint">{t("reports.watermarkHint")}</p>}
        <div className="page-actions">
          {own && editable && <button type="button" className="primary" onClick={() => setDialog("submit")}>{t("reports.submit")}</button>}
          {own && editable && <button type="button" onClick={() => setDialog("edit")}>{t("common.edit")}</button>}
          {own && !underReview && status !== "deleted" && (
            <button type="button" onClick={() => setDialog("version")}>
              {status === "acknowledged" ? t("reports.correction") : t("reports.newVersion")}
            </button>
          )}
          {own && underReview && (
            <button type="button" onClick={() => void simple.run("withdraw", { version: d.version }, t("reports.confirmWithdraw"))}>
              {t("reports.withdraw")}
            </button>
          )}
          {own && (status === "draft" || status === "withdrawn") && (
            <button type="button" className="danger"
              onClick={() => void simple.run("delete", { version: d.version }, t("reports.confirmDelete"))}>
              {t("reports.delete")}
            </button>
          )}
          {isAdmin && underReview && (
            <>
              <button type="button" className="primary" onClick={() => setDialog("acknowledge")}>{t("reports.acknowledge")}</button>
              <button type="button" onClick={() => setDialog("return")}>{t("reports.return")}</button>
            </>
          )}
          {isAdmin && ["submitted", "viewed", "acknowledged"].includes(status) && !activeForward && (
            <button type="button" onClick={() => setDialog("forward")}>{t("reports.forward")}</button>
          )}
          {isAdmin && activeForward && (
            <button type="button" onClick={() => void simple.run("revoke-forward", undefined, t("reports.confirmRevoke"))}>
              {t("reports.revokeForward")}
            </button>
          )}
          {isAdmin && status === "acknowledged" && !d.archived && (
            <button type="button" onClick={() => void simple.run("archive")}>{t("reports.archive")}</button>
          )}
          {isAdmin && status === "deleted" && (
            <button type="button" onClick={() => void simple.run("restore")}>{t("reports.restore")}</button>
          )}
        </div>
      </div>

      <div className="card">
        <h2>{t("reports.versions")}</h2>
        <ul className="timeline">
          {d.versions.map((v) => (
            <li key={v.id}>
              <strong>{t("reports.versionN", { n: v.number })}</strong>
              {v.current && <span className="badge">{t("reports.current")}</span>} ·{" "}
              <span className="ltr">{formatDateTime(v.created_at, tz)}</span>
              {v.reason && <p dir="auto">{v.reason}</p>}
              <div className="row-actions">
                <button type="button" disabled={view.busy} onClick={() => void view.run(v.id, "inline")}>{t("reports.view")}</button>
                <button type="button" disabled={view.busy} onClick={() => void view.run(v.id, "attachment")}>{t("reports.download")}</button>
              </div>
            </li>
          ))}
        </ul>
      </div>

      {isAdmin && (d.forwards?.length ?? 0) > 0 && (
        <div className="card">
          <h2>{t("reports.forwards")}</h2>
          <ul className="timeline">
            {d.forwards!.map((f) => (
              <li key={f.id}>
                {t("reports.forwardedBy", { name: f.by ?? "", at: formatDateTime(f.at, tz) })}
                {f.revoked_at && <span className="badge">{t("reports.revokedAt", { at: formatDateTime(f.revoked_at, tz) })}</span>}
                {f.note && <p dir="auto">{f.note}</p>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {(own || isAdmin) && (
        <div className="card">
          <h2>{t("reports.accessHistory")}</h2>
          <ErrorMessage error={history.error} />
          {history.data?.length === 0 && <p className="hint">{t("reports.noAccess")}</p>}
          <ul className="timeline">
            {history.data?.map((a, i) => (
              <li key={i}>
                {t(`reports.events.${a.action}`, { defaultValue: a.action })} · {a.by} ({t(`roles.${a.role}`)}) ·{" "}
                <span className="ltr">{formatDateTime(a.at, tz)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {dialog && <ActionDialog kind={dialog} doc={d} onClose={() => setDialog(null)}
        onDone={async (message) => { setDialog(null); await refresh(message); }} />}
    </>
  );
}

function ActionDialog({ kind, doc, onClose, onDone }: {
  kind: Exclude<Dialog, null>;
  doc: DocumentDetail;
  onClose: () => void;
  onDone: (message: string) => Promise<void>;
}) {
  const { t } = useTranslation();
  const [text, setText] = useState(kind === "edit" ? doc.notes ?? "" : "");
  const [title, setTitle] = useState(doc.title);
  const [reportDate, setReportDate] = useState(doc.report_date);
  const [pages, setPages] = useState<Picked[]>([]);
  const [key] = useState(newKey);
  const ids = readyIds(pages);
  const correction = kind === "version" && doc.status === "acknowledged";
  const run = useAction(async () => {
    const base = `/api/documents/${doc.id}`;
    if (kind === "submit") await api(`${base}/submit`, { method: "POST", body: { version: doc.version, message: text || null } });
    if (kind === "acknowledge") await api(`${base}/acknowledge`, { method: "POST", body: { version: doc.version, comment: text || null } });
    if (kind === "return") await api(`${base}/return`, { method: "POST", body: { version: doc.version, comment: text } });
    if (kind === "forward") await api(`${base}/forward`, { method: "POST", body: { note: text || null } });
    if (kind === "version")
      await api(`${base}/versions`, { method: "POST", body: { version: doc.version, file_ids: ids, reason: text || null, client_key: key } });
    if (kind === "edit")
      await api(base, { method: "PATCH", body: { version: doc.version, title, notes: text || null, report_date: reportDate } });
    await onDone(t(`reports.done.${kind}`));
  });
  const titles: Record<typeof kind, string> = {
    submit: "reports.submit",
    acknowledge: "reports.acknowledge",
    return: "reports.return",
    forward: "reports.forward",
    version: correction ? "reports.correction" : "reports.newVersion",
    edit: "common.edit",
  };
  const textLabel: Record<typeof kind, string> = {
    submit: `${t("reports.message")} (${t("common.optional")})`,
    acknowledge: `${t("reports.comment")} (${t("common.optional")})`,
    return: t("reports.returnReason"),
    forward: `${t("reports.forwardNote")} (${t("common.optional")})`,
    version: correction ? t("reports.correctionReason") : `${t("common.reason")} (${t("common.optional")})`,
    edit: `${t("reports.notes")} (${t("common.optional")})`,
  };
  const required = kind === "return" || correction;
  return (
    <Modal title={t(titles[kind])} onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); void run.run(); }}>
        {kind === "forward" && <p className="hint">{t("reports.forwardHint")}</p>}
        {kind === "version" && <PagePicker pages={pages} onChange={setPages} />}
        {kind === "edit" && (
          <>
            <TextField label={t("reports.title")} value={title} onChange={setTitle} required />
            <DateField label={t("reports.reportDate")} value={reportDate} onChange={setReportDate} />
          </>
        )}
        <div className="field">
          <label htmlFor="action-text">{textLabel[kind]}</label>
          <textarea id="action-text" dir="auto" rows={3} required={required} value={text} onChange={(e) => setText(e.target.value)} />
        </div>
        <ErrorMessage error={run.error} />
        <div className="form-actions">
          <button type="button" onClick={onClose}>{t("common.cancel")}</button>
          <button type="submit" className="primary" disabled={run.busy || (kind === "version" && !ids)}>{t(titles[kind])}</button>
        </div>
      </form>
    </Modal>
  );
}
