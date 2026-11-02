import { useEffect, useMemo, useState } from "react";
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
import TextField from "@mui/material/TextField";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Typography from "@mui/material/Typography";
import { errorText, request } from "../../api";
import { EmptyState } from "../../components/EmptyState";
import { useActor } from "../../session";
import styles from "./FailuresPage.module.css";

type Failure = {
  message_id: string;
  submission_id: string | null;
  error_class: string;
  error: string;
  attempts: number;
  dead_lettered_at?: string | null;
  resolved_at: string | null;
};

type Filter = "open" | "resolved" | "all";

export function FailuresPage() {
  const { actor } = useActor();
  const [rows, setRows] = useState<Failure[]>([]);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("open");
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(8);
  const [busyId, setBusyId] = useState<string | null>(null);

  async function load() {
    const response = await request("/ops/intake-errors", actor);
    if (!response.ok) {
      setError(errorText(response.data));
      return;
    }
    setError(null);
    setRows(response.data as Failure[]);
  }

  useEffect(() => {
    void load().catch(() => setError("Portal API is not reachable"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [actor]);

  const counts = useMemo(() => {
    const next = { open: 0, resolved: 0, all: rows.length };
    for (const row of rows) {
      next[row.resolved_at ? "resolved" : "open"] += 1;
    }
    return next;
  }, [rows]);

  const visible = rows.filter((row) => {
    if (filter === "open") {
      return !row.resolved_at;
    }
    if (filter === "resolved") {
      return Boolean(row.resolved_at);
    }
    return true;
  });
  const pageRows = visible.slice(page * rowsPerPage, page * rowsPerPage + rowsPerPage);

  function chooseFilter(value: Filter) {
    setFilter(value);
    setPage(0);
  }

  async function act(messageId: string, action: "replay" | "discard") {
    if (!reason.trim()) {
      setError("A reason is required");
      return;
    }
    setBusyId(messageId);
    const response = await request(`/ops/intake-errors/${encodeURIComponent(messageId)}/${action}`, actor, {
      method: "POST",
      body: JSON.stringify({ reason: reason.trim() }),
    });
    setBusyId(null);
    if (!response.ok) {
      setError(errorText(response.data));
      return;
    }
    setNotice(action === "replay" ? "Replayed" : "Discarded");
    setError(null);
    await load();
  }

  return (
    <section className={styles.page}>
      <div>
        <Typography variant="h4" component="h1">Intake failures</Typography>
        <Typography color="text.secondary">
          Messages that did not become a claim. Enter a reason, then replay or discard a row.
        </Typography>
      </div>
      <TextField
        label="Reason"
        value={reason}
        onChange={(event) => setReason(event.target.value)}
        helperText="Required for replay and discard"
        fullWidth
      />
      {notice && <Alert severity="success">{notice}</Alert>}
      {error && <Alert severity="error">{error}</Alert>}
      {!error && rows.length === 0 && <EmptyState title="No intake failures" />}
      {rows.length > 0 && (
        <>
          <ToggleButtonGroup
            exclusive
            size="small"
            value={filter}
            onChange={(_event, value: Filter | null) => value && chooseFilter(value)}
          >
            <ToggleButton value="open">Open {counts.open}</ToggleButton>
            <ToggleButton value="resolved">Resolved {counts.resolved}</ToggleButton>
            <ToggleButton value="all">All {counts.all}</ToggleButton>
          </ToggleButtonGroup>
          {visible.length === 0 ? (
            <EmptyState title="Nothing in this view" detail="Choose another filter to see the rest of the failures." />
          ) : (
            <TableContainer className={styles.table}>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Message</TableCell>
                    <TableCell>Error</TableCell>
                    <TableCell>Submission</TableCell>
                    <TableCell>Attempts</TableCell>
                    <TableCell>Status</TableCell>
                    <TableCell />
                  </TableRow>
                </TableHead>
                <TableBody>
                  {pageRows.map((row) => (
                    <TableRow key={row.message_id} hover>
                      <TableCell>
                        <Typography className={styles.id} component="div">{row.message_id}</Typography>
                        {row.dead_lettered_at && (
                          <Typography variant="caption" color="text.secondary">
                            {new Date(row.dead_lettered_at).toLocaleString()}
                          </Typography>
                        )}
                      </TableCell>
                      <TableCell>
                        <Typography variant="body2">{row.error_class}: {row.error}</Typography>
                      </TableCell>
                      <TableCell>
                        <Typography className={styles.id} component="div">
                          {row.submission_id ?? "—"}
                        </Typography>
                      </TableCell>
                      <TableCell>{row.attempts}</TableCell>
                      <TableCell>
                        <Chip size="small" label={row.resolved_at ? "Resolved" : "Open"} color={row.resolved_at ? "success" : "warning"} />
                      </TableCell>
                      <TableCell>
                        {!row.resolved_at && (
                          <div className={styles.actions}>
                            <Button size="small" variant="contained" disabled={busyId === row.message_id} onClick={() => void act(row.message_id, "replay")}>
                              Replay
                            </Button>
                            <Button size="small" variant="outlined" disabled={busyId === row.message_id} onClick={() => void act(row.message_id, "discard")}>
                              Discard
                            </Button>
                          </div>
                        )}
                      </TableCell>
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
