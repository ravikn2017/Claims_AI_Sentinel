import Chip from "@mui/material/Chip";
import styles from "./StatusChip.module.css";

const labels: Record<string, string> = {
  RECEIVED: "Received",
  PROCESSING: "Processing",
  FAILED_PROCESSING: "Processing failed",
  PENDING_INFO: "Needs information",
  REJECTED: "Rejected",
  VALIDATED: "Queued for adjudication",
  IN_ADJUDICATION: "In adjudication",
  PENDING_REVIEW: "In review",
  APPROVED: "Approved",
  DENIED: "Denied",
};

const colors: Record<string, "default" | "info" | "warning" | "success" | "error" | "primary"> = {
  RECEIVED: "default",
  PROCESSING: "info",
  FAILED_PROCESSING: "error",
  PENDING_INFO: "warning",
  REJECTED: "error",
  VALIDATED: "primary",
  IN_ADJUDICATION: "info",
  PENDING_REVIEW: "warning",
  APPROVED: "success",
  DENIED: "error",
};

export function StatusChip({ status }: { status: string }) {
  return <Chip className={styles.chip} label={labels[status] ?? status} color={colors[status] ?? "default"} size="small" />;
}
