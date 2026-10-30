import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, ApiError } from "../api";
import { DateField, ErrorMessage, Modal, PageHeader, SelectField, StatusBadge, useAction } from "../components";
import { formatDate, formatDateTime } from "../format";
import { useClusters } from "../hooks";
import { useSession } from "../session";
import type { Assignment, Board } from "../types";

type School = Board["schools"][number];
type Dialog =
  | { kind: "assign"; school: School }
  | { kind: "end"; assignment: Assignment }
  | { kind: "reassign"; assignment: Assignment }
  | { kind: "history"; school: School };

/** FR-AS1 to FR-AS9: who supervises which school, from when, and why. */
export default function Assignments() {
  const { t } = useTranslation();
  const clusters = useClusters();
  const client = useQueryClient();
  const [clusterId, setClusterId] = useState("");
  const [dialog, setDialog] = useState<Dialog | null>(null);
  useEffect(() => {
    const first = clusters.data?.find((c) => c.status === "active");
    if (!clusterId && first) setClusterId(String(first.id));
  }, [clusters.data, clusterId]);
  const board = useQuery({
    queryKey: ["board", clusterId],
    queryFn: () => api<Board>(`/api/assignments/board?cluster_id=${clusterId}`),
    enabled: !!clusterId,
  });
  const refresh = () => client.invalidateQueries({ queryKey: ["board"] });
  const done = async () => {
    setDialog(null);
    await refresh();
  };

  return (
    <>
      <PageHeader title={t("assignments.title")} />
      <div className="filters">
        <SelectField label={t("schools.cluster")} value={clusterId} onChange={setClusterId}
          options={(clusters.data ?? []).map((c) => ({ value: String(c.id), label: `${c.code} · ${c.name}` }))} />
      </div>
      <ErrorMessage error={clusters.error ?? board.error} />
      {board.data && (
        <div className="board">
          <div className="table-wrap" tabIndex={0}>
            <table>
              <thead>
                <tr>
                  <th>{t("schools.school")}</th>
                  <th>{t("assignments.supervisors")}</th>
                  <th>{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {board.data.schools.map((s) => (
                  <tr key={s.id}>
                    <td>
                      <span className="ltr">{s.code}</span> · {s.name}
                    </td>
                    <td>
                      {s.assignments.length === 0 && <span className="badge badge-warn">{t("assignments.unassigned")}</span>}
                      <ul className="chips">
                        {s.assignments.map((a) => (
                          <li key={a.id} className="chip">
                            <span>{a.supervisor.name}</span> <StatusBadge status={a.state} />
                            <span className="hint ltr">
                              {formatDate(a.start_date)}{a.end_date ? ` – ${formatDate(a.end_date)}` : ""}
                            </span>
                            <button type="button" className="link" onClick={() => setDialog({ kind: "reassign", assignment: a })}>
                              {t("assignments.reassign")}
                            </button>
                            <button type="button" className="link" onClick={() => setDialog({ kind: "end", assignment: a })}>
                              {t("assignments.end")}
                            </button>
                          </li>
                        ))}
                      </ul>
                    </td>
                    <td>
                      <div className="row-actions">
                        <button type="button" onClick={() => setDialog({ kind: "assign", school: s })}>{t("assignments.assign")}</button>
                        <button type="button" onClick={() => setDialog({ kind: "history", school: s })}>{t("assignments.history")}</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="card">
            <h2>{t("assignments.workload")}</h2>
            <ul className="workload">
              {board.data.supervisors.map((s) => (
                <li key={s.id}>
                  {s.name} <span className="hint ltr">({s.staff_id})</span>: {t("assignments.schoolsCount", { count: s.active_schools })}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
      {dialog?.kind === "assign" && board.data && (
        <AssignDialog school={dialog.school} board={board.data} onClose={() => setDialog(null)} onDone={done} />
      )}
      {(dialog?.kind === "end" || dialog?.kind === "reassign") && board.data && (
        <ChangeDialog kind={dialog.kind} assignment={dialog.assignment} board={board.data} onClose={() => setDialog(null)}
          onDone={done} />
      )}
      {dialog?.kind === "history" && <HistoryDialog school={dialog.school} onClose={() => setDialog(null)} />}
    </>
  );
}

function ReasonField({ value, onChange, required }: { value: string; onChange: (v: string) => void; required?: boolean }) {
  const { t } = useTranslation();
  return (
    <div className="field">
      <label htmlFor="assignment-reason">{required ? t("common.reason") : `${t("common.reason")} (${t("common.optional")})`}</label>
      <textarea id="assignment-reason" dir="auto" rows={3} required={required} value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

function AssignDialog({ school, board, onClose, onDone }: { school: School; board: Board; onClose: () => void; onDone: () => Promise<void> }) {
  const { t } = useTranslation();
  const taken = new Set(school.assignments.map((a) => a.supervisor.id));
  const [supervisor, setSupervisor] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [reason, setReason] = useState("");
  const save = useAction(async () => {
    await api("/api/assignments", {
      method: "POST",
      body: { supervisor_id: Number(supervisor), school_id: school.id, start_date: start || null, end_date: end || null, reason: reason || null },
    });
    await onDone();
  });
  return (
    <Modal title={`${t("assignments.assign")} · ${school.name}`} onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); void save.run(); }}>
        <SelectField label={t("roles.supervisor")} value={supervisor} onChange={setSupervisor} required placeholder=""
          options={board.supervisors.filter((s) => !taken.has(s.id)).map((s) => ({
            value: String(s.id),
            label: `${s.name} (${t("assignments.schoolsCount", { count: s.active_schools })})`,
          }))} />
        <div className="form-grid">
          <DateField label={t("assignments.startDate")} value={start} onChange={setStart} />
          <DateField label={`${t("assignments.endDate")} (${t("common.optional")})`} value={end} onChange={setEnd} />
        </div>
        <p className="hint">{t("assignments.startHint")}</p>
        <ReasonField value={reason} onChange={setReason} />
        <ErrorMessage error={save.error} />
        <div className="form-actions">
          <button type="button" onClick={onClose}>{t("common.cancel")}</button>
          <button type="submit" className="primary" disabled={save.busy || !supervisor}>{t("assignments.assign")}</button>
        </div>
      </form>
    </Modal>
  );
}

/** Ending or reassigning. Open evaluation drafts need a decision: transfer them or cancel them (FR-AS9). */
function ChangeDialog({ kind, assignment, board, onClose, onDone }: {
  kind: "end" | "reassign";
  assignment: Assignment;
  board: Board;
  onClose: () => void;
  onDone: () => Promise<void>;
}) {
  const { t } = useTranslation();
  const [current, setCurrent] = useState(assignment);
  const [date, setDate] = useState("");
  const [reason, setReason] = useState("");
  const [target, setTarget] = useState("");
  const [drafts, setDrafts] = useState<{ count: number } | null>(null);
  const [choice, setChoice] = useState<"transfer" | "cancel">("transfer");
  const [transferTo, setTransferTo] = useState("");
  const others = board.schools
    .find((s) => s.id === assignment.school.id)
    ?.assignments.filter((a) => a.supervisor.id !== assignment.supervisor.id && a.state !== "ended") ?? [];
  const save = useAction(async () => {
    try {
      if (kind === "end") {
        await api(`/api/assignments/${current.id}/end`, {
          method: "POST",
          body: {
            version: current.version,
            end_date: date || null,
            reason,
            drafts: drafts ? choice : null,
            transfer_to_supervisor_id: drafts && choice === "transfer" ? Number(transferTo) : null,
          },
        });
      } else {
        await api(`/api/assignments/${current.id}/reassign`, {
          method: "POST",
          body: {
            version: current.version,
            to_supervisor_id: Number(target),
            effective_date: date || null,
            reason,
            drafts: drafts ? choice : null,
          },
        });
      }
    } catch (error) {
      if (error instanceof ApiError && error.code === "drafts_open") {
        setDrafts(error.detail as { count: number });
        return;
      }
      if (error instanceof ApiError && error.code === "version_conflict") {
        // Someone else changed it: show their version and let the user decide again.
        const latest = (error.detail as { current?: Assignment })?.current;
        if (latest) setCurrent(latest);
      }
      throw error;
    }
    await onDone();
  });
  return (
    <Modal title={`${t(kind === "end" ? "assignments.end" : "assignments.reassign")} · ${assignment.school.name}`} onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); void save.run(); }}>
        <p>
          {current.supervisor.name} · <span className="ltr">{formatDate(current.start_date)}</span>
          {current.end_date && <span className="ltr"> – {formatDate(current.end_date)}</span>}
        </p>
        {kind === "reassign" && (
          <SelectField label={t("assignments.newSupervisor")} value={target} onChange={setTarget} required placeholder=""
            options={board.supervisors.filter((s) => s.id !== current.supervisor.id).map((s) => ({ value: String(s.id), label: s.name }))} />
        )}
        <DateField label={kind === "end" ? t("assignments.endDate") : t("assignments.effectiveDate")} value={date} onChange={setDate} />
        <p className="hint">{t("assignments.todayHint")}</p>
        <ReasonField value={reason} onChange={setReason} required />
        {drafts && (
          <fieldset className="field checks">
            <legend>{t("assignments.draftsOpen", { count: drafts.count })}</legend>
            <label className="check">
              <input type="radio" checked={choice === "transfer"} onChange={() => setChoice("transfer")} />
              {kind === "end" ? t("assignments.transferDrafts") : t("assignments.transferToNew")}
            </label>
            <label className="check">
              <input type="radio" checked={choice === "cancel"} onChange={() => setChoice("cancel")} />
              {t("assignments.cancelDrafts")}
            </label>
            {kind === "end" && choice === "transfer" && (
              <SelectField label={t("assignments.transferTo")} value={transferTo} onChange={setTransferTo} required placeholder=""
                options={others.map((a) => ({ value: String(a.supervisor.id), label: a.supervisor.name }))} />
            )}
            {kind === "end" && choice === "transfer" && others.length === 0 && (
              <p className="hint">{t("assignments.noOtherSupervisor")}</p>
            )}
          </fieldset>
        )}
        <ErrorMessage error={save.error} />
        <div className="form-actions">
          <button type="button" onClick={onClose}>{t("common.cancel")}</button>
          <button type="submit" className="primary" disabled={save.busy}>
            {t(kind === "end" ? "assignments.end" : "assignments.reassign")}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function HistoryDialog({ school, onClose }: { school: School; onClose: () => void }) {
  const { t } = useTranslation();
  const { district } = useSession();
  const history = useQuery({
    queryKey: ["assignment-history", school.id],
    queryFn: () => api<Assignment[]>(`/api/assignments/history?school_id=${school.id}`),
  });
  return (
    <Modal title={`${t("assignments.history")} · ${school.name}`} onClose={onClose}>
      <ErrorMessage error={history.error} />
      <div className="table-wrap" tabIndex={0}>
        <table>
          <thead>
            <tr>
              <th>{t("roles.supervisor")}</th>
              <th>{t("assignments.period")}</th>
              <th>{t("common.status")}</th>
              <th>{t("assignments.who")}</th>
            </tr>
          </thead>
          <tbody>
            {history.data?.map((a) => (
              <tr key={a.id}>
                <td>{a.supervisor.name}</td>
                <td className="ltr">{formatDate(a.start_date)} – {a.end_date ? formatDate(a.end_date) : "…"}</td>
                <td><StatusBadge status={a.state} /></td>
                <td>
                  <div>{t("assignments.createdBy", { name: a.created_by, at: formatDateTime(a.created_at, district?.time_zone ?? "UTC") })}</div>
                  {a.reason && <div className="hint" dir="auto">{a.reason}</div>}
                  {a.ended_by && (
                    <div>{t("assignments.endedBy", { name: a.ended_by, at: formatDateTime(a.ended_at, district?.time_zone ?? "UTC") })}</div>
                  )}
                  {a.end_reason && <div className="hint" dir="auto">{a.end_reason}</div>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Modal>
  );
}
