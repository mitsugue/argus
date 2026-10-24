"""Repair a rejected presentation plan by rule before asking the model again.

Measured 2026-10-24 (ai-usage-report, 10/17-10/23): 33-76% of the
integrated-view editions needed a second full model call (~45,000 input
tokens each). About four in five first rejections were two layout faults
that a rule can fix without changing any text the model wrote:

- presentation_caption_evidence: a caption cites an evidence id that its own
  display element does not carry (or that the context does not have). The
  unknown ids are removed; at least one valid id must remain.
- presentation_required_demotion: an element the catalog marks mandatory was
  placed in 'detail'. It is raised to 'support', the lowest allowed place
  (the main account, view, to 'lead', where Today's reading flow needs it).
- presentation_urgent_demotion: an urgent element was not placed in 'lead'
  or was 'quiet'. It is placed in 'lead' and a 'quiet' emphasis becomes
  'normal'.

The repaired plan is validated again by argus_presentation_intent.validate_plan,
unchanged. Anything the rules cannot fix (wording, lengths, numbers, the
primary hierarchy, ordering) still goes to the existing bounded correction
call. Pure functions only: no model, no clock, no store.
"""
from copy import deepcopy
from typing import Any, Dict, List, Mapping, Optional, Tuple

REPAIRABLE = frozenset({
    "presentation_caption_evidence",
    "presentation_required_demotion",
    "presentation_urgent_demotion",
})


def repair(plan: Any, catalog: Mapping[str, Any],
           context: Optional[Mapping[str, Any]]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, str]]]:
    """A copy of the plan with the rule-fixable faults fixed, and the changes.

    Returns (None, []) when the plan has nothing a rule can fix."""
    if not isinstance(plan, Mapping) or not isinstance(plan.get("elements"), list):
        return None, []
    known = {row.get("id"): row for row in catalog.get("elements") or [] if isinstance(row, Mapping)}
    facts = {f.get("evidenceId") for f in (context or {}).get("facts") or [] if isinstance(f, Mapping)}
    fixed = deepcopy(dict(plan))
    changes: List[Dict[str, str]] = []
    for row in fixed["elements"]:
        if not isinstance(row, dict):
            continue
        source = known.get(row.get("id"))
        if not isinstance(source, Mapping):
            continue
        identifier = str(row.get("id"))
        if source.get("urgent") and (row.get("placement") != "lead" or row.get("emphasis") == "quiet"):
            row["placement"] = "lead"
            if row.get("emphasis") == "quiet":
                row["emphasis"] = "normal"
            changes.append({"id": identifier, "rule": "presentation_urgent_demotion"})
        elif source.get("mandatory") and row.get("placement") == "detail":
            # The main account (view) belongs in lead on Today; any other
            # mandatory element goes to support, the lowest allowed place.
            row["placement"] = "lead" if identifier == "view" else "support"
            changes.append({"id": identifier, "rule": "presentation_required_demotion"})
        caption = row.get("caption")
        if isinstance(caption, dict) and isinstance(caption.get("evidenceIds"), list):
            allowed = set(source.get("evidenceIds") or [])
            refs = caption["evidenceIds"]
            keep = [ref for ref in refs if ref in allowed and ref in facts]
            if keep and len(keep) != len(refs):
                caption["evidenceIds"] = keep
                changes.append({"id": identifier, "rule": "presentation_caption_evidence"})
    return (fixed, changes) if changes else (None, [])


__all__ = ["REPAIRABLE", "repair"]
