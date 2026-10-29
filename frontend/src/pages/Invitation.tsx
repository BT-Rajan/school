import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";

import { api } from "../api";
import { ErrorMessage, TextField, useAction } from "../components";
import type { Me } from "../types";
import { type Confirmed, EnrollAuthenticator, type Enrollment, RecoveryCodes } from "./mfa";

interface InvitationInfo {
  name: string;
  email: string;
  role: string;
  totp_required: boolean;
}

export default function Invitation() {
  const { t } = useTranslation();
  const { token = "" } = useParams();
  const navigate = useNavigate();
  const client = useQueryClient();
  const info = useQuery({
    queryKey: ["invitation", token],
    queryFn: () => api<InvitationInfo>(`/api/auth/invitations/${encodeURIComponent(token)}`),
    retry: false,
  });
  const policy = useQuery({
    queryKey: ["password-policy"],
    queryFn: () => api<{ min_length: number }>("/api/auth/password-policy"),
  });
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [method, setMethod] = useState<"email" | "totp" | "">("");
  const [mismatch, setMismatch] = useState(false);
  const [enrollment, setEnrollment] = useState<Enrollment | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);

  const finish = (me: Me) => {
    client.setQueryData(["me"], me);
    navigate("/", { replace: true });
  };
  const accept = useAction(async (chosenMethod: "email" | "totp") => {
    const result = await api<{ me: Me | null; enrollment: Enrollment | null }>(
      `/api/auth/invitations/${encodeURIComponent(token)}/accept`,
      { method: "POST", body: { password, method: chosenMethod } },
    );
    if (result.me) finish(result.me);
    else setEnrollment(result.enrollment);
  });

  if (info.isLoading) return <p>{t("common.loading")}</p>;
  if (info.isError || !info.data) {
    return <div className="card narrow alert alert-error">{t("invite.invalid")}</div>;
  }
  const chosen = info.data.totp_required ? "totp" : method;

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    setMismatch(password !== confirm);
    if (password === confirm && chosen) void accept.run(chosen);
  };

  if (codes) {
    return (
      <div className="card narrow">
        <RecoveryCodes codes={codes} onDone={() => navigate("/", { replace: true })} />
      </div>
    );
  }
  if (enrollment) {
    return (
      <div className="card narrow">
        <EnrollAuthenticator
          enrollment={enrollment}
          onDone={(result: Confirmed) => {
            client.setQueryData(["me"], result.me);
            setCodes(result.recovery_codes);
          }}
        />
      </div>
    );
  }
  return (
    <form className="card narrow" onSubmit={onSubmit}>
      <h1>{t("invite.title", { name: info.data.name })}</h1>
      <p>{t("invite.intro", { email: info.data.email })}</p>
      <TextField label={t("login.password")} type="password" value={password} onChange={setPassword} required
        autoComplete="new-password" hint={t("invite.passwordHint", { min: policy.data?.min_length ?? 10 })} />
      <TextField label={t("reset.confirmPassword")} type="password" value={confirm} onChange={setConfirm} required
        autoComplete="new-password" />
      <fieldset className="field">
        <legend>{t("invite.method")}</legend>
        {info.data.totp_required ? (
          <p className="hint">{t("invite.totpRequired")}</p>
        ) : (
          <label className="check">
            <input type="radio" name="method" checked={chosen === "email"} onChange={() => setMethod("email")} />
            <span>
              {t("invite.methodEmail")} <span className="hint">{t("invite.methodEmailHint")}</span>
            </span>
          </label>
        )}
        <label className="check">
          <input type="radio" name="method" checked={chosen === "totp"} onChange={() => setMethod("totp")} />
          <span>
            {t("invite.methodTotp")} <span className="hint">{t("invite.methodTotpHint")}</span>
          </span>
        </label>
      </fieldset>
      {mismatch && <div className="alert alert-error">{t("reset.mismatch")}</div>}
      <ErrorMessage error={accept.error} />
      <div className="form-actions">
        <button className="primary" type="submit" disabled={!chosen || accept.busy}>
          {t("invite.submit")}
        </button>
      </div>
    </form>
  );
}
