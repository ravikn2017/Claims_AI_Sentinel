import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Typography from "@mui/material/Typography";
import { Link as RouterLink } from "react-router-dom";
import { errorText, request } from "../../api";
import { EmptyState } from "../../components/EmptyState";
import { useActor } from "../../session";
import styles from "./QueuePage.module.css";

type Task = {
  task_id: number;
  claim_id: string;
  risk_score: string | null;
  status: string;
  task_type: string;
  assignee: string | null;
};

export function QueuePage() {
  const { actor } = useActor();
  const [taskType, setTaskType] = useState(actor.role === "investigator" ? "INVESTIGATION" : "REVIEW");
  const [tasks, setTasks] = useState<Task[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void request(`/review-tasks?status=OPEN&task_type=${taskType}`, actor)
      .then((response) => {
        if (cancelled) {
          return;
        }
        if (!response.ok) {
          setError(errorText(response.data));
          return;
        }
        setError(null);
        setTasks(response.data as Task[]);
      })
      .catch(() => {
        if (!cancelled) {
          setError("Portal API is not reachable");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [actor, taskType]);

  return (
    <section className={styles.page}>
      <Typography variant="h4" component="h1">Work queue</Typography>
      <ToggleButtonGroup exclusive value={taskType} onChange={(_event, value: string | null) => value && setTaskType(value)}>
        <ToggleButton value="REVIEW">Review</ToggleButton>
        <ToggleButton value="INVESTIGATION">Investigation</ToggleButton>
      </ToggleButtonGroup>
      {error && <Alert severity="error">{error}</Alert>}
      {!error && tasks.length === 0 && <EmptyState title="No open tasks" detail="Tasks appear here when the adjudicator pauses for a person. None are queued yet." />}
      <ul className={styles.list}>
        {tasks.map((task) => (
          <li key={task.task_id} className={styles.item}>
            <div>
              <Typography className={styles.id}>{task.claim_id}</Typography>
              <Typography variant="body2" color="text.secondary">
                {task.task_type} · risk {task.risk_score ?? "—"}
              </Typography>
            </div>
            <Button component={RouterLink} to={`/review/${task.task_id}`} variant="contained">Open</Button>
          </li>
        ))}
      </ul>
    </section>
  );
}
