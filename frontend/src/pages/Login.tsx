import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";

import { api } from "../api";
import { ErrorMessage, Notice, TextField, useAction } from "../components";
import { useSession } from "../session";
import type { Me } from "../types";
import { CodeInput } from "./mfa";

interface Challenge {
  challenge: string;
  method: "email" | "totp";
}

export default function Login() {
  const { t } = useTranslation();
  const { me } = useSession();
  const client = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [challenge, setChallenge] = useState<Challenge | null>(null);
  const [code, setCode] = useState("");
  const [recovery, setRecovery] = useState(false);
  const [recoveryCode, setRecoveryCode] = useState("");
  const [resent, setResent] = useState(false);

  const start = useAction(async () => {
    setChallenge(await api<Challenge>("/api/auth/login", { method: "POST", body: { email, password } }));
    setPassword("");
  });
  const verify = useAction(async () => {
    const result = await api<Me>("/api/auth/login/verify", {
      method: "POST",
      body: recovery ? { challenge: challenge!.challenge, recovery_code: recoveryCode } : { challenge: challenge!.challenge, code },
    });
    client.setQueryData(["me"], result);
    const from = (location.state as { from?: string } | null)?.from ?? "/";
    navigate(from, { replace: true });
  });
  const resend = useAction(async () => {
    await api("/api/auth/login/resend", { method: "POST", body: { challenge: challenge!.challenge } });
    setResent(true);
  });

  if (me) return <Navigate to="/" replace />;

  const onPassword = (e: FormEvent) => {
    e.preventDefault();
    void start.run();
  };
  const onCode = (e: FormEvent) => {
    e.preventDefault();
    void verify.run();
  };

  return (
    <div className="card narrow">
      {!challenge ? (
        <form onSubmit={onPassword}>
          <h1>{t("login.title")}</h1>
          <TextField label={t("login.email")} type="email" value={email} onChange={setEmail} required
            autoComplete="username" dir="ltr" />
          <TextField label={t("login.password")} type="password" value={password} onChange={setPassword} required
            autoComplete="current-password" />
          <ErrorMessage error={start.error} />
          <div className="form-actions">
            <Link to="/reset-password">{t("login.forgot")}</Link>
            <button className="primary" type="submit" disabled={start.busy}>
              {t("login.submit")}
            </button>
          </div>
        </form>
      ) : (
        <form onSubmit={onCode}>
          <h1>{t("login.codeTitle")}</h1>
          <p>{challenge.method === "email" ? t("login.codeSentEmail") : t("login.codeTotp")}</p>
          {recovery ? (
            <TextField label={t("login.recoveryCode")} value={recoveryCode} onChange={setRecoveryCode} dir="ltr"
              autoComplete="off" />
          ) : (
            <CodeInput label={t("login.code")} value={code} onChange={setCode} />
          )}
          {resent && <Notice>{t("login.resent")}</Notice>}
          <ErrorMessage error={verify.error ?? resend.error} />
          <div className="form-actions">
            {challenge.method === "email" && (
              <button type="button" className="link" onClick={() => void resend.run()} disabled={resend.busy}>
                {t("login.resend")}
              </button>
            )}
            {challenge.method === "totp" && (
              <button type="button" className="link" onClick={() => setRecovery(!recovery)}>
                {recovery ? t("login.useCode") : t("login.useRecovery")}
              </button>
            )}
            <button type="button" className="link" onClick={() => { setChallenge(null); setCode(""); }}>
              {t("login.startOver")}
            </button>
            <button className="primary" type="submit" disabled={verify.busy || (!recovery && code.length !== 6)}>
              {t("login.verify")}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
