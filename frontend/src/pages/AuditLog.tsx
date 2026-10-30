import { useQuery } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, download, query } from "../api";
import { DateField, ErrorMessage, PageHeader, Pager, SelectField, TextField, useAction } from "../components";
import { formatDateTime } from "../format";
import { useSession } from "../session";

interface Entry {
  seq: number;
  at: string;
  actor: { id: number; name: string | null } | null;
  actor_role: string | null;
  action: string;
  severity: "info" | "warning" | "critical";
  entity_type: string | null;
  entity_id: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  ip: string | null;
  user_agent: string | null;
}

interface Result {
  items: Entry[];
  total: number;
  page: number;
  retention_years: number;
  past_retention: number;
  actions: string[];
}

const PAGE_SIZE = 50;
const ISO = /^\d{4}-\d{2}-\d{2}$/;

/** FR-L5: search the audit log by actor, entity, action and date; exports are audited. */
export default function AuditLog() {
  const { t } = useTranslation();
  const { district } = useSession();
  const tz = district?.time_zone ?? "UTC";
  const [action, setAction] = useState("");
  const [actorId, setActorId] = useState("");
  const [entityType, setEntityType] = useState("");
  const [entityId, setEntityId] = useState("");
  const [severity, setSeverity] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<number | null>(null);
  const filters = {
    action: action || undefined,
    actor_id: /^\d+$/.test(actorId) ? actorId : undefined,
    entity_type: entityType || undefined,
    entity_id: entityId || undefined,
    severity: severity || undefined,
    date_from: ISO.test(from) ? from : undefined,
    date_to: ISO.test(to) ? to : undefined,
  };
  const log = useQuery({
    queryKey: ["audit", filters, page],
    queryFn: () => api<Result>(`/api/admin/audit${query({ ...filters, page, page_size: PAGE_SIZE })}`),
  });
  const exportAs = useAction(async (format: "csv" | "xlsx") => {
    await download(`/api/admin/audit/export${query({ ...filters, format, locale: document.documentElement.lang === "ar" ? "ar" : "en" })}`, `audit-log.${format}`);
  });
  const set = (fn: (v: string) => void) => (v: string) => { fn(v); setPage(1); };
  const data = log.data;
  // Actions grouped by their area ("document.", "login.") make a short first list to pick from.
  const areas = [...new Set((data?.actions ?? []).map((a) => `${a.split(".")[0]}.`))];

  return (
    <>
      <PageHeader title={t("auditLog.title")}>
        <button type="button" disabled={exportAs.busy} onClick={() => void exportAs.run("xlsx")}>{t("auditLog.exportXlsx")}</button>
        <button type="button" disabled={exportAs.busy} onClick={() => void exportAs.run("csv")}>{t("auditLog.exportCsv")}</button>
      </PageHeader>
      <p className="hint">{t("auditLog.intro")}</p>
      {data && data.past_retention > 0 && (
        <div className="alert alert-warn" role="status">{t("auditLog.pastRetention", { count: data.past_retention, years: data.retention_years })}</div>
      )}
      <div className="filters">
        <SelectField label={t("auditLog.action")} value={action} onChange={set(setAction)} placeholder={t("common.all")}
          options={[
            ...areas.map((a) => ({ value: a, label: `${a}*` })),
            ...(data?.actions ?? []).map((a) => ({ value: a, label: a })),
          ]} />
        <TextField label={t("auditLog.actorId")} value={actorId} onChange={set(setActorId)} dir="ltr" inputMode="numeric" />
        <TextField label={t("auditLog.entityType")} value={entityType} onChange={set(setEntityType)} dir="ltr" />
        <TextField label={t("auditLog.entityId")} value={entityId} onChange={set(setEntityId)} dir="ltr" />
        <SelectField label={t("auditLog.severity")} value={severity} onChange={set(setSeverity)} placeholder={t("common.all")}
          options={["info", "warning", "critical"].map((s) => ({ value: s, label: t(`auditLog.severities.${s}`) }))} />
        <DateField label={t("standard.from")} value={from} onChange={set(setFrom)} />
        <DateField label={t("standard.to")} value={to} onChange={set(setTo)} />
      </div>
      <ErrorMessage error={log.error ?? exportAs.error} />
      {data && (
        <>
          <p className="hint">{t("auditLog.count", { count: data.total })}</p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>{t("settings.when")}</th>
                  <th>{t("auditLog.actor")}</th>
                  <th>{t("auditLog.action")}</th>
                  <th>{t("auditLog.entity")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.items.map((e) => (
                  <Fragment key={e.seq}>
                    <tr className={`audit-${e.severity}`}>
                      <td className="ltr">{e.seq}</td>
                      <td className="ltr">{formatDateTime(e.at, tz)}</td>
                      <td>{e.actor ? <>{e.actor.name ?? `#${e.actor.id}`} <span className="hint">{e.actor_role ? t(`roles.${e.actor_role}`, { defaultValue: e.actor_role }) : ""}</span></> : t("auditLog.system")}</td>
                      <td className="ltr">{e.action}</td>
                      <td className="ltr">{e.entity_type ? `${e.entity_type} ${e.entity_id ?? ""}` : ""}</td>
                      <td>
                        <button type="button" className="link" aria-expanded={open === e.seq} onClick={() => setOpen(open === e.seq ? null : e.seq)}>
                          {t("auditLog.details")}
                        </button>
                      </td>
                    </tr>
                    {open === e.seq && (
                      <tr>
                        <td colSpan={6}>
                          <dl className="facts ltr" dir="ltr">
                            {e.before && (<><dt>{t("auditLog.before")}</dt><dd><pre>{JSON.stringify(e.before, null, 2)}</pre></dd></>)}
                            {e.after && (<><dt>{t("auditLog.after")}</dt><dd><pre>{JSON.stringify(e.after, null, 2)}</pre></dd></>)}
                            {e.ip && (<><dt>IP</dt><dd>{e.ip}</dd></>)}
                            {e.user_agent && (<><dt>{t("auditLog.device")}</dt><dd>{e.user_agent}</dd></>)}
                          </dl>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
          <Pager page={page} total={data.total} pageSize={PAGE_SIZE} onPage={setPage} />
        </>
      )}
    </>
  );
}
