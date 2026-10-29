import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";

import { api, ApiError, query } from "../api";
import { DateField, ErrorMessage, Modal, PageHeader, Pager, SelectField, StatusBadge, TextField, useAction } from "../components";
import { formatDate, formatDateTime } from "../format";
import { useClusters } from "../hooks";
import { isOfflineError } from "../offline/hooks";
import * as queue from "../offline/queue";
import PagePicker, { type Picked, queueable, readyIds } from "../reports/PagePicker";
import { useSession } from "../session";
import type { Assignment, CatalogReport, DocumentDetail, DocumentSummary, EvaluationSummary, Page, Teacher } from "../types";
import { newKey, todayIn } from "./Evaluations";

const PAGE_SIZE = 50;
const STATUSES = ["draft", "submitted", "viewed", "acknowledged", "returned", "withdrawn", "deleted"];

/** "My reports" for supervisors, the "Report inbox" for admins, "Forwarded to me" for Cluster Heads (FR-D40 to FR-D43). */
export default function Reports() {
  const { t } = useTranslation();
  const { me, district } = useSession();
  const tz = district?.time_zone ?? "UTC";
  const isAdmin = me?.role === "district_admin";
  const isSupervisor = me?.role === "supervisor";
  const clusters = useClusters(isAdmin);
  const [filters, setFilters] = useState({ q: "", status: "", cluster_id: "", report_code: "", date_from: "", date_to: "" });
  const [archived, setArchived] = useState(false);
  const [page, setPage] = useState(1);
  const [uploading, setUploading] = useState(false);
  const set = (key: keyof typeof filters) => (value: string) => {
    setFilters({ ...filters, [key]: value });
    setPage(1);
  };
  const list = useQuery({
    queryKey: ["documents", filters, archived, page],
    queryFn: () =>
      api<Page<DocumentSummary>>(`/api/documents${query({ ...filters, include_archived: archived || undefined, page, page_size: PAGE_SIZE })}`),
  });
  const title = isAdmin ? t("reports.inbox") : isSupervisor ? t("reports.mine") : t("reports.forwarded");
  return (
    <>
      <PageHeader title={title}>
        {isSupervisor && (
          <button type="button" className="primary" onClick={() => setUploading(true)}>{t("reports.upload")}</button>
        )}
      </PageHeader>
      <div className="filters">
        <TextField label={t("common.search")} value={filters.q} onChange={set("q")} />
        <SelectField label={t("common.status")} value={filters.status} onChange={set("status")} placeholder={t("common.anyStatus")}
          options={STATUSES.filter((s) => isSupervisor || (s !== "draft" && (isAdmin || s !== "deleted"))).map((s) => ({
            value: s,
            label: t(`status.${s}`),
          }))} />
        {isAdmin && (
          <SelectField label={t("schools.cluster")} value={filters.cluster_id} onChange={set("cluster_id")} placeholder={t("common.all")}
            options={(clusters.data ?? []).map((c) => ({ value: String(c.id), label: `${c.code} · ${c.name}` }))} />
        )}
        <TextField label={t("reports.reportCode")} value={filters.report_code} onChange={set("report_code")} dir="ltr" />
        <DateField label={t("reports.from")} value={filters.date_from} onChange={set("date_from")} />
        <DateField label={t("reports.to")} value={filters.date_to} onChange={set("date_to")} />
        <label className="check">
          <input type="checkbox" checked={archived} onChange={(e) => { setArchived(e.target.checked); setPage(1); }} />
          {t("reports.includeArchived")}
        </label>
      </div>
      <ErrorMessage error={list.error} />
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{t("reports.title")}</th>
              <th>{t("reports.reportCode")}</th>
              <th>{t("schools.school")}</th>
              {!isSupervisor && <th>{t("roles.supervisor")}</th>}
              <th>{t("reports.reportDate")}</th>
              <th>{t("reports.submittedAt")}</th>
              <th>{t("common.status")}</th>
            </tr>
          </thead>
          <tbody>
            {list.data?.items.map((d) => (
              <tr key={d.id} className={d.overdue ? "row-warn" : ""}>
                <td><Link to={`/reports/${d.id}`} dir="auto">{d.title}</Link></td>
                <td className="ltr">{d.report.code} / {d.report.version_code}</td>
                <td>{d.school.name}</td>
                {!isSupervisor && <td>{d.supervisor.name}</td>}
                <td className="ltr">{formatDate(d.report_date)}</td>
                <td className="ltr">{formatDateTime(d.submitted_at, tz)}</td>
                <td>
                  <StatusBadge status={d.status} />
                  {d.overdue && <span className="badge badge-warn">{t("reports.overdue")}</span>}
                  {d.archived && <span className="badge">{t("reports.archived")}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {list.data && list.data.items.length === 0 && <p className="hint">{t("reports.empty")}</p>}
      {list.data && <Pager page={page} total={list.data.total} pageSize={PAGE_SIZE} onPage={setPage} />}
      {uploading && <UploadDialog onClose={() => setUploading(false)} />}
    </>
  );
}

export function useReportVersions() {
  return useQuery({ queryKey: ["catalog"], queryFn: () => api<CatalogReport[]>("/api/catalog") });
}

/** FR-D1 to FR-D8: scan or pick pages, tag them with the ministry report, and send them to the District Admins. */
function UploadDialog({ onClose }: { onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const { district } = useSession();
  const navigate = useNavigate();
  const client = useQueryClient();
  const catalog = useReportVersions();
  const assignments = useQuery({ queryKey: ["my-assignments"], queryFn: () => api<Assignment[]>("/api/me/assignments") });
  const [versionId, setVersionId] = useState("");
  const [schoolId, setSchoolId] = useState("");
  const [teacherId, setTeacherId] = useState("");
  const [evaluationId, setEvaluationId] = useState("");
  const [reportDate, setReportDate] = useState(todayIn(district?.time_zone ?? "UTC"));
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState("");
  const [submitNow, setSubmitNow] = useState(true);
  const [pages, setPages] = useState<Picked[]>([]);
  const [duplicate, setDuplicate] = useState<number | null>(null);
  const [key] = useState(newKey);

  const versions = (catalog.data ?? []).flatMap((r) =>
    r.versions.filter((v) => ["scheduled", "active", "closed"].includes(v.status)).map((v) => ({ report: r, version: v })),
  );
  const chosen = versions.find((x) => String(x.version.id) === versionId);
  const forTeacher = chosen?.report.subject_type === "teacher";
  const schools = new Map((assignments.data ?? []).filter((a) => a.state !== "upcoming").map((a) => [a.school.id, a.school]));
  const teachers = useQuery({
    queryKey: ["teachers", "school", schoolId],
    queryFn: () => api<Page<Teacher>>(`/api/teachers${query({ school_id: schoolId, page_size: 200 })}`),
    enabled: forTeacher && !!schoolId,
  });
  const evaluations = useQuery({
    queryKey: ["evaluations", "school", schoolId],
    queryFn: () => api<Page<EvaluationSummary>>(`/api/evaluations${query({ school_id: schoolId, page_size: 100 })}`),
    enabled: !!schoolId,
  });
  const ids = readyIds(pages);
  const canQueue = queueable(pages);
  const metadata = () => ({
    ministry_report_version_id: Number(versionId),
    school_id: Number(schoolId),
    teacher_id: forTeacher && teacherId ? Number(teacherId) : null,
    evaluation_id: evaluationId ? Number(evaluationId) : null,
    report_date: reportDate,
    title: title || null,
    notes: notes || null,
  });
  /** FR-PW4, FR-D6: no connection, so the pages wait on the device and upload later. */
  const keepOnDevice = async () => {
    const label = `${versions.find((x) => String(x.version.id) === versionId)?.report.report_code ?? ""} · ${schools.get(Number(schoolId))?.name ?? ""}`;
    try {
      await queue.enqueueDocument(pages.map((p) => p.source), metadata(), submitNow, label);
    } catch (error) {
      if (error instanceof queue.QueueFullError) throw new ApiError(0, "offline_queue_full");
      throw error;
    }
    navigate("/outbox");
  };
  const save = useAction(async (confirmDuplicate: boolean) => {
    if (!ids) return keepOnDevice();
    let doc: DocumentDetail;
    try {
      doc = await api<DocumentDetail>("/api/documents", {
        method: "POST",
        body: {
          ...metadata(),
          file_ids: ids,
          client_key: key,
          device_time: new Date().toISOString(),
          confirm_duplicate: confirmDuplicate,
        },
      });
    } catch (error) {
      if (error instanceof ApiError && error.code === "duplicate_document") {
        setDuplicate((error.detail as { document_id: number }).document_id);
        return;
      }
      if (isOfflineError(error)) return keepOnDevice();
      throw error;
    }
    if (submitNow) {
      doc = await api<DocumentDetail>(`/api/documents/${doc.id}/submit`, { method: "POST", body: { version: doc.version } });
    }
    await client.invalidateQueries({ queryKey: ["documents"] });
    await client.invalidateQueries({ queryKey: ["dashboard"] });
    navigate(`/reports/${doc.id}`);
  });
  const versionLabel = (x: (typeof versions)[number]) =>
    `${x.report.report_code} ${x.version.version_code} · ${i18n.language === "ar" ? x.version.title_ar || x.version.title_en : x.version.title_en || x.version.title_ar}`;

  return (
    <Modal title={t("reports.upload")} onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); void save.run(false); }}>
        <SelectField label={t("reports.reportVersion")} value={versionId} onChange={setVersionId} required placeholder=""
          options={versions.map((x) => ({ value: String(x.version.id), label: versionLabel(x) }))} />
        <SelectField label={t("schools.school")} value={schoolId} required placeholder=""
          onChange={(v) => { setSchoolId(v); setTeacherId(""); setEvaluationId(""); }}
          options={[...schools.values()].map((s) => ({ value: String(s.id), label: `${s.code} · ${s.name}` }))} />
        {forTeacher && (
          <SelectField label={t("evaluations.teacher")} value={teacherId} onChange={setTeacherId} required placeholder=""
            options={(teachers.data?.items ?? []).map((tc) => ({ value: String(tc.id), label: `${tc.name} (${tc.staff_id})` }))} />
        )}
        <DateField label={t("reports.reportDate")} value={reportDate} onChange={setReportDate} />
        <PagePicker pages={pages} onChange={setPages} />
        <TextField label={`${t("reports.title")} (${t("common.optional")})`} value={title} onChange={setTitle}
          hint={t("reports.titleHint")} />
        <div className="field">
          <label htmlFor="report-notes">{t("reports.notes")} ({t("common.optional")})</label>
          <textarea id="report-notes" dir="auto" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </div>
        {(evaluations.data?.items.length ?? 0) > 0 && (
          <SelectField label={`${t("reports.linkEvaluation")} (${t("common.optional")})`} value={evaluationId} onChange={setEvaluationId}
            placeholder={t("common.none")}
            options={evaluations.data!.items.filter((e) => e.status !== "cancelled").map((e) => ({
              value: String(e.id),
              label: `${e.report.code} · ${formatDate(e.visit_date)}`,
            }))} />
        )}
        <label className="check">
          <input type="checkbox" checked={submitNow} onChange={(e) => setSubmitNow(e.target.checked)} />
          {t("reports.submitNow")}
        </label>
        {duplicate !== null && (
          <div className="alert alert-error" role="alert">
            <p>{t("reports.duplicate")}</p>
            <div className="page-actions">
              <Link to={`/reports/${duplicate}`}>{t("reports.openExisting")}</Link>
              <button type="button" onClick={() => void save.run(true)}>{t("reports.uploadAnyway")}</button>
            </div>
          </div>
        )}
        <ErrorMessage error={save.error ?? catalog.error ?? assignments.error} />
        <div className="form-actions">
          <button type="button" onClick={onClose}>{t("common.cancel")}</button>
          <button type="submit" className="primary" disabled={save.busy || !(ids || canQueue) || !versionId || !schoolId}>
            {submitNow ? t("reports.uploadAndSubmit") : t("reports.saveDraft")}
          </button>
        </div>
      </form>
    </Modal>
  );
}
