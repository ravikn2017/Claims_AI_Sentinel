import { useState, type FormEvent } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { errorText, request } from "../../api";
import { EmptyState } from "../../components/EmptyState";
import { useActor } from "../../session";
import styles from "./AuditPage.module.css";

type Row = { occurred_at: string; source: string; summary: string };

export function AuditPage() {
  const { actor } = useActor();
  const [claimId, setClaimId] = useState("");
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load(event: FormEvent) {
    event.preventDefault();
    const response = await request(`/ops/audit/${encodeURIComponent(claimId.trim())}`, actor);
    if (!response.ok) {
      setError(errorText(response.data));
      setRows(null);
      return;
    }
    setError(null);
    setRows(response.data as Row[]);
  }

  return (
    <section className={styles.page}>
      <Typography variant="h4" component="h1">Audit</Typography>
      <form className={styles.lookup} onSubmit={(event) => void load(event)}>
        <TextField label="Claim id" value={claimId} onChange={(event) => setClaimId(event.target.value)} required />
        <Button type="submit" variant="contained">Show trail</Button>
      </form>
      {error && <Alert severity="error">{error}</Alert>}
      {rows && rows.length === 0 && <EmptyState title="No audit rows for that claim" />}
      <ul className={styles.list}>
        {rows?.map((row, index) => (
          <li key={index} className={styles.item}>
            <Typography variant="body2" color="text.secondary">{new Date(row.occurred_at).toLocaleString()} · {row.source}</Typography>
            <Typography>{row.summary}</Typography>
          </li>
        ))}
      </ul>
    </section>
  );
}
