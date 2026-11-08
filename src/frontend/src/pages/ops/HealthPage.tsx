import { useCallback, useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import LinearProgress from "@mui/material/LinearProgress";
import Typography from "@mui/material/Typography";
import RefreshOutlined from "@mui/icons-material/RefreshOutlined";
import { errorText, request } from "../../api";
import { useActor } from "../../session";
import styles from "./HealthPage.module.css";

type Service = {
  name: string;
  status: string;
  postgres: string | null;
  rabbitmq: string | null;
  latency_ms: number | null;
};

type Report = {
  checked_at: string;
  postgres: string;
  rabbitmq: string;
  up: number;
  total: number;
  status: string;
  services: Service[];
};

function tone(status: string): "success" | "error" | "default" {
  if (status === "ok") {
    return "success";
  }
  if (status === "down" || status === "error") {
    return "error";
  }
  return "default";
}

function label(status: string) {
  if (status === "ok") {
    return "Up";
  }
  if (status === "down" || status === "error") {
    return "Down";
  }
  return status;
}

export function HealthPage() {
  const { actor } = useActor();
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const response = await request("/ops/health", actor);
      if (!response.ok) {
        setError(errorText(response.data, "Platform check failed"));
        setReport(null);
        return;
      }
      setReport(response.data as Report);
      setError(null);
    } catch {
      setError("Portal API is not reachable");
      setReport(null);
    } finally {
      setBusy(false);
    }
  }, [actor]);

  useEffect(() => {
    void load();
  }, [load]);

  const slowest = Math.max(1, ...(report?.services.map((service) => service.latency_ms ?? 0) ?? [1]));
  const rings = [styles.ring0, styles.ring1, styles.ring2, styles.ring3, styles.ring4, styles.ring5];
  const ring = report ? rings[Math.round((report.up / Math.max(report.total, 1)) * 5)] : "";

  return (
    <section className={styles.page}>
      <div className={styles.header}>
        <div>
          <Typography variant="h4" component="h1">Health</Typography>
          <Typography color="text.secondary">
            Portal, payer, chatbot, adjudicator, and fraud detection, plus the database and queue they share.
          </Typography>
        </div>
        <Button variant="outlined" startIcon={<RefreshOutlined />} onClick={() => void load()} disabled={busy}>
          {busy ? "Checking…" : "Check again"}
        </Button>
      </div>
      {error && <Alert severity="error">{error}</Alert>}
      {report && (
        <>
          <div className={styles.summary}>
            <div className={`${styles.ring} ${ring}`}>
              <div className={styles.hole}>
                <Typography variant="h5" component="p">{report.up}/{report.total}</Typography>
                <Typography variant="caption" color="text.secondary">services up</Typography>
              </div>
            </div>
            <div className={styles.summaryText}>
              <Chip size="small" color={tone(report.status)} label={report.status === "ok" ? "All healthy" : "Needs attention"} />
              <Typography>
                Checked {new Date(report.checked_at).toLocaleTimeString()}
              </Typography>
              <div className={styles.deps}>
                <Chip size="small" variant="outlined" color={tone(report.postgres)} label={`Postgres ${label(report.postgres)}`} />
                <Chip size="small" variant="outlined" color={tone(report.rabbitmq)} label={`RabbitMQ ${label(report.rabbitmq)}`} />
              </div>
            </div>
          </div>
          <div className={styles.panel}>
            <Typography variant="subtitle1" component="h2">Reply time</Typography>
            <ul className={styles.bars}>
              {report.services.map((service) => (
                <li key={service.name}>
                  <div className={styles.barLabel}>
                    <span>{service.name}</span>
                    <span>{service.latency_ms == null ? "No reply" : `${service.latency_ms} ms`}</span>
                  </div>
                  <LinearProgress
                    variant="determinate"
                    color={service.status === "ok" ? "success" : "error"}
                    value={service.latency_ms == null ? 100 : Math.max(8, (service.latency_ms / slowest) * 100)}
                  />
                </li>
              ))}
            </ul>
          </div>
          <div className={styles.cards}>
            {report.services.map((service) => (
              <article key={service.name} className={styles.card}>
                <div className={styles.cardTop}>
                  <Typography variant="h6" component="h2">{service.name}</Typography>
                  <Chip size="small" color={tone(service.status)} label={label(service.status)} />
                </div>
                <Typography variant="body2" color="text.secondary">
                  Postgres {service.postgres ? label(service.postgres) : "—"}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  RabbitMQ {service.rabbitmq ? label(service.rabbitmq) : "—"}
                </Typography>
                <Typography variant="body2">
                  {service.latency_ms == null ? "The service did not answer." : `Answered in ${service.latency_ms} ms.`}
                </Typography>
              </article>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
