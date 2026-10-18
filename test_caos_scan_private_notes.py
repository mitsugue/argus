"""The scheduled collection keeps response bodies out of the public log (2026-10-18)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def test_collection_responses_are_stored_privately_not_printed():
    text = (ROOT / '.github/workflows/caos-scan.yml').read_text()
    for line in ('echo "caos-collect: $RESP"', 'echo "osint-agents: $OS"', 'echo "missions-tick[$BATCH]: $MT"',
                 'echo "osint-benchmark: $BM"', 'echo "osint-canary: $CN"'):
        assert line not in text, line
    assert text.count('private_diagnostics_store.py') == 2 and 'ARGUS_PRIVATE_LEDGER_TOKEN' in text
    assert 'caos-collect: stored privately' in text
