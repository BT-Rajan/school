import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api";
import { ErrorMessage, Notice, PageHeader, SelectField, TextField, useAction } from "../components";
import { formatDateTime } from "../format";
import { useSession } from "../session";
import type { Role, StaffUser } from "../types";

type Defaults = Record<string, Partial<Record<Channel, boolean>>>;
type Channel = "in_app" | "email" | "push";
const CHANNELS: Channel[] = ["in_app", "email", "push"];
const ROLES: Role[] = ["district_admin", "form_author", "cluster_head", "supervisor", "teacher"];

interface AdminSettings {
  code: string;
  name_en: string;
  name_ar: string;
  default_locale: "en" | "ar";
  time_zone: string;
  date_format: string;
  settings: Record<string, unknown> & {
    enabled_locales: string[];
    totp_required_roles: Role[];
    notification_defaults: Defaults;
  };
  logo: boolean;
  mail_provider: string;
  mail_sender: string;
  notice_types: string[];
  version: number;
}

interface FailedSignIn {
  at: string;
  action: string;
  user: { id: number; name: string; email: string } | null;
  reason: string | null;
  ip: string | null;
}

// Plain fields, grouped as on the screen (FR-AD1).
const GROUPS: { title: string; keys: string[] }[] = [
  { title: "security", keys: ["session_idle_hours"] },
  { title: "mail", keys: ["mail_sender_name", "mail_daily_limit", "mail_reserve_fraction", "invitation_daily_cap", "digest_time"] },
  { title: "audit", keys: ["audit_retention_years", "audit_verify_time"] },
  {
    title: "documents",
    keys: ["document_retention_years", "acknowledge_overdue_days", "upload_max_mb", "upload_max_pages", "upload_rate_per_hour", "storage_quota_mb_per_user", "custom_field_limit"],
  },
];
const TEXT_KEYS = new Set(["mail_sender_name", "digest_time", "audit_verify_time"]);

export default function Settings() {
  const { t } = useTranslation();
  const { district } = useSession();
  const tz = district?.time_zone ?? "UTC";
  const client = useQueryClient();
  const current = useQuery({ queryKey: ["admin-settings"], queryFn: () => api<AdminSettings>("/api/admin/settings") });
  const locked = useQuery({ queryKey: ["locked"], queryFn: () => api<StaffUser[]>("/api/admin/locked-accounts") });
  const failed = useQuery({ queryKey: ["failed-sign-ins"], queryFn: () => api<FailedSignIn[]>("/api/admin/failed-sign-ins") });
  const [code, setCode] = useState("");
  const [nameEn, setNameEn] = useState("");
  const [nameAr, setNameAr] = useState("");
  const [timeZone, setTimeZone] = useState("");
  const [defaultLocale, setDefaultLocale] = useState("en");
  const [arabic, setArabic] = useState(true);
  const [totpRoles, setTotpRoles] = useState<Role[]>([]);
  const [defaults, setDefaults] = useState<Defaults>({});
  const [values, setValues] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    const d = current.data;
    if (!d) return;
    setCode(d.code);
    setNameEn(d.name_en);
    setNameAr(d.name_ar);
    setTimeZone(d.time_zone);
    setDefaultLocale(d.default_locale);
    setArabic(d.settings.enabled_locales.includes("ar"));
    setTotpRoles(d.settings.totp_required_roles);
    setDefaults(d.settings.notification_defaults ?? {});
    setValues(Object.fromEntries(GROUPS.flatMap((g) => g.keys).map((k) => [k, String(d.settings[k] ?? "")])));
  }, [current.data]);

  const save = useAction(async () => {
    const plain = Object.fromEntries(
      Object.entries(values).map(([k, v]) => [k, TEXT_KEYS.has(k) ? v : Number(v)]),
    );
    await api("/api/admin/settings", {
      method: "PATCH",
      body: {
        version: current.data!.version,
        code,
        name_en: nameEn,
        name_ar: nameAr,
        time_zone: timeZone,
        default_locale: defaultLocale,
        settings: {
          ...plain,
          enabled_locales: arabic ? ["en", "ar"] : ["en"],
          totp_required_roles: totpRoles,
          notification_defaults: defaults,
        },
      },
    });
    setSaved(true);
    await current.refetch();
    await client.invalidateQueries({ queryKey: ["district"] });
  });
  const logo = useAction(async (file: File) => {
    const form = new FormData();
    form.append("file", file, file.name);
    await api("/api/admin/logo", { method: "PUT", form });
    await current.refetch();
    await client.invalidateQueries({ queryKey: ["district"] });
  });
  const unlock = useAction(async (id: number) => {
    await api(`/api/users/${id}/unlock`, { method: "POST" });
    await locked.refetch();
  });

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    setSaved(false);
    void save.run();
  };
  const toggleDefault = (type: string, channel: Channel, on: boolean) =>
    setDefaults((d) => ({ ...d, [type]: { ...d[type], [channel]: on } }));
  const data = current.data;
  const channelLabel = { in_app: t("notifications.inApp"), email: t("notifications.email"), push: t("notifications.push") };

  return (
    <>
      <PageHeader title={t("settings.title")} />
      <form onSubmit={onSubmit}>
        <div className="card">
          <h2>{t("settings.district")}</h2>
          <div className="form-grid">
            <TextField label={t("settings.code")} value={code} onChange={setCode} required dir="ltr" />
            <TextField label={t("settings.nameEn")} value={nameEn} onChange={setNameEn} required dir="ltr" />
            <TextField label={t("settings.nameAr")} value={nameAr} onChange={setNameAr} required dir="rtl" />
            <TextField label={t("settings.timeZone")} value={timeZone} onChange={setTimeZone} required dir="ltr" hint={t("settings.timeZoneHint")} />
            <SelectField label={t("settings.defaultLocale")} value={defaultLocale} onChange={setDefaultLocale}
              options={[{ value: "en", label: "English" }, ...(arabic ? [{ value: "ar", label: "العربية" }] : [])]} />
          </div>
          <p className="hint">{t("settings.dateFormatHint", { format: data?.date_format ?? "D/MM/YYYY" })}</p>
          <fieldset className="field">
            <legend>{t("settings.languages")}</legend>
            <label className="check"><input type="checkbox" checked disabled /> English</label>
            <label className="check">
              <input type="checkbox" checked={arabic} onChange={(e) => { setArabic(e.target.checked); if (!e.target.checked) setDefaultLocale("en"); }} /> العربية
            </label>
          </fieldset>
          <div className="field">
            <span className="label">{t("settings.logo")}</span>
            {data?.logo && <img className="logo-preview" src={`/api/district/logo?v=${data.version}`} alt={t("settings.logoAlt")} />}
            <label className="button-like">
              {data?.logo ? t("settings.logoReplace") : t("settings.logoUpload")}
              <input type="file" className="visually-hidden" accept="image/png,image/jpeg"
                onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void logo.run(f); }} />
            </label>
            <ErrorMessage error={logo.error} />
          </div>
        </div>

        <div className="card">
          <h2>{t("settings.groups.security")}</h2>
          <fieldset className="field">
            <legend>{t("settings.totpRoles")}</legend>
            {ROLES.map((r) => (
              <label key={r} className="check">
                <input type="checkbox" checked={totpRoles.includes(r)} disabled={r === "district_admin"}
                  onChange={(e) => setTotpRoles((list) => (e.target.checked ? [...list, r] : list.filter((x) => x !== r)))} />{" "}
                {t(`roles.${r}`)}
              </label>
            ))}
          </fieldset>
        </div>

        {GROUPS.map((g) => (
          <div key={g.title} className="card">
            {g.title !== "security" && <h2>{t(`settings.groups.${g.title}`)}</h2>}
            {g.title === "mail" && data && (
              <p className="hint">{t("settings.mailProvider", { provider: data.mail_provider, sender: data.mail_sender })}</p>
            )}
            <div className="form-grid">
              {g.keys.map((key) => (
                <TextField key={key} label={t(`settings.keys.${key}`)} value={values[key] ?? ""} dir="ltr"
                  onChange={(v) => setValues((s) => ({ ...s, [key]: v }))} required={key !== "mail_sender_name"} />
              ))}
            </div>
          </div>
        ))}

        <div className="card">
          <h2>{t("settings.groups.notifications")}</h2>
          <p className="hint">{t("settings.noticeDefaultsHint")}</p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t("settings.notice")}</th>
                  {CHANNELS.map((c) => <th key={c}>{channelLabel[c]}</th>)}
                </tr>
              </thead>
              <tbody>
                {(data?.notice_types ?? []).map((type) => (
                  <tr key={type}>
                    <td>{t(`notifications.types.${type}`, { defaultValue: type })}</td>
                    {CHANNELS.map((c) => (
                      <td key={c}>
                        <input type="checkbox" checked={defaults[type]?.[c] ?? true}
                          aria-label={`${t(`notifications.types.${type}`, { defaultValue: type })}: ${channelLabel[c]}`}
                          onChange={(e) => toggleDefault(type, c, e.target.checked)} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {saved && <Notice>{t("common.saved")}</Notice>}
        <ErrorMessage error={current.error ?? save.error} />
        <div className="form-actions">
          <button className="primary" type="submit" disabled={!data || save.busy}>{t("common.save")}</button>
        </div>
      </form>

      <section className="card">
        <h2>{t("settings.locked")}</h2>
        <ErrorMessage error={unlock.error} />
        {locked.data?.length === 0 && <p>{t("settings.noneLocked")}</p>}
        {!!locked.data?.length && (
          <div className="table-wrap">
            <table>
              <tbody>
                {locked.data.map((u) => (
                  <tr key={u.id}>
                    <td>{u.name}</td>
                    <td className="ltr">{u.email}</td>
                    <td>{t("settings.until")} <span className="ltr">{formatDateTime(u.locked_until, tz)}</span></td>
                    <td><button type="button" onClick={() => void unlock.run(u.id)}>{t("staff.unlock")}</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card">
        <h2>{t("settings.failed")}</h2>
        {failed.data?.length === 0 && <p>{t("settings.noneFailed")}</p>}
        {!!failed.data?.length && (
          <div className="table-wrap">
            <table>
              <thead><tr><th>{t("settings.when")}</th><th>{t("settings.who")}</th><th>{t("settings.what")}</th><th>IP</th></tr></thead>
              <tbody>
                {failed.data.map((f, i) => (
                  <tr key={i}>
                    <td className="ltr">{formatDateTime(f.at, tz)}</td>
                    <td>{f.user ? <>{f.user.name} <span className="hint ltr">{f.user.email}</span></> : t("settings.unknownAccount")}</td>
                    <td>{t(`settings.failure.${f.action}`, { defaultValue: f.action })}</td>
                    <td className="ltr">{f.ip ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
