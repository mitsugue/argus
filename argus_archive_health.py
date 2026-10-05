"""Local SQLite counts/bytes for admin diagnostics; never read record bodies.

No creation, migration, deletion, provider access, or backup authority. Queries
have a short budget; unavailable measurements stay unknown, never zero.
"""
from pathlib import Path
import sqlite3
import stat
import time

TABLES = {
    "analysis_history": ("views", "outcomes", "level_map_eps", "level_map_mornings", "candidate_records"),
    "source_history": ("raw_sources", "observations", "selected_vix_inputs", "selected_feature_inputs"),
}
QUERY_BUDGET_SEC = 0.25


def _file_bytes(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("archive_regular_file_required")
    return info.st_size


def read_archive_metadata(path, *, kind):
    """Read committed rows (including WAL) and file sizes, not source content.

    Counts and size stats are observations, not an atomic backup, an integrity
    check or a measurement of the hosting account's storage quota.
    """
    if kind not in TABLES:
        raise ValueError("archive_kind_unknown")
    result = {"status": "not_configured" if path is None else "unavailable",
              "databaseBytes": None, "walBytes": None,
              "tables": {name: {"status": "unknown", "rows": None} for name in TABLES[kind]}}
    if path is None:
        return result
    conn = None
    try:
        path = Path(path)
        if not path.exists() and not path.is_symlink():
            result["status"] = "missing"
            return result
        database_bytes = _file_bytes(path)
        wal = path.with_name(path.name + "-wal")
        wal_bytes = _file_bytes(wal) if wal.exists() or wal.is_symlink() else 0
        deadline = time.monotonic() + QUERY_BUDGET_SEC
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True,
                               timeout=QUERY_BUDGET_SEC)
        conn.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        tables = {}
        for name in TABLES[kind]:
            exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
            tables[name] = {"status": "measured" if exists else "not_created",
                            "rows": conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] if exists else None}
        if time.monotonic() >= deadline:
            raise TimeoutError("archive_measurement_budget")
        return {"status": "measured", "databaseBytes": database_bytes,
                "walBytes": wal_bytes, "tables": tables}
    except (OSError, ValueError, sqlite3.Error, TimeoutError):
        return result
    finally:
        if conn is not None:
            conn.close()
