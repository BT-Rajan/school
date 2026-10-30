import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, query } from "../api";
import { ErrorMessage, Modal, PageHeader, StatusBadge, TextField, useAction } from "../components";
import type { ReferenceValue } from "../types";

const LISTS = ["designation", "subject", "class", "qualification"] as const;
type List = (typeof LISTS)[number];

export default function ReferenceLists() {
  const { t } = useTranslation();
  const client = useQueryClient();
  const [list, setList] = useState<List>("designation");
  const [showRetired, setShowRetired] = useState(false);
  const values = useQuery({
    queryKey: ["reference", list, showRetired],
    queryFn: () => api<ReferenceValue[]>(`/api/reference/${list}${query({ include_retired: showRetired || undefined })}`),
  });
  const refresh = () => client.invalidateQueries({ queryKey: ["reference", list] });

  const [editing, setEditing] = useState<ReferenceValue | "new" | null>(null);
  const [code, setCode] = useState("");
  const [nameEn, setNameEn] = useState("");
  const [nameAr, setNameAr] = useState("");
  const [order, setOrder] = useState("0");
  const open = (value: ReferenceValue | "new") => {
    setEditing(value);
    setCode(value === "new" ? "" : value.code);
    setNameEn(value === "new" ? "" : value.name_en);
    setNameAr(value === "new" ? "" : value.name_ar);
    setOrder(value === "new" ? "0" : String(value.sort_order));
  };
  const save = useAction(async () => {
    const body = { name_en: nameEn, name_ar: nameAr, sort_order: Number(order) || 0 };
    if (editing === "new") await api(`/api/reference/${list}`, { method: "POST", body: { ...body, code } });
    else if (editing) await api(`/api/reference-values/${editing.id}`, { method: "PATCH", body: { ...body, version: editing.version } });
    setEditing(null);
    await refresh();
  });
  const toggle = useAction(async (value: ReferenceValue) => {
    await api(`/api/reference-values/${value.id}/${value.status === "active" ? "retire" : "restore"}`, { method: "POST" });
    await refresh();
  });
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void save.run();
  };

  return (
    <>
      <PageHeader title={t("reference.title")}>
        <button className="primary" type="button" onClick={() => open("new")}>{t("reference.new")}</button>
      </PageHeader>
      <div className="filters" role="tablist">
        {LISTS.map((name) => (
          <button key={name} type="button" role="tab" aria-selected={list === name}
            className={list === name ? "primary" : ""} onClick={() => setList(name)}>
            {t(`reference.${name}`)}
          </button>
        ))}
      </div>
      <label className="check">
        <input type="checkbox" checked={showRetired} onChange={(e) => setShowRetired(e.target.checked)} />
        {t("reference.showRetired")}
      </label>
      <ErrorMessage error={values.error ?? toggle.error} />
      <div className="table-wrap" tabIndex={0}>
        <table>
          <thead>
            <tr>
              <th>{t("reference.code")}</th>
              <th>{t("reference.nameEn")}</th>
              <th>{t("reference.nameAr")}</th>
              <th>{t("reference.order")}</th>
              <th>{t("common.status")}</th>
              <th>{t("common.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {values.data?.map((v) => (
              <tr key={v.id}>
                <td className="ltr">{v.code}</td>
                <td lang="en" dir="ltr">{v.name_en}</td>
                <td lang="ar" dir="rtl">{v.name_ar}</td>
                <td>{v.sort_order}</td>
                <td><StatusBadge status={v.status} /></td>
                <td>
                  <div className="row-actions">
                    <button type="button" onClick={() => open(v)}>{t("common.edit")}</button>
                    <button type="button" onClick={() => void toggle.run(v)}>
                      {v.status === "active" ? t("reference.retire") : t("reference.restore")}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {editing && (
        <Modal title={t(`reference.${list}`)} onClose={() => setEditing(null)}>
          <form onSubmit={onSubmit}>
            <TextField label={t("reference.code")} value={code} onChange={setCode} required dir="ltr" disabled={editing !== "new"} />
            <TextField label={t("reference.nameEn")} value={nameEn} onChange={setNameEn} required dir="ltr" />
            <TextField label={t("reference.nameAr")} value={nameAr} onChange={setNameAr} required dir="rtl" />
            <TextField label={t("reference.order")} value={order} onChange={setOrder} inputMode="numeric" dir="ltr" />
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
