import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api";
import { ErrorMessage, Modal, PageHeader, StatusBadge, TextField, useAction } from "../components";
import { formatDateTime } from "../format";
import { useSession } from "../session";
import type { StaffUser } from "../types";

type Kind = "admins" | "cluster-heads";

function StaffTable({ kind, title, newLabel }: { kind: Kind; title: string; newLabel: string }) {
  const { t } = useTranslation();
  const { me, district } = useSession();
  const client = useQueryClient();
  const list = useQuery({ queryKey: [kind], queryFn: () => api<StaffUser[]>(`/api/${kind}`) });
  const refresh = () => client.invalidateQueries({ queryKey: [kind] });
  const [creating, setCreating] = useState(false);
  const [staffId, setStaffId] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const create = useAction(async () => {
    await api(`/api/${kind}`, { method: "POST", body: { staff_id: staffId, name, email } });
    setCreating(false);
    setStaffId("");
    setName("");
    setEmail("");
    await refresh();
  });
  const act = useAction(async (user: StaffUser, action: string) => {
    if (action === "deactivate" && !window.confirm(t("common.confirmDeactivate"))) return;
    if (action === "mfa-reset" && !window.confirm(t("staff.resetMfaConfirm"))) return;
    await api(`/api/users/${user.id}/${action}`, { method: "POST" });
    await refresh();
  });
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void create.run();
  };

  return (
    <section className="card">
      <div className="page-header">
        <h2>{title}</h2>
        <button className="primary" type="button" onClick={() => setCreating(true)}>{newLabel}</button>
      </div>
      <ErrorMessage error={list.error ?? act.error} />
      <div className="table-wrap" tabIndex={0}>
        <table>
          <thead>
            <tr>
              <th>{t("staff.staffId")}</th>
              <th>{t("supervisors.name")}</th>
              <th>{t("supervisors.email")}</th>
              <th>{t("staff.method")}</th>
              <th>{t("staff.lastLogin")}</th>
              <th>{t("common.status")}</th>
              <th>{t("common.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {list.data?.map((u) => (
              <tr key={u.id}>
                <td className="ltr">{u.staff_id}</td>
                <td>{u.name}</td>
                <td className="ltr">{u.email}</td>
                <td>{u.mfa_method === "totp" ? t("invite.methodTotp") : t("invite.methodEmail")}</td>
                <td className="ltr">{formatDateTime(u.last_login_at, district?.time_zone ?? "UTC")}</td>
                <td>
                  <StatusBadge status={u.status} /> {u.locked && <span className="badge badge-inactive">{t("staff.locked")}</span>}
                </td>
                <td>
                  {u.id !== me?.id && (
                    <div className="row-actions">
                      {u.status === "invited" && (
                        <button type="button" onClick={() => void act.run(u, "resend-invitation")}>{t("teachers.resendInvite")}</button>
                      )}
                      {u.locked && <button type="button" onClick={() => void act.run(u, "unlock")}>{t("staff.unlock")}</button>}
                      {u.status === "active" && (
                        <button type="button" onClick={() => void act.run(u, "mfa-reset")}>{t("staff.resetMfa")}</button>
                      )}
                      <button type="button" className={u.status !== "inactive" ? "danger" : ""}
                        onClick={() => void act.run(u, u.status === "inactive" ? "reactivate" : "deactivate")}>
                        {u.status === "inactive" ? t("common.reactivate") : t("common.deactivate")}
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {creating && (
        <Modal title={newLabel} onClose={() => setCreating(false)}>
          <form onSubmit={onSubmit}>
            <TextField label={t("staff.staffId")} value={staffId} onChange={setStaffId} required dir="ltr" />
            <TextField label={t("supervisors.name")} value={name} onChange={setName} required />
            <TextField label={t("supervisors.email")} type="email" value={email} onChange={setEmail} required dir="ltr" />
            <ErrorMessage error={create.error} />
            <div className="form-actions">
              <button type="button" onClick={() => setCreating(false)}>{t("common.cancel")}</button>
              <button className="primary" type="submit" disabled={create.busy}>{t("common.create")}</button>
            </div>
          </form>
        </Modal>
      )}
    </section>
  );
}

export default function Staff() {
  const { t } = useTranslation();
  return (
    <>
      <PageHeader title={t("staff.title")} />
      <StaffTable kind="admins" title={t("staff.admins")} newLabel={t("staff.newAdmin")} />
      <StaffTable kind="cluster-heads" title={t("staff.heads")} newLabel={t("staff.newHead")} />
    </>
  );
}
