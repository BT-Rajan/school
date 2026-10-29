import { type Dispatch, type SetStateAction, useState } from "react";
import { useTranslation } from "react-i18next";

import { uploadFile } from "../api";
import { useErrorText } from "../components";
import type { UploadedFile } from "../types";

export interface Picked {
  key: string;
  name: string;
  file?: UploadedFile;
  error?: unknown;
}

/**
 * Pages of a scanned report (FR-D1, FR-D2): PDFs or images from the device, or photos from the
 * camera. Each is uploaded as soon as it is picked; the server joins them into one PDF in this order.
 */
export default function PagePicker({ pages, onChange }: { pages: Picked[]; onChange: Dispatch<SetStateAction<Picked[]>> }) {
  const { t } = useTranslation();
  const errorText = useErrorText();
  const [busy, setBusy] = useState(0);
  const add = async (list: File[]) => {
    if (!list.length) return;
    const entries: Picked[] = list.map((f, i) => ({ key: `${Date.now()}-${i}-${f.name}`, name: f.name }));
    // Updates are applied to the latest list, so moving or removing pages during upload is kept.
    onChange((prev) => [...prev, ...entries]);
    setBusy((n) => n + entries.length);
    // One at a time keeps a phone on a weak connection from timing out on all of them at once.
    for (const [i, file] of list.entries()) {
      const key = entries[i].key;
      try {
        const stored = await uploadFile<UploadedFile>(file);
        onChange((prev) => prev.map((p) => (p.key === key ? { ...p, file: stored } : p)));
      } catch (error) {
        onChange((prev) => prev.map((p) => (p.key === key ? { ...p, error } : p)));
      }
      setBusy((n) => n - 1);
    }
  };
  const move = (i: number, delta: number) => {
    const j = i + delta;
    if (j < 0 || j >= pages.length) return;
    const next = [...pages];
    [next[i], next[j]] = [next[j], next[i]];
    onChange(next);
  };
  return (
    <fieldset className="field checks">
      <legend>{t("reports.pages")}</legend>
      <p className="hint">{t("reports.pagesHint")}</p>
      <ol className="page-list">
        {pages.map((p, i) => (
          <li key={p.key}>
            <span dir="auto">{p.name}</span>{" "}
            {p.error ? (
              <span className="field-error">{errorText(p.error)[0]}</span>
            ) : p.file ? (
              <span className="hint">{p.file.pages ? t("reports.pageCount", { count: p.file.pages }) : ""}</span>
            ) : (
              <span className="hint">{t("reports.uploading")}</span>
            )}
            <span className="row-actions">
              <button type="button" disabled={i === 0} onClick={() => move(i, -1)} aria-label={t("builder.moveUp")}>↑</button>
              <button type="button" disabled={i === pages.length - 1} onClick={() => move(i, 1)} aria-label={t("builder.moveDown")}>↓</button>
              <button type="button" className="link" onClick={() => onChange(pages.filter((x) => x.key !== p.key))}>
                {t("builder.remove")}
              </button>
            </span>
          </li>
        ))}
      </ol>
      <div className="page-actions">
        <label className="button-like">
          {t("reports.chooseFiles")}
          <input type="file" className="visually-hidden" multiple accept="application/pdf,image/jpeg,image/png,image/heic,image/heif,image/tiff,.heic,.heif"
            onChange={(e) => { const files = Array.from(e.target.files ?? []); e.target.value = ""; void add(files); }} />
        </label>
        <label className="button-like">
          {t("reports.takePhoto")}
          <input type="file" className="visually-hidden" accept="image/*" capture="environment"
            onChange={(e) => { const files = Array.from(e.target.files ?? []); e.target.value = ""; void add(files); }} />
        </label>
      </div>
      {busy > 0 && <p className="hint" role="status">{t("reports.uploadingCount", { count: busy })}</p>}
    </fieldset>
  );
}

export function readyIds(pages: Picked[]): number[] | null {
  if (!pages.length || pages.some((p) => !p.file)) return null;
  return pages.map((p) => p.file!.id);
}
