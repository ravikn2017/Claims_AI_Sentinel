import { useEffect, useState, type FormEvent } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import MenuItem from "@mui/material/MenuItem";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useParams } from "react-router-dom";
import { errorText, request } from "../../api";
import { ClaimStages, type AdjEvent, type HistoryRow } from "../../components/ClaimStages";
import { useActor } from "../../session";
import { FraudAssistant } from "./FraudAssistant";
import styles from "./CasePage.module.css";

type Task = {
  task_id: number;
  claim_id: string;
  summary: Record<string, unknown>;
  risk_score: string | null;
  status: string;
  task_type: string;
  assignee: string | null;
  picked_at: string | null;
  claim_status?: string | null;
  history?: HistoryRow[];
};

const leaseMs = 30 * 60 * 1000;

const words: Record<string, string> = {
  COVERED: "Covered",
  NOT_COVERED: "Not covered",
  NEEDS_INFO: "Needs information",
  CLEAR: "Clear",
  FLAGGED: "Flagged",
  NECESSARY: "Necessary",
  NOT_NECESSARY: "Not necessary",
  CONFIRMED: "Confirmed",
  CLEARED: "Cleared",
  approve: "Approve",
  deny: "Deny",
  APPROVED: "Approved",
  DENIED: "Denied",
  review: "A person should decide",
};

type AgentResult = {
  verdict?: unknown;
  confidence?: unknown;
  reasons?: unknown;
  error?: unknown;
  outcome?: unknown;
  notes?: unknown;
};

function phrase(value: unknown) {
  if (value == null || value === "") {
    return "";
  }
  const key = String(value);
  return words[key] ?? key.replaceAll("_", " ");
}

function asResult(value: unknown): AgentResult | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as AgentResult;
}

function reasonsOf(result: AgentResult | null) {
  if (!result || !Array.isArray(result.reasons)) {
    return [];
  }
  return result.reasons.map((reason) => phrase(reason)).filter(Boolean);
}

function confidenceOf(result: AgentResult | null) {
  const value = Number(result?.confidence);
  if (!Number.isFinite(value)) {
    return "";
  }
  return value <= 1 ? `${Math.round(value * 100)}% confidence` : `confidence ${value}`;
}

function Check({ title, result }: { title: string; result: AgentResult | null }) {
  if (!result || (result.verdict == null && result.error == null)) {
    return null;
  }
  const confidence = confidenceOf(result);
  const reasons = reasonsOf(result);
  return (
    <div className={styles.block}>
      <Typography sx={{ fontWeight: 700 }}>{title}</Typography>
      <Typography>
        {[phrase(result.verdict) || "No verdict", confidence].filter(Boolean).join(" · ")}
      </Typography>
      {result.error ? <Typography color="error">{String(result.error)}</Typography> : null}
      {reasons.length > 0 && (
        <ul className={styles.reasons}>
          {reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function latestEvent(events: AdjEvent[], eventType: string) {
  return [...events].reverse().find((event) => event.event_type === eventType);
}

function textOf(value: unknown) {
  return value == null ? "" : String(value).trim();
}

function SummaryView({ summary, events }: { summary: Record<string, unknown>; events: AdjEvent[] }) {
  const policy = asResult(summary.policy_result);
  const fraud = asResult(summary.fraud_result);
  const medical = asResult(summary.med_result);
  const recorded = asResult(summary.investigation);
  const investigationEvent = latestEvent(events, "INVESTIGATION_RESULT");
  const investigation = recorded || investigationEvent
    ? {
        outcome: recorded?.outcome ?? investigationEvent?.payload.outcome,
        notes: textOf(recorded?.notes) || textOf(investigationEvent?.payload.notes),
        actor: textOf(recorded && "investigator" in recorded ? recorded.investigator : investigationEvent?.payload.investigator) || investigationEvent?.actor || "",
      }
    : null;
  const reviewEvent = latestEvent(events, "REVIEW_DECIDED");
  const reviewNotes = textOf(reviewEvent?.payload.notes);
  const reviewer = textOf(reviewEvent?.payload.reviewer) || reviewEvent?.actor || "";
  const empty = !policy && !fraud && !medical && !investigation && !reviewEvent && summary.recommendation == null && summary.risk_score == null;
  if (empty) {
    return <Typography color="text.secondary">No summary recorded.</Typography>;
  }
  return (
    <div className={styles.card}>
      {summary.recommendation != null && (
        <div className={styles.block}>
          <Typography sx={{ fontWeight: 700 }}>Recommendation</Typography>
          <Typography>{phrase(summary.recommendation)}</Typography>
        </div>
      )}
      {summary.risk_score != null && summary.risk_score !== "" && (
        <div className={styles.block}>
          <Typography sx={{ fontWeight: 700 }}>Risk score</Typography>
          <Typography>{String(summary.risk_score)}</Typography>
        </div>
      )}
      <Check title="Policy check" result={policy} />
      <Check title="Fraud check" result={fraud} />
      <Check title="Medical necessity" result={medical} />
      {investigation && (investigation.outcome != null || investigation.notes) && (
        <div className={styles.block}>
          <Typography sx={{ fontWeight: 700 }}>Investigation</Typography>
          <Typography>{phrase(investigation.outcome) || "Waiting for an outcome"}{investigation.actor ? ` · ${investigation.actor}` : ""}</Typography>
          <Typography>{investigation.notes || "No notes recorded"}</Typography>
        </div>
      )}
      {reviewEvent && (
        <div className={styles.block}>
          <Typography sx={{ fontWeight: 700 }}>Review decision</Typography>
          <Typography>{phrase(reviewEvent.payload.decision)}{reviewer ? ` · ${reviewer}` : ""}</Typography>
          <Typography>{reviewNotes || "No notes recorded"}</Typography>
        </div>
      )}
    </div>
  );
}

function remaining(pickedAt: string | null) {
  if (!pickedAt) {
    return null;
  }
  const left = new Date(pickedAt).getTime() + leaseMs - Date.now();
  const minutes = Math.max(0, Math.ceil(left / 60000));
  return `${minutes} min left on the 30-minute lease`;
}

export function CasePage() {
  const { taskId } = useParams();
  const { actor } = useActor();
  const [task, setTask] = useState<Task | null>(null);
  const [events, setEvents] = useState<AdjEvent[]>([]);
  const [assessment, setAssessment] = useState<string | null>(null);
  const [memo, setMemo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [decision, setDecision] = useState("APPROVED");
  const [outcome, setOutcome] = useState("CLEARED");
  const [allowed, setAllowed] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    const response = await request(`/review-tasks/${taskId}`, actor);
    if (!response.ok) {
      setError(errorText(response.data));
      setTask(null);
      return;
    }
    const next = response.data as Task;
    setTask(next);
    setError(null);
    const eventResponse = await request(`/ops/events/${encodeURIComponent(next.claim_id)}`, actor);
    if (eventResponse.ok) {
      setEvents(eventResponse.data as AdjEvent[]);
    }
    const fraud = await request(`/fraud/assessments/${encodeURIComponent(next.claim_id)}`, actor);
    if (fraud.ok) {
      const body = fraud.data as { assessment: { narrative?: { headline?: string; summary?: string }; risk_score?: string }; referral_memo?: { body?: unknown } | null };
      const narrative = body.assessment.narrative;
      setAssessment([narrative?.headline, narrative?.summary, body.assessment.risk_score ? `Risk score ${body.assessment.risk_score}` : null].filter(Boolean).join(" "));
      setMemo(body.referral_memo ? JSON.stringify(body.referral_memo.body, null, 2) : null);
    } else {
      setAssessment(null);
      setMemo(null);
    }
  }

  useEffect(() => {
    void load().catch(() => setError("Portal API is not reachable"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId, actor]);

  async function pickUp() {
    setBusy(true);
    setNotice(null);
    const response = await request(`/review-tasks/${taskId}/claim`, actor, { method: "POST" });
    setBusy(false);
    if (!response.ok) {
      setError(errorText(response.data, "Already taken"));
      return;
    }
    setError(null);
    await load();
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!task) {
      return;
    }
    setBusy(true);
    const path = task.task_type === "INVESTIGATION"
      ? `/review-tasks/${task.task_id}/investigation`
      : `/review-tasks/${task.task_id}/decision`;
    const payload = task.task_type === "INVESTIGATION"
      ? { outcome, notes }
      : { decision, allowed_amount: allowed || null, notes };
    const response = await request(path, actor, { method: "POST", body: JSON.stringify(payload) });
    setBusy(false);
    if (!response.ok) {
      setError(errorText(response.data));
      return;
    }
    const body = response.data as { detail?: string };
    setNotice(body.detail ?? "Recorded");
    setError(null);
    await load();
  }

  if (!task && error) {
    return <Alert severity="error">{error}</Alert>;
  }
  if (!task) {
    return <Typography>Loading task…</Typography>;
  }
  const decided = [...events].reverse().find((event) => event.event_type === "DECIDED");
  const decidedStatus = typeof decided?.payload.decision === "string" ? decided.payload.decision : "";
  const claimStatus = task.claim_status || (decidedStatus === "APPROVED" || decidedStatus === "DENIED" ? decidedStatus : "PENDING_REVIEW");
  const history = task.history && task.history.length > 0
    ? task.history
    : decidedStatus === "APPROVED" || decidedStatus === "DENIED"
      ? [
          { from_status: "IN_ADJUDICATION", to_status: "PENDING_REVIEW", reason: null },
          { from_status: "PENDING_REVIEW", to_status: decidedStatus, reason: null },
        ]
      : [];
  const canAct = (task.task_type === "REVIEW" && actor.role === "reviewer") || (task.task_type === "INVESTIGATION" && actor.role === "investigator");
  const mine = canAct && task.assignee === actor.id && task.status === "IN_REVIEW";

  return (
    <section className={styles.page}>
      <div>
        <Typography variant="h4" component="h1">{task.task_type === "INVESTIGATION" ? "Investigation" : "Review"}</Typography>
        <Typography className={styles.id}>{task.claim_id}</Typography>
        <Typography color="text.secondary">
          {task.status} · risk {task.risk_score ?? "—"}
          {task.assignee ? ` · ${task.assignee}` : ""}
          {mine && task.picked_at ? ` · ${remaining(task.picked_at)}` : ""}
        </Typography>
      </div>
      {error && <Alert severity="error">{error}</Alert>}
      {notice && <Alert severity="info">{notice}</Alert>}
      <div className={styles.columns}>
        <div className={styles.summaryColumn}>
          <Typography variant="h6" component="h2">Summary</Typography>
          <SummaryView summary={task.summary ?? {}} events={events} />
        </div>
        <ClaimStages status={claimStatus} history={history} events={events} staff />
      </div>
      {assessment && (
        <>
          <Typography variant="h6" component="h2">Fraud assessment</Typography>
          <Typography>{assessment}</Typography>
        </>
      )}
      {!assessment && <Typography color="text.secondary">No fraud assessment yet.</Typography>}
      {memo && (
        <>
          <Typography variant="h6" component="h2">Referral memo</Typography>
          <pre className={styles.summary}>{memo}</pre>
        </>
      )}
      {!canAct && (
        <Alert severity="info">{task.task_type === "INVESTIGATION" ? "Under investigation" : "Under review"}</Alert>
      )}
      {canAct && task.status === "OPEN" && (
        <Button variant="contained" onClick={() => void pickUp()} disabled={busy}>Pick up</Button>
      )}
      {mine && (
        <form className={styles.form} onSubmit={(event) => void submit(event)}>
          {task.task_type === "INVESTIGATION" ? (
            <TextField select label="Outcome" value={outcome} onChange={(event) => setOutcome(event.target.value)}>
              <MenuItem value="CLEARED">Cleared</MenuItem>
              <MenuItem value="CONFIRMED">Confirmed</MenuItem>
            </TextField>
          ) : (
            <>
              <TextField select label="Decision" value={decision} onChange={(event) => setDecision(event.target.value)}>
                <MenuItem value="APPROVED">Approved</MenuItem>
                <MenuItem value="DENIED">Denied</MenuItem>
              </TextField>
              <TextField label="Allowed amount" value={allowed} onChange={(event) => setAllowed(event.target.value)} />
            </>
          )}
          <TextField label="Notes" value={notes} onChange={(event) => setNotes(event.target.value)} multiline minRows={3} />
          <Button type="submit" variant="contained" disabled={busy}>Submit</Button>
        </form>
      )}
      {task.status === "IN_REVIEW" && !mine && <Alert severity="warning">Only {task.assignee} can decide this task.</Alert>}
      {(actor.role === "reviewer" || actor.role === "investigator") && <FraudAssistant claimId={task.claim_id} />}
    </section>
  );
}
