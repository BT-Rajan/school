import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";

import { api, query } from "../api";
import { CheckboxGroup, DateField, ErrorMessage, Modal, PageHeader, Pager, SelectField, StatusBadge, useAction } from "../components";
import { formatDate } from "../format";
import { useAllSchools } from "../hooks";
import { useSession } from "../session";
import type { Assignment, CatalogReport, Page, Teacher, TeacherRequestSummary } from "../types";
import { todayIn } from "./Evaluations";

const PAGE_SIZE = 50;
const SHOW = ["open", "overdue", "submitted", "closed", "awaiting_confirmation", "unaddressed"] as const;

export function RequestStatus({ r }: { r: Pick<TeacherRequestSummary, "status" | "overdue"> }) {
  const { t } = useTranslation();
  return (
    <>
      <StatusBadge status={r.status} />
      {r.overdue && <span className="badge badge-error">{t("requests.overdue")}</span>}
    </>
  );
}

/** FR-R1 to FR-R3: a teacher's requests, or the requests a member of staff can see. */
export default function Requests() {
  const { t, i18n } = useTranslation();
  const { me } = useSession();
  const isTeacher = me?.role === "teacher";
  const [show, setShow] = useState<string>(isTeacher ? "open" : "");
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const list = useQuery({
    queryKey: ["requests", show, page],
    queryFn: () => api<Page<TeacherRequestSummary>>(`/api/requests${query({ show, page, page_size: PAGE_SIZE })}`),
  });
  const title = (r: TeacherRequestSummary) => (i18n.language === "ar" ? r.report.title_ar || r.report.title_en : r.report.title_en || r.report.title_ar);
  return (
    <>
      <PageHeader title={isTeacher ? t("requests.mine") : t("requests.title")}>
        {!isTeacher && (
          <button type="button" className="primary" onClick={() => setCreating(true)}>{t("requests.new")}</button>
        )}
      </PageHeader>
      <div className="filters">
        <SelectField label={t("requests.show")} value={show} placeholder={t("common.all")}
          onChange={(v) => { setShow(v); setPage(1); }}
          options={SHOW.filter((s) => !isTeacher || ["open", "overdue", "submitted", "closed"].includes(s)).map((s) => ({
            value: s,
            label: t(`requests.filters.${s}`),
          }))} />
      </div>
      <ErrorMessage error={list.error} />
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{t("evaluations.report")}</th>
              <th>{t("schools.school")}</th>
              {!isTeacher && <th>{t("evaluations.teacher")}</th>}
              <th>{isTeacher ? t("requests.from") : t("requests.requester")}</th>
              <th>{t("requests.due")}</th>
              <th>{t("common.status")}</th>
            </tr>
          </thead>
          <tbody>
            {list.data?.items.map((r) => (
              <tr key={r.id} className={r.overdue ? "row-warn" : ""}>
                <td>
                  <Link to={`/requests/${r.id}`}>
                    <span className="ltr">{r.report.code}</span> · {title(r)}
                  </Link>
                  {r.evaluation?.about && <div className="hint">{t("requests.about", { name: r.evaluation.about })}</div>}
                </td>
                <td>{r.school.name}</td>
                {!isTeacher && (
                  <td>
                    {r.teacher?.name ?? <span className="badge badge-warn">{t("requests.noTeacher")}</span>}
                    {r.pending_teacher && <div className="hint">{t("requests.pendingMove", { name: r.pending_teacher.name })}</div>}
                  </td>
                )}
                <td>{r.requester}</td>
                <td className="ltr">{formatDate(r.due_date)}</td>
                <td><RequestStatus r={r} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {list.data && list.data.items.length === 0 && <p className="hint">{t("requests.empty")}</p>}
      {list.data && <Pager page={page} total={list.data.total} pageSize={PAGE_SIZE} onPage={setPage} />}
      {creating && <CreateDialog onClose={() => setCreating(false)} />}
    </>
  );
}

/** FR-R1: a standalone request on a published form the District Admins approved for it. */
function CreateDialog({ onClose }: { onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const { me, district } = useSession();
  const client = useQueryClient();
  const navigate = useNavigate();
  const isSupervisor = me?.role === "supervisor";
  const catalog = useQuery({ queryKey: ["catalog"], queryFn: () => api<CatalogReport[]>("/api/catalog") });
  const assignments = useQuery({
    queryKey: ["my-assignments"],
    queryFn: () => api<Assignment[]>("/api/me/assignments"),
    enabled: isSupervisor,
  });
  const allSchools = useAllSchools(!isSupervisor);
  const [formId, setFormId] = useState("");
  const [due, setDue] = useState(todayIn(district?.time_zone ?? "UTC"));
  const [instructions, setInstructions] = useState("");
  const [mode, setMode] = useState<"contacts" | "teachers">("contacts");
  const [schoolIds, setSchoolIds] = useState<string[]>([]);
  const [teacherSchool, setTeacherSchool] = useState("");
  const [teacherIds, setTeacherIds] = useState<string[]>([]);
  const teachers = useQuery({
    queryKey: ["teachers", "school", teacherSchool],
    queryFn: () => api<Page<Teacher>>(`/api/teachers${query({ school_id: teacherSchool, status: "active", page_size: 200 })}`),
    enabled: mode === "teachers" && !!teacherSchool,
  });
  const forms = (catalog.data ?? []).filter((r) => r.standalone_allowed).flatMap((r) =>
    r.versions.filter((v) => v.status === "active").map((v) => ({
      value: String(v.form_id),
      label: `${r.report_code} ${v.version_code} · ${i18n.language === "ar" ? v.title_ar || v.title_en : v.title_en || v.title_ar}`,
    })),
  );
  const schools = isSupervisor
    ? (assignments.data ?? []).filter((a) => a.state === "active").map((a) => a.school)
    : (allSchools.data ?? []);
  const schoolOptions = schools.map((s) => ({ value: String(s.id), label: `${s.code} · ${s.name}` }));
  const create = useAction(async () => {
    const created = await api<TeacherRequestSummary[]>("/api/requests", {
      method: "POST",
      body: {
        form_id: Number(formId),
        due_date: due,
        instructions: instructions || null,
        school_ids: mode === "contacts" ? schoolIds.map(Number) : [],
        teacher_ids: mode === "teachers" ? teacherIds.map(Number) : [],
      },
    });
    await client.invalidateQueries({ queryKey: ["requests"] });
    if (created.length === 1) navigate(`/requests/${created[0].id}`);
    else onClose();
  });
  const chosen = mode === "contacts" ? schoolIds.length : teacherIds.length;
  return (
    <Modal title={t("requests.new")} onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); void create.run(); }}>
        <SelectField label={t("evaluations.form")} value={formId} onChange={setFormId} required placeholder="" options={forms} />
        {catalog.data && forms.length === 0 && <p className="hint">{t("requests.noForms")}</p>}
        <DateField label={t("requests.due")} value={due} onChange={setDue} />
        <div className="field">
          <label htmlFor="request-instructions">{t("requests.instructions")} ({t("common.optional")})</label>
          <textarea id="request-instructions" dir="auto" rows={3} value={instructions} onChange={(e) => setInstructions(e.target.value)} />
        </div>
        <fieldset className="field checks">
          <legend>{t("requests.sendTo")}</legend>
          <label className="check">
            <input type="radio" checked={mode === "contacts"} onChange={() => setMode("contacts")} />
            {t("requests.toContacts")}
          </label>
          <label className="check">
            <input type="radio" checked={mode === "teachers"} onChange={() => setMode("teachers")} />
            {t("requests.toTeachers")}
          </label>
        </fieldset>
        {mode === "contacts" ? (
          <CheckboxGroup label={t("schools.title")} options={schoolOptions} value={schoolIds} onChange={setSchoolIds} />
        ) : (
          <>
            <SelectField label={t("schools.school")} value={teacherSchool} placeholder=""
              onChange={(v) => { setTeacherSchool(v); setTeacherIds([]); }} options={schoolOptions} />
            {teacherSchool && (
              <CheckboxGroup label={t("teachers.title")} value={teacherIds} onChange={setTeacherIds}
                options={(teachers.data?.items ?? []).map((tc) => ({ value: String(tc.id), label: `${tc.name} (${tc.staff_id})` }))} />
            )}
          </>
        )}
        <ErrorMessage error={create.error ?? catalog.error} />
        <div className="form-actions">
          <button type="button" onClick={onClose}>{t("common.cancel")}</button>
          <button type="submit" className="primary" disabled={create.busy || !formId || chosen === 0}>
            {t("requests.send", { count: chosen })}
          </button>
        </div>
      </form>
    </Modal>
  );
}
