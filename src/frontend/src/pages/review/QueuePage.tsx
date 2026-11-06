import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TablePagination from "@mui/material/TablePagination";
import TableRow from "@mui/material/TableRow";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Typography from "@mui/material/Typography";
import { Link as RouterLink } from "react-router-dom";
import { errorText, request } from "../../api";
import { EmptyState } from "../../components/EmptyState";
import { useActor } from "../../session";
import styles from "./QueuePage.module.css";

type AgentResult = {
  verdict?: unknown;
  reasons?: unknown;
};

type Task = {
  task_id: number;
  claim_id: string;
  summary: Record<string, unknown> | null;
  risk_score: string | null;
  task_type: string;
  created_at: string;
  member_id?: string | null;
  member_name?: string | null;
  provider_name?: string | null;
  total_billed?: string | null;
  service_from?: string | null;
  service_to?: string | null;
};

const words: Record<string, string> = {
  COVERED: "Covered",
  NOT_COVERED: "Not covered",
  NEEDS_INFO: "Needs information",
  CLEAR: "Clear",
  FLAGGED: "Flagged",
  NECESSARY: "Necessary",
  NOT_NECESSARY: "Not necessary",
  approve: "Approve",
  deny: "Deny",
  review: "Needs a person",
};

function phrase(value: unknown) {
  if (value == null || value === "") {
    return "";
  }
  const key = String(value);
  return words[key] ?? key.replaceAll("_", " ");
}

function resultOf(summary: Record<string, unknown> | null, key: string): AgentResult | null {
  const value = summary?.[key];
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as AgentResult;
}

function firstReason(summary: Record<string, unknown> | null) {
  const listed = summary?.reasons;
  if (Array.isArray(listed) && listed.length > 0) {
    return phrase(listed[0]);
  }
  for (const key of ["fraud_result", "policy_result", "med_result"]) {
    const reasons = resultOf(summary, key)?.reasons;
    if (Array.isArray(reasons) && reasons.length > 0) {
      return phrase(reasons[0]);
    }
  }
  return "";
}

function when(value: string | null | undefined) {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

function day(value: string | null | undefined) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleDateString();
}

function money(value: string | null | undefined) {
  if (value == null || value === "") {
    return "—";
  }
  const amount = Number(value);
  if (!Number.isFinite(amount)) {
    return value;
  }
  return amount.toLocaleString(undefined, { style: "currency", currency: "USD" });
}

function chipColor(value: unknown): "success" | "warning" | "error" | "default" {
  const key = String(value ?? "");
  if (["COVERED", "CLEAR", "NECESSARY", "approve"].includes(key)) {
    return "success";
  }
  if (["NEEDS_INFO", "review"].includes(key)) {
    return "warning";
  }
  if (["NOT_COVERED", "FLAGGED", "NOT_NECESSARY", "deny"].includes(key)) {
    return "error";
  }
  return "default";
}

function Verdict({ value }: { value: unknown }) {
  const label = phrase(value);
  if (!label) {
    return <span className={styles.muted}>—</span>;
  }
  return <Chip size="small" variant="outlined" label={label} color={chipColor(value)} />;
}

export function QueuePage() {
  const { actor } = useActor();
  const [taskType, setTaskType] = useState(actor.role === "investigator" ? "INVESTIGATION" : "REVIEW");
  const [tasks, setTasks] = useState<Task[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(8);

  useEffect(() => {
    let cancelled = false;
    void request(`/review-tasks?status=OPEN&task_type=${taskType}`, actor)
      .then((response) => {
        if (cancelled) {
          return;
        }
        if (!response.ok) {
          setError(errorText(response.data));
          return;
        }
        setError(null);
        setTasks(response.data as Task[]);
        setPage(0);
      })
      .catch(() => {
        if (!cancelled) {
          setError("Portal API is not reachable");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [actor, taskType]);

  const pageRows = tasks.slice(page * rowsPerPage, page * rowsPerPage + rowsPerPage);
  const lead = taskType === "INVESTIGATION"
    ? "Claims a person needs to confirm or clear before adjudication continues."
    : "Claims a person needs to approve or deny.";

  return (
    <section className={styles.page}>
      <div>
        <Typography variant="h4" component="h1">Work queue</Typography>
        <Typography color="text.secondary">{lead}</Typography>
      </div>
      <ToggleButtonGroup exclusive value={taskType} onChange={(_event, value: string | null) => value && setTaskType(value)}>
        <ToggleButton value="REVIEW">Review</ToggleButton>
        <ToggleButton value="INVESTIGATION">Investigation</ToggleButton>
      </ToggleButtonGroup>
      {error && <Alert severity="error">{error}</Alert>}
      {!error && tasks.length === 0 && <EmptyState title="No open tasks" detail="Tasks appear here when the adjudicator pauses for a person. None are queued yet." />}
      {tasks.length > 0 && (
        <TableContainer className={styles.table}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Claim</TableCell>
                <TableCell>Member</TableCell>
                <TableCell>Provider</TableCell>
                <TableCell>Service</TableCell>
                <TableCell>Billed</TableCell>
                <TableCell>Policy</TableCell>
                <TableCell>Fraud</TableCell>
                <TableCell>Medical</TableCell>
                <TableCell>Recommendation</TableCell>
                <TableCell>Risk</TableCell>
                <TableCell />
              </TableRow>
            </TableHead>
            <TableBody>
              {pageRows.map((task) => {
                const summary = task.summary;
                const reason = firstReason(summary);
                const service = [day(task.service_from), day(task.service_to)].filter(Boolean).join(" – ");
                const member = task.member_name || task.member_id || "—";
                return (
                  <TableRow key={task.task_id} hover>
                    <TableCell>
                      <Typography className={styles.id} component="div">{task.claim_id}</Typography>
                      <Typography variant="caption" color="text.secondary">Waiting since {when(task.created_at)}</Typography>
                      {reason && <Typography className={styles.why} variant="caption" color="text.secondary">{reason}</Typography>}
                    </TableCell>
                    <TableCell>
                      <Typography component="div">{member}</Typography>
                      {task.member_name && task.member_id && (
                        <Typography variant="caption" color="text.secondary">{task.member_id}</Typography>
                      )}
                    </TableCell>
                    <TableCell>{task.provider_name || "—"}</TableCell>
                    <TableCell className={styles.nowrap}>{service || "—"}</TableCell>
                    <TableCell className={styles.nowrap}>{money(task.total_billed)}</TableCell>
                    <TableCell><Verdict value={resultOf(summary, "policy_result")?.verdict} /></TableCell>
                    <TableCell><Verdict value={resultOf(summary, "fraud_result")?.verdict} /></TableCell>
                    <TableCell><Verdict value={resultOf(summary, "med_result")?.verdict} /></TableCell>
                    <TableCell><Verdict value={summary?.recommendation} /></TableCell>
                    <TableCell className={styles.nowrap}>{task.risk_score ?? "—"}</TableCell>
                    <TableCell>
                      <Button component={RouterLink} to={`/review/${task.task_id}`} variant="contained" size="small">Open</Button>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
          <TablePagination
            component="div"
            count={tasks.length}
            page={page}
            onPageChange={(_event, next) => setPage(next)}
            rowsPerPage={rowsPerPage}
            onRowsPerPageChange={(event) => {
              setRowsPerPage(Number(event.target.value));
              setPage(0);
            }}
            rowsPerPageOptions={[8, 15, 30]}
          />
        </TableContainer>
      )}
    </section>
  );
}
