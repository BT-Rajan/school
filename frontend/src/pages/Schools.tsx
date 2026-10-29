import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, ApiError, query } from "../api";
import {
  CustomFieldInputs,
  ErrorMessage,
  Modal,
  PageHeader,
  Pager,
  SelectField,
  StatusBadge,
  TextField,
  useAction,
} from "../components";
import { useClusters, useCustomFields } from "../hooks";
import type { CustomValues, Page, School, Teacher } from "../types";

const PAGE_SIZE = 50;

interface Form {
  cluster_id: string;
  code: string;
  name: string;
  address: string;
  school_type: string;
  medium: string;
  contact_phone: string;
  contact_email: string;
  custom: CustomValues;
}

const empty: Form = {
  cluster_id: "", code: "", name: "", address: "", school_type: "", medium: "", contact_phone: "", contact_email: "",
  custom: {},
};

function toForm(s: School): Form {
  return {
    cluster_id: String(s.cluster.id), code: s.code, name: s.name, address: s.address, school_type: s.school_type,
    medium: s.medium, contact_phone: s.contact_phone, contact_email: s.contact_email ?? "", custom: s.custom,
  };
}

export default function Schools() {
  const { t } = useTranslation();
  const client = useQueryClient();
  const clusters = useClusters();
  const customFields = useCustomFields("school");
  const [q, setQ] = useState("");
  const [clusterId, setClusterId] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const list = useQuery({
    queryKey: ["schools", q, clusterId, status, page],
    queryFn: () => api<Page<School>>(`/api/schools${query({ q, cluster_id: clusterId, status, page, page_size: PAGE_SIZE })}`),
    placeholderData: keepPreviousData,
  });

  const [editing, setEditing] = useState<School | "new" | null>(null);
  const [form, setForm] = useState<Form>(empty);
  const set = (patch: Partial<Form>) => setForm((f) => ({ ...f, ...patch }));
  const open = (school: School | "new") => {
    setEditing(school);
    setForm(school === "new" ? { ...empty, cluster_id: clusterId } : toForm(school));
  };
  const refresh = () => client.invalidateQueries({ queryKey: ["schools"] });

  const save = useAction(async () => {
    const body = { ...form, contact_email: form.contact_email || null };
    try {
      if (editing === "new") {
        await api("/api/schools", { method: "POST", body: { ...body, cluster_id: Number(form.cluster_id) } });
      } else if (editing) {
        const { cluster_id: _c, code: _code, ...changes } = body;
        await api(`/api/schools/${editing.id}`, { method: "PATCH", body: { ...changes, version: editing.version } });
      }
    } catch (error) {
      if (error instanceof ApiError && error.code === "version_conflict") open((error.detail as { current: School }).current);
      throw error;
    }
    setEditing(null);
    await refresh();
  });
  const toggle = useAction(async (school: School) => {
    const action = school.status === "active" ? "deactivate" : "reactivate";
    if (action === "deactivate" && !window.confirm(t("common.confirmDeactivate"))) return;
    await api(`/api/schools/${school.id}/${action}`, { method: "POST" });
    await refresh();
  });

  const [contactFor, setContactFor] = useState<School | null>(null);
  const [contactId, setContactId] = useState("");
  const teachers = useQuery({
    queryKey: ["teachers", "school", contactFor?.id],
    queryFn: () => api<Page<Teacher>>(`/api/teachers${query({ school_id: contactFor!.id, status: "active", page_size: 200 })}`),
    enabled: !!contactFor,
  });
  const setContact = useAction(async () => {
    await api(`/api/schools/${contactFor!.id}/contact`, { method: "PUT", body: { teacher_id: Number(contactId) } });
    setContactFor(null);
    await refresh();
  });

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void save.run();
  };
  const clusterOptions = (clusters.data ?? [])
    .filter((c) => c.status === "active")
    .map((c) => ({ value: String(c.id), label: `${c.code} · ${c.name}` }));

  return (
    <>
      <PageHeader title={t("schools.title")}>
        <button className="primary" type="button" onClick={() => open("new")}>{t("schools.new")}</button>
      </PageHeader>
      <div className="filters">
        <input type="search" value={q} placeholder={t("schools.searchHint")} aria-label={t("common.search")}
          onChange={(e) => { setQ(e.target.value); setPage(1); }} />
        <select value={clusterId} aria-label={t("schools.cluster")} onChange={(e) => { setClusterId(e.target.value); setPage(1); }}>
          <option value="">{t("common.all")}</option>
          {clusterOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <select value={status} aria-label={t("common.status")} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
          <option value="">{t("common.anyStatus")}</option>
          <option value="active">{t("status.active")}</option>
          <option value="inactive">{t("status.inactive")}</option>
        </select>
      </div>
      <ErrorMessage error={list.error ?? toggle.error} />
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{t("schools.code")}</th>
              <th>{t("schools.name")}</th>
              <th>{t("schools.cluster")}</th>
              <th>{t("schools.contact")}</th>
              <th>{t("common.status")}</th>
              <th>{t("common.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {list.data?.items.map((s) => (
              <tr key={s.id}>
                <td className="ltr">{s.code}</td>
                <td>{s.name}</td>
                <td className="ltr">{s.cluster.code}</td>
                <td>{s.contact_teacher?.name ?? t("common.none")}</td>
                <td><StatusBadge status={s.status} /></td>
                <td>
                  <div className="row-actions">
                    <button type="button" onClick={() => open(s)}>{t("common.edit")}</button>
                    <button type="button" onClick={() => { setContactFor(s); setContactId(String(s.contact_teacher?.teacher_id ?? "")); }}>
                      {t("schools.setContact")}
                    </button>
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
        <Modal title={editing === "new" ? t("schools.new") : t("schools.edit")} onClose={() => setEditing(null)}>
          <form onSubmit={onSubmit}>
            <div className="form-grid">
              <SelectField label={t("schools.cluster")} value={form.cluster_id} onChange={(v) => set({ cluster_id: v })}
                options={clusterOptions} placeholder="" required />
              <TextField label={t("schools.code")} value={form.code} onChange={(v) => set({ code: v })} required dir="ltr"
                disabled={editing !== "new"} />
              <TextField label={t("schools.name")} value={form.name} onChange={(v) => set({ name: v })} required />
              <TextField label={t("schools.address")} value={form.address} onChange={(v) => set({ address: v })} required />
              <TextField label={t("schools.type")} value={form.school_type} onChange={(v) => set({ school_type: v })} required />
              <TextField label={t("schools.medium")} value={form.medium} onChange={(v) => set({ medium: v })} required />
              <TextField label={t("schools.phone")} value={form.contact_phone} onChange={(v) => set({ contact_phone: v })}
                required dir="ltr" inputMode="numeric" />
              <TextField label={`${t("schools.email")} (${t("common.optional")})`} type="email" value={form.contact_email}
                onChange={(v) => set({ contact_email: v })} dir="ltr" />
              <CustomFieldInputs fields={customFields.data ?? []} values={form.custom} onChange={(custom) => set({ custom })} />
            </div>
            <ErrorMessage error={save.error} />
            <div className="form-actions">
              <button type="button" onClick={() => setEditing(null)}>{t("common.cancel")}</button>
              <button className="primary" type="submit" disabled={save.busy}>{t("common.save")}</button>
            </div>
          </form>
        </Modal>
      )}

      {contactFor && (
        <Modal title={`${t("schools.setContact")}: ${contactFor.name}`} onClose={() => setContactFor(null)}>
          <form onSubmit={(e) => { e.preventDefault(); void setContact.run(); }}>
            <SelectField label={t("schools.contact")} value={contactId} onChange={setContactId} placeholder="" required
              options={(teachers.data?.items ?? []).map((tch) => ({ value: String(tch.id), label: `${tch.name} (${tch.staff_id})` }))} />
            <ErrorMessage error={setContact.error} />
            <div className="form-actions">
              <button type="button" onClick={() => setContactFor(null)}>{t("common.cancel")}</button>
              <button className="primary" type="submit" disabled={!contactId || setContact.busy}>{t("common.save")}</button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}
