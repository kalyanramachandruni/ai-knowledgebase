"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { NavBar } from "@/components/NavBar";
import { StatusBadge } from "@/components/StatusBadge";
import { api } from "@/lib/api";
import { getToken, redirectIfUnauthorized } from "@/lib/auth";
import type { KnowledgeProductSummary } from "@/lib/types";

export default function DashboardPage() {
  const router = useRouter();
  const [products, setProducts] = useState<KnowledgeProductSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    api.listProducts().then(setProducts).catch((err) => {
      if (!redirectIfUnauthorized(err, router)) setError(String(err));
    });
  }, [router]);

  if (error) return <Centered text={`Error: ${error}`} />;
  if (!products) return <Centered text="Loading..." />;

  const total = products.length;
  const published = products.filter((p) => p.current_status === "published").length;
  const pendingReview = products.filter((p) => p.current_status === "review").length;
  const recent = [...products].slice(0, 5);

  return (
    <div className="min-h-screen bg-gray-50">
      <NavBar />
      <main className="mx-auto max-w-5xl px-6 py-8">
        <h1 className="text-xl font-semibold text-gray-900">Dashboard</h1>

        <div className="mt-6 grid grid-cols-3 gap-4">
          <StatCard label="Total Knowledge Products" value={total} />
          <StatCard label="Published Products" value={published} />
          <StatCard label="Pending Reviews" value={pendingReview} />
        </div>

        <div className="mt-8">
          <h2 className="text-sm font-medium text-gray-700">Recent Changes</h2>
          <div className="mt-3 divide-y divide-gray-200 rounded-lg border border-gray-200 bg-white">
            {recent.map((p) => (
              <Link
                key={p.id}
                href={`/products/${p.id}`}
                className="flex items-center justify-between px-4 py-3 hover:bg-gray-50"
              >
                <div>
                  <div className="text-sm font-medium text-gray-900">{p.name}</div>
                  <div className="text-xs text-gray-500">
                    {p.product_key} · v{p.current_semver}
                  </div>
                </div>
                <StatusBadge status={p.current_status} />
              </Link>
            ))}
            {recent.length === 0 && <div className="px-4 py-6 text-sm text-gray-500">No products yet.</div>}
          </div>
        </div>
      </main>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-5">
      <div className="text-2xl font-semibold text-gray-900">{value}</div>
      <div className="mt-1 text-sm text-gray-500">{label}</div>
    </div>
  );
}

function Centered({ text }: { text: string }) {
  return <div className="flex min-h-screen items-center justify-center text-sm text-gray-500">{text}</div>;
}
