import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Typography from "@mui/material/Typography";
import { useActor } from "../../session";
import styles from "./HealthPage.module.css";

type Health = { status: string; postgres: string; rabbitmq: string };

export function HealthPage() {
  const { actor } = useActor();
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void fetch("/health", { headers: { "X-Actor-Role": actor.role } })
      .then(async (response) => {
        const body = (await response.json()) as Health;
        setHealth(body);
        setError(response.ok ? null : "Platform check failed");
      })
      .catch(() => setError("Portal API is not reachable"));
  }, [actor.role]);

  return (
    <section className={styles.page}>
      <Typography variant="h4" component="h1">Health</Typography>
      {error && <Alert severity="error">{error}</Alert>}
      {health && (
        <ul className={styles.list}>
          <li>Overall: {health.status}</li>
          <li>Postgres: {health.postgres}</li>
          <li>RabbitMQ: {health.rabbitmq}</li>
        </ul>
      )}
    </section>
  );
}
