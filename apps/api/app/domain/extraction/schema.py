from __future__ import annotations

from app.domain.extraction.ports import ExtractionSchema

KNOWLEDGE_EXTRACTION_SCHEMA = ExtractionSchema(
    json_schema={
        "type": "object",
        "properties": {
            "process_overview": {
                "type": "object",
                "description": "High-level context about this process, required for AI agent orientation.",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "1-3 sentences describing what this process achieves and why it matters.",
                    },
                    "trigger": {
                        "type": "string",
                        "description": "The event, condition, or action that initiates this process.",
                    },
                    "outcome": {
                        "type": "string",
                        "description": "What a successful completion of this process looks like.",
                    },
                },
                "required": ["summary", "trigger", "outcome"],
            },
            "process_steps": {
                "type": "array",
                "description": "Ordered process steps with enough detail for an AI agent to understand and orchestrate them.",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Short step label, e.g. 'Validate Address'.",
                        },
                        "description": {
                            "type": "string",
                            "description": "What to do in this step — specific enough for an agent to act on. Include key details, conditions, and how-to information. Do not just restate the step name.",
                        },
                        "responsible_role": {
                            "type": "string",
                            "description": "Which business role performs this step, e.g. 'Sales Representative'. Leave blank if not stated.",
                        },
                        "inputs": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Data or documents needed to start this step.",
                        },
                        "outputs": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Data or documents produced by this step.",
                        },
                        "decision": {
                            "type": ["string", "null"],
                            "description": "If this step is a decision point, describe the branching logic. Null if not a decision.",
                        },
                        "tools_used": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Business systems used in this step, e.g. 'Salesforce', 'SAP'.",
                        },
                    },
                    "required": ["name", "description"],
                },
            },
            "rules": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "condition": {"type": "string", "description": "When this rule applies."},
                        "action": {"type": "string", "description": "What must happen."},
                        "rationale": {
                            "type": "string",
                            "description": "Why this rule exists, if stated in the document.",
                        },
                    },
                    "required": ["condition", "action"],
                },
                "description": "Business rules that must be applied during the process.",
            },
            "policies": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "condition": {"type": "string"},
                        "action": {"type": "string"},
                        "rationale": {"type": "string"},
                    },
                    "required": ["condition", "action"],
                },
                "description": "Governance or compliance policies.",
            },
            "sla_target": {
                "type": ["string", "null"],
                "description": "Primary service level target, e.g. '2h response time'. Null if not stated.",
            },
            "escalations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "trigger": {
                            "type": "string",
                            "description": "What triggers the escalation — time elapsed (e.g. '90m'), a condition, or an event.",
                        },
                        "escalate_to": {
                            "type": "string",
                            "description": "Role or team to escalate to.",
                        },
                        "action": {
                            "type": "string",
                            "description": "What the escalated party should do.",
                        },
                    },
                    "required": ["trigger", "escalate_to"],
                },
                "description": "Escalation paths when SLA is breached or issues arise.",
            },
            "roles": {
                "type": "array",
                "description": "Business roles involved in this process. Do NOT include individual person names.",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Role name, e.g. 'Sales Manager', 'Finance Team'. Never an individual's name.",
                        },
                        "responsibilities": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "What this role is responsible for in this process.",
                        },
                    },
                    "required": ["name"],
                },
            },
            "tools": {
                "type": "array",
                "description": "Business systems and tools used in this process. Do NOT include internal code class names, Apex triggers, or API method names.",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Tool or system name, e.g. 'Salesforce', 'SAP', 'Confluence'.",
                        },
                        "purpose": {
                            "type": "string",
                            "description": "How this tool is used in the process.",
                        },
                    },
                    "required": ["name"],
                },
            },
        },
        "required": ["process_overview", "process_steps", "rules", "policies", "sla_target", "escalations", "roles", "tools"],
    }
)
