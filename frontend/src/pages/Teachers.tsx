import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, ApiError, query } from "../api";
import {
  CheckboxGroup,
  CustomFieldInputs,
  DateField,
  ErrorMessage,
  Modal,
  Notice,
  PageHeader,
  Pager,
  SelectField,
  StatusBadge,
  TextField,
  useAction,
  useRefName,
} from "../components";
import { formatDate } from "../format";
import { useAllSchools, useCustomFields, useReference } from "../hooks";
import { useSession } from "../session";
import type { CustomValues, Onboarding, Page, Teacher } from "../types";

const PAGE_SIZE = 50;

interface Form {
  staff_id: string;
  name: string;
  email: string;
  school_id: string;
  designation: string;
  subjects: string[];
  classes: string[];
  experience_years: string;
  qualifications: { code: string; year: string }[];
  custom: CustomValues;
}

const empty: Form = {
  staff_id: "", name: "", email: "", school_id: "", designation: "", subjects: [], classes: [], experience_years: "",
  qualifications: [], custom: {},
};

function toForm(tch: Teacher): Form {
  return {
    staff_id: tch.staff_id, name: tch.name, email: tch.email, school_id: String(tch.school.id),
    designation: tch.designation.code, subjects: tch.subjects.map((s) => s.code), classes: tch.classes.map((c) => c.code),
    experience_years: String(tch.experience_recorded.years),
    qualifications: tch.qualifications.map((q) => ({ code: q.code, year: q.year ? String(q.year) : "" })),
    custom: tch.custom,
  };
}

export default function Teachers() {
  const { t } = useTranslation();
  const { me } = useSession();
  const isAdmin = me?.role === "district_admin";
  const refName = useRefName();
  const client = useQueryClient();
  const schools = useAllSchools();
  const designations = useReference("designation");
  const subjects = useReference("subject");
  const classes = useReference("class");
  const qualifications = useReference("qualification");
  const customFields = useCustomFields("teacher");

  const [q, setQ] = useState("");
  const [schoolId, setSchoolId] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const list = useQuery({
    queryKey: ["teachers", q, schoolId, status, page],
    queryFn: () => api<Page<Teacher>>(`/api/teachers${query({ q, school_id: schoolId, status, page, page_size: PAGE_SIZE })}`),
    placeholderData: keepPreviousData,
  });
  const refresh = () => client.invalidateQueries({ queryKey: ["teachers"] });

  const [editing, setEditing] = useState<Teacher | "new" | null>(null);
  const [form, setForm] = useState<Form>(empty);
  const set = (patch: Partial<Form>) => setForm((f) => ({ ...f, ...patch }));
  const open = (teacher: Teacher | "new") => {
    setEditing(teacher);
    setForm(teacher === "new" ? { ...empty, school_id: schoolId } : toForm(teacher));
  };
  const save = useAction(async () => {
    const shared = {
      name: form.name,
      email: form.email,
      designation: form.designation,
      subjects: form.subjects,
      classes: form.classes,
      experience_years: form.experience_years === "" ? null : Number(form.experience_years),
      qualifications: form.qualifications.map((qual) => ({ code: qual.code, year: qual.year ? Number(qual.year) : null })),
      custom: form.custom,
    };
    try {
      if (editing === "new") {
        await api("/api/teachers", {
          method: "POST",
          body: { ...shared, staff_id: form.staff_id, school_id: Number(form.school_id) },
        });
      } else if (editing) {
        const changes: Record<string, unknown> = { ...shared, version: editing.version };
        if (form.email === editing.email) delete changes.email;
        if (Number(form.experience_years) === editing.experience_recorded.years) delete changes.experience_years;
        await api(`/api/teachers/${editing.id}`, { method: "PATCH", body: changes });
      }
    } catch (error) {
      if (error instanceof ApiError && error.code === "version_conflict") open((error.detail as { current: Teacher }).current);
      throw error;
    }
    setEditing(null);
    await refresh();
  });

  const [moving, setMoving] = useState<Teacher | null>(null);
  const [target, setTarget] = useState("");
  const [movedOn, setMovedOn] = useState("");
  const transfer = useAction(async () => {
    await api(`/api/teachers/${moving!.id}/transfer`, {
      method: "POST",
      body: { school_id: Number(target), moved_on: movedOn || null },
    });
    setMoving(null);
    await refresh();
  });

  const [notice, setNotice] = useState("");
  const accountAction = useAction(async (teacher: Teacher, action: "deactivate" | "reactivate" | "resend-invitation" | "mfa-reset") => {
    if (action === "deactivate" && !window.confirm(t("common.confirmDeactivate"))) return;
    if (action === "mfa-reset" && !window.confirm(t("staff.resetMfaConfirm"))) return;
    await api(`/api/users/${teacher.user_id}/${action}`, { method: "POST" });
    if (action === "resend-invitation") setNotice(t("teachers.inviteSent"));
    await refresh();
  });

  const schoolOptions = (schools.data ?? []).map((s) => ({ value: String(s.id), label: `${s.code} · ${s.name}` }));
  const refOptions = (values: typeof designations.data) =>
    (values ?? []).map((v) => ({ value: v.code, label: refName(v) }));
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void save.run();
  };
  const toggleQualification = (code: string, on: boolean) =>
    set({
      qualifications: on
        ? [...form.qualifications, { code, year: "" }]
        : form.qualifications.filter((qual) => qual.code !== code),
    });

  return (
    <>
      <PageHeader title={t("teachers.title")}>
        <button className="primary" type="button" onClick={() => open("new")}>{t("teachers.new")}</button>
      </PageHeader>
      <OnboardingCard />
      <div className="filters">
        <input type="search" value={q} placeholder={t("teachers.searchHint")} aria-label={t("common.search")}
          onChange={(e) => { setQ(e.target.value); setPage(1); }} />
        <select value={schoolId} aria-label={t("teachers.school")} onChange={(e) => { setSchoolId(e.target.value); setPage(1); }}>
          <option value="">{t("common.all")}</option>
          {schoolOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <select value={status} aria-label={t("common.status")} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
          <option value="">{t("common.anyStatus")}</option>
          <option value="active">{t("status.active")}</option>
          <option value="inactive">{t("status.inactive")}</option>
        </select>
      </div>
      {notice && <Notice>{notice}</Notice>}
      <ErrorMessage error={list.error ?? accountAction.error} />
      <div className="table-wrap" tabIndex={0}>
        <table>
          <thead>
            <tr>
              <th>{t("teachers.staffId")}</th>
              <th>{t("teachers.name")}</th>
              <th>{t("teachers.school")}</th>
              <th>{t("teachers.designation")}</th>
              <th>{t("teachers.subjects")}</th>
              <th>{t("teachers.experience")}</th>
              <th>{t("teachers.account")}</th>
              <th>{t("common.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {list.data?.items.map((tch) => (
              <tr key={tch.id}>
                <td className="ltr">{tch.staff_id}</td>
                <td>{tch.name}</td>
                <td className="ltr">{tch.school.code}</td>
                <td>{refName(tch.designation)}</td>
                <td>{tch.subjects.map(refName).join("، ")}</td>
                <td>{tch.experience_years}</td>
                <td><StatusBadge status={tch.account_status} /></td>
                <td>
                  <div className="row-actions">
                    <button type="button" onClick={() => open(tch)}>{t("common.edit")}</button>
                    <button type="button" onClick={() => { setMoving(tch); setTarget(""); setMovedOn(""); }}>
                      {t("teachers.transfer")}
                    </button>
                    {tch.account_status === "invited" && (
                      <button type="button" onClick={() => void accountAction.run(tch, "resend-invitation")}>
                        {t("teachers.resendInvite")}
                      </button>
                    )}
                    {isAdmin && tch.account_status === "active" && (
                      <button type="button" onClick={() => void accountAction.run(tch, "mfa-reset")}>{t("staff.resetMfa")}</button>
                    )}
                    <button type="button" className={tch.status === "active" ? "danger" : ""}
                      onClick={() => void accountAction.run(tch, tch.status === "active" ? "deactivate" : "reactivate")}>
                      {tch.status === "active" ? t("common.deactivate") : t("common.reactivate")}
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
        <Modal title={editing === "new" ? t("teachers.new") : t("teachers.edit")} onClose={() => setEditing(null)}>
          <form onSubmit={onSubmit}>
            <div className="form-grid">
              <TextField label={t("teachers.staffId")} value={form.staff_id} onChange={(v) => set({ staff_id: v })}
                required dir="ltr" disabled={editing !== "new"} />
              <TextField label={t("teachers.name")} value={form.name} onChange={(v) => set({ name: v })} required />
              <TextField label={t("teachers.email")} type="email" value={form.email} onChange={(v) => set({ email: v })}
                required dir="ltr" disabled={editing !== "new" && editing.account_status !== "invited"} />
              <SelectField label={t("teachers.school")} value={form.school_id} onChange={(v) => set({ school_id: v })}
                options={schoolOptions} placeholder="" required disabled={editing !== "new"} />
              <SelectField label={t("teachers.designation")} value={form.designation}
                onChange={(v) => set({ designation: v })} options={refOptions(designations.data)} placeholder="" required />
              <TextField label={t("teachers.experience")} value={form.experience_years} inputMode="numeric" dir="ltr"
                onChange={(v) => set({ experience_years: v.replace(/\D/g, "").slice(0, 2) })} required />
            </div>
            <CheckboxGroup label={t("teachers.subjects")} options={refOptions(subjects.data)} value={form.subjects}
              onChange={(v) => set({ subjects: v })} />
            <CheckboxGroup label={t("teachers.classes")} options={refOptions(classes.data)} value={form.classes}
              onChange={(v) => set({ classes: v })} />
            <fieldset className="field checks">
              <legend>{t("teachers.qualifications")}</legend>
              {(qualifications.data ?? []).map((qual) => {
                const chosen = form.qualifications.find((x) => x.code === qual.code);
                return (
                  <div key={qual.code} className="check">
                    <input type="checkbox" id={`q-${qual.code}`} checked={!!chosen}
                      onChange={(e) => toggleQualification(qual.code, e.target.checked)} />
                    <label htmlFor={`q-${qual.code}`}>{refName(qual)}</label>
                    {chosen && (
                      <input aria-label={t("teachers.year")} placeholder={t("teachers.year")} value={chosen.year}
                        inputMode="numeric" dir="ltr" style={{ width: "6em" }}
                        onChange={(e) => set({
                          qualifications: form.qualifications.map((x) =>
                            x.code === qual.code ? { ...x, year: e.target.value.replace(/\D/g, "").slice(0, 4) } : x),
                        })} />
                    )}
                  </div>
                );
              })}
            </fieldset>
            <div className="form-grid">
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

      {moving && (
        <Modal title={`${t("teachers.transfer")}: ${moving.name}`} onClose={() => setMoving(null)}>
          <form onSubmit={(e) => { e.preventDefault(); void transfer.run(); }}>
            <SelectField label={t("teachers.transferTo")} value={target} onChange={setTarget} placeholder="" required
              options={(schools.data ?? [])
                .filter((s) => s.cluster.id === moving.cluster.id && s.id !== moving.school.id)
                .map((s) => ({ value: String(s.id), label: `${s.code} · ${s.name}` }))} />
            <DateField label={t("teachers.transferDate")} value={movedOn} onChange={setMovedOn} />
            <ErrorMessage error={transfer.error} />
            <div className="form-actions">
              <button type="button" onClick={() => setMoving(null)}>{t("common.cancel")}</button>
              <button className="primary" type="submit" disabled={!target || transfer.busy}>{t("teachers.transfer")}</button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}

/** Phase 3: invite every teacher who has not joined, spread over days within the mail budget (FR-N8). */
function OnboardingCard() {
  const { t } = useTranslation();
  const client = useQueryClient();
  const status = useQuery({ queryKey: ["teacher-onboarding"], queryFn: () => api<Onboarding>("/api/teachers/onboarding") });
  const [planned, setPlanned] = useState<{ date: string; count: number }[] | null>(null);
  const invite = useAction(async () => {
    const result = await api<{ queued: number; by_day: { date: string; count: number }[] }>("/api/teachers/invitations", {
      method: "POST",
      body: {},
    });
    setPlanned(result.by_day);
    await client.invalidateQueries({ queryKey: ["teacher-onboarding"] });
  });
  if (!status.data) return null;
  const s = status.data;
  return (
    <div className="card onboarding">
      <p>{t("teachers.onboarding", { active: s.active, invited: s.invited, waiting: s.needs_invitation })}</p>
      {s.needs_invitation > 0 && (
        <button type="button" disabled={invite.busy} onClick={() => void invite.run()}>
          {t("teachers.inviteWaiting", { count: s.needs_invitation })}
        </button>
      )}
      {planned && planned.length > 0 && (
        <ul>
          {planned.map((p) => (
            <li key={p.date}>{t("teachers.plannedDay", { date: formatDate(p.date), count: p.count })}</li>
          ))}
        </ul>
      )}
      <ErrorMessage error={invite.error} />
    </div>
  );
}
