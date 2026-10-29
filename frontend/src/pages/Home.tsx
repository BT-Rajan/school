import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { api } from "../api";
import { formatDateTime } from "../format";
import { useSession } from "../session";
import type { Role } from "../types";

const SHORTCUTS: Record<Role, { to: string; key: string }[]> = {
  district_admin: [
    { to: "/reports", key: "nav.reports" },
    { to: "/forms", key: "nav.forms" },
    { to: "/assignments", key: "nav.assignments" },
    { to: "/evaluations", key: "nav.evaluations" },
  ],
  form_author: [{ to: "/forms", key: "nav.forms" }],
  cluster_head: [
    { to: "/assignments", key: "nav.assignments" },
    { to: "/reports", key: "nav.reports" },
    { to: "/evaluations", key: "nav.evaluations" },
  ],
  supervisor: [
    { to: "/dashboard", key: "nav.dashboard" },
    { to: "/reports", key: "nav.reports" },
    { to: "/evaluations", key: "nav.evaluations" },
  ],
  teacher: [],
};

interface AdminStatus {
  audit: { ok: boolean; ran_at: string; checked: number; broken_at_seq: number | null; detail: string | null } | null;
  mail: { limit: number; sent_total: number; queued: number };
}

export default function Home() {
  const { t } = useTranslation();
  const { me, district } = useSession();
  const isAdmin = me?.role === "district_admin";
  const status = useQuery({
    queryKey: ["admin-status"],
    queryFn: () => api<AdminStatus>("/api/admin/status"),
    enabled: isAdmin,
  });
  if (!me) return null;
  const audit = status.data?.audit;
  return (
    <>
      <div className="page-header">
        <h1>{t("home.welcome", { name: me.name })}</h1>
      </div>
      <div className="card">
        <p>{t("home.role", { role: t(`roles.${me.role}`) })}</p>
        {SHORTCUTS[me.role].length > 0 ? (
          <div className="page-actions">
            {SHORTCUTS[me.role].map((s) => (
              <Link key={s.to} to={s.to} className="button-like">{t(s.key)}</Link>
            ))}
          </div>
        ) : (
          <p className="hint">{t("home.nothingYet")}</p>
        )}
      </div>
      {isAdmin && status.data && (
        <div className="card">
          {audit ? (
            <div className={`alert ${audit.ok ? "alert-ok" : "alert-error"}`} role={audit.ok ? "status" : "alert"}>
              {audit.ok
                ? t("home.auditOk", { date: formatDateTime(audit.ran_at, district?.time_zone ?? "UTC"), count: audit.checked })
                : t("home.auditBroken", { seq: audit.broken_at_seq, detail: audit.detail })}
            </div>
          ) : (
            <p>{t("home.auditNever")}</p>
          )}
          <p>
            {t("home.mail", { sent: status.data.mail.sent_total, limit: status.data.mail.limit, queued: status.data.mail.queued })}
          </p>
        </div>
      )}
    </>
  );
}
