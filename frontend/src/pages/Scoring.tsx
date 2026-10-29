import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { api, ApiError } from "../api";
import { ErrorMessage, Notice, PageHeader, StatusBadge, TextField, useAction } from "../components";
import { formatDateTime } from "../format";
import type { FormSchema } from "../forms/schema";
import { useSession } from "../session";
import type { FormDetail, Recalculation, RuleSet, RuleSetProblem } from "../types";

const SCORED = ["single_choice", "multi_choice", "yes_no", "number", "rating"];

/** A starting point: every question that can be scored, with placeholder points to fill in. */
function template(schema: FormSchema): Record<string, unknown> {
  const questions: Record<string, unknown> = {};
  for (const s of schema.sections) {
    for (const q of s.questions) {
      if (!SCORED.includes(q.type)) continue;
      if (q.type === "yes_no") questions[q.key] = { points: { yes: 1, no: 0 } };
      else if (q.type === "single_choice" || q.type === "multi_choice")
        questions[q.key] = { points: Object.fromEntries((q.options ?? []).map((o) => [o.code, 0])) };
      else if (q.max != null) questions[q.key] = { value: true };
      else questions[q.key] = { ranges: [{ min: 0, max: 10, points: 1 }] };
    }
  }
  return {
    questions,
    sections: {},
    missing: "exclude",
    decimals: 2,
    bands: [],
    examples: [
      {
        name: "Example 1",
        answers: Object.fromEntries(schema.sections.map((s) => [s.key, {}])),
        expected: { percent: 0 },
      },
    ],
  };
}

/**
 * FR-SC2, FR-SC3: the form's scoring formula as versioned rule sets. Builders draft and check them
 * against the district's worked examples; an admin activates one and recalculates stored scores.
 */
export default function Scoring() {
  const { id } = useParams();
  const { t, i18n } = useTranslation();
  const { me, district } = useSession();
  const tz = district?.time_zone ?? "UTC";
  const client = useQueryClient();
  const isAdmin = me?.role === "district_admin";
  const form = useQuery({ queryKey: ["form", id], queryFn: () => api<FormDetail>(`/api/forms/${id}`) });
  const ruleSets = useQuery({ queryKey: ["rule-sets", id], queryFn: () => api<RuleSet[]>(`/api/forms/${id}/rule-sets`) });
  const recalcs = useQuery({
    queryKey: ["recalculations", id],
    queryFn: () => api<Recalculation[]>(`/api/forms/${id}/recalculations`),
    enabled: isAdmin,
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === "queued" || r.status === "running") ? 2000 : false),
  });
  const [selected, setSelected] = useState<number | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const refresh = async () => {
    await client.invalidateQueries({ queryKey: ["rule-sets", id] });
    await client.invalidateQueries({ queryKey: ["recalculations", id] });
  };

  const create = useAction(async (from?: RuleSet) => {
    if (!form.data) return;
    const rules = from ? from.rules : template(form.data.schema);
    const made = await api<RuleSet>(`/api/forms/${id}/rule-sets`, { method: "POST", body: { rules, note: null } });
    await refresh();
    setSelected(made.id);
  });

  if (form.error) return <ErrorMessage error={form.error} />;
  if (!form.data) return <p>{t("common.loading")}</p>;
  const data = form.data;
  const list = ruleSets.data ?? [];
  const active = list.find((r) => r.status === "active");
  const current = list.find((r) => r.id === selected) ?? null;
  const title = i18n.language === "ar" ? data.catalog.title_ar || data.catalog.title_en : data.catalog.title_en || data.catalog.title_ar;

  return (
    <>
      <p><Link to={`/forms/${id}`}>← {data.report.code} · {data.catalog.version_code}</Link></p>
      <PageHeader title={t("scoring.title")}>
        <button type="button" disabled={create.busy} onClick={() => void create.run(active)}>
          {active ? t("scoring.newFromActive") : t("scoring.new")}
        </button>
      </PageHeader>
      <p>{title}</p>
      <p className="hint">{t("scoring.intro")}</p>
      {notice && <Notice>{notice}</Notice>}
      <ErrorMessage error={create.error ?? ruleSets.error} />
      <div className="card">
        <h2>{t("scoring.ruleSets")}</h2>
        {list.length === 0 && <p className="hint">{t("scoring.none")}</p>}
        <ul className="timeline">
          {list.map((r) => (
            <li key={r.id}>
              <button type="button" className="link" onClick={() => setSelected(r.id)} aria-current={r.id === selected}>
                {t("scoring.ruleSetN", { n: r.number })}
              </button>{" "}
              <StatusBadge status={r.status} />
              {r.note && <span dir="auto"> · {r.note}</span>}
              <div className="hint">
                {r.activated_at
                  ? t("scoring.activatedBy", { name: r.activated_by, at: formatDateTime(r.activated_at, tz) })
                  : t("scoring.createdBy", { name: r.created_by, at: formatDateTime(r.created_at, tz) })}
              </div>
            </li>
          ))}
        </ul>
      </div>
      {current && (
        <Editor key={`${current.id}-${current.version}`} id={current.id} isAdmin={isAdmin} onChanged={refresh}
          onActivated={() => setNotice(t("scoring.activated"))} />
      )}
      {isAdmin && (
        <Recalculate formId={Number(id)} active={active} history={recalcs.data ?? []} onStarted={refresh} />
      )}
    </>
  );
}

function ProblemList({ problems }: { problems: RuleSetProblem[] }) {
  const { t } = useTranslation();
  if (!problems.length) return null;
  return (
    <div className="alert alert-error" role="alert">
      <p>{t("scoring.problems")}</p>
      <ul>
        {problems.map((p, i) => (
          <li key={i}>
            <span className="ltr">{p.where}</span>: {t(`scoring.problem.${p.code}`, { defaultValue: p.code })}
            {p.detail && <span className="ltr"> ({p.detail})</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Editor({ id, isAdmin, onChanged, onActivated }: { id: number; isAdmin: boolean; onChanged: () => Promise<void>; onActivated: () => void }) {
  const { t } = useTranslation();
  const rs = useQuery({ queryKey: ["rule-set", id], queryFn: () => api<RuleSet>(`/api/rule-sets/${id}`) });
  const [text, setText] = useState("");
  const [note, setNote] = useState("");
  const [parseError, setParseError] = useState(false);
  const [dirty, setDirty] = useState(false);
  const client = useQueryClient();
  useEffect(() => {
    if (rs.data && !dirty) {
      setText(JSON.stringify(rs.data.rules, null, 2));
      setNote(rs.data.note ?? "");
    }
  }, [rs.data, dirty]);
  const save = useAction(async () => {
    let rules: unknown;
    try {
      rules = JSON.parse(text);
      setParseError(false);
    } catch {
      setParseError(true);
      return;
    }
    const saved = await api<RuleSet>(`/api/rule-sets/${id}`, { method: "PATCH", body: { version: rs.data!.version, rules, note: note || null } });
    client.setQueryData(["rule-set", id], saved);
    setDirty(false);
    await onChanged();
  });
  const activate = useAction(async () => {
    const done = await api<RuleSet>(`/api/rule-sets/${id}/activate`, { method: "POST", body: { version: rs.data!.version } });
    client.setQueryData(["rule-set", id], done);
    await onChanged();
    onActivated();
  });
  const discard = useAction(async () => {
    if (!window.confirm(t("scoring.confirmDiscard"))) return;
    const done = await api<RuleSet>(`/api/rule-sets/${id}/discard`, { method: "POST", body: { version: rs.data!.version } });
    client.setQueryData(["rule-set", id], done);
    await onChanged();
  });
  if (rs.error) return <ErrorMessage error={rs.error} />;
  if (!rs.data) return <p>{t("common.loading")}</p>;
  const r = rs.data;
  const draft = r.status === "draft";
  const examples = r.examples ?? [];
  const problems = r.problems ?? [];
  const ready = !dirty && problems.length === 0 && examples.length > 0 && examples.every((e) => e.matches);
  const saveError = save.error instanceof ApiError && save.error.code === "rule_set_invalid" ? save.error : null;

  return (
    <div className="card">
      <h2>{t("scoring.ruleSetN", { n: r.number })} <StatusBadge status={r.status} /></h2>
      {draft ? <p className="hint">{t("scoring.editHint")}</p> : <p className="hint">{t("scoring.fixed")}</p>}
      <div className="field">
        <label htmlFor="rules-json">{t("scoring.rules")}</label>
        <textarea id="rules-json" className="code-block" dir="ltr" rows={18} spellCheck={false} readOnly={!draft} value={text}
          onChange={(e) => { setText(e.target.value); setDirty(true); }} />
        {parseError && <div className="field-error" role="alert">{t("scoring.notJson")}</div>}
      </div>
      {draft && (
        <TextField label={`${t("scoring.note")} (${t("common.optional")})`} value={note} onChange={(v) => { setNote(v); setDirty(true); }} />
      )}
      <ProblemList problems={problems} />
      {saveError && (
        <ProblemList problems={(saveError.detail as RuleSetProblem[]) ?? []} />
      )}
      <h3>{t("scoring.examples")}</h3>
      {examples.length === 0 ? (
        <p className="hint">{t("scoring.noExamples")}</p>
      ) : (
        <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{t("scoring.example")}</th>
              <th>{t("scoring.points")}</th>
              <th>{t("scoring.percent")}</th>
              <th>{t("scoring.band")}</th>
              <th>{t("scoring.matches")}</th>
            </tr>
          </thead>
          <tbody>
            {examples.map((e) => (
              <tr key={e.name}>
                <td dir="auto">{e.name}</td>
                <td className="ltr">{e.result.points} / {e.result.max}</td>
                <td className="ltr">{e.result.percent ?? "-"}</td>
                <td>{e.result.band?.en ?? "-"}</td>
                <td>{e.matches ? <span className="badge badge-active">{t("scoring.match")}</span> : (
                  <span className="badge badge-warn">{t("scoring.mismatch", { what: e.mismatches.join(", ") })}</span>
                )}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}
      {draft && (
        <div className="page-actions">
          <button type="button" className={isAdmin ? undefined : "primary"} disabled={save.busy || !dirty} onClick={() => void save.run()}>
            {t("scoring.saveAndCheck")}
          </button>
          {isAdmin && (
            <button type="button" className="primary" disabled={!ready || activate.busy} onClick={() => void activate.run()}
              title={ready ? undefined : t("scoring.notReady")}>
              {t("scoring.activate")}
            </button>
          )}
          <button type="button" className="link danger" onClick={() => void discard.run()}>{t("scoring.discard")}</button>
        </div>
      )}
      {draft && !ready && <p className="hint">{t("scoring.notReady")}</p>}
      <ErrorMessage error={saveError ? null : save.error ?? activate.error ?? discard.error} />
    </div>
  );
}

function Recalculate({ formId, active, history, onStarted }: { formId: number; active?: RuleSet; history: Recalculation[]; onStarted: () => Promise<void> }) {
  const { t } = useTranslation();
  const { district } = useSession();
  const tz = district?.time_zone ?? "UTC";
  const [reason, setReason] = useState("");
  const start = useAction(async () => {
    await api(`/api/forms/${formId}/recalculations`, { method: "POST", body: { reason } });
    setReason("");
    await onStarted();
  });
  return (
    <div className="card">
      <h2>{t("scoring.recalculate")}</h2>
      <p className="hint">{t("scoring.recalculateHint")}</p>
      {active ? (
        <form onSubmit={(e) => { e.preventDefault(); void start.run(); }}>
          <TextField label={t("common.reason")} value={reason} onChange={setReason} required />
          <button type="submit" disabled={start.busy || reason.trim().length < 3}>
            {t("scoring.recalculateWith", { n: active.number })}
          </button>
        </form>
      ) : (
        <p className="hint">{t("scoring.noActive")}</p>
      )}
      <ErrorMessage error={start.error} />
      {history.length > 0 && (
        <ul className="timeline">
          {history.map((r) => (
            <li key={r.id}>
              <strong>{t("scoring.ruleSetN", { n: r.rule_set.number })}</strong> · <StatusBadge status={r.status} /> ·{" "}
              {t("scoring.recalcCounts", { evaluations: r.evaluations, changed: r.changed })}
              <div className="hint">
                <span dir="auto">{r.reason}</span> · {r.requested_by} · <span className="ltr">{formatDateTime(r.requested_at, tz)}</span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
