import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { api } from "../api";
import { ErrorMessage, PageHeader, StatusBadge } from "../components";
import { formatDate, formatDateTime } from "../format";
import { useSession } from "../session";
import type { Assignment, DocumentStatus, SupervisorDashboard } from "../types";

const COUNTED: DocumentStatus[] = ["draft", "submitted", "viewed", "acknowledged", "returned", "withdrawn"];

/** FR-D44, FR-L9: a supervisor's own reports, what came back, which schools are covered, and who opened what. */
export default function Dashboard() {
  const { t, i18n } = useTranslation();
  const { district } = useSession();
  const tz = district?.time_zone ?? "UTC";
  const data = useQuery({ queryKey: ["dashboard"], queryFn: () => api<SupervisorDashboard>("/api/documents/dashboard") });
  const assignments = useQuery({ queryKey: ["my-assignments"], queryFn: () => api<Assignment[]>("/api/me/assignments") });
  const d = data.data;
  const busiest = Math.max(1, ...(d?.per_month.map((m) => m.count) ?? [1]));
  return (
    <>
      <PageHeader title={t("dashboard.title")}>
        <Link to="/reports" className="button-like">{t("reports.mine")}</Link>
      </PageHeader>
      <ErrorMessage error={data.error ?? assignments.error} />
      {(data.isLoading || assignments.isLoading) && <p>{t("common.loading")}</p>}
      <div className="card">
        <h2>{t("dashboard.mySchools")}</h2>
        <ul className="chips">
          {assignments.data?.map((a) => (
            <li key={a.id} className="chip">
              <span className="ltr">{a.school.code}</span> · {a.school.name} <StatusBadge status={a.state} />
              <span className="hint ltr">{formatDate(a.start_date)}{a.end_date ? ` – ${formatDate(a.end_date)}` : ""}</span>
            </li>
          ))}
        </ul>
        {assignments.data?.length === 0 && <p className="hint">{t("dashboard.noSchools")}</p>}
      </div>
      {d && (
        <>
          <div className="stats">
            {COUNTED.map((s) => (
              <div key={s} className="stat">
                <div className="stat-value">{d.counts[s] ?? 0}</div>
                <div className="stat-label">{t(`status.${s}`)}</div>
              </div>
            ))}
          </div>
          {d.returned.length > 0 && (
            <div className="card">
              <h2>{t("dashboard.returned")}</h2>
              <ul>
                {d.returned.map((r) => (
                  <li key={r.id}>
                    <Link to={`/reports/${r.id}`} dir="auto">{r.title}</Link> · {r.school.name}
                    {r.review_comment && <p className="hint" dir="auto">{r.review_comment}</p>}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="card">
            <h2>{t("dashboard.coverage")}</h2>
            {d.coverage.length === 0 && <p className="hint">{t("dashboard.noOpenReports")}</p>}
            {d.coverage.map((c) => (
              <div key={c.report.version_id} className="coverage">
                <h3>
                  <span className="ltr">{c.report.code} {c.report.version_code}</span> ·{" "}
                  {i18n.language === "ar" ? c.report.title_ar : c.report.title_en}
                </h3>
                <ul className="chips">
                  {c.schools.map((s) => (
                    <li key={s.id} className={`chip ${s.covered ? "chip-ok" : "chip-missing"}`}>
                      {s.covered ? "✓" : "○"} {s.name}
                      <span className="visually-hidden">{s.covered ? t("dashboard.covered") : t("dashboard.notCovered")}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
          <div className="card">
            <h2>{t("dashboard.perMonth")}</h2>
            <ul className="bars">
              {d.per_month.map((m) => (
                <li key={m.month}>
                  <span className="ltr bar-label">{Number(m.month.slice(5))}/{m.month.slice(0, 4)}</span>
                  <span className="bar" style={{ inlineSize: `${(m.count / busiest) * 100}%` }} />
                  <span className="bar-value">{m.count}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="card">
            <h2>{t("reports.accessHistory")}</h2>
            {d.access_history.length === 0 && <p className="hint">{t("reports.noAccess")}</p>}
            <ul className="timeline">
              {d.access_history.map((a, i) => (
                <li key={i}>
                  <Link to={`/reports/${a.document_id}`} dir="auto">{a.title ?? `#${a.document_id}`}</Link>:{" "}
                  {t(`reports.events.${a.action}`, { defaultValue: a.action })} · {a.by} ({t(`roles.${a.role}`)}) ·{" "}
                  <span className="ltr">{formatDateTime(a.at, tz)}</span>
                </li>
              ))}
            </ul>
          </div>
        </>
      )}
    </>
  );
}
