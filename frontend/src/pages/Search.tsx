import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router-dom";

import { api, query } from "../api";
import { ErrorMessage, PageHeader, StatusBadge } from "../components";
import { formatDate } from "../format";
import type { EvaluationSummary } from "../types";

interface Group<T> { items: T[]; total: number }
interface Results {
  schools?: Group<{ id: number; code: string; name: string; cluster: { code: string } }>;
  teachers?: Group<{ id: number; name: string; staff_id: string; school: { code: string; name: string } }>;
  supervisors?: Group<{ id: number; name: string; staff_id: string | null }>;
  evaluations?: Group<EvaluationSummary>;
  documents?: Group<{ id: number; title: string; status: string; report_date: string; school: { code: string; name: string } }>;
}

/** FR-RP1: one search across what the user may see. */
export default function Search() {
  const { t } = useTranslation();
  const [params] = useSearchParams();
  const q = params.get("q") ?? "";
  const results = useQuery({
    queryKey: ["search", q],
    queryFn: () => api<Results>(`/api/search${query({ q })}`),
    enabled: q.trim().length >= 2,
  });
  const r = results.data;
  const empty = r && Object.values(r).every((g) => !g || g.total === 0);
  // Only the first few of each kind are shown; a longer list is on its own screen.
  const more = (g: Group<unknown>) => g.total > g.items.length && <p className="hint">{t("search.more", { count: g.total })}</p>;
  return (
    <>
      <PageHeader title={t("search.title")} />
      <p>{q.trim().length < 2 ? t("search.tooShort") : t("search.for", { q })}</p>
      <ErrorMessage error={results.error} />
      {empty && <p className="hint">{t("search.none")}</p>}
      {r?.schools && r.schools.total > 0 && (
        <div className="card">
          <h2>{t("nav.schools")}</h2>
          <ul className="timeline">
            {r.schools.items.map((s) => <li key={s.id}><span className="ltr">{s.code}</span> · {s.name} <span className="hint">· {s.cluster.code}</span></li>)}
          </ul>
          {more(r.schools)}
        </div>
      )}
      {r?.teachers && r.teachers.total > 0 && (
        <div className="card">
          <h2>{t("nav.teachers")}</h2>
          <ul className="timeline">
            {r.teachers.items.map((tc) => <li key={tc.id}>{tc.name} <span className="hint ltr">({tc.staff_id})</span> · {tc.school.name}</li>)}
          </ul>
          {more(r.teachers)}
        </div>
      )}
      {r?.supervisors && r.supervisors.total > 0 && (
        <div className="card">
          <h2>{t("nav.supervisors")}</h2>
          <ul className="timeline">
            {r.supervisors.items.map((s) => <li key={s.id}>{s.name} {s.staff_id && <span className="hint ltr">({s.staff_id})</span>}</li>)}
          </ul>
          {more(r.supervisors)}
        </div>
      )}
      {r?.evaluations && r.evaluations.total > 0 && (
        <div className="card">
          <h2>{t("nav.evaluations")}</h2>
          <ul className="timeline">
            {r.evaluations.items.map((e) => (
              <li key={e.id}>
                <Link to={`/evaluations/${e.id}`}>{e.report.code} · {e.school.name}{e.teacher ? ` · ${e.teacher.name}` : ""}</Link>{" "}
                <StatusBadge status={e.status} />
                {e.visit_date && <span className="hint ltr"> · {formatDate(e.visit_date)}</span>}
              </li>
            ))}
          </ul>
          {more(r.evaluations)}
        </div>
      )}
      {r?.documents && r.documents.total > 0 && (
        <div className="card">
          <h2>{t("nav.reports")}</h2>
          <ul className="timeline">
            {r.documents.items.map((d) => (
              <li key={d.id}>
                <Link to={`/reports/${d.id}`} dir="auto">{d.title}</Link> <StatusBadge status={d.status} />
                <span className="hint"> · {d.school.name} · <span className="ltr">{formatDate(d.report_date)}</span></span>
              </li>
            ))}
          </ul>
          {more(r.documents)}
        </div>
      )}
    </>
  );
}
