"use client";

import React, { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { NavBar } from "@/components/NavBar";
import { api, ApiError } from "@/lib/api";
import { getToken, getUser, redirectIfUnauthorized } from "@/lib/auth";
import type { ConfluencePage, ConfluencePageDetail, ConfluenceSpace, CurationRun, CompiledProductSummary, WebPageLink, LinkTreeNode, LinkTreeResponse } from "@/lib/types";

interface SyncResult {
  space_key: string;
  pages_created: number;
  pages_updated: number;
  pages_skipped_unchanged: number;
}

type Tab = "connect" | "pages" | "web";
type PageStatus = "idle" | "curating" | "curated" | "reused" | "compiling" | "compiled" | "failed" | "discarded";

function StatusBadge({ status, isCompiled }: { status: LinkTreeNode["run_status"]; isCompiled: boolean }) {
  return (
    <span className="flex items-center gap-1">
      {isCompiled && (
        <span className="inline-flex items-center rounded-full bg-indigo-100 px-1.5 py-0.5 text-indigo-700 text-[10px] font-medium">Compiled</span>
      )}
      {status === "succeeded" && !isCompiled && (
        <span className="inline-flex items-center rounded-full bg-green-100 px-1.5 py-0.5 text-green-700 text-[10px] font-medium">Curated</span>
      )}
      {status === "failed" && (
        <span className="inline-flex items-center rounded-full bg-red-100 px-1.5 py-0.5 text-red-700 text-[10px] font-medium">Failed</span>
      )}
      {status === "running" && (
        <span className="inline-flex items-center gap-0.5 rounded-full bg-yellow-100 px-1.5 py-0.5 text-yellow-700 text-[10px] font-medium">
          <span className="h-1.5 w-1.5 rounded-full bg-yellow-400 animate-pulse inline-block" />Curating
        </span>
      )}
    </span>
  );
}

function TreeNode({ node, sourceId, childrenOf }: { node: LinkTreeNode; sourceId: string; childrenOf: "children" | "parents" }) {
  const [expanded, setExpanded] = useState(false);
  const [lazyChildren, setLazyChildren] = useState<LinkTreeNode[] | null>(null);
  const [loading, setLoading] = useState(false);
  const indent = (node.depth - 1) * 16;

  async function handleExpand() {
    if (expanded) { setExpanded(false); return; }
    setExpanded(true);
    if (lazyChildren !== null || !node.page_id) return;
    setLoading(true);
    try {
      const data = await api.getWebPageLinkTree(sourceId, node.page_id);
      const next = childrenOf === "children" ? data.children : data.parents;
      setLazyChildren(next.map(c => ({ ...c, depth: node.depth + 1 })));
    } catch {
      setLazyChildren([]);
    } finally {
      setLoading(false);
    }
  }

  const displayChildren = lazyChildren ?? [];
  const canExpand = !!node.page_id;

  return (
    <div>
      <div
        className="flex items-start gap-1 py-1 hover:bg-gray-50 rounded px-1 cursor-default"
        style={{ paddingLeft: `${indent + 4}px` }}
      >
        {canExpand ? (
          <button
            className="mt-0.5 text-gray-400 hover:text-gray-600 text-xs w-3 shrink-0"
            onClick={handleExpand}
          >
            {loading ? "·" : expanded ? "▾" : "▸"}
          </button>
        ) : (
          <span className="w-3 shrink-0 text-gray-200 text-xs">–</span>
        )}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            {node.page_id ? (
              <span className="text-gray-800 truncate max-w-xs text-xs font-medium">{node.title ?? node.url}</span>
            ) : (
              <span className="text-gray-400 italic text-xs truncate max-w-xs">{node.url}</span>
            )}
            {!node.page_id && (
              <span className="text-gray-300 text-[10px]">Not crawled</span>
            )}
            <StatusBadge status={node.run_status} isCompiled={node.is_compiled} />
          </div>
          {node.title && node.title !== node.url && (
            <span className="text-gray-400 text-[10px] truncate block max-w-sm">{node.url}</span>
          )}
        </div>
      </div>
      {expanded && displayChildren.length > 0 && (
        <div>
          {displayChildren.map((child) => (
            <TreeNode key={child.page_id ?? child.url} node={child} sourceId={sourceId} childrenOf={childrenOf} />
          ))}
        </div>
      )}
    </div>
  );
}

function LinkTreeSection({ data, sourceId }: { data: LinkTreeResponse; sourceId: string }) {
  const hasParents = data.parents.length > 0;
  const hasChildren = data.children.length > 0;

  if (!hasParents && !hasChildren) {
    return <p className="text-gray-400 italic text-xs">No links found for this page.</p>;
  }

  return (
    <div className="space-y-4">
      {hasParents && (
        <div>
          <p className="text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Referenced by</p>
          <div className="border border-gray-100 rounded-lg bg-gray-50/50 py-1">
            {data.parents.map((node) => (
              <TreeNode key={node.page_id ?? node.url} node={node} sourceId={sourceId} childrenOf="parents" />
            ))}
          </div>
        </div>
      )}
      {hasChildren && (
        <div>
          <p className="text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Links to</p>
          <div className="border border-gray-100 rounded-lg bg-gray-50/50 py-1">
            {data.children.map((node) => (
              <TreeNode key={node.page_id ?? node.url} node={node} sourceId={sourceId} childrenOf="children" />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

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
          Connect Confluence spaces and curate Knowledge Products from ingested pages.
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
  const [runs, setRuns] = useState<Record<string, CurationRun>>({});
  const [search, setSearch] = useState("");
  const [pageStatus, setPageStatus] = useState<Record<string, PageStatus>>({});

  // Space-level action state
  const [curating, setCurating] = useState(false);
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
        const historyMap = await api.getBulkCurationHistory(selectedSpace || undefined)
          .catch(() => ({} as Record<string, CurationRun[]>));
        const newRuns: Record<string, CurationRun> = {};
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

  async function handleCurateAll() {
    if (!pages) return;
    setCurating(true);
    setError(null);
    setCompileResult(null);
    const toProcess = filtered; // respect current search filter
    for (const page of toProcess) {
      setPageStatus((s) => ({ ...s, [page.id]: "curating" }));
      try {
        const run = await api.smartCuratePage(page.id);
        setRuns((r) => ({ ...r, [page.id]: run }));
        if (run.status === "failed") {
          setPageStatus((s) => ({ ...s, [page.id]: "failed" }));
        } else {
          setPageStatus((s) => ({ ...s, [page.id]: run.reused ? "reused" : "curated" }));
        }
      } catch {
        setPageStatus((s) => ({ ...s, [page.id]: "failed" }));
      }
    }
    setCurating(false);
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
      let pendingPageIds: string[];
      if (selectedPages.size > 0) {
        pendingPageIds = filtered
          .filter((p) => selectedPages.has(p.id) && runs[p.id]?.status === "succeeded")
          .map((p) => p.id);
      } else if (forceCompileAll) {
        pendingPageIds = filtered
          .filter((p) => runs[p.id]?.status === "succeeded")
          .map((p) => p.id);
      } else {
        const pending = await api.getPendingCompileRuns(selectedSpace);
        pendingPageIds = pending.map((p) => p.page_id);
      }

      if (pendingPageIds.length === 0) {
        setError(selectedPages.size > 0
          ? "None of the selected pages have a succeeded curation."
          : "No pages pending compile — all curated pages are already up to date.");
        setCompiling(false);
        return;
      }

      // Stream SSE compile progress — updates each page status in real time
      const token = getToken();
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/v1/curation-runs/batch-compile-stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          page_ids: pendingPageIds,
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
      const historyMap = await api.getBulkCurationHistory(selectedSpace).catch(() => ({} as Record<string, CurationRun[]>));
      const newRuns: Record<string, CurationRun> = {};
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

  const pendingCurateCount = filtered.filter((p) => {
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
              <p className="text-xs font-medium text-gray-700 mb-1">Step 1 — Curate</p>
              <button
                onClick={handleCurateAll}
                disabled={curating || compiling}
                className="rounded bg-gray-900 px-4 py-1.5 text-xs font-medium text-white hover:bg-gray-700 disabled:opacity-50"
              >
                {curating ? "Curating…" : `Curate All ${filtered.length} Pages`}
              </button>
              {pendingCurateCount > 0 && !curating && (
                <p className="mt-1 text-xs text-amber-700">{pendingCurateCount} page{pendingCurateCount !== 1 ? "s" : ""} not yet curated</p>
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
                  disabled={curating || compiling}
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
                  <span className="text-xs text-gray-600">Compile All — force recompile all curated pages in current scope</span>
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
                  ? `${selectedPages.size} page${selectedPages.size !== 1 ? "s" : ""} selected — ${selectedSucceededCount} with succeeded curation will be compiled.`
                  : forceCompileAll
                  ? `Force recompiling all ${allSucceededCount} curated page${allSucceededCount !== 1 ? "s" : ""} in current scope.`
                  : "Only compiles pages with new curations since last compile."}
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
                  title={isSelectable ? "Select for compile" : "No succeeded curation"}
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
    curating: "bg-yellow-100 text-yellow-800",
    curated: "bg-blue-100 text-blue-800",
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
  run: CurationRun | null;
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
              {status === "curating" ? "Curating…" :
               status === "curated" ? "Curated" :
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

      {/* Curation + Compile info boxes */}
      {run && (
        <div className="mt-3 border-t border-gray-100 pt-3 grid grid-cols-1 sm:grid-cols-2 gap-3">
          {/* Curation box */}
          <div className="rounded border border-gray-100 bg-gray-50 px-3 py-2 text-xs space-y-1">
            <p className="font-medium text-gray-700 text-[11px] uppercase tracking-wide">Last Curation</p>
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

function CompileBox({ run, onNavigate }: { run: CurationRun; onNavigate: (id: string) => void }) {
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

const STATUS_OPTIONS: { value: string; label: string }[] = [
  { value: "not_curated", label: "Not Curated" },
  { value: "curated", label: "Curated" },
  { value: "curation_failed", label: "Curation Failed" },
  { value: "compiled_to_kp", label: "Compiled to KP" },
  { value: "not_compiled_to_kp", label: "Not Compiled to KP" },
  { value: "compile_failed", label: "Compile Failed" },
];

function getDistinctStatuses(pages: import("@/lib/types").WebPage[]): { value: string; label: string }[] {
  const present = new Set<string>();
  pages.forEach((pg) => {
    if (!pg.latest_run_status) present.add("not_curated");
    else if (pg.latest_run_status === "succeeded") present.add("curated");
    else if (pg.latest_run_status === "failed") present.add("curation_failed");
    if (pg.is_compiled) present.add("compiled_to_kp");
    else if (pg.latest_run_status === "succeeded") present.add("not_compiled_to_kp");
    if (pg.latest_compile_status === "skipped") present.add("compile_failed");
  });
  return STATUS_OPTIONS.filter((o) => present.has(o.value));
}

function StatusMultiSelect({
  pages,
  selected,
  onChange,
}: {
  pages: import("@/lib/types").WebPage[];
  selected: string[];
  onChange: (next: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const options = getDistinctStatuses(pages);

  useEffect(() => {
    if (!open) return;
    function handle(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [open]);

  function toggle(value: string) {
    onChange(selected.includes(value) ? selected.filter((v) => v !== value) : [...selected, value]);
  }

  const label = selected.length === 0 ? "All" : selected.map((v) => STATUS_OPTIONS.find((o) => o.value === v)?.label ?? v).join(", ");

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className={`flex items-center gap-1.5 rounded border px-2 py-1 text-xs ${selected.length > 0 ? "border-indigo-400 bg-indigo-50 text-indigo-700" : "border-gray-300 bg-white text-gray-600"} hover:border-indigo-400`}
      >
        <span className="shrink-0 text-gray-500">Status:</span>
        <span className="max-w-[200px] truncate">{label}</span>
        <span className="text-gray-400 shrink-0">▾</span>
      </button>
      {open && (
        <div className="absolute left-0 top-full mt-1 z-20 rounded border border-gray-200 bg-white shadow-lg min-w-[180px] py-1">
          {options.length === 0 ? (
            <p className="px-3 py-2 text-xs text-gray-400 italic">No data yet</p>
          ) : (
            <>
              {options.map(({ value, label: optLabel }) => (
                <label key={value} className="flex items-center gap-2 px-3 py-1.5 hover:bg-gray-50 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={selected.includes(value)}
                    onChange={() => toggle(value)}
                    className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                  />
                  <span className="text-xs text-gray-700">{optLabel}</span>
                </label>
              ))}
              {selected.length > 0 && (
                <div className="border-t border-gray-100 mt-1 pt-1">
                  <button
                    onClick={() => { onChange([]); setOpen(false); }}
                    className="w-full px-3 py-1.5 text-xs text-left text-gray-400 hover:text-gray-600"
                  >
                    Clear selection
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

type CrawlEvent =
  | { type: "crawling"; url: string; queued: number; visited: number }
  | { type: "page_found"; url: string; page_id: string; title: string; thin_content?: boolean }
  | { type: "page_updated"; url: string; page_id: string; title: string; thin_content?: boolean }
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
  const [curatingPages, setCuratingPages] = useState<Set<string>>(new Set());
  const [curatingAll, setCuratingAll] = useState<string | null>(null);
  const [pageFilters, setPageFilters] = useState<Record<string, FilterRow[]>>({});
  const [curationStatusFilter, setCurationStatusFilter] = useState<Record<string, string[]>>({});
  const [colWidths, setColWidths] = useState({ cb: 36, title: 260, url: 420, curation: 200, compiled_kp: 110, fetched: 170, action: 140 });
  const [selectedKpId, setSelectedKpId] = useState<string | null>(null);
  const [showNotInKp, setShowNotInKp] = useState(false);
  const [compiledKps, setCompiledKps] = useState<Record<string, import("@/lib/types").CompiledKpSummary[]>>({});
  const [kpStatusMap, setKpStatusMap] = useState<Record<string, Record<string, "compiled" | "not_relevant" | "none">>>({});
  const [showLegend, setShowLegend] = useState(false);
  const [compileForm, setCompileForm] = useState<Record<string, { productKey: string; name: string; owner: string; brief: string } | null>>({});
  const [compiling, setCompiling] = useState<Record<string, boolean>>({});
  const [compiledKp, setCompiledKp] = useState<Record<string, { id: string; name: string; semver: string } | null>>({});
  const [compilePageStatus, setCompilePageStatus] = useState<Record<string, Record<string, "compiling" | "compiled" | "discarded" | "failed">>>({});
  const [compileProgress, setCompileProgress] = useState<Record<string, { done: number; total: number }>>({});
  const [draftModal, setDraftModal] = useState<{ runId: string; title: string } | null>(null);
  const [draftJson, setDraftJson] = useState<Record<string, unknown> | null>(null);
  const [draftLoading, setDraftLoading] = useState(false);
  const [addName, setAddName] = useState("");
  const [addUrl, setAddUrl] = useState("");
  const [addDepth, setAddDepth] = useState<number | null>(1);
  const [addIncludeQuery, setAddIncludeQuery] = useState(false);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Links popup modal
  const [linksModal, setLinksModal] = useState<{ pageId: string; pageTitle: string; sourceId: string } | null>(null);
  const [linksModalData, setLinksModalData] = useState<LinkTreeResponse | null>(null);
  const [linksModalLoading, setLinksModalLoading] = useState(false);
  // Per-page link expansion: pageId → links (null = not loaded, [] = loaded empty)
  const [expandedLinks, setExpandedLinks] = useState<Record<string, WebPageLink[] | null>>({});
  const [loadingLinks, setLoadingLinks] = useState<Set<string>>(new Set());
  // Per-source selected page IDs for compilation
  const [selectedWebPages, setSelectedWebPages] = useState<Record<string, Set<string>>>({});
  // Linked pages curation confirmation modal
  const [linkedCurationModal, setLinkedCurationModal] = useState<{
    sourceId: string;
    pages: import("@/lib/types").WebPage[];
    checked: Set<string>;
  } | null>(null);
  const [queueingLinked, setQueueingLinked] = useState(false);

  useEffect(() => {
    api.listWebSources().then(setSources).catch(() => {});
  }, []);

  useEffect(() => {
    if (!selectedKpId || !expandedSource) return;
    api.getKpPageStatus(expandedSource, selectedKpId)
      .then((rows) => {
        const map: Record<string, "compiled" | "not_relevant" | "none"> = {};
        rows.forEach((r) => { map[r.page_id] = r.status; });
        setKpStatusMap((prev) => ({ ...prev, [expandedSource]: map }));
      })
      .catch(() => {});
  }, [selectedKpId, expandedSource]);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setAdding(true);
    setError(null);
    try {
      const src = await api.createWebSource(addName.trim(), addUrl.trim(), addDepth, addIncludeQuery);
      setSources((s) => [...s, src]);
      setAddName("");
      setAddUrl("");
      setAddDepth(1);
      setAddIncludeQuery(false);
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
          setCrawlLog((l) => [...l.slice(-99), `+ ${ev.title || ev.url}${ev.thin_content ? " (thin content)" : ""}`]);
        } else if (ev.type === "page_updated") {
          setCrawlLog((l) => [...l.slice(-99), `↻ ${ev.title || ev.url}${ev.thin_content ? " (thin content)" : ""}`]);
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
    const kps = await api.getCompiledKps(sourceId).catch(() => []);
    setCompiledKps((prev) => ({ ...prev, [sourceId]: kps }));
  }

  async function handleViewDraft(runId: string, title: string) {
    setDraftModal({ runId, title });
    setDraftJson(null);
    setDraftLoading(true);
    try {
      const run = await api.getCurationRun(runId);
      setDraftJson(run.structured_draft ?? null);
    } catch (err) {
      setDraftJson({ error: String(err) });
    } finally {
      setDraftLoading(false);
    }
  }

  async function handleCuratePage(sourceId: string, pageId: string, showLinkedModal = false) {
    setCuratingPages((s) => new Set(s).add(pageId));
    try {
      const result = await api.curateWebPage(sourceId, pageId);
      // Update page status in local state
      setPages((prev) => ({
        ...prev,
        [sourceId]: (prev[sourceId] ?? []).map((pg) =>
          pg.id === pageId
            ? { ...pg, latest_run_id: result.run_id, latest_run_status: result.status as "succeeded" | "failed" | "running", latest_run_error: result.error_message }
            : pg
        ),
      }));
      if (showLinkedModal && result.status === "succeeded") {
        const allPages = await api.listWebPages(sourceId).catch(() => [] as import("@/lib/types").WebPage[]);
        setPages((p) => ({ ...p, [sourceId]: allPages }));
        checkLinkedPagesModal(sourceId, allPages);
      }
    } catch (err) {
      setError(String(err));
    } finally {
      setCuratingPages((s) => { const n = new Set(s); n.delete(pageId); return n; });
    }
  }

  async function handleToggleLinks(sourceId: string, pageId: string) {
    if (expandedLinks[pageId] !== undefined) {
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

  async function handleOpenLinksModal(sourceId: string, pageId: string, pageTitle: string) {
    setLinksModal({ pageId, pageTitle, sourceId });
    setLinksModalData(null);
    setLinksModalLoading(true);
    try {
      const tree = await api.getWebPageLinkTree(sourceId, pageId);
      setLinksModalData(tree);
    } catch {
      setLinksModalData(null);
    } finally {
      setLinksModalLoading(false);
    }
  }

  async function handleCurateAll(sourceId: string, filtered: import("@/lib/types").WebPage[]) {
    setCuratingAll(sourceId);
    const pending = filtered.filter(
      (pg) =>
        !pg.latest_run_status ||
        pg.latest_run_status === "failed" ||
        pg.latest_run_status === "running" ||
        pg.changed_since_extraction
    );
    for (const pg of pending) {
      await handleCuratePage(sourceId, pg.id);
    }
    setCuratingAll(null);
    // After bulk curation, check if there are linked pages needing curation
    const allPages = await api.listWebPages(sourceId).catch(() => [] as import("@/lib/types").WebPage[]);
    setPages((p) => ({ ...p, [sourceId]: allPages }));
    checkLinkedPagesModal(sourceId, allPages);
  }

  function checkLinkedPagesModal(sourceId: string, allPages: import("@/lib/types").WebPage[]) {
    const linked = allPages.filter(
      (pg) => !pg.latest_run_status || pg.changed_since_extraction
    );
    if (linked.length > 0) {
      setLinkedCurationModal({ sourceId, pages: linked, checked: new Set(linked.map((p) => p.id)) });
    }
  }

  async function handleCompile(sourceId: string, filteredPages: import("@/lib/types").WebPage[]) {
    const form = compileForm[sourceId];
    if (!form || !form.productKey.trim() || !form.name.trim() || !form.owner.trim()) return;
    const sel = selectedWebPages[sourceId];
    const pool = sel && sel.size > 0
      ? filteredPages.filter((pg) => sel.has(pg.id))
      : filteredPages;
    const pageIds = pool
      .filter((pg) => pg.latest_run_status === "succeeded")
      .map((pg) => pg.id);

    if (!pageIds.length) return;

    setCompiling((c) => ({ ...c, [sourceId]: true }));
    setCompilePageStatus((s) => ({ ...s, [sourceId]: {} }));
    setCompileProgress((p) => ({ ...p, [sourceId]: { done: 0, total: pageIds.length } }));
    setError(null);

    const token = getToken();
    try {
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1"}/curation-runs/batch-compile-stream`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
          body: JSON.stringify({
            page_ids: pageIds,
            product_key: form.productKey.trim(),
            name: form.name.trim(),
            owner: form.owner.trim(),
            created_by: user?.user_id ?? "00000000-0000-0000-0000-000000000000",
            brief: form.brief.trim() || null,
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
            // Refresh compiled KPs list
            api.getCompiledKps(sourceId).then((kps) => setCompiledKps((prev) => ({ ...prev, [sourceId]: kps }))).catch(() => {});
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

  function curationBadge(status: string | null, runId?: string | null, title?: string) {
    if (!status) return <span className="text-gray-300 text-xs">—</span>;
    const map: Record<string, string> = {
      running: "bg-yellow-100 text-yellow-700",
      succeeded: "bg-green-100 text-green-700",
      failed: "bg-red-100 text-red-700",
    };
    const label: Record<string, string> = { running: "Curating…", succeeded: "Curated", failed: "Failed" };
    if (status === "succeeded" && runId) {
      return (
        <button
          onClick={() => handleViewDraft(runId, title ?? "")}
          className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${map.succeeded} hover:ring-1 hover:ring-green-400 underline-offset-1`}
          title="View curated draft JSON"
        >
          Curated ↗
        </button>
      );
    }
    return (
      <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${map[status] ?? "bg-gray-100 text-gray-600"}`}>
        {label[status] ?? status}
      </span>
    );
  }

  async function handleConfirmLinkedCuration() {
    if (!linkedCurationModal) return;
    const { sourceId, checked } = linkedCurationModal;
    const pageIds = Array.from(checked);
    if (!pageIds.length) { setLinkedCurationModal(null); return; }
    setQueueingLinked(true);
    try {
      await api.batchQueueCuration(sourceId, pageIds);
      // Refresh pages to show pending statuses
      const refreshed = await api.listWebPages(sourceId).catch(() => [] as import("@/lib/types").WebPage[]);
      setPages((p) => ({ ...p, [sourceId]: refreshed }));
    } catch (err) {
      setError(String(err));
    } finally {
      setQueueingLinked(false);
      setLinkedCurationModal(null);
    }
  }

  return (
    <div className="space-y-6">
      {/* Linked curation confirmation modal */}
      {linkedCurationModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
          <div className="w-full max-w-lg rounded-xl border border-gray-200 bg-white shadow-xl p-6">
            <h2 className="text-sm font-semibold text-gray-900 mb-1">
              {linkedCurationModal.pages.length} linked page{linkedCurationModal.pages.length !== 1 ? "s are" : " is"} uncurated or have changed content
            </h2>
            <p className="text-xs text-gray-500 mb-4">Curate them now? They will be queued for background curation.</p>
            <div className="max-h-48 overflow-y-auto space-y-1 border border-gray-100 rounded-lg bg-gray-50 px-3 py-2 mb-4">
              {linkedCurationModal.pages.map((pg) => (
                <label key={pg.id} className="flex items-center gap-2 cursor-pointer py-0.5">
                  <input
                    type="checkbox"
                    checked={linkedCurationModal.checked.has(pg.id)}
                    onChange={(e) => {
                      setLinkedCurationModal((m) => {
                        if (!m) return m;
                        const next = new Set(m.checked);
                        if (e.target.checked) next.add(pg.id); else next.delete(pg.id);
                        return { ...m, checked: next };
                      });
                    }}
                    className="rounded border-gray-300 text-indigo-600"
                  />
                  <span className="text-xs font-medium text-gray-800 truncate max-w-xs">{pg.title}</span>
                  {pg.changed_since_extraction && (
                    <span className="text-[10px] rounded-full bg-amber-100 text-amber-700 px-1.5 py-0.5 shrink-0">Changed</span>
                  )}
                  {!pg.latest_run_status && (
                    <span className="text-[10px] rounded-full bg-gray-100 text-gray-500 px-1.5 py-0.5 shrink-0">Not curated</span>
                  )}
                </label>
              ))}
            </div>
            <div className="flex items-center justify-end gap-3">
              <button
                onClick={() => setLinkedCurationModal(null)}
                className="rounded border border-gray-300 px-4 py-2 text-xs font-medium text-gray-700 hover:bg-gray-50"
              >
                Skip
              </button>
              <button
                onClick={handleConfirmLinkedCuration}
                disabled={queueingLinked || linkedCurationModal.checked.size === 0}
                className="rounded bg-indigo-600 px-4 py-2 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
              >
                {queueingLinked ? "Queuing…" : `Curate ${linkedCurationModal.checked.size} linked page${linkedCurationModal.checked.size !== 1 ? "s" : ""}`}
              </button>
            </div>
          </div>
        </div>
      )}

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
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Crawl Depth</label>
              <select
                value={addDepth === null ? "recursive" : String(addDepth)}
                onChange={(e) => setAddDepth(e.target.value === "recursive" ? null : Number(e.target.value))}
                className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
              >
                <option value="1">1 — Direct links only</option>
                <option value="2">2 — Links of links</option>
                <option value="3">3 — Three levels deep</option>
                <option value="recursive">Recursive — entire domain</option>
              </select>
            </div>
          </div>
          <label
            className="flex items-center gap-2 text-xs text-gray-700"
            title="Enable for sites where ?id= or ?page= selects different content"
          >
            <input
              type="checkbox"
              checked={addIncludeQuery}
              onChange={(e) => setAddIncludeQuery(e.target.checked)}
              className="rounded"
            />
            Treat query strings as separate pages
          </label>
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
            const selectedStatuses = curationStatusFilter[src.id] ?? [];
            const filteredPages = applyPageFilters(srcPages, filterRows).filter((pg) => {
              if (!selectedStatuses.length) return true;
              return selectedStatuses.some((s) => {
                if (s === "not_curated") return !pg.latest_run_status;
                if (s === "curated") return pg.latest_run_status === "succeeded";
                if (s === "curation_failed") return pg.latest_run_status === "failed";
                if (s === "compiled_to_kp") return pg.is_compiled;
                if (s === "not_compiled_to_kp") return pg.latest_run_status === "succeeded" && !pg.is_compiled;
                if (s === "compile_failed") return pg.latest_compile_status === "skipped";
                return false;
              });
            });
            const hasFilter = filterRows.some((r) => r.pattern.trim()) || selectedStatuses.length > 0;

            // KP filter
            const statusMap = kpStatusMap[src.id] ?? {};
            let kpFiltered = filteredPages;
            if (selectedKpId) {
              if (showNotInKp) {
                kpFiltered = filteredPages.filter((pg) => {
                  const s = statusMap[pg.id] ?? "none";
                  return s === "not_relevant" || s === "none";
                });
              } else {
                kpFiltered = filteredPages.filter((pg) => statusMap[pg.id] === "compiled");
              }
            }
            const displayPages = kpFiltered;

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
              setCurationStatusFilter((f) => ({ ...f, [src.id]: [] }));
            }

            const crawlPending = src.crawl_status === "PENDING";
            const crawlFailed = src.crawl_status === "FAILED";
            const crawlTip = src.successful_crawl_count === 0
              ? "This source has never been successfully crawled."
              : src.successful_crawl_count === 1
              ? "Previously crawled successfully 1 time."
              : `Previously crawled successfully ${src.successful_crawl_count} times.`;

            return (
              <div key={src.id} className="rounded-lg border border-gray-200 bg-white">
                {/* Crawl FAILED warning banner */}
                {crawlFailed && !isCrawling && (
                  <div className="rounded-t-lg border-b border-amber-200 bg-amber-50 px-5 py-2 flex items-center gap-2">
                    <span className="text-amber-600">⚠</span>
                    <span className="text-xs text-amber-800 font-medium">Last crawl failed.</span>
                    <span className="text-xs text-amber-700">{crawlTip}</span>
                  </div>
                )}
                {/* Header row */}
                <div className="flex items-center justify-between px-5 py-4">
                  <div>
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-semibold text-gray-900">{src.name}</p>
                      {crawlPending && (
                        <span className="inline-flex items-center gap-1 rounded-full bg-indigo-100 px-2 py-0.5 text-xs text-indigo-700 font-medium">
                          <span className="h-1.5 w-1.5 rounded-full bg-indigo-500 animate-pulse inline-block" />
                          Crawl in progress…
                        </span>
                      )}
                    </div>
                    <a href={src.root_url} target="_blank" rel="noreferrer" className="text-xs text-blue-600 hover:underline">
                      {src.root_url}
                    </a>
                    <p className="text-xs text-gray-400 mt-0.5">
                      {src.page_count} page{src.page_count !== 1 ? "s" : ""}
                      {" · depth: "}{src.crawl_depth === null ? "recursive" : src.crawl_depth}
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
                          disabled={isCrawling || crawlPending || !!curatingAll}
                          title={curatingAll ? "Cannot crawl while curation is running" : undefined}
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
                          {/* Curation status multi-select filter */}
                          <div className="flex items-center gap-1.5">
                            <StatusMultiSelect
                              pages={srcPages}
                              selected={selectedStatuses}
                              onChange={(next) => setCurationStatusFilter((f) => ({ ...f, [src.id]: next }))}
                            />
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
                          const sel = selectedWebPages[src.id];
                          const selSize = sel?.size ?? 0;
                          const allFilteredPending = filteredPages.filter((p) => !p.latest_run_status || p.latest_run_status === "failed");
                          const allFilteredSucceeded = filteredPages.filter((p) => p.latest_run_status === "succeeded");
                          // Pending within selection
                          const pendingInSelection = selSize > 0
                            ? filteredPages.filter((p) => sel!.has(p.id) && (!p.latest_run_status || p.latest_run_status === "failed"))
                            : [];
                          const curateTarget = selSize > 0 ? pendingInSelection : allFilteredPending;
                          const curateCount = curateTarget.length;
                          // Succeeded within selection
                          const selSucceededCount = selSize > 0
                            ? filteredPages.filter((p) => sel!.has(p.id) && p.latest_run_status === "succeeded").length
                            : 0;
                          const compileCount = selSize > 0 ? selSucceededCount : allFilteredSucceeded.length;
                          const form = compileForm[src.id] ?? null;
                          const isCompiling = compiling[src.id] ?? false;
                          const lastKp = compiledKp[src.id] ?? null;
                          const failedPages = filteredPages.filter((p) => p.latest_run_status === "failed");
                          const hasFailedRuns = failedPages.length > 0;
                          const compileBlocked = hasFailedRuns;
                          const compileBlockReason = hasFailedRuns
                            ? `${failedPages.length} page${failedPages.length !== 1 ? "s" : ""} have failed curation — fix before compiling`
                            : undefined;
                          return (
                            <div className="border-b border-gray-200 bg-gray-50">
                              <div className="flex items-center justify-between px-4 py-2">
                                <div className="flex items-center gap-3">
                                  <p className="text-xs text-gray-500">
                                    {allFilteredSucceeded.length} of {filteredPages.length} curated
                                    {hasFilter && ` (filtered)`}
                                    {allFilteredPending.length > 0 && ` · ${allFilteredPending.length} pending`}
                                  </p>
                                  {selSize > 0 && (
                                    <span className="text-xs text-indigo-600 font-medium">
                                      {selSize} selected ({selSucceededCount} curated, {pendingInSelection.length} pending)
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
                                    onClick={() => handleCurateAll(src.id, curateTarget)}
                                    disabled={curatingAll === src.id || curateCount === 0 || crawlPending}
                                    title={crawlPending ? "Cannot curate while a crawl is running" : undefined}
                                    className="rounded bg-blue-600 px-3 py-1 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-40"
                                  >
                                    {curatingAll === src.id ? "Curating…" : selSize > 0 ? `Curate ${curateCount} selected` : `Curate ${curateCount} pending`}
                                  </button>
                                  <button
                                    onClick={() => setCompileForm((f) => ({ ...f, [src.id]: f[src.id] ? null : { productKey: "", name: src.name, owner: user?.display_name ?? "", brief: "" } }))}
                                    disabled={compileCount === 0 || compileBlocked}
                                    title={compileBlockReason}
                                    className={`rounded px-3 py-1 text-xs font-medium text-white disabled:opacity-40 ${selSize > 0 ? "bg-indigo-700 hover:bg-indigo-800" : "bg-indigo-600 hover:bg-indigo-700"}`}
                                  >
                                    {selSize > 0 ? `Compile ${compileCount} selected → KP` : `Compile ${compileCount} → KP`}
                                  </button>
                                  {compileBlocked && (
                                    <span className="text-xs text-red-600" title={compileBlockReason}>
                                      {failedPages.length} failed
                                    </span>
                                  )}
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
                                  </div>
                                  <div>
                                    <label className="block text-xs text-gray-500 mb-0.5">
                                      Product Brief <span className="text-gray-400">(describe what this KP is about — used to filter irrelevant pages during compilation)</span>
                                    </label>
                                    <textarea
                                      value={form.brief}
                                      onChange={(e) => setCompileForm((f) => ({ ...f, [src.id]: { ...f[src.id]!, brief: e.target.value } }))}
                                      placeholder="e.g. Customer self-service processes on posten.no — tracking parcels, managing delivery, address services and mail handling."
                                      rows={2}
                                      className="w-full rounded border border-gray-300 px-2 py-1 text-xs"
                                    />
                                  </div>
                                  <div className="flex items-center gap-2">
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
                        {showLegend && (
                          <div className="mx-0 mb-2 rounded-lg border border-indigo-100 bg-indigo-50 px-4 py-3 text-xs text-gray-700">
                            <div className="flex items-center justify-between mb-2">
                              <span className="font-semibold text-indigo-700">Status legend</span>
                              <button onClick={() => setShowLegend(false)} className="text-gray-400 hover:text-gray-600 text-sm leading-none">×</button>
                            </div>
                            <div className="grid grid-cols-2 gap-x-8 gap-y-1.5">
                              <div className="flex items-start gap-2">
                                <span className="inline-flex items-center rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700 shrink-0">Curated</span>
                                <span className="text-gray-500">LLM has analysed this page and produced a structured knowledge draft. Click the badge to view the draft JSON.</span>
                              </div>
                              <div className="flex items-start gap-2">
                                <span className="inline-flex items-center rounded-full bg-yellow-100 px-2 py-0.5 text-xs font-medium text-yellow-700 shrink-0">Curating…</span>
                                <span className="text-gray-500">Curation is currently running for this page.</span>
                              </div>
                              <div className="flex items-start gap-2">
                                <span className="inline-flex items-center rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700 shrink-0">Failed</span>
                                <span className="text-gray-500">The last curation attempt returned an error. Hover the error text for details.</span>
                              </div>
                              <div className="flex items-start gap-2">
                                <span className="inline-flex items-center rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700 shrink-0">Changed</span>
                                <span className="text-gray-500">Page content was updated by a crawl since the last curation — re-curation (and re-compile) is recommended.</span>
                              </div>
                              <div className="flex items-start gap-2">
                                <span className="inline-flex items-center rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700 shrink-0">Compiled</span>
                                <span className="text-gray-500">The curated draft has been merged into a Knowledge Product version.</span>
                              </div>
                              <div className="flex items-start gap-2">
                                <span className="inline-flex items-center rounded-full bg-indigo-100 px-2 py-0.5 text-xs font-medium text-indigo-700 shrink-0">Compiling…</span>
                                <span className="text-gray-500">Compile is in progress — this page's draft is being merged into a KP version.</span>
                              </div>
                              <div className="flex items-start gap-2">
                                <span className="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700 shrink-0">Thin content</span>
                                <span className="text-gray-500">Very little text was found during crawl. The page may require JavaScript to render fully.</span>
                              </div>
                              <div className="flex items-start gap-2">
                                <span className="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700 shrink-0">Discarded</span>
                                <span className="text-gray-500">Already compiled in a previous session for this KP — skipped to avoid double-counting.</span>
                              </div>
                              <div className="flex items-start gap-2">
                                <span className="inline-flex items-center rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700 shrink-0">In N KPs</span>
                                <span className="text-gray-500">This page has been compiled into N Knowledge Products.</span>
                              </div>
                              <div className="flex items-start gap-2">
                                <span className="inline-flex items-center rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 shrink-0">Not relevant</span>
                                <span className="text-gray-500">This page was processed during a compile but the LLM brief filter determined it was off-topic — not merged into the KP.</span>
                              </div>
                              <div className="flex items-start gap-2">
                                <span className="inline-flex items-center rounded-full bg-gray-100 px-1.5 py-0.5 text-[10px] font-medium text-gray-500 shrink-0">Not compiled</span>
                                <span className="text-gray-500">This page has never been included in a compile run for this KP — visible when "Show pages not in KP" is checked.</span>
                              </div>
                            </div>
                          </div>
                        )}
                        {/* KP filter bar */}
                        {(compiledKps[src.id]?.length ?? 0) > 0 && (
                          <div className="flex items-center gap-3 mb-2 px-4 py-2 border-b border-gray-100">
                            <label className="text-xs text-gray-500 shrink-0">Filter by KP:</label>
                            <select
                              value={selectedKpId ?? ""}
                              onChange={(e) => {
                                setSelectedKpId(e.target.value || null);
                                setShowNotInKp(false);
                              }}
                              className="rounded border border-gray-300 px-2 py-1 text-xs"
                            >
                              <option value="">All pages</option>
                              {(compiledKps[src.id] ?? []).map((kp) => (
                                <option key={kp.product_id} value={kp.product_id}>
                                  {kp.product_name} ({kp.compiled_page_count})
                                </option>
                              ))}
                            </select>
                            <label className={`flex items-center gap-1.5 text-xs ${!selectedKpId ? "opacity-40 cursor-not-allowed" : "cursor-pointer"}`}>
                              <input
                                type="checkbox"
                                checked={showNotInKp}
                                disabled={!selectedKpId}
                                onChange={(e) => setShowNotInKp(e.target.checked)}
                                className="rounded"
                              />
                              Show pages not in KP
                            </label>
                            {selectedKpId && (
                              <span className="text-xs text-gray-400">
                                {showNotInKp
                                  ? `${kpFiltered.length} page${kpFiltered.length !== 1 ? "s" : ""} not in KP`
                                  : `${kpFiltered.length} page${kpFiltered.length !== 1 ? "s" : ""} compiled`}
                              </span>
                            )}
                          </div>
                        )}
                        <div className="overflow-x-auto">
                          <table className="text-xs" style={{ tableLayout: "fixed", width: Object.values(colWidths).reduce((a, b) => a + b, 0) }}>
                            <colgroup>
                              <col style={{ width: colWidths.cb }} />
                              <col style={{ width: colWidths.title }} />
                              <col style={{ width: colWidths.url }} />
                              <col style={{ width: colWidths.curation }} />
                              <col style={{ width: colWidths.compiled_kp }} />
                              <col style={{ width: colWidths.fetched }} />
                              <col style={{ width: colWidths.action }} />
                            </colgroup>
                            <thead>
                              {(() => {
                                const sel = selectedWebPages[src.id];
                                const allSelected = displayPages.length > 0 && displayPages.every((p) => sel?.has(p.id));
                                const someSelected = !allSelected && displayPages.some((p) => sel?.has(p.id));
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
                                            if (e.target.checked) displayPages.forEach((p) => cur.add(p.id));
                                            else displayPages.forEach((p) => cur.delete(p.id));
                                            return { ...prev, [src.id]: cur };
                                          });
                                        }}
                                        className="rounded"
                                        title="Select all filtered pages"
                                      />
                                    </th>
                                    {(["title", "url", "curation"] as const).map((col, i) => (
                                      <th key={col} className="px-4 py-2 font-medium relative" style={{ width: colWidths[col] }}>
                                        <span className="inline-flex items-center gap-1">
                                          {["Title", "URL", "Curation"][i]}
                                          {col === "curation" && (
                                            <button
                                              onClick={() => setShowLegend((v) => !v)}
                                              className="inline-flex items-center justify-center w-4 h-4 rounded-full text-[10px] font-bold bg-gray-200 text-gray-500 hover:bg-indigo-100 hover:text-indigo-600 leading-none"
                                              title="Show status legend"
                                            >?</button>
                                          )}
                                        </span>
                                        <span
                                          onMouseDown={(e) => startColResize(col, e)}
                                          className="absolute right-0 top-0 h-full w-1.5 cursor-col-resize hover:bg-indigo-400 opacity-0 hover:opacity-60 active:opacity-80"
                                        />
                                      </th>
                                    ))}
                                    <th className="px-4 py-2 font-medium relative" style={{ width: colWidths.compiled_kp }}>
                                      Compiled KP
                                      <span
                                        onMouseDown={(e) => startColResize("compiled_kp", e)}
                                        className="absolute right-0 top-0 h-full w-1.5 cursor-col-resize hover:bg-indigo-400 opacity-0 hover:opacity-60 active:opacity-80"
                                      />
                                    </th>
                                    <th className="px-4 py-2 font-medium relative" style={{ width: colWidths.fetched }}>
                                      Fetched
                                      <span
                                        onMouseDown={(e) => startColResize("fetched", e)}
                                        className="absolute right-0 top-0 h-full w-1.5 cursor-col-resize hover:bg-indigo-400 opacity-0 hover:opacity-60 active:opacity-80"
                                      />
                                    </th>
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
                              {displayPages.map((pg) => {
                                const isCurating = curatingPages.has(pg.id);
                                const status = isCurating ? "running" : pg.latest_run_status;
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
                                const isSelected = selectedWebPages[src.id]?.has(pg.id) ?? false;
                                const colSpan = 7; // cb + title + url + curation + compiled_kp + fetched + action
                                const isChanged = pg.changed_since_extraction;
                                const rows: React.ReactNode[] = [
                                  <tr key={`${pg.id}-row`} className={`hover:bg-gray-50 ${isSelected ? "bg-indigo-50/40" : isChanged ? "bg-red-50" : ""}`}>
                                    <td className="px-2 py-2 text-center">
                                      <input
                                        type="checkbox"
                                        checked={isSelected}
                                        onChange={() => togglePageSelection(src.id, pg.id, srcPages)}
                                        className="rounded"
                                        title="Select for curation or compilation"
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
                                          {isCurating && (
                                            <span className="inline-block h-1.5 w-1.5 rounded-full bg-yellow-400 animate-pulse shrink-0" />
                                          )}
                                          {curationBadge(status ?? null, pg.latest_run_id, pg.title)}
                                          {isChanged && (
                                            <span className="inline-flex items-center rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700" title="Page content changed since last curation — re-curate and re-compile needed">
                                              Changed
                                            </span>
                                          )}
                                          {pg.is_thin_content && (
                                            <span className="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700" title="Very little text was found — the page may require JavaScript to render.">
                                              Thin content
                                            </span>
                                          )}
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
                                    <td className="px-4 py-2" style={{ width: colWidths.compiled_kp }}>
                                      {pg.compiled_kp_count > 0 ? (
                                        <span className="inline-flex items-center rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
                                          In {pg.compiled_kp_count} KP{pg.compiled_kp_count !== 1 ? "s" : ""}
                                        </span>
                                      ) : (
                                        <span className="text-gray-300 text-xs">—</span>
                                      )}
                                      {selectedKpId && (() => {
                                        const s = (kpStatusMap[src.id] ?? {})[pg.id];
                                        if (s === "not_relevant") return (
                                          <span className="ml-1 inline-flex items-center rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">Not relevant</span>
                                        );
                                        if (s === "none") return (
                                          <span className="ml-1 inline-flex items-center rounded-full bg-gray-100 px-1.5 py-0.5 text-[10px] font-medium text-gray-500">Not compiled</span>
                                        );
                                        return null;
                                      })()}
                                    </td>
                                    <td className="px-4 py-2 text-gray-400 whitespace-nowrap overflow-hidden">
                                      {new Date(pg.fetched_at).toLocaleString()}
                                    </td>
                                    <td className="px-4 py-2">
                                      <div className="flex items-center gap-1.5">
                                        <button
                                          onClick={() => handleOpenLinksModal(src.id, pg.id, pg.title)}
                                          disabled={linksModalLoading && linksModal?.pageId === pg.id}
                                          title="Show pages linked from this page"
                                          className="rounded border border-gray-200 px-2 py-0.5 text-xs text-gray-600 hover:bg-gray-100 disabled:opacity-40"
                                        >
                                          {linksModalLoading && linksModal?.pageId === pg.id ? "…" : "Links"}
                                        </button>
                                        {isOwner && (
                                          <button
                                            onClick={() => handleCuratePage(src.id, pg.id, true)}
                                            disabled={isCurating || crawlPending}
                                            title={crawlPending ? "Cannot curate while a crawl is running" : undefined}
                                            className="rounded border border-gray-200 px-2 py-0.5 text-xs text-gray-600 hover:bg-gray-100 disabled:opacity-40"
                                          >
                                            {isCurating ? "…" : status === "succeeded" ? "Re-curate" : "Curate"}
                                          </button>
                                        )}
                                      </div>
                                    </td>
                                  </tr>,
                                ];
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

      {/* Link tree modal */}
      {linksModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={() => setLinksModal(null)}>
          <div className="relative w-full max-w-2xl max-h-[85vh] rounded-xl bg-white shadow-2xl flex flex-col" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200">
              <div>
                <p className="text-sm font-semibold text-gray-900">Page link tree</p>
                <p className="text-xs text-gray-500 mt-0.5 truncate">{linksModal.pageTitle}</p>
              </div>
              <button onClick={() => setLinksModal(null)} className="rounded-full p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600">✕</button>
            </div>
            <div className="overflow-y-auto flex-1 px-5 py-4 text-xs">
              {linksModalLoading ? (
                <p className="text-gray-400 animate-pulse">Loading tree…</p>
              ) : !linksModalData ? (
                <p className="text-gray-400 italic">Could not load link tree. Re-crawl to populate links.</p>
              ) : (
                <LinkTreeSection data={linksModalData} sourceId={linksModal.sourceId} />
              )}
            </div>
          </div>
        </div>
      )}

      {draftModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={() => setDraftModal(null)}>
          <div
            className="relative w-full max-w-3xl max-h-[85vh] rounded-xl bg-white shadow-2xl flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-start justify-between gap-4 px-5 py-4 border-b border-gray-200">
              <div className="min-w-0">
                <p className="text-sm font-semibold text-gray-900">Curated Draft JSON</p>
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
