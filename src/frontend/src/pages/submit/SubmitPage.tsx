import { useState, type FormEvent } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useNavigate } from "react-router-dom";
import { errorText, request } from "../../api";
import { useActor } from "../../session";
import styles from "./SubmitPage.module.css";

type Line = {
  line_no: number;
  cpt_code: string;
  units: number;
  billed_amount: string;
  service_date: string;
  diagnosis_pointers: string;
  prior_auth_number: string;
};

type FormState = {
  member_id: string;
  first_name: string;
  last_name: string;
  dob: string;
  group_number: string;
  billing_npi: string;
  billing_name: string;
  rendering_npi: string;
  place_of_service: string;
  service_from: string;
  service_to: string;
  diagnosis_codes: string;
  total_billed: string;
  lines: Line[];
};

const cleanClaim: FormState = {
  member_id: "MBR-100231",
  first_name: "Jane",
  last_name: "Doe",
  dob: "1984-03-12",
  group_number: "GRP-7781",
  billing_npi: "1234567893",
  billing_name: "Lakeside Family Clinic",
  rendering_npi: "1987654328",
  place_of_service: "11",
  service_from: "2026-10-20",
  service_to: "2026-10-20",
  diagnosis_codes: "E11.9, I10",
  total_billed: "230.00",
  lines: [
    { line_no: 1, cpt_code: "99214", units: 1, billed_amount: "185.00", service_date: "2026-10-20", diagnosis_pointers: "1, 2", prior_auth_number: "" },
    { line_no: 2, cpt_code: "83036", units: 1, billed_amount: "45.00", service_date: "2026-10-20", diagnosis_pointers: "1", prior_auth_number: "" },
  ],
};

const pendingClaim: FormState = {
  ...cleanClaim,
  lines: [cleanClaim.lines[0], { ...cleanClaim.lines[1], cpt_code: "8303" }],
};

const rejectedClaim: FormState = {
  ...cleanClaim,
  service_from: "2020-01-15",
  service_to: "2020-01-15",
  lines: cleanClaim.lines.map((line) => ({ ...line, service_date: "2020-01-15" })),
};

function pointers(value: string) {
  return value
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => Number(part));
}

export function SubmitPage() {
  const { actor } = useActor();
  const navigate = useNavigate();
  const [form, setForm] = useState(cleanClaim);
  const [submissionId, setSubmissionId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const lineSum = form.lines.reduce((sum, line) => sum + Number(line.billed_amount || 0), 0);

  function updateLine(index: number, patch: Partial<Line>) {
    setForm({
      ...form,
      lines: form.lines.map((line, lineIndex) => (lineIndex === index ? { ...line, ...patch } : line)),
    });
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const payload = {
      submission_id: submissionId.trim() || null,
      submitter_type: actor.role === "member" ? "member" : "provider",
      submitter_id: actor.id,
      claim: {
        claim_type: "professional",
        member: {
          member_id: form.member_id,
          first_name: form.first_name,
          last_name: form.last_name,
          dob: form.dob,
        },
        group_number: form.group_number,
        billing_provider: { npi: form.billing_npi, name: form.billing_name },
        rendering_npi: form.rendering_npi,
        place_of_service: form.place_of_service,
        service_from: form.service_from,
        service_to: form.service_to,
        diagnosis_codes: form.diagnosis_codes.split(",").map((code) => code.trim()).filter(Boolean),
        lines: form.lines.map((line) => ({
          line_no: line.line_no,
          cpt_code: line.cpt_code,
          modifiers: [],
          units: Number(line.units),
          billed_amount: line.billed_amount,
          service_date: line.service_date,
          diagnosis_pointers: pointers(line.diagnosis_pointers),
          prior_auth_number: line.prior_auth_number.trim() || null,
        })),
        total_billed: form.total_billed,
      },
    };
    try {
      let response: { ok: boolean; data: unknown };
      if (file) {
        const data = new FormData();
        data.set("payload", JSON.stringify(payload));
        data.set("file", file);
        data.set("doc_type", "medical_record");
        response = await request("/submissions", actor, { method: "POST", body: data });
      } else {
        response = await request("/submissions", actor, { method: "POST", body: JSON.stringify(payload) });
      }
      if (!response.ok) {
        setError(errorText(response.data));
        return;
      }
      const id = (response.data as { submission_id: string }).submission_id;
      navigate(`/claims/${encodeURIComponent(id)}`);
    } catch {
      setError("Portal API is not reachable");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className={styles.form} onSubmit={(event) => void submit(event)}>
      <div>
        <Typography variant="h4" component="h1">Submit a claim</Typography>
        <Typography color="text.secondary">Shape checks only. The payer service decides whether the claim is valid.</Typography>
      </div>
      <div className={styles.presets}>
        <Button type="button" variant="outlined" onClick={() => setForm(cleanClaim)}>Clean example</Button>
        <Button type="button" variant="outlined" onClick={() => setForm(pendingClaim)}>Fixable example</Button>
        <Button type="button" variant="outlined" onClick={() => setForm(rejectedClaim)}>Rejected example</Button>
      </div>
      <TextField label="Submission id" value={submissionId} onChange={(event) => setSubmissionId(event.target.value)} helperText="Leave blank to generate one" />
      <div className={styles.grid}>
        <TextField label="Member id" value={form.member_id} onChange={(event) => setForm({ ...form, member_id: event.target.value })} required />
        <TextField label="First name" value={form.first_name} onChange={(event) => setForm({ ...form, first_name: event.target.value })} required />
        <TextField label="Last name" value={form.last_name} onChange={(event) => setForm({ ...form, last_name: event.target.value })} required />
        <TextField label="Date of birth" value={form.dob} onChange={(event) => setForm({ ...form, dob: event.target.value })} required />
        <TextField label="Group number" value={form.group_number} onChange={(event) => setForm({ ...form, group_number: event.target.value })} />
        <TextField label="Billing NPI" value={form.billing_npi} onChange={(event) => setForm({ ...form, billing_npi: event.target.value })} required />
        <TextField label="Billing name" value={form.billing_name} onChange={(event) => setForm({ ...form, billing_name: event.target.value })} required />
        <TextField label="Rendering NPI" value={form.rendering_npi} onChange={(event) => setForm({ ...form, rendering_npi: event.target.value })} required />
        <TextField label="Place of service" value={form.place_of_service} onChange={(event) => setForm({ ...form, place_of_service: event.target.value })} required />
        <TextField label="Service from" value={form.service_from} onChange={(event) => setForm({ ...form, service_from: event.target.value })} required />
        <TextField label="Service to" value={form.service_to} onChange={(event) => setForm({ ...form, service_to: event.target.value })} required />
        <TextField label="Diagnosis codes" value={form.diagnosis_codes} onChange={(event) => setForm({ ...form, diagnosis_codes: event.target.value })} required />
      </div>
      {form.lines.map((line, index) => (
        <fieldset key={line.line_no} className={styles.line}>
          <legend>Line {line.line_no}</legend>
          <div className={styles.grid}>
            <TextField label="CPT" value={line.cpt_code} onChange={(event) => updateLine(index, { cpt_code: event.target.value })} required />
            <TextField label="Units" type="number" value={line.units} onChange={(event) => updateLine(index, { units: Number(event.target.value) })} required />
            <TextField label="Amount" value={line.billed_amount} onChange={(event) => updateLine(index, { billed_amount: event.target.value })} required />
            <TextField label="Service date" value={line.service_date} onChange={(event) => updateLine(index, { service_date: event.target.value })} required />
            <TextField label="Pointers" value={line.diagnosis_pointers} onChange={(event) => updateLine(index, { diagnosis_pointers: event.target.value })} required />
            <TextField label="Prior auth" value={line.prior_auth_number} onChange={(event) => updateLine(index, { prior_auth_number: event.target.value })} />
          </div>
        </fieldset>
      ))}
      <TextField
        label="Total billed"
        value={form.total_billed}
        onChange={(event) => setForm({ ...form, total_billed: event.target.value })}
        helperText={`Line sum ${lineSum.toFixed(2)}`}
        required
      />
      <label className={styles.file}>
        PDF (optional)
        <input type="file" accept="application/pdf,.pdf" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
      </label>
      {error && <Alert severity="error">{error}</Alert>}
      <Button type="submit" variant="contained" disabled={busy}>{busy ? "Submitting…" : "Submit"}</Button>
    </form>
  );
}
