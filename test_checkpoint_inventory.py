import json
import subprocess
import sys


def test_inventory_reports_every_top_level_section_without_values(tmp_path):
    source = tmp_path / "checkpoint.json"
    source.write_text(json.dumps({"a": [1, 2], "b": {"x": "secret-value"}}))
    result = subprocess.run(
        [sys.executable, "scripts/checkpoint_inventory.py", str(source)],
        check=True, capture_output=True, text=True)
    report = json.loads(result.stdout)
    assert report["sectionCount"] == 2
    assert {row["section"] for row in report["sections"]} == {"a", "b"}
    assert "secret-value" not in result.stdout
    assert sum(row["serializedBytes"] for row in report["sections"]) == \
        report["sectionSerializedBytes"]
