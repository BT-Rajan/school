export type Role = "district_admin" | "form_author" | "cluster_head" | "supervisor" | "teacher";

export interface Me {
  id: number;
  name: string;
  email: string;
  role: Role;
  locale: "en" | "ar";
  mfa_method: "email" | "totp";
  totp_required: boolean;
  /** FR-AD3: admins' support views of this account, shown once at sign-in. */
  support_notices?: { id: number; admin: string; reason: string; started_at: string; ended_at: string }[];
  /** Set while an admin views this account read-only. */
  support_view?: { admin: string } | null;
}

export interface District {
  code: string;
  name_en: string;
  name_ar: string;
  default_locale: string;
  enabled_locales: string[];
  date_format: string;
  time_zone: string;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
}

export interface Ref {
  code: string;
  name_en: string;
  name_ar: string;
}

export interface ReferenceValue extends Ref {
  id: number;
  list: string;
  sort_order: number;
  status: string;
  version: number;
}

export interface CustomField {
  id: number;
  entity: "teacher" | "school";
  key: string;
  field_type: "text" | "number" | "date" | "single_choice" | "multi_choice" | "yes_no";
  label_en: string;
  label_ar: string;
  required: boolean;
  options: { code: string; en: string; ar: string }[];
  validation: Record<string, number>;
  sort_order: number;
  status: string;
  version: number;
}

export type CustomValues = Record<string, string | number | boolean | string[]>;

export interface Cluster {
  id: number;
  code: string;
  name: string;
  cluster_head: { id: number; name: string; email: string } | null;
  status: string;
  version: number;
}

export interface School {
  id: number;
  code: string;
  name: string;
  cluster: { id: number; code: string; name: string };
  address: string;
  school_type: string;
  medium: string;
  contact_phone: string;
  contact_email: string | null;
  contact_teacher: { teacher_id: number; name: string; since: string } | null;
  custom: CustomValues;
  status: string;
  version: number;
}

export interface Teacher {
  id: number;
  user_id: number;
  staff_id: string;
  name: string;
  email: string;
  account_status: string;
  status: string;
  district: string;
  cluster: { id: number; code: string; name: string };
  school: { id: number; code: string; name: string };
  designation: Ref;
  subjects: Ref[];
  classes: Ref[];
  experience_years: number;
  experience_recorded: { years: number; as_of: string };
  qualifications: (Ref & { year: number | null })[];
  custom: CustomValues;
  version: number;
}

export interface Supervisor {
  id: number;
  user_id: number;
  staff_id: string;
  name: string;
  email: string;
  account_status: string;
  status: string;
  cluster: { id: number; code: string; name: string };
  version: number;
}

export interface StaffUser {
  id: number;
  role: Role;
  staff_id: string | null;
  name: string;
  email: string;
  locale: string;
  status: string;
  mfa_method: string;
  locked: boolean;
  last_login_at: string | null;
  version: number;
  locked_until?: string;
}

export interface ImportRow {
  row: number;
  key: string;
  action: "created" | "updated" | "unchanged" | "error";
  errors: { field?: string; code: string; value?: string }[];
}

export interface ImportBatch {
  id: number;
  entity: string;
  filename: string;
  status: "previewed" | "committed";
  summary: Record<string, number>;
  rows: ImportRow[];
  invitation_schedule: { date: string; count: number }[];
}

// Phase 2 ------------------------------------------------------------------------------------

export interface Bilingual {
  en: string;
  ar: string;
}

export interface Assignment {
  id: number;
  supervisor: { id: number; name: string; staff_id: string };
  school: { id: number; code: string; name: string };
  start_date: string;
  end_date: string | null;
  state: "upcoming" | "active" | "ended";
  reason: string | null;
  end_reason: string | null;
  version: number;
  created_by?: string;
  created_at?: string;
  ended_by?: string | null;
  ended_at?: string | null;
}

export interface Board {
  cluster: { id: number; code: string; name: string };
  schools: { id: number; code: string; name: string; assignments: Assignment[] }[];
  supervisors: { id: number; name: string; staff_id: string; active_schools: number }[];
}

export type FormStatus = "draft" | "in_review" | "scheduled" | "active" | "closed";

export interface CatalogVersion {
  id: number;
  version_code: string;
  title_en: string;
  title_ar: string;
  ministry_published_on: string | null;
  source_file_id: number | null;
  form_id: number;
  status: FormStatus;
  start_date: string | null;
  end_date: string | null;
}

export interface CatalogReport {
  id: number;
  report_code: string;
  subject_type: "school" | "teacher";
  standalone_allowed: boolean;
  versions: CatalogVersion[];
}

export interface FormSummary {
  id: number;
  report: { id: number; code: string; subject_type: "school" | "teacher" };
  catalog: {
    id: number;
    version_code: string;
    title_en: string;
    title_ar: string;
    ministry_published_on: string | null;
    source_file_id: number | null;
  };
  status: FormStatus;
  start_date: string | null;
  end_date: string | null;
  closed_at: string | null;
  version: number;
}

export interface FormDetail extends FormSummary {
  schema: import("./forms/schema").FormSchema;
  problems: Problem[];
}

export interface FormComment {
  action: string;
  comment: string;
  by: string;
  role: Role;
  at: string;
}

export interface Problem {
  where: string;
  code: string;
}

export interface EvaluationSummary {
  id: number;
  form_id: number;
  report: { code: string; version_code: string; title_en: string; title_ar: string };
  subject_type: "school" | "teacher";
  school: { id: number; code: string; name: string };
  teacher: { id: number; name: string; staff_id?: string } | null;
  supervisor: { id: number; name: string };
  status: "draft" | "submitted" | "amended" | "cancelled";
  visit_date: string | null;
  submitted_at: string | null;
  amended_at: string | null;
  form_status: FormStatus;
  form_end_date: string | null;
  /** FR-SC3: calculated on the server at submission, with the rule set that gave it. */
  score: Score | null;
  version: number;
}

export interface Score {
  points: number;
  max: number;
  percent: number | null;
  band: { en: string; ar: string } | null;
  sections: Record<string, { points: number; max: number }>;
  rule_set_id: number;
  rule_set_number: number;
  calculated_at: string;
}

export interface RuleSetProblem {
  where: string;
  code: string;
  detail?: string;
}

export interface RuleSet {
  id: number;
  form_id: number;
  number: number;
  status: "draft" | "active" | "retired" | "discarded";
  rules: Record<string, unknown>;
  note: string | null;
  created_by: string | null;
  created_at: string;
  activated_by: string | null;
  activated_at: string | null;
  retired_at: string | null;
  version: number;
  problems?: RuleSetProblem[];
  examples?: { name: string; matches: boolean; mismatches: string[]; result: Omit<Score, "rule_set_id" | "rule_set_number" | "calculated_at"> }[];
}

export interface Recalculation {
  id: number;
  form_id: number;
  rule_set: { id: number; number: number };
  reason: string;
  status: "queued" | "running" | "done" | "failed";
  evaluations: number;
  changed: number;
  requested_by: string | null;
  requested_at: string;
  finished_at: string | null;
}

export type RequestStatus = "not_started" | "in_progress" | "submitted" | "returned" | "waived" | "cancelled";

export interface EvaluationRequest {
  id: number;
  status: RequestStatus;
  overdue: boolean;
  due_date: string;
  teacher: { id: number; name: string } | null;
  pending_teacher: string | null;
  return_count: number;
  close_reason: string | null;
}

export interface Evaluation extends EvaluationSummary {
  request: EvaluationRequest | null;
  visit_notes: string | null;
  location: { latitude: number; longitude: number; accuracy_m: number | null } | null;
  cancel_reason: string | null;
  sections: {
    key: string;
    respondent: "supervisor" | "teacher";
    status: string;
    answers: Record<string, unknown>;
    submitted_at: string | null;
  }[];
}

export interface Amendment {
  reason: string;
  prior: { visit_date: string | null; visit_notes: string | null; sections: Record<string, Record<string, unknown>> };
  by: string;
  at: string;
}

export type DocumentStatus = "draft" | "submitted" | "viewed" | "acknowledged" | "returned" | "withdrawn" | "deleted";

export interface ReportRef {
  code: string;
  version_code: string;
  version_id: number;
  title_en: string;
  title_ar: string;
}

export interface DocumentSummary {
  id: number;
  title: string;
  report: ReportRef;
  school: { id: number; code: string; name: string };
  cluster_id: number;
  teacher_id: number | null;
  evaluation_id: number | null;
  supervisor: { id: number; name: string };
  report_date: string;
  status: DocumentStatus;
  submitted_at: string | null;
  first_viewed_at: string | null;
  acknowledged_at: string | null;
  returned_at: string | null;
  review_comment: string | null;
  archived: boolean;
  overdue: boolean;
  retention_expired: boolean;
  file: { status: string; pages: number | null; size: number } | null;
  mine: boolean;
  version: number;
}

export interface DocumentDetail extends DocumentSummary {
  notes: string | null;
  tags: string[];
  acknowledged_by: string | null;
  returned_by: string | null;
  first_viewed_by: string | null;
  versions: { id: number; number: number; reason: string | null; created_at: string; current: boolean }[];
  forwards?: { id: number; cluster_id: number; note: string | null; by: string | null; at: string; revoked_at: string | null }[];
}

export interface AccessEvent {
  action: string;
  by: string;
  role: Role;
  at: string;
}

export interface SupervisorDashboard {
  counts: Partial<Record<DocumentStatus, number>>;
  returned: DocumentSummary[];
  coverage: { report: ReportRef; schools: { id: number; code: string; name: string; covered: boolean }[] }[];
  per_month: { month: string; count: number }[];
  access_history: (AccessEvent & { document_id: number; title?: string })[];
}

export interface UploadedFile {
  id: number;
  name: string;
  mime_type: string;
  size: number;
  pages: number | null;
  sha256: string;
  status: "pending" | "clean" | "quarantined" | string;
  created_at: string;
}

export interface NotificationItem {
  id: number;
  type: string;
  payload: Record<string, unknown>;
  text: Bilingual;
  read: boolean;
  created_at: string;
}

export interface NotificationPreference {
  type: string;
  in_app: boolean;
  email: boolean;
  push: boolean;
}

export interface TeacherRequestSummary {
  id: number;
  kind: "evaluation" | "standalone";
  report: { code: string; version_code: string; title_en: string; title_ar: string };
  school: { id: number; code: string; name: string };
  teacher: { id: number; name: string } | null;
  pending_teacher: { id: number; name: string } | null;
  via_contact: boolean;
  requester: string;
  evaluation: { id: number; subject_type: "school" | "teacher"; status: string; about: string | null } | null;
  status: RequestStatus;
  overdue: boolean;
  due_date: string;
  submitted_at: string | null;
  returned_at: string | null;
  return_comment: string | null;
  return_count: number;
  closed_at: string | null;
  close_reason: string | null;
  version: number;
  can: { answer: boolean; manage: boolean; waive: boolean };
}

export interface TeacherRequestDetail extends TeacherRequestSummary {
  instructions: string | null;
  sections: import("./forms/schema").Section[];
  answers: Record<string, Record<string, unknown>>;
}

export interface RequestEvent {
  action: string;
  by: string | null;
  at: string;
  detail: Record<string, unknown> | null;
}

export interface Onboarding {
  active: number;
  invited: number;
  needs_invitation: number;
}
