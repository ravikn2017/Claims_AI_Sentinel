import AssignmentOutlined from "@mui/icons-material/AssignmentOutlined";
import ChatOutlined from "@mui/icons-material/ChatOutlined";
import FactCheckOutlined from "@mui/icons-material/FactCheckOutlined";
import InboxOutlined from "@mui/icons-material/InboxOutlined";
import LibraryBooksOutlined from "@mui/icons-material/LibraryBooksOutlined";
import MenuBookOutlined from "@mui/icons-material/MenuBookOutlined";
import NoteAddOutlined from "@mui/icons-material/NoteAddOutlined";
import ReportProblemOutlined from "@mui/icons-material/ReportProblemOutlined";
import SearchOutlined from "@mui/icons-material/SearchOutlined";
import Typography from "@mui/material/Typography";
import { Link as RouterLink } from "react-router-dom";
import { staffRoles, useSession, type Role } from "../../session";
import styles from "./HomePage.module.css";

const cards: { to: string; title: string; detail: string; icon: typeof NoteAddOutlined; roles: Role[] }[] = [
  {
    to: "/submit",
    title: "Submit a claim",
    detail: "Send a professional claim and follow it from validation onward.",
    icon: NoteAddOutlined,
    roles: ["provider", "member", "reviewer", "investigator", "ops"],
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

export function HomePage() {
  const { user } = useSession();
  if (!user) {
    return null;
  }
  const visible = cards.filter((card) => card.roles.includes(user.role));
  return (
    <section className={styles.page}>
      <div>
        <Typography variant="overline" color="text.secondary">
          {user.role}
        </Typography>
        <Typography variant="h4" component="h1">
          Hello, {user.displayName}
        </Typography>
        <Typography color="text.secondary">
          Choose where to go. Submit a claim or open the list, then use Back to return.
        </Typography>
      </div>
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
    </section>
  );
}
