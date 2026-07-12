"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { NavBar } from "@/components/NavBar";
import { api, ApiError } from "@/lib/api";
import { getUser } from "@/lib/auth";

export default function NewProductPage() {
  const router = useRouter();
  const user = getUser();
  const [productKey, setProductKey] = useState("");
  const [name, setName] = useState("");
  const [owner, setOwner] = useState("");
  const [steps, setSteps] = useState("");
  const [slaTarget, setSlaTarget] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!user) return;
    setError(null);
    setLoading(true);
    try {
      const product = await api.createProduct({
        product_key: productKey,
        name,
        owner,
        compile: {
          process_steps: steps.split("\n").map((s) => s.trim()).filter(Boolean).map((name) => ({ name })),
          rules: [],
          policies: [],
          sla_target: slaTarget || null,
          escalations: [],
          roles: [],
          tools: [],
          bump: "major",
          created_by: user.user_id,
        },
      });
      router.push(`/products/${product.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <NavBar />
      <main className="mx-auto max-w-2xl px-6 py-8">
        <h1 className="text-xl font-semibold text-gray-900">New Knowledge Product</h1>
        <form onSubmit={handleSubmit} className="mt-6 space-y-4 rounded-lg border border-gray-200 bg-white p-6">
          <Field label="Product key (slug)" value={productKey} onChange={setProductKey} placeholder="shipment_creation" />
          <Field label="Name" value={name} onChange={setName} placeholder="Shipment Creation" />
          <Field label="Owner" value={owner} onChange={setOwner} placeholder="Logistics" />
          <div>
            <label className="block text-sm font-medium text-gray-700">Process steps (one per line)</label>
            <textarea
              value={steps}
              onChange={(e) => setSteps(e.target.value)}
              rows={4}
              className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"
              placeholder={"Validate Address\nSelect Carrier\nGenerate Label"}
            />
          </div>
          <Field label="SLA target (optional)" value={slaTarget} onChange={setSlaTarget} placeholder="2h" />
          {error && <p className="text-sm text-red-600">{error}</p>}
          <button
            type="submit"
            disabled={loading}
            className="rounded bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-700 disabled:opacity-50"
          >
            {loading ? "Creating..." : "Create"}
          </button>
        </form>
      </main>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700">{label}</label>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        required
        className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"
      />
    </div>
  );
}
