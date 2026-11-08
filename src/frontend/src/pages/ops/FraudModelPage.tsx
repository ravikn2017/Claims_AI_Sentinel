import { useCallback, useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Typography from "@mui/material/Typography";
import { errorText, request } from "../../api";
import { EmptyState } from "../../components/EmptyState";
import { useActor } from "../../session";
import styles from "./FraudModelPage.module.css";

type Technique = {
  technique: string;
  threshold: number;
  tp: number;
  tn: number;
  fp: number;
  fn: number;
  precision: number;
  recall: number;
  f1: number;
  selected: boolean;
};

type Report = {
  trained_at: string;
  next_refresh_at: string;
  row_count: number;
  fraud_count: number;
  active_technique: string;
  model_version: string;
  dataset: string;
  techniques: Technique[];
};

const names: Record<string, string> = {
  logistic_regression: "Logistic regression",
  random_forest: "Random forest",
  xgboost: "XGBoost",
  soft_voting_ensemble: "Soft-voting ensemble",
};

function label(technique: string) {
  return names[technique] || technique;
}

function percent(value: number) {
  return value.toFixed(3);
}

function when(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString();
}

export function FraudModelPage() {
  const { actor } = useActor();
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const response = await request("/ops/fraud-model", actor);
    if (response.status === 404) {
      setReport(null);
      setError(null);
      return;
    }
    if (!response.ok) {
      setError(errorText(response.data));
      return;
    }
    setReport(response.data as Report);
    setError(null);
  }, [actor]);

  useEffect(() => {
    void load();
  }, [load]);

  async function select(technique: string) {
    if (!report || technique === report.active_technique) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const response = await request("/ops/fraud-model/select", actor, {
        method: "POST",
        body: JSON.stringify({ technique }),
      });
      if (!response.ok) {
        setError(errorText(response.data));
        return;
      }
      setReport(response.data as Report);
    } catch {
      setError("Fraud model service is unavailable");
    } finally {
      setBusy(false);
    }
  }

  async function train() {
    setBusy(true);
    setError(null);
    try {
      const response = await request("/ops/fraud-model/train", actor, { method: "POST" });
      if (!response.ok) {
        setError(errorText(response.data));
        return;
      }
      setReport(response.data as Report);
    } catch {
      setError("Fraud model service is unavailable");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className={styles.page}>
      <div className={styles.heading}>
        <div>
          <Typography variant="h4" component="h1">Fraud model</Typography>
          <Typography color="text.secondary">
            Supervised claim-risk training on claim_risk_synthetic. Train now starts with the highest F1. Click a technique to use it for scoring.
          </Typography>
        </div>
        <Button variant="contained" disabled={busy} onClick={() => void train()}>
          {busy ? "Working" : "Train now"}
        </Button>
      </div>
      {error && <Alert severity="error">{error}</Alert>}
      {!report && !error && <EmptyState title="No model yet" detail="Train now fits logistic regression, random forest, XGBoost, and a soft-voting ensemble." />}
      {report && (
        <>
          <Typography>
            Trained {when(report.trained_at)}. Next refresh {when(report.next_refresh_at)}.
            {" "}{report.row_count} rows, {report.fraud_count} labeled fraud.
            Active technique: {label(report.active_technique)}. Version {report.model_version}.
          </Typography>
          <div className={styles.grid}>
            {report.techniques.map((technique) => (
              <article
                key={technique.technique}
                role="button"
                tabIndex={0}
                aria-pressed={technique.selected}
                className={technique.selected ? styles.active : styles.card}
                onClick={() => {
                  if (!busy) {
                    void select(technique.technique);
                  }
                }}
                onKeyDown={(event) => {
                  if (!busy && (event.key === "Enter" || event.key === " ")) {
                    event.preventDefault();
                    void select(technique.technique);
                  }
                }}
              >
                <Typography variant="h6" component="h2">
                  {label(technique.technique)}{technique.selected ? " · active" : ""}
                </Typography>
                <p>Precision {percent(technique.precision)} · Recall {percent(technique.recall)} · F1 {percent(technique.f1)}</p>
                <p>TP {technique.tp} · TN {technique.tn} · FP {technique.fp} · FN {technique.fn}</p>
                <table className={styles.matrix}>
                  <caption>Confusion matrix</caption>
                  <thead>
                    <tr>
                      <th />
                      <th>Predicted clear</th>
                      <th>Predicted fraud</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <th>Actual clear</th>
                      <td>TN {technique.tn}</td>
                      <td>FP {technique.fp}</td>
                    </tr>
                    <tr>
                      <th>Actual fraud</th>
                      <td>FN {technique.fn}</td>
                      <td>TP {technique.tp}</td>
                    </tr>
                  </tbody>
                </table>
              </article>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
