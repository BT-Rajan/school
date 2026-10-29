import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api, download, query } from "../api";
import { DateField, ErrorMessage, PageHeader, SelectField, StatusBadge, useAction } from "../components";
import { formatDate, formatDateTime } from "../format";
import { useAllSchools, useClusters } from "../hooks";
import { useSession } from "../session";
import type { CatalogReport, Page, Supervisor } from "../types";

const REPORTS = [
  "evaluations_by_school",
  "evaluations_by_supervisor",
  "evaluations_by_period",
  "request_completion",
  "assignment_history",
  "raw_answers",
  "scanned_reports",
] as const;
type Name = (typeof REPORTS)[number];

interface Result {
  name: Name;
  title: string;
  columns: { key: string; label: string }[];
  rows: (string | number | null)[][];
}

interface ZipJob {
  id: number;
  status: string;
  count: number;
  file: { id: number; name: string; size: number; status: string } | null;
  created_at: string;
  finished_at: string | null;
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

/** FR-RP3 to FR-RP5: standard reports on screen, exported to Excel or PDF in either language. */
export default function StandardReports() {
  const { t, i18n } = useTranslation();
  const { me } = useSession();
  const isAdmin = me?.role === "district_admin";
  const manager = isAdmin || me?.role === "cluster_head";
  const [name, setName] = useState<Name>("evaluations_by_school");
  const [versionId, setVersionId] = useState("");
  const [formId, setFormId] = useState("");
  const [clusterId, setClusterId] = useState("");
  const [schoolId, setSchoolId] = useState("");
  const [supervisorId, setSupervisorId] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [group, setGroup] = useState("supervisor");
  const catalog = useQuery({ queryKey: ["catalog"], queryFn: () => api<CatalogReport[]>("/api/catalog") });
  const clusters = useClusters(manager);
  const schools = useAllSchools(true);
  const supervisors = useQuery({
    queryKey: ["supervisors", "all"],
    queryFn: () => api<Page<Supervisor>>("/api/supervisors?page_size=200"),
    enabled: manager,
  });
  const versions = (catalog.data ?? []).flatMap((r) => r.versions.filter((v) => v.status !== "draft" && v.status !== "in_review").map((v) => ({ r, v })));
  const label = (x: (typeof versions)[number]) =>
    `${x.r.report_code} ${x.v.version_code} · ${i18n.language === "ar" ? x.v.title_ar || x.v.title_en : x.v.title_en || x.v.title_ar}`;
  const params = {
    report_version_id: name === "raw_answers" ? undefined : versionId || undefined,
    form_id: name === "raw_answers" ? formId || undefined : undefined,
    cluster_id: clusterId || undefined,
    school_id: schoolId || undefined,
    supervisor_id: supervisorId || undefined,
    date_from: ISO_DATE.test(from) ? from : undefined,
    date_to: ISO_DATE.test(to) ? to : undefined,
    group: name === "scanned_reports" ? group : undefined,
  };
  const ready = name !== "raw_answers" || !!formId;
  const report = useQuery({
    queryKey: ["standard-report", name, params, i18n.language],
    queryFn: () => api<Result>(`/api/standard-reports/${name}${query({ ...params, locale: i18n.language })}`),
    enabled: ready,
  });
  const exportAs = useAction(async (format: "xlsx" | "pdf", locale: "en" | "ar") => {
    await download(`/api/standard-reports/${name}${query({ ...params, format, locale })}`, `${name}-${locale}.${format}`);
  });

  return (
    <>
      <PageHeader title={t("standard.title")} />
      <div className="card">
        <div className="filters">
          <SelectField label={t("standard.report")} value={name} onChange={(v) => setName(v as Name)}
            options={REPORTS.map((r) => ({ value: r, label: t(`standard.names.${r}`) }))} />
          {name === "raw_answers" ? (
            <SelectField label={t("standard.form")} value={formId} onChange={setFormId} placeholder="" required
              options={versions.map((x) => ({ value: String(x.v.form_id), label: label(x) }))} />
          ) : (
            name !== "assignment_history" && (
              <SelectField label={t("reports.reportVersion")} value={versionId} onChange={setVersionId} placeholder={t("common.all")}
                options={versions.map((x) => ({ value: String(x.v.id), label: label(x) }))} />
            )
          )}
          {manager && (
            <SelectField label={t("schools.cluster")} value={clusterId} onChange={setClusterId} placeholder={t("common.all")}
              options={(clusters.data ?? []).map((c) => ({ value: String(c.id), label: `${c.code} · ${c.name}` }))} />
          )}
          <SelectField label={t("schools.school")} value={schoolId} onChange={setSchoolId} placeholder={t("common.all")}
            options={(schools.data ?? []).map((s) => ({ value: String(s.id), label: `${s.code} · ${s.name}` }))} />
          {manager && name !== "request_completion" && (
            <SelectField label={t("roles.supervisor")} value={supervisorId} onChange={setSupervisorId} placeholder={t("common.all")}
              options={(supervisors.data?.items ?? []).map((s) => ({ value: String(s.id), label: s.name }))} />
          )}
          <DateField label={t("standard.from")} value={from} onChange={setFrom} />
          <DateField label={t("standard.to")} value={to} onChange={setTo} />
          {name === "scanned_reports" && (
            <SelectField label={t("standard.groupBy")} value={group} onChange={setGroup}
              options={["supervisor", "school", "report", "period"].map((g) => ({ value: g, label: t(`standard.groups.${g}`) }))} />
          )}
        </div>
        <p className="hint">{t(`standard.about.${name}`)}</p>
        <div className="page-actions">
          <button type="button" disabled={!ready || exportAs.busy} onClick={() => void exportAs.run("xlsx", "en")}>{t("standard.excelEn")}</button>
          <button type="button" disabled={!ready || exportAs.busy} onClick={() => void exportAs.run("xlsx", "ar")}>{t("standard.excelAr")}</button>
          <button type="button" disabled={!ready || exportAs.busy} onClick={() => void exportAs.run("pdf", "en")}>{t("standard.pdfEn")}</button>
          <button type="button" disabled={!ready || exportAs.busy} onClick={() => void exportAs.run("pdf", "ar")}>{t("standard.pdfAr")}</button>
        </div>
        <p className="hint">{t("standard.audited")}</p>
        <ErrorMessage error={exportAs.error ?? report.error} />
      </div>
      {!ready && <p className="hint">{t("standard.chooseForm")}</p>}
      {report.data && (
        <div className="card">
          <h2>{report.data.title}</h2>
          <p className="hint">{t("standard.rows", { count: report.data.rows.length })}</p>
          {report.data.rows.length === 0 ? <p>{t("standard.empty")}</p> : (
            <div className="table-wrap">
              <table>
                <thead><tr>{report.data.columns.map((c) => <th key={c.key}>{c.label}</th>)}</tr></thead>
                <tbody>
                  {report.data.rows.slice(0, 500).map((row, i) => (
                    <tr key={i}>
                      {row.map((v, j) => (
                        <td key={j} dir="auto">{typeof v === "string" && ISO_DATE.test(v) ? formatDate(v) : v ?? ""}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {report.data.rows.length > 500 && <p className="hint">{t("standard.firstRows", { count: 500 })}</p>}
        </div>
      )}
      {isAdmin && <ZipExports params={params} />}
    </>
  );
}

/** FR-RP5: the matching scanned reports as one watermarked ZIP, made in the background. */
function ZipExports({ params }: { params: Record<string, string | undefined> }) {
  const { t } = useTranslation();
  const { district } = useSession();
  const tz = district?.time_zone ?? "UTC";
  const jobs = useQuery({
    queryKey: ["document-exports"],
    queryFn: () => api<ZipJob[]>("/api/document-exports"),
    refetchInterval: (q) => (q.state.data?.some((j) => j.status === "queued" || j.status === "running" || j.file?.status === "pending") ? 2000 : false),
  });
  const start = useAction(async () => {
    await api("/api/document-exports", {
      method: "POST",
      body: {
        report_version_id: params.report_version_id ? Number(params.report_version_id) : null,
        cluster_id: params.cluster_id ? Number(params.cluster_id) : null,
        school_id: params.school_id ? Number(params.school_id) : null,
        supervisor_id: params.supervisor_id ? Number(params.supervisor_id) : null,
        date_from: params.date_from ?? null,
        date_to: params.date_to ?? null,
      },
    });
    await jobs.refetch();
  });
  const fetchFile = useAction(async (job: ZipJob) => {
    const link = await api<{ url: string }>(`/api/files/${job.file!.id}/link`, { method: "POST", body: { disposition: "attachment" } });
    await download(link.url, job.file!.name);
  });
  return (
    <div className="card">
      <h2>{t("standard.zipTitle")}</h2>
      <p className="hint">{t("standard.zipHint")}</p>
      <button type="button" disabled={start.busy} onClick={() => void start.run()}>{t("standard.zipStart")}</button>
      <ErrorMessage error={start.error ?? fetchFile.error} />
      {(jobs.data ?? []).length > 0 && (
        <ul className="timeline">
          {jobs.data!.map((j) => (
            <li key={j.id}>
              <StatusBadge status={j.file?.status === "pending" ? "running" : j.status} /> · {t("standard.zipCount", { count: j.count })} ·{" "}
              <span className="ltr">{formatDateTime(j.created_at, tz)}</span>
              {j.status === "done" && j.file?.status === "clean" && (
                <> · <button type="button" className="link" onClick={() => void fetchFile.run(j)}>{t("standard.zipDownload")}</button></>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
