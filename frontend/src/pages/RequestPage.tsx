import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { api, ApiError } from "../api";
import { DateField, ErrorMessage, Modal, Notice, PageHeader, useAction } from "../components";
import SectionView from "../forms/Renderer";
import { type Answers, visibleAnswers } from "../forms/schema";
import { formatDate, formatDateTime } from "../format";
import { useSession } from "../session";
import type { Problem, RequestEvent, TeacherRequestDetail } from "../types";
import { RequestStatus } from "./Requests";

type Dialog = "return" | "settings" | "waive" | "cancel" | null;

function answerProblems(error: unknown): Problem[] {
  return error instanceof ApiError && error.code === "answers_invalid" && Array.isArray(error.detail)
    ? (error.detail as Problem[])
    : [];
}

/** One request: the teacher answers it here; the requester and Cluster Head act on it (FR-R3 to FR-R5). */
export default function RequestPage() {
  const { t, i18n } = useTranslation();
  const { id } = useParams();
  const { me, district } = useSession();
  const tz = district?.time_zone ?? "UTC";
  const client = useQueryClient();
  const request = useQuery({ queryKey: ["request", id], queryFn: () => api<TeacherRequestDetail>(`/api/requests/${id}`) });
  const r = request.data;
  const staff = me?.role !== "teacher";
  const history = useQuery({
    queryKey: ["request-history", id],
    queryFn: () => api<RequestEvent[]>(`/api/requests/${id}/history`),
    enabled: !!r && staff,
  });
  const [answers, setAnswers] = useState<Record<string, Answers>>({});
  const [dirty, setDirty] = useState(false);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    if (r && !dirty) setAnswers(r.answers ?? {});
  }, [r, dirty]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const after = async (updated: TeacherRequestDetail, message: string) => {
    client.setQueryData(["request", id], updated);
    setDirty(false);
    setAnswers(updated.answers ?? {});
    setNotice(message);
    await client.invalidateQueries({ queryKey: ["requests"] });
    await client.invalidateQueries({ queryKey: ["request-history", id] });
  };
  const payload = () =>
    Object.fromEntries((r?.sections ?? []).map((s) => [s.key, visibleAnswers(s, answers[s.key] ?? {})]));
  const save = useAction(async () => {
    const updated = await api<TeacherRequestDetail>(`/api/requests/${id}`, {
      method: "PATCH",
      body: { version: r!.version, sections: payload() },
    });
    await after(updated, t("requests.draftSaved"));
  });
  const submit = useAction(async () => {
    if (!window.confirm(t("requests.confirmSubmit"))) return;
    const updated = await api<TeacherRequestDetail>(`/api/requests/${id}/submit`, {
      method: "POST",
      body: { version: r!.version, sections: payload() },
    });
    await after(updated, t("requests.submittedNotice"));
  });
  const confirm = useAction(async (accept: boolean) => {
    const updated = await api<TeacherRequestDetail>(`/api/requests/${id}/confirm-move`, {
      method: "POST",
      body: { version: r!.version, accept },
    });
    await after(updated, accept ? t("requests.moveAccepted") : t("requests.moveDeclined"));
  });

  if (request.error) return <ErrorMessage error={request.error} />;
  if (!r) return <p>{t("common.loading")}</p>;
  const title = i18n.language === "ar" ? r.report.title_ar || r.report.title_en : r.report.title_en || r.report.title_ar;
  const problems = [...answerProblems(save.error), ...answerProblems(submit.error)];
  const open = ["not_started", "in_progress", "returned"].includes(r.status);

  return (
    <>
      <p><Link to="/requests">← {staff ? t("requests.title") : t("requests.mine")}</Link></p>
      <PageHeader title={`${r.report.code} · ${title}`}>
        <RequestStatus r={r} />
      </PageHeader>
      {r.status === "returned" && r.return_comment && (
        <div className="alert alert-error" role="status">
          <strong>{t("requests.returnedWith")}</strong>
          <p dir="auto">{r.return_comment}</p>
        </div>
      )}
      {r.pending_teacher && r.can.manage && (
        <div className="alert alert-error" role="status">
          <p>{t("requests.confirmMove", { from: r.teacher?.name ?? "", to: r.pending_teacher.name })}</p>
          <div className="page-actions">
            <button type="button" className="primary" disabled={confirm.busy} onClick={() => void confirm.run(true)}>
              {t("requests.moveToNew", { name: r.pending_teacher.name })}
            </button>
            <button type="button" disabled={confirm.busy} onClick={() => void confirm.run(false)}>
              {t("requests.keepWith", { name: r.teacher?.name ?? "" })}
            </button>
          </div>
        </div>
      )}
      {notice && <Notice>{notice}</Notice>}
      <ErrorMessage error={confirm.error} />

      <div className="card">
        <dl className="facts">
          <dt>{t("schools.school")}</dt>
          <dd><span className="ltr">{r.school.code}</span> · {r.school.name}</dd>
          {r.evaluation?.about && (<><dt>{t("requests.aboutLabel")}</dt><dd>{r.evaluation.about}</dd></>)}
          <dt>{t("requests.requester")}</dt>
          <dd>{r.requester}</dd>
          {staff && (
            <>
              <dt>{t("evaluations.teacher")}</dt>
              <dd>
                {r.teacher?.name ?? t("requests.noTeacher")}
                {r.via_contact && <span className="hint"> · {t("requests.viaContact")}</span>}
              </dd>
            </>
          )}
          <dt>{t("requests.due")}</dt>
          <dd className="ltr">{formatDate(r.due_date)}</dd>
          {r.submitted_at && (<><dt>{t("requests.submittedAt")}</dt><dd className="ltr">{formatDateTime(r.submitted_at, tz)}</dd></>)}
          {r.close_reason && (<><dt>{t("common.reason")}</dt><dd dir="auto">{r.close_reason}</dd></>)}
          {staff && r.evaluation && (
            <><dt>{t("requests.evaluation")}</dt><dd><Link to={`/evaluations/${r.evaluation.id}`}>#{r.evaluation.id}</Link></dd></>
          )}
        </dl>
        {r.instructions && (
          <div className="instructions">
            <h2>{t("requests.instructions")}</h2>
            <p dir="auto">{r.instructions}</p>
          </div>
        )}
        <div className="page-actions">
          {r.can.manage && r.status === "submitted" && (!r.evaluation || r.evaluation.status === "draft") && (
            <button type="button" onClick={() => setDialog("return")}>{t("requests.return")}</button>
          )}
          {r.can.manage && open && <button type="button" onClick={() => setDialog("settings")}>{t("requests.changeDue")}</button>}
          {r.can.waive && <button type="button" onClick={() => setDialog("waive")}>{t("requests.waive")}</button>}
          {r.can.manage && open && r.kind === "standalone" && (
            <button type="button" className="danger" onClick={() => setDialog("cancel")}>{t("requests.cancel")}</button>
          )}
        </div>
      </div>

      {r.sections.map((s) => (
        <div key={s.key} className="card">
          <SectionView section={s} answers={answers[s.key] ?? {}} problems={problems}
            onChange={r.can.answer ? (a) => { setAnswers({ ...answers, [s.key]: a }); setDirty(true); } : undefined} />
        </div>
      ))}
      {staff && !["submitted", "returned"].includes(r.status) && r.status !== "waived" && (
        <p className="hint">{t("requests.answersAfterSubmit")}</p>
      )}

      {r.can.answer && (
        <div className="card sticky-actions">
          <ErrorMessage error={save.error ?? submit.error} />
          {problems.length > 0 && <p className="field-error">{t("evaluations.fixProblems", { count: problems.length })}</p>}
          <div className="form-actions">
            <button type="button" disabled={save.busy || !dirty} onClick={() => void save.run()}>{t("evaluations.saveDraft")}</button>
            <button type="button" className="primary" disabled={submit.busy} onClick={() => void submit.run()}>
              {r.status === "returned" ? t("requests.resubmit") : t("evaluations.submit")}
            </button>
          </div>
        </div>
      )}

      {staff && (history.data?.length ?? 0) > 0 && (
        <div className="card">
          <h2>{t("requests.history")}</h2>
          <ul className="timeline">
            {history.data!.map((h, i) => (
              <li key={i}>
                <strong>{t(`requests.events.${h.action}`, { defaultValue: h.action })}</strong>
                {h.by && <> · {h.by}</>} · <span className="ltr">{formatDateTime(h.at, tz)}</span>
                {typeof h.detail?.comment === "string" && <p dir="auto">{h.detail.comment}</p>}
                {typeof h.detail?.reason === "string" && <p dir="auto">{h.detail.reason}</p>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {dialog && <ActionDialog kind={dialog} request={r} onClose={() => setDialog(null)}
        onDone={async (updated, message) => { setDialog(null); await after(updated, message); }} />}
    </>
  );
}

function ActionDialog({ kind, request, onClose, onDone }: {
  kind: Exclude<Dialog, null>;
  request: TeacherRequestDetail;
  onClose: () => void;
  onDone: (r: TeacherRequestDetail, message: string) => Promise<void>;
}) {
  const { t } = useTranslation();
  const [text, setText] = useState(kind === "settings" ? request.instructions ?? "" : "");
  const [due, setDue] = useState(request.due_date);
  const run = useAction(async () => {
    const base = `/api/requests/${request.id}`;
    const version = request.version;
    const call = (path: string, body: unknown) => api<TeacherRequestDetail>(`${base}/${path}`, { method: "POST", body });
    const updated =
      kind === "return"
        ? await call("return", { version, comment: text })
        : kind === "settings"
          ? await call("settings", { version, due_date: due, instructions: text || null })
          : await call(kind, { version, reason: text });
    await onDone(updated, t(`requests.done.${kind}`));
  });
  const titles = { return: "requests.return", settings: "requests.changeDue", waive: "requests.waive", cancel: "requests.cancel" };
  const labels = {
    return: t("requests.returnComment"),
    settings: `${t("requests.instructions")} (${t("common.optional")})`,
    waive: t("requests.waiveReason"),
    cancel: t("common.reason"),
  };
  return (
    <Modal title={t(titles[kind])} onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); void run.run(); }}>
        {kind === "waive" && <p className="hint">{t("requests.waiveHint")}</p>}
        {kind === "settings" && <DateField label={t("requests.due")} value={due} onChange={setDue} />}
        <div className="field">
          <label htmlFor="request-action-text">{labels[kind]}</label>
          <textarea id="request-action-text" dir="auto" rows={3} required={kind !== "settings"} value={text}
            onChange={(e) => setText(e.target.value)} />
        </div>
        <ErrorMessage error={run.error} />
        <div className="form-actions">
          <button type="button" onClick={onClose}>{t("common.close")}</button>
          <button type="submit" className={kind === "cancel" ? "danger" : "primary"} disabled={run.busy}>{t(titles[kind])}</button>
        </div>
      </form>
    </Modal>
  );
}
