"use client";

import { getToken } from "@/lib/auth";
import type {
  ApprovalRequest,
  KnowledgeProduct,
  KnowledgeProductSummary,
  VersionDiff,
} from "@/lib/types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string> | undefined),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail ?? res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const api = {
  issueDevToken: (user_id: string, display_name: string, roles: string[]) =>
    request<{ access_token: string; user_id: string; roles: string[] }>("/auth/dev-token", {
      method: "POST",
      body: JSON.stringify({ user_id, display_name, roles }),
    }),

  listProducts: (params: { status?: string; search?: string } = {}) => {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v) as [string, string][]
    ).toString();
    return request<KnowledgeProductSummary[]>(`/knowledge-products${qs ? `?${qs}` : ""}`);
  },

  getProduct: (id: string) => request<KnowledgeProduct>(`/knowledge-products/${id}`),

  listVersions: (id: string) =>
    request<KnowledgeProduct["versions"]>(`/knowledge-products/${id}/versions`),

  compareVersions: (id: string, fromId: string, toId: string) =>
    request<VersionDiff>(`/knowledge-products/${id}/versions/${fromId}/diff/${toId}`),

  submitForReview: (productId: string, versionId: string, actorId: string) =>
    request<KnowledgeProduct>(
      `/knowledge-products/${productId}/versions/${versionId}/submit-for-review`,
      { method: "POST", body: JSON.stringify({ actor_id: actorId }) }
    ),

  getPendingApproval: (productId: string, versionId: string) =>
    request<ApprovalRequest | null>(`/knowledge-products/${productId}/versions/${versionId}/pending-approval`),

  decideApproval: (
    productId: string,
    requestId: string,
    decision: "approved" | "rejected",
    comment?: string
  ) =>
    request<ApprovalRequest>(`/knowledge-products/${productId}/approval-requests/${requestId}/decide`, {
      method: "POST",
      body: JSON.stringify({ decision, comment }),
    }),

  publish: (productId: string, versionId: string, actorId: string) =>
    request<KnowledgeProduct>(`/knowledge-products/${productId}/versions/${versionId}/publish`, {
      method: "POST",
      body: JSON.stringify({ actor_id: actorId }),
    }),

  retire: (productId: string, versionId: string, actorId: string) =>
    request<KnowledgeProduct>(`/knowledge-products/${productId}/versions/${versionId}/retire`, {
      method: "POST",
      body: JSON.stringify({ actor_id: actorId }),
    }),

  createProduct: (payload: Record<string, unknown>) =>
    request<KnowledgeProduct>("/knowledge-products", { method: "POST", body: JSON.stringify(payload) }),

  syncConfluenceSpace: (spaceKey: string, spaceName: string, baseUrl: string) =>
    request<{
      space_key: string;
      pages_created: number;
      pages_updated: number;
      pages_skipped_unchanged: number;
    }>("/confluence/spaces/sync", {
      method: "POST",
      body: JSON.stringify({ space_key: spaceKey, space_name: spaceName, base_url: baseUrl }),
    }),

  listConfluencePages: (spaceKey?: string) => {
    const qs = spaceKey ? `?space_key=${encodeURIComponent(spaceKey)}` : "";
    return request<import("@/lib/types").ConfluencePage[]>(`/confluence/pages${qs}`);
  },

  extractPage: (pageId: string) =>
    request<import("@/lib/types").ExtractionRun>(`/confluence/pages/${pageId}/extract`, {
      method: "POST",
    }),

  compileExtraction: (runId: string, payload: {
    product_key: string;
    name: string;
    owner: string;
    created_by: string;
  }) =>
    request<import("@/lib/types").KnowledgeProduct>(`/extraction-runs/${runId}/compile`, {
      method: "POST",
      body: JSON.stringify({ ...payload, bump: "minor" }),
    }),
};
