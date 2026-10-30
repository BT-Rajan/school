import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, ApiError, query } from "../api";
import { ErrorMessage, Modal, PageHeader, Pager, SelectField, StatusBadge, TextField, useAction } from "../components";
import { useClusters } from "../hooks";
import { useSession } from "../session";
import type { Page, Supervisor } from "../types";

const PAGE_SIZE = 50;

export default function Supervisors() {
  const { t } = useTranslation();
  const { me } = useSession();
  const isAdmin = me?.role === "district_admin";
  const client = useQueryClient();
  const clusters = useClusters();
  const [q, setQ] = useState("");
  const [clusterId, setClusterId] = useState("");
  const [page, setPage] = useState(1);
  const list = useQuery({
    queryKey: ["supervisors", q, clusterId, page],
    queryFn: () => api<Page<Supervisor>>(`/api/supervisors${query({ q, cluster_id: clusterId, page, page_size: PAGE_SIZE })}`),
    placeholderData: keepPreviousData,
  });
  const refresh = () => client.invalidateQueries({ queryKey: ["supervisors"] });

  const [editing, setEditing] = useState<Supervisor | "new" | null>(null);
  const [staffId, setStaffId] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [formCluster, setFormCluster] = useState("");
  const open = (s: Supervisor | "new") => {
    setEditing(s);
    setStaffId(s === "new" ? "" : s.staff_id);
    setName(s === "new" ? "" : s.name);
    setEmail(s === "new" ? "" : s.email);
    setFormCluster(s === "new" ? clusterId : String(s.cluster.id));
  };
  const save = useAction(async () => {
    try {
      if (editing === "new") {
        await api("/api/supervisors", {
          method: "POST",
          body: { staff_id: staffId, name, email, cluster_id: Number(formCluster) },
        });
      } else if (editing) {
        await api(`/api/supervisors/${editing.id}`, {
          method: "PATCH",
          body: { version: editing.version, name, email: email === editing.email ? null : email },
        });
        if (isAdmin && formCluster !== String(editing.cluster.id)) {
          await api(`/api/supervisors/${editing.id}/move`, { method: "POST", body: { cluster_id: Number(formCluster) } });
        }
      }
    } catch (error) {
      if (error instanceof ApiError && error.code === "version_conflict") open((error.detail as { current: Supervisor }).current);
      throw error;
    }
    setEditing(null);
    await refresh();
  });
  // An admin resets a supervisor who lost their authenticator to emailed codes (FR-A8).
  const resetMfa = useAction(async (s: Supervisor) => {
    if (!window.confirm(t("staff.resetMfaConfirm"))) return;
    await api(`/api/users/${s.user_id}/mfa-reset`, { method: "POST" });
    await refresh();
  });
  const toggle = useAction(async (s: Supervisor) => {
    const action = s.status === "active" ? "deactivate" : "reactivate";
    if (action === "deactivate" && !window.confirm(t("common.confirmDeactivate"))) return;
    await api(`/api/users/${s.user_id}/${action}`, { method: "POST" });
    await refresh();
  });

  const clusterOptions = (clusters.data ?? []).map((c) => ({ value: String(c.id), label: `${c.code} · ${c.name}` }));
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void save.run();
  };

  return (
    <>
      <PageHeader title={t("supervisors.title")}>
        <button className="primary" type="button" onClick={() => open("new")}>{t("supervisors.new")}</button>
      </PageHeader>
      <div className="filters">
        <input type="search" value={q} placeholder={t("supervisors.searchHint")} aria-label={t("common.search")}
          onChange={(e) => { setQ(e.target.value); setPage(1); }} />
        <select value={clusterId} aria-label={t("supervisors.cluster")} onChange={(e) => { setClusterId(e.target.value); setPage(1); }}>
          <option value="">{t("common.all")}</option>
          {clusterOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </div>
      <ErrorMessage error={list.error ?? toggle.error} />
      <div className="table-wrap" tabIndex={0}>
        <table>
          <thead>
            <tr>
              <th>{t("supervisors.staffId")}</th>
              <th>{t("supervisors.name")}</th>
              <th>{t("supervisors.email")}</th>
              <th>{t("supervisors.cluster")}</th>
              <th>{t("common.status")}</th>
              <th>{t("common.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {list.data?.items.map((s) => (
              <tr key={s.id}>
                <td className="ltr">{s.staff_id}</td>
                <td>{s.name}</td>
                <td className="ltr">{s.email}</td>
                <td className="ltr">{s.cluster.code}</td>
                <td><StatusBadge status={s.status === "active" ? s.account_status : s.status} /></td>
                <td>
                  <div className="row-actions">
                    <button type="button" onClick={() => open(s)}>{t("common.edit")}</button>
                    {isAdmin && s.account_status === "active" && (
                      <button type="button" onClick={() => void resetMfa.run(s)}>{t("staff.resetMfa")}</button>
                    )}
                    <button type="button" className={s.status === "active" ? "danger" : ""} onClick={() => void toggle.run(s)}>
                      {s.status === "active" ? t("common.deactivate") : t("common.reactivate")}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {list.data && <Pager page={page} total={list.data.total} pageSize={PAGE_SIZE} onPage={setPage} />}
      {editing && (
        <Modal title={editing === "new" ? t("supervisors.new") : t("supervisors.edit")} onClose={() => setEditing(null)}>
          <form onSubmit={onSubmit}>
            <TextField label={t("supervisors.staffId")} value={staffId} onChange={setStaffId} required dir="ltr"
              disabled={editing !== "new"} />
            <TextField label={t("supervisors.name")} value={name} onChange={setName} required />
            <TextField label={t("supervisors.email")} type="email" value={email} onChange={setEmail} required dir="ltr"
              disabled={editing !== "new" && editing.account_status !== "invited"} />
            {(editing === "new" || isAdmin) && (
              <SelectField label={editing === "new" ? t("supervisors.cluster") : t("supervisors.move")}
                value={formCluster} onChange={setFormCluster} options={clusterOptions} placeholder="" required />
            )}
            <ErrorMessage error={save.error} />
            <div className="form-actions">
              <button type="button" onClick={() => setEditing(null)}>{t("common.cancel")}</button>
              <button className="primary" type="submit" disabled={save.busy}>{t("common.save")}</button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}
