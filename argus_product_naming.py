"""Runtime admission of AI content using an external plain-text naming policy.

This prevents new content from reintroducing retired metadata. It does not
rename or conceal existing records; those require their own verified migration.
Diagnostics never contain the matched text, prompt, source URL or response.
"""
from functools import lru_cache
import json
import os
import re
import unicodedata

import argus_persistent_storage


class NamingPolicyError(ValueError):
    pass


def compile_policy(value):
    if not isinstance(value, dict) or value.get("schemaVersion") != "product-naming-policy-v1":
        raise ValueError("policy_schema_invalid")
    rows = value.get("rules")
    if not isinstance(rows, list) or not rows:
        raise ValueError("policy_rules_required")
    compiled, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("rule_object_required")
        rid, expression = row.get("id"), row.get("pattern")
        if not isinstance(rid, str) or not re.fullmatch(r"N[0-9]{3}", rid) or rid in seen:
            raise ValueError("anonymous_rule_id_required")
        if not isinstance(expression, str) or not expression:
            raise ValueError("rule_pattern_required")
        pattern = re.compile(expression)
        if pattern.search(""):
            raise ValueError("empty_match_rule_rejected")
        compiled.append((rid, pattern))
        seen.add(rid)
    return tuple(compiled)


@lru_cache(maxsize=1)
def _runtime_rules(raw):
    try:
        return compile_policy(json.loads(raw))
    except (ValueError, TypeError, re.error):
        raise NamingPolicyError("naming_policy_unavailable") from None


def inspect_content(value, rules):
    findings, active = set(), set()

    def visit(item, depth=0):
        if depth > 128:
            raise NamingPolicyError("naming_content_uninspectable")
        if isinstance(item, str):
            normalized = unicodedata.normalize("NFKC", item)
            findings.update(rid for rid, pattern in rules if pattern.search(normalized))
        elif isinstance(item, (dict, list, tuple)):
            identity = id(item)
            if identity in active:
                raise NamingPolicyError("naming_content_uninspectable")
            active.add(identity)
            if isinstance(item, dict):
                for key, child in item.items():
                    visit(key, depth + 1)
                    visit(child, depth + 1)
            else:
                for child in item:
                    visit(child, depth + 1)
            active.remove(identity)
        elif item is not None and not isinstance(item, (int, float, bool)):
            raise NamingPolicyError("naming_content_uninspectable")

    visit(value)
    return {"status": "REJECTED" if findings else "PASS", "ruleIds": sorted(findings)}


def require_allowed(value, *, required=None):
    raw = os.environ.get("PRODUCT_NAMING_POLICY", "")
    if required is None:
        required = argus_persistent_storage.production_mode()
    if not raw:
        if required:
            raise NamingPolicyError("naming_policy_unavailable")
        return {"status": "NOT_CONFIGURED", "ruleIds": []}
    result = inspect_content(value, _runtime_rules(raw))
    if result["status"] != "PASS":
        raise NamingPolicyError("naming_content_rejected:" + ",".join(result["ruleIds"]))
    return result
