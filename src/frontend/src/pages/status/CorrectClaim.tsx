import { useEffect, useState, type FormEvent } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { errorText, request } from "../../api";
import { useActor } from "../../session";
import styles from "./CorrectClaim.module.css";

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
  lines: Line[];
};

type Draft = {
  member?: { member_id?: string; first_name?: string; last_name?: string; dob?: string };
  group_number?: string | null;
  billing_provider?: { npi?: string; name?: string };
  rendering_npi?: string | null;
  place_of_service?: string | null;
  service_from?: string | null;
  service_to?: string | null;
  diagnosis_codes?: string[];
  total_billed?: string | number | null;
  lines?: Array<{
    line_no: number;
    cpt_code?: string;
    units?: number;
    billed_amount?: string | number;
    service_date?: string;
    diagnosis_pointers?: number[];
    prior_auth_number?: string | null;
  }>;
};

function textOf(value: unknown) {
  return value == null ? "" : String(value);
}

function fromDraft(draft: Draft): FormState {
  return {
    member_id: draft.member?.member_id ?? "",
    first_name: draft.member?.first_name ?? "",
    last_name: draft.member?.last_name ?? "",
    dob: textOf(draft.member?.dob).slice(0, 10),
    group_number: draft.group_number ?? "",
    billing_npi: draft.billing_provider?.npi ?? "",
    billing_name: draft.billing_provider?.name ?? "",
    rendering_npi: draft.rendering_npi ?? "",
    place_of_service: draft.place_of_service ?? "",
    service_from: textOf(draft.service_from).slice(0, 10),
    service_to: textOf(draft.service_to).slice(0, 10),
    diagnosis_codes: (draft.diagnosis_codes ?? []).join(", "),
    lines: (draft.lines ?? []).map((line) => ({
      line_no: line.line_no,
      cpt_code: line.cpt_code ?? "",
      units: line.units ?? 1,
      billed_amount: textOf(line.billed_amount),
      service_date: textOf(line.service_date).slice(0, 10),
      diagnosis_pointers: (line.diagnosis_pointers ?? []).join(", "),
      prior_auth_number: line.prior_auth_number ?? "",
    })),
  };
}

function money(value: string) {
  const amount = Number(value);
  return Number.isFinite(amount) ? amount : 0;
}

function pointers(value: string) {
  return value
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => Number(part));
}

export function CorrectClaim({ submissionId }: { submissionId: string }) {
  const { actor } = useActor();
  const [form, setForm] = useState<FormState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const response = await request(`/submissions/${encodeURIComponent(submissionId)}/draft`, actor);
        if (cancelled) {
          return;
        }
        if (!response.ok) {
          setError(errorText(response.data, "The claim details are not available"));
          return;
        }
        const body = response.data as { draft?: Draft | string };
        const draft = typeof body.draft === "string" ? (JSON.parse(body.draft) as Draft) : body.draft;
        if (!draft) {
          setError("The claim details are not available");
          return;
        }
        setForm(fromDraft(draft));
      } catch {
        if (!cancelled) {
          setError("Portal API is not reachable");
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [submissionId, actor]);

  function updateLine(index: number, patch: Partial<Line>) {
    if (!form) {
      return;
    }
    setForm({
      ...form,
      lines: form.lines.map((line, lineIndex) => (lineIndex === index ? { ...line, ...patch } : line)),
    });
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!form) {
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    const payload = {
      claim: {
        claim_type: "professional",
        member: {
          member_id: form.member_id,
          first_name: form.first_name,
          last_name: form.last_name,
          dob: form.dob,
        },
        group_number: form.group_number || null,
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
        total_billed: form.lines.reduce((sum, line) => sum + money(line.billed_amount), 0).toFixed(2),
      },
    };
    try {
      const response = await request(`/submissions/${encodeURIComponent(submissionId)}/correction`, actor, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        setError(errorText(response.data, "The correction was not saved"));
        return;
      }
      const saved = response.data as { claim_status?: string; issues?: string[] };
      if (saved.claim_status === "VALIDATED") {
        setNotice("Saved. The claim passed the checks and can move on.");
        return;
      }
      if (saved.claim_status === "REJECTED") {
        setNotice("Saved. The claim is rejected.");
        return;
      }
      const remaining = (saved.issues ?? []).join(" ");
      setNotice(remaining ? `Saved. Still needs information: ${remaining}` : "Saved. The claim still needs information.");
    } catch {
      setError("Portal API is not reachable");
    } finally {
      setBusy(false);
    }
  }

  if (!form) {
    return error ? <Alert severity="error">{error}</Alert> : null;
  }

  const lineSum = form.lines.reduce((sum, line) => sum + money(line.billed_amount), 0);

  return (
    <form className={styles.form} onSubmit={(event) => void save(event)}>
      <div>
        <Typography variant="h6" component="h2">Update this claim</Typography>
        <Typography color="text.secondary">
          Change the details and save. The payer checks the whole claim again.
        </Typography>
      </div>
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
      <Typography>Total billed {lineSum.toFixed(2)}</Typography>
      {error && <Alert severity="error">{error}</Alert>}
      {notice && <Alert severity={notice.startsWith("Saved. The claim passed") ? "success" : "info"}>{notice}</Alert>}
      <Button type="submit" variant="contained" disabled={busy}>{busy ? "Saving…" : "Save correction"}</Button>
    </form>
  );
}
