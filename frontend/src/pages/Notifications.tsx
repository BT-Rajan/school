import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { api } from "../api";
import { ErrorMessage, PageHeader, useAction } from "../components";
import { formatDateTime } from "../format";
import { currentSubscription, disablePush, enablePush, pushSupported, serverKey } from "../push";
import { useSession } from "../session";
import type { NotificationItem, NotificationPreference, Role } from "../types";

interface Inbox {
  items: NotificationItem[];
  unread: number;
}

/** Polled once a minute while signed in; the badge in the header reads the same query. */
export function useInbox(enabled: boolean) {
  return useQuery({
    queryKey: ["notifications"],
    queryFn: () => api<Inbox>("/api/notifications"),
    enabled,
    refetchInterval: 60_000,
  });
}

/** Where a notice leads, when it is about one record. */
function target(n: NotificationItem, role: Role | undefined): string | null {
  const p = n.payload;
  if (typeof p.request_id === "number") return `/requests/${p.request_id}`;
  if (typeof p.document_id === "number") return `/reports/${p.document_id}`;
  if (typeof p.evaluation_id === "number") return `/evaluations/${p.evaluation_id}`;
  if (typeof p.form_id === "number") {
    return role === "form_author" || role === "district_admin" ? `/forms/${p.form_id}` : "/evaluations";
  }
  if (n.type === "reports_overdue") return "/reports";
  if (n.type.startsWith("assignment_")) return "/dashboard";
  return null;
}

/** FR-N1, FR-N4: the notification center and per-type, per-channel choices. */
export default function Notifications() {
  const { t, i18n } = useTranslation();
  const { me, district } = useSession();
  const tz = district?.time_zone ?? "UTC";
  const client = useQueryClient();
  const inbox = useInbox(true);
  const prefs = useQuery({
    queryKey: ["notification-preferences"],
    queryFn: () => api<NotificationPreference[]>("/api/notifications/preferences"),
  });
  const refresh = () => client.invalidateQueries({ queryKey: ["notifications"] });
  const markRead = useAction(async (id: number) => {
    await api(`/api/notifications/${id}/read`, { method: "POST" });
    await refresh();
  });
  const markAll = useAction(async () => {
    await api("/api/notifications/read-all", { method: "POST" });
    await refresh();
  });
  const setPref = useAction(async (type: string, channel: "in_app" | "email" | "push", enabled: boolean) => {
    await api("/api/notifications/preferences", { method: "PUT", body: { type, channel, enabled } });
    await client.invalidateQueries({ queryKey: ["notification-preferences"] });
  });
  const lang = i18n.language === "ar" ? "ar" : "en";
  const key = useQuery({ queryKey: ["push-key"], queryFn: serverKey, enabled: pushSupported(), staleTime: Infinity });
  const channels: ("in_app" | "email" | "push")[] = key.data ? ["in_app", "email", "push"] : ["in_app", "email"];
  const channelLabel = { in_app: t("notifications.inApp"), email: t("notifications.email"), push: t("notifications.push") };
  return (
    <>
      <PageHeader title={t("notifications.title")}>
        <button type="button" disabled={!inbox.data?.unread || markAll.busy} onClick={() => void markAll.run()}>
          {t("notifications.markAllRead")}
        </button>
      </PageHeader>
      <ErrorMessage error={inbox.error ?? markRead.error ?? markAll.error} />
      <ul className="notifications">
        {inbox.data?.items.map((n) => {
          const to = target(n, me?.role);
          return (
            <li key={n.id} className={n.read ? "" : "unread"}>
              <div dir="auto">{to ? <Link to={to} onClick={() => !n.read && void markRead.run(n.id)}>{n.text[lang]}</Link> : n.text[lang]}</div>
              <div className="hint ltr">{formatDateTime(n.created_at, tz)}</div>
              {!n.read && (
                <button type="button" className="link" onClick={() => void markRead.run(n.id)}>{t("notifications.markRead")}</button>
              )}
            </li>
          );
        })}
      </ul>
      {inbox.data?.items.length === 0 && <p className="hint">{t("notifications.empty")}</p>}

      {key.data && <DevicePush publicKey={key.data} />}

      <div className="card">
        <h2>{t("notifications.preferences")}</h2>
        <p className="hint">{t("notifications.preferencesHint")}</p>
        <ErrorMessage error={prefs.error ?? setPref.error} />
        <div className="table-wrap" tabIndex={0}>
          <table>
            <thead>
              <tr>
                <th>{t("notifications.type")}</th>
                {channels.map((c) => <th key={c}>{channelLabel[c]}</th>)}
              </tr>
            </thead>
            <tbody>
              {prefs.data?.map((p) => (
                <tr key={p.type}>
                  <td>{t(`notifications.types.${p.type}`, { defaultValue: p.type })}</td>
                  {channels.map((channel) => (
                    <td key={channel}>
                      <input type="checkbox" checked={p[channel]} disabled={setPref.busy}
                        aria-label={`${t(`notifications.types.${p.type}`, { defaultValue: p.type })}: ${channelLabel[channel]}`}
                        onChange={(e) => void setPref.run(p.type, channel, e.target.checked)} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

/** FR-N3: turn push notices on or off for this browser. */
function DevicePush({ publicKey }: { publicKey: string }) {
  const { t } = useTranslation();
  const subscription = useQuery({ queryKey: ["push-subscription"], queryFn: currentSubscription });
  const client = useQueryClient();
  const [denied, setDenied] = useState(false);
  const toggle = useAction(async () => {
    if (subscription.data) await disablePush();
    else setDenied(!(await enablePush(publicKey)));
    await client.invalidateQueries({ queryKey: ["push-subscription"] });
  });
  return (
    <div className="card">
      <h2>{t("notifications.device")}</h2>
      <p className="hint">{subscription.data ? t("notifications.pushOn") : t("notifications.pushOff")}</p>
      <button type="button" disabled={toggle.busy || subscription.isLoading} onClick={() => void toggle.run()}>
        {subscription.data ? t("notifications.turnOff") : t("notifications.turnOn")}
      </button>
      {denied && <p className="field-error">{t("notifications.pushDenied")}</p>}
      <ErrorMessage error={toggle.error} />
    </div>
  );
}
