import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import MenuItem from "@mui/material/MenuItem";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { errorText, request } from "../../api";
import { EmptyState } from "../../components/EmptyState";
import { useActor } from "../../session";
import styles from "./ReferencePage.module.css";

const kinds = [
  { id: "members", label: "Members" },
  { id: "policies", label: "Policies" },
  { id: "providers", label: "Providers" },
  { id: "benefits", label: "Plan benefits" },
  { id: "cpt", label: "CPT" },
  { id: "icd10", label: "ICD-10" },
];

export function ReferencePage() {
  const { actor } = useActor();
  const [kind, setKind] = useState("members");
  const [query, setQuery] = useState("");
  const [planCode, setPlanCode] = useState("");
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams();
    if (query.trim()) {
      params.set("q", query.trim());
    }
    if (planCode.trim()) {
      params.set("plan_code", planCode.trim());
    }
    let cancelled = false;
    void request(`/ops/reference/${kind}?${params.toString()}`, actor)
      .then((response) => {
        if (cancelled) {
          return;
        }
        if (!response.ok) {
          setError(errorText(response.data));
          return;
        }
        setError(null);
        setRows(response.data as Record<string, unknown>[]);
      })
      .catch(() => {
        if (!cancelled) {
          setError("Portal API is not reachable");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [actor, kind, query, planCode]);

  const columns = rows[0] ? Object.keys(rows[0]) : [];

  return (
    <section className={styles.page}>
      <Typography variant="h4" component="h1">Reference data</Typography>
      <div className={styles.filters}>
        <TextField select label="Table" value={kind} onChange={(event) => setKind(event.target.value)}>
          {kinds.map((item) => (
            <MenuItem key={item.id} value={item.id}>{item.label}</MenuItem>
          ))}
        </TextField>
        <TextField label="Search" value={query} onChange={(event) => setQuery(event.target.value)} />
        <TextField label="Plan code" value={planCode} onChange={(event) => setPlanCode(event.target.value)} />
      </div>
      {error && <Alert severity="error">{error}</Alert>}
      {rows.length === 0 && !error && <EmptyState title="No rows" />}
      {rows.length > 0 && (
        <div className={styles.table}>
          <Table size="small">
            <TableHead>
              <TableRow>
                {columns.map((column) => <TableCell key={column}>{column}</TableCell>)}
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((row, index) => (
                <TableRow key={index}>
                  {columns.map((column) => <TableCell key={column}>{String(row[column] ?? "")}</TableCell>)}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </section>
  );
}
