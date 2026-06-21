"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { saveSession } from "@/lib/auth";

const ROLES = ["admin", "knowledge_owner", "reviewer", "consumer"] as const;

export default function LoginPage() {
  const router = useRouter();
  const [displayName, setDisplayName] = useState("Demo User");
  const [role, setRole] = useState<string>("knowledge_owner");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const userId = crypto.randomUUID();
      const result = await api.issueDevToken(userId, displayName, [role]);
      saveSession(result.access_token, {
        user_id: result.user_id,
        display_name: displayName,
        roles: result.roles,
      });
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to sign in");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50">
      <form onSubmit={handleSubmit} className="w-full max-w-sm space-y-4 rounded-lg border border-gray-200 bg-white p-8 shadow-sm">
        <div>
          <h1 className="text-lg font-semibold text-gray-900">Knowledge Product Studio</h1>
          <p className="mt-1 text-sm text-gray-500">
            Dev sign-in — issues a JWT with the selected role. Replace with your SSO provider in production.
          </p>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700">Display name</label>
          <input
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700">Role</label>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value)}
            className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </div>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button
          type="submit"
          disabled={loading}
          className="w-full rounded bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-700 disabled:opacity-50"
        >
          {loading ? "Signing in..." : "Sign in"}
        </button>
      </form>
    </div>
  );
}
