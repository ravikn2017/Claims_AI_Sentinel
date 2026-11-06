import { useState } from "react";
import AppBar from "@mui/material/AppBar";
import Button from "@mui/material/Button";
import IconButton from "@mui/material/IconButton";
import Popover from "@mui/material/Popover";
import Toolbar from "@mui/material/Toolbar";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import AccountCircleOutlined from "@mui/icons-material/AccountCircleOutlined";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import AssignmentOutlined from "@mui/icons-material/AssignmentOutlined";
import ChatOutlined from "@mui/icons-material/ChatOutlined";
import FactCheckOutlined from "@mui/icons-material/FactCheckOutlined";
import HomeOutlined from "@mui/icons-material/HomeOutlined";
import InboxOutlined from "@mui/icons-material/InboxOutlined";
import LibraryBooksOutlined from "@mui/icons-material/LibraryBooksOutlined";
import MenuBookOutlined from "@mui/icons-material/MenuBookOutlined";
import MenuOutlined from "@mui/icons-material/MenuOutlined";
import MenuOpenOutlined from "@mui/icons-material/MenuOpenOutlined";
import MonitorHeartOutlined from "@mui/icons-material/MonitorHeartOutlined";
import NoteAddOutlined from "@mui/icons-material/NoteAddOutlined";
import ReportProblemOutlined from "@mui/icons-material/ReportProblemOutlined";
import SearchOutlined from "@mui/icons-material/SearchOutlined";
import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import styles from "./App.module.css";
import { BrandMark } from "./components/BrandMark";
import { ThemeToggle } from "./components/ThemeToggle";
import { request } from "./api";
import { LoginPage } from "./pages/login/LoginPage";
import { ClaimsPage } from "./pages/claims/ClaimsPage";
import { HomePage } from "./pages/home/HomePage";
import { InquiryPage } from "./pages/inquiry/InquiryPage";
import { AuditPage } from "./pages/ops/AuditPage";
import { FailuresPage } from "./pages/ops/FailuresPage";
import { HealthPage } from "./pages/ops/HealthPage";
import { KnowledgePage } from "./pages/ops/KnowledgePage";
import { ReferencePage } from "./pages/ops/ReferencePage";
import { CasePage } from "./pages/review/CasePage";
import { QueuePage } from "./pages/review/QueuePage";
import { StatusPage } from "./pages/status/StatusPage";
import { SubmitPage } from "./pages/submit/SubmitPage";
import { homeFor, staffRoles, useSession, type Role, type User } from "./session";

const everyone: Role[] = ["provider", "member", "reviewer", "investigator", "ops"];

const links: { to: string; label: string; icon: typeof HomeOutlined; roles: Role[]; end?: boolean }[] = [
  { to: "/", label: "Home", icon: HomeOutlined, roles: everyone, end: true },
  { to: "/submit", label: "Submit", icon: NoteAddOutlined, roles: ["provider", "member", "reviewer", "ops"] },
  { to: "/claims", label: "Claims", icon: AssignmentOutlined, roles: everyone, end: true },
  { to: "/inquiry", label: "Ask", icon: ChatOutlined, roles: ["member"], end: true },
  { to: "/claims/lookup", label: "Look up", icon: SearchOutlined, roles: staffRoles },
  { to: "/review", label: "Queue", icon: InboxOutlined, roles: ["reviewer", "investigator"], end: true },
  { to: "/ops/knowledge", label: "Knowledge", icon: MenuBookOutlined, roles: ["ops"] },
  { to: "/ops/failures", label: "Intake failures", icon: ReportProblemOutlined, roles: ["ops"] },
  { to: "/ops/audit", label: "Audit", icon: FactCheckOutlined, roles: ["ops"] },
  { to: "/ops/reference", label: "Reference data", icon: LibraryBooksOutlined, roles: ["ops"] },
];

function backFor(pathname: string): { to: string; label: string } | null {
  if (pathname === "/") {
    return null;
  }
  if (pathname.startsWith("/claims/") && pathname !== "/claims/lookup") {
    return { to: "/claims", label: "Back to claims" };
  }
  if (pathname.startsWith("/review/") && pathname !== "/review") {
    return { to: "/review", label: "Back to queue" };
  }
  return { to: "/", label: "Back" };
}

function ProfileButton({ user, onSignOut }: { user: User; onSignOut: () => void }) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const submitter = user.actor.id !== user.userId ? user.actor.id : null;
  return (
    <>
      <IconButton color="inherit" aria-label="Profile" onClick={(event) => setAnchor(event.currentTarget)}>
        <AccountCircleOutlined />
      </IconButton>
      <Popover
        open={Boolean(anchor)}
        anchorEl={anchor}
        onClose={() => setAnchor(null)}
        anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
        transformOrigin={{ vertical: "top", horizontal: "right" }}
      >
        <div className={styles.profile}>
          <Typography variant="subtitle1">{user.displayName}</Typography>
          <Typography variant="body2" color="text.secondary">{user.email}</Typography>
          <Typography variant="body2"><span className={styles.profileLabel}>Role</span> {user.role}</Typography>
          <Typography variant="body2"><span className={styles.profileLabel}>User</span> {user.userId}</Typography>
          {submitter && <Typography variant="body2"><span className={styles.profileLabel}>Submitter</span> {submitter}</Typography>}
          <Button className={styles.signOut} color="inherit" onClick={onSignOut}>
            Sign out
          </Button>
        </div>
      </Popover>
    </>
  );
}

function Shell() {
  const { user, setUser } = useSession();
  const location = useLocation();
  const [navOpen, setNavOpen] = useState(true);
  if (!user) {
    return <Navigate to="/login" replace />;
  }
  const visible = links.filter((link) => link.roles.includes(user.role));
  const back = backFor(location.pathname);

  async function signOut() {
    try {
      await request("/auth/logout", user?.actor, { method: "POST" });
    } catch {
      /* drop the local session even if the portal is down */
    }
    setUser(null);
  }

  return (
    <div className={styles.shell}>
      <AppBar position="static" color="primary" className={styles.bar}>
        <Toolbar className={styles.toolbar}>
          <div className={styles.brandBlock}>
            <BrandMark />
            <div>
              <Typography variant="h6" component="p" className={styles.brand}>
                ClaimsAI Sentinel
              </Typography>
              <Typography variant="caption" component="p" className={styles.tagline}>
                {user.displayName} · {user.role}
              </Typography>
            </div>
          </div>
          <div className={styles.controls}>
            {user.role === "ops" && (
              <Button color="inherit" component={NavLink} to="/ops/health" startIcon={<MonitorHeartOutlined />} className={location.pathname === "/ops/health" ? styles.healthOn : undefined}>
                Health
              </Button>
            )}
            <ThemeToggle />
            <ProfileButton user={user} onSignOut={() => void signOut()} />
          </div>
        </Toolbar>
      </AppBar>
      <div className={navOpen ? styles.body : `${styles.body} ${styles.bodyCollapsed}`}>
        <nav className={navOpen ? styles.nav : `${styles.nav} ${styles.navCollapsed}`}>
          <IconButton
            className={styles.menuToggle}
            aria-label={navOpen ? "Collapse menu" : "Expand menu"}
            aria-expanded={navOpen}
            onClick={() => setNavOpen((open) => !open)}
          >
            {navOpen ? <MenuOpenOutlined /> : <MenuOutlined />}
          </IconButton>
          {visible.map((link) => {
            const active = link.end ? location.pathname === link.to : location.pathname.startsWith(link.to);
            const item = (
              <NavLink key={link.to} to={link.to} end={link.end} className={active ? `${styles.link} ${styles.active}` : styles.link}>
                <link.icon className={styles.navIcon} />
                <span className={styles.navLabel}>{link.label}</span>
              </NavLink>
            );
            return navOpen ? item : (
              <Tooltip key={link.to} title={link.label} placement="right">
                {item}
              </Tooltip>
            );
          })}
        </nav>
        <main className={styles.main}>
          {back && (
            <Button component={NavLink} to={back.to} end startIcon={<ArrowBackIcon />} className={styles.back}>
              {back.label}
            </Button>
          )}
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/submit" element={user.role === "investigator" ? <Navigate to="/" replace /> : <SubmitPage />} />
            <Route path="/claims" element={<ClaimsPage />} />
            <Route path="/inquiry" element={<InquiryPage />} />
            <Route path="/claims/lookup" element={<StatusPage />} />
            <Route path="/claims/:submissionId" element={<StatusPage />} />
            <Route path="/review" element={<QueuePage />} />
            <Route path="/review/:taskId" element={<CasePage />} />
            <Route path="/ops/knowledge" element={<KnowledgePage />} />
            <Route path="/ops/failures" element={<FailuresPage />} />
            <Route path="/ops/audit" element={<AuditPage />} />
            <Route path="/ops/reference" element={<ReferencePage />} />
            <Route path="/ops/health" element={<HealthPage />} />
            <Route path="*" element={<Navigate to={homeFor(user.role)} replace />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}

export function App() {
  const { user } = useSession();
  return (
    <Routes>
      <Route path="/login" element={user ? <Navigate to={homeFor(user.role)} replace /> : <LoginPage />} />
      <Route path="/*" element={<Shell />} />
    </Routes>
  );
}
