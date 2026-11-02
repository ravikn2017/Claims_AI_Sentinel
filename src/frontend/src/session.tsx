import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type Role = "provider" | "member" | "reviewer" | "investigator" | "ops";

export type Actor = {
  id: string;
  type: string;
  role: Role;
};

export type User = {
  token: string;
  userId: string;
  email: string;
  displayName: string;
  role: Role;
  actor: Actor;
};

const roles: Role[] = ["provider", "member", "reviewer", "investigator", "ops"];
const tokenKey = "claimsai-token";
const userKey = "claimsai-user";

export function tokenStorageKey() {
  return tokenKey;
}

function isRole(value: string): value is Role {
  return roles.includes(value as Role);
}

export function userFromLogin(body: {
  token: string;
  user_id: string;
  email: string;
  display_name: string;
  role: string;
  actor_type: string;
  submitter_id: string | null;
}): User | null {
  if (!isRole(body.role) || !body.token || !body.user_id) {
    return null;
  }
  return {
    token: body.token,
    userId: body.user_id,
    email: body.email,
    displayName: body.display_name,
    role: body.role,
    actor: {
      id: body.submitter_id || body.user_id,
      type: body.actor_type,
      role: body.role,
    },
  };
}

function loadUser(): User | null {
  try {
    const raw = sessionStorage.getItem(userKey);
    const token = sessionStorage.getItem(tokenKey);
    if (!raw || !token) {
      return null;
    }
    const parsed = JSON.parse(raw) as User;
    if (parsed.token === token && isRole(parsed.role) && parsed.actor?.id) {
      return parsed;
    }
  } catch {
    /* ask the person to sign in again */
  }
  return null;
}

function persist(user: User | null) {
  sessionStorage.removeItem("claimsai-actor");
  if (!user) {
    sessionStorage.removeItem(tokenKey);
    sessionStorage.removeItem(userKey);
    return;
  }
  sessionStorage.setItem(tokenKey, user.token);
  sessionStorage.setItem(userKey, JSON.stringify(user));
}

const SessionContext = createContext<{ user: User | null; setUser: (user: User | null) => void } | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUserState] = useState<User | null>(loadUser);
  const value = useMemo(
    () => ({
      user,
      setUser(next: User | null) {
        persist(next);
        setUserState(next);
      },
    }),
    [user],
  );
  useEffect(() => {
    function onSignedOut() {
      persist(null);
      setUserState(null);
    }
    window.addEventListener("claimsai-signed-out", onSignedOut);
    return () => window.removeEventListener("claimsai-signed-out", onSignedOut);
  }, []);
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const value = useContext(SessionContext);
  if (!value) {
    throw new Error("Session is missing");
  }
  return value;
}

export function useActor() {
  const { user } = useSession();
  if (!user) {
    throw new Error("Sign in required");
  }
  return { actor: user.actor };
}

export function homeFor(_role: Role) {
  return "/";
}

export const staffRoles: Role[] = ["reviewer", "investigator", "ops"];
