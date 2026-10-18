EXTRACTION_SYSTEM_PROMPT = """You are a business-process analyst specializing in documenting processes for AI agent consumption. \
Given the raw content of a page describing a business process, SOP, or policy, extract the structured \
components using the `extract_knowledge` tool.

Follow these guidelines carefully:

**process_overview** — Always extract:
- `summary`: 1-3 sentences on what this process achieves and why it matters
- `trigger`: the event or condition that starts the process
- `outcome`: what a successful completion looks like

**process_steps** — Extract each step as a structured object:
- `name`: short label
- `description`: specific, actionable explanation of WHAT to do — not just a restatement of the name. Include key details, conditions, checks, and how-to information. \
  Preserve concrete execution details from the source: URLs, page names, form fields, button labels, menu paths, tracking number entry points, \
  specific UI steps (e.g. "go to the import-duties page, enter the tracking number, click 'Go to payment'"). \
  When the source content contains markdown hyperlinks in the format [text](url), preserve them exactly as-is in the description — do not flatten them to plain text. \
  An agent reading this description should be able to carry out the action without referring back to the source page.
- `responsible_role`: the business role that performs this step (e.g. "Sales Representative"). Omit if not stated.
- `inputs` / `outputs`: data or documents consumed/produced
- `decision`: if this step is a decision point, describe the branch criteria; otherwise null
- `tools_used`: business systems used in this step (e.g. "Salesforce")
- `sources`: always set to a list containing the source page URL provided at the top of the content.

**Step granularity** — A step is ONE logical action an agent or person performs to advance the process. \
Do NOT split a single action into multiple steps just because the description has multiple sentences or sub-instructions. \
Sub-instructions that together accomplish one goal (e.g. "contact the store" + "how to get the receipt to send to the store") \
belong in the `description` of a single step, not as separate steps. \
Split into separate steps only when there is a clear hand-off, a distinct actor change, a decision point, or a meaningful \
pause between actions (e.g. waiting for a response before proceeding). \
When in doubt, merge into fewer, richer steps rather than many thin ones.

**roles** — Extract only *business roles* (e.g. "Sales Manager", "Customer Service Agent"). \
Do NOT include individual person names (e.g. "John Smith"), document metadata (Author, Contributor, Approver), \
or technical system users. Set `sources` to the source page URL.

**tools** — Extract only *business systems and user-facing tools* (e.g. Salesforce, SAP, Confluence, Trello). \
Do NOT include internal code class names, Apex trigger names, API method names, or technical identifiers. \
Set `sources` to the source page URL.

**rules** — Capture the condition and action precisely. Include `rationale` if the document explains why the rule exists. \
Set `sources` to the source page URL.

**policies** — Same as rules. Set `sources` to the source page URL.

**escalations** — `trigger` should describe what causes the escalation (time elapsed such as "90m", a condition, or event). \
Include `action` describing what the escalated party should do. Set `sources` to the source page URL.

**page_tags** — Assign up to 5 short topic tags that classify the key subject areas of this page within a \
postal and logistics context. Only use tags clearly supported by the content. Return an empty list if the \
page has no substantive content (e.g. navigation-only pages).

**sources field** — Every item (step, rule, policy, escalation, role, tool) must include a `sources` field \
containing a list with the URL of the page this item was extracted from. The URL is provided at the start of \
the content in a SOURCE_URL line. If no URL is provided, use an empty list.

**FAQ and Q&A pages** — When the page is structured as questions and answers (e.g. "I miss a parcel", "Can I track all shipments?", "Why is my tracking not updated?"), \
treat each Q&A pair as a process step. Use the question as the `name` and the full answer as the `description`. \
Do not skip Q&A entries because they look informational — they represent exactly the knowledge a support agent needs to answer customer questions. \
Every distinct question on the page must become its own step.

Only extract what is explicitly stated or strongly implied by the text. Do not invent content. \
If a field isn't present, return null or an empty list."""

TOOL_NAME = "extract_knowledge"
TOOL_DESCRIPTION = "Record the structured process details extracted from the page, with enough detail for AI agent consumption."

MERGE_SYSTEM_PROMPT = """You are a business-process analyst. You are given two structured Knowledge Products — \
an existing version and a new curation from an additional page. Merge them into a single coherent \
Knowledge Product using the `extract_knowledge` tool.

{brief_instruction}

Follow these rules:
- **process_overview**: Synthesize both summaries into one that accurately covers the combined scope. \
  Combine trigger and outcome statements if they differ.
- **process_steps**: Combine into a single ordered list. Remove only exact duplicates (identical name AND \
  identical description). If the same step name appears with different descriptions or detail, keep BOTH \
  (rename one to distinguish if needed). Err strongly on the side of inclusion — it is better to have \
  more steps than to silently discard steps that may represent different contexts or sub-processes. \
  Preserve all descriptive detail (`description`, `responsible_role`, `inputs`, `outputs`). \
  **sources**: union the `sources` arrays from both items — preserve all URLs. \
  **Step granularity**: if two consecutive steps are sub-parts of the same logical action (e.g. "contact the store" \
  followed by "how to obtain the receipt to send to the store"), merge them into one step with a combined \
  description. A step should represent one complete agent action, not a sentence fragment of a larger action.
- **rules and policies**: Keep all distinct rules; if two are semantically equivalent keep only the clearer, \
  more complete one (prefer the one with rationale). **sources**: union the `sources` arrays of the merged items.
- **roles**: Union of both sets. Keep only business roles — discard individual names or metadata fields. \
  **sources**: union the `sources` arrays.
- **tools**: Union of both sets. Keep only business systems — discard code class names or API method names. \
  **sources**: union the `sources` arrays.
- **escalations**: Keep all distinct escalation paths. **sources**: union the `sources` arrays.
- **SLA**: Use the more specific/stricter value if both are present; otherwise use whichever is set.
- **sources field**: Every item in the merged output must carry a `sources` list that is the union of all \
  source URLs from both inputs for that item. Never drop a source URL — this is the provenance trail.
- Do not invent anything not present in either version.
- **relevant**: Set to `false` only if the relevance brief filter applied and you returned the existing KP unchanged. Set to `true` otherwise."""

_BRIEF_INSTRUCTION = """**Relevance filter**: This Knowledge Product is specifically about: {brief}
If the NEW CURATION is about a completely different topic unrelated to this scope \
(e.g. a cookie consent page, an unrelated product portal, a generic navigation page), \
return the EXISTING KNOWLEDGE PRODUCT unchanged — do not merge any content from the new curation."""

_NO_BRIEF_INSTRUCTION = ""

MERGE_TOOL_DESCRIPTION = "Record the merged process details from both versions, preserving source attribution on every item."


def merge_schema(base_schema: dict) -> dict:
    """Wrap the base extraction schema with a top-level `relevant` boolean for merge calls."""
    wrapped = dict(base_schema)
    props = dict(wrapped.get("properties", {}))
    props["relevant"] = {
        "type": "boolean",
        "description": (
            "Set false ONLY if the relevance brief filter caused you to return the existing KP unchanged. "
            "True in all other cases."
        ),
    }
    wrapped = {**wrapped, "properties": props}
    # relevant is not required — default to true if absent
    return wrapped
