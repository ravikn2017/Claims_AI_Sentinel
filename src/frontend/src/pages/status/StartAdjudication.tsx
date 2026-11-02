import { useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import { errorText, request } from "../../api";
import { useActor } from "../../session";
import styles from "./StartAdjudication.module.css";

export function StartAdjudication({ claimId, onStarted }: { claimId: string; onStarted: () => void }) {
  const { actor } = useActor();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function start() {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const response = await request(`/adjudication/${encodeURIComponent(claimId)}/start`, actor, { method: "POST" });
      if (!response.ok) {
        setError(errorText(response.data));
        return;
      }
      const body = response.data as { adjudication_attempt?: number };
      setNote(`Queued attempt ${body.adjudication_attempt ?? ""}. The claim stays validated until the adjudicator picks it up.`);
      onStarted();
    } catch {
      setError("Portal API is not reachable");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={styles.box}>
      <Button variant="contained" onClick={() => void start()} disabled={busy}>
        {busy ? "Starting…" : "Start adjudication"}
      </Button>
      {note && <Alert severity="success">{note}</Alert>}
      {error && <Alert severity="error">{error}</Alert>}
    </div>
  );
}
