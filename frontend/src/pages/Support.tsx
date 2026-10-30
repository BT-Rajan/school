import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api, download, query } from "../api";
import { ErrorMessage, Modal, PageHeader, SelectField, TextField, useAction } from "../components";
import { formatDateTime } from "../format";
import { useSession } from "../session";
import { startSupportView } from "../support";
import type { Role } from "../types";

interface Found { id: number; name: string; email: string; role: Role; staff_id: string | null }
interface SupportSession {
  id: number;
  user: { id: number; name: string; email: string; role: Role };
  reason: string;
  started_at: string;
  expires_at: string;
  ended_at: string | null;
  active: boolean;
  views: number;
}

/** FR-AD3 and FR-AD4: viewing a user's screens read-only, and exporting what is held about them. */
export default function Support() {
  const { t } = useTranslation();
  const { district } = useSession();
  const tz = district?.time_zone ?? "UTC";
  const client = useQueryClient();
  const [q, setQ] = useState("");
  const [term, setTerm] = useState("");
  const [viewing, setViewing] = useState<Found | null>(null);
  const [reason, setReason] = useState("");
  const [minutes, setMinutes] = useState("30");
  const found = useQuery({
    queryKey: ["support-users", term],
    queryFn: () => api<Found[]>(`/api/admin/support-users${query({ q: term })}`),
    enabled: term.length >= 2,
  });
  const history = useQuery({ queryKey: ["support-sessions"], queryFn: () => api<SupportSession[]>("/api/admin/support-sessions") });
  const start = useAction(async () => {
    const s = await api<SupportSession>("/api/admin/support-sessions", {
      method: "POST",
      body: { user_id: viewing!.id, reason, minutes: Number(minutes) },
    });
    startSupportView({ id: s.id, name: s.user.name, expires_at: s.expires_at });
    // A fresh start, so everything on screen is fetched again as the user sees it.
    client.clear();
    window.location.assign("/");
  });
  const exportData = useAction(async (u: Found) => {
    if (!window.confirm(t("support.confirmExport", { name: u.name }))) return;
    await download(`/api/admin/users/${u.id}/export`, `person-${u.id}.json`);
  });

  return (
    <>
      <PageHeader title={t("support.title")} />
      <p className="hint">{t("support.intro")}</p>
      <form className="card" role="search" onSubmit={(e) => { e.preventDefault(); setTerm(q.trim()); }}>
        <TextField label={t("support.find")} value={q} onChange={setQ} hint={t("support.findHint")} />
        <button type="submit">{t("support.search")}</button>
        <ErrorMessage error={found.error ?? exportData.error} />
        {found.data && found.data.length === 0 && <p className="hint">{t("search.none")}</p>}
        {!!found.data?.length && (
          <div className="table-wrap">
            <table>
              <tbody>
                {found.data.map((u) => (
                  <tr key={u.id}>
                    <td>{u.name}</td>
                    <td className="ltr">{u.email}</td>
                    <td>{t(`roles.${u.role}`)}</td>
                    <td className="row-actions">
                      <button type="button" onClick={() => { setViewing(u); setReason(""); }}>{t("support.view")}</button>
                      <button type="button" onClick={() => void exportData.run(u)}>{t("support.export")}</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </form>
      <div className="card">
        <h2>{t("support.recent")}</h2>
        {history.data?.length === 0 && <p className="hint">{t("support.none")}</p>}
        <ul className="timeline">
          {(history.data ?? []).map((s) => (
            <li key={s.id}>
              <strong>{s.user.name}</strong> · <span dir="auto">{s.reason}</span>
              <div className="hint">
                <span className="ltr">{formatDateTime(s.started_at, tz)}</span> · {t("support.views", { count: s.views })}
                {s.active && <> · {t("support.activeUntil", { at: formatDateTime(s.expires_at, tz) })}</>}
              </div>
            </li>
          ))}
        </ul>
      </div>
      {viewing && (
        <Modal title={t("support.viewTitle", { name: viewing.name })} onClose={() => setViewing(null)}>
          <form onSubmit={(e) => { e.preventDefault(); void start.run(); }}>
            <p>{t("support.viewHint")}</p>
            <TextField label={t("common.reason")} value={reason} onChange={setReason} required hint={t("support.reasonHint")} />
            <SelectField label={t("support.minutes")} value={minutes} onChange={setMinutes}
              options={["10", "20", "30"].map((m) => ({ value: m, label: t("support.minutesN", { count: Number(m) }) }))} />
            <ErrorMessage error={start.error} />
            <div className="form-actions">
              <button type="button" onClick={() => setViewing(null)}>{t("common.cancel")}</button>
              <button type="submit" className="primary" disabled={start.busy || reason.trim().length < 10}>{t("support.start")}</button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}
