"""Shared explanation validation only: no market composer or decision authority."""
from __future__ import annotations
import re
import hashlib
import json
from typing import Any,Dict,Mapping,Optional

UNIFIED_FACT_LIMIT = 64


_FORBIDDEN_BRIEF_PATTERNS = (
    "買え", "売れ", "全力", "今すぐ買", "今すぐ売", "確実に", "必ず",
    "暴騰確率", "上昇確率", "%の確率", "％の確率",
)


def _digits_of(text: str) -> set:
    # Formatting an existing value with thousands separators does not invent
    # a new number. Only correctly grouped numeric tokens are normalized.
    value = re.sub(r"(?<![\d,])\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\d,])",
                   lambda match: match.group(0).replace(",", ""), str(text or ""))
    return set(re.findall(r"\d+(?:\.\d+)?", value))


UNIFIED_SECTIONS = ("view", "reasons", "changes", "impact", "next", "invalidation")


def validate_unified_ai(value: Any, context: Mapping[str, Any], *, diagnostic=None) -> Optional[Dict[str, Any]]:
    """Reject unsupported numbers, references and claims of observed inference.

    This is a structural constraint, not proof that every sentence is correct.
    Source inspection and semantic evaluation remain required before acceptance.
    """
    def rejected(reason, section=None):
        if isinstance(diagnostic, dict):
            diagnostic.update(status="REJECTED", reason=reason, section=section)
        return None
    if not isinstance(value, Mapping) or set(value) != set(UNIFIED_SECTIONS):
        return rejected("six_section_schema_required")
    current = {r["evidenceId"]: r for r in context.get("facts", [])}
    prior = {r["evidenceId"]: r for r in context.get("previousFacts", [])}
    sections = {}
    for key in UNIFIED_SECTIONS:
        row = value[key]
        if not isinstance(row, Mapping) or set(row) != {"textJa", "evidenceIds", "kind"}:
            return rejected("section_schema_invalid", key)
        text, refs, kind = row["textJa"], row["evidenceIds"], row["kind"]
        if not isinstance(text, str) or not text.strip() or len(text) > 240 or \
                kind not in {"FACT", "INFERENCE", "UNKNOWN"} or \
                not isinstance(refs, list) or len(refs) > 6 or \
                any(not isinstance(ref, str) for ref in refs) or len(set(refs)) != len(refs):
            if isinstance(diagnostic, dict):
                diagnostic['fieldIssues'] = {
                    'textCharacters': len(text) if isinstance(text, str) else None,
                    'textLimit': 240,
                    'kindAllowed': kind in {'FACT', 'INFERENCE', 'UNKNOWN'} if isinstance(kind, str) else False,
                    'referenceCount': len(refs) if isinstance(refs, list) else None,
                    'referenceLimit': 6,
                    'referencesDistinctStrings': isinstance(refs, list) and all(isinstance(ref, str) for ref in refs)
                        and len(set(refs)) == len(refs),
                }
            return rejected("section_field_invalid", key)
        allowed = {**prior, **current} if key == "changes" else current
        if any(ref not in allowed for ref in refs):
            return rejected("unknown_evidence_reference", key)
        if kind != "UNKNOWN" and not refs:
            return rejected("evidence_reference_required", key)
        if key == "impact" and not context.get("ownerContextAvailable") and kind != "UNKNOWN":
            return rejected("owner_context_unavailable", key)
        if key == "changes" and not context.get("changes", {}).get("comparisonAvailable") and kind != "UNKNOWN":
            return rejected("previous_context_unavailable", key)
        if kind == "FACT" and (key in {"view", "impact", "next", "invalidation"} or
                any(allowed[ref].get("verification") != "VERIFIED" for ref in refs)):
            return rejected("fact_requires_verified_references", key)
        if any(p in text for p in _FORBIDDEN_BRIEF_PATTERNS) or "確率" in text:
            return rejected("unsupported_authority_or_probability", key)
        allowed_digits = set().union(*(_digits_of(allowed[ref]["text"]) for ref in refs)) if refs else set()
        unsupported = _digits_of(text) - allowed_digits
        if unsupported:
            result = rejected("unsupported_numeric_tokens", key)
            if isinstance(diagnostic, dict):
                diagnostic["unsupportedNumericTokens"] = sorted(unsupported)[:20]
            return result
        if key == "impact" and not context.get("ownerContextAvailable"):
            text = "市場全体の見通しです。登録銘柄ごとの影響は、銘柄別の根拠を確認する必要があります。"
        if key == "changes" and not context.get("changes", {}).get("comparisonAvailable"):
            text = "比較できる前回の見立てをまだ取得していません。"
        sections[key] = {"textJa": text.strip(), "evidenceIds": list(refs), "kind": kind}
    if isinstance(diagnostic, dict):
        diagnostic.update(status="ACCEPTED", reason=None, section=None)
    return {"schemaVersion": "argus-unified-brief-v1", "contextId": context["contextId"],
            "sections": sections, "actionAuthority": False,
            "ownerContextAvailable": context["ownerContextAvailable"],
            "historyStatus": context["historyStatus"]}


def calculation_identity(calculations):
    """Ignore read timestamps, retaining price/input/definition changes."""
    def stable(value):
        if isinstance(value, Mapping):
            return {key: stable(item) for key, item in value.items()
                    if key not in {"informationCutoff", "lastSuccessfulAcquisitionAt", "valuationAcquisition", "researchCache"}}
        if isinstance(value, list):
            return [stable(item) for item in value]
        return value
    return hashlib.sha256(json.dumps(stable(calculations), sort_keys=True,
        separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def prompt_references(context, catalog):
    """Use request-local short references; restore originals before validation.

    All facts, text, units, dates and verification flags remain verbatim. The
    mapping is local to this request and never changes a stored evidence ID.
    """
    fields = {"evidenceId", "evidenceIds", "contextId", "inventoryId", "payloadId",
              "sourceRowSha256", "addedEvidenceIds", "removedEvidenceIds",
              "previousSharedEvidenceIds", "baseMarketContextId", "indexComparisonEvidenceId"}
    forward, reverse = {}, {}
    def walk(value, mapping, *, key=None, allocate=False):
        if isinstance(value, dict):
            return {k: walk(v, mapping, key=k, allocate=allocate) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v, mapping, key=key, allocate=allocate) for v in value]
        if key in fields and isinstance(value, str):
            if allocate and re.fullmatch(r"(?:(?:brief|dialogue)-fact-)?[a-f0-9]{64}", value):
                if value not in mapping:
                    alias = "ref-" + str(len(mapping))
                    mapping[value] = alias
                    reverse[alias] = value
            return mapping.get(value, value)
        return value
    short_context = walk(context, forward, allocate=True)
    short_catalog = walk(catalog, forward, allocate=True)
    def restore(value): return walk(value, reverse)
    def compact(value): return walk(value, forward)
    return short_context, short_catalog, restore, compact
