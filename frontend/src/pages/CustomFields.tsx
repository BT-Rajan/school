import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api";
import { ErrorMessage, Field, Modal, PageHeader, SelectField, StatusBadge, TextField, useAction } from "../components";
import type { CustomField } from "../types";

const TYPES = ["text", "number", "date", "single_choice", "multi_choice", "yes_no"] as const;

function parseOptions(text: string) {
  return text
    .split("\n")
    .map((line) => line.split("|").map((part) => part.trim()))
    .filter((parts) => parts[0])
    .map(([code, en = "", ar = ""]) => ({ code, en: en || code, ar: ar || en || code }));
}

function optionsText(field: CustomField) {
  return field.options.map((o) => `${o.code} | ${o.en} | ${o.ar}`).join("\n");
}

function FieldTable({ entity }: { entity: "teacher" | "school" }) {
  const { t, i18n } = useTranslation();
  const client = useQueryClient();
  const fields = useQuery({
    queryKey: ["custom-fields", entity, "all"],
    queryFn: () => api<CustomField[]>(`/api/custom-fields/${entity}?include_retired=true`),
  });
  const refresh = () => client.invalidateQueries({ queryKey: ["custom-fields", entity] });
  const [editing, setEditing] = useState<CustomField | "new" | null>(null);
  const [key, setKey] = useState("");
  const [type, setType] = useState<string>("text");
  const [labelEn, setLabelEn] = useState("");
  const [labelAr, setLabelAr] = useState("");
  const [required, setRequired] = useState(false);
  const [options, setOptions] = useState("");
  const open = (field: CustomField | "new") => {
    setEditing(field);
    setKey(field === "new" ? "" : field.key);
    setType(field === "new" ? "text" : field.field_type);
    setLabelEn(field === "new" ? "" : field.label_en);
    setLabelAr(field === "new" ? "" : field.label_ar);
    setRequired(field === "new" ? false : field.required);
    setOptions(field === "new" ? "" : optionsText(field));
  };
  const save = useAction(async () => {
    const hasOptions = type === "single_choice" || type === "multi_choice";
    const body = { label_en: labelEn, label_ar: labelAr, required, options: hasOptions ? parseOptions(options) : [] };
    if (editing === "new") {
      await api("/api/custom-fields", { method: "POST", body: { ...body, entity, key, field_type: type } });
    } else if (editing) {
      await api(`/api/custom-fields/${editing.id}`, { method: "PATCH", body: { ...body, version: editing.version } });
    }
    setEditing(null);
    await refresh();
  });
  const toggle = useAction(async (field: CustomField) => {
    await api(`/api/custom-fields/${field.id}/${field.status === "active" ? "retire" : "restore"}`, { method: "POST" });
    await refresh();
  });
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void save.run();
  };

  return (
    <section className="card">
      <div className="page-header">
        <h2>{t(`customFields.${entity}`)}</h2>
        <button className="primary" type="button" onClick={() => open("new")}>{t("customFields.new")}</button>
      </div>
      <ErrorMessage error={fields.error ?? toggle.error} />
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{t("customFields.key")}</th>
              <th>{t("customFields.labelEn")}</th>
              <th>{t("customFields.type")}</th>
              <th>{t("customFields.required")}</th>
              <th>{t("common.status")}</th>
              <th>{t("common.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {fields.data?.map((f) => (
              <tr key={f.id}>
                <td className="ltr">{f.key}</td>
                <td>{i18n.language === "ar" ? f.label_ar : f.label_en}</td>
                <td>{t(`customFields.types.${f.field_type}`)}</td>
                <td>{f.required ? t("common.yes") : t("common.no")}</td>
                <td><StatusBadge status={f.status} /></td>
                <td>
                  <div className="row-actions">
                    <button type="button" onClick={() => open(f)}>{t("common.edit")}</button>
                    <button type="button" onClick={() => void toggle.run(f)}>
                      {f.status === "active" ? t("customFields.retire") : t("customFields.restore")}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {editing && (
        <Modal title={t(`customFields.${entity}`)} onClose={() => setEditing(null)}>
          <form onSubmit={onSubmit}>
            <TextField label={t("customFields.key")} hint={t("customFields.keyHint")} value={key} required dir="ltr"
              onChange={(v) => setKey(v.toLowerCase())} disabled={editing !== "new"} />
            <SelectField label={t("customFields.type")} value={type} onChange={setType} disabled={editing !== "new"}
              options={TYPES.map((v) => ({ value: v, label: t(`customFields.types.${v}`) }))} />
            <TextField label={t("customFields.labelEn")} value={labelEn} onChange={setLabelEn} required dir="ltr" />
            <TextField label={t("customFields.labelAr")} value={labelAr} onChange={setLabelAr} required dir="rtl" />
            <label className="check">
              <input type="checkbox" checked={required} onChange={(e) => setRequired(e.target.checked)} />
              {t("customFields.required")}
            </label>
            {(type === "single_choice" || type === "multi_choice") && (
              <Field label={t("customFields.options")} hint={t("customFields.optionsHint")}>
                {(id) => <textarea id={id} value={options} dir="auto" onChange={(e) => setOptions(e.target.value)} />}
              </Field>
            )}
            <ErrorMessage error={save.error} />
            <div className="form-actions">
              <button type="button" onClick={() => setEditing(null)}>{t("common.cancel")}</button>
              <button className="primary" type="submit" disabled={save.busy}>{t("common.save")}</button>
            </div>
          </form>
        </Modal>
      )}
    </section>
  );
}

export default function CustomFields() {
  const { t } = useTranslation();
  return (
    <>
      <PageHeader title={t("customFields.title")} />
      <p className="hint">{t("customFields.limit", { limit: 15 })}</p>
      <FieldTable entity="teacher" />
      <FieldTable entity="school" />
    </>
  );
}
