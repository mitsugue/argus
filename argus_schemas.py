# -*- coding: utf-8 -*-
"""ARGUS Structured Output Schemas — v12.2.7(純・feature-flagged)。

高価値6スキーマの明示検証。SDKのStructured Outputs対応が未確認のため、
既存の検証済み互換パーサを維持しつつ、本モジュールで受信後検証を行う。
検証失敗=degraded/schema_failed — 不正出力は証拠に入らない。
"""
import re
from typing import Any, Dict, List, Optional, Tuple

STRUCTURED_OUTPUTS_ENABLED = False      # SDK対応の実測確認まで互換パーサ併用

_URL_RE = re.compile(r"^https?://[\w.\-]+/\S*$|^https?://[\w.\-]+/?$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([T ].*)?$|^unknown$")

SCHEMAS: Dict[str, Dict[str, Any]] = {
    "AgentRun": {"required": ("provider", "status", "claims"),
                 "enums": {"status": ("ok", "error", "disabled", "queued",
                                      "degraded", "no_claims")}},
    "EvidenceItem": {"required": ("titleJa", "verificationStatus"),
                     "enums": {"verificationStatus":
                               ("verified", "metadata_only", "inaccessible",
                                "stale", "unknown", "contradicted")}},
    "CatalystVerdict": {"required": ("verdict", "confidence"),
                        "enums": {"confidence": ("high", "medium", "low",
                                                 "unknown")}},
    "GapResolution": {"required": ("resolutionStatus", "resolutionReasonJa"),
                      "enums": {}},
    "ContradictionReport": {"required": ("ownerReadableWarningsJa",),
                            "enums": {}},
    "ResearchQualityScore": {"required": ("argusScore", "status"),
                             "enums": {"status": ("below_gemini",
                                                  "matches_gemini",
                                                  "exceeds_gemini",
                                                  "exceeds_gemini_2x",
                                                  "insufficient_data")}},
}


def validate(schema: str, obj: Any) -> Tuple[bool, Optional[str]]:
    """スキーマ検証。失敗理由を返す(証拠へ入れない判断は呼び出し側)。"""
    spec = SCHEMAS.get(schema)
    if spec is None:
        return False, f"unknown_schema:{schema}"
    if not isinstance(obj, dict):
        return False, "not_object"
    for k in spec["required"]:
        if k not in obj:
            return False, f"missing_required:{k}"
    for k, allowed in spec["enums"].items():
        if k in obj and obj[k] not in allowed:
            return False, f"invalid_enum:{k}={obj[k]}"
    if "url" in obj and obj["url"] not in (None, "", "unknown"):
        if not _URL_RE.match(str(obj["url"])):
            return False, "invalid_url"
    if "publishedAt" in obj and obj["publishedAt"] not in (None, ""):
        if not _DATE_RE.match(str(obj["publishedAt"])):
            return False, "invalid_date"
    return True, None


def validate_claims(claims: List[Any]) -> Dict[str, Any]:
    ok, rejected = [], []
    for c in (claims or []):
        good, why = validate("EvidenceItem",
                             {**c, "verificationStatus":
                              c.get("verificationStatus", "unknown")}
                             if isinstance(c, dict) else c)
        (ok if good else rejected).append(
            c if good else {"reason": why})
    return {"accepted": ok, "rejectedCount": len(rejected),
            "schemaFailed": len(rejected) > 0 and len(ok) == 0}
