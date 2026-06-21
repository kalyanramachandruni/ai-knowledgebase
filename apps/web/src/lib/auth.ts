"use client";

const TOKEN_KEY = "kps_token";
const USER_KEY = "kps_user";

export interface StoredUser {
  user_id: string;
  display_name: string;
  roles: string[];
}

export function saveSession(token: string, user: StoredUser) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function getUser(): StoredUser | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem(USER_KEY);
  return raw ? JSON.parse(raw) : null;
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

/** Call from a page's catch block: if the API rejected the token, bounce to
 * /login instead of leaving the user stuck on a raw error message. */
export function redirectIfUnauthorized(err: unknown, router: { push: (path: string) => void }): boolean {
  if (err instanceof Error && "status" in err && (err as { status?: number }).status === 401) {
    clearSession();
    router.push("/login");
    return true;
  }
  return false;
}
