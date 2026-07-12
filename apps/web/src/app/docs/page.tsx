"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { NavBar } from "@/components/NavBar";
import { api, ApiError } from "@/lib/api";
import { getToken, getUser, redirectIfUnauthorized } from "@/lib/auth";
import type { DocumentDetail, DocumentSummary } from "@/lib/types";

import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import CodeBlock from "@tiptap/extension-code-block";
import Placeholder from "@tiptap/extension-placeholder";
import TextAlign from "@tiptap/extension-text-align";
import Underline from "@tiptap/extension-underline";

// ── Types ─────────────────────────────────────────────────────────────────────

type TreeNode = DocumentSummary & { children: TreeNode[] };

function buildTree(docs: DocumentSummary[]): TreeNode[] {
  const map = new Map<string, TreeNode>();
  docs.forEach((d) => map.set(d.id, { ...d, children: [] }));
  const roots: TreeNode[] = [];
  docs.forEach((d) => {
    if (d.parent_id && map.has(d.parent_id)) {
      map.get(d.parent_id)!.children.push(map.get(d.id)!);
    } else {
      roots.push(map.get(d.id)!);
    }
  });
  return roots;
}

// ── Sidebar ───────────────────────────────────────────────────────────────────

function SidebarNode({
  node,
  activeId,
  depth,
  onSelect,
  onAddChild,
  onDelete,
}: {
  node: TreeNode;
  activeId: string | null;
  depth: number;
  onSelect: (id: string) => void;
  onAddChild: (parentId: string) => void;
  onDelete: (id: string, title: string) => void;
}) {
  const [expanded, setExpanded] = useState(true);
  const hasChildren = node.children.length > 0;

  return (
    <li>
      <div
        className={`group flex items-center gap-1 rounded px-2 py-1 text-sm cursor-pointer select-none ${
          node.id === activeId
            ? "bg-blue-50 text-blue-700 font-medium"
            : "text-gray-700 hover:bg-gray-100"
        }`}
        style={{ paddingLeft: `${depth * 12 + 8}px` }}
      >
        <button
          className="w-4 shrink-0 text-gray-400 hover:text-gray-600"
          onClick={() => setExpanded((e) => !e)}
        >
          {hasChildren ? (expanded ? "▾" : "▸") : "·"}
        </button>
        <span className="flex-1 truncate" onClick={() => onSelect(node.id)}>
          {node.title || "Untitled"}
        </span>
        {/* Add sub-page */}
        <button
          title="Add sub-page"
          className="hidden group-hover:flex items-center text-gray-400 hover:text-blue-600 text-xs px-0.5"
          onClick={(e) => { e.stopPropagation(); onAddChild(node.id); }}
        >
          +
        </button>
        {/* Delete */}
        <button
          title="Delete page"
          className="hidden group-hover:flex items-center text-gray-400 hover:text-red-600 text-xs px-0.5"
          onClick={(e) => { e.stopPropagation(); onDelete(node.id, node.title); }}
        >
          🗑
        </button>
      </div>
      {hasChildren && expanded && (
        <ul>
          {node.children.map((child) => (
            <SidebarNode
              key={child.id}
              node={child}
              activeId={activeId}
              depth={depth + 1}
              onSelect={onSelect}
              onAddChild={onAddChild}
              onDelete={onDelete}
            />
          ))}
        </ul>
      )}
    </li>
  );
}

function Sidebar({
  docs,
  activeId,
  onSelect,
  onNew,
  onAddChild,
  onDelete,
}: {
  docs: DocumentSummary[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onAddChild: (parentId: string) => void;
  onDelete: (id: string, title: string) => void;
}) {
  const tree = buildTree(docs);

  return (
    <aside className="flex h-full w-60 shrink-0 flex-col border-r border-gray-200 bg-white">
      <div className="flex items-center justify-between border-b border-gray-200 px-3 py-3">
        <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">Pages</span>
        <button
          onClick={onNew}
          className="rounded bg-blue-600 px-2 py-1 text-xs font-medium text-white hover:bg-blue-700"
        >
          + New
        </button>
      </div>
      <div className="flex-1 overflow-y-auto py-2">
        {tree.length === 0 ? (
          <p className="px-4 py-6 text-xs text-gray-400">No pages yet. Create one!</p>
        ) : (
          <ul className="space-y-0.5">
            {tree.map((node) => (
              <SidebarNode
                key={node.id}
                node={node}
                activeId={activeId}
                depth={0}
                onSelect={onSelect}
                onAddChild={onAddChild}
                onDelete={onDelete}
              />
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}

// ── Toolbar ───────────────────────────────────────────────────────────────────

function ToolbarButton({
  onClick,
  active,
  title,
  children,
}: {
  onClick: () => void;
  active?: boolean;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <button
      onMouseDown={(e) => { e.preventDefault(); onClick(); }}
      title={title}
      className={`rounded px-2 py-1 text-sm font-medium transition-colors ${
        active
          ? "bg-gray-200 text-gray-900"
          : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
      }`}
    >
      {children}
    </button>
  );
}

// ── Compile modal ─────────────────────────────────────────────────────────────

function CompileModal({
  docTitle,
  onClose,
  onCompile,
}: {
  docTitle: string;
  onClose: () => void;
  onCompile: (opts: { product_key: string; name: string; owner: string; include_subpages: boolean }) => void;
}) {
  const slug = docTitle.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  const [productKey, setProductKey] = useState(slug);
  const [name, setName] = useState(docTitle);
  const [owner, setOwner] = useState("");
  const [includeSubpages, setIncludeSubpages] = useState(true);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
        <h2 className="mb-4 text-base font-semibold text-gray-900">Compile to Knowledge Product</h2>
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Product key (slug)</label>
            <input
              value={productKey}
              onChange={(e) => setProductKey(e.target.value)}
              className="w-full rounded border border-gray-300 px-3 py-1.5 text-sm"
              placeholder="e.g. salesforce-onboarding"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Product name</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full rounded border border-gray-300 px-3 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Owner</label>
            <input
              value={owner}
              onChange={(e) => setOwner(e.target.value)}
              className="w-full rounded border border-gray-300 px-3 py-1.5 text-sm"
              placeholder="e.g. Sales Ops"
            />
          </div>
          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={includeSubpages}
              onChange={(e) => setIncludeSubpages(e.target.checked)}
              className="rounded"
            />
            Include sub-pages
          </label>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onClose} className="rounded border border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50">
            Cancel
          </button>
          <button
            onClick={() => {
              if (!productKey.trim() || !name.trim() || !owner.trim()) return;
              onCompile({ product_key: productKey.trim(), name: name.trim(), owner: owner.trim(), include_subpages: includeSubpages });
            }}
            className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            Extract &amp; Compile
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Editor panel ──────────────────────────────────────────────────────────────

function EditorPanel({
  doc,
  onSaved,
  onCompileRequest,
}: {
  doc: DocumentDetail;
  onSaved: (updated: DocumentDetail) => void;
  onCompileRequest: () => void;
}) {
  const [title, setTitle] = useState(doc.title);
  const [saveStatus, setSaveStatus] = useState<"saved" | "saving" | "unsaved">("saved");
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const editor = useEditor({
    extensions: [
      StarterKit.configure({ codeBlock: false }),
      CodeBlock,
      Placeholder.configure({ placeholder: "Start writing…" }),
      TextAlign.configure({ types: ["heading", "paragraph"] }),
      Underline,
    ],
    content: (doc.content as object) ?? "",
    editorProps: {
      attributes: {
        class: "tiptap-content tiptap max-w-none min-h-[60vh] px-8 py-6 text-gray-800",
      },
    },
    onUpdate: ({ editor }) => {
      setSaveStatus("unsaved");
      if (saveTimer.current) clearTimeout(saveTimer.current);
      saveTimer.current = setTimeout(() => {
        save(title, editor.getJSON());
      }, 2000);
    },
  });

  useEffect(() => {
    if (editor && doc.content) {
      editor.commands.setContent(doc.content as object);
    } else if (editor) {
      editor.commands.clearContent();
    }
    setTitle(doc.title);
    setSaveStatus("saved");
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc.id]);

  const save = useCallback(
    async (currentTitle: string, content: object) => {
      setSaveStatus("saving");
      try {
        const updated = await api.updateDocument(doc.id, { title: currentTitle, content });
        onSaved(updated);
        setSaveStatus("saved");
      } catch {
        setSaveStatus("unsaved");
      }
    },
    [doc.id, onSaved]
  );

  function handleTitleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const newTitle = e.target.value;
    setTitle(newTitle);
    setSaveStatus("unsaved");
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      if (editor) save(newTitle, editor.getJSON());
    }, 2000);
  }

  if (!editor) return null;

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-1 border-b border-gray-200 bg-white px-4 py-2">
        {/* Text style */}
        <ToolbarButton onClick={() => editor.chain().focus().toggleBold().run()} active={editor.isActive("bold")} title="Bold (⌘B)">
          <strong>B</strong>
        </ToolbarButton>
        <ToolbarButton onClick={() => editor.chain().focus().toggleItalic().run()} active={editor.isActive("italic")} title="Italic (⌘I)">
          <em>I</em>
        </ToolbarButton>
        <ToolbarButton onClick={() => editor.chain().focus().toggleUnderline().run()} active={editor.isActive("underline")} title="Underline (⌘U)">
          <span className="underline">U</span>
        </ToolbarButton>
        <ToolbarButton onClick={() => editor.chain().focus().toggleStrike().run()} active={editor.isActive("strike")} title="Strikethrough">
          <span className="line-through">S</span>
        </ToolbarButton>

        <div className="mx-1 h-5 w-px bg-gray-200" />

        {/* Headings */}
        <ToolbarButton onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()} active={editor.isActive("heading", { level: 1 })} title="Heading 1">
          H1
        </ToolbarButton>
        <ToolbarButton onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()} active={editor.isActive("heading", { level: 2 })} title="Heading 2">
          H2
        </ToolbarButton>

        <div className="mx-1 h-5 w-px bg-gray-200" />

        {/* Lists */}
        <ToolbarButton onClick={() => editor.chain().focus().toggleBulletList().run()} active={editor.isActive("bulletList")} title="Bullet list">
          •—
        </ToolbarButton>
        <ToolbarButton onClick={() => editor.chain().focus().toggleOrderedList().run()} active={editor.isActive("orderedList")} title="Ordered list">
          1—
        </ToolbarButton>
        <ToolbarButton onClick={() => editor.chain().focus().toggleCodeBlock().run()} active={editor.isActive("codeBlock")} title="Code block">
          {"</>"}
        </ToolbarButton>

        <div className="mx-1 h-5 w-px bg-gray-200" />

        {/* Indentation */}
        <ToolbarButton onClick={() => editor.chain().focus().sinkListItem("listItem").run()} title="Indent (Tab)">
          →|
        </ToolbarButton>
        <ToolbarButton onClick={() => editor.chain().focus().liftListItem("listItem").run()} title="Outdent (Shift+Tab)">
          |←
        </ToolbarButton>

        <div className="mx-1 h-5 w-px bg-gray-200" />

        {/* Alignment */}
        <ToolbarButton onClick={() => editor.chain().focus().setTextAlign("left").run()} active={editor.isActive({ textAlign: "left" })} title="Align left">
          ≡L
        </ToolbarButton>
        <ToolbarButton onClick={() => editor.chain().focus().setTextAlign("center").run()} active={editor.isActive({ textAlign: "center" })} title="Align center">
          ≡C
        </ToolbarButton>
        <ToolbarButton onClick={() => editor.chain().focus().setTextAlign("right").run()} active={editor.isActive({ textAlign: "right" })} title="Align right">
          ≡R
        </ToolbarButton>

        <div className="flex-1" />

        {/* Save status + compile */}
        <span className={`text-xs mr-2 ${saveStatus === "saving" ? "text-blue-500" : saveStatus === "unsaved" ? "text-amber-500" : "text-gray-400"}`}>
          {saveStatus === "saving" ? "Saving…" : saveStatus === "unsaved" ? "Unsaved" : "Saved"}
        </span>
        <button
          onMouseDown={(e) => e.preventDefault()}
          onClick={onCompileRequest}
          className="rounded bg-violet-600 px-3 py-1 text-xs font-medium text-white hover:bg-violet-700"
          title="Extract & compile this page into a Knowledge Product"
        >
          ⚡ Compile to KP
        </button>
      </div>

      {/* Title */}
      <div className="border-b border-gray-100 bg-white px-8 pt-8 pb-2">
        <input
          value={title}
          onChange={handleTitleChange}
          onKeyDown={(e) => e.key === "Enter" && editor?.commands.focus()}
          placeholder="Page title"
          className="w-full text-3xl font-bold text-gray-900 placeholder-gray-300 outline-none"
        />
      </div>

      {/* Editor */}
      <div className="flex-1 overflow-y-auto bg-white">
        <EditorContent editor={editor} />
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function DocsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [docs, setDocs] = useState<DocumentSummary[]>([]);
  const [activeDoc, setActiveDoc] = useState<DocumentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [compiling, setCompiling] = useState(false);
  const [compileSuccess, setCompileSuccess] = useState<{ id: string; name: string } | null>(null);
  const [showCompileModal, setShowCompileModal] = useState(false);

  const activeId = searchParams.get("id");

  async function loadDocs() {
    const list = await api.listDocuments();
    setDocs(list);
    return list;
  }

  useEffect(() => {
    if (!getToken()) { router.push("/login"); return; }
    loadDocs().catch((err) => {
      if (!redirectIfUnauthorized(err, router)) setError(String(err));
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!activeId) { setActiveDoc(null); return; }
    api.getDocument(activeId)
      .then(setActiveDoc)
      .catch((err) => {
        if (!redirectIfUnauthorized(err, router)) setError(String(err));
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId]);

  function selectDoc(id: string) {
    router.push(`/docs?id=${id}`, { scroll: false });
  }

  async function createDoc(parentId: string | null = null) {
    try {
      const doc = await api.createDocument({ title: "Untitled", parent_id: parentId });
      await loadDocs();
      selectDoc(doc.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create page");
    }
  }

  async function deleteDoc(id: string, title: string) {
    if (!confirm(`Delete "${title || "Untitled"}"? This cannot be undone.`)) return;
    try {
      await api.deleteDocument(id);
      if (activeId === id) router.push("/docs", { scroll: false });
      await loadDocs();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to delete page");
    }
  }

  async function handleCompile(opts: {
    product_key: string;
    name: string;
    owner: string;
    include_subpages: boolean;
  }) {
    if (!activeDoc) return;
    setShowCompileModal(false);
    setCompiling(true);
    setCompileSuccess(null);
    try {
      const result = await api.compileDocument(activeDoc.id, { ...opts, bump: "minor" });
      setCompileSuccess({ id: result.id, name: result.name });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Compilation failed");
    } finally {
      setCompiling(false);
    }
  }

  function handleSaved(updated: DocumentDetail) {
    setActiveDoc(updated);
    setDocs((prev) =>
      prev.map((d) => d.id === updated.id ? { ...d, title: updated.title, updated_at: updated.updated_at } : d)
    );
  }

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-gray-50">
      <NavBar />

      {error && (
        <div className="border-b border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
          {error}
          <button className="ml-2 underline" onClick={() => setError(null)}>dismiss</button>
        </div>
      )}

      {compiling && (
        <div className="border-b border-violet-200 bg-violet-50 px-4 py-2 text-sm text-violet-700">
          Extracting &amp; compiling document into a Knowledge Product… this may take a moment.
        </div>
      )}

      {compileSuccess && (
        <div className="border-b border-green-200 bg-green-50 px-4 py-2 text-sm text-green-700 flex items-center gap-3">
          <span>Knowledge Product <strong>{compileSuccess.name}</strong> created/updated successfully.</span>
          <button
            className="underline"
            onClick={() => router.push(`/products/${compileSuccess.id}`)}
          >
            View
          </button>
          <button className="ml-auto underline" onClick={() => setCompileSuccess(null)}>dismiss</button>
        </div>
      )}

      <div className="flex flex-1 overflow-hidden">
        <Sidebar
          docs={docs}
          activeId={activeId}
          onSelect={selectDoc}
          onNew={() => createDoc(null)}
          onAddChild={(parentId) => createDoc(parentId)}
          onDelete={deleteDoc}
        />
        <main className="flex flex-1 flex-col overflow-hidden">
          {activeDoc ? (
            <EditorPanel
              key={activeDoc.id}
              doc={activeDoc}
              onSaved={handleSaved}
              onCompileRequest={() => setShowCompileModal(true)}
            />
          ) : (
            <div className="flex flex-1 flex-col items-center justify-center text-center">
              <div className="text-5xl mb-4">📄</div>
              <h2 className="text-lg font-semibold text-gray-700">Select a page or create a new one</h2>
              <p className="mt-1 text-sm text-gray-400">Your documents live here</p>
              <button
                onClick={() => createDoc(null)}
                className="mt-4 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
              >
                + Create first page
              </button>
            </div>
          )}
        </main>
      </div>

      {showCompileModal && activeDoc && (
        <CompileModal
          docTitle={activeDoc.title}
          onClose={() => setShowCompileModal(false)}
          onCompile={handleCompile}
        />
      )}
    </div>
  );
}
