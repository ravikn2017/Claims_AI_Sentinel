import { useEffect, useMemo, useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
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
import { StatusChip } from "../../components/StatusChip";
import { staffRoles, useActor } from "../../session";
import styles from "./ClaimsPage.module.css";

type Row = {
  submission_id: string;
  channel: string;
  submitter_id: string;
  publish_status: string;
  created_at: string;
  claim_id: string | null;
  claim_status: string;
  had_pending_info: boolean;
};

type Filter = "all" | "chat" | "active" | "closed";

const steps = [
  { label: "Submitted" },
  { label: "Validating" },
  { label: "Needs information", chat: true },
  { label: "Queued" },
  { label: "Adjudication" },
  { label: "Review" },
  { label: "Decision" },
];

function activeIndex(status: string) {
  switch (status) {
    case "PROCESSING":
    case "FAILED_PROCESSING":
      return 1;
    case "PENDING_INFO":
      return 2;
    case "VALIDATED":
      return 3;
    case "IN_ADJUDICATION":
      return 4;
    case "PENDING_REVIEW":
      return 5;
    case "APPROVED":
    case "DENIED":
    case "REJECTED":
      return 6;
    default:
      return 0;
  }
}

function stepState(index: number, status: string, hadPendingInfo: boolean) {
  const active = activeIndex(status);
  if (status === "FAILED_PROCESSING" && index === 1) {
    return "error";
  }
  if ((status === "REJECTED" || status === "DENIED") && index === 6) {
    return "error";
  }
  if (index === 2 && active > 2 && !hadPendingInfo) {
    return "skipped";
  }
  if (index < active) {
    return "done";
  }
  if (index === active) {
    return "active";
  }
  return "waiting";
}

function bucket(status: string): Filter {
  if (status === "PENDING_INFO") {
    return "chat";
  }
  if (status === "APPROVED" || status === "DENIED" || status === "REJECTED" || status === "FAILED_PROCESSING") {
    return "closed";
  }
  return "active";
}

function chatLabel(row: Row) {
  if (row.claim_status === "PENDING_INFO") {
    return "Chat open";
  }
  if (row.had_pending_info) {
    return "Chat kept";
  }
  return "No chat";
}

function StageRail({ status, hadPendingInfo }: { status: string; hadPendingInfo: boolean }) {
  const active = activeIndex(status);
  return (
    <div className={styles.rail}>
      <div className={styles.track} aria-hidden="true">
        {steps.map((step, index) => {
          const state = stepState(index, status, hadPendingInfo);
          const marker = step.chat ? styles.chatMark : styles.mark;
          return (
            <span key={step.label} className={styles.station} title={`${step.label}: ${state}`}>
              {index > 0 && (
                <span className={`${styles.bar} ${["done", "active", "error"].includes(state) ? styles.done : ""}`} />
              )}
              <span className={`${marker} ${styles[state]}`} />
            </span>
          );
        })}
      </div>
      <Typography variant="caption" component="p" className={styles.caption}>
        {status === "PENDING_INFO" ? "Update the claim here" : steps[active].label}
      </Typography>
    </div>
  );
}

export function ClaimsPage() {
  const { actor } = useActor();
  const staff = staffRoles.includes(actor.role);
  const [rows, setRows] = useState<Row[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(8);

  useEffect(() => {
    let cancelled = false;
    void request(`/submissions?submitter_id=${encodeURIComponent(actor.id)}`, actor)
      .then((response) => {
        if (cancelled) {
          return;
        }
        if (!response.ok) {
          setError(errorText(response.data));
          return;
        }
        setError(null);
        setRows(response.data as Row[]);
      })
      .catch(() => {
        if (!cancelled) {
          setError("Portal API is not reachable");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [actor]);

  const counts = useMemo(() => {
    const next = { all: rows.length, chat: 0, active: 0, closed: 0 };
    for (const row of rows) {
      next[bucket(row.claim_status)] += 1;
    }
    return next;
  }, [rows]);

  const visible = rows.filter((row) => filter === "all" || bucket(row.claim_status) === filter);
  const pageRows = visible.slice(page * rowsPerPage, page * rowsPerPage + rowsPerPage);

  function chooseFilter(value: Filter) {
    setFilter(value);
    setPage(0);
  }

  return (
    <section className={styles.page}>
      <div>
        <Typography variant="h4" component="h1">Claims</Typography>
        <Typography color="text.secondary">
          {staff
            ? "Every submission. Open one, then use Back to return to this list."
            : `Submissions for ${actor.id}. The chat opens on the Needs information step and stays on the claim after you answer.`}
        </Typography>
      </div>
      {error && <Alert severity="error">{error}</Alert>}
      {!error && rows.length === 0 && <EmptyState title="No submissions yet" detail="Submit a claim and it will show up here." />}
      {rows.length > 0 && (
        <>
          <ToggleButtonGroup
            exclusive
            size="small"
            value={filter}
            onChange={(_event, value: Filter | null) => value && chooseFilter(value)}
          >
            <ToggleButton value="all">All {counts.all}</ToggleButton>
            <ToggleButton value="chat">Needs information {counts.chat}</ToggleButton>
            <ToggleButton value="active">In progress {counts.active}</ToggleButton>
            <ToggleButton value="closed">Closed {counts.closed}</ToggleButton>
          </ToggleButtonGroup>
          <div className={styles.legend}>
            <span className={`${styles.chatMark} ${styles.active}`} />
            <Typography variant="caption" color="text.secondary">Diamond marks the chat step</Typography>
          </div>
          {visible.length === 0 ? (
            <EmptyState title="Nothing in this view" detail="Choose another filter to see the rest of the claims." />
          ) : (
            <TableContainer className={styles.table}>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Submission</TableCell>
                    <TableCell>Status</TableCell>
                    <TableCell>Progress</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {pageRows.map((row) => (
                    <TableRow key={row.submission_id} hover className={row.claim_status === "PENDING_INFO" ? styles.chatRow : undefined}>
                      <TableCell>
                        <div className={styles.identity}>
                          <div>
                            <Typography className={styles.id} component="div">{row.submission_id}</Typography>
                            <Typography variant="caption" color="text.secondary">
                              {new Date(row.created_at).toLocaleString()}
                              {staff ? ` · ${row.submitter_id}` : ""} · {chatLabel(row)}
                            </Typography>
                          </div>
                          <Button
                            component={RouterLink}
                            to={`/claims/${encodeURIComponent(row.submission_id)}`}
                            variant={row.claim_status === "PENDING_INFO" ? "contained" : "outlined"}
                            size="small"
                          >
                            {row.claim_status === "PENDING_INFO" ? "Update claim" : row.had_pending_info ? "Open chat" : "Open"}
                          </Button>
                        </div>
                      </TableCell>
                      <TableCell><StatusChip status={row.claim_status} /></TableCell>
                      <TableCell><StageRail status={row.claim_status} hadPendingInfo={row.had_pending_info} /></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <TablePagination
                component="div"
                count={visible.length}
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
        </>
      )}
    </section>
  );
}
