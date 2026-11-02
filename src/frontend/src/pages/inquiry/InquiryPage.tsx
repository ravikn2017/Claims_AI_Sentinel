import { useEffect, useState, type FormEvent } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { Navigate } from "react-router-dom";
import { errorText, request } from "../../api";
import { useActor, useSession } from "../../session";
import styles from "./InquiryPage.module.css";

type ChatMessage = {
  role: "assistant" | "user";
  text: string;
};

export function InquiryPage() {
  const { user } = useSession();
  const { actor } = useActor();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    const response = await request("/inquiry", actor);
    if (!response.ok) {
      setError(errorText(response.data));
      return;
    }
    const body = response.data as { messages: ChatMessage[] };
    setMessages(body.messages);
    setError(null);
  }

  useEffect(() => {
    if (user?.role !== "member") {
      return;
    }
    void load().catch(() => setError("Portal API is not reachable"));
    // Reload when the signed-in member changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [actor]);

  if (!user || user.role !== "member") {
    return <Navigate to="/" replace />;
  }

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
      const response = await request("/inquiry", actor, {
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

  return (
    <section className={styles.page}>
      <div>
        <Typography variant="h4" component="h1">Ask</Typography>
        <Typography color="text.secondary">
          Ask about your claims, your plan, or a provider. This chat cannot change a claim.
        </Typography>
      </div>
      <div className={styles.thread}>
        {messages.length === 0 && (
          <Typography color="text.secondary">
            For example: what claims do I have, what does my plan cover, or is Lakeside Family Clinic in network?
          </Typography>
        )}
        {messages.map((message, index) => (
          <p key={`${message.role}-${index}`} className={message.role === "user" ? styles.user : styles.assistant}>
            {message.text}
          </p>
        ))}
      </div>
      {error && <Alert severity="error">{error}</Alert>}
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
    </section>
  );
}
