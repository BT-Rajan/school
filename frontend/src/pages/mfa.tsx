import QRCode from "qrcode";
import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api";
import { ErrorMessage, TextField, useAction } from "../components";
import type { Me } from "../types";

export interface Enrollment {
  challenge: string;
  secret: string;
  otpauth_uri: string;
}

export interface Confirmed {
  me: Me;
  recovery_codes: string[];
}

export function CodeInput({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) {
  return (
    <TextField
      label={label}
      value={value}
      onChange={(v) => onChange(v.replace(/\D/g, "").slice(0, 6))}
      inputMode="numeric"
      autoComplete="one-time-code"
      dir="ltr"
    />
  );
}

/** Scan, confirm, and receive recovery codes (FR-A12, FR-A14). */
export function EnrollAuthenticator({ enrollment, onDone }: { enrollment: Enrollment; onDone: (r: Confirmed) => void }) {
  const { t } = useTranslation();
  const [qr, setQr] = useState("");
  const [code, setCode] = useState("");
  const confirm = useAction(async () => {
    const result = await api<Confirmed>("/api/auth/mfa/totp/confirm", {
      method: "POST",
      body: { challenge: enrollment.challenge, code },
    });
    onDone(result);
  });
  useEffect(() => {
    void QRCode.toDataURL(enrollment.otpauth_uri, { margin: 1, width: 200 }).then(setQr);
  }, [enrollment.otpauth_uri]);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    void confirm.run();
  };
  return (
    <form onSubmit={submit}>
      <h2>{t("enroll.title")}</h2>
      <p>{t("enroll.step1")}</p>
      {qr && <img className="qr" src={qr} alt="" />}
      <p>
        {t("enroll.manual")} <span className="secret">{enrollment.secret.match(/.{1,4}/g)?.join(" ")}</span>
      </p>
      <p>{t("enroll.step2")}</p>
      <CodeInput label={t("login.code")} value={code} onChange={setCode} />
      <ErrorMessage error={confirm.error} />
      <div className="form-actions">
        <button className="primary" type="submit" disabled={code.length !== 6 || confirm.busy}>
          {t("enroll.confirm")}
        </button>
      </div>
    </form>
  );
}

export function RecoveryCodes({ codes, onDone }: { codes: string[]; onDone: () => void }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  return (
    <div>
      <h2>{t("recovery.title")}</h2>
      <p>{t("recovery.intro")}</p>
      <div className="recovery-codes card">
        {codes.map((c) => (
          <span key={c}>{c}</span>
        ))}
      </div>
      <div className="form-actions">
        <button
          type="button"
          onClick={() => void navigator.clipboard?.writeText(codes.join("\n")).then(() => setCopied(true))}
        >
          {copied ? t("recovery.copied") : t("recovery.copy")}
        </button>
        <button type="button" className="primary" onClick={onDone}>
          {t("recovery.saved")}
        </button>
      </div>
    </div>
  );
}
