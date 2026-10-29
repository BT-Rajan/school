export type Role = "district_admin" | "form_author" | "cluster_head" | "supervisor" | "teacher";

export interface Me {
  id: number;
  name: string;
  email: string;
  role: Role;
  locale: "en" | "ar";
  mfa_method: "email" | "totp";
  totp_required: boolean;
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
