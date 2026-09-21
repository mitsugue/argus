"""Retired monitors must not make unattended external requests."""
from pathlib import Path


WORKFLOWS = (
    "ai-rejudge.yml",
    "crypto-watch.yml",
    "market-watch.yml",
    "mover-causes.yml",
)


def _trigger_section(name: str) -> str:
    text = Path(".github/workflows", name).read_text(encoding="utf-8")
    return text.split("\non:\n", 1)[1].split("\npermissions:", 1)[0].split("\njobs:", 1)[0]


def test_retired_background_workflows_are_manual_only():
    for name in WORKFLOWS:
        trigger = _trigger_section(name)
        assert "workflow_dispatch:" in trigger
        assert "schedule:" not in trigger
