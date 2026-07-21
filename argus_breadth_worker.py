# -*- coding: utf-8 -*-
"""Clean-process entry point for the deterministic J-Quants breadth worker."""
import sys
import types


def _disable_quote_adapter():
    """Keep the breadth-only process from loading the stateful moomoo SDK."""
    adapter = types.ModuleType("moomoo")

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("quote_adapter_disabled_in_breadth_worker")

    adapter.OpenQuoteContext = unavailable
    adapter.OpenSecTradeContext = unavailable
    adapter.RET_OK = 0
    sys.modules["moomoo"] = adapter


def process_entry(job_id, connection, memory_soft_limit_mb, ledger_seed=None):
    """Import the backend only after isolating unrelated quote side effects."""
    _disable_quote_adapter()
    import scanner
    scanner._jquants_breadth_process_entry(
        job_id, connection, memory_soft_limit_mb, ledger_seed)
