import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api";
import { ErrorMessage, Modal, Notice, PageHeader, TextField, useAction } from "../components";
import { formatDateTime } from "../format";
import { useSession } from "../session";
import type { Me } from "../types";
import { CodeInput, type Confirmed, EnrollAuthenticator, type Enrollment, RecoveryCodes } from "./mfa";

interface SessionRow {
  id: number;
  created_at: string;
  last_seen_at: string;
  ip: string | null;
  user_agent: string | null;
  current: boolean;
}

type Dialog = null | "totp" | "email" | "codes";

export default function Account() {
  const { t } = useTranslation();
  const { me, district } = useSession();
  const client = useQueryClient();
  const tz = district?.time_zone ?? "UTC";
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: () => api<SessionRow[]>("/api/auth/sessions") });

  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [changed, setChanged] = useState(false);
  const change = useAction(async () => {
    await api("/api/auth/password", { method: "POST", body: { current_password: current, new_password: next } });
    setCurrent("");
    setNext("");
    setChanged(true);
    void sessions.refetch();
  });

  const [dialog, setDialog] = useState<Dialog>(null);
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [enrollment, setEnrollment] = useState<Enrollment | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);
  const closeDialog = () => {
    setDialog(null);
    setPassword("");
    setCode("");
    setEnrollment(null);
    setCodes(null);
  };
  const startTotp = useAction(async () => {
    setEnrollment(await api<Enrollment>("/api/auth/mfa/totp/start", { method: "POST", body: { password } }));
  });
  const toEmail = useAction(async () => {
    client.setQueryData(["me"], await api<Me>("/api/auth/mfa/email", { method: "POST", body: { password, code } }));
    closeDialog();
  });
  const newCodes = useAction(async () => {
    setCodes(await api<string[]>("/api/auth/mfa/recovery-codes", { method: "POST", body: { password, code } }));
  });
  const revoke = useAction(async (id: number) => {
    await api(`/api/auth/sessions/${id}`, { method: "DELETE" });
    void sessions.refetch();
  });

  if (!me) return null;
  const onPassword = (e: FormEvent) => {
    e.preventDefault();
    void change.run();
  };

  return (
    <>
      <PageHeader title={t("account.title")} />
      <section className="card">
        <h2>{t("account.profile")}</h2>
        <p>
          {me.name} · <span className="ltr">{me.email}</span> · {t(`roles.${me.role}`)}
        </p>
      </section>

      <section className="card">
        <h2>{t("account.mfa")}</h2>
        <p>{me.mfa_method === "totp" ? t("account.mfaTotp") : t("account.mfaEmail")}</p>
        <div className="form-actions" style={{ justifyContent: "flex-start" }}>
          {me.mfa_method === "email" && (
            <button type="button" onClick={() => setDialog("totp")}>{t("account.switchToTotp")}</button>
          )}
          {me.mfa_method === "totp" && (
            <>
              <button type="button" onClick={() => setDialog("codes")}>{t("account.regenerate")}</button>
              {!me.totp_required && (
                <button type="button" onClick={() => setDialog("email")}>{t("account.switchToEmail")}</button>
              )}
            </>
          )}
        </div>
      </section>

      <form className="card" onSubmit={onPassword}>
        <h2>{t("account.password")}</h2>
        <TextField label={t("account.currentPassword")} type="password" value={current} onChange={setCurrent}
          autoComplete="current-password" required />
        <TextField label={t("account.newPassword")} type="password" value={next} onChange={setNext}
          autoComplete="new-password" required />
        {changed && <Notice>{t("account.changed")}</Notice>}
        <ErrorMessage error={change.error} />
        <div className="form-actions">
          <button className="primary" type="submit" disabled={change.busy}>{t("common.save")}</button>
        </div>
      </form>

      <section className="card">
        <h2>{t("account.sessions")}</h2>
        <ErrorMessage error={revoke.error} />
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t("account.started")}</th>
                <th>{t("account.lastSeen")}</th>
                <th>IP</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {sessions.data?.map((s) => (
                <tr key={s.id}>
                  <td className="ltr">{formatDateTime(s.created_at, tz)}</td>
                  <td className="ltr">{formatDateTime(s.last_seen_at, tz)}</td>
                  <td className="ltr" title={s.user_agent ?? ""}>{s.ip}</td>
                  <td>
                    {s.current ? (
                      t("account.thisDevice")
                    ) : (
                      <button type="button" onClick={() => void revoke.run(s.id)}>{t("account.revoke")}</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {dialog && (
        <Modal title={t("account.mfa")} onClose={closeDialog}>
          {codes ? (
            <RecoveryCodes codes={codes} onDone={closeDialog} />
          ) : enrollment ? (
            <EnrollAuthenticator
              enrollment={enrollment}
              onDone={(result: Confirmed) => {
                client.setQueryData(["me"], result.me);
                setCodes(result.recovery_codes);
              }}
            />
          ) : (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void (dialog === "totp" ? startTotp.run() : dialog === "email" ? toEmail.run() : newCodes.run());
              }}
            >
              <TextField label={t("account.passwordPrompt")} type="password" value={password} onChange={setPassword}
                autoComplete="current-password" required />
              {dialog !== "totp" && <CodeInput label={t("account.codePrompt")} value={code} onChange={setCode} />}
              <ErrorMessage error={startTotp.error ?? toEmail.error ?? newCodes.error} />
              <div className="form-actions">
                <button type="button" onClick={closeDialog}>{t("common.cancel")}</button>
                <button className="primary" type="submit">{t("login.submit")}</button>
              </div>
            </form>
          )}
        </Modal>
      )}
    </>
  );
}
