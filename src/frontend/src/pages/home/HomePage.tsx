import AssignmentOutlined from "@mui/icons-material/AssignmentOutlined";
import CheckOutlined from "@mui/icons-material/CheckOutlined";
import ChatOutlined from "@mui/icons-material/ChatOutlined";
import FactCheckOutlined from "@mui/icons-material/FactCheckOutlined";
import InboxOutlined from "@mui/icons-material/InboxOutlined";
import LibraryBooksOutlined from "@mui/icons-material/LibraryBooksOutlined";
import MenuBookOutlined from "@mui/icons-material/MenuBookOutlined";
import NoteAddOutlined from "@mui/icons-material/NoteAddOutlined";
import QueryStatsOutlined from "@mui/icons-material/QueryStatsOutlined";
import ReportProblemOutlined from "@mui/icons-material/ReportProblemOutlined";
import SearchOutlined from "@mui/icons-material/SearchOutlined";
import Typography from "@mui/material/Typography";
import { Link as RouterLink } from "react-router-dom";
import { roleLabel, staffRoles, useSession, type Role } from "../../session";
import styles from "./HomePage.module.css";

const cards: { to: string; title: string; detail: string; icon: typeof NoteAddOutlined; roles: Role[] }[] = [
  {
    to: "/submit",
    title: "Submit a claim",
    detail: "Send a professional claim and follow it from validation onward.",
    icon: NoteAddOutlined,
    roles: ["provider", "member", "ops"],
  },
  {
    to: "/claims",
    title: "Claims",
    detail: "Open a submission, see where it stands, and return here when you are done.",
    icon: AssignmentOutlined,
    roles: ["provider", "member", "reviewer", "investigator", "ops"],
  },
  {
    to: "/inquiry",
    title: "Ask",
    detail: "Ask about your claims, your plan, or a provider. This does not change a claim.",
    icon: ChatOutlined,
    roles: ["member"],
  },
  {
    to: "/review",
    title: "Work queue",
    detail: "Pick up a review or an investigation that is waiting for a person.",
    icon: InboxOutlined,
    roles: ["reviewer", "investigator"],
  },
  {
    to: "/claims/lookup",
    title: "Look up a claim",
    detail: "Open any submission when you already have its id.",
    icon: SearchOutlined,
    roles: staffRoles,
  },
  {
    to: "/ops/knowledge",
    title: "Knowledge",
    detail: "Index evidence of coverage and medical policy for retrieval.",
    icon: MenuBookOutlined,
    roles: ["ops"],
  },
  {
    to: "/ops/fraud-model",
    title: "Fraud model",
    detail: "Train the claim-risk model and compare precision, recall, and F1.",
    icon: QueryStatsOutlined,
    roles: ["ops"],
  },
  {
    to: "/ops/failures",
    title: "Intake failures",
    detail: "Replay or discard submissions that did not make it into a claim.",
    icon: ReportProblemOutlined,
    roles: ["ops"],
  },
  {
    to: "/ops/audit",
    title: "Audit",
    detail: "Read the trail of what happened to a claim.",
    icon: FactCheckOutlined,
    roles: ["ops"],
  },
  {
    to: "/ops/reference",
    title: "Reference data",
    detail: "Look up codes, plans, and other read-only reference rows.",
    icon: LibraryBooksOutlined,
    roles: ["ops"],
  },
];

const briefs: Record<Role, { summary: string; can: string[] }> = {
  provider: {
    summary: "You file professional claims for your practice and follow the ones you submitted.",
    can: [
      "Submit a professional claim and attach a record",
      "Open your submissions and see where each one stands",
    ],
  },
  member: {
    summary: "You are the person the claim is for. You can file a claim and ask about your plan. Asking does not change a decision.",
    can: [
      "Submit a claim",
      "Follow your own submissions",
      "Ask about your claims, your plan, or a provider",
    ],
  },
  reviewer: {
    summary: "You decide claims the adjudicator paused for a person. You do not file new claims.",
    can: [
      "See every submission and look one up by id",
      "Pick up a review from the queue",
      "Approve or deny the claim, and ask why the fraud check scored it",
    ],
  },
  investigator: {
    summary: "You examine claims the fraud check flagged. You confirm the concern or clear it. You do not file new claims.",
    can: [
      "See every submission and look one up by id",
      "Pick up an investigation from the queue",
      "Confirm or clear the claim, and ask the fraud assistant about the evidence",
    ],
  },
  ops: {
    summary: "You keep the platform running. You can see every claim, repair intake, and check whether each service is up.",
    can: [
      "Submit a claim or open any submission",
      "Index coverage and medical policy for retrieval",
      "Train the fraud model and compare precision, recall, and F1",
      "Replay or discard intake failures",
      "Read the audit trail and look up reference codes and plans",
      "Check service health from the top bar",
    ],
  },
};

export function HomePage() {
  const { user } = useSession();
  if (!user) {
    return null;
  }
  const visible = cards.filter((card) => card.roles.includes(user.role));
  const brief = briefs[user.role];
  return (
    <section className={styles.page}>
      <header className={styles.hero}>
        <p className={styles.kicker}>{roleLabel(user.role)}</p>
        <h1 className={styles.title}>Hello, {user.displayName}</h1>
        <p className={styles.summary}>{brief.summary}</p>
        <ul className={styles.can}>
          {brief.can.map((item) => (
            <li key={item}>
              <CheckOutlined className={styles.check} />
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </header>
      <div className={styles.section}>
        <p className={styles.sectionLabel}>Where to go</p>
      <div className={styles.grid}>
        {visible.map((card) => (
          <RouterLink key={card.to} to={card.to} className={styles.card}>
            <span className={styles.icon}>
              <card.icon fontSize="small" />
            </span>
            <Typography variant="h6" component="h2">
              {card.title}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {card.detail}
            </Typography>
          </RouterLink>
        ))}
      </div>
      </div>
    </section>
  );
}
