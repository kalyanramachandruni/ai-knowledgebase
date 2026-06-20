from __future__ import annotations

from app.domain.knowledge_product.entities import KnowledgeProductVersion


class ContextPackageGenerator:
    """Capability 6. Pure projection — no own aggregate, no persistence —
    from a canonical KnowledgeProductVersion to the flatter Agent Context
    shape (docs/sample_agent_context.json) that AI agents actually consume
    at runtime. Deliberately not the same shape as the canonical YAML:
    agents don't need the governance metadata (owner, status), just the
    capability surface."""

    def build(self, *, product_key: str, version: KnowledgeProductVersion) -> dict:
        return {
            "capability": product_key,
            "version": str(version.semver),
            "process": [step.name for step in sorted(version.process_steps, key=lambda s: s.sequence)],
            "rules": [{"condition": r.condition, "action": r.action} for r in version.rules],
            "policies": [{"condition": p.condition, "action": p.action} for p in version.policies],
            "sla": {"target": version.sla.target} if version.sla else None,
            "escalations": [{"after": e.after, "escalate_to": e.escalate_to} for e in version.escalations],
            "roles": [r.name for r in version.roles],
            "tools": [t.key for t in version.tools],
        }
