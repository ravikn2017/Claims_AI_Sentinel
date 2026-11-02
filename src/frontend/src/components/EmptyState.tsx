import Typography from "@mui/material/Typography";
import styles from "./EmptyState.module.css";

export function EmptyState({ title, detail }: { title: string; detail?: string }) {
  return (
    <div className={styles.box}>
      <Typography variant="subtitle1">{title}</Typography>
      {detail && (
        <Typography variant="body2" color="text.secondary">
          {detail}
        </Typography>
      )}
    </div>
  );
}
