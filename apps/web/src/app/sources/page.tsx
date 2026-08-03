"use client";

import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { NavBar } from "@/components/NavBar";
import { api, ApiError } from "@/lib/api";
import { getToken, getUser, redirectIfUnauthorized } from "@/lib/auth";
import type { ConfluencePage, ConfluencePageDetail, ConfluenceSpace, ExtractionRun, CompiledProductSummary, WebPageLink } from "@/lib/types";

interface SyncResult {
  space_key: string;
  pages_created: number;
  pages_updated: number;
  pages_skipped_unchanged: number;
}

type Tab = "connect" | "pages" | "web";
type PageStatus = "idle" | "extracting" | "extracted" | "reused" | "compiling" | "compiled" | "failed" | "discarded";

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
      <main className="mx-auto max-w-7xl px-6 py-8">
        <h1 className="text-xl font-semibold text-gray-900">Sources</h1>
        <p className="mt-1 text-sm text-gray-500">
          Connect Confluence spaces and extract Knowledge Products from ingested pages.
        </p>

        <div className="mt-6 flex border-b border-gray-200">
          <TabBtn active={tab === "connect"} onClick={() => setTab("connect")}>Connect Space</TabBtn>
          <TabBtn active={tab === "pages"} onClick={() => setTab("pages")}>Ingested Pages</TabBtn>
          <TabBtn active={tab === "web"} onClick={() => setTab("web")}>Web Wikis</TabBtn>
        </div>

        <div className="mt-6">
          {tab === "connect" ? (
            <ConnectTab isOwner={!!isOwner} router={router} />
          ) : tab === "pages" ? (
            <PagesTab isOwner={!!isOwner} router={router} user={user} />
          ) : (
            <WebWikisTab isOwner={!!isOwner} />
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
  const [forceCompileAll, setForceCompileAll] = useState(false);
  const [selectedPages, setSelectedPages] = useState<Set<string>>(new Set());

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
    setSelectedPages(new Set());
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
      let pending: Array<{ page_id: string; run_id: string }>;
      if (selectedPages.size > 0) {
        // Individual selection takes priority
        pending = filtered
          .filter((p) => selectedPages.has(p.id) && runs[p.id]?.status === "succeeded")
          .map((p) => ({ page_id: p.id, run_id: runs[p.id].id }));
      } else if (forceCompileAll) {
        pending = filtered
          .filter((p) => runs[p.id]?.status === "succeeded")
          .map((p) => ({ page_id: p.id, run_id: runs[p.id].id }));
      } else {
        pending = await api.getPendingCompileRuns(selectedSpace);
      }

      if (pending.length === 0) {
        setError(selectedPages.size > 0
          ? "None of the selected pages have a succeeded extraction."
          : "No pages pending compile — all extracted pages are already up to date.");
        setCompiling(false);
        return;
      }

      // Stream SSE compile progress — updates each page status in real time
      const token = getToken();
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/v1/extraction-runs/batch-compile-stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          items: pending.map((p) => ({ run_id: p.run_id, page_id: p.page_id })),
          product_key: compileProductKey,
          name: compileProductName,
          owner: compileOwner,
          created_by: user.user_id,
          force: forceCompileAll,
        }),
      });

      if (!res.ok || !res.body) {
        throw new Error(await res.text());
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let errorMessage: string | null = null;

      // Read the full stream line by line
      outer: while (true) {
        const { done, value } = await reader.read();
        if (value) buffer += decoder.decode(value, { stream: !done });
        if (done) break;

        // Process all complete SSE messages (delimited by \n\n)
        let boundary: number;
        while ((boundary = buffer.indexOf("\n\n")) !== -1) {
          const message = buffer.slice(0, boundary).trim();
          buffer = buffer.slice(boundary + 2);

          if (!message.startsWith("data:")) continue;
          let event: Record<string, unknown>;
          try { event = JSON.parse(message.slice(5).trim()); } catch { continue; }

          console.log("[compile-stream] event:", event.type, event);
          if (event.type === "merging" && typeof event.page_id === "string") {
            setPageStatus((s) => ({ ...s, [event.page_id as string]: "compiling" }));
          } else if (event.type === "discarded" && typeof event.page_id === "string") {
            setPageStatus((s) => ({ ...s, [event.page_id as string]: "discarded" }));
          } else if (event.type === "skipped" && typeof event.page_id === "string") {
            setPageStatus((s) => ({ ...s, [event.page_id as string]: "failed" }));
          } else if (event.type === "page_compiled" && typeof event.page_id === "string") {
            setPageStatus((s) => ({ ...s, [event.page_id as string]: "compiled" }));
            setCompileResult({
              product_key: event.product_key as string,
              name: event.name as string,
              semver: event.semver as string,
            });
          } else if (event.type === "page_error" && typeof event.page_id === "string") {
            setPageStatus((s) => ({ ...s, [event.page_id as string]: "failed" }));
          } else if (event.type === "done") {
            console.log("[compile-stream] done received");
            break outer;
          } else if (event.type === "error") {
            console.error("[compile-stream] server error:", event.message);
            errorMessage = event.message as string;
            break outer;
          }
        }
      }

      // Refresh run history after stream closes
      const historyMap = await api.getBulkExtractionHistory(selectedSpace).catch(() => ({} as Record<string, ExtractionRun[]>));
      const newRuns: Record<string, ExtractionRun> = {};
      (pages ?? []).forEach((p) => {
        const pageRuns = historyMap[p.id] ?? [];
        if (pageRuns.length > 0) newRuns[p.id] = pageRuns[0];
      });
      setRuns(newRuns);

      if (errorMessage) throw new Error(errorMessage);

    } catch (err) {
      setError(err instanceof Error ? err.message : "Compile failed");
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

  const allSucceededCount = filtered.filter((p) => {
    const run = runs[p.id];
    return run && run.status === "succeeded";
  }).length;

  const selectedSucceededCount = filtered.filter((p) => selectedPages.has(p.id) && runs[p.id]?.status === "succeeded").length;
  const compileCount = selectedPages.size > 0 ? selectedSucceededCount : forceCompileAll ? allSucceededCount : pendingCompileCount;
  const compileLabel = selectedPages.size > 0 ? "Selected" : forceCompileAll ? "All" : "Pending";

  const allFilteredSucceeded = filtered.filter((p) => runs[p.id]?.status === "succeeded");
  const allFilteredSelected = allFilteredSucceeded.length > 0 && allFilteredSucceeded.every((p) => selectedPages.has(p.id));
  const someFilteredSelected = allFilteredSucceeded.some((p) => selectedPages.has(p.id));

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
              <p className="text-xs font-medium text-gray-700 mb-1">Step 2 — Compile Pages → KP</p>
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
                  className={`rounded px-4 py-1.5 text-xs font-medium text-white disabled:opacity-50 ${
                    selectedPages.size > 0 ? "bg-indigo-600 hover:bg-indigo-700" :
                    forceCompileAll ? "bg-orange-600 hover:bg-orange-700" : "bg-blue-700 hover:bg-blue-800"
                  }`}
                >
                  {compiling ? "Compiling…" : `Compile ${compileLabel} (${compileCount})`}
                </button>
                {selectedPages.size > 0 && (
                  <button
                    onClick={() => setSelectedPages(new Set())}
                    className="text-xs text-gray-400 hover:text-gray-600 underline"
                  >
                    Clear selection
                  </button>
                )}
              </div>
              <div className="mt-2 flex items-center gap-4">
                <label className="flex items-center gap-1.5 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={forceCompileAll}
                    onChange={(e) => setForceCompileAll(e.target.checked)}
                    className="rounded border-gray-300 text-orange-600 focus:ring-orange-500"
                  />
                  <span className="text-xs text-gray-600">Compile All — force recompile all extracted pages in current scope</span>
                </label>
                {allFilteredSucceeded.length > 0 && (
                  <label className="flex items-center gap-1.5 cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={allFilteredSelected}
                      ref={(el) => { if (el) el.indeterminate = someFilteredSelected && !allFilteredSelected; }}
                      onChange={(e) => {
                        if (e.target.checked) {
                          setSelectedPages(new Set(allFilteredSucceeded.map((p) => p.id)));
                        } else {
                          setSelectedPages(new Set());
                        }
                      }}
                      className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                    />
                    <span className="text-xs text-gray-600">
                      Select all succeeded ({allFilteredSucceeded.length})
                    </span>
                  </label>
                )}
              </div>
              <p className="mt-1 text-xs text-gray-400">
                {selectedPages.size > 0
                  ? `${selectedPages.size} page${selectedPages.size !== 1 ? "s" : ""} selected — ${selectedSucceededCount} with succeeded extraction will be compiled.`
                  : forceCompileAll
                  ? `Force recompiling all ${allSucceededCount} extracted page${allSucceededCount !== 1 ? "s" : ""} in current scope.`
                  : "Only compiles pages with new extractions since last compile."}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Page list */}
      <div className="space-y-3">
        {filtered.map((page) => {
          const run = runs[page.id];
          const status = pageStatus[page.id];
          const isSelectable = run?.status === "succeeded";
          const isSelected = selectedPages.has(page.id);
          return (
            <div key={page.id} className="flex items-start gap-2">
              <div className="pt-3.5 pl-1">
                <input
                  type="checkbox"
                  checked={isSelected}
                  disabled={!isSelectable}
                  onChange={(e) => {
                    setSelectedPages((prev) => {
                      const next = new Set(prev);
                      if (e.target.checked) next.add(page.id);
                      else next.delete(page.id);
                      return next;
                    });
                  }}
                  className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 disabled:opacity-30 disabled:cursor-not-allowed"
                  title={isSelectable ? "Select for compile" : "No succeeded extraction"}
                />
              </div>
              <div className="flex-1 min-w-0">
                <PageCard
                  page={page}
                  run={run ?? null}
                  status={status ?? "idle"}
                  expanded={!!expanded[page.id]}
                  loadingDetail={!!loadingDetail[page.id]}
                  pageDetail={pageDetails[page.id] ?? null}
                  onToggleContent={() => handleToggleContent(page.id)}
                  onNavigate={(id) => router.push(`/products/${id}`)}
                />
              </div>
            </div>
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
    discarded: "bg-amber-100 text-amber-700",
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
               status === "compiled" ? "Compiled" :
               status === "discarded" ? "Discarded" : "Failed"}
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

// ── Web Wikis Tab ─────────────────────────────────────────────────────────────

type CrawlEvent =
  | { type: "crawling"; url: string; queued: number; visited: number }
  | { type: "page_found"; url: string; page_id: string; title: string }
  | { type: "page_updated"; url: string; page_id: string; title: string }
  | { type: "page_unchanged"; url: string; page_id: string }
  | { type: "page_skipped"; url: string; reason: string }
  | { type: "page_error"; url: string; error: string }
  | { type: "done"; created: number; updated: number; skipped: number }
  | { type: "error"; message: string };

type FilterField = "url" | "title" | "fetched" | "tags";
type FilterConnector = "AND" | "OR";
type FilterRow = { field: FilterField; pattern: string; connector: FilterConnector };

const DEFAULT_FILTER_ROW: FilterRow = { field: "url", pattern: "", connector: "AND" };

function applyPageFilters(pages: import("@/lib/types").WebPage[], rows: FilterRow[]): import("@/lib/types").WebPage[] {
  const active = rows.filter((r) => r.pattern.trim());
  if (!active.length) return pages;
  return pages.filter((pg) => {
    let result = matchFilterRow(pg, active[0]);
    for (let i = 1; i < active.length; i++) {
      result = active[i].connector === "AND"
        ? result && matchFilterRow(pg, active[i])
        : result || matchFilterRow(pg, active[i]);
    }
    return result;
  });
}

function matchFilterRow(pg: import("@/lib/types").WebPage, row: FilterRow): boolean {
  let re: RegExp;
  try { re = new RegExp(row.pattern, "i"); } catch { return false; }
  if (row.field === "url") return re.test(pg.url);
  if (row.field === "title") return re.test(pg.title);
  if (row.field === "tags") return (pg.page_tags ?? []).some((t) => re.test(t));
  return re.test(pg.fetched_at);
}

function WebWikisTab({ isOwner }: { isOwner: boolean }) {
  const user = getUser();
  const [sources, setSources] = useState<import("@/lib/types").WebSource[]>([]);
  const [pages, setPages] = useState<Record<string, import("@/lib/types").WebPage[]>>({});
  const [expandedSource, setExpandedSource] = useState<string | null>(null);
  const [crawlingId, setCrawlingId] = useState<string | null>(null);
  const [currentUrl, setCurrentUrl] = useState<string>("");
  const [crawlStats, setCrawlStats] = useState<{ visited: number; queued: number; found: number }>({ visited: 0, queued: 0, found: 0 });
  const [crawlLog, setCrawlLog] = useState<string[]>([]);
  const [crawlResult, setCrawlResult] = useState<{ created: number; updated: number; skipped: number } | null>(null);
  const [extractingPages, setExtractingPages] = useState<Set<string>>(new Set());
  const [extractingAll, setExtractingAll] = useState<string | null>(null);
  const [pageFilters, setPageFilters] = useState<Record<string, FilterRow[]>>({});
  const [extractionStatusFilter, setExtractionStatusFilter] = useState<Record<string, "none" | "succeeded" | "failed" | "running" | "compiled" | "not_compiled" | null>>({});
  const [colWidths, setColWidths] = useState({ cb: 36, title: 260, url: 420, extraction: 200, fetched: 170, action: 140 });
  const [compileForm, setCompileForm] = useState<Record<string, { productKey: string; name: string; owner: string } | null>>({});
  const [compiling, setCompiling] = useState<Record<string, boolean>>({});
  const [compiledKp, setCompiledKp] = useState<Record<string, { id: string; name: string; semver: string } | null>>({});
  const [compilePageStatus, setCompilePageStatus] = useState<Record<string, Record<string, "compiling" | "compiled" | "discarded" | "failed">>>({});
  const [compileProgress, setCompileProgress] = useState<Record<string, { done: number; total: number }>>({});
  const [draftModal, setDraftModal] = useState<{ runId: string; title: string } | null>(null);
  const [draftJson, setDraftJson] = useState<Record<string, unknown> | null>(null);
  const [draftLoading, setDraftLoading] = useState(false);
  const [addName, setAddName] = useState("");
  const [addUrl, setAddUrl] = useState("");
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Per-page link expansion: pageId → links (null = not loaded, [] = loaded empty)
  const [expandedLinks, setExpandedLinks] = useState<Record<string, WebPageLink[] | null>>({});
  const [loadingLinks, setLoadingLinks] = useState<Set<string>>(new Set());
  // Per-source selected page IDs for compilation
  const [selectedWebPages, setSelectedWebPages] = useState<Record<string, Set<string>>>({});
  // Per-source toggle: include linked pages in compilation
  const [includeLinkedPages, setIncludeLinkedPages] = useState<Record<string, boolean>>({});;

  useEffect(() => {
    api.listWebSources().then(setSources).catch(() => {});
  }, []);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setAdding(true);
    setError(null);
    try {
      const src = await api.createWebSource(addName.trim(), addUrl.trim());
      setSources((s) => [...s, src]);
      setAddName("");
      setAddUrl("");
    } catch (err) {
      setError(String(err));
    } finally {
      setAdding(false);
    }
  }

  async function handleDelete(id: string) {
    if (!confirm("Delete this web source and all its pages?")) return;
    try {
      await api.deleteWebSource(id);
      setSources((s) => s.filter((x) => x.id !== id));
    } catch (err) {
      setError(String(err));
    }
  }

  async function handleCrawl(source: import("@/lib/types").WebSource) {
    setCrawlingId(source.id);
    setCurrentUrl("");
    setCrawlStats({ visited: 0, queued: 0, found: 0 });
    setCrawlLog([]);
    setCrawlResult(null);
    setError(null);

    const token = getToken();
    const res = await fetch(
      `${process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1"}/web-sources/${source.id}/crawl`,
      { method: "POST", headers: token ? { Authorization: `Bearer ${token}` } : {} }
    );
    if (!res.ok || !res.body) {
      setError(`Crawl failed: HTTP ${res.status}`);
      setCrawlingId(null);
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    outer: while (true) {
      const { done, value } = await reader.read();
      if (value) buffer += decoder.decode(value, { stream: !done });
      if (done) break;
      let boundary: number;
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        const msg = buffer.slice(0, boundary).trim();
        buffer = buffer.slice(boundary + 2);
        if (!msg.startsWith("data:")) continue;
        let ev: CrawlEvent;
        try { ev = JSON.parse(msg.slice(5).trim()); } catch { continue; }

        if (ev.type === "crawling") {
          setCurrentUrl(ev.url);
          setCrawlStats({ visited: ev.visited, queued: ev.queued, found: 0 });
        } else if (ev.type === "page_found") {
          setCrawlStats((s) => ({ ...s, found: s.found + 1 }));
          setCrawlLog((l) => [...l.slice(-99), `+ ${ev.title || ev.url}`]);
        } else if (ev.type === "page_updated") {
          setCrawlLog((l) => [...l.slice(-99), `↻ ${ev.title || ev.url}`]);
        } else if (ev.type === "page_unchanged") {
          // silent
        } else if (ev.type === "page_skipped" || ev.type === "page_error") {
          setCrawlLog((l) => [...l.slice(-99), `✗ ${"reason" in ev ? ev.reason : ev.error}`]);
        } else if (ev.type === "done") {
          setCrawlResult({ created: ev.created, updated: ev.updated, skipped: ev.skipped });
          setCurrentUrl("");
          const updated = await api.listWebSources().catch(() => sources);
          setSources(updated);
          if (expandedSource === source.id) {
            const pg = await api.listWebPages(source.id).catch(() => []);
            setPages((p) => ({ ...p, [source.id]: pg }));
          }
          break outer;
        } else if (ev.type === "error") {
          setError(ev.message);
          break outer;
        }
      }
    }
    setCrawlingId(null);
    setCurrentUrl("");
  }

  async function togglePages(sourceId: string) {
    if (expandedSource === sourceId) {
      setExpandedSource(null);
      return;
    }
    setExpandedSource(sourceId);
    if (!pages[sourceId]) {
      const pg = await api.listWebPages(sourceId).catch(() => []);
      setPages((p) => ({ ...p, [sourceId]: pg }));
    }
  }

  async function handleViewDraft(runId: string, title: string) {
    setDraftModal({ runId, title });
    setDraftJson(null);
    setDraftLoading(true);
    try {
      const run = await api.getExtractionRun(runId);
      setDraftJson(run.structured_draft ?? null);
    } catch (err) {
      setDraftJson({ error: String(err) });
    } finally {
      setDraftLoading(false);
    }
  }

  async function handleExtractPage(sourceId: string, pageId: string) {
    setExtractingPages((s) => new Set(s).add(pageId));
    try {
      const result = await api.extractWebPage(sourceId, pageId);
      // Update page status in local state
      setPages((prev) => ({
        ...prev,
        [sourceId]: (prev[sourceId] ?? []).map((pg) =>
          pg.id === pageId
            ? { ...pg, latest_run_id: result.run_id, latest_run_status: result.status as "succeeded" | "failed" | "running", latest_run_error: result.error_message }
            : pg
        ),
      }));
    } catch (err) {
      setError(String(err));
    } finally {
      setExtractingPages((s) => { const n = new Set(s); n.delete(pageId); return n; });
    }
  }

  async function handleToggleLinks(sourceId: string, pageId: string) {
    if (expandedLinks[pageId] !== undefined) {
      // Already loaded — toggle off
      setExpandedLinks((s) => { const n = { ...s }; delete n[pageId]; return n; });
      return;
    }
    setLoadingLinks((s) => { const n = new Set(s); n.add(pageId); return n; });
    try {
      const links = await api.listWebPageLinks(sourceId, pageId);
      setExpandedLinks((s) => ({ ...s, [pageId]: links }));
    } catch {
      setExpandedLinks((s) => ({ ...s, [pageId]: [] }));
    } finally {
      setLoadingLinks((s) => { const n = new Set(s); n.delete(pageId); return n; });
    }
  }

  async function handleExtractAll(sourceId: string, filtered: import("@/lib/types").WebPage[]) {
    setExtractingAll(sourceId);
    const pending = filtered.filter((pg) => !pg.latest_run_status || pg.latest_run_status === "failed" || pg.latest_run_status === "running");
    for (const pg of pending) {
      await handleExtractPage(sourceId, pg.id);
    }
    setExtractingAll(null);
  }

  async function handleCompile(sourceId: string, filteredPages: import("@/lib/types").WebPage[]) {
    const form = compileForm[sourceId];
    if (!form || !form.productKey.trim() || !form.name.trim() || !form.owner.trim()) return;
    const sel = selectedWebPages[sourceId];
    const pool = sel && sel.size > 0
      ? filteredPages.filter((pg) => sel.has(pg.id))
      : filteredPages;
    const baseItems = pool
      .filter((pg) => pg.latest_run_status === "succeeded" && pg.latest_run_id)
      .map((pg) => ({ run_id: pg.latest_run_id!, page_id: pg.id }));

    // If "include linked pages" is on, expand each selected page's links
    let items = baseItems;
    if (includeLinkedPages[sourceId]) {
      const itemPageIds = new Set(baseItems.map((i) => i.page_id));
      const extraItems: { run_id: string; page_id: string }[] = [];
      const token = getToken();
      const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";
      for (const item of baseItems) {
        // Use cached links if already expanded, otherwise fetch
        let links = expandedLinks[item.page_id];
        if (links === undefined || links === null) {
          try {
            const src = sources.find((s) => filteredPages.some((p) => p.id === item.page_id));
            const srcId = src?.id ?? sourceId;
            const r = await fetch(`${apiBase}/web-sources/${srcId}/pages/${item.page_id}/links`, {
              headers: token ? { Authorization: `Bearer ${token}` } : {},
            });
            if (r.ok) links = await r.json();
          } catch { links = []; }
        }
        for (const lnk of links ?? []) {
          if (lnk.linked_page_run_status === "succeeded" && lnk.linked_page_run_id && lnk.linked_page_id && !itemPageIds.has(lnk.linked_page_id)) {
            itemPageIds.add(lnk.linked_page_id);
            extraItems.push({ run_id: lnk.linked_page_run_id, page_id: lnk.linked_page_id });
          }
        }
      }
      items = [...baseItems, ...extraItems];
    }
    if (!items.length) return;

    setCompiling((c) => ({ ...c, [sourceId]: true }));
    setCompilePageStatus((s) => ({ ...s, [sourceId]: {} }));
    setCompileProgress((p) => ({ ...p, [sourceId]: { done: 0, total: items.length } }));
    setError(null);

    const token = getToken();
    try {
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1"}/extraction-runs/batch-compile-stream`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
          body: JSON.stringify({
            items,
            product_key: form.productKey.trim(),
            name: form.name.trim(),
            owner: form.owner.trim(),
            created_by: user?.user_id ?? "00000000-0000-0000-0000-000000000000",
          }),
        }
      );
      if (!res.ok || !res.body) throw new Error(await res.text());

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      outer: while (true) {
        const { done, value } = await reader.read();
        if (value) buffer += decoder.decode(value, { stream: !done });
        if (done) break;
        let boundary: number;
        while ((boundary = buffer.indexOf("\n\n")) !== -1) {
          const msg = buffer.slice(0, boundary).trim();
          buffer = buffer.slice(boundary + 2);
          if (!msg.startsWith("data:")) continue;
          let ev: Record<string, unknown>;
          try { ev = JSON.parse(msg.slice(5).trim()); } catch { continue; }

          const pageId = typeof ev.page_id === "string" ? ev.page_id : null;
          if (ev.type === "start" && typeof ev.total === "number") {
            setCompileProgress((p) => ({ ...p, [sourceId]: { done: 0, total: ev.total as number } }));
          } else if (ev.type === "merging" && pageId) {
            setCompilePageStatus((s) => ({ ...s, [sourceId]: { ...s[sourceId], [pageId]: "compiling" } }));
          } else if (ev.type === "discarded" && pageId) {
            setCompilePageStatus((s) => ({ ...s, [sourceId]: { ...s[sourceId], [pageId]: "discarded" } }));
            setCompileProgress((p) => ({ ...p, [sourceId]: { ...p[sourceId], done: (p[sourceId]?.done ?? 0) + 1 } }));
          } else if ((ev.type === "page_compiled" || ev.type === "skipped") && pageId) {
            const st = ev.type === "page_compiled" ? "compiled" : "failed";
            setCompilePageStatus((s) => ({ ...s, [sourceId]: { ...s[sourceId], [pageId]: st } }));
            setCompileProgress((p) => ({ ...p, [sourceId]: { ...p[sourceId], done: (p[sourceId]?.done ?? 0) + 1 } }));
          } else if (ev.type === "page_error" && pageId) {
            setCompilePageStatus((s) => ({ ...s, [sourceId]: { ...s[sourceId], [pageId]: "failed" } }));
            setCompileProgress((p) => ({ ...p, [sourceId]: { ...p[sourceId], done: (p[sourceId]?.done ?? 0) + 1 } }));
          } else if (ev.type === "done") {
            setCompiledKp((c) => ({ ...c, [sourceId]: { id: ev.product_id as string, name: ev.name as string, semver: ev.semver as string } }));
            setCompileForm((f) => ({ ...f, [sourceId]: null }));
            // Snap done to total so progress always shows 100% on completion
            setCompileProgress((p) => ({ ...p, [sourceId]: { ...p[sourceId], done: p[sourceId]?.total ?? p[sourceId]?.done ?? 0 } }));
            break outer;
          } else if (ev.type === "error") {
            setError(ev.message as string);
            break outer;
          }
        }
      }
    } catch (err) {
      setError(String(err));
    } finally {
      setCompiling((c) => ({ ...c, [sourceId]: false }));
    }
  }

  function togglePageSelection(sourceId: string, pageId: string, srcPages: import("@/lib/types").WebPage[]) {
    setSelectedWebPages((prev) => {
      const cur = new Set(prev[sourceId] ?? []);
      if (cur.has(pageId)) {
        cur.delete(pageId);
      } else {
        cur.add(pageId);
        // Also auto-select linked child pages that are in this source and have a succeeded extraction
        const links = expandedLinks[pageId];
        if (links) {
          const srcPageIds = new Set(srcPages.map((p) => p.id));
          for (const lnk of links) {
            if (lnk.linked_page_id && srcPageIds.has(lnk.linked_page_id)) {
              const linked = srcPages.find((p) => p.id === lnk.linked_page_id);
              if (linked?.latest_run_status === "succeeded") cur.add(lnk.linked_page_id);
            }
          }
        }
      }
      return { ...prev, [sourceId]: cur };
    });
  }

  function startColResize(col: keyof typeof colWidths, e: React.MouseEvent) {
    e.preventDefault();
    const startX = e.clientX;
    const startW = colWidths[col];
    const onMove = (mv: MouseEvent) => {
      const next = Math.max(60, startW + mv.clientX - startX);
      setColWidths((w) => ({ ...w, [col]: next }));
    };
    const onUp = () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }

  function extractionBadge(status: string | null, runId?: string | null, title?: string) {
    if (!status) return <span className="text-gray-300 text-xs">—</span>;
    const map: Record<string, string> = {
      running: "bg-yellow-100 text-yellow-700",
      succeeded: "bg-green-100 text-green-700",
      failed: "bg-red-100 text-red-700",
    };
    const label: Record<string, string> = { running: "Extracting…", succeeded: "Extracted", failed: "Failed" };
    if (status === "succeeded" && runId) {
      return (
        <button
          onClick={() => handleViewDraft(runId, title ?? "")}
          className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${map.succeeded} hover:ring-1 hover:ring-green-400 underline-offset-1`}
          title="View extracted draft JSON"
        >
          Extracted ↗
        </button>
      );
    }
    return (
      <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${map[status] ?? "bg-gray-100 text-gray-600"}`}>
        {label[status] ?? status}
      </span>
    );
  }

  return (
    <div className="space-y-6">
      {/* Add source form */}
      {isOwner && (
        <form onSubmit={handleAdd} className="rounded-lg border border-gray-200 bg-white p-5 space-y-3">
          <h2 className="text-sm font-semibold text-gray-900">Add Web Wiki</h2>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Name</label>
              <input
                value={addName}
                onChange={(e) => setAddName(e.target.value)}
                placeholder="My Wiki"
                required
                className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Root URL</label>
              <input
                value={addUrl}
                onChange={(e) => setAddUrl(e.target.value)}
                placeholder="https://wiki.example.com"
                required
                type="url"
                className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
              />
            </div>
          </div>
          {error && <p className="text-xs text-red-500">{error}</p>}
          <button
            type="submit"
            disabled={adding}
            className="rounded bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-700 disabled:opacity-50"
          >
            {adding ? "Adding…" : "Add Source"}
          </button>
        </form>
      )}

      {/* Source list */}
      {sources.length === 0 ? (
        <p className="text-sm text-gray-400 italic">No web sources yet.</p>
      ) : (
        <div className="space-y-4">
          {sources.map((src) => {
            const isCrawling = crawlingId === src.id;
            const srcPages = pages[src.id] ?? [];
            const filterRows = pageFilters[src.id] ?? [DEFAULT_FILTER_ROW];
            const statusFilter = extractionStatusFilter[src.id] ?? null;
            const filteredPages = applyPageFilters(srcPages, filterRows).filter((pg) => {
              if (!statusFilter) return true;
              if (statusFilter === "none") return !pg.latest_run_status;
              if (statusFilter === "compiled") return pg.is_compiled;
              if (statusFilter === "not_compiled") return !pg.is_compiled;
              return pg.latest_run_status === statusFilter;
            });
            const hasFilter = filterRows.some((r) => r.pattern.trim()) || !!statusFilter;
            const pendingExtract = filteredPages.filter((pg) => !pg.latest_run_status || pg.latest_run_status === "failed" || pg.latest_run_status === "running").length;

            function setRows(updater: (rows: FilterRow[]) => FilterRow[]) {
              setPageFilters((f) => ({ ...f, [src.id]: updater(f[src.id] ?? [DEFAULT_FILTER_ROW]) }));
            }
            function addRow() {
              setPageFilters((f) => {
                const rows = f[src.id] ?? [DEFAULT_FILTER_ROW];
                return { ...f, [src.id]: [...rows, { ...DEFAULT_FILTER_ROW }] };
              });
            }
            function removeRow(i: number) {
              setPageFilters((f) => {
                const rows = (f[src.id] ?? [DEFAULT_FILTER_ROW]).filter((_, idx) => idx !== i);
                return { ...f, [src.id]: rows.length ? rows : [DEFAULT_FILTER_ROW] };
              });
            }
            function clearFilters() {
              setPageFilters((f) => ({ ...f, [src.id]: [DEFAULT_FILTER_ROW] }));
              setExtractionStatusFilter((f) => ({ ...f, [src.id]: null }));
            }

            return (
              <div key={src.id} className="rounded-lg border border-gray-200 bg-white">
                {/* Header row */}
                <div className="flex items-center justify-between px-5 py-4">
                  <div>
                    <p className="text-sm font-semibold text-gray-900">{src.name}</p>
                    <a href={src.root_url} target="_blank" rel="noreferrer" className="text-xs text-blue-600 hover:underline">
                      {src.root_url}
                    </a>
                    <p className="text-xs text-gray-400 mt-0.5">
                      {src.page_count} page{src.page_count !== 1 ? "s" : ""}
                      {src.last_crawled_at ? ` · last crawled ${new Date(src.last_crawled_at).toLocaleString()}` : " · never crawled"}
                      {src.last_crawl_created != null && (
                        <span> · +{src.last_crawl_created} new, ↻{src.last_crawl_updated} updated, ✗{src.last_crawl_skipped} skipped</span>
                      )}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => togglePages(src.id)}
                      className="rounded border border-gray-200 px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-50"
                    >
                      {expandedSource === src.id ? "Hide pages ▲" : "View pages ▼"}
                    </button>
                    {isOwner && (
                      <>
                        <button
                          onClick={() => handleCrawl(src)}
                          disabled={isCrawling}
                          className="rounded bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                        >
                          {isCrawling ? "Crawling…" : "Crawl"}
                        </button>
                        <button
                          onClick={() => handleDelete(src.id)}
                          className="rounded border border-red-200 px-3 py-1.5 text-xs text-red-600 hover:bg-red-50"
                        >
                          Delete
                        </button>
                      </>
                    )}
                  </div>
                </div>

                {/* Active crawl indicator */}
                {isCrawling && (
                  <div className="border-t border-indigo-100 bg-indigo-50 px-5 py-3 space-y-2">
                    {/* Currently fetching URL */}
                    <div className="flex items-center gap-2">
                      <span className="inline-block h-2 w-2 rounded-full bg-indigo-500 animate-pulse shrink-0" />
                      <span className="text-xs font-medium text-indigo-700">Fetching</span>
                      <span className="text-xs text-indigo-600 font-mono truncate max-w-[480px]" title={currentUrl}>
                        {currentUrl || "Starting…"}
                      </span>
                    </div>
                    {/* Stats row */}
                    <div className="flex items-center gap-4 text-xs text-indigo-500">
                      <span>{crawlStats.visited} visited</span>
                      <span>{crawlStats.queued} queued</span>
                      <span>{crawlStats.found} new pages found</span>
                    </div>
                    {/* Log (last few lines) */}
                    {crawlLog.length > 0 && (
                      <div className="max-h-24 overflow-y-auto font-mono text-xs text-indigo-400 space-y-0.5 border-t border-indigo-100 pt-2">
                        {crawlLog.slice(-10).map((line, i) => (
                          <p key={i}>{line}</p>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* Crawl result banner */}
                {crawlResult && !isCrawling && (
                  <div className="border-t border-gray-100 bg-green-50 px-5 py-2 text-xs text-green-700">
                    Crawl complete — {crawlResult.created} new, {crawlResult.updated} updated, {crawlResult.skipped} skipped
                  </div>
                )}

                {/* Pages table */}
                {expandedSource === src.id && (
                  <div className="border-t border-gray-200">
                    {!pages[src.id] ? (
                      <p className="px-5 py-3 text-xs text-gray-400">Loading…</p>
                    ) : srcPages.length === 0 ? (
                      <p className="px-5 py-3 text-xs text-gray-400 italic">No pages crawled yet. Click "Crawl" to start.</p>
                    ) : (
                      <>
                        {/* Filter bar */}
                        <div className="px-4 py-2 bg-gray-50 border-b border-gray-200 space-y-1.5">
                          {/* Extraction status quick filter */}
                          <div className="flex items-center gap-1.5 flex-wrap">
                            <span className="text-xs text-gray-500 shrink-0">Status:</span>
                            {([
                              { value: null, label: "All" },
                              { value: "none", label: "Not extracted" },
                              { value: "succeeded", label: "Extracted" },
                              { value: "failed", label: "Failed" },
                              { value: "running", label: "Running" },
                              { value: "compiled", label: "Compiled" },
                              { value: "not_compiled", label: "Not compiled" },
                            ] as { value: typeof statusFilter; label: string }[]).map(({ value, label }) => (
                              <button
                                key={String(value)}
                                onClick={() => setExtractionStatusFilter((f) => ({ ...f, [src.id]: value }))}
                                className={`px-2 py-0.5 rounded-full text-xs border transition-colors ${statusFilter === value ? "bg-indigo-600 text-white border-indigo-600" : "bg-white text-gray-500 border-gray-300 hover:border-indigo-400"}`}
                              >
                                {label}
                              </button>
                            ))}
                          </div>
                          <div className="border-t border-gray-200" />
                          {(filterRows.length ? filterRows : []).map((row, i) => {
                            let rowInvalid = false;
                            if (row.pattern.trim()) {
                              try { new RegExp(row.pattern, "i"); } catch { rowInvalid = true; }
                            }
                            return (
                              <div key={i} className="space-y-1">
                                {i > 0 && (
                                  <div className="flex items-center gap-1 pl-1">
                                    {(["AND", "OR"] as FilterConnector[]).map((op) => (
                                      <button
                                        key={op}
                                        onClick={() => setRows((rows) => rows.map((r, idx) => idx === i ? { ...r, connector: op } : r))}
                                        className={`px-2 py-0.5 rounded text-xs font-mono font-semibold border transition-colors ${row.connector === op ? "bg-indigo-600 text-white border-indigo-600" : "bg-white text-gray-500 border-gray-300 hover:border-indigo-400"}`}
                                      >
                                        {op}
                                      </button>
                                    ))}
                                  </div>
                                )}
                                <div className="flex items-center gap-1.5">
                                  <select
                                    value={row.field}
                                    onChange={(e) => setRows((rows) => rows.map((r, idx) => idx === i ? { ...r, field: e.target.value as FilterField } : r))}
                                    className="rounded border border-gray-300 px-2 py-1 text-xs text-gray-600 bg-white shrink-0"
                                  >
                                    <option value="url">URL</option>
                                    <option value="title">Title</option>
                                    <option value="fetched">Fetched</option>
                                    <option value="tags">Tags</option>
                                  </select>
                                  <div className="relative flex-1">
                                    <input
                                      value={row.pattern}
                                      onChange={(e) => setRows((rows) => rows.map((r, idx) => idx === i ? { ...r, pattern: e.target.value } : r))}
                                      placeholder="regex pattern, e.g. /en/ or ^https://wiki"
                                      className={`w-full rounded border px-3 py-1 text-xs font-mono ${rowInvalid ? "border-red-400 bg-red-50" : "border-gray-300"}`}
                                    />
                                    {rowInvalid && (
                                      <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-red-500">invalid regex</span>
                                    )}
                                  </div>
                                  {filterRows.length > 0 && (
                                    <button
                                      onClick={() => removeRow(i)}
                                      className="shrink-0 text-gray-400 hover:text-red-500 text-sm leading-none px-1"
                                      title="Remove filter"
                                    >×</button>
                                  )}
                                </div>
                              </div>
                            );
                          })}
                          <div className="flex items-center gap-3 pt-0.5">
                            <button
                              onClick={addRow}
                              className="text-xs text-indigo-600 hover:text-indigo-800 font-medium"
                            >+ Add filter</button>
                            {hasFilter && (
                              <>
                                <span className="text-xs text-gray-500">{filteredPages.length} of {srcPages.length} match</span>
                                <button onClick={clearFilters} className="text-xs text-gray-400 hover:text-gray-600">Clear</button>
                              </>
                            )}
                          </div>
                        </div>

                        {/* Action bar */}
                        {isOwner && (() => {
                          const extractedCount = filteredPages.filter((p) => p.latest_run_status === "succeeded").length;
                          const sel = selectedWebPages[src.id];
                          const selSize = sel?.size ?? 0;
                          const selSucceededCount = selSize > 0
                            ? filteredPages.filter((p) => sel!.has(p.id) && p.latest_run_status === "succeeded").length
                            : 0;
                          const compileCount = selSize > 0 ? selSucceededCount : extractedCount;
                          const form = compileForm[src.id] ?? null;
                          const isCompiling = compiling[src.id] ?? false;
                          const lastKp = compiledKp[src.id] ?? null;
                          // Select-all logic for action bar
                          const allFilteredSucceeded = filteredPages.filter((p) => p.latest_run_status === "succeeded");
                          const allSelected = allFilteredSucceeded.length > 0 && allFilteredSucceeded.every((p) => sel?.has(p.id));
                          const someSelected = allFilteredSucceeded.some((p) => sel?.has(p.id));
                          return (
                            <div className="border-b border-gray-200 bg-gray-50">
                              <div className="flex items-center justify-between px-4 py-2">
                                <div className="flex items-center gap-3">
                                  <p className="text-xs text-gray-500">
                                    {extractedCount} of {filteredPages.length} extracted
                                    {hasFilter && ` (filtered)`}
                                    {pendingExtract > 0 && ` · ${pendingExtract} pending`}
                                  </p>
                                  {selSize > 0 && (
                                    <span className="text-xs text-indigo-600 font-medium">
                                      {selSize} page{selSize !== 1 ? "s" : ""} selected ({selSucceededCount} extracted)
                                    </span>
                                  )}
                                  {selSize > 0 && (
                                    <button
                                      onClick={() => setSelectedWebPages((prev) => ({ ...prev, [src.id]: new Set() }))}
                                      className="text-xs text-gray-400 hover:text-gray-600"
                                    >Clear selection</button>
                                  )}
                                </div>
                                <div className="flex items-center gap-2">
                                  <button
                                    onClick={() => handleExtractAll(src.id, filteredPages)}
                                    disabled={extractingAll === src.id || pendingExtract === 0}
                                    className="rounded bg-blue-600 px-3 py-1 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-40"
                                  >
                                    {extractingAll === src.id ? "Extracting…" : `Extract ${pendingExtract} pending`}
                                  </button>
                                  <label className="flex items-center gap-1.5 text-xs text-gray-600 cursor-pointer select-none">
                                    <input
                                      type="checkbox"
                                      checked={includeLinkedPages[src.id] ?? false}
                                      onChange={(e) => setIncludeLinkedPages((prev) => ({ ...prev, [src.id]: e.target.checked }))}
                                      className="rounded"
                                    />
                                    Include linked pages
                                  </label>
                                  <button
                                    onClick={() => setCompileForm((f) => ({ ...f, [src.id]: f[src.id] ? null : { productKey: "", name: src.name, owner: user?.display_name ?? "" } }))}
                                    disabled={compileCount === 0}
                                    className={`rounded px-3 py-1 text-xs font-medium text-white disabled:opacity-40 ${selSize > 0 ? "bg-indigo-700 hover:bg-indigo-800" : "bg-indigo-600 hover:bg-indigo-700"}`}
                                  >
                                    {selSize > 0 ? `Compile ${compileCount} selected → KP` : `Compile ${compileCount} → KP`}
                                  </button>
                                </div>
                              </div>

                              {/* Compile form */}
                              {form && (
                                <div className="px-4 pb-3 space-y-2 border-t border-gray-200 pt-2">
                                  <p className="text-xs font-medium text-gray-700">Compile {compileCount} page{compileCount !== 1 ? "s" : ""} into a Knowledge Product{selSize > 0 ? " (selected)" : ""}</p>
                                  <div className="flex items-end gap-2 flex-wrap">
                                    <div>
                                      <label className="block text-xs text-gray-500 mb-0.5">Product Key</label>
                                      <input
                                        value={form.productKey}
                                        onChange={(e) => setCompileForm((f) => ({ ...f, [src.id]: { ...f[src.id]!, productKey: e.target.value } }))}
                                        placeholder="e.g. wiki-onboarding"
                                        className="rounded border border-gray-300 px-2 py-1 text-xs w-36"
                                      />
                                    </div>
                                    <div>
                                      <label className="block text-xs text-gray-500 mb-0.5">Name</label>
                                      <input
                                        value={form.name}
                                        onChange={(e) => setCompileForm((f) => ({ ...f, [src.id]: { ...f[src.id]!, name: e.target.value } }))}
                                        placeholder="KP name"
                                        className="rounded border border-gray-300 px-2 py-1 text-xs w-44"
                                      />
                                    </div>
                                    <div>
                                      <label className="block text-xs text-gray-500 mb-0.5">Owner</label>
                                      <input
                                        value={form.owner}
                                        onChange={(e) => setCompileForm((f) => ({ ...f, [src.id]: { ...f[src.id]!, owner: e.target.value } }))}
                                        placeholder="owner name"
                                        className="rounded border border-gray-300 px-2 py-1 text-xs w-32"
                                      />
                                    </div>
                                    <button
                                      onClick={() => handleCompile(src.id, filteredPages)}
                                      disabled={isCompiling || !form.productKey.trim() || !form.name.trim() || !form.owner.trim()}
                                      className="rounded bg-indigo-600 px-3 py-1 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-40"
                                    >
                                      {isCompiling ? "Compiling…" : "Compile"}
                                    </button>
                                    <button
                                      onClick={() => setCompileForm((f) => ({ ...f, [src.id]: null }))}
                                      className="text-xs text-gray-400 hover:text-gray-600"
                                    >Cancel</button>
                                  </div>
                                </div>
                              )}

                              {/* Compile progress */}
                              {isCompiling && (() => {
                                const prog = compileProgress[src.id];
                                const pct = prog && prog.total > 0 ? Math.round((prog.done / prog.total) * 100) : 0;
                                return (
                                  <div className="px-4 pb-3 border-t border-gray-200 pt-2 space-y-1.5">
                                    <div className="flex items-center justify-between text-xs text-gray-600">
                                      <span className="flex items-center gap-1.5">
                                        <span className="inline-block h-1.5 w-1.5 rounded-full bg-indigo-500 animate-pulse" />
                                        Compiling… {prog?.done ?? 0} / {prog?.total ?? 0} pages
                                      </span>
                                      <span>{pct}%</span>
                                    </div>
                                    <div className="w-full h-1.5 rounded-full bg-gray-200 overflow-hidden">
                                      <div
                                        className="h-full rounded-full bg-indigo-500 transition-all duration-300"
                                        style={{ width: `${pct}%` }}
                                      />
                                    </div>
                                  </div>
                                );
                              })()}

                              {/* Compiled KP result */}
                              {lastKp && !form && !isCompiling && (
                                <div className="px-4 pb-2 flex items-center gap-2 text-xs text-green-700">
                                  <span>✓ Compiled →</span>
                                  <a href={`/products/${lastKp.id}`} className="font-medium underline hover:text-green-900">
                                    {lastKp.name} v{lastKp.semver}
                                  </a>
                                  <button onClick={() => setCompiledKp((c) => ({ ...c, [src.id]: null }))} className="text-gray-400 hover:text-gray-600 ml-1">×</button>
                                </div>
                              )}
                            </div>
                          );
                        })()}
                        {(() => {
                          const sel = selectedWebPages[src.id];
                          const allFilteredSucceeded = filteredPages.filter((p) => p.latest_run_status === "succeeded");
                          const allSelected = allFilteredSucceeded.length > 0 && allFilteredSucceeded.every((p) => sel?.has(p.id));
                          const someSelected = !allSelected && allFilteredSucceeded.some((p) => sel?.has(p.id));
                          return null; // variables only — rendered below
                        })()}
                        <div className="overflow-x-auto">
                          <table className="text-xs" style={{ tableLayout: "fixed", width: Object.values(colWidths).reduce((a, b) => a + b, 0) }}>
                            <colgroup>
                              <col style={{ width: colWidths.cb }} />
                              <col style={{ width: colWidths.title }} />
                              <col style={{ width: colWidths.url }} />
                              <col style={{ width: colWidths.extraction }} />
                              <col style={{ width: colWidths.fetched }} />
                              <col style={{ width: colWidths.action }} />
                            </colgroup>
                            <thead>
                              {(() => {
                                const sel = selectedWebPages[src.id];
                                const allFilteredSucceeded = filteredPages.filter((p) => p.latest_run_status === "succeeded");
                                const allSelected = allFilteredSucceeded.length > 0 && allFilteredSucceeded.every((p) => sel?.has(p.id));
                                const someSelected = !allSelected && allFilteredSucceeded.some((p) => sel?.has(p.id));
                                return (
                                  <tr className="bg-gray-50 text-left text-gray-500 select-none">
                                    <th className="px-2 py-2 font-medium text-center" style={{ width: colWidths.cb }}>
                                      <input
                                        type="checkbox"
                                        checked={allSelected}
                                        ref={(el) => { if (el) el.indeterminate = someSelected; }}
                                        onChange={(e) => {
                                          setSelectedWebPages((prev) => {
                                            const cur = new Set(prev[src.id] ?? []);
                                            if (e.target.checked) allFilteredSucceeded.forEach((p) => cur.add(p.id));
                                            else allFilteredSucceeded.forEach((p) => cur.delete(p.id));
                                            return { ...prev, [src.id]: cur };
                                          });
                                        }}
                                        className="rounded"
                                        title="Select all extracted pages"
                                      />
                                    </th>
                                    {(["title", "url", "extraction", "fetched"] as const).map((col, i) => (
                                      <th key={col} className="px-4 py-2 font-medium relative" style={{ width: colWidths[col] }}>
                                        {["Title", "URL", "Extraction", "Fetched"][i]}
                                        <span
                                          onMouseDown={(e) => startColResize(col, e)}
                                          className="absolute right-0 top-0 h-full w-1.5 cursor-col-resize hover:bg-indigo-400 opacity-0 hover:opacity-60 active:opacity-80"
                                        />
                                      </th>
                                    ))}
                                    <th className="px-4 py-2 font-medium relative" style={{ width: colWidths.action }}>
                                      Actions
                                      <span
                                        onMouseDown={(e) => startColResize("action", e)}
                                        className="absolute right-0 top-0 h-full w-1.5 cursor-col-resize hover:bg-indigo-400 opacity-0 hover:opacity-60 active:opacity-80"
                                      />
                                    </th>
                                  </tr>
                                );
                              })()}
                            </thead>
                            <tbody className="divide-y divide-gray-100">
                              {filteredPages.map((pg) => {
                                const isExtracting = extractingPages.has(pg.id);
                                const status = isExtracting ? "running" : pg.latest_run_status;
                                const compileStatus = compilePageStatus[src.id]?.[pg.id] ?? null;
                                const compileBadgeMap: Record<string, string> = {
                                  compiling: "bg-indigo-100 text-indigo-700",
                                  compiled: "bg-green-100 text-green-700",
                                  discarded: "bg-amber-100 text-amber-700",
                                  failed: "bg-red-100 text-red-700",
                                };
                                const compileLabelMap: Record<string, string> = {
                                  compiling: "Compiling…",
                                  compiled: "Compiled",
                                  discarded: "Discarded",
                                  failed: "Compile failed",
                                };
                                const linksOpen = expandedLinks[pg.id] !== undefined;
                                const linksLoading = loadingLinks.has(pg.id);
                                const links = expandedLinks[pg.id] ?? null;
                                const isSelected = selectedWebPages[src.id]?.has(pg.id) ?? false;
                                const colSpan = 6; // cb + title + url + extraction + fetched + action
                                const rows: React.ReactNode[] = [
                                  <tr key={`${pg.id}-row`} className={`hover:bg-gray-50 ${isSelected ? "bg-indigo-50/40" : ""}`}>
                                    <td className="px-2 py-2 text-center">
                                      <input
                                        type="checkbox"
                                        checked={isSelected}
                                        onChange={() => togglePageSelection(src.id, pg.id, srcPages)}
                                        className="rounded"
                                        title={pg.latest_run_status === "succeeded" ? "Select for compilation" : "Extract page first to enable compilation"}
                                      />
                                    </td>
                                    <td className="px-4 py-2 font-medium text-gray-800 overflow-hidden text-ellipsis whitespace-nowrap" title={pg.title}>
                                      {pg.title}
                                    </td>
                                    <td className="px-4 py-2 overflow-hidden whitespace-nowrap">
                                      <a href={pg.url} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline font-mono text-xs" title={pg.url}>
                                        {pg.url}
                                      </a>
                                    </td>
                                    <td className="px-4 py-2 overflow-hidden">
                                      <div className="flex flex-col gap-1">
                                        <div className="flex items-center gap-1.5 flex-wrap">
                                          {isExtracting && (
                                            <span className="inline-block h-1.5 w-1.5 rounded-full bg-yellow-400 animate-pulse shrink-0" />
                                          )}
                                          {extractionBadge(status ?? null, pg.latest_run_id, pg.title)}
                                          {status === "failed" && pg.latest_run_error && (
                                            <span className="text-red-400 truncate text-xs" title={pg.latest_run_error}>
                                              {pg.latest_run_error}
                                            </span>
                                          )}
                                          {compileStatus ? (
                                            <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${compileBadgeMap[compileStatus]}`}>
                                              {compileStatus === "compiling" && <span className="inline-block h-1.5 w-1.5 rounded-full bg-indigo-500 animate-pulse" />}
                                              {compileLabelMap[compileStatus]}
                                            </span>
                                          ) : pg.is_compiled ? (
                                            <span className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium bg-green-100 text-green-700" title={pg.compiled_at ? `Compiled ${new Date(pg.compiled_at).toLocaleString()}` : "Compiled"}>
                                              Compiled
                                            </span>
                                          ) : null}
                                        </div>
                                        {pg.page_tags && pg.page_tags.length > 0 && (
                                          <div className="flex flex-wrap gap-1">
                                            {pg.page_tags.map((tag) => (
                                              <span key={tag} className="inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium bg-sky-50 text-sky-700 border border-sky-200 whitespace-nowrap" title={tag}>
                                                {tag}
                                              </span>
                                            ))}
                                          </div>
                                        )}
                                      </div>
                                    </td>
                                    <td className="px-4 py-2 text-gray-400 whitespace-nowrap overflow-hidden">
                                      {new Date(pg.fetched_at).toLocaleString()}
                                    </td>
                                    <td className="px-4 py-2">
                                      <div className="flex items-center gap-1.5">
                                        <button
                                          onClick={() => handleToggleLinks(src.id, pg.id)}
                                          disabled={linksLoading}
                                          title={linksOpen ? "Hide linked pages" : "Show pages linked from this page"}
                                          className={`rounded border px-2 py-0.5 text-xs disabled:opacity-40 ${linksOpen ? "border-indigo-300 bg-indigo-50 text-indigo-700 hover:bg-indigo-100" : "border-gray-200 text-gray-600 hover:bg-gray-100"}`}
                                        >
                                          {linksLoading ? "…" : linksOpen ? "▲ Links" : "Links"}
                                        </button>
                                        {isOwner && (
                                          <button
                                            onClick={() => handleExtractPage(src.id, pg.id)}
                                            disabled={isExtracting}
                                            className="rounded border border-gray-200 px-2 py-0.5 text-xs text-gray-600 hover:bg-gray-100 disabled:opacity-40"
                                          >
                                            {isExtracting ? "…" : status === "succeeded" ? "Re-extract" : "Extract"}
                                          </button>
                                        )}
                                      </div>
                                    </td>
                                  </tr>,
                                ];
                                if (linksOpen && links !== null) rows.push(
                                    <tr key={`${pg.id}-links`} className="bg-indigo-50/50">
                                      <td colSpan={colSpan} className="px-6 py-3">
                                        {links.length === 0 ? (
                                          <p className="text-xs text-gray-400 italic">No links found. Re-crawl this source to discover links.</p>
                                        ) : (
                                          <div className="overflow-x-auto">
                                            <p className="text-xs font-medium text-gray-500 mb-2">{links.length} link{links.length !== 1 ? "s" : ""} found on this page</p>
                                            <table className="w-full text-xs border-collapse">
                                              <thead>
                                                <tr className="text-left text-gray-400 border-b border-indigo-100">
                                                  <th className="py-1 pr-3 font-medium">URL</th>
                                                  <th className="py-1 pr-3 font-medium">Title</th>
                                                  <th className="py-1 font-medium">Status</th>
                                                </tr>
                                              </thead>
                                              <tbody className="divide-y divide-indigo-100/60">
                                                {links.map((lnk) => (
                                                  <tr key={lnk.url} className="hover:bg-indigo-50">
                                                    <td className="py-1.5 pr-3 max-w-xs overflow-hidden text-ellipsis whitespace-nowrap">
                                                      <a href={lnk.url} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline font-mono" title={lnk.url}>
                                                        {lnk.url}
                                                      </a>
                                                    </td>
                                                    <td className="py-1.5 pr-3 text-gray-600 max-w-xs overflow-hidden text-ellipsis whitespace-nowrap">
                                                      {lnk.linked_page_title ?? lnk.title ?? <span className="text-gray-300 italic">not crawled</span>}
                                                    </td>
                                                    <td className="py-1.5">
                                                      <div className="flex flex-wrap items-center gap-1">
                                                        {!lnk.linked_page_id ? (
                                                          <span className="text-gray-300">Not crawled</span>
                                                        ) : lnk.linked_page_run_status === "succeeded" ? (
                                                          <span className="inline-flex items-center rounded-full bg-green-100 px-2 py-0.5 text-green-700 font-medium">Extracted</span>
                                                        ) : lnk.linked_page_run_status === "failed" ? (
                                                          <span className="inline-flex items-center rounded-full bg-red-100 px-2 py-0.5 text-red-700 font-medium">Failed</span>
                                                        ) : lnk.linked_page_run_status === "running" ? (
                                                          <span className="inline-flex items-center gap-1 rounded-full bg-yellow-100 px-2 py-0.5 text-yellow-700 font-medium">
                                                            <span className="h-1.5 w-1.5 rounded-full bg-yellow-400 animate-pulse inline-block" />Extracting
                                                          </span>
                                                        ) : (
                                                          <span className="text-gray-400">Crawled, not extracted</span>
                                                        )}
                                                        {lnk.linked_page_is_compiled && (
                                                          <span
                                                            className="inline-flex items-center rounded-full bg-indigo-100 px-2 py-0.5 text-indigo-700 font-medium"
                                                            title={lnk.linked_page_compiled_at ? `Compiled ${new Date(lnk.linked_page_compiled_at).toLocaleString()}` : "Compiled"}
                                                          >
                                                            Compiled
                                                          </span>
                                                        )}
                                                      </div>
                                                    </td>
                                                  </tr>
                                                ))}
                                              </tbody>
                                            </table>
                                          </div>
                                        )}
                                      </td>
                                    </tr>
                                );
                                return rows;
                              })}
                            </tbody>
                          </table>
                        </div>
                      </>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Structured draft JSON modal */}
      {draftModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={() => setDraftModal(null)}>
          <div
            className="relative w-full max-w-3xl max-h-[85vh] rounded-xl bg-white shadow-2xl flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-start justify-between gap-4 px-5 py-4 border-b border-gray-200">
              <div className="min-w-0">
                <p className="text-sm font-semibold text-gray-900">Extracted Draft JSON</p>
                <p className="text-xs text-gray-500 mt-0.5 truncate" title={draftModal.title}>{draftModal.title}</p>
                <p className="text-xs text-gray-400 font-mono mt-0.5">{draftModal.runId}</p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {draftJson && !draftLoading && (
                  <button
                    onClick={() => navigator.clipboard.writeText(JSON.stringify(draftJson, null, 2))}
                    className="rounded border border-gray-200 px-2 py-1 text-xs text-gray-600 hover:bg-gray-50"
                    title="Copy JSON to clipboard"
                  >
                    Copy
                  </button>
                )}
                <button
                  onClick={() => setDraftModal(null)}
                  className="rounded-full w-6 h-6 flex items-center justify-center text-gray-400 hover:bg-gray-100 hover:text-gray-600 text-lg leading-none"
                >
                  ×
                </button>
              </div>
            </div>
            {/* Body */}
            <div className="overflow-y-auto flex-1 p-5">
              {draftLoading ? (
                <p className="text-sm text-gray-400 text-center py-10">Loading…</p>
              ) : draftJson === null ? (
                <p className="text-sm text-gray-400 italic text-center py-10">No structured draft available for this run.</p>
              ) : (
                <pre className="text-xs font-mono text-gray-800 whitespace-pre-wrap break-words leading-relaxed bg-gray-50 rounded-lg p-4">
                  {JSON.stringify(draftJson, null, 2)}
                </pre>
              )}
            </div>
          </div>
        </div>
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
