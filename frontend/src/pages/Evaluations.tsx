import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";

import { api, ApiError, query } from "../api";
import { DateField, ErrorMessage, Modal, PageHeader, Pager, SelectField, StatusBadge, useAction } from "../components";
import { formatDate } from "../format";
import { isOfflineError } from "../offline/hooks";
import * as queue from "../offline/queue";
import { useSession } from "../session";
import type { Assignment, Evaluation, EvaluationSummary, FormDetail, FormSummary, Page, Teacher } from "../types";

const PAGE_SIZE = 50;

export function todayIn(timeZone: string): string {
  // en-CA formats as YYYY-MM-DD.
  return new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
}

export function newKey(): string {
  return typeof crypto.randomUUID === "function" ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export default function Evaluations() {
  const { t, i18n } = useTranslation();
  const { me } = useSession();
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [starting, setStarting] = useState(false);
  const list = useQuery({
    queryKey: ["evaluations", status, page],
    queryFn: () => api<Page<EvaluationSummary>>(`/api/evaluations${query({ status, page, page_size: PAGE_SIZE })}`),
  });
  const isSupervisor = me?.role === "supervisor";
  return (
    <>
      <PageHeader title={t("evaluations.title")}>
        {isSupervisor && (
          <button type="button" className="primary" onClick={() => setStarting(true)}>{t("evaluations.new")}</button>
        )}
      </PageHeader>
      <div className="filters">
        <SelectField label={t("common.status")} value={status} placeholder={t("common.anyStatus")}
          onChange={(v) => { setStatus(v); setPage(1); }}
          options={["draft", "submitted", "amended", "cancelled"].map((s) => ({ value: s, label: t(`status.${s}`) }))} />
      </div>
      <ErrorMessage error={list.error} />
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{t("evaluations.report")}</th>
              <th>{t("schools.school")}</th>
              <th>{t("evaluations.teacher")}</th>
              {!isSupervisor && <th>{t("roles.supervisor")}</th>}
              <th>{t("evaluations.visitDate")}</th>
              <th>{t("common.status")}</th>
            </tr>
          </thead>
          <tbody>
            {list.data?.items.map((e) => (
              <tr key={e.id}>
                <td>
                  <Link to={`/evaluations/${e.id}`}>
                    <span className="ltr">{e.report.code}</span> · {i18n.language === "ar" ? e.report.title_ar : e.report.title_en}
                  </Link>
                </td>
                <td>{e.school.name}</td>
                <td>{e.teacher?.name ?? ""}</td>
                {!isSupervisor && <td>{e.supervisor.name}</td>}
                <td className="ltr">{formatDate(e.visit_date)}</td>
                <td><StatusBadge status={e.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {list.data && list.data.items.length === 0 && <p className="hint">{t("evaluations.empty")}</p>}
      {list.data && <Pager page={page} total={list.data.total} pageSize={PAGE_SIZE} onPage={setPage} />}
      {starting && <StartDialog onClose={() => setStarting(false)} />}
    </>
  );
}

/** FR-E1, FR-E4: an evaluation starts from an open form and a school assigned to the supervisor today. */
function StartDialog({ onClose, initialSchool }: { onClose: () => void; initialSchool?: number }) {
  const { t, i18n } = useTranslation();
  const { district } = useSession();
  const navigate = useNavigate();
  const forms = useQuery({ queryKey: ["forms"], queryFn: () => api<FormSummary[]>("/api/forms") });
  const assignments = useQuery({ queryKey: ["my-assignments"], queryFn: () => api<Assignment[]>("/api/me/assignments") });
  const [formId, setFormId] = useState("");
  const [schoolId, setSchoolId] = useState(initialSchool ? String(initialSchool) : "");
  const [teacherId, setTeacherId] = useState("");
  const [visitDate, setVisitDate] = useState(todayIn(district?.time_zone ?? "UTC"));
  const [key] = useState(newKey);
  const form = forms.data?.find((f) => String(f.id) === formId);
  const forTeacher = form?.report.subject_type === "teacher";
  const teachers = useQuery({
    queryKey: ["teachers", "school", schoolId],
    queryFn: () => api<Page<Teacher>>(`/api/teachers${query({ school_id: schoolId, status: "active", page_size: 200 })}`),
    enabled: forTeacher && !!schoolId,
  });
  const client = useQueryClient();
  const { me } = useSession();
  const start = useAction(async () => {
    const body = {
      form_id: Number(formId),
      school_id: Number(schoolId),
      teacher_id: forTeacher && teacherId ? Number(teacherId) : null,
      visit_date: visitDate || null,
      client_key: key,
    };
    try {
      const created = await api<Evaluation>("/api/evaluations", { method: "POST", body });
      navigate(`/evaluations/${created.id}`);
    } catch (error) {
      if (!isOfflineError(error)) throw error;
      // FR-PW4: start it on the device; the same client key creates it once online.
      const detail = client.getQueryData<FormDetail>(["form", formId]);
      const assignment = schools.find((a) => String(a.school.id) === schoolId);
      if (!detail || !form || !assignment) throw new ApiError(0, "not_available_offline");
      const teacher = teachers.data?.items.find((tc) => String(tc.id) === teacherId);
      const localId = -Date.now();
      const local: Evaluation = {
        id: localId,
        form_id: form.id,
        report: { code: form.report.code, version_code: form.catalog.version_code, title_en: form.catalog.title_en, title_ar: form.catalog.title_ar },
        subject_type: form.report.subject_type,
        school: assignment.school,
        teacher: teacher ? { id: teacher.id, name: teacher.name } : null,
        supervisor: { id: assignment.supervisor.id, name: me?.name ?? "" },
        status: "draft",
        visit_date: body.visit_date,
        submitted_at: null,
        amended_at: null,
        form_status: form.status,
        form_end_date: form.end_date,
        version: 0,
        request: null,
        visit_notes: null,
        location: null,
        cancel_reason: null,
        sections: detail.schema.sections
          .filter((s) => s.respondent === "supervisor")
          .map((s) => ({ key: s.key, respondent: "supervisor" as const, status: "not_started", answers: {}, submitted_at: null })),
      };
      await queue.saveLocalEvaluation(local);
      client.setQueryData(["evaluation", String(localId)], local);
      await queue.enqueueStart(localId, body, `${form.report.code} · ${assignment.school.name}`);
      navigate(`/evaluations/${localId}`);
    }
  });
  const title = (f: FormSummary) => (i18n.language === "ar" ? f.catalog.title_ar || f.catalog.title_en : f.catalog.title_en || f.catalog.title_ar);
  const active = (forms.data ?? []).filter((f) => f.status === "active");
  const schools = (assignments.data ?? []).filter((a) => a.state === "active");
  return (
    <Modal title={t("evaluations.new")} onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); void start.run(); }}>
        <SelectField label={t("evaluations.form")} value={formId} onChange={setFormId} required placeholder=""
          options={active.map((f) => ({ value: String(f.id), label: `${f.report.code} ${f.catalog.version_code} · ${title(f)}` }))} />
        {forms.data && active.length === 0 && <p className="hint">{t("evaluations.noOpenForms")}</p>}
        <SelectField label={t("schools.school")} value={schoolId} onChange={(v) => { setSchoolId(v); setTeacherId(""); }} required placeholder=""
          options={schools.map((a) => ({ value: String(a.school.id), label: `${a.school.code} · ${a.school.name}` }))} />
        {forTeacher && (
          <SelectField label={t("evaluations.teacher")} value={teacherId} onChange={setTeacherId} required placeholder=""
            options={(teachers.data?.items ?? []).map((tc) => ({ value: String(tc.id), label: `${tc.name} (${tc.staff_id})` }))} />
        )}
        <DateField label={t("evaluations.visitDate")} value={visitDate} onChange={setVisitDate} />
        <ErrorMessage error={forms.error ?? assignments.error ?? start.error} />
        <div className="form-actions">
          <button type="button" onClick={onClose}>{t("common.cancel")}</button>
          <button type="submit" className="primary" disabled={start.busy || !formId || !schoolId}>{t("evaluations.start")}</button>
        </div>
      </form>
    </Modal>
  );
}

export { StartDialog };
