import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { PageHeader, useAction, useErrorText } from "../components";
import { formatDate, formatDateTime } from "../format";
import { useOnline, useQueue } from "../offline/hooks";
import * as queue from "../offline/queue";
import { useSession } from "../session";
import { ApiError } from "../api";

function bytes(n: number): string {
  return n > 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.ceil(n / 1024)} KB`;
}

/** FR-PW7: what is waiting on this device, and FR-PW6: choosing when versions differ. */
export default function Outbox() {
  const { t } = useTranslation();
  const { district } = useSession();
  const tz = district?.time_zone ?? "UTC";
  const items = useQueue();
  const online = useOnline();
  const errorText = useErrorText();
  const [storage, setStorage] = useState<{ persisted: boolean; usage: number; quota: number } | null>(null);
  useEffect(() => {
    void (async () => {
      try {
        const persisted = (await navigator.storage?.persisted?.()) ?? false;
        const estimate = (await navigator.storage?.estimate?.()) ?? {};
        setStorage({ persisted, usage: estimate.usage ?? 0, quota: estimate.quota ?? 0 });
      } catch {
        setStorage(null);
      }
    })();
  }, [items.length]);
  const sync = useAction(() => queue.sync());
  const files = items.flatMap((i) => (i.kind === "document.create" ? i.pages : []));
  const fileBytes = files.reduce((n, p) => n + p.size, 0);
  // FR-PW8: warn when queued work could be lost.
  const atRisk = items.length > 0 && storage && (!storage.persisted || (storage.quota > 0 && storage.usage / storage.quota > 0.8));

  return (
    <>
      <PageHeader title={t("offline.title")}>
        <button type="button" disabled={!online || sync.busy || items.length === 0} onClick={() => void sync.run()}>
          {t("offline.sendNow")}
        </button>
      </PageHeader>
      <p role="status">{online ? t("offline.online") : t("offline.offlineNow")}</p>
      {items.length === 0 && <p className="hint">{t("offline.nothingWaiting")}</p>}
      {files.length > 0 && (
        <p className="hint">{t("offline.files", { count: files.length, max: queue.MAX_FILES, size: bytes(fileBytes) })}</p>
      )}
      {atRisk && <div className="alert alert-warn" role="alert">{t("offline.storageRisk")}</div>}
      <ul className="timeline outbox">
        {items.map((item) => (
          <li key={item.key} className={`outbox-${item.status}`}>
            <strong>{t(`offline.kinds.${item.kind}`)}</strong> · {item.label}
            <div className="hint">
              {t(`offline.status.${item.status}`)} · <span className="ltr">{formatDateTime(new Date(item.created).toISOString(), tz)}</span>
            </div>
            {item.status === "failed" && item.error && (
              <p className="field-error">{errorText(new ApiError(422, item.error))[0]}</p>
            )}
            {item.status === "conflict" && item.kind === "evaluation.save" && <Conflict item={item} />}
            {item.status === "failed" && (
              <div className="row-actions">
                <button type="button" onClick={() => void queue.retry(item.key)}>{t("offline.retry")}</button>
                <button type="button" className="danger"
                  onClick={() => window.confirm(t("offline.confirmDiscard")) && void queue.discard(item.key)}>
                  {t("offline.discard")}
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </>
  );
}

function Conflict({ item }: { item: queue.SaveItem }) {
  const { t } = useTranslation();
  const server = item.server;
  const answered = (sections: Record<string, Record<string, unknown>>) =>
    Object.values(sections).reduce((n, s) => n + Object.keys(s ?? {}).length, 0);
  return (
    <div className="conflict">
      <p>{t("offline.conflict")}</p>
      <div className="conflict-versions">
        <div className="card">
          <h3>{t("offline.mine")}</h3>
          <p>{t("evaluations.visitDate")}: <span className="ltr">{formatDate(item.body.visit_date)}</span></p>
          <p>{t("offline.answered", { count: answered(item.body.sections) })}</p>
          {item.body.visit_notes && <p dir="auto">{item.body.visit_notes}</p>}
        </div>
        {server && (
          <div className="card">
            <h3>{t("offline.server")}</h3>
            <p>{t("evaluations.visitDate")}: <span className="ltr">{formatDate(server.visit_date)}</span></p>
            <p>
              {t("offline.answered", {
                count: answered(Object.fromEntries(server.sections.filter((s) => s.respondent === "supervisor").map((s) => [s.key, s.answers]))),
              })}
            </p>
            {server.visit_notes && <p dir="auto">{server.visit_notes}</p>}
          </div>
        )}
      </div>
      <div className="row-actions">
        <button type="button" className="primary" onClick={() => void queue.keepMine(item.key)}>{t("offline.keepMine")}</button>
        <button type="button" onClick={() => void queue.discard(item.key)}>{t("offline.useServer")}</button>
      </div>
    </div>
  );
}
