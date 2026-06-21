"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { NavBar } from "@/components/NavBar";
import { StatusBadge } from "@/components/StatusBadge";
import { api } from "@/lib/api";
import { getToken, redirectIfUnauthorized } from "@/lib/auth";
import type { KnowledgeProductSummary, KnowledgeProductStatus } from "@/lib/types";

type SortKey = "name" | "status" | "semver";

export default function ProductsPage() {
  const router = useRouter();
  const [products, setProducts] = useState<KnowledgeProductSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<KnowledgeProductStatus | "all">("all");
  const [sortKey, setSortKey] = useState<SortKey>("name");

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    api.listProducts().then(setProducts).catch((err) => {
      if (!redirectIfUnauthorized(err, router)) setError(String(err));
    });
  }, [router]);

  const filtered = useMemo(() => {
    if (!products) return [];
    return products
      .filter((p) => statusFilter === "all" || p.current_status === statusFilter)
      .filter((p) => p.name.toLowerCase().includes(search.toLowerCase()) || p.product_key.includes(search))
      .sort((a, b) => {
        if (sortKey === "name") return a.name.localeCompare(b.name);
        if (sortKey === "status") return a.current_status.localeCompare(b.current_status);
        return a.current_semver.localeCompare(b.current_semver);
      });
  }, [products, search, statusFilter, sortKey]);

  if (error) return <div className="p-8 text-sm text-red-600">Error: {error}</div>;

  return (
    <div className="min-h-screen bg-gray-50">
      <NavBar />
      <main className="mx-auto max-w-5xl px-6 py-8">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold text-gray-900">Knowledge Products</h1>
          <Link
            href="/products/new"
            className="rounded bg-gray-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-gray-700"
          >
            + New
          </Link>
        </div>

        <div className="mt-4 flex gap-3">
          <input
            placeholder="Search by name or key..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-64 rounded border border-gray-300 px-3 py-2 text-sm"
          />
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as KnowledgeProductStatus | "all")}
            className="rounded border border-gray-300 px-3 py-2 text-sm"
          >
            <option value="all">All statuses</option>
            <option value="draft">Draft</option>
            <option value="review">Review</option>
            <option value="approved">Approved</option>
            <option value="published">Published</option>
            <option value="retired">Retired</option>
          </select>
          <select
            value={sortKey}
            onChange={(e) => setSortKey(e.target.value as SortKey)}
            className="rounded border border-gray-300 px-3 py-2 text-sm"
          >
            <option value="name">Sort: Name</option>
            <option value="status">Sort: Status</option>
            <option value="semver">Sort: Version</option>
          </select>
        </div>

        {!products ? (
          <div className="mt-8 text-sm text-gray-500">Loading...</div>
        ) : (
          <table className="mt-6 w-full overflow-hidden rounded-lg border border-gray-200 bg-white text-sm">
            <thead className="bg-gray-50 text-left text-xs uppercase text-gray-500">
              <tr>
                <th className="px-4 py-2">Name</th>
                <th className="px-4 py-2">Key</th>
                <th className="px-4 py-2">Owner</th>
                <th className="px-4 py-2">Version</th>
                <th className="px-4 py-2">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {filtered.map((p) => (
                <tr key={p.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3">
                    <Link href={`/products/${p.id}`} className="font-medium text-gray-900 hover:underline">
                      {p.name}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-gray-500">{p.product_key}</td>
                  <td className="px-4 py-3 text-gray-500">{p.owner}</td>
                  <td className="px-4 py-3 text-gray-500">v{p.current_semver}</td>
                  <td className="px-4 py-3">
                    <StatusBadge status={p.current_status} />
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-gray-500">
                    No matching Knowledge Products.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </main>
    </div>
  );
}
