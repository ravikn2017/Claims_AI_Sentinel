import { useState, type FormEvent } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { errorText, request } from "../../api";
import { useActor } from "../../session";
import styles from "./FraudAssistant.module.css";

type Turn = { role: "user" | "assistant"; text: string };

export function FraudAssistant({ claimId }: { claimId: string }) {
  const { actor } = useActor();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function ask(event: FormEvent) {
    event.preventDefault();
    const text = question.trim();
    if (!text) {
      return;
    }
    setBusy(true);
    setQuestion("");
    setTurns((current) => [...current, { role: "user", text }]);
    try {
      const response = await request(`/fraud/assessments/${encodeURIComponent(claimId)}/ask`, actor, {
        method: "POST",
        body: JSON.stringify({ question: text, user_id: actor.id, role: actor.role }),
      });
      if (!response.ok) {
        setError(errorText(response.data));
        return;
      }
      const body = response.data as { answer: string };
      setTurns((current) => [...current, { role: "assistant", text: body.answer }]);
      setError(null);
    } catch {
      setError("Portal API is not reachable");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className={styles.panel}>
      <Typography variant="h6" component="h2">Fraud assistant</Typography>
      <Typography variant="body2" color="text.secondary">
        Explains a stored assessment. It cannot clear or deny the claim.
      </Typography>
      <div className={styles.thread}>
        {turns.map((turn, index) => (
          <p key={index} className={turn.role === "user" ? styles.user : styles.assistant}>{turn.text}</p>
        ))}
      </div>
      {error && <Alert severity="error">{error}</Alert>}
      <form className={styles.composer} onSubmit={(event) => void ask(event)}>
        <TextField label="Ask about this claim" value={question} onChange={(event) => setQuestion(event.target.value)} fullWidth disabled={busy} />
        <Button type="submit" variant="contained" disabled={busy || !question.trim()}>Ask</Button>
      </form>
    </section>
  );
}
