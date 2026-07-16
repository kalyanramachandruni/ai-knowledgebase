"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { NavBar } from "@/components/NavBar";
import { api, ApiError } from "@/lib/api";
import { getToken, getUser, redirectIfUnauthorized } from "@/lib/auth";
import type { ConfluencePage, ConfluencePageDetail, ConfluenceSpace, ExtractionRun, CompiledProductSummary } from "@/lib/types";

interface SyncResult {
  space_key: string;
  pages_created: number;
  pages_updated: number;
  pages_skipped_unchanged: number;
}

type Tab = "connect" | "pages";
type PageStatus = "idle" | "extracting" | "extracted" | "reused" | "compiling" | "compiled" | "failed";

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
  const [spaces, setSpaces] = useState<ConfluenceSpace[]>([]);
  const [loadingSpaces, setLoadingSpaces] = useState(true);

  // Form state — used for both "connect new" and "resync existing"
  const [formSpaceKey, setFormSpaceKey] = useState("");
  const [formSpaceName, setFormSpaceName] = useState("");
  const [formBaseUrl, setFormBaseUrl] = useState("");
  const [syncing, setSyncing] = useState<string | null>(null); // space_key being synced, or "new"
  const [formError, setFormError] = useState<string | null>(null);
  const [syncResults, setSyncResults] = useState<Record<string, SyncResult>>({});

  function loadSpaces() {
    setLoadingSpaces(true);
    api.listConfluenceSpaces()
      .then(setSpaces)
      .catch(() => {})
      .finally(() => setLoadingSpaces(false));
  }

  useEffect(() => { loadSpaces(); }, []);

  async function handleSync(e: React.FormEvent, spaceKey: string, spaceName: string, baseUrl: string) {
    e.preventDefault();
    setFormError(null);
    setSyncing(spaceKey || "new");
    try {
      const result = await api.syncConfluenceSpace(spaceKey, spaceName, baseUrl);
      setSyncResults((prev) => ({ ...prev, [result.space_key]: result }));
      loadSpaces();
      if (!spaceKey) {
        setFormSpaceKey("");
        setFormSpaceName("");
        setFormBaseUrl("");
      }
    } catch (err) {
      if (!redirectIfUnauthorized(err, router)) {
        setFormError(err instanceof ApiError ? err.message : String(err));
      }
    } finally {
      setSyncing(null);
    }
  }

  function fmt(dt: string | null) {
    if (!dt) return "—";
    return new Date(dt).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  }

  return (
    <>
      {!isOwner && (
        <p className="mb-4 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          Connecting a source requires the Knowledge Owner or Admin role.
        </p>
      )}

      {/* Connect new space form */}
      {isOwner && (
        <>
          <h2 className="mb-3 text-sm font-semibold text-gray-700">
            {spaces.length > 0 ? "Connect a new space" : "Connect space"}
          </h2>
          <form
            onSubmit={(e) => handleSync(e, formSpaceKey, formSpaceName, formBaseUrl)}
            className="mb-8 space-y-4 rounded-lg border border-gray-200 bg-white p-6"
          >
            <Field label="Space key" value={formSpaceKey} onChange={setFormSpaceKey} placeholder="LOG" disabled={!!syncing} />
            <Field label="Space name" value={formSpaceName} onChange={setFormSpaceName} placeholder="Logistics" disabled={!!syncing} />
            <Field
              label="Confluence base URL"
              value={formBaseUrl}
              onChange={setFormBaseUrl}
              placeholder="https://api.atlassian.com/ex/confluence/{cloudId}/wiki/rest/api"
              disabled={!!syncing}
            />
            <p className="text-xs text-gray-400">
              Uses the API token configured server-side (CONFLUENCE_API_TOKEN) — credentials aren&apos;t entered here.
            </p>
            {formError && <p className="text-sm text-red-600">{formError}</p>}
            <button
              type="submit"
              disabled={!!syncing}
              className="rounded bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-700 disabled:opacity-50"
            >
              {syncing === "new" ? "Syncing..." : "Connect & Sync"}
            </button>
          </form>
        </>
      )}

      {/* Synced spaces list */}
      {!loadingSpaces && spaces.length > 0 && (
        <div className="mb-8">
          <h2 className="mb-3 text-sm font-semibold text-gray-700">Synced spaces</h2>
          <div className="space-y-3">
            {spaces.map((space) => {
              const result = syncResults[space.space_key];
              const isSyncing = syncing === space.space_key;
              return (
                <div key={space.id} className="rounded-lg border border-gray-200 bg-white p-5">
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="rounded bg-gray-100 px-2 py-0.5 font-mono text-xs text-gray-600">
                          {space.space_key}
                        </span>
                        <span className="font-medium text-gray-900">{space.name}</span>
                      </div>
                      <p className="mt-1 truncate text-xs text-gray-400">{space.base_url}</p>
                      <div className="mt-2 flex flex-wrap gap-4 text-xs text-gray-500">
                        <span>Last synced: <span className="text-gray-700">{fmt(space.last_synced_at)}</span></span>
                        <span>Pages: <span className="text-gray-700">{space.page_count}</span></span>
                        {space.last_sync_created != null && (
                          <>
                            <span>Created: <span className="text-green-700">{space.last_sync_created}</span></span>
                            <span>Updated: <span className="text-blue-700">{space.last_sync_updated ?? 0}</span></span>
                            <span>Skipped: <span className="text-gray-600">{space.last_sync_skipped ?? 0}</span></span>
                          </>
                        )}
                      </div>
                      {result && (
                        <div className="mt-2 rounded border border-green-200 bg-green-50 px-3 py-2 text-xs text-green-800">
                          Sync complete — created {result.pages_created}, updated {result.pages_updated}, skipped {result.pages_skipped_unchanged}
                        </div>
                      )}
                    </div>
                    {isOwner && (
                      <form
                        onSubmit={(e) => handleSync(e, space.space_key, space.name, space.base_url)}
                        className="shrink-0"
                      >
                        <button
                          type="submit"
                          disabled={!!syncing}
                          className="rounded border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                        >
                          {isSyncing ? "Syncing..." : "Resync"}
                        </button>
                      </form>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {!isOwner && spaces.length === 0 && !loadingSpaces && (
        <p className="text-sm text-gray-500">No spaces connected yet.</p>
      )}
    </>
  );
}

function PagesTab({ isOwner, router, user }: { isOwner: boolean; router: ReturnType<typeof useRouter>; user: ReturnType<typeof getUser> }) {
  const [spaces, setSpaces] = useState<ConfluenceSpace[]>([]);
  const [selectedSpace, setSelectedSpace] = useState<string>("");
  const [pages, setPages] = useState<ConfluencePage[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [pageDetails, setPageDetails] = useState<Record<string, ConfluencePageDetail | null>>({});
  const [loadingDetail, setLoadingDetail] = useState<Record<string, boolean>>({});
  const [runs, setRuns] = useState<Record<string, ExtractionRun>>({});
  const [search, setSearch] = useState("");
  const [pageStatus, setPageStatus] = useState<Record<string, PageStatus>>({});

  // Space-level action state
  const [extracting, setExtracting] = useState(false);
  const [compiling, setCompiling] = useState(false);
  const [compileProductKey, setCompileProductKey] = useState("");
  const [compileProductName, setCompileProductName] = useState("");
  const [compileOwner, setCompileOwner] = useState("");
  const [productIndex, setProductIndex] = useState<Record<string, { name: string; owner: string }>>({});
  const [compileResult, setCompileResult] = useState<{ product_key: string; name: string; semver: string } | null>(null);

  useEffect(() => {
    api.listConfluenceSpaces().then(setSpaces).catch(() => {});
    api.listProducts().then((products) => {
      const idx: Record<string, { name: string; owner: string }> = {};
      products.forEach((p) => { idx[p.product_key] = { name: p.name, owner: p.owner }; });
      setProductIndex(idx);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    setPages(null);
    setRuns({});
    setPageStatus({});
    setCompileResult(null);
    if (!selectedSpace && spaces.length === 0) return;
    api.listConfluencePages(selectedSpace || undefined)
      .then(async (fetchedPages) => {
        setPages(fetchedPages);
        const historyMap = await api.getBulkExtractionHistory(selectedSpace || undefined)
          .catch(() => ({} as Record<string, ExtractionRun[]>));
        const newRuns: Record<string, ExtractionRun> = {};
        fetchedPages.forEach((p) => {
          const pageRuns = historyMap[p.id] ?? [];
          if (pageRuns.length > 0) newRuns[p.id] = pageRuns[0];
        });
        setRuns(newRuns);
      })
      .catch((err) => {
        if (!redirectIfUnauthorized(err, router)) setError(String(err));
      });
  }, [selectedSpace, router, spaces.length]);

  async function handleToggleContent(pageId: string) {
    const next = !expanded[pageId];
    setExpanded((e) => ({ ...e, [pageId]: next }));
    if (next && pageDetails[pageId] === undefined) {
      setLoadingDetail((l) => ({ ...l, [pageId]: true }));
      try {
        const detail = await api.getConfluencePage(pageId);
        setPageDetails((d) => ({ ...d, [pageId]: detail }));
      } catch {
        setPageDetails((d) => ({ ...d, [pageId]: null }));
      } finally {
        setLoadingDetail((l) => ({ ...l, [pageId]: false }));
      }
    }
  }

  async function handleExtractAll() {
    if (!pages) return;
    setExtracting(true);
    setError(null);
    setCompileResult(null);
    const toProcess = filtered; // respect current search filter
    for (const page of toProcess) {
      setPageStatus((s) => ({ ...s, [page.id]: "extracting" }));
      try {
        const run = await api.smartExtractPage(page.id);
        setRuns((r) => ({ ...r, [page.id]: run }));
        if (run.status === "failed") {
          setPageStatus((s) => ({ ...s, [page.id]: "failed" }));
        } else {
          setPageStatus((s) => ({ ...s, [page.id]: run.reused ? "reused" : "extracted" }));
        }
      } catch {
        setPageStatus((s) => ({ ...s, [page.id]: "failed" }));
      }
    }
    setExtracting(false);
  }

  async function handleCompilePending() {
    if (!selectedSpace) { setError("Select a space first."); return; }
    if (!compileProductKey || !compileProductName || !compileOwner) {
      setError("Fill in Product Key, Product Name, and Owner before compiling.");
      return;
    }
    const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    if (!user?.user_id || !uuidPattern.test(user.user_id)) {
      router.push("/login");
      return;
    }

    setCompiling(true);
    setError(null);
    setCompileResult(null);

    try {
      // Fetch which runs still need compile for this space
      const pending = await api.getPendingCompileRuns(selectedSpace);
      if (pending.length === 0) {
        setError("No pages pending compile — all extracted pages are already up to date.");
        setCompiling(false);
        return;
      }

      // Mark each page as compiling
      pending.forEach(({ page_id }) => {
        setPageStatus((s) => ({ ...s, [page_id]: "compiling" }));
      });

      const product = await api.batchCompile({
        run_ids: pending.map((p) => p.run_id),
        product_key: compileProductKey,
        name: compileProductName,
        owner: compileOwner,
        created_by: user.user_id,
      });

      // Refresh history for all pages to get updated compile info
      const historyMap = await api.getBulkExtractionHistory(selectedSpace).catch(() => ({} as Record<string, ExtractionRun[]>));
      const newRuns: Record<string, ExtractionRun> = {};
      (pages ?? []).forEach((p) => {
        const pageRuns = historyMap[p.id] ?? [];
        if (pageRuns.length > 0) newRuns[p.id] = pageRuns[0];
      });
      setRuns(newRuns);

      pending.forEach(({ page_id }) => {
        setPageStatus((s) => ({ ...s, [page_id]: "compiled" }));
      });

      setCompileResult({
        product_key: product.product_key,
        name: product.name,
        semver: product.current_version.semver,
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Compile failed");
      // Revert compiling pages back to extracted
      setPageStatus((s) => {
        const next = { ...s };
        Object.keys(next).forEach((id) => { if (next[id] === "compiling") next[id] = "failed"; });
        return next;
      });
    }
    setCompiling(false);
  }

  const filtered = (pages ?? []).filter((p) =>
    !search || p.title.toLowerCase().includes(search.toLowerCase())
  );

  const pendingExtractCount = filtered.filter((p) => {
    const run = runs[p.id];
    return !run || run.status === "failed";
  }).length;

  const pendingCompileCount = filtered.filter((p) => {
    const run = runs[p.id];
    return run && run.status === "succeeded" && !run.compiled_at && !run.compile_status;
  }).length;

  if (!pages) return <p className="text-sm text-gray-500">Loading pages...</p>;

  return (
    <>
      {error && <p className="mb-3 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      {compileResult && (
        <div className="mb-4 rounded border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-900">
          Compiled into <strong>{compileResult.name}</strong> — version <strong>{compileResult.semver}</strong>
        </div>
      )}

      {/* Filters */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <select
          value={selectedSpace}
          onChange={(e) => { setSelectedSpace(e.target.value); setSearch(""); }}
          className="rounded border border-gray-300 px-3 py-2 text-sm bg-white"
        >
          <option value="">All spaces</option>
          {spaces.map((s) => (
            <option key={s.id} value={s.space_key}>{s.name} ({s.space_key})</option>
          ))}
        </select>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search pages..."
          className="w-full max-w-xs rounded border border-gray-300 px-3 py-2 text-sm"
        />
        <span className="text-sm text-gray-500">{filtered.length} pages</span>
      </div>

      {/* Space-level action panel */}
      {isOwner && selectedSpace && filtered.length > 0 && (
        <div className="mb-5 rounded-lg border border-gray-200 bg-white p-4 space-y-4">
          <div className="flex flex-wrap gap-3 items-center">
            <div>
              <p className="text-xs font-medium text-gray-700 mb-1">Step 1 — Extract</p>
              <button
                onClick={handleExtractAll}
                disabled={extracting || compiling}
                className="rounded bg-gray-900 px-4 py-1.5 text-xs font-medium text-white hover:bg-gray-700 disabled:opacity-50"
              >
                {extracting ? "Extracting…" : `Extract All ${filtered.length} Pages`}
              </button>
              {pendingExtractCount > 0 && !extracting && (
                <p className="mt-1 text-xs text-amber-700">{pendingExtractCount} page{pendingExtractCount !== 1 ? "s" : ""} not yet extracted</p>
              )}
            </div>
            <div className="w-px h-10 bg-gray-200 hidden sm:block" />
            <div className="flex-1 min-w-0">
              <p className="text-xs font-medium text-gray-700 mb-1">Step 2 — Compile Pending Pages → KP</p>
              <div className="flex flex-wrap gap-2 items-center">
                <input
                  value={compileProductKey}
                  onChange={(e) => setCompileProductKey(e.target.value)}
                  onBlur={() => {
                    const match = productIndex[compileProductKey.trim()];
                    if (match) {
                      if (!compileProductName) setCompileProductName(match.name);
                      if (!compileOwner) setCompileOwner(match.owner);
                    }
                  }}
                  placeholder="product-key"
                  className="rounded border border-gray-300 px-2 py-1 text-xs w-32"
                />
                <input value={compileProductName} onChange={(e) => setCompileProductName(e.target.value)}
                  placeholder="Product name" className="rounded border border-gray-300 px-2 py-1 text-xs w-40" />
                <input value={compileOwner} onChange={(e) => setCompileOwner(e.target.value)}
                  placeholder="Owner" className="rounded border border-gray-300 px-2 py-1 text-xs w-28" />
                <button
                  onClick={handleCompilePending}
                  disabled={extracting || compiling}
                  className="rounded bg-blue-700 px-4 py-1.5 text-xs font-medium text-white hover:bg-blue-800 disabled:opacity-50"
                >
                  {compiling ? "Compiling…" : `Compile Pending (${pendingCompileCount})`}
                </button>
              </div>
              <p className="mt-1 text-xs text-gray-400">Only compiles pages with new extractions since last compile.</p>
            </div>
          </div>
        </div>
      )}

      {/* Page list */}
      <div className="space-y-3">
        {filtered.map((page) => {
          const run = runs[page.id];
          const status = pageStatus[page.id];
          return (
            <PageCard
              key={page.id}
              page={page}
              run={run ?? null}
              status={status ?? "idle"}
              expanded={!!expanded[page.id]}
              loadingDetail={!!loadingDetail[page.id]}
              pageDetail={pageDetails[page.id] ?? null}
              onToggleContent={() => handleToggleContent(page.id)}
              onNavigate={(id) => router.push(`/products/${id}`)}
            />
          );
        })}

        {filtered.length === 0 && (
          <p className="text-sm text-gray-500">
            {(pages ?? []).length === 0 ? "No pages synced yet. Connect a space first." : "No pages match your search."}
          </p>
        )}
      </div>
    </>
  );
}

function statusBadge(status: string) {
  const map: Record<string, string> = {
    succeeded: "bg-green-100 text-green-800",
    failed: "bg-red-100 text-red-800",
    running: "bg-yellow-100 text-yellow-800",
    pending: "bg-gray-100 text-gray-700",
    extracting: "bg-yellow-100 text-yellow-800",
    extracted: "bg-blue-100 text-blue-800",
    reused: "bg-purple-100 text-purple-800",
    compiling: "bg-yellow-100 text-yellow-800",
    compiled: "bg-green-100 text-green-800",
  };
  return map[status] ?? "bg-gray-100 text-gray-600";
}

function fmt(iso: string | null | undefined) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function shortId(id: string) {
  return id.slice(0, 8) + "…";
}

interface PageCardProps {
  page: ConfluencePage;
  run: ExtractionRun | null;
  status: PageStatus;
  expanded: boolean;
  loadingDetail: boolean;
  pageDetail: ConfluencePageDetail | null;
  onToggleContent: () => void;
  onNavigate: (productId: string) => void;
}

function PageCard({ page, run, status, expanded, loadingDetail, pageDetail, onToggleContent, onNavigate }: PageCardProps) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-gray-900">{page.title}</p>
          <p className="text-xs text-gray-400 mt-0.5">
            {page.space_key} · Page v{page.confluence_version} · modified {fmt(page.last_modified_at)}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {status !== "idle" && (
            <span className={`rounded px-2 py-0.5 text-xs font-medium ${statusBadge(status)}`}>
              {status === "extracting" ? "Extracting…" :
               status === "extracted" ? "Extracted" :
               status === "reused" ? "Reused (cached)" :
               status === "compiling" ? "Compiling…" :
               status === "compiled" ? "Compiled" : "Failed"}
            </span>
          )}
          <button
            onClick={onToggleContent}
            className="rounded border border-gray-200 px-2 py-1 text-xs text-gray-500 hover:bg-gray-50"
          >
            {expanded ? "▲ Hide" : "▼ Content"}
          </button>
        </div>
      </div>

      {/* Page content preview */}
      {expanded && (
        <div className="mt-3 border-t border-gray-100 pt-3">
          {loadingDetail ? (
            <p className="text-xs text-gray-400">Loading content…</p>
          ) : pageDetail === null ? (
            <p className="text-xs text-red-500">Failed to load content.</p>
          ) : pageDetail ? (
            <pre className="whitespace-pre-wrap text-xs text-gray-700 font-sans leading-relaxed max-h-48 overflow-y-auto">
              {pageDetail.plain_text || "(no text content)"}
            </pre>
          ) : null}
        </div>
      )}

      {/* Extraction + Compile info boxes */}
      {run && (
        <div className="mt-3 border-t border-gray-100 pt-3 grid grid-cols-1 sm:grid-cols-2 gap-3">
          {/* Extraction box */}
          <div className="rounded border border-gray-100 bg-gray-50 px-3 py-2 text-xs space-y-1">
            <p className="font-medium text-gray-700 text-[11px] uppercase tracking-wide">Last Extraction</p>
            <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
              <span className={`rounded px-1.5 py-0.5 font-medium ${statusBadge(run.status)}`}>{run.status}</span>
              <span className="text-gray-500 font-mono">{shortId(run.id)}</span>
            </div>
            <p className="text-gray-500">{fmt(run.started_at)}</p>
            {run.status === "failed" && run.error_message && (
              <p className="text-red-600 mt-1 break-words">{run.error_message}</p>
            )}
          </div>

          {/* Compile box */}
          <CompileBox run={run} onNavigate={onNavigate} />
        </div>
      )}
    </div>
  );
}

function CompileBox({ run, onNavigate }: { run: ExtractionRun; onNavigate: (id: string) => void }) {
  const hasAnyCompile = run.compile_status || run.compiled_at;
  const latestSucceeded = run.compile_status === "succeeded";
  const latestFailed = run.compile_status === "failed";
  const neverCompiled = !hasAnyCompile;

  const compiledProduct = run.compiled_product;
  const prevProduct = run.prev_compiled_product;

  return (
    <div className="rounded border border-gray-100 bg-gray-50 px-3 py-2 text-xs space-y-1">
      <p className="font-medium text-gray-700 text-[11px] uppercase tracking-wide">Compile Status</p>

      {neverCompiled && (
        <p className="text-gray-400 italic">Not yet compiled</p>
      )}

      {latestSucceeded && compiledProduct && (
        <>
          <div className="flex items-center gap-1.5">
            <span className="rounded px-1.5 py-0.5 font-medium bg-green-100 text-green-800">succeeded</span>
            <button
              onClick={() => onNavigate(compiledProduct.product_id)}
              className="text-blue-600 hover:underline font-medium"
            >
              {compiledProduct.name} v{compiledProduct.semver}
            </button>
          </div>
          <p className="text-gray-500">{fmt(run.compiled_at)}</p>
        </>
      )}

      {latestFailed && (
        <>
          <div className="flex items-center gap-1.5">
            <span className="rounded px-1.5 py-0.5 font-medium bg-red-100 text-red-800">failed</span>
            <span className="text-red-600">{fmt(run.compiled_at)}</span>
          </div>
          {run.compile_error && (
            <p className="text-red-600 break-words">{run.compile_error}</p>
          )}
          {prevProduct && (
            <div className="mt-2 border-t border-gray-200 pt-2">
              <p className="text-gray-500 text-[11px]">Previously compiled:</p>
              <div className="flex items-center gap-1.5 mt-0.5">
                <span className="rounded px-1.5 py-0.5 font-medium bg-green-100 text-green-800">succeeded</span>
                <button
                  onClick={() => onNavigate(prevProduct.product_id)}
                  className="text-blue-600 hover:underline"
                >
                  {prevProduct.name} v{prevProduct.semver}
                </button>
              </div>
              <p className="text-gray-500">{fmt(run.prev_compiled_at)}</p>
            </div>
          )}
        </>
      )}
    </div>
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
