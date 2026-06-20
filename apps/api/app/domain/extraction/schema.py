from __future__ import annotations

from app.domain.extraction.ports import ExtractionSchema

KNOWLEDGE_EXTRACTION_SCHEMA = ExtractionSchema(
    json_schema={
        "type": "object",
        "properties": {
            "process_steps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Ordered process steps, e.g. 'Validate Address', 'Select Carrier'.",
            },
            "rules": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"condition": {"type": "string"}, "action": {"type": "string"}},
                    "required": ["condition", "action"],
                },
                "description": "Business rules, e.g. {condition: 'weight > 30kg', action: 'use freight'}.",
            },
            "policies": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"condition": {"type": "string"}, "action": {"type": "string"}},
                    "required": ["condition", "action"],
                },
                "description": "Policies, e.g. {condition: 'shipment_value > 1000', action: 'manager approval'}.",
            },
            "sla_target": {
                "type": ["string", "null"],
                "description": "Service level target duration, e.g. '2h'. Null if no SLA is stated.",
            },
            "escalations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"after": {"type": "string"}, "escalate_to": {"type": "string"}},
                    "required": ["after", "escalate_to"],
                },
                "description": "Escalation paths, e.g. {after: '90m', escalate_to: 'Logistics Manager'}.",
            },
            "roles": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Roles responsible for or involved in this process.",
            },
            "tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": "APIs/tools referenced, e.g. 'sap_create_shipment'.",
            },
        },
        "required": ["process_steps", "rules", "policies", "sla_target", "escalations", "roles", "tools"],
    }
)
