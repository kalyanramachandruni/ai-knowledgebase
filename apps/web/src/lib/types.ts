export interface DocumentSummary {
  id: string;
  title: string;
  parent_id: string | null;
  updated_at: string;
}

export interface DocumentDetail extends DocumentSummary {
  content: object | null;
  created_at: string;
}

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

export interface ConfluenceSpace {
  id: string;
  space_key: string;
  name: string;
}

export interface ConfluencePage {
  id: string;
  space_id: string;
  space_key: string;
  confluence_page_id: string;
  title: string;
  confluence_version: number;
  last_modified_at: string;
}

export interface ConfluencePageDetail extends ConfluencePage {
  plain_text: string;
  labels: string[];
}

export interface CompiledProductSummary {
  product_id: string;
  product_key: string;
  name: string;
  version_id: string;
  semver: string;
}

export interface ExtractionRun {
  id: string;
  page_id: string;
  status: "running" | "succeeded" | "failed";
  llm_provider: string;
  llm_model: string;
  structured_draft: Record<string, unknown> | null;
  error_message: string | null;
  started_at?: string | null;
  compiled_product?: CompiledProductSummary | null;
}
