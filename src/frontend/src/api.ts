import type { Actor } from "./session";
import { tokenStorageKey } from "./session";

export async function request(path: string, actor?: Actor | null, init: RequestInit = {}) {
  const headers = new Headers(init.headers);
  if (actor) {
    headers.set("X-Actor-Type", actor.type);
    headers.set("X-Actor-Id", actor.id);
    headers.set("X-Actor-Role", actor.role);
  }
  const token = sessionStorage.getItem(tokenStorageKey());
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, { ...init, headers });
  if (response.status === 401 && !path.startsWith("/auth/")) {
    sessionStorage.removeItem(tokenStorageKey());
    sessionStorage.removeItem("claimsai-user");
    window.dispatchEvent(new Event("claimsai-signed-out"));
  }
  const text = await response.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text };
    }
  }
  return { ok: response.ok, status: response.status, data };
}

export function errorText(data: unknown, fallback = "Request failed") {
  if (!data || typeof data !== "object") {
    return fallback;
  }
  const detail = (data as { detail?: unknown }).detail;
  if (typeof detail === "string") {
    return detail;
  }
  if (detail && typeof detail === "object" && "status" in detail) {
    return `The claim is ${(detail as { status: string }).status}`;
  }
  return fallback;
}
