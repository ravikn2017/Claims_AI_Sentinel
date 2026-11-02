import { useEffect, useState, type FormEvent } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import MenuItem from "@mui/material/MenuItem";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { errorText, request } from "../../api";
import { EmptyState } from "../../components/EmptyState";
import { useActor } from "../../session";
import styles from "./KnowledgePage.module.css";

type Chunk = {
  id: number;
  doc_type: string;
  doc_id: string;
  plan_code: string | null;
  section: string | null;
  heading: string | null;
  text: string;
  embedded: boolean;
};

export function KnowledgePage() {
  const { actor } = useActor();
  const [docType, setDocType] = useState("eoc");
  const [docId, setDocId] = useState("SILVER-PPO-01");
  const [planCode, setPlanCode] = useState("SILVER-PPO-01");
  const [cpts, setCpts] = useState("");
  const [body, setBody] = useState("");
  const [planFilter, setPlanFilter] = useState("");
  const [cptFilter, setCptFilter] = useState("");
  const [query, setQuery] = useState("");
  const [chunks, setChunks] = useState<Chunk[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function search() {
    const params = new URLSearchParams();
    if (docType) {
      params.set("doc_type", docType);
    }
    if (planFilter.trim()) {
      params.set("plan_code", planFilter.trim());
    }
    if (cptFilter.trim()) {
      params.set("cpt", cptFilter.trim());
    }
    if (query.trim()) {
      params.set("q", query.trim());
    }
    const response = await request(`/ops/chunks?${params.toString()}`, actor);
    if (!response.ok) {
      setError(errorText(response.data));
      return;
    }
    setError(null);
    setChunks(response.data as Chunk[]);
  }

  useEffect(() => {
    void search().catch(() => setError("Portal API is not reachable"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [actor]);

  async function ingest(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setNotice(null);
    const response = await request("/ops/documents", actor, {
      method: "POST",
      body: JSON.stringify({
        doc_type: docType,
        doc_id: docId.trim(),
        plan_code: planCode.trim() || null,
        cpt_codes: cpts.split(",").map((code) => code.trim()).filter(Boolean),
        text: body,
      }),
    });
    setBusy(false);
    if (!response.ok) {
      setError(errorText(response.data));
      return;
    }
    const result = response.data as { chunks: number };
    setNotice(`Indexed ${result.chunks} sections.`);
    setError(null);
    await search();
  }

  async function reindex() {
    setBusy(true);
    setNotice(null);
    const response = await request("/ops/documents/reindex", actor, { method: "POST" });
    setBusy(false);
    if (!response.ok) {
      setError(errorText(response.data));
      return;
    }
    const result = response.data as { documents: number; chunks: number };
    setNotice(`Indexed ${result.documents} documents, ${result.chunks} sections.`);
    setError(null);
    await search();
  }

  async function onFile(file: File | null) {
    if (!file) {
      return;
    }
    setBody(await file.text());
  }

  return (
    <section className={styles.page}>
      <Typography variant="h4" component="h1">Knowledge</Typography>
      <Typography color="text.secondary">
        Evidence of coverage holds exclusions and exceptions. Medical policies are the clinical guidelines.
      </Typography>
      <form className={styles.form} onSubmit={(event) => void ingest(event)}>
        <TextField select label="Document type" value={docType} onChange={(event) => setDocType(event.target.value)}>
          <MenuItem value="eoc">Evidence of coverage</MenuItem>
          <MenuItem value="medical_policy">Clinical guideline</MenuItem>
        </TextField>
        <TextField label="Document id" value={docId} onChange={(event) => setDocId(event.target.value)} required />
        <TextField label="Plan code" value={planCode} onChange={(event) => setPlanCode(event.target.value)} />
        <TextField label="CPT codes" value={cpts} onChange={(event) => setCpts(event.target.value)} helperText="Comma-separated, for a medical policy" />
        <TextField label="Markdown" value={body} onChange={(event) => setBody(event.target.value)} multiline minRows={8} required />
        <input type="file" accept=".md,text/markdown,text/plain" onChange={(event) => void onFile(event.target.files?.[0] ?? null)} />
        <Button type="submit" variant="contained" disabled={busy}>Index document</Button>
        <Button type="button" variant="outlined" disabled={busy} onClick={() => void reindex()}>
          Index seed documents
        </Button>
      </form>
      {notice && <Alert severity="success">{notice}</Alert>}
      {error && <Alert severity="error">{error}</Alert>}
      <form className={styles.filters} onSubmit={(event) => { event.preventDefault(); void search(); }}>
        <TextField label="Plan" value={planFilter} onChange={(event) => setPlanFilter(event.target.value)} />
        <TextField label="CPT" value={cptFilter} onChange={(event) => setCptFilter(event.target.value)} />
        <TextField label="Text" value={query} onChange={(event) => setQuery(event.target.value)} />
        <Button type="submit" variant="outlined">Search</Button>
      </form>
      {chunks.length === 0 && <EmptyState title="No sections" detail="Index a document, then search by plan or CPT." />}
      <ul className={styles.list}>
        {chunks.map((chunk) => (
          <li key={chunk.id} className={styles.chunk}>
            <Typography variant="subtitle2">
              {chunk.doc_id} · {chunk.section ?? "section"} {chunk.heading ?? ""} · {chunk.embedded ? "Embedded" : "Not embedded"}
            </Typography>
            <Typography variant="body2">{chunk.text}</Typography>
          </li>
        ))}
      </ul>
    </section>
  );
}
