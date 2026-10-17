"""Operational workflows must not probe retired paid AI providers."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent


def test_manual_and_research_workflows_are_terra_only():
    paths = (
        ".github/workflows/news-intake-ops.yml",
        ".github/workflows/prediction-ledger.yml",
        ".github/workflows/research-benchmark.yml",
    )
    for relative in paths:
        text = (ROOT / relative).read_text(encoding="utf-8").lower()
        assert "gemini" not in text
        assert "model=sol" not in text

    benchmark = (ROOT / paths[-1]).read_text(encoding="utf-8")
    assert '"models":["gpt-5.6-terra"]' in benchmark
