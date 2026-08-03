"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { NavBar } from "@/components/NavBar";
import { StatusBadge } from "@/components/StatusBadge";
import { api } from "@/lib/api";
import { getToken, redirectIfUnauthorized } from "@/lib/auth";
import type { CompiledPageSession, KnowledgeProductVersion, VersionDiff } from "@/lib/types";

function fmt(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function CompiledPagesPanel({ productId, versionId }: { productId: string; versionId: string }) {
  const [sessions, setSessions] = useState<CompiledPageSession[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expandedSessions, setExpandedSessions] = useState<Set<string>>(new Set());

  useEffect(() => {
    api.getCompiledPages(productId, versionId)
      .then(setSessions)
      .catch((e) => setError(String(e)));
  }, [productId, versionId]);

  if (error) return <p className="mt-2 text-xs text-red-500">{error}</p>;
  if (!sessions) return <p className="mt-2 text-xs text-gray-400">Loading…</p>;
  if (sessions.length === 0) return <p className="mt-2 text-xs text-gray-400 italic">No pages compiled into this version.</p>;

  const totalPages = sessions.reduce((n, s) => n + s.pages.length, 0);

  return (
    <div className="mt-3 border-t border-gray-100 pt-3">
      <p className="text-xs font-medium text-gray-500 mb-2">
        {totalPages} page{totalPages !== 1 ? "s" : ""} across {sessions.length} compile session{sessions.length !== 1 ? "s" : ""}
      </p>
      <div className="space-y-2">
        {sessions.map((session, si) => {
          const isOpen = expandedSessions.has(session.session_id);
          return (
            <div key={session.session_id} className="rounded border border-gray-200 bg-gray-50">
              <button
                className="flex w-full items-center justify-between px-3 py-2 text-left"
                onClick={() => setExpandedSessions((prev) => {
                  const next = new Set(prev);
                  if (isOpen) next.delete(session.session_id);
                  else next.add(session.session_id);
                  return next;
                })}
              >
                <span className="text-xs font-medium text-gray-700">
                  Session {si + 1}{session.product_name ? ` — ${session.product_name}` : ""} — {fmt(session.created_at)}
                </span>
                <span className="flex items-center gap-2 text-xs text-gray-400">
                  {session.pages.length} page{session.pages.length !== 1 ? "s" : ""}
                  <span>{isOpen ? "▲" : "▼"}</span>
                </span>
              </button>

              {isOpen && (
                <div className="border-t border-gray-200 overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="bg-gray-100 text-gray-500 text-left">
                        <th className="px-3 py-1.5 font-medium">Status</th>
                        <th className="px-3 py-1.5 font-medium">Page title</th>
                        <th className="px-3 py-1.5 font-medium">Page ID</th>
                        <th className="px-3 py-1.5 font-medium">Run ID</th>
                        <th className="px-3 py-1.5 font-medium">Compiled at</th>
                        <th className="px-3 py-1.5 font-medium">Reason</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {session.pages.map((page, pi) => {
                        const isDiscarded = page.status !== "compiled";
                        return (
                          <tr key={page.run_id ?? pi} className={isDiscarded ? "bg-gray-50 opacity-60" : "bg-white hover:bg-gray-50"}>
                            <td className="px-3 py-1.5 whitespace-nowrap">
                              {page.status === "compiled" && (
                                <span className="inline-flex items-center rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">Compiled</span>
                              )}
                              {page.status === "discarded" && (
                                <span className="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">Discarded</span>
                              )}
                              {page.status === "skipped" && (
                                <span className="inline-flex items-center rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">Failed</span>
                              )}
                            </td>
                            <td className="px-3 py-1.5 font-medium text-gray-800 max-w-[200px] truncate" title={page.title ?? ""}>
                              {page.title || "—"}
                            </td>
                            <td className="px-3 py-1.5 text-gray-400 font-mono" title={page.page_id ?? ""}>{page.page_id ? `${page.page_id.slice(0, 8)}…` : "—"}</td>
                            <td className="px-3 py-1.5 text-gray-400 font-mono" title={page.run_id ?? ""}>
                              {page.run_id ? `${page.run_id.slice(0, 8)}…` : "—"}
                            </td>
                            <td className="px-3 py-1.5 text-gray-500 whitespace-nowrap">{fmt(page.compiled_at)}</td>
                            <td className="px-3 py-1.5 text-gray-400 max-w-[180px] truncate" title={page.reason ?? ""}>
                              {page.reason ?? "—"}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function VersionHistoryPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [versions, setVersions] = useState<KnowledgeProductVersion[] | null>(null);
  const [productName, setProductName] = useState("");
  const [fromId, setFromId] = useState<string>("");
  const [toId, setToId] = useState<string>("");
  const [diff, setDiff] = useState<VersionDiff | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expandedVersions, setExpandedVersions] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    Promise.all([api.getProduct(params.id), api.listVersions(params.id)])
      .then(([product, vers]) => {
        setProductName(product.name);
        setVersions(vers);
        if (vers.length >= 2) {
          setFromId(vers[vers.length - 2].id);
          setToId(vers[vers.length - 1].id);
        }
      })
      .catch((err) => {
        if (!redirectIfUnauthorized(err, router)) setError(String(err));
      });
  }, [params.id, router]);

  async function runDiff() {
    if (!fromId || !toId) return;
    setError(null);
    try {
      const result = await api.compareVersions(params.id, fromId, toId);
      setDiff(result);
    } catch (err) {
      setError(String(err));
    }
  }

  if (error) return <div className="p-8 text-sm text-red-600">Error: {error}</div>;
  if (!versions) return <div className="p-8 text-sm text-gray-500">Loading...</div>;

  return (
    <div className="min-h-screen bg-gray-50">
      <NavBar />
      <main className="mx-auto max-w-4xl px-6 py-8">
        <Link href={`/products/${params.id}`} className="text-sm text-blue-600 hover:underline">
          ← Back to {productName || "product"}
        </Link>
        <h1 className="mt-2 text-xl font-semibold text-gray-900">Version History</h1>

        <div className="mt-4 divide-y divide-gray-200 rounded-lg border border-gray-200 bg-white">
          {[...versions].reverse().map((v) => {
            const isOpen = expandedVersions.has(v.id);
            return (
              <div key={v.id} className="px-4 py-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span className="text-sm font-semibold text-gray-900">v{v.semver}</span>
                    <StatusBadge status={v.status} />
                  </div>
                  <button
                    onClick={() => setExpandedVersions((prev) => {
                      const next = new Set(prev);
                      if (isOpen) next.delete(v.id);
                      else next.add(v.id);
                      return next;
                    })}
                    className="text-xs text-blue-600 hover:underline"
                  >
                    {isOpen ? "Hide pages ▲" : "View compiled pages ▼"}
                  </button>
                </div>
                {isOpen && (
                  <CompiledPagesPanel productId={params.id} versionId={v.id} />
                )}
              </div>
            );
          })}
        </div>

        <div className="mt-8 rounded-lg border border-gray-200 bg-white p-5">
          <h2 className="text-sm font-semibold text-gray-900">Compare versions</h2>
          <div className="mt-3 flex items-center gap-3">
            <select value={fromId} onChange={(e) => setFromId(e.target.value)} className="rounded border border-gray-300 px-3 py-2 text-sm">
              {versions.map((v) => (
                <option key={v.id} value={v.id}>v{v.semver}</option>
              ))}
            </select>
            <span className="text-sm text-gray-400">vs</span>
            <select value={toId} onChange={(e) => setToId(e.target.value)} className="rounded border border-gray-300 px-3 py-2 text-sm">
              {versions.map((v) => (
                <option key={v.id} value={v.id}>v{v.semver}</option>
              ))}
            </select>
            <button onClick={runDiff} className="rounded bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-700">
              Diff
            </button>
          </div>

          {diff && (
            <div className="mt-4 space-y-3">
              {Object.keys(diff.diff).length === 0 ? (
                <p className="text-sm text-gray-500">No differences.</p>
              ) : (
                Object.entries(diff.diff).map(([field, change]) => (
                  <div key={field} className="rounded border border-gray-200 p-3">
                    <div className="text-xs font-semibold uppercase text-gray-500">{field}</div>
                    <div className="mt-2 grid grid-cols-2 gap-3 text-xs">
                      <pre className="overflow-x-auto rounded bg-red-50 p-2 text-red-800">
                        {JSON.stringify(change.from, null, 2)}
                      </pre>
                      <pre className="overflow-x-auto rounded bg-green-50 p-2 text-green-800">
                        {JSON.stringify(change.to, null, 2)}
                      </pre>
                    </div>
                  </div>
                ))
              )}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
