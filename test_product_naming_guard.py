"""Generic naming audit contracts; actual policy belongs outside this product."""
import json
from pathlib import Path

import pytest

from scripts.product_naming_guard import audit, inspect_text, load_policy


def policy(tmp_path):
    root = tmp_path / "product"
    root.mkdir()
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({"schemaVersion": "product-naming-policy-v1", "rules": [
        {"id": "N001", "pattern": r"(?i)\bretired_person\b"}]}))
    return root, path


def test_external_policy_normalizes_width_without_general_word_replacement(tmp_path):
    root, path = policy(tmp_path)
    rules = load_policy(path, root)
    assert inspect_text("ＲＥＴＩＲＥＤ＿ＰＥＲＳＯＮ", rules)[0]["ruleId"] == "N001"
    assert not inspect_text("retired_personality", rules)


def test_audit_covers_paths_and_text_without_echoing_matches(tmp_path):
    root, path = policy(tmp_path)
    file = root / "retired_person.txt"
    file.write_text("retired_person\nordinary\nRETIRED_PERSON")
    result = audit([file], root=root, rules=load_policy(path, root))
    assert result["status"] == "FAIL"
    assert len(result["findings"]) == 3
    assert "retired_person" not in json.dumps(result).lower()
    assert all(len(row["pathId"]) == 64 for row in result["findings"])


def test_missing_policy_and_product_embedded_policy_never_pass(tmp_path):
    root, path = policy(tmp_path)
    with pytest.raises(OSError):
        load_policy(tmp_path / "missing.json", root)
    embedded = root / "policy.json"
    embedded.write_text(path.read_text())
    with pytest.raises(ValueError, match="outside_product"):
        load_policy(embedded, root)
    path.write_text('{"schemaVersion":"product-naming-policy-v1","rules":[]}')
    with pytest.raises(ValueError, match="rules_required"):
        load_policy(path, root)
