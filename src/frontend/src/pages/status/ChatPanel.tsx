import { useEffect, useState, type FormEvent } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { errorText, request } from "../../api";
import { useActor } from "../../session";
import styles from "./ChatPanel.module.css";

type ChatMessage = {
  role: "assistant" | "user";
  text: string;
};

export function ChatPanel({ claimId, waiting = true }: { claimId: string; waiting?: boolean }) {
  const { actor } = useActor();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    const response = await request(`/chat/${encodeURIComponent(claimId)}`, actor);
    if (!response.ok) {
      setError(errorText(response.data));
      return;
    }
    const body = response.data as { messages: ChatMessage[] };
    setMessages(body.messages);
    setError(null);
  }

  useEffect(() => {
    void load().catch(() => setError("Portal API is not reachable"));
    // Reload when the claim id or the signed-in actor changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [claimId, actor]);

  async function send(event: FormEvent) {
    event.preventDefault();
    const text = draft.trim();
    if (!text) {
      return;
    }
    setBusy(true);
    setError(null);
    setMessages((current) => [...current, { role: "user", text }]);
    setDraft("");
    try {
      const response = await request(`/chat/${encodeURIComponent(claimId)}`, actor, {
        method: "POST",
        body: JSON.stringify({ text }),
      });
      if (!response.ok) {
        setMessages((current) => [...current, { role: "assistant", text: errorText(response.data) }]);
        return;
      }
      await load();
    } catch {
      setError("Portal API is not reachable");
    } finally {
      setBusy(false);
    }
  }

  async function upload() {
    if (!file) {
      return;
    }
    setBusy(true);
    const data = new FormData();
    data.set("file", file);
    data.set("doc_type", "medical_record");
    try {
      const response = await request(`/chat/${encodeURIComponent(claimId)}/documents`, actor, { method: "POST", body: data });
      if (!response.ok) {
        setError(errorText(response.data));
        return;
      }
      setFile(null);
      await load();
    } catch {
      setError("Portal API is not reachable");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className={styles.panel}>
      <Typography variant="h6" component="h2">Missing information</Typography>
      <Typography variant="body2" color="text.secondary">
        {waiting
          ? "The payer service checks each answer. This chat does not change the claim on its own."
          : "The answers are saved. This conversation stays on the claim."}
      </Typography>
      <div className={styles.thread}>
        {messages.length === 0 && <Typography color="text.secondary">No open questions.</Typography>}
        {messages.map((message, index) => (
          <p key={`${message.role}-${index}`} className={message.role === "user" ? styles.user : styles.assistant}>
            {message.text}
          </p>
        ))}
      </div>
      {error && <Alert severity="error">{error}</Alert>}
      {waiting && (
        <>
          <form className={styles.composer} onSubmit={(event) => void send(event)}>
            <TextField
              label="Message"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              disabled={busy}
              fullWidth
            />
            <Button type="submit" variant="contained" disabled={busy || !draft.trim()}>Send</Button>
          </form>
          <div className={styles.composer}>
            <input type="file" accept="application/pdf,.pdf" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
            <Button type="button" variant="outlined" disabled={!file || busy} onClick={() => void upload()}>Attach PDF</Button>
          </div>
        </>
      )}
    </section>
  );
}
