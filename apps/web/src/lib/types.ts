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
  compiled_at: string | null;
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

export interface CompiledPageEntry {
  run_id: string | null;
  page_id: string | null;
  title: string | null;
  status: "compiled" | "discarded" | "skipped";
  reason: string | null;
  compiled_at: string | null;
}

export interface CompiledPageSession {
  session_id: string;
  product_name: string | null;
  created_at: string | null;
  pages: CompiledPageEntry[];
}

export interface WebSource {
  id: string;
  name: string;
  root_url: string;
  crawl_depth: number | null;
  include_query_strings: boolean;
  last_crawled_at: string | null;
  page_count: number;
  last_crawl_created: number | null;
  last_crawl_updated: number | null;
  last_crawl_skipped: number | null;
  crawl_status: "PENDING" | "SUCCESSFUL" | "FAILED" | null;
  successful_crawl_count: number;
}

export interface WebPage {
  id: string;
  source_id: string;
  url: string;
  title: string;
  content_hash: string | null;
  fetched_at: string;
  latest_run_id: string | null;
  latest_run_status: "running" | "succeeded" | "failed" | null;
  latest_run_error: string | null;
  page_tags: string[];
  is_compiled: boolean;
  compiled_at: string | null;
  latest_compile_status: string | null;
  changed_since_extraction: boolean;
  is_thin_content: boolean;
  compiled_kp_count: number;
}

export interface CompiledKpSummary {
  product_id: string;
  product_key: string;
  product_name: string;
  compiled_page_count: number;
}

export interface PageKpStatus {
  page_id: string;
  status: "compiled" | "not_relevant" | "none";
}

export interface WebPageLink {
  url: string;
  title: string | null;
  linked_page_id: string | null;
  linked_page_title: string | null;
  linked_page_run_status: "running" | "succeeded" | "failed" | null;
  linked_page_run_id: string | null;
  linked_page_is_compiled: boolean;
  linked_page_compiled_at: string | null;
}

export interface LinkTreeNode {
  page_id: string | null;
  url: string;
  title: string | null;
  depth: number;
  run_status: "running" | "succeeded" | "failed" | null;
  is_compiled: boolean;
  children: LinkTreeNode[];
}

export interface LinkTreeResponse {
  page_id: string;
  url: string;
  title: string;
  run_status: "running" | "succeeded" | "failed" | null;
  is_compiled: boolean;
  parents: LinkTreeNode[];
  children: LinkTreeNode[];
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
  base_url: string;
  last_synced_at: string | null;
  page_count: number;
  last_sync_created: number | null;
  last_sync_updated: number | null;
  last_sync_skipped: number | null;
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

export interface CurationRun {
  id: string;
  page_id: string;
  status: "running" | "succeeded" | "failed";
  llm_provider: string;
  llm_model: string;
  structured_draft: Record<string, unknown> | null;
  error_message: string | null;
  started_at?: string | null;
  compiled_product?: CompiledProductSummary | null;
  reused?: boolean;
  compiled_at?: string | null;
  compile_status?: "succeeded" | "failed" | null;
  compile_error?: string | null;
  compiled_version_id?: string | null;
  prev_compiled_product?: CompiledProductSummary | null;
  prev_compiled_at?: string | null;
}
