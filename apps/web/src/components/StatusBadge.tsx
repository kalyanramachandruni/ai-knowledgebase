import type { KnowledgeProductStatus } from "@/lib/types";

const STYLES: Record<KnowledgeProductStatus, string> = {
  draft: "bg-gray-100 text-gray-700",
  review: "bg-amber-100 text-amber-800",
  approved: "bg-blue-100 text-blue-800",
  published: "bg-green-100 text-green-800",
  retired: "bg-red-100 text-red-700",
};

export function StatusBadge({ status }: { status: KnowledgeProductStatus }) {
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${STYLES[status]}`}>
      {status}
    </span>
  );
}
