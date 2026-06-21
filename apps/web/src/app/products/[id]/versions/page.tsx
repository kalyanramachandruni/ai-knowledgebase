"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { NavBar } from "@/components/NavBar";
import { StatusBadge } from "@/components/StatusBadge";
import { api } from "@/lib/api";
import { getToken, redirectIfUnauthorized } from "@/lib/auth";
import type { KnowledgeProductVersion, VersionDiff } from "@/lib/types";

export default function VersionHistoryPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [versions, setVersions] = useState<KnowledgeProductVersion[] | null>(null);
  const [productName, setProductName] = useState("");
  const [fromId, setFromId] = useState<string>("");
  const [toId, setToId] = useState<string>("");
  const [diff, setDiff] = useState<VersionDiff | null>(null);
  const [error, setError] = useState<string | null>(null);

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
          {[...versions].reverse().map((v) => (
            <div key={v.id} className="flex items-center justify-between px-4 py-3">
              <span className="text-sm font-medium text-gray-900">v{v.semver}</span>
              <StatusBadge status={v.status} />
            </div>
          ))}
        </div>

        <div className="mt-8 rounded-lg border border-gray-200 bg-white p-5">
          <h2 className="text-sm font-semibold text-gray-900">Compare versions</h2>
          <div className="mt-3 flex items-center gap-3">
            <select value={fromId} onChange={(e) => setFromId(e.target.value)} className="rounded border border-gray-300 px-3 py-2 text-sm">
              {versions.map((v) => (
                <option key={v.id} value={v.id}>
                  v{v.semver}
                </option>
              ))}
            </select>
            <span className="text-sm text-gray-400">vs</span>
            <select value={toId} onChange={(e) => setToId(e.target.value)} className="rounded border border-gray-300 px-3 py-2 text-sm">
              {versions.map((v) => (
                <option key={v.id} value={v.id}>
                  v{v.semver}
                </option>
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
