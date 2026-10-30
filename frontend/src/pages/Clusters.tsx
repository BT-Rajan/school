import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, ApiError } from "../api";
import { ErrorMessage, Modal, PageHeader, SelectField, StatusBadge, TextField, useAction } from "../components";
import { useClusterHeads, useClusters } from "../hooks";
import { useSession } from "../session";
import type { Cluster } from "../types";

export default function Clusters() {
  const { t } = useTranslation();
  const { me } = useSession();
  const isAdmin = me?.role === "district_admin";
  const client = useQueryClient();
  const clusters = useClusters();
  const heads = useClusterHeads(isAdmin);
  const [editing, setEditing] = useState<Cluster | "new" | null>(null);
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [headId, setHeadId] = useState("");

  const open = (cluster: Cluster | "new") => {
    setEditing(cluster);
    setCode(cluster === "new" ? "" : cluster.code);
    setName(cluster === "new" ? "" : cluster.name);
    setHeadId(cluster === "new" ? "" : String(cluster.cluster_head?.id ?? ""));
  };
  const refresh = () => client.invalidateQueries({ queryKey: ["clusters"] });
  const save = useAction(async () => {
    const cluster_head_id = headId ? Number(headId) : null;
    try {
      if (editing === "new") {
        await api("/api/clusters", { method: "POST", body: { code, name, cluster_head_id } });
      } else if (editing) {
        await api(`/api/clusters/${editing.id}`, {
          method: "PATCH",
          body: { version: editing.version, name, cluster_head_id },
        });
      }
    } catch (error) {
      if (error instanceof ApiError && error.code === "version_conflict") {
        const current = (error.detail as { current: Cluster }).current;
        open(current);
      }
      throw error;
    }
    setEditing(null);
    await refresh();
  });
  const toggle = useAction(async (cluster: Cluster) => {
    const action = cluster.status === "active" ? "deactivate" : "reactivate";
    if (action === "deactivate" && !window.confirm(t("common.confirmDeactivate"))) return;
    await api(`/api/clusters/${cluster.id}/${action}`, { method: "POST" });
    await refresh();
  });

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void save.run();
  };
  const headOptions = (heads.data ?? [])
    .filter((h) => h.status !== "inactive")
    .map((h) => ({ value: String(h.id), label: `${h.name} (${h.email})` }));

  return (
    <>
      <PageHeader title={t("clusters.title")}>
        {isAdmin && (
          <button className="primary" type="button" onClick={() => open("new")}>
            {t("clusters.new")}
          </button>
        )}
      </PageHeader>
      <ErrorMessage error={clusters.error ?? toggle.error} />
      <div className="table-wrap" tabIndex={0}>
        <table>
          <thead>
            <tr>
              <th>{t("clusters.code")}</th>
              <th>{t("clusters.name")}</th>
              <th>{t("clusters.head")}</th>
              <th>{t("common.status")}</th>
              {isAdmin && <th>{t("common.actions")}</th>}
            </tr>
          </thead>
          <tbody>
            {clusters.data?.map((c) => (
              <tr key={c.id}>
                <td className="ltr">{c.code}</td>
                <td>{c.name}</td>
                <td>{c.cluster_head?.name ?? t("clusters.noHead")}</td>
                <td><StatusBadge status={c.status} /></td>
                {isAdmin && (
                  <td>
                    <div className="row-actions">
                      <button type="button" onClick={() => open(c)}>{t("common.edit")}</button>
                      <button type="button" className={c.status === "active" ? "danger" : ""}
                        onClick={() => void toggle.run(c)}>
                        {c.status === "active" ? t("common.deactivate") : t("common.reactivate")}
                      </button>
                    </div>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {editing && (
        <Modal title={editing === "new" ? t("clusters.new") : t("clusters.edit")} onClose={() => setEditing(null)}>
          <form onSubmit={onSubmit}>
            <TextField label={t("clusters.code")} value={code} onChange={setCode} required dir="ltr"
              disabled={editing !== "new"} />
            <TextField label={t("clusters.name")} value={name} onChange={setName} required />
            <SelectField label={t("clusters.head")} value={headId} onChange={setHeadId} options={headOptions}
              placeholder={t("clusters.noHead")} />
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
