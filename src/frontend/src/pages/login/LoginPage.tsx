import { useState, type FormEvent } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useNavigate } from "react-router-dom";
import { errorText, request } from "../../api";
import { BrandMark } from "../../components/BrandMark";
import { ThemeToggle } from "../../components/ThemeToggle";
import { homeFor, useSession, userFromLogin, type Role } from "../../session";
import styles from "./LoginPage.module.css";

const demos: { email: string; role: string; detail: string }[] = [
  { email: "provider@example.test", role: "Provider", detail: "Lakeside Family Clinic" },
  { email: "member@example.test", role: "Member", detail: "Jane Doe" },
  { email: "reviewer@example.test", role: "Reviewer", detail: "Review queue" },
  { email: "investigator@example.test", role: "Investigator", detail: "Investigation queue" },
  { email: "ops@example.test", role: "Ops", detail: "Knowledge and audit" },
];

export function LoginPage() {
  const { setUser } = useSession();
  const navigate = useNavigate();
  const [email, setEmail] = useState("provider@example.test");
  const [password, setPassword] = useState("sentinel");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const response = await request("/auth/login", null, {
        method: "POST",
        body: JSON.stringify({ email: email.trim(), password }),
      });
      if (!response.ok) {
        setError(errorText(response.data, "Sign-in failed"));
        return;
      }
      const user = userFromLogin(response.data as Parameters<typeof userFromLogin>[0]);
      if (!user) {
        setError("The portal returned an account this screen does not recognize");
        return;
      }
      setUser(user);
      navigate(homeFor(user.role as Role), { replace: true });
    } catch {
      setError("Portal API is not reachable");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={styles.page}>
      <section className={styles.panel}>
        <p className={styles.kicker}>Payer portal</p>
        <div className={styles.titleRow}>
          <BrandMark />
          <Typography variant="h3" component="h1">
            ClaimsAI Sentinel
          </Typography>
        </div>
        <p className={styles.lede}>
          Submit a claim, answer what is missing, and follow it through validation and review. Your account decides
          which screens you can open.
        </p>
      </section>
      <section className={styles.formSide}>
        <div className={styles.toggle}>
          <ThemeToggle />
        </div>
        <form className={styles.card} onSubmit={submit}>
          <div>
            <Typography variant="h5" component="h2">
              Sign in
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Synthetic local accounts. The shared password is sentinel.
            </Typography>
          </div>
          {error ? <Alert severity="error">{error}</Alert> : null}
          <TextField
            label="Email"
            type="email"
            autoComplete="username"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
            fullWidth
          />
          <TextField
            label="Password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
            fullWidth
          />
          <Button type="submit" variant="contained" size="large" disabled={busy}>
            {busy ? "Signing in" : "Sign in"}
          </Button>
          <div className={styles.demos}>
            <Typography variant="overline">Demo accounts</Typography>
            {demos.map((demo) => (
              <button
                key={demo.email}
                type="button"
                className={styles.demo}
                onClick={() => {
                  setEmail(demo.email);
                  setPassword("sentinel");
                  setError(null);
                }}
              >
                <span>{demo.role}</span>
                <span className={styles.demoDetail}>{demo.detail}</span>
              </button>
            ))}
          </div>
        </form>
      </section>
    </div>
  );
}
