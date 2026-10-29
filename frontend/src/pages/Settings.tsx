import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api";
import { ErrorMessage, Notice, PageHeader, TextField, useAction } from "../components";
import { formatDateTime } from "../format";
import { useSession } from "../session";
import type { StaffUser } from "../types";

interface AdminSettings {
  name_en: string;
  name_ar: string;
  time_zone: string;
  settings: Record<string, string | number>;
  version: number;
}

const KEYS = [
  "mail_daily_limit",
  "mail_reserve_fraction",
  "invitation_daily_cap",
  "digest_time",
  "session_idle_hours",
  "custom_field_limit",
  "upload_max_mb",
  "upload_max_pages",
  "upload_rate_per_hour",
  "storage_quota_mb_per_user",
] as const;

export default function Settings() {
  const { t } = useTranslation();
  const { district } = useSession();
  const client = useQueryClient();
  const current = useQuery({ queryKey: ["admin-settings"], queryFn: () => api<AdminSettings>("/api/admin/settings") });
  const locked = useQuery({ queryKey: ["locked"], queryFn: () => api<StaffUser[]>("/api/admin/locked-accounts") });
  const [nameEn, setNameEn] = useState("");
  const [nameAr, setNameAr] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!current.data) return;
    setNameEn(current.data.name_en);
    setNameAr(current.data.name_ar);
    setValues(Object.fromEntries(KEYS.map((k) => [k, String(current.data.settings[k] ?? "")])));
  }, [current.data]);

  const save = useAction(async () => {
    await api("/api/admin/settings", {
      method: "PATCH",
      body: { version: current.data!.version, name_en: nameEn, name_ar: nameAr, settings: values },
    });
    setSaved(true);
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

  return (
    <>
      <PageHeader title={t("settings.title")} />
      <form className="card" onSubmit={onSubmit}>
        <div className="form-grid">
          <TextField label={t("settings.nameEn")} value={nameEn} onChange={setNameEn} required dir="ltr" />
          <TextField label={t("settings.nameAr")} value={nameAr} onChange={setNameAr} required dir="rtl" />
          {KEYS.map((key) => (
            <TextField key={key} label={t(`settings.${key}`)} value={values[key] ?? ""} dir="ltr"
              onChange={(v) => setValues((s) => ({ ...s, [key]: v }))} required />
          ))}
        </div>
        {saved && <Notice>{t("common.saved")}</Notice>}
        <ErrorMessage error={current.error ?? save.error} />
        <div className="form-actions">
          <button className="primary" type="submit" disabled={!current.data || save.busy}>{t("common.save")}</button>
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
                    <td>
                      {t("settings.until")} <span className="ltr">{formatDateTime(u.locked_until, district?.time_zone ?? "UTC")}</span>
                    </td>
                    <td>
                      <button type="button" onClick={() => void unlock.run(u.id)}>{t("staff.unlock")}</button>
                    </td>
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
