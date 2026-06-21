export type KnowledgeProductStatus = "draft" | "review" | "approved" | "published" | "retired";

export type Role = "admin" | "knowledge_owner" | "reviewer" | "consumer";

export interface RuleOrPolicy {
  condition: string;
  action: string;
}

export interface Escalation {
  after: string;
  escalate_to: string;
}

export interface CanonicalContent {
  metadata: { id: string; name: string; owner: string; version: string };
  process: { steps: string[] };
  rules: RuleOrPolicy[];
  policies: RuleOrPolicy[];
  sla: { target: string } | null;
  escalations: Escalation[];
  roles: string[];
  tools: string[];
}

export interface KnowledgeProductVersion {
  id: string;
  semver: string;
  status: KnowledgeProductStatus;
  content: CanonicalContent;
}

export interface KnowledgeProduct {
  id: string;
  product_key: string;
  name: string;
  owner: string;
  current_version: KnowledgeProductVersion;
  versions: KnowledgeProductVersion[];
}

export interface KnowledgeProductSummary {
  id: string;
  product_key: string;
  name: string;
  owner: string;
  current_status: KnowledgeProductStatus;
  current_semver: string;
}

export interface VersionDiff {
  diff: Record<string, { from: unknown; to: unknown }>;
}

export interface ApprovalRequest {
  id: string;
  version_id: string;
  requested_by: string;
  reviewer_id: string | null;
  decision: "pending" | "approved" | "rejected";
  comment: string | null;
}
