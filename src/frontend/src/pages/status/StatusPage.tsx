import { useEffect, useState, type FormEvent } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useNavigate, useParams } from "react-router-dom";
import { errorText, request } from "../../api";
import { ClaimStages, type AdjEvent, type HistoryRow } from "../../components/ClaimStages";
import { StatusChip } from "../../components/StatusChip";
import { staffRoles, useActor } from "../../session";
import { ChatPanel } from "./ChatPanel";
import { StartAdjudication } from "./StartAdjudication";
import styles from "./StatusPage.module.css";

type Issue = { issue_id: number; issue_code: string; message: string };

type HistoryEntry = HistoryRow & { changed_at?: string | null };

type StatusBody = {
  submission_id: string;
  status: string;
  claim_id: string | null;
  message: string | null;
  respond_by?: string | null;
  issues: Issue[];
  history: HistoryRow[];
};

export function StatusPage() {
  const { submissionId: routeId } = useParams();
  const navigate = useNavigate();
  const { actor } = useActor();
  const [lookup, setLookup] = useState(routeId ?? "");
  const [body, setBody] = useState<StatusBody | null>(null);
  const [events, setEvents] = useState<AdjEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const staff = staffRoles.includes(actor.role);
  const claimant = actor.role === "provider" || actor.role === "member";

  useEffect(() => {
    setLookup(routeId ?? "");
  }, [routeId]);

  useEffect(() => {
    if (!routeId) {
      setBody(null);
      return;
    }
    let cancelled = false;
    async function load() {
      try {
        const response = await request(`/submissions/${encodeURIComponent(routeId!)}/status`, actor);
        if (cancelled) {
          return;
        }
        if (!response.ok) {
          setBody(null);
          setError(errorText(response.data, "Status is not available"));
          return;
        }
        const next = response.data as StatusBody;
        setError(null);
        setBody(next);
        if (staff && next.claim_id) {
          const eventResponse = await request(`/ops/events/${encodeURIComponent(next.claim_id)}`, actor);
          if (!cancelled && eventResponse.ok) {
            setEvents(eventResponse.data as AdjEvent[]);
          }
        } else if (!cancelled) {
          setEvents([]);
        }
      } catch {
        if (!cancelled) {
          setError("Portal API is not reachable");
        }
      }
    }
    void load();
    const timer = window.setInterval(() => void load(), 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [routeId, actor, staff]);

  function open(event: FormEvent) {
    event.preventDefault();
    const id = lookup.trim();
    if (id) {
      navigate(`/claims/${encodeURIComponent(id)}`);
    }
  }

  return (
    <section className={styles.page}>
      <Typography variant="h4" component="h1">Claim status</Typography>
      <form className={styles.lookup} onSubmit={open}>
        <TextField label="Submission id" value={lookup} onChange={(event) => setLookup(event.target.value)} placeholder="SUB-…" />
        <Button type="submit" variant="contained">Look up</Button>
      </form>
      {error && <Alert severity="error">{error}</Alert>}
      {body && (
        <div className={styles.layout}>
          <div className={styles.detail}>
            <div className={styles.heading}>
              <Typography className={styles.id}>{body.submission_id}</Typography>
              <StatusChip status={body.status} />
            </div>
            {body.claim_id && <Typography>Claim <span className={styles.id}>{body.claim_id}</span></Typography>}
            {body.message && <Typography>{body.message}</Typography>}
            {body.respond_by && body.status === "PENDING_INFO" && (
              <Typography color="text.secondary">Reply by {new Date(body.respond_by).toLocaleString()}</Typography>
            )}
            {staff && body.status === "VALIDATED" && body.claim_id && (
              <StartAdjudication claimId={body.claim_id} onStarted={() => undefined} />
            )}
            {body.issues.length > 0 && (
              <div>
                <Typography variant="h6" component="h2">Open issues</Typography>
                <ul>
                  {body.issues.map((issue) => (
                    <li key={issue.issue_id}>{issue.issue_code}: {issue.message}</li>
                  ))}
                </ul>
              </div>
            )}
            {claimant && body.claim_id && (body.status === "PENDING_INFO" || body.history.some((row) => row.to_status === "PENDING_INFO")) && (
              <ChatPanel claimId={body.claim_id} waiting={body.status === "PENDING_INFO"} />
            )}
            {body.history.length > 0 && (
              <div className={styles.history}>
                <Typography variant="h6" component="h2">History</Typography>
                <TableContainer className={styles.table}>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>When</TableCell>
                        <TableCell>From</TableCell>
                        <TableCell>To</TableCell>
                        <TableCell>Reason</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {(body.history as HistoryEntry[]).map((row, index) => (
                        <TableRow key={index} hover>
                          <TableCell className={styles.when}>
                            {row.changed_at ? new Date(row.changed_at).toLocaleString() : "—"}
                          </TableCell>
                          <TableCell>{row.from_status ? <StatusChip status={row.from_status} /> : "—"}</TableCell>
                          <TableCell><StatusChip status={row.to_status} /></TableCell>
                          <TableCell>{row.reason || "—"}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              </div>
            )}
          </div>
          <div className={styles.stages}>
            <ClaimStages status={body.status} history={body.history} events={events} staff={staff} />
          </div>
        </div>
      )}
    </section>
  );
}
