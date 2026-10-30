import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { api } from "../api";
import { StatusBadge } from "../components";
import { formatDate, formatDateTime, formatNumber } from "../format";
import { useSession } from "../session";
import type { EvaluationSummary, Role } from "../types";

const SHORTCUTS: Record<Role, { to: string; key: string }[]> = {
  district_admin: [
    { to: "/reports", key: "nav.reports" },
    { to: "/standard-reports", key: "nav.standardReports" },
    { to: "/forms", key: "nav.forms" },
    { to: "/assignments", key: "nav.assignments" },
  ],
  form_author: [{ to: "/forms", key: "nav.forms" }],
  cluster_head: [
    { to: "/assignments", key: "nav.assignments" },
    { to: "/evaluations", key: "nav.evaluations" },
    { to: "/standard-reports", key: "nav.standardReports" },
  ],
  supervisor: [
    { to: "/evaluations", key: "nav.evaluations" },
    { to: "/reports", key: "nav.reports" },
    { to: "/dashboard", key: "nav.dashboard" },
  ],
  teacher: [{ to: "/requests", key: "nav.myRequests" }],
};

interface ReportRef { code: string; version_code: string; title_en: string; title_ar: string }
interface SchoolRef { id: number; code: string; name: string }

interface AdminDash {
  role: "district_admin";
  counts: { clusters: number; schools: number; teachers: number; supervisors: number; overdue_requests: number };
  audit: { ok: boolean; ran_at: string; checked: number; broken_at_seq: number | null } | null;
  inbox: { submitted: number; viewed: number; returned: number; acknowledged: number; overdue: number };
  coverage: { report: ReportRef; form_id: number; schools: number; with_report: number; evaluated: number; end_date: string }[];
  forms: { id: number; report: ReportRef; status: string; start_date: string | null; end_date: string | null }[];
  mail: { limit: number; sent_total: number; queued: number };
  storage: { files: number; bytes: number };
  quarantined: number;
}
interface HeadDash {
  role: "cluster_head";
  unassigned_schools: SchoolRef[];
  without_contact: SchoolRef[];
  progress: (SchoolRef & { drafts: number; submitted: number })[];
  active_forms: number;
  workload: { id: number; name: string; schools: number; drafts: number; submitted_this_month: number }[];
  overdue_requests: number;
  forwarded_reports: number;
}
interface SupervisorDash {
  role: "supervisor";
  upcoming: EvaluationSummary[];
  drafts: EvaluationSummary[];
  draft_count: number;
  completed: number;
  completed_this_month: number;
  overdue_requests: number;
  reports: Record<string, number>;
}
interface TeacherDash {
  role: "teacher";
  pending: { id: number; report: ReportRef; due_date: string; overdue: boolean; status: string; school: SchoolRef }[];
  pending_count: number;
}
type Dash = AdminDash | HeadDash | SupervisorDash | TeacherDash;

/** FR-AD3: admins who viewed this account's screens, shown once at the next sign-in. */
function SupportNotices() {
  const { t } = useTranslation();
  const { me, district, refresh } = useSession();
  const tz = district?.time_zone ?? "UTC";
  const seen = async () => {
    await api("/api/auth/me/support-notices/seen", { method: "POST" });
    await refresh();
  };
  return (
    <div className="alert alert-warn" role="alert">
      <p>{t("support.noticeTitle")}</p>
      <ul>
        {me!.support_notices!.map((n) => (
          <li key={n.id}>
            {t("support.noticeLine", { admin: n.admin, from: formatDateTime(n.started_at, tz), to: formatDateTime(n.ended_at, tz) })}{" "}
            <span dir="auto">“{n.reason}”</span>
          </li>
        ))}
      </ul>
      <button type="button" onClick={() => void seen()}>{t("support.noticeOk")}</button>
    </div>
  );
}

function Stat({ label, value, to, warn }: { label: string; value: number | string; to?: string; warn?: boolean }) {
  const body = (
    <>
      <span className={`stat-value${warn ? " stat-warn" : ""}`}>{typeof value === "number" ? formatNumber(value) : value}</span>
      <span className="stat-label">{label}</span>
    </>
  );
  return to ? <Link to={to} className="stat">{body}</Link> : <div className="stat">{body}</div>;
}

function useReportTitle() {
  const { i18n } = useTranslation();
  return (r: ReportRef) => `${r.code} ${r.version_code} · ${i18n.language === "ar" ? r.title_ar || r.title_en : r.title_en || r.title_ar}`;
}

function bytes(n: number): string {
  if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(1)} GB`;
  return `${(n / 1024 ** 2).toFixed(1)} MB`;
}

/** FR-RP2: each role's dashboard. */
export default function Home() {
  const { t } = useTranslation();
  const { me } = useSession();
  const dash = useQuery({
    queryKey: ["dashboard", "home"],
    queryFn: () => api<Dash>("/api/dashboard"),
    enabled: !!me && me.role !== "form_author",
  });
  if (!me) return null;
  const data = dash.data;
  return (
    <>
      <div className="page-header">
        <h1>{t("home.welcome", { name: me.name })}</h1>
      </div>
      <div className="card">
        <p>{t("home.role", { role: t(`roles.${me.role}`) })}</p>
        <div className="page-actions">
          {SHORTCUTS[me.role].map((s) => (
            <Link key={s.to} to={s.to} className="button-like">{t(s.key)}</Link>
          ))}
        </div>
      </div>
      {!!me.support_notices?.length && <SupportNotices />}
      {data?.role === "district_admin" && <Admin d={data} />}
      {data?.role === "cluster_head" && <Head d={data} />}
      {data?.role === "supervisor" && <Supervisor d={data} />}
      {data?.role === "teacher" && <Teacher d={data} />}
    </>
  );
}

function Admin({ d }: { d: AdminDash }) {
  const { t } = useTranslation();
  const { district } = useSession();
  const title = useReportTitle();
  const tz = district?.time_zone ?? "UTC";
  return (
    <>
      <div className="stats">
        <Stat label={t("nav.clusters")} value={d.counts.clusters} to="/clusters" />
        <Stat label={t("nav.schools")} value={d.counts.schools} to="/schools" />
        <Stat label={t("nav.teachers")} value={d.counts.teachers} to="/teachers" />
        <Stat label={t("nav.supervisors")} value={d.counts.supervisors} to="/supervisors" />
        <Stat label={t("dash.overdueRequests")} value={d.counts.overdue_requests} to="/requests" warn={d.counts.overdue_requests > 0} />
      </div>
      <div className="card">
        <h2>{t("dash.inbox")}</h2>
        <div className="stats">
          <Stat label={t("status.submitted")} value={d.inbox.submitted} to="/reports" />
          <Stat label={t("status.viewed")} value={d.inbox.viewed} to="/reports" />
          <Stat label={t("dash.overdueReview")} value={d.inbox.overdue} warn={d.inbox.overdue > 0} to="/reports" />
          <Stat label={t("status.returned")} value={d.inbox.returned} />
          <Stat label={t("status.acknowledged")} value={d.inbox.acknowledged} />
        </div>
      </div>
      <div className="card">
        <h2>{t("dash.coverage")}</h2>
        {d.coverage.length === 0 ? <p className="hint">{t("dash.noActiveForms")}</p> : (
          <div className="table-wrap" tabIndex={0}>
            <table>
              <thead><tr><th>{t("evaluations.reportVersion")}</th><th>{t("dash.evaluated")}</th><th>{t("dash.withReport")}</th><th>{t("dash.closes")}</th></tr></thead>
              <tbody>
                {d.coverage.map((c) => (
                  <tr key={c.form_id}>
                    <td>{title(c.report)}</td>
                    <td className="ltr">{c.evaluated} / {c.schools}</td>
                    <td className="ltr">{c.with_report} / {c.schools}</td>
                    <td className="ltr">{formatDate(c.end_date)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <div className="card">
        <h2>{t("dash.forms")}</h2>
        {d.forms.length === 0 ? <p className="hint">{t("dash.noForms")}</p> : (
          <ul className="timeline">
            {d.forms.map((f) => (
              <li key={f.id}>
                <Link to={`/forms/${f.id}`}>{title(f.report)}</Link> <StatusBadge status={f.status} />
                {f.start_date && <span className="hint ltr"> · {formatDate(f.start_date)} – {formatDate(f.end_date)}</span>}
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="card">
        <h2>{t("dash.system")}</h2>
        {d.audit ? (
          <div className={`alert ${d.audit.ok ? "alert-ok" : "alert-error"}`} role={d.audit.ok ? "status" : "alert"}>
            {d.audit.ok
              ? t("home.auditOk", { date: formatDateTime(d.audit.ran_at, tz), count: d.audit.checked })
              : t("home.auditBroken", { seq: d.audit.broken_at_seq, detail: "" })}
          </div>
        ) : (
          <p>{t("home.auditNever")}</p>
        )}
        <p>{t("home.mail", { sent: d.mail.sent_total, limit: d.mail.limit, queued: d.mail.queued })}</p>
        <p>{t("dash.storage", { files: formatNumber(d.storage.files), size: bytes(d.storage.bytes) })}</p>
        <p className={d.quarantined ? "field-error" : undefined}>{t("dash.quarantined", { count: d.quarantined })}</p>
      </div>
    </>
  );
}

function SchoolList({ schools }: { schools: SchoolRef[] }) {
  return (
    <ul className="inline-list">
      {schools.map((s) => <li key={s.id}><span className="ltr">{s.code}</span> · {s.name}</li>)}
    </ul>
  );
}

function Head({ d }: { d: HeadDash }) {
  const { t } = useTranslation();
  return (
    <>
      <div className="stats">
        <Stat label={t("dash.unassigned")} value={d.unassigned_schools.length} to="/assignments" warn={d.unassigned_schools.length > 0} />
        <Stat label={t("dash.withoutContact")} value={d.without_contact.length} to="/schools" warn={d.without_contact.length > 0} />
        <Stat label={t("dash.overdueRequests")} value={d.overdue_requests} to="/requests" warn={d.overdue_requests > 0} />
        <Stat label={t("dash.forwarded")} value={d.forwarded_reports} to="/reports" />
      </div>
      {d.unassigned_schools.length > 0 && (
        <div className="card"><h2>{t("dash.unassigned")}</h2><SchoolList schools={d.unassigned_schools} /></div>
      )}
      {d.without_contact.length > 0 && (
        <div className="card"><h2>{t("dash.withoutContact")}</h2><SchoolList schools={d.without_contact} /></div>
      )}
      <div className="card">
        <h2>{t("dash.progress")}</h2>
        <p className="hint">{t("dash.progressHint", { count: d.active_forms })}</p>
        <div className="table-wrap" tabIndex={0}>
          <table>
            <thead><tr><th>{t("schools.school")}</th><th>{t("dash.drafts")}</th><th>{t("status.submitted")}</th></tr></thead>
            <tbody>
              {d.progress.map((p) => (
                <tr key={p.id}><td><span className="ltr">{p.code}</span> · {p.name}</td><td>{p.drafts}</td><td>{p.submitted}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="card">
        <h2>{t("dash.workload")}</h2>
        <div className="table-wrap" tabIndex={0}>
          <table>
            <thead><tr><th>{t("roles.supervisor")}</th><th>{t("nav.schools")}</th><th>{t("dash.drafts")}</th><th>{t("dash.thisMonth")}</th></tr></thead>
            <tbody>
              {d.workload.map((w) => (
                <tr key={w.id}><td>{w.name}</td><td>{w.schools}</td><td>{w.drafts}</td><td>{w.submitted_this_month}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

function EvaluationLinks({ items }: { items: EvaluationSummary[] }) {
  return (
    <ul className="timeline">
      {items.map((e) => (
        <li key={e.id}>
          <Link to={`/evaluations/${e.id}`}>{e.report.code} · {e.school.name}</Link>
          {e.visit_date && <span className="hint ltr"> · {formatDate(e.visit_date)}</span>}
        </li>
      ))}
    </ul>
  );
}

function Supervisor({ d }: { d: SupervisorDash }) {
  const { t } = useTranslation();
  return (
    <>
      <div className="stats">
        <Stat label={t("dash.drafts")} value={d.draft_count} to="/evaluations" />
        <Stat label={t("dash.completed")} value={d.completed} to="/evaluations" />
        <Stat label={t("dash.thisMonth")} value={d.completed_this_month} />
        <Stat label={t("dash.overdueRequests")} value={d.overdue_requests} to="/requests" warn={d.overdue_requests > 0} />
        <Stat label={t("dash.reportsReturned")} value={d.reports.returned ?? 0} to="/reports" warn={(d.reports.returned ?? 0) > 0} />
      </div>
      <div className="card">
        <h2>{t("dash.upcoming")}</h2>
        {d.upcoming.length ? <EvaluationLinks items={d.upcoming} /> : <p className="hint">{t("dash.noUpcoming")}</p>}
      </div>
      {d.drafts.length > 0 && (
        <div className="card"><h2>{t("dash.drafts")}</h2><EvaluationLinks items={d.drafts} /></div>
      )}
    </>
  );
}

function Teacher({ d }: { d: TeacherDash }) {
  const { t } = useTranslation();
  const title = useReportTitle();
  return (
    <div className="card">
      <h2>{t("dash.pending", { count: d.pending_count })}</h2>
      {d.pending.length === 0 ? <p className="hint">{t("dash.nothingPending")}</p> : (
        <ul className="timeline">
          {d.pending.map((r) => (
            <li key={r.id}>
              <Link to={`/requests/${r.id}`}>{title(r.report)}</Link> <StatusBadge status={r.status} />
              <div className={r.overdue ? "field-error" : "hint"}>{t("dash.due", { date: formatDate(r.due_date) })}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
