import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, ApiError, download } from "../api";
import { ErrorMessage, Field, Notice, PageHeader, SelectField, useAction, useErrorText } from "../components";
import { formatDate } from "../format";
import type { ImportBatch } from "../types";

const ENTITIES = ["schools", "teachers", "supervisors"] as const;
type Entity = (typeof ENTITIES)[number];

export default function Imports() {
  const { t, i18n } = useTranslation();
  const errorText = useErrorText();
  const client = useQueryClient();
  const [entity, setEntity] = useState<Entity>("teachers");
  const [file, setFile] = useState<File | null>(null);
  const [batch, setBatch] = useState<ImportBatch | null>(null);
  const locale = i18n.language === "ar" ? "ar" : "en";

  const preview = useAction(async () => {
    const form = new FormData();
    form.append("file", file!);
    setBatch(await api<ImportBatch>(`/api/imports/${entity}/preview`, { method: "POST", form }));
  });
  const commit = useAction(async () => {
    setBatch(await api<ImportBatch>(`/api/imports/${batch!.id}/commit`, { method: "POST" }));
    await client.invalidateQueries();
  });
  const exportFile = useAction(async (format: "csv" | "xlsx") =>
    download(`/api/exports/${entity}?format=${format}&locale=${locale}`, `${entity}.${format}`),
  );
  const template = useAction(async () =>
    download(`/api/imports/templates/${entity}?locale=${locale}`, `${entity}-template.csv`),
  );

  const onPreview = (e: FormEvent) => {
    e.preventDefault();
    if (file) void preview.run();
  };
  const toImport = batch ? (batch.summary.created ?? 0) + (batch.summary.updated ?? 0) : 0;
  const rowError = (error: { field?: string; code: string; value?: string }) =>
    errorText(new ApiError(422, error.code, error.value ? { value: error.value } : undefined))[0] +
    (error.field ? ` (${error.field})` : "");

  return (
    <>
      <PageHeader title={t("imports.title")} />
      <form className="card" onSubmit={onPreview}>
        <SelectField label={t("imports.entity")} value={entity}
          onChange={(v) => { setEntity(v as Entity); setBatch(null); }}
          options={ENTITIES.map((e) => ({ value: e, label: t(`imports.${e}`) }))} />
        <div className="form-actions" style={{ justifyContent: "flex-start" }}>
          <button type="button" onClick={() => void template.run()}>{t("imports.template")}</button>
        </div>
        <Field label={t("imports.file")}>
          {(id) => (
            <input id={id} type="file" accept=".csv,.xlsx"
              onChange={(e) => { setFile(e.target.files?.[0] ?? null); setBatch(null); }} />
          )}
        </Field>
        <ErrorMessage error={preview.error ?? template.error} />
        <div className="form-actions">
          <button className="primary" type="submit" disabled={!file || preview.busy}>{t("imports.preview")}</button>
        </div>
      </form>

      {batch && (
        <section className="card">
          {batch.status === "committed" ? (
            <Notice>
              {t("imports.committed")}
              {batch.invitation_schedule.length > 0 && (
                <>
                  <div>{t("imports.schedule")}</div>
                  <ul>
                    {batch.invitation_schedule.map((day) => (
                      <li key={day.date}>{t("imports.scheduleRow", { date: formatDate(day.date), count: day.count })}</li>
                    ))}
                  </ul>
                </>
              )}
            </Notice>
          ) : (
            <div className="form-actions" style={{ justifyContent: "space-between" }}>
              <span>
                {(["created", "updated", "unchanged", "error"] as const)
                  .map((a) => `${t(`imports.${a}`)}: ${batch.summary[a] ?? 0}`)
                  .join(" · ")}
              </span>
              <button className="primary" type="button" disabled={toImport === 0 || commit.busy} onClick={() => void commit.run()}>
                {toImport === 0 ? t("imports.nothingToImport") : t("imports.commit", { count: toImport })}
              </button>
            </div>
          )}
          <ErrorMessage error={commit.error} />
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t("imports.row")}</th>
                  <th>{t("imports.key")}</th>
                  <th>{t("imports.result")}</th>
                  <th>{t("imports.problems")}</th>
                </tr>
              </thead>
              <tbody>
                {batch.rows.map((row) => (
                  <tr key={row.row}>
                    <td>{row.row}</td>
                    <td className="ltr">{row.key}</td>
                    <td><span className={`badge badge-${row.action}`}>{t(`imports.${row.action}`)}</span></td>
                    <td>{row.errors.map((error, i) => <div key={i}>{rowError(error)}</div>)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section className="card">
        <h2>{t("imports.export")}: {t(`imports.${entity}`)}</h2>
        <ErrorMessage error={exportFile.error} />
        <div className="form-actions" style={{ justifyContent: "flex-start" }}>
          <button type="button" onClick={() => void exportFile.run("xlsx")}>{t("imports.exportXlsx")}</button>
          <button type="button" onClick={() => void exportFile.run("csv")}>{t("imports.exportCsv")}</button>
        </div>
      </section>
    </>
  );
}
