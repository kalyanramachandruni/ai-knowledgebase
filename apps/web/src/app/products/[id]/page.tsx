"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { NavBar } from "@/components/NavBar";
import { StatusBadge } from "@/components/StatusBadge";
import { api, ApiError } from "@/lib/api";
import { getToken, getUser, redirectIfUnauthorized } from "@/lib/auth";
import type { ApprovalRequest, KnowledgeProduct } from "@/lib/types";

export default function ProductDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [product, setProduct] = useState<KnowledgeProduct | null>(null);
  const [pendingApproval, setPendingApproval] = useState<ApprovalRequest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  async function reload() {
    const p = await api.getProduct(params.id);
    setProduct(p);
    if (p.current_version.status === "review") {
      setPendingApproval(await api.getPendingApproval(params.id, p.current_version.id));
    } else {
      setPendingApproval(null);
    }
  }

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    reload().catch((err) => {
      if (!redirectIfUnauthorized(err, router)) setError(String(err));
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.id, router]);

  if (error) return <div className="p-8 text-sm text-red-600">Error: {error}</div>;
  if (!product) return <div className="p-8 text-sm text-gray-500">Loading...</div>;

  const v = product.current_version;
  const user = getUser();
  const isReviewer = user?.roles.includes("reviewer") || user?.roles.includes("admin");
  const isOwner = user?.roles.includes("knowledge_owner") || user?.roles.includes("admin");

  async function runAction(fn: () => Promise<unknown>) {
    setActionError(null);
    try {
      await fn();
      await reload();
    } catch (err) {
      if (!redirectIfUnauthorized(err, router)) {
        setActionError(err instanceof ApiError ? err.message : String(err));
      }
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <NavBar />
      <main className="mx-auto max-w-4xl px-6 py-8">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold text-gray-900">{product.name}</h1>
            <p className="text-sm text-gray-500">
              {product.product_key} · owner: {product.owner}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <StatusBadge status={v.status} />
            <span className="text-sm text-gray-500">v{v.semver}</span>
          </div>
        </div>

        <div className="mt-3 flex gap-2">
          <Link href={`/products/${product.id}/versions`} className="text-sm text-blue-600 hover:underline">
            View version history →
          </Link>
        </div>

        {actionError && <p className="mt-3 text-sm text-red-600">{actionError}</p>}

        {user && (
          <div className="mt-4 flex gap-2">
            {v.status === "draft" && isOwner && (
              <ActionButton
                label="Submit for review"
                onClick={() => runAction(() => api.submitForReview(product.id, v.id, user.user_id))}
              />
            )}
            {v.status === "approved" && isOwner && (
              <ActionButton
                label="Publish"
                onClick={() => runAction(() => api.publish(product.id, v.id, user.user_id))}
              />
            )}
            {v.status === "published" && isOwner && (
              <ActionButton
                label="Retire"
                onClick={() => runAction(() => api.retire(product.id, v.id, user.user_id))}
              />
            )}
            {v.status === "review" && isReviewer && pendingApproval && (
              <>
                <ActionButton
                  label="Approve"
                  onClick={() => runAction(() => api.decideApproval(product.id, pendingApproval.id, "approved"))}
                />
                <ActionButton
                  label="Reject"
                  onClick={() => runAction(() => api.decideApproval(product.id, pendingApproval.id, "rejected"))}
                />
              </>
            )}
          </div>
        )}

        <Section title="Metadata">
          <KeyValue label="ID" value={v.content.metadata.id} />
          <KeyValue label="Name" value={v.content.metadata.name} />
          <KeyValue label="Owner" value={v.content.metadata.owner} />
          <KeyValue label="Version" value={v.content.metadata.version} />
        </Section>

        {v.content.process_overview && (
          <Section title="Process Overview">
            <div className="space-y-2 text-sm text-gray-700">
              {v.content.process_overview.summary && <p>{v.content.process_overview.summary}</p>}
              {v.content.process_overview.trigger && (
                <p><span className="font-medium text-gray-500">Trigger: </span>{v.content.process_overview.trigger}</p>
              )}
              {v.content.process_overview.outcome && (
                <p><span className="font-medium text-gray-500">Outcome: </span>{v.content.process_overview.outcome}</p>
              )}
            </div>
          </Section>
        )}

        <Section title="Process Steps">
          <StepList steps={v.content.process.steps} />
        </Section>

        <Section title="Rules">
          <RuleList items={v.content.rules} />
        </Section>

        <Section title="Policies">
          <RuleList items={v.content.policies} />
        </Section>

        <Section title="SLA">
          {v.content.sla ? (
            <p className="text-sm text-gray-700">Target: {v.content.sla.target}</p>
          ) : (
            <p className="text-sm text-gray-400">No SLA defined.</p>
          )}
          {v.content.escalations.length > 0 && (
            <ul className="mt-2 space-y-1 text-sm text-gray-700">
              {v.content.escalations.map((e: {after?: string; trigger?: string; escalate_to: string; action?: string}, i: number) => (
                <li key={i}>
                  <span className="font-medium">{e.trigger ?? e.after}</span> → {e.escalate_to}
                  {e.action && <span className="text-gray-500"> — {e.action}</span>}
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="Roles">
          <RoleList items={v.content.roles} />
        </Section>

        <Section title="Tools">
          <ToolList items={v.content.tools} />
        </Section>
      </main>
    </div>
  );
}

function ActionButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="rounded bg-gray-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-gray-700"
    >
      {label}
    </button>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-6 rounded-lg border border-gray-200 bg-white p-5">
      <h2 className="text-sm font-semibold text-gray-900">{title}</h2>
      <div className="mt-3">{children}</div>
    </section>
  );
}

function KeyValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-2 text-sm">
      <span className="w-20 text-gray-500">{label}</span>
      <span className="text-gray-900">{value}</span>
    </div>
  );
}

function RuleList({ items }: { items: { condition: string; action: string }[] }) {
  if (items.length === 0) return <p className="text-sm text-gray-400">None.</p>;
  return (
    <ul className="space-y-1 text-sm text-gray-700">
      {items.map((item, i) => (
        <li key={i}>
          IF <code className="rounded bg-gray-100 px-1">{item.condition}</code> THEN {item.action}
        </li>
      ))}
    </ul>
  );
}

type StepItem = string | { name: string; description?: string; responsible_role?: string; inputs?: string[]; outputs?: string[]; decision?: string; tools_used?: string[] };
type RoleItem = string | { name: string; responsibilities?: string[] };
type ToolItem = string | { name: string; purpose?: string };

function StepList({ steps }: { steps: StepItem[] }) {
  if (steps.length === 0) return <p className="text-sm text-gray-400">No steps defined.</p>;
  return (
    <ol className="space-y-3">
      {steps.map((step, i) => {
        if (typeof step === "string") {
          return (
            <li key={i} className="flex gap-2 text-sm text-gray-700">
              <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-gray-100 text-xs font-medium text-gray-600">{i + 1}</span>
              <span>{step}</span>
            </li>
          );
        }
        return (
          <li key={i} className="flex gap-3">
            <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-blue-50 text-xs font-medium text-blue-700">{i + 1}</span>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-gray-900">{step.name}</p>
              {step.description && <p className="mt-0.5 text-sm text-gray-600">{step.description}</p>}
              <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-gray-500">
                {step.responsible_role && <span>👤 {step.responsible_role}</span>}
                {step.tools_used && step.tools_used.length > 0 && <span>🔧 {step.tools_used.join(", ")}</span>}
                {step.decision && <span>⚡ Decision: {step.decision}</span>}
              </div>
              {(step.inputs?.length || step.outputs?.length) ? (
                <div className="mt-1 flex gap-4 text-xs text-gray-500">
                  {step.inputs?.length ? <span>In: {step.inputs.join(", ")}</span> : null}
                  {step.outputs?.length ? <span>Out: {step.outputs.join(", ")}</span> : null}
                </div>
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function RoleList({ items }: { items: RoleItem[] }) {
  if (items.length === 0) return <p className="text-sm text-gray-400">None.</p>;
  return (
    <ul className="space-y-2">
      {items.map((item, i) => {
        const name = typeof item === "string" ? item : item.name;
        const responsibilities = typeof item === "string" ? [] : (item.responsibilities ?? []);
        return (
          <li key={i}>
            <span className="rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-700">{name}</span>
            {responsibilities.length > 0 && (
              <ul className="mt-1 ml-4 list-disc space-y-0.5 text-xs text-gray-500">
                {responsibilities.map((r, j) => <li key={j}>{r}</li>)}
              </ul>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function ToolList({ items }: { items: ToolItem[] }) {
  if (items.length === 0) return <p className="text-sm text-gray-400">None.</p>;
  return (
    <ul className="space-y-1.5">
      {items.map((item, i) => {
        const name = typeof item === "string" ? item : item.name;
        const purpose = typeof item === "string" ? "" : (item.purpose ?? "");
        return (
          <li key={i} className="flex flex-wrap items-baseline gap-2 text-sm">
            <span className="rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-700">{name}</span>
            {purpose && <span className="text-xs text-gray-500">{purpose}</span>}
          </li>
        );
      })}
    </ul>
  );
}
