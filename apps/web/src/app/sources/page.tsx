"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { NavBar } from "@/components/NavBar";
import { api, ApiError } from "@/lib/api";
import { getToken, getUser, redirectIfUnauthorized } from "@/lib/auth";
import type { ConfluencePage, ConfluencePageDetail, ConfluenceSpace, ExtractionRun, KnowledgeProduct, CompiledProductSummary } from "@/lib/types";

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

type BulkStatus = "idle" | "extracting" | "extracted" | "compiling" | "compiled" | "failed";

function PagesTab({ isOwner, router, user }: { isOwner: boolean; router: ReturnType<typeof useRouter>; user: ReturnType<typeof getUser> }) {
  const [spaces, setSpaces] = useState<ConfluenceSpace[]>([]);
  const [selectedSpace, setSelectedSpace] = useState<string>("");
  const [pages, setPages] = useState<ConfluencePage[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [pageDetails, setPageDetails] = useState<Record<string, ConfluencePageDetail | null>>({});
  const [loadingDetail, setLoadingDetail] = useState<Record<string, boolean>>({});
  const [extracting, setExtracting] = useState<Record<string, boolean>>({});
  const [runs, setRuns] = useState<Record<string, ExtractionRun>>({});
  const [compiling, setCompiling] = useState<Record<string, boolean>>({});
  const [compiled, setCompiled] = useState<Record<string, KnowledgeProduct>>({});
  const [compiledSummaries, setCompiledSummaries] = useState<Record<string, CompiledProductSummary[]>>({});
  const [compileForm, setCompileForm] = useState<Record<string, { name: string; key: string; owner: string }>>({});
  const [search, setSearch] = useState("");
  const [bulkStatus, setBulkStatus] = useState<Record<string, BulkStatus>>({});
  const [bulkRunning, setBulkRunning] = useState(false);
  const [bulkProductKey, setBulkProductKey] = useState("");
  const [bulkProductName, setBulkProductName] = useState("");
  const [bulkOwner, setBulkOwner] = useState("");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [productFilter, setProductFilter] = useState<Set<string>>(new Set());
  const [productDropdownOpen, setProductDropdownOpen] = useState(false);

  useEffect(() => {
    api.listConfluenceSpaces().then(setSpaces).catch(() => {});
  }, []);

  useEffect(() => {
    if (!productDropdownOpen) return;
    const close = (e: MouseEvent) => {
      if (!(e.target as Element).closest("[data-product-dropdown]")) {
        setProductDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [productDropdownOpen]);

  useEffect(() => {
    setPages(null);
    setRuns({});
    setCompiled({});
    setCompiledSummaries({});
    setProductFilter(new Set());
    setSelectedIds(new Set());
    api.listConfluencePages(selectedSpace || undefined)
      .then(async (fetchedPages) => {
        setPages(fetchedPages);
        // Load extraction history for all pages in parallel
        const histories = await Promise.all(
          fetchedPages.map((p) =>
            api.getPageExtractionHistory(p.id).catch(() => [] as ExtractionRun[])
          )
        );
        const newRuns: Record<string, ExtractionRun> = {};
        const newCompiled: Record<string, CompiledProductSummary[]> = {};
        fetchedPages.forEach((p, i) => {
          const pageRuns = histories[i]; // sorted desc by started_at
          if (pageRuns.length > 0) newRuns[p.id] = pageRuns[0];
          // Collect all distinct products this page was compiled into
          const seen = new Set<string>();
          const products: CompiledProductSummary[] = [];
          for (const run of pageRuns) {
            if (run.compiled_product && !seen.has(run.compiled_product.product_key)) {
              seen.add(run.compiled_product.product_key);
              products.push(run.compiled_product);
            }
          }
          if (products.length > 0) newCompiled[p.id] = products;
        });
        setRuns(newRuns);
        setCompiledSummaries(newCompiled);
      })
      .catch((err) => {
        if (!redirectIfUnauthorized(err, router)) setError(String(err));
      });
  }, [selectedSpace, router]);

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
      setCompiledSummaries((c) => {
        const newEntry: CompiledProductSummary = {
          product_id: product.id, product_key: product.product_key, name: product.name,
          version_id: product.current_version.id, semver: product.current_version.semver,
        };
        const existing = (c[pageId] ?? []).filter((s) => s.product_key !== product.product_key);
        return { ...c, [pageId]: [newEntry, ...existing] };
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setCompiling((c) => ({ ...c, [pageId]: false }));
    }
  }

  function toggleSelect(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  function toggleSelectAll(filteredPages: ConfluencePage[]) {
    if (filteredPages.every((p) => selectedIds.has(p.id))) {
      // Deselect only the currently filtered pages, leave others intact
      setSelectedIds((prev) => {
        const next = new Set(prev);
        filteredPages.forEach((p) => next.delete(p.id));
        return next;
      });
    } else {
      setSelectedIds((prev) => new Set([...prev, ...filteredPages.map((p) => p.id)]));
    }
  }

  async function handleBulkExtractCompile(filteredPages: ConfluencePage[]) {
    if (!bulkProductKey || !bulkProductName || !bulkOwner) {
      setError("Fill in Product Key, Product Name, and Owner before running bulk extract & compile.");
      return;
    }
    if (!user?.user_id) { setError("Not logged in."); return; }
    setBulkRunning(true);
    setError(null);

    // Phase 1: extract all pages, collect succeeded run IDs
    const succeededRunIds: string[] = [];
    for (const page of filteredPages) {
      setBulkStatus((s) => ({ ...s, [page.id]: "extracting" }));
      try {
        const run = await api.extractPage(page.id);
        setRuns((r) => ({ ...r, [page.id]: run }));
        if (run.status === "failed") {
          setBulkStatus((s) => ({ ...s, [page.id]: "failed" }));
        } else {
          succeededRunIds.push(run.id);
          setBulkStatus((s) => ({ ...s, [page.id]: "extracted" }));
        }
      } catch {
        setBulkStatus((s) => ({ ...s, [page.id]: "failed" }));
      }
    }

    if (succeededRunIds.length === 0) {
      setError("All extractions failed — nothing to compile.");
      setBulkRunning(false);
      return;
    }

    // Phase 2: single batch-compile from all succeeded runs → one KP version
    filteredPages.forEach((page) => {
      setBulkStatus((s) => s[page.id] === "extracted" ? { ...s, [page.id]: "compiling" } : s);
    });
    try {
      const product = await api.batchCompile({
        run_ids: succeededRunIds,
        product_key: bulkProductKey,
        name: bulkProductName,
        owner: bulkOwner,
        created_by: user.user_id,
      });
      const newEntry: CompiledProductSummary = {
        product_id: product.id, product_key: product.product_key, name: product.name,
        version_id: product.current_version.id, semver: product.current_version.semver,
      };
      // Mark every successfully extracted page as compiled and update their summary
      filteredPages.forEach((page) => {
        setCompiled((c) => ({ ...c, [page.id]: product }));
        setCompiledSummaries((cs) => {
          const existing = (cs[page.id] ?? []).filter((s) => s.product_key !== product.product_key);
          return { ...cs, [page.id]: [newEntry, ...existing] };
        });
        setBulkStatus((s) => s[page.id] !== "failed" ? { ...s, [page.id]: "compiled" } : s);
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Batch compile failed");
      filteredPages.forEach((page) => {
        setBulkStatus((s) => s[page.id] === "compiling" ? { ...s, [page.id]: "failed" } : s);
      });
    }
    setBulkRunning(false);
  }

  // Distinct products across all pages for the filter dropdown
  const compiledProducts = Object.values(
    Object.values(compiledSummaries).flat().reduce<Record<string, CompiledProductSummary>>((acc, s) => {
      acc[s.product_key] = s;
      return acc;
    }, {})
  ).sort((a, b) => a.name.localeCompare(b.name));

  const filtered = (pages ?? []).filter((p) => {
    if (search && !p.title.toLowerCase().includes(search.toLowerCase())) return false;
    if (productFilter.size > 0) {
      const pageProductKeys = (compiledSummaries[p.id] ?? []).map((s) => s.product_key);
      if (productFilter.has("__uncompiled__") && pageProductKeys.length === 0) return true;
      return pageProductKeys.some((k) => productFilter.has(k));
    }
    return true;
  });

  if (!pages) return <p className="text-sm text-gray-500">Loading pages...</p>;

  return (
    <>
      {error && <p className="mb-3 text-sm text-red-600">{error}</p>}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <select
          value={selectedSpace}
          onChange={(e) => { setSelectedSpace(e.target.value); setProductFilter(new Set()); setSelectedIds(new Set()); }}
          className="rounded border border-gray-300 px-3 py-2 text-sm bg-white"
        >
          <option value="">All spaces</option>
          {spaces.map((s) => (
            <option key={s.id} value={s.space_key}>{s.name} ({s.space_key})</option>
          ))}
        </select>

        {/* Multi-select product filter */}
        <div className="relative" data-product-dropdown>
          <button
            onClick={() => setProductDropdownOpen((o) => !o)}
            className="flex items-center gap-2 rounded border border-gray-300 px-3 py-2 text-sm bg-white hover:bg-gray-50 min-w-[160px]"
          >
            <span className="flex-1 text-left">
              {productFilter.size === 0
                ? "All products"
                : productFilter.size === 1 && productFilter.has("__uncompiled__")
                ? "Not compiled yet"
                : productFilter.size === 1
                ? compiledProducts.find((p) => productFilter.has(p.product_key))?.name ?? "1 product"
                : `${productFilter.size} selected`}
            </span>
            <span className="text-gray-400 text-xs">▼</span>
          </button>
          {productDropdownOpen && (
            <div className="absolute z-20 mt-1 left-0 min-w-[220px] rounded-lg border border-gray-200 bg-white shadow-lg py-1">
              <label
                className="flex items-center gap-2 px-3 py-1.5 text-xs text-gray-500 hover:bg-gray-50 cursor-pointer border-b border-gray-100"
                onClick={() => { setProductFilter(new Set()); setSelectedIds(new Set()); }}
              >
                <input type="checkbox" readOnly checked={productFilter.size === 0} className="rounded" />
                All products
              </label>
              <label className="flex items-center gap-2 px-3 py-1.5 text-sm hover:bg-gray-50 cursor-pointer border-b border-gray-100">
                <input
                  type="checkbox"
                  className="rounded"
                  checked={productFilter.has("__uncompiled__")}
                  onChange={() => {
                    setProductFilter((prev) => {
                      const next = new Set(prev);
                      next.has("__uncompiled__") ? next.delete("__uncompiled__") : next.add("__uncompiled__");
                      const ids = new Set(
                        (pages ?? []).filter((p) => {
                          const pageKeys = (compiledSummaries[p.id] ?? []).map((s) => s.product_key);
                          if (next.has("__uncompiled__") && pageKeys.length === 0) return true;
                          return pageKeys.some((k) => next.has(k));
                        }).map((p) => p.id)
                      );
                      setSelectedIds(ids);
                      return next;
                    });
                  }}
                />
                <span className="truncate text-gray-500 italic">Not compiled yet</span>
              </label>
              {compiledProducts.map((p) => (
                <label key={p.product_key} className="flex items-center gap-2 px-3 py-1.5 text-sm hover:bg-gray-50 cursor-pointer">
                  <input
                    type="checkbox"
                    className="rounded"
                    checked={productFilter.has(p.product_key)}
                    onChange={() => {
                      setProductFilter((prev) => {
                        const next = new Set(prev);
                        next.has(p.product_key) ? next.delete(p.product_key) : next.add(p.product_key);
                        const ids = new Set(
                          (pages ?? []).filter((p2) => {
                            const pageKeys = (compiledSummaries[p2.id] ?? []).map((s) => s.product_key);
                            if (next.has("__uncompiled__") && pageKeys.length === 0) return true;
                            return pageKeys.some((k) => next.has(k));
                          }).map((p2) => p2.id)
                        );
                        setSelectedIds(ids);
                        return next;
                      });
                    }}
                  />
                  <span className="truncate">{p.name}</span>
                </label>
              ))}
              {compiledProducts.length === 0 && (
                <p className="px-3 py-2 text-xs text-gray-400">No compiled products yet</p>
              )}
            </div>
          )}
        </div>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search pages..."
          className="w-full max-w-xs rounded border border-gray-300 px-3 py-2 text-sm"
        />
        <label className="flex items-center gap-1.5 text-sm text-gray-600 cursor-pointer select-none">
          <input
            type="checkbox"
            className="rounded"
            checked={filtered.length > 0 && filtered.every((p) => selectedIds.has(p.id))}
            ref={(el) => {
              if (el) el.indeterminate = selectedIds.size > 0 && !filtered.every((p) => selectedIds.has(p.id));
            }}
            onChange={() => toggleSelectAll(filtered)}
          />
          Select all
        </label>
        <span className="text-sm text-gray-500">
          {selectedIds.size > 0 ? `${selectedIds.size} selected · ` : ""}{filtered.length} pages
        </span>
      </div>

      {isOwner && filtered.length > 0 && (
        <div className="mb-5 rounded-lg border border-blue-100 bg-blue-50 p-4">
          <p className="text-sm font-medium text-blue-900 mb-3">Bulk Extract &amp; Compile</p>
          <div className="flex flex-wrap gap-2 mb-3">
            <input value={bulkProductKey} onChange={(e) => setBulkProductKey(e.target.value)}
              placeholder="product-key" className="rounded border border-gray-300 px-2 py-1 text-xs w-36" />
            <input value={bulkProductName} onChange={(e) => setBulkProductName(e.target.value)}
              placeholder="Product name" className="rounded border border-gray-300 px-2 py-1 text-xs w-44" />
            <input value={bulkOwner} onChange={(e) => setBulkOwner(e.target.value)}
              placeholder="Owner" className="rounded border border-gray-300 px-2 py-1 text-xs w-32" />
            <button
              onClick={() => {
                const target = selectedIds.size > 0
                  ? filtered.filter((p) => selectedIds.has(p.id))
                  : filtered;
                handleBulkExtractCompile(target);
              }}
              disabled={bulkRunning}
              className="rounded bg-blue-700 px-4 py-1 text-xs font-medium text-white hover:bg-blue-800 disabled:opacity-50"
            >
              {bulkRunning ? "Processing..." : selectedIds.size > 0
                ? `Extract & Compile ${selectedIds.size} selected`
                : `Extract & Compile all ${filtered.length} pages`}
            </button>
          </div>
          <p className="text-xs text-blue-700">Pages processed one at a time. LLM merges each page into the same product.</p>
        </div>
      )}

      <div className="space-y-3">
        {filtered.map((page) => {
          const run = runs[page.id];
          const summaries = compiledSummaries[page.id] ?? [];
          const bStatus = bulkStatus[page.id];
          const form = compileForm[page.id] ?? { name: page.title, key: page.title.toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 40), owner: user?.display_name ?? "" };

          return (
            <div key={page.id} className={`rounded-lg border bg-white p-4 ${selectedIds.has(page.id) ? "border-blue-300 ring-1 ring-blue-200" : "border-gray-200"}`}>
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-start gap-3">
                  <input
                    type="checkbox"
                    className="mt-0.5 rounded cursor-pointer"
                    checked={selectedIds.has(page.id)}
                    onChange={() => toggleSelect(page.id)}
                  />
                  <div>
                    <p className="text-sm font-medium text-gray-900">{page.title}</p>
                    <p className="text-xs text-gray-400 mt-0.5">
                      {page.space_key} · v{page.confluence_version} · {new Date(page.last_modified_at).toLocaleDateString()}
                    </p>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {bStatus && (
                    <span className={`rounded px-2 py-0.5 text-xs font-medium ${
                      bStatus === "compiled" ? "bg-green-100 text-green-800" :
                      bStatus === "failed" ? "bg-red-100 text-red-800" :
                      bStatus === "extracting" || bStatus === "compiling" ? "bg-yellow-100 text-yellow-800" :
                      "bg-blue-100 text-blue-800"
                    }`}>
                      {bStatus === "extracting" ? "Extracting..." :
                       bStatus === "extracted" ? "Extracted" :
                       bStatus === "compiling" ? "Compiling..." :
                       bStatus === "compiled" ? "Compiled" : "Failed"}
                    </span>
                  )}
                  <button
                    onClick={() => handleToggleContent(page.id)}
                    className="rounded border border-gray-200 px-2 py-1 text-xs text-gray-500 hover:bg-gray-50"
                  >
                    {expanded[page.id] ? "▲ Hide" : "▼ Content"}
                  </button>
                  {isOwner && !run && !bStatus && (
                    <button
                      onClick={() => handleExtract(page.id)}
                      disabled={extracting[page.id]}
                      className="rounded border border-gray-300 px-3 py-1 text-xs font-medium hover:bg-gray-50 disabled:opacity-50"
                    >
                      {extracting[page.id] ? "Extracting..." : "Extract"}
                    </button>
                  )}
                </div>
              </div>

              {expanded[page.id] && (
                <div className="mt-3 border-t border-gray-100 pt-3">
                  {loadingDetail[page.id] ? (
                    <p className="text-xs text-gray-400">Loading content...</p>
                  ) : pageDetails[page.id] === null ? (
                    <p className="text-xs text-red-500">Failed to load content.</p>
                  ) : pageDetails[page.id] ? (
                    <pre className="whitespace-pre-wrap text-xs text-gray-700 font-sans leading-relaxed max-h-64 overflow-y-auto">
                      {pageDetails[page.id]!.plain_text || "(no text content)"}
                    </pre>
                  ) : null}
                </div>
              )}

              {run && (
                <div className="mt-3 border-t border-gray-100 pt-3">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${
                      run.status === "succeeded" ? "bg-green-100 text-green-800" :
                      run.status === "failed" ? "bg-red-100 text-red-800" :
                      "bg-yellow-100 text-yellow-800"
                    }`}>
                      {run.status}
                    </span>
                    <span className="text-xs text-gray-400">{run.llm_model}</span>
                    {run.started_at && (
                      <span className="text-xs text-gray-400">
                        · {new Date(run.started_at).toLocaleString()}
                      </span>
                    )}
                  </div>

                  {run.status === "failed" && run.error_message && (
                    <p className="mt-1 text-xs text-red-600">{run.error_message}</p>
                  )}

                  {run.status === "succeeded" && summaries.length === 0 && !bStatus && (
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

                  {summaries.length > 0 && (
                    <div className="mt-2">
                      <p className="text-xs text-gray-500 font-medium mb-1">Compiled into:</p>
                      <div className="flex flex-wrap gap-1.5">
                        {summaries.map((s) => (
                          <button
                            key={s.product_key}
                            onClick={() => router.push(`/products/${s.product_id}`)}
                            className="inline-flex items-center gap-1 rounded-full bg-green-50 border border-green-200 px-2.5 py-0.5 text-xs text-green-800 hover:bg-green-100"
                          >
                            {s.name}
                            <span className="text-green-500">v{s.semver}</span>
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
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
