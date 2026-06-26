"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { NavBar } from "@/components/NavBar";
import { api, ApiError } from "@/lib/api";
import { getToken, getUser, redirectIfUnauthorized } from "@/lib/auth";

interface SyncResult {
  space_key: string;
  pages_created: number;
  pages_updated: number;
  pages_skipped_unchanged: number;
}

export default function SourcesPage() {
  const router = useRouter();
  const user = getUser();
  const isOwner = user?.roles.includes("knowledge_owner") || user?.roles.includes("admin");

  const [spaceKey, setSpaceKey] = useState("");
  const [spaceName, setSpaceName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SyncResult | null>(null);

  useEffect(() => {
    if (!getToken()) router.push("/login");
  }, [router]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setResult(null);
    setLoading(true);
    try {
      const syncResult = await api.syncConfluenceSpace(spaceKey, spaceName, baseUrl);
      setResult(syncResult);
    } catch (err) {
      if (!redirectIfUnauthorized(err, router)) {
        setError(err instanceof ApiError ? err.message : String(err));
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <NavBar />
      <main className="mx-auto max-w-2xl px-6 py-8">
        <h1 className="text-xl font-semibold text-gray-900">Sources</h1>
        <p className="mt-1 text-sm text-gray-500">
          Connect a Confluence space and ingest its pages. Re-syncing is incremental — only
          pages whose Confluence version has changed are re-ingested.
        </p>

        {!isOwner && (
          <p className="mt-4 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
            Connecting a source requires the Knowledge Owner or Admin role.
          </p>
        )}

        <form onSubmit={handleSubmit} className="mt-6 space-y-4 rounded-lg border border-gray-200 bg-white p-6">
          <Field
            label="Space key"
            value={spaceKey}
            onChange={setSpaceKey}
            placeholder="LOG"
            disabled={!isOwner}
          />
          <Field
            label="Space name"
            value={spaceName}
            onChange={setSpaceName}
            placeholder="Logistics"
            disabled={!isOwner}
          />
          <Field
            label="Confluence base URL"
            value={baseUrl}
            onChange={setBaseUrl}
            placeholder="https://your-domain.atlassian.net"
            disabled={!isOwner}
          />
          <p className="text-xs text-gray-400">
            Uses the API token configured server-side (CONFLUENCE_API_TOKEN) — credentials aren&apos;t
            entered here.
          </p>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <button
            type="submit"
            disabled={loading || !isOwner}
            className="rounded bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-700 disabled:opacity-50"
          >
            {loading ? "Syncing..." : "Connect & Sync"}
          </button>
        </form>

        {result && (
          <div className="mt-6 rounded-lg border border-green-200 bg-green-50 p-5 text-sm text-green-900">
            <p className="font-medium">Synced space &quot;{result.space_key}&quot;</p>
            <ul className="mt-2 space-y-1">
              <li>Pages created: {result.pages_created}</li>
              <li>Pages updated: {result.pages_updated}</li>
              <li>Pages unchanged (skipped): {result.pages_skipped_unchanged}</li>
            </ul>
          </div>
        )}
      </main>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
  disabled,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  disabled?: boolean;
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700">{label}</label>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        required
        disabled={disabled}
        className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm disabled:bg-gray-100"
      />
    </div>
  );
}
