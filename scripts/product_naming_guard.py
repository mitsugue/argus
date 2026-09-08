#!/usr/bin/env python3
"""Audit product names using a required policy held outside the product tree.

Reports contain rule IDs, line numbers and path hashes, never matched text.
The policy is plain UTF-8 JSON; it is neither bundled nor encoded in source.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import unicodedata


def load_policy(path: Path, product_root: Path):
    path, product_root = path.resolve(), product_root.resolve()
    if path.is_relative_to(product_root):
        raise ValueError("policy_must_be_outside_product")
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schemaVersion") != "product-naming-policy-v1":
        raise ValueError("policy_schema_invalid")
    rules = value.get("rules")
    if not isinstance(rules, list) or not rules:
        raise ValueError("policy_rules_required")
    compiled, seen = [], set()
    for row in rules:
        rid = row.get("id")
        if not isinstance(rid, str) or not re.fullmatch(r"N[0-9]{3}", rid) or rid in seen:
            raise ValueError("anonymous_rule_id_required")
        expression = row.get("pattern")
        if not isinstance(expression, str) or not expression:
            raise ValueError("rule_pattern_required")
        pattern = re.compile(expression)
        if pattern.search(""):
            raise ValueError("empty_match_rule_rejected")
        compiled.append((rid, pattern))
        seen.add(rid)
    return compiled


def inspect_text(text: str, rules):
    normalized = unicodedata.normalize("NFKC", text)
    return [{"ruleId": rid, "line": lineno, "count": len(matches)}
            for lineno, line in enumerate(normalized.splitlines(), 1)
            for rid, pattern in rules if (matches := list(pattern.finditer(line)))]


def audit(paths: list[Path], *, root: Path, rules):
    findings, inspected, binary, missing = [], 0, 0, 0
    for path in sorted(set(paths)):
        relative = str(path.relative_to(root))
        path_id = hashlib.sha256(relative.encode()).hexdigest()
        for item in inspect_text(relative, rules):
            findings.append({"pathId": path_id, "location": "path", **item})
        if not path.is_file():
            missing += 1
            continue
        if path.is_symlink() and not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("external_symlink_requires_separate_audit")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            binary += 1
            continue
        inspected += 1
        for item in inspect_text(text, rules):
            findings.append({"pathId": path_id, "location": "content", **item})
    return {"schemaVersion": "product-naming-audit-v1",
            "status": "FAIL" if findings or missing else "PASS",
            "textFilesInspected": inspected, "binaryFilesNotTextScanned": binary,
            "missingFiles": missing, "findings": findings,
            "scope": "selected_paths_and_utf8_contents"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--directory", type=Path,
                        help="Audit every file in this artifact directory instead of Git files")
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        rules = load_policy(args.policy, root)
        if args.directory:
            target = args.directory.resolve()
            if not target.is_relative_to(root) or not target.is_dir():
                raise ValueError("artifact_directory_invalid")
            paths = [p for p in target.rglob("*") if p.is_file()]
            if not paths:
                raise ValueError("artifact_directory_empty")
        else:
            raw = subprocess.check_output(
                ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=root)
            paths = [root / p for p in raw.decode().split("\0") if p]
            # Deleted tracked files are absent from the candidate artifact.
            deleted = subprocess.check_output(["git", "ls-files", "-z", "--deleted"], cwd=root)
            absent = {root / p for p in deleted.decode().split("\0") if p}
            paths = [p for p in paths if p not in absent]
        result = audit(paths, root=root, rules=rules)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "PASS" else 1
    except (OSError, ValueError, re.error, subprocess.CalledProcessError):
        print(json.dumps({"schemaVersion": "product-naming-audit-v1", "status": "ERROR",
                          "reason": "policy_or_audit_unavailable"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
