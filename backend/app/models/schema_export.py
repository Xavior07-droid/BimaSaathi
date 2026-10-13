"""JSON Schema export (A2). `python -m app.models.schema_export` writes files to app/data/schemas/.

gemini_schema() flattens a Pydantic schema into the simple subset Gemini's
response_schema accepts: inlined $refs, no additionalProperties/title/default,
and `anyOf:[X, null]` rewritten to X + nullable:true.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.models.policy import AskOutput, DocumentClassification, ExclusionMatchOutput, FraudReasonOutput, PolicyBrain, PolicyExtraction, RecommendationOutput, SummaryOutput

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "schemas"
MODELS: dict[str, type[BaseModel]] = {
    "policy_brain": PolicyBrain,
    "policy_extraction": PolicyExtraction,
    "summary_output": SummaryOutput,
    "ask_output": AskOutput,
    "exclusion_match_output": ExclusionMatchOutput,
    "document_classification": DocumentClassification,
    "recommendation_output": RecommendationOutput,
    "fraud_reason_output": FraudReasonOutput,
}
_DROP = {"title", "default", "additionalProperties", "$defs", "examples"}


def _inline(node: Any, defs: dict[str, Any]) -> Any:
    if isinstance(node, list):
        return [_inline(n, defs) for n in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        return _inline(defs[node["$ref"].split("/")[-1]], defs)
    if "anyOf" in node:
        non_null = [o for o in node["anyOf"] if o.get("type") != "null"]
        has_null = len(non_null) != len(node["anyOf"])
        if len(non_null) == 1:
            out = _inline(non_null[0], defs)
            if has_null:
                out = {**out, "nullable": True}
            if "description" in node:
                out.setdefault("description", node["description"])
            return out
    out = {k: _inline(v, defs) for k, v in node.items() if k not in _DROP}
    if out.get("type") == "object" and "properties" in out:
        # keep `required` only for fields that have no default (pydantic already does this)
        pass
    return out


def gemini_schema(model: type[BaseModel]) -> dict[str, Any]:
    raw = model.model_json_schema()
    return _inline(raw, raw.get("$defs", {}))


def export_all(out_dir: Path = OUT_DIR) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, model in MODELS.items():
        for suffix, schema in ((".schema.json", model.model_json_schema()),
                               (".gemini.json", gemini_schema(model))):
            p = out_dir / f"{name}{suffix}"
            p.write_text(json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
            written.append(p)
    return written


if __name__ == "__main__":
    for p in export_all():
        print("wrote", p)
