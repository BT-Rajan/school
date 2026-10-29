import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { api } from "../api";
import { ErrorMessage, Notice, TextField, useAction } from "../components";
import { CodeInput } from "./mfa";

export default function ResetPassword() {
  const { t } = useTranslation();
  const [email, setEmail] = useState("");
  const [challenge, setChallenge] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [secondCode, setSecondCode] = useState("");
  const [done, setDone] = useState(false);
  const [mismatch, setMismatch] = useState(false);

  const request = useAction(async () => {
    const result = await api<{ challenge: string }>("/api/auth/password-reset/request", {
      method: "POST",
      body: { email },
    });
    setChallenge(result.challenge);
  });
  const complete = useAction(async () => {
    await api("/api/auth/password-reset/complete", {
      method: "POST",
      body: { challenge, code, new_password: password, second_code: secondCode || null },
    });
    setDone(true);
  });

  const onRequest = (e: FormEvent) => {
    e.preventDefault();
    void request.run();
  };
  const onComplete = (e: FormEvent) => {
    e.preventDefault();
    setMismatch(password !== confirm);
    if (password === confirm) void complete.run();
  };

  return (
    <div className="card narrow">
      <h1>{t("reset.title")}</h1>
      {done ? (
        <>
          <Notice>{t("reset.done")}</Notice>
          <Link to="/login">{t("reset.toLogin")}</Link>
        </>
      ) : !challenge ? (
        <form onSubmit={onRequest}>
          <p>{t("reset.intro")}</p>
          <TextField label={t("login.email")} type="email" value={email} onChange={setEmail} required dir="ltr" />
          <ErrorMessage error={request.error} />
          <div className="form-actions">
            <Link to="/login">{t("reset.toLogin")}</Link>
            <button className="primary" type="submit" disabled={request.busy}>
              {t("reset.send")}
            </button>
          </div>
        </form>
      ) : (
        <form onSubmit={onComplete}>
          <CodeInput label={t("reset.code")} value={code} onChange={setCode} />
          <TextField label={t("reset.newPassword")} type="password" value={password} onChange={setPassword}
            autoComplete="new-password" required />
          <TextField label={t("reset.confirmPassword")} type="password" value={confirm} onChange={setConfirm}
            autoComplete="new-password" required />
          <TextField label={t("reset.secondCode")} hint={t("reset.secondCodeHint")} value={secondCode}
            onChange={(v) => setSecondCode(v.replace(/\D/g, "").slice(0, 6))} inputMode="numeric" dir="ltr" />
          {mismatch && <div className="alert alert-error">{t("reset.mismatch")}</div>}
          <ErrorMessage error={complete.error} />
          <div className="form-actions">
            <button className="primary" type="submit" disabled={complete.busy || code.length !== 6}>
              {t("reset.submit")}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
