"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { NavBar } from "@/components/NavBar";
import { api, ApiError } from "@/lib/api";
import { getToken, getUser, redirectIfUnauthorized } from "@/lib/auth";
import type { ConfluencePage, ExtractionRun, KnowledgeProduct } from "@/lib/types";

interface SyncResult {
  space_key: string;
  pages_created: number;
  pages_updated: number;
  pages_skipped_unchanged: number;
}

type Tab = "connect" | "pages";

export default function SourcesPage() {
  const router = useRouter();
  const user = getUser();
  const isOwner = user?.roles.includes("knowledge_owner") || user?.roles.includes("admin");
  const [tab, setTab] = useState<Tab>("connect");

  useEffect(() => {
    if (!getToken()) router.push("/login");
  }, [router]);

  return (
    <div className="min-h-screen bg-gray-50">
      <NavBar />
      <main className="mx-auto max-w-4xl px-6 py-8">
        <h1 className="text-xl font-semibold text-gray-900">Sources</h1>
        <p className="mt-1 text-sm text-gray-500">
          Connect Confluence spaces and extract Knowledge Products from ingested pages.
        </p>

        <div className="mt-6 flex border-b border-gray-200">
          <TabBtn active={tab === "connect"} onClick={() => setTab("connect")}>Connect Space</TabBtn>
          <TabBtn active={tab === "pages"} onClick={() => setTab("pages")}>Ingested Pages</TabBtn>
        </div>

        <div className="mt-6">
          {tab === "connect" ? (
            <ConnectTab isOwner={!!isOwner} router={router} />
          ) : (
            <PagesTab isOwner={!!isOwner} router={router} user={user} />
          )}
        </div>
      </main>
    </div>
  );
}

function TabBtn({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px ${
        active ? "border-gray-900 text-gray-900" : "border-transparent text-gray-500 hover:text-gray-700"
      }`}
    >
      {children}
    </button>
  );
}

function ConnectTab({ isOwner, router }: { isOwner: boolean; router: ReturnType<typeof useRouter> }) {
  const [spaceKey, setSpaceKey] = useState("");
  const [spaceName, setSpaceName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SyncResult | null>(null);

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
    <>
      {!isOwner && (
        <p className="mb-4 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          Connecting a source requires the Knowledge Owner or Admin role.
        </p>
      )}
      <form onSubmit={handleSubmit} className="space-y-4 rounded-lg border border-gray-200 bg-white p-6">
        <Field label="Space key" value={spaceKey} onChange={setSpaceKey} placeholder="LOG" disabled={!isOwner} />
        <Field label="Space name" value={spaceName} onChange={setSpaceName} placeholder="Logistics" disabled={!isOwner} />
        <Field
          label="Confluence base URL"
          value={baseUrl}
          onChange={setBaseUrl}
          placeholder="https://api.atlassian.com/ex/confluence/{cloudId}/wiki/rest/api"
          disabled={!isOwner}
        />
        <p className="text-xs text-gray-400">
          Uses the API token configured server-side (CONFLUENCE_API_TOKEN) — credentials aren&apos;t entered here.
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
    </>
  );
}

function PagesTab({ isOwner, router, user }: { isOwner: boolean; router: ReturnType<typeof useRouter>; user: ReturnType<typeof getUser> }) {
  const [pages, setPages] = useState<ConfluencePage[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [extracting, setExtracting] = useState<Record<string, boolean>>({});
  const [runs, setRuns] = useState<Record<string, ExtractionRun>>({});
  const [compiling, setCompiling] = useState<Record<string, boolean>>({});
  const [compiled, setCompiled] = useState<Record<string, KnowledgeProduct>>({});
  const [compileForm, setCompileForm] = useState<Record<string, { name: string; key: string; owner: string }>>({});
  const [search, setSearch] = useState("");

  useEffect(() => {
    api.listConfluencePages()
      .then(setPages)
      .catch((err) => {
        if (!redirectIfUnauthorized(err, router)) setError(String(err));
      });
  }, [router]);

  async function handleExtract(pageId: string) {
    setExtracting((e) => ({ ...e, [pageId]: true }));
    try {
      const run = await api.extractPage(pageId);
      setRuns((r) => ({ ...r, [pageId]: run }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setExtracting((e) => ({ ...e, [pageId]: false }));
    }
  }

  async function handleCompile(pageId: string, runId: string) {
    const form = compileForm[pageId] ?? { name: "", key: "", owner: "" };
    if (!form.name || !form.key || !form.owner) {
      setError("Fill in product name, key, and owner before compiling.");
      return;
    }
    if (!user?.user_id) {
      setError("Not logged in.");
      return;
    }
    setCompiling((c) => ({ ...c, [pageId]: true }));
    setError(null);
    try {
      const product = await api.compileExtraction(runId, {
        product_key: form.key,
        name: form.name,
        owner: form.owner,
        created_by: user.user_id,
      });
      setCompiled((c) => ({ ...c, [pageId]: product }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setCompiling((c) => ({ ...c, [pageId]: false }));
    }
  }

  const filtered = pages?.filter((p) =>
    p.title.toLowerCase().includes(search.toLowerCase())
  ) ?? [];

  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!pages) return <p className="text-sm text-gray-500">Loading pages...</p>;

  return (
    <>
      <div className="mb-4 flex items-center gap-3">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search pages..."
          className="w-full max-w-sm rounded border border-gray-300 px-3 py-2 text-sm"
        />
        <span className="text-sm text-gray-500">{filtered.length} pages</span>
      </div>

      <div className="space-y-3">
        {filtered.map((page) => {
          const run = runs[page.id];
          const product = compiled[page.id];
          const form = compileForm[page.id] ?? { name: page.title, key: page.title.toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 40), owner: user?.display_name ?? "" };

          return (
            <div key={page.id} className="rounded-lg border border-gray-200 bg-white p-4">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-sm font-medium text-gray-900">{page.title}</p>
                  <p className="text-xs text-gray-400 mt-0.5">
                    v{page.confluence_version} · {new Date(page.last_modified_at).toLocaleDateString()}
                  </p>
                </div>
                {isOwner && !run && (
                  <button
                    onClick={() => handleExtract(page.id)}
                    disabled={extracting[page.id]}
                    className="shrink-0 rounded border border-gray-300 px-3 py-1 text-xs font-medium hover:bg-gray-50 disabled:opacity-50"
                  >
                    {extracting[page.id] ? "Extracting..." : "Extract"}
                  </button>
                )}
              </div>

              {run && (
                <div className="mt-3 border-t border-gray-100 pt-3">
                  <div className="flex items-center gap-2">
                    <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${
                      run.status === "succeeded" ? "bg-green-100 text-green-800" :
                      run.status === "failed" ? "bg-red-100 text-red-800" :
                      "bg-yellow-100 text-yellow-800"
                    }`}>
                      {run.status}
                    </span>
                    <span className="text-xs text-gray-400">{run.llm_model}</span>
                  </div>

                  {run.status === "failed" && run.error_message && (
                    <p className="mt-1 text-xs text-red-600">{run.error_message}</p>
                  )}

                  {run.status === "succeeded" && !product && (
                    <div className="mt-3 space-y-2">
                      <p className="text-xs font-medium text-gray-700">Compile into Knowledge Product</p>
                      <div className="grid grid-cols-3 gap-2">
                        <input
                          value={form.name}
                          onChange={(e) => setCompileForm((f) => ({ ...f, [page.id]: { ...form, name: e.target.value } }))}
                          placeholder="Product name"
                          className="rounded border border-gray-300 px-2 py-1 text-xs"
                        />
                        <input
                          value={form.key}
                          onChange={(e) => setCompileForm((f) => ({ ...f, [page.id]: { ...form, key: e.target.value } }))}
                          placeholder="product-key"
                          className="rounded border border-gray-300 px-2 py-1 text-xs"
                        />
                        <input
                          value={form.owner}
                          onChange={(e) => setCompileForm((f) => ({ ...f, [page.id]: { ...form, owner: e.target.value } }))}
                          placeholder="Owner"
                          className="rounded border border-gray-300 px-2 py-1 text-xs"
                        />
                      </div>
                      <button
                        onClick={() => handleCompile(page.id, run.id)}
                        disabled={compiling[page.id]}
                        className="rounded bg-gray-900 px-3 py-1 text-xs font-medium text-white hover:bg-gray-700 disabled:opacity-50"
                      >
                        {compiling[page.id] ? "Compiling..." : "Compile → Knowledge Product"}
                      </button>
                    </div>
                  )}

                  {product && (
                    <div className="mt-2 flex items-center gap-2">
                      <span className="text-xs text-green-700 font-medium">✓ Created:</span>
                      <button
                        onClick={() => router.push(`/products/${product.id}`)}
                        className="text-xs text-blue-600 hover:underline"
                      >
                        {product.name} (v{product.current_version.semver})
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}

        {filtered.length === 0 && (
          <p className="text-sm text-gray-500">
            {pages.length === 0 ? "No pages synced yet. Connect a space first." : "No pages match your search."}
          </p>
        )}
      </div>
    </>
  );
}

function Field({
  label, value, onChange, placeholder, disabled,
}: {
  label: string; value: string; onChange: (v: string) => void; placeholder?: string; disabled?: boolean;
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
