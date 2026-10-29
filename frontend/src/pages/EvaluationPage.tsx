import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, ApiError, download } from "../api";
import { DateField, ErrorMessage, Modal, Notice, PageHeader, StatusBadge, useAction } from "../components";
import SectionView from "../forms/Renderer";
import { type Answers, visibleAnswers } from "../forms/schema";
import { formatDate, formatDateTime } from "../format";
import { isOfflineError, useQueue } from "../offline/hooks";
import * as queue from "../offline/queue";
import { useSession } from "../session";
import type { Amendment, DocumentSummary, Evaluation, FormDetail, Problem } from "../types";
import { RequestStatus } from "./Requests";

type Location = { latitude: number; longitude: number; accuracy_m: number };

/** FR-E8: asked only at submission, and only if the supervisor ticks the box. */
function currentLocation(): Promise<Location | null> {
  if (!("geolocation" in navigator)) return Promise.resolve(null);
  return new Promise((resolve) =>
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ latitude: p.coords.latitude, longitude: p.coords.longitude, accuracy_m: Math.round(p.coords.accuracy) }),
      () => resolve(null),
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 },
    ),
  );
}

function answerProblems(error: unknown): Problem[] {
  return error instanceof ApiError && error.code === "answers_invalid" && Array.isArray(error.detail)
    ? (error.detail as Problem[])
    : [];
}

export default function EvaluationPage() {
  const { t, i18n } = useTranslation();
  const { id } = useParams();
  const { me, district } = useSession();
  const tz = district?.time_zone ?? "UTC";
  const client = useQueryClient();
  const navigate = useNavigate();
  const numericId = Number(id);
  // Started offline: a negative id held on the device until the server gives the real one.
  const isLocal = numericId < 0;
  const evaluation = useQuery({
    queryKey: ["evaluation", id],
    queryFn: async () => {
      if (!isLocal) return api<Evaluation>(`/api/evaluations/${id}`);
      const local = await queue.localEvaluation(numericId);
      if (!local) throw new ApiError(404, "not_found");
      return local;
    },
  });
  const items = useQueue();
  const queued = items.filter((i) => i.kind.startsWith("evaluation.") && i.ref === numericId);
  const submitQueued = queued.some((i) => i.kind === "evaluation.submit");
  useEffect(() => {
    if (!isLocal) return;
    // Once the server has it, show the real record.
    void queue.serverId(numericId).then((real) => real && navigate(`/evaluations/${real}`, { replace: true }));
  }, [isLocal, numericId, items, navigate]);
  const e = evaluation.data;
  const form = useQuery({
    queryKey: ["form", String(e?.form_id)],
    queryFn: () => api<FormDetail>(`/api/forms/${e!.form_id}`),
    enabled: !!e,
  });
  const amendments = useQuery({
    queryKey: ["amendments", id],
    queryFn: () => api<Amendment[]>(`/api/evaluations/${id}/amendments`),
    enabled: !!e && e.status === "amended",
  });
  const documents = useQuery({
    queryKey: ["evaluation-documents", id],
    queryFn: () => api<DocumentSummary[]>(`/api/evaluations/${id}/documents`),
    enabled: !!e,
  });

  const [answers, setAnswers] = useState<Record<string, Answers>>({});
  const [visitDate, setVisitDate] = useState("");
  const [notes, setNotes] = useState("");
  const [dirty, setDirty] = useState(false);
  const [amending, setAmending] = useState(false);
  const [reason, setReason] = useState("");
  const [shareLocation, setShareLocation] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [notice, setNotice] = useState("");

  const reset = (from: Evaluation) => {
    setAnswers(Object.fromEntries(from.sections.map((s) => [s.key, s.answers])));
    setVisitDate(from.visit_date ?? "");
    setNotes(from.visit_notes ?? "");
    setDirty(false);
  };
  useEffect(() => {
    if (e && !dirty) reset(e);
    // Only reload from the server when nothing is being edited.
  }, [e]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (ev: BeforeUnloadEvent) => ev.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const own = me?.role === "supervisor";
  const sections = (form.data?.schema.sections ?? []).filter((s) => s.respondent === "supervisor");
  const teacherSections = (form.data?.schema.sections ?? []).filter((s) => s.respondent === "teacher");
  const payload = () => ({
    visit_date: visitDate || null,
    visit_notes: notes || null,
    sections: Object.fromEntries(sections.map((s) => [s.key, visibleAnswers(s, answers[s.key] ?? {})])),
  });
  const after = async (updated: Evaluation, message: string) => {
    client.setQueryData(["evaluation", id], updated);
    reset(updated);
    setNotice(message);
    await client.invalidateQueries({ queryKey: ["evaluations"] });
  };
  /** FR-PW4: no connection, so the change waits on the device and is sent in order later. */
  const keepOnDevice = async (andSubmit: boolean) => {
    const body = payload();
    const label = `${e!.report.code} · ${e!.school.name}`;
    await queue.enqueueSave(numericId, isLocal ? null : e!.version, body, label);
    if (andSubmit) await queue.enqueueSubmit(numericId, label);
    const updated: Evaluation = {
      ...e!,
      visit_date: body.visit_date,
      visit_notes: body.visit_notes,
      sections: e!.sections.map((s) =>
        s.respondent === "supervisor" ? { ...s, answers: body.sections[s.key] ?? s.answers, status: "in_progress" } : s,
      ),
    };
    if (isLocal) await queue.saveLocalEvaluation(updated);
    client.setQueryData(["evaluation", id], updated);
    reset(updated);
    setNotice(andSubmit ? t("offline.submitQueued") : t("offline.savedOnDevice"));
  };
  const save = useAction(async () => {
    if (isLocal) return keepOnDevice(false);
    try {
      const updated = await api<Evaluation>(`/api/evaluations/${id}`, { method: "PATCH", body: { version: e!.version, ...payload() } });
      await after(updated, t("evaluations.draftSaved"));
    } catch (error) {
      if (!isOfflineError(error)) throw error;
      await keepOnDevice(false);
    }
  });
  const submit = useAction(async () => {
    if (isLocal || !navigator.onLine) {
      if (!window.confirm(t("evaluations.confirmSubmit"))) return;
      return keepOnDevice(true);
    }
    let current = e!;
    if (dirty) {
      current = await api<Evaluation>(`/api/evaluations/${id}`, { method: "PATCH", body: { version: current.version, ...payload() } });
      client.setQueryData(["evaluation", id], current);
    }
    if (!window.confirm(t("evaluations.confirmSubmit"))) return;
    const location = shareLocation ? await currentLocation() : null;
    const updated = await api<Evaluation>(`/api/evaluations/${id}/submit`, {
      method: "POST",
      body: { version: current.version, location },
    });
    await after(updated, t("evaluations.submittedNotice"));
  });
  const amend = useAction(async () => {
    const updated = await api<Evaluation>(`/api/evaluations/${id}/amend`, {
      method: "POST",
      body: { version: e!.version, reason, ...payload() },
    });
    setAmending(false);
    setReason("");
    await after(updated, t("evaluations.amendedNotice"));
    await client.invalidateQueries({ queryKey: ["amendments", id] });
  });
  const pdf = useAction((locale: "en" | "ar") =>
    download(`/api/evaluations/${id}/pdf?locale=${locale}`, `${e!.report.code}-${e!.school.code}-${e!.id}-${locale}.pdf`),
  );

  if (evaluation.error) return <ErrorMessage error={evaluation.error} />;
  if (!e || !form.data) return <p>{t("common.loading")}</p>;
  const editing = own && !submitQueued && (e.status === "draft" || amending);
  const problems = [...answerProblems(save.error), ...answerProblems(submit.error), ...answerProblems(amend.error)];
  const visitProblems = problems.filter((p) => p.where === "visit_date");
  const title = i18n.language === "ar" ? e.report.title_ar : e.report.title_en;

  return (
    <>
      <p><Link to="/evaluations">← {t("evaluations.title")}</Link></p>
      <PageHeader title={`${e.report.code} · ${title}`}>
        <StatusBadge status={e.status} />
      </PageHeader>
      {queued.length > 0 && (
        <div className="alert alert-warn" role="status">
          {submitQueued ? t("offline.submitWaiting") : t("offline.changesWaiting")}{" "}
          <Link to="/outbox">{t("offline.seeOutbox")}</Link>
        </div>
      )}
      <div className="card">
        <dl className="facts">
          <dt>{t("schools.school")}</dt>
          <dd><span className="ltr">{e.school.code}</span> · {e.school.name}</dd>
          {e.teacher && (<><dt>{t("evaluations.teacher")}</dt><dd>{e.teacher.name}</dd></>)}
          <dt>{t("roles.supervisor")}</dt>
          <dd>{e.supervisor.name}</dd>
          <dt>{t("evaluations.reportVersion")}</dt>
          <dd className="ltr">{e.report.code} / {e.report.version_code}</dd>
          {e.submitted_at && (<><dt>{t("evaluations.submittedAt")}</dt><dd className="ltr">{formatDateTime(e.submitted_at, tz)}</dd></>)}
          {e.status === "draft" && e.form_end_date && (
            <><dt>{t("evaluations.formCloses")}</dt><dd className="ltr">{formatDate(e.form_end_date)}</dd></>
          )}
          {e.cancel_reason && (<><dt>{t("common.reason")}</dt><dd dir="auto">{e.cancel_reason}</dd></>)}
        </dl>
        <div className="page-actions">
          {e.status !== "draft" && e.status !== "cancelled" && (
            <>
              <button type="button" disabled={pdf.busy} onClick={() => void pdf.run("en")}>{t("evaluations.pdfEn")}</button>
              <button type="button" disabled={pdf.busy} onClick={() => void pdf.run("ar")}>{t("evaluations.pdfAr")}</button>
            </>
          )}
          {own && (e.status === "submitted" || e.status === "amended") && !amending && (
            <button type="button" onClick={() => setAmending(true)}>{t("evaluations.amend")}</button>
          )}
          {own && e.status === "draft" && (
            <button type="button" className="danger" onClick={() => setCancelling(true)}>{t("evaluations.cancelDraft")}</button>
          )}
        </div>
        {notice && <Notice>{notice}</Notice>}
        <ErrorMessage error={pdf.error} />
      </div>

      <div className="card">
        {editing ? (
          <>
            <DateField label={t("evaluations.visitDate")} value={visitDate} onChange={(v) => { setVisitDate(v); setDirty(true); }} />
            {visitProblems.map((p, i) => (
              <div key={i} className="field-error" role="alert">{t(`answers.${p.code}`, { defaultValue: t("answers.invalid") })}</div>
            ))}
            <div className="field">
              <label htmlFor="visit-notes">{t("evaluations.visitNotes")} ({t("common.optional")})</label>
              <textarea id="visit-notes" dir="auto" rows={3} value={notes} onChange={(ev) => { setNotes(ev.target.value); setDirty(true); }} />
            </div>
          </>
        ) : (
          <dl className="facts">
            <dt>{t("evaluations.visitDate")}</dt>
            <dd className="ltr">{formatDate(e.visit_date)}</dd>
            {e.visit_notes && (<><dt>{t("evaluations.visitNotes")}</dt><dd dir="auto">{e.visit_notes}</dd></>)}
          </dl>
        )}
      </div>

      {sections.map((s) => (
        <div key={s.key} className="card">
          <SectionView section={s} answers={answers[s.key] ?? {}} problems={problems}
            onChange={editing ? (a) => { setAnswers({ ...answers, [s.key]: a }); setDirty(true); } : undefined} />
        </div>
      ))}

      {e.request && (
        <div className="card">
          <h2>{t("requests.teacherPart")}</h2>
          <dl className="facts">
            <dt>{t("evaluations.teacher")}</dt>
            <dd>{e.request.teacher?.name ?? t("requests.noTeacher")}</dd>
            <dt>{t("common.status")}</dt>
            <dd><RequestStatus r={e.request} /></dd>
            <dt>{t("requests.due")}</dt>
            <dd className="ltr">{formatDate(e.request.due_date)}</dd>
            {e.request.close_reason && (<><dt>{t("common.reason")}</dt><dd dir="auto">{e.request.close_reason}</dd></>)}
          </dl>
          {e.status === "draft" && !["submitted", "waived"].includes(e.request.status) && (
            <p className="hint">{t("requests.evaluationWaits")}</p>
          )}
          <p><Link to={`/requests/${e.request.id}`}>{t("requests.open")}</Link></p>
          {teacherSections.map((s) => {
            const given = e.sections.find((x) => x.key === s.key);
            return given && Object.keys(given.answers).length > 0 ? (
              <SectionView key={s.key} section={s} answers={given.answers} />
            ) : null;
          })}
        </div>
      )}

      {editing && (
        <div className="card sticky-actions">
          <ErrorMessage error={save.error ?? submit.error ?? amend.error} />
          {problems.length > 0 && <p className="field-error">{t("evaluations.fixProblems", { count: problems.length })}</p>}
          {e.status === "draft" ? (
            <>
              <label className="check">
                <input type="checkbox" checked={shareLocation} onChange={(ev) => setShareLocation(ev.target.checked)} />
                {t("evaluations.shareLocation")}
              </label>
              <div className="form-actions">
                <button type="button" disabled={save.busy || !dirty} onClick={() => void save.run()}>{t("evaluations.saveDraft")}</button>
                <button type="button" className="primary" disabled={submit.busy} onClick={() => void submit.run()}>
                  {t("evaluations.submit")}
                </button>
              </div>
            </>
          ) : (
            <>
              <div className="field">
                <label htmlFor="amend-reason">{t("evaluations.amendReason")}</label>
                <textarea id="amend-reason" dir="auto" rows={2} required value={reason} onChange={(ev) => setReason(ev.target.value)} />
              </div>
              <div className="form-actions">
                <button type="button" onClick={() => { setAmending(false); reset(e); }}>{t("common.cancel")}</button>
                <button type="button" className="primary" disabled={amend.busy || !reason.trim()} onClick={() => void amend.run()}>
                  {t("evaluations.saveAmendment")}
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {(amendments.data?.length ?? 0) > 0 && (
        <div className="card">
          <h2>{t("evaluations.amendments")}</h2>
          <ul className="timeline">
            {amendments.data!.map((a, i) => (
              <li key={i}>
                {a.by} · <span className="ltr">{formatDateTime(a.at, tz)}</span>
                <p dir="auto">{a.reason}</p>
              </li>
            ))}
          </ul>
        </div>
      )}

      {(documents.data?.length ?? 0) > 0 && (
        <div className="card">
          <h2>{t("evaluations.linkedReports")}</h2>
          <ul>
            {documents.data!.map((d) => (
              <li key={d.id}><Link to={`/reports/${d.id}`}>{d.title}</Link> <StatusBadge status={d.status} /></li>
            ))}
          </ul>
        </div>
      )}

      {cancelling && <CancelDialog evaluation={e} onClose={() => setCancelling(false)}
        onDone={async (updated) => { setCancelling(false); await after(updated, t("evaluations.cancelledNotice")); }} />}
    </>
  );
}

function CancelDialog({ evaluation, onClose, onDone }: {
  evaluation: Evaluation;
  onClose: () => void;
  onDone: (e: Evaluation) => Promise<void>;
}) {
  const { t } = useTranslation();
  const [reason, setReason] = useState("");
  const cancel = useAction(async () => {
    const updated = await api<Evaluation>(`/api/evaluations/${evaluation.id}/cancel`, {
      method: "POST",
      body: { version: evaluation.version, reason },
    });
    await onDone(updated);
  });
  return (
    <Modal title={t("evaluations.cancelDraft")} onClose={onClose}>
      <form onSubmit={(ev) => { ev.preventDefault(); void cancel.run(); }}>
        <div className="field">
          <label htmlFor="cancel-reason">{t("common.reason")}</label>
          <textarea id="cancel-reason" dir="auto" rows={3} required value={reason} onChange={(ev) => setReason(ev.target.value)} />
        </div>
        <ErrorMessage error={cancel.error} />
        <div className="form-actions">
          <button type="button" onClick={onClose}>{t("common.close")}</button>
          <button type="submit" className="danger" disabled={cancel.busy}>{t("evaluations.cancelDraft")}</button>
        </div>
      </form>
    </Modal>
  );
}
