"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { NavBar } from "@/components/NavBar";
import { StatusBadge } from "@/components/StatusBadge";
import { api, ApiError } from "@/lib/api";
import { getToken, getUser, redirectIfUnauthorized } from "@/lib/auth";
import type { ApprovalRequest, CanonicalContent, KnowledgeProduct } from "@/lib/types";

// ── editable draft types ──────────────────────────────────────────────────────

interface DraftStep {
  name: string;
  description: string;
  responsible_role: string;
  tools_used: string;
  inputs: string;
  outputs: string;
  decision: string;
}

interface DraftRule { condition: string; action: string }
interface DraftEscalation { after: string; escalate_to: string; action: string }
interface DraftRole { name: string; responsibilities: string }
interface DraftTool { name: string; purpose: string }

interface EditDraft {
  overview_summary: string;
  overview_trigger: string;
  overview_outcome: string;
  steps: DraftStep[];
  rules: DraftRule[];
  policies: DraftRule[];
  sla_target: string;
  escalations: DraftEscalation[];
  roles: DraftRole[];
  tools: DraftTool[];
}

type StepItem = string | { name: string; description?: string; responsible_role?: string; inputs?: string[]; outputs?: string[]; decision?: string; tools_used?: string[] };
type RoleItem = string | { name: string; responsibilities?: string[] };
type ToolItem = string | { name: string; purpose?: string };

function contentToDraft(c: CanonicalContent): EditDraft {
  const steps: DraftStep[] = (c.process?.steps ?? []).map((s: StepItem) =>
    typeof s === "string"
      ? { name: s, description: "", responsible_role: "", tools_used: "", inputs: "", outputs: "", decision: "" }
      : {
          name: s.name ?? "",
          description: s.description ?? "",
          responsible_role: s.responsible_role ?? "",
          tools_used: (s.tools_used ?? []).join(", "),
          inputs: (s.inputs ?? []).join(", "),
          outputs: (s.outputs ?? []).join(", "),
          decision: s.decision ?? "",
        }
  );
  const roles: DraftRole[] = (c.roles ?? []).map((r: RoleItem) =>
    typeof r === "string"
      ? { name: r, responsibilities: "" }
      : { name: r.name ?? "", responsibilities: (r.responsibilities ?? []).join("\n") }
  );
  const tools: DraftTool[] = (c.tools ?? []).map((t: ToolItem) =>
    typeof t === "string"
      ? { name: t, purpose: "" }
      : { name: t.name ?? "", purpose: t.purpose ?? "" }
  );
  return {
    overview_summary: c.process_overview?.summary ?? "",
    overview_trigger: c.process_overview?.trigger ?? "",
    overview_outcome: c.process_overview?.outcome ?? "",
    steps,
    rules: (c.rules ?? []).map((r) => ({ condition: r.condition ?? "", action: r.action ?? "" })),
    policies: (c.policies ?? []).map((p) => ({ condition: p.condition ?? "", action: p.action ?? "" })),
    sla_target: c.sla?.target ?? "",
    escalations: (c.escalations ?? []).map((e) => ({
      after: (e as { after?: string; trigger?: string }).after ?? (e as { after?: string; trigger?: string }).trigger ?? "",
      escalate_to: e.escalate_to ?? "",
      action: (e as { action?: string }).action ?? "",
    })),
    roles,
    tools,
  };
}

function draftToPayload(d: EditDraft, userId: string) {
  const csv = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);
  return {
    compile: {
      created_by: userId,
      bump: "patch",
      process_overview: {
        summary: d.overview_summary,
        trigger: d.overview_trigger,
        outcome: d.overview_outcome,
      },
      process_steps: d.steps.map((s) => ({
        name: s.name,
        description: s.description,
        responsible_role: s.responsible_role,
        tools_used: csv(s.tools_used),
        inputs: csv(s.inputs),
        outputs: csv(s.outputs),
        decision: s.decision || null,
      })),
      rules: d.rules,
      policies: d.policies,
      sla_target: d.sla_target || null,
      escalations: d.escalations.map((e) => ({ after: e.after, escalate_to: e.escalate_to, action: e.action })),
      roles: d.roles.map((r) => ({
        name: r.name,
        responsibilities: r.responsibilities.split("\n").map((x) => x.trim()).filter(Boolean),
      })),
      tools: d.tools.map((t) => ({ name: t.name, purpose: t.purpose })),
    },
  };
}

// ── page ──────────────────────────────────────────────────────────────────────

export default function ProductDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [product, setProduct] = useState<KnowledgeProduct | null>(null);
  const [pendingApproval, setPendingApproval] = useState<ApprovalRequest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<EditDraft | null>(null);
  const [saving, setSaving] = useState(false);

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
    if (!getToken()) { router.push("/login"); return; }
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
  const canEdit = v.status === "draft" && !!isOwner;

  function startEdit() {
    setDraft(contentToDraft(v.content));
    setActionError(null);
    setEditing(true);
  }

  function cancelEdit() {
    setEditing(false);
    setDraft(null);
    setActionError(null);
  }

  async function saveEdit() {
    if (!draft || !user?.user_id) return;
    setSaving(true);
    setActionError(null);
    try {
      await api.updateProduct(product!.id, draftToPayload(draft, user.user_id));
      setEditing(false);
      setDraft(null);
      await reload();
    } catch (err) {
      if (!redirectIfUnauthorized(err, router)) {
        setActionError(err instanceof ApiError ? err.message : String(err));
      }
    } finally {
      setSaving(false);
    }
  }

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
            <p className="text-sm text-gray-500">{product.product_key} · owner: {product.owner}</p>
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

        {/* Action bar */}
        {user && (
          <div className="mt-4 flex flex-wrap gap-2">
            {canEdit && !editing && (
              <ActionButton label="Edit" variant="secondary" onClick={startEdit} />
            )}
            {!editing && (
              <>
                <ActionButton label="Export JSON" variant="secondary" onClick={() => api.exportSkillBundle(product.id, "json").catch((e) => setActionError(String(e)))} />
                <ActionButton label="Export Markdown" variant="secondary" onClick={() => api.exportSkillBundle(product.id, "markdown").catch((e) => setActionError(String(e)))} />
              </>
            )}
            {editing && (
              <>
                <ActionButton label={saving ? "Saving…" : "Save changes"} onClick={saveEdit} disabled={saving} />
                <ActionButton label="Cancel" variant="secondary" onClick={cancelEdit} disabled={saving} />
              </>
            )}
            {v.status === "draft" && isOwner && !editing && (
              <ActionButton label="Submit for review" onClick={() => runAction(() => api.submitForReview(product.id, v.id, user.user_id))} />
            )}
            {v.status === "approved" && isOwner && (
              <ActionButton label="Publish" onClick={() => runAction(() => api.publish(product.id, v.id, user.user_id))} />
            )}
            {v.status === "published" && isOwner && (
              <ActionButton label="Retire" onClick={() => runAction(() => api.retire(product.id, v.id, user.user_id))} />
            )}
            {v.status === "review" && isReviewer && pendingApproval && (
              <>
                <ActionButton label="Approve" onClick={() => runAction(() => api.decideApproval(product.id, pendingApproval.id, "approved"))} />
                <ActionButton label="Reject" onClick={() => runAction(() => api.decideApproval(product.id, pendingApproval.id, "rejected"))} />
              </>
            )}
          </div>
        )}

        {editing && draft ? (
          <EditForm draft={draft} onChange={setDraft} />
        ) : (
          <ViewMode v={v} />
        )}
      </main>
    </div>
  );
}

// ── view mode ─────────────────────────────────────────────────────────────────

function ViewMode({ v }: { v: KnowledgeProduct["current_version"] }) {
  const c = v.content;
  type StepItem = string | { name: string; description?: string; responsible_role?: string; inputs?: string[]; outputs?: string[]; decision?: string; tools_used?: string[] };
  type RoleItem = string | { name: string; responsibilities?: string[] };
  type ToolItem = string | { name: string; purpose?: string };

  return (
    <>
      <Section title="Metadata">
        <KeyValue label="ID" value={c.metadata.id} />
        <KeyValue label="Name" value={c.metadata.name} />
        <KeyValue label="Owner" value={c.metadata.owner} />
        <KeyValue label="Version" value={c.metadata.version} />
      </Section>

      {c.process_overview && (
        <Section title="Process Overview">
          <div className="space-y-2 text-sm text-gray-700">
            {c.process_overview.summary && <p>{c.process_overview.summary}</p>}
            {c.process_overview.trigger && <p><span className="font-medium text-gray-500">Trigger: </span>{c.process_overview.trigger}</p>}
            {c.process_overview.outcome && <p><span className="font-medium text-gray-500">Outcome: </span>{c.process_overview.outcome}</p>}
          </div>
        </Section>
      )}

      <Section title="Process Steps">
        <StepList steps={c.process.steps as StepItem[]} />
      </Section>

      <Section title="Rules">
        <RuleList items={c.rules} />
      </Section>

      <Section title="Policies">
        <RuleList items={c.policies} />
      </Section>

      <Section title="SLA">
        {c.sla ? (
          <p className="text-sm text-gray-700">Target: {c.sla.target}</p>
        ) : (
          <p className="text-sm text-gray-400">No SLA defined.</p>
        )}
        {c.escalations.length > 0 && (
          <ul className="mt-2 space-y-1 text-sm text-gray-700">
            {c.escalations.map((e: { after?: string; trigger?: string; escalate_to: string; action?: string }, i: number) => (
              <li key={i}>
                <span className="font-medium">{e.trigger ?? e.after}</span> → {e.escalate_to}
                {e.action && <span className="text-gray-500"> — {e.action}</span>}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Roles">
        <RoleList items={c.roles as RoleItem[]} />
      </Section>

      <Section title="Tools">
        <ToolList items={c.tools as ToolItem[]} />
      </Section>
    </>
  );
}

// ── edit form ─────────────────────────────────────────────────────────────────

function EditForm({ draft, onChange }: { draft: EditDraft; onChange: (d: EditDraft) => void }) {
  function set<K extends keyof EditDraft>(key: K, val: EditDraft[K]) {
    onChange({ ...draft, [key]: val });
  }

  function setStep(i: number, patch: Partial<DraftStep>) {
    const steps = draft.steps.map((s, idx) => idx === i ? { ...s, ...patch } : s);
    set("steps", steps);
  }

  function addStep() {
    set("steps", [...draft.steps, { name: "", description: "", responsible_role: "", tools_used: "", inputs: "", outputs: "", decision: "" }]);
  }

  function removeStep(i: number) { set("steps", draft.steps.filter((_, idx) => idx !== i)); }

  function setRule(arr: "rules" | "policies", i: number, patch: Partial<DraftRule>) {
    set(arr, draft[arr].map((r, idx) => idx === i ? { ...r, ...patch } : r));
  }

  function addRule(arr: "rules" | "policies") { set(arr, [...draft[arr], { condition: "", action: "" }]); }
  function removeRule(arr: "rules" | "policies", i: number) { set(arr, draft[arr].filter((_, idx) => idx !== i)); }

  function setEsc(i: number, patch: Partial<DraftEscalation>) {
    set("escalations", draft.escalations.map((e, idx) => idx === i ? { ...e, ...patch } : e));
  }

  function addEsc() { set("escalations", [...draft.escalations, { after: "", escalate_to: "", action: "" }]); }
  function removeEsc(i: number) { set("escalations", draft.escalations.filter((_, idx) => idx !== i)); }

  function setRole(i: number, patch: Partial<DraftRole>) {
    set("roles", draft.roles.map((r, idx) => idx === i ? { ...r, ...patch } : r));
  }

  function addRole() { set("roles", [...draft.roles, { name: "", responsibilities: "" }]); }
  function removeRole(i: number) { set("roles", draft.roles.filter((_, idx) => idx !== i)); }

  function setTool(i: number, patch: Partial<DraftTool>) {
    set("tools", draft.tools.map((t, idx) => idx === i ? { ...t, ...patch } : t));
  }

  function addTool() { set("tools", [...draft.tools, { name: "", purpose: "" }]); }
  function removeTool(i: number) { set("tools", draft.tools.filter((_, idx) => idx !== i)); }

  return (
    <div className="mt-6 space-y-5">
      {/* Process Overview */}
      <EditSection title="Process Overview">
        <Label>Summary</Label>
        <Textarea value={draft.overview_summary} onChange={(v) => set("overview_summary", v)} rows={3} />
        <Label>Trigger</Label>
        <Textarea value={draft.overview_trigger} onChange={(v) => set("overview_trigger", v)} rows={2} />
        <Label>Outcome</Label>
        <Textarea value={draft.overview_outcome} onChange={(v) => set("overview_outcome", v)} rows={2} />
      </EditSection>

      {/* Process Steps */}
      <EditSection title="Process Steps">
        <div className="space-y-4">
          {draft.steps.map((s, i) => (
            <div key={i} className="relative rounded-lg border border-gray-200 bg-gray-50 p-4">
              <button onClick={() => removeStep(i)} className="absolute right-3 top-3 text-xs text-red-500 hover:text-red-700">Remove</button>
              <p className="mb-3 text-xs font-semibold text-gray-500">Step {i + 1}</p>
              <div className="grid grid-cols-2 gap-3">
                <div className="col-span-2">
                  <Label>Name</Label>
                  <Input value={s.name} onChange={(v) => setStep(i, { name: v })} />
                </div>
                <div className="col-span-2">
                  <Label>Description</Label>
                  <Textarea value={s.description} onChange={(v) => setStep(i, { description: v })} rows={2} />
                </div>
                <div>
                  <Label>Responsible role</Label>
                  <Input value={s.responsible_role} onChange={(v) => setStep(i, { responsible_role: v })} />
                </div>
                <div>
                  <Label>Tools used (comma-separated)</Label>
                  <Input value={s.tools_used} onChange={(v) => setStep(i, { tools_used: v })} />
                </div>
                <div>
                  <Label>Inputs (comma-separated)</Label>
                  <Input value={s.inputs} onChange={(v) => setStep(i, { inputs: v })} />
                </div>
                <div>
                  <Label>Outputs (comma-separated)</Label>
                  <Input value={s.outputs} onChange={(v) => setStep(i, { outputs: v })} />
                </div>
                <div className="col-span-2">
                  <Label>Decision point</Label>
                  <Input value={s.decision} onChange={(v) => setStep(i, { decision: v })} placeholder="Optional" />
                </div>
              </div>
            </div>
          ))}
        </div>
        <AddButton onClick={addStep} label="Add step" />
      </EditSection>

      {/* Rules */}
      <EditSection title="Rules">
        <RuleEditor items={draft.rules} onSet={(i, p) => setRule("rules", i, p)} onAdd={() => addRule("rules")} onRemove={(i) => removeRule("rules", i)} />
      </EditSection>

      {/* Policies */}
      <EditSection title="Policies">
        <RuleEditor items={draft.policies} onSet={(i, p) => setRule("policies", i, p)} onAdd={() => addRule("policies")} onRemove={(i) => removeRule("policies", i)} />
      </EditSection>

      {/* SLA */}
      <EditSection title="SLA">
        <Label>SLA target</Label>
        <Input value={draft.sla_target} onChange={(v) => set("sla_target", v)} placeholder="e.g. 99.9% uptime / 24h response" />
        <p className="mt-4 mb-2 text-xs font-semibold text-gray-500">Escalations</p>
        <div className="space-y-3">
          {draft.escalations.map((e, i) => (
            <div key={i} className="relative rounded-lg border border-gray-200 bg-gray-50 p-3">
              <button onClick={() => removeEsc(i)} className="absolute right-3 top-3 text-xs text-red-500 hover:text-red-700">Remove</button>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <Label>After / trigger</Label>
                  <Input value={e.after} onChange={(v) => setEsc(i, { after: v })} />
                </div>
                <div>
                  <Label>Escalate to</Label>
                  <Input value={e.escalate_to} onChange={(v) => setEsc(i, { escalate_to: v })} />
                </div>
                <div>
                  <Label>Action</Label>
                  <Input value={e.action} onChange={(v) => setEsc(i, { action: v })} />
                </div>
              </div>
            </div>
          ))}
        </div>
        <AddButton onClick={addEsc} label="Add escalation" />
      </EditSection>

      {/* Roles */}
      <EditSection title="Roles">
        <div className="space-y-3">
          {draft.roles.map((r, i) => (
            <div key={i} className="relative rounded-lg border border-gray-200 bg-gray-50 p-3">
              <button onClick={() => removeRole(i)} className="absolute right-3 top-3 text-xs text-red-500 hover:text-red-700">Remove</button>
              <Label>Name</Label>
              <Input value={r.name} onChange={(v) => setRole(i, { name: v })} />
              <Label>Responsibilities (one per line)</Label>
              <Textarea value={r.responsibilities} onChange={(v) => setRole(i, { responsibilities: v })} rows={3} />
            </div>
          ))}
        </div>
        <AddButton onClick={addRole} label="Add role" />
      </EditSection>

      {/* Tools */}
      <EditSection title="Tools">
        <div className="space-y-3">
          {draft.tools.map((t, i) => (
            <div key={i} className="relative rounded-lg border border-gray-200 bg-gray-50 p-3">
              <button onClick={() => removeTool(i)} className="absolute right-3 top-3 text-xs text-red-500 hover:text-red-700">Remove</button>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label>Name</Label>
                  <Input value={t.name} onChange={(v) => setTool(i, { name: v })} />
                </div>
                <div>
                  <Label>Purpose</Label>
                  <Input value={t.purpose} onChange={(v) => setTool(i, { purpose: v })} />
                </div>
              </div>
            </div>
          ))}
        </div>
        <AddButton onClick={addTool} label="Add tool" />
      </EditSection>
    </div>
  );
}

function RuleEditor({
  items, onSet, onAdd, onRemove,
}: {
  items: DraftRule[];
  onSet: (i: number, p: Partial<DraftRule>) => void;
  onAdd: () => void;
  onRemove: (i: number) => void;
}) {
  return (
    <>
      <div className="space-y-3">
        {items.map((r, i) => (
          <div key={i} className="relative rounded-lg border border-gray-200 bg-gray-50 p-3">
            <button onClick={() => onRemove(i)} className="absolute right-3 top-3 text-xs text-red-500 hover:text-red-700">Remove</button>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Condition (IF)</Label>
                <Textarea value={r.condition} onChange={(v) => onSet(i, { condition: v })} rows={2} />
              </div>
              <div>
                <Label>Action (THEN)</Label>
                <Textarea value={r.action} onChange={(v) => onSet(i, { action: v })} rows={2} />
              </div>
            </div>
          </div>
        ))}
      </div>
      <AddButton onClick={onAdd} label="Add rule" />
    </>
  );
}

// ── primitives ────────────────────────────────────────────────────────────────

function EditSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-gray-200 bg-white p-5">
      <h2 className="mb-3 text-sm font-semibold text-gray-900">{title}</h2>
      <div className="space-y-2">{children}</div>
    </section>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return <p className="mb-1 text-xs font-medium text-gray-600">{children}</p>;
}

function Input({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <input
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className="w-full rounded border border-gray-300 px-2.5 py-1.5 text-sm text-gray-900 focus:border-gray-500 focus:outline-none"
    />
  );
}

function Textarea({ value, onChange, rows = 2 }: { value: string; onChange: (v: string) => void; rows?: number }) {
  return (
    <textarea
      value={value}
      onChange={(e) => onChange(e.target.value)}
      rows={rows}
      className="w-full rounded border border-gray-300 px-2.5 py-1.5 text-sm text-gray-900 focus:border-gray-500 focus:outline-none"
    />
  );
}

function AddButton({ onClick, label }: { onClick: () => void; label: string }) {
  return (
    <button
      onClick={onClick}
      className="mt-2 rounded border border-dashed border-gray-300 px-3 py-1.5 text-xs text-gray-500 hover:border-gray-400 hover:text-gray-700"
    >
      + {label}
    </button>
  );
}

function ActionButton({ label, onClick, variant = "primary", disabled }: {
  label: string;
  onClick: () => void;
  variant?: "primary" | "secondary";
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`rounded px-3 py-1.5 text-sm font-medium disabled:opacity-50 ${
        variant === "secondary"
          ? "border border-gray-300 bg-white text-gray-700 hover:bg-gray-50"
          : "bg-gray-900 text-white hover:bg-gray-700"
      }`}
    >
      {label}
    </button>
  );
}

// ── view-mode sub-components ──────────────────────────────────────────────────

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

type StepItem2 = string | { name: string; description?: string; responsible_role?: string; inputs?: string[]; outputs?: string[]; decision?: string; tools_used?: string[] };

function StepList({ steps }: { steps: StepItem2[] }) {
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

type RoleItem2 = string | { name: string; responsibilities?: string[] };

function RoleList({ items }: { items: RoleItem2[] }) {
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

type ToolItem2 = string | { name: string; purpose?: string };

function ToolList({ items }: { items: ToolItem2[] }) {
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
