import AccountTreeOutlined from "@mui/icons-material/AccountTreeOutlined";
import CancelOutlined from "@mui/icons-material/CancelOutlined";
import ChatOutlined from "@mui/icons-material/ChatOutlined";
import CheckCircleOutlined from "@mui/icons-material/CheckCircleOutlined";
import FactCheckOutlined from "@mui/icons-material/FactCheckOutlined";
import GavelOutlined from "@mui/icons-material/GavelOutlined";
import HighlightOffOutlined from "@mui/icons-material/HighlightOffOutlined";
import HowToRegOutlined from "@mui/icons-material/HowToRegOutlined";
import MedicalServicesOutlined from "@mui/icons-material/MedicalServicesOutlined";
import MenuBookOutlined from "@mui/icons-material/MenuBookOutlined";
import ScheduleOutlined from "@mui/icons-material/ScheduleOutlined";
import SearchOutlined from "@mui/icons-material/SearchOutlined";
import SendOutlined from "@mui/icons-material/SendOutlined";
import ShieldOutlined from "@mui/icons-material/ShieldOutlined";
import Step from "@mui/material/Step";
import StepLabel from "@mui/material/StepLabel";
import Stepper from "@mui/material/Stepper";
import Typography from "@mui/material/Typography";
import type { SvgIconComponent } from "@mui/icons-material";
import styles from "./ClaimStages.module.css";

export type HistoryRow = { from_status: string | null; to_status: string; reason: string | null };

export type AdjEvent = {
  event_type: string;
  payload: Record<string, unknown>;
  actor?: string;
};

type StepState = "done" | "active" | "waiting" | "skipped" | "error";

type Stage = { label: string; detail?: string; state: StepState };

const stageIcons: Record<string, SvgIconComponent> = {
  Submitted: SendOutlined,
  Validating: FactCheckOutlined,
  "Needs information": ChatOutlined,
  "Queued for adjudication": ScheduleOutlined,
  "Adjudication in progress": AccountTreeOutlined,
  "Policy check": MenuBookOutlined,
  "Fraud check": ShieldOutlined,
  "Medical necessity": MedicalServicesOutlined,
  Investigation: SearchOutlined,
  "Claim review": HowToRegOutlined,
  "In review": HowToRegOutlined,
  Approved: CheckCircleOutlined,
  Denied: CancelOutlined,
  Rejected: HighlightOffOutlined,
  Decision: GavelOutlined,
};

const later = new Set(["VALIDATED", "IN_ADJUDICATION", "PENDING_REVIEW", "APPROVED", "DENIED"]);

function verdict(events: AdjEvent[], agent: string) {
  const match = [...events].reverse().find((event) => event.event_type === "AGENT_RESULT" && event.payload.agent === agent);
  return typeof match?.payload.verdict === "string" ? match.payload.verdict : undefined;
}

function staffChecks(events: AdjEvent[], status: string): Stage[] {
  const steps: Stage[] = [];
  const policy = verdict(events, "policy_compliance");
  const fraud = verdict(events, "fraud_detection");
  const medical = verdict(events, "medical_necessity");
  if (policy) {
    steps.push({ label: "Policy check", detail: policy, state: "done" });
  }
  if (fraud) {
    steps.push({ label: "Fraud check", detail: fraud, state: "done" });
  }
  if (medical) {
    steps.push({ label: "Medical necessity", detail: medical, state: "done" });
  } else if (policy === "NOT_COVERED") {
    steps.push({ label: "Medical necessity", detail: "Skipped", state: "skipped" });
  }
  const investigation = events.filter((event) => event.event_type.startsWith("INVESTIGATION"));
  if (investigation.length > 0 || fraud === "FLAGGED") {
    const result = investigation.find((event) => event.event_type === "INVESTIGATION_RESULT");
    const outcome = typeof result?.payload.outcome === "string" ? result.payload.outcome : undefined;
    steps.push({
      label: "Investigation",
      detail: outcome ?? "Waiting",
      state: result ? "done" : "active",
    });
  }
  const reviews = events.filter((event) => event.event_type.startsWith("REVIEW_"));
  if (reviews.length > 0) {
    const decided = reviews.some((event) => event.event_type === "REVIEW_DECIDED");
    const picked = reviews.some((event) => event.event_type === "REVIEW_PICKED_UP");
    steps.push({
      label: "Claim review",
      detail: decided ? "Decided" : picked ? "Picked up" : "Waiting in the queue",
      state: decided ? "done" : "active",
    });
  }
  if (steps.length === 0) {
    steps.push({
      label: "Adjudication in progress",
      state: status === "IN_ADJUDICATION" ? "active" : "done",
    });
  }
  return steps;
}

export function buildStages(status: string, history: HistoryRow[], events: AdjEvent[], staff: boolean): Stage[] {
  const seen = new Set(history.map((row) => row.to_status));
  seen.add(status);
  const hadInfo = seen.has("PENDING_INFO");
  const reachedQueue = [...later].some((item) => seen.has(item));
  const failed = status === "FAILED_PROCESSING";
  const rejected = status === "REJECTED";
  const steps: Stage[] = [
    { label: "Submitted", state: "done" },
    {
      label: "Validating",
      state: failed ? "error" : status === "PROCESSING" ? "active" : "done",
      detail: failed ? "Processing failed" : undefined,
    },
  ];
  if (hadInfo) {
    steps.push({
      label: "Needs information",
      state: status === "PENDING_INFO" ? "active" : "done",
    });
  }
  steps.push({
    label: "Queued for adjudication",
    state: status === "VALIDATED" ? "active" : reachedQueue ? "done" : failed || rejected ? "skipped" : "waiting",
  });
  if (staff && events.length > 0) {
    steps.push(...staffChecks(events, status));
  } else {
    steps.push({
      label: "Adjudication in progress",
      state: status === "IN_ADJUDICATION" ? "active" : ["PENDING_REVIEW", "APPROVED", "DENIED"].includes(status) ? "done" : failed || rejected ? "skipped" : "waiting",
    });
  }
  const skippedReview = (status === "APPROVED" || status === "DENIED") && !seen.has("PENDING_REVIEW");
  steps.push({
    label: "In review",
    detail: status === "PENDING_REVIEW" ? "Waiting for a reviewer, or a reviewer has the claim" : undefined,
    state: status === "PENDING_REVIEW" ? "active" : skippedReview || failed || rejected ? "skipped" : seen.has("PENDING_REVIEW") ? "done" : "waiting",
  });
  const decisionLabel = status === "APPROVED" ? "Approved" : status === "DENIED" ? "Denied" : status === "REJECTED" ? "Rejected" : "Decision";
  steps.push({
    label: decisionLabel,
    state: status === "APPROVED" ? "done" : status === "DENIED" || rejected ? "error" : failed ? "skipped" : "waiting",
  });
  return steps;
}

export function ClaimStages({ status, history, events, staff }: { status: string; history: HistoryRow[]; events: AdjEvent[]; staff: boolean }) {
  const steps = buildStages(status, history, events, staff);
  const active = Math.max(0, steps.findIndex((step) => step.state === "active" || step.state === "error"));
  return (
    <Stepper className={styles.stepper} activeStep={active} orientation="vertical">
      {steps.map((step) => {
        const Icon = stageIcons[step.label];
        return (
          <Step key={step.label} completed={step.state === "done"}>
            <StepLabel
              className={step.state === "skipped" ? styles.skipped : undefined}
              error={step.state === "error"}
              optional={step.detail ? <Typography variant="caption">{step.detail}</Typography> : undefined}
            >
              <span className={styles.label}>
                {step.label}
                {Icon && (
                  <Icon
                    className={styles.icon}
                    fontSize="small"
                    color={step.state === "error" ? "error" : step.state === "active" ? "primary" : "action"}
                    aria-hidden
                  />
                )}
              </span>
            </StepLabel>
          </Step>
        );
      })}
    </Stepper>
  );
}
