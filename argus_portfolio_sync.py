"""ARGUS V11.9.0 — Portfolio Sync / Snapshot Foundation (pure, deterministic).

THREE-LAYER ARCHITECTURE (documented here as the single source of truth):

  A. LOCAL LAYER (exists, unchanged)
     localStorage on each device (argus.assets.v1 holds quantity/avgCost).
     Fast, offline-capable, zero server dependency.

  B. PRIVATE CLOUD SYNC LAYER (exists — client-encrypted; formalized here)
     The passphrase vault (web/src/lib/vault.ts): the DEVICE encrypts the
     backup (AES-GCM, PBKDF2 200k iters) and only CIPHERTEXT reaches the
     backend relay / public ledger branch. Any device with the passphrase
     restores and merges (sync-v2 per-item merge + tombstones + deviceId).
     → Mac/iPhone/iPad sync of positions ALREADY WORKS this way, with
       encryptionStatus='client_encrypted'. The server NEVER sees plaintext
       holdings, so there is nothing the server could leak.
     A future server-side plaintext store (Supabase/private DB) is modeled
     but DISABLED BY DEFAULT — endpoints return disabled/403 until an
     authenticated private backend actually exists.

  C. SNAPSHOT / AUDIT LAYER (new in v11.9.0)
     Append-only local snapshots (argus.portfolio.snapshots.v1) + decision
     audit records (argus.decision.audit.v1). Both keys ride the SAME
     encrypted vault (added to BACKUP_KEYS), so history is preserved
     permanently and syncs across devices — still ciphertext-only in the
     cloud. Future backtesting fills the futureReturn placeholders.

STILL REQUIRED for a server-side (non-vault) auto sync, intentionally NOT
implemented yet: owner authentication/lock, a private backend table or
encrypted object storage, a conflict-resolution UI, device registration,
optional client-side encryption for that path, recovery keys, retention
policy. Until then: sync endpoints stay disabled; the vault is the canonical
cross-device path.

No broker login. No trading. Nothing here fabricates positions.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

SYNC_SCHEMA_VERSION = "portfolio-sync-v1"
SNAPSHOT_SCHEMA_VERSION = "portfolio-snapshot-v1"
AUDIT_SCHEMA_VERSION = "decision-audit-v1"

CONFLICT_STATUSES = ("clean", "local_newer", "cloud_newer", "conflict", "disabled")
ENCRYPTION_STATUSES = ("local_only", "server_private", "client_encrypted", "unknown")
SYNC_SOURCES = ("localStorage", "manual_sync", "private_cloud", "import", "unknown")
PRIVACY_LEVELS = ("private", "redacted", "local_only")
DECISION_CONTEXTS = ("add_allowed_small", "add_only_on_pullback", "wait", "avoid_chase",
                     "monitor", "caution", "hold", "investigate", "no_action")
OWNER_ACTIONS = ("bought", "sold", "trimmed", "added", "held", "watched", "skipped", "unknown")

# Fields that must NEVER appear on public unauthenticated endpoints.
SENSITIVE_FIELDS = ("quantity", "averageCost", "avgCost", "costBasis", "marketValue",
                    "unrealizedPnl", "unrealizedPnlPct", "accountType", "portfolioTotal",
                    "totalMarketValue", "weightPct", "valueJpy", "ownerNote", "positions")


def validate_sync_record(rec: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """PortfolioSyncRecord validation — shape only, never rejects on values."""
    errs: List[str] = []
    if rec.get("schemaVersion") != SYNC_SCHEMA_VERSION:
        errs.append(f"schemaVersion must be {SYNC_SCHEMA_VERSION}")
    if not rec.get("portfolioId"):
        errs.append("portfolioId required")
    if not isinstance(rec.get("positions"), list):
        errs.append("positions must be a list")
    if rec.get("conflictStatus") not in CONFLICT_STATUSES:
        errs.append("conflictStatus invalid")
    if rec.get("encryptionStatus") not in ENCRYPTION_STATUSES:
        errs.append("encryptionStatus invalid")
    if rec.get("source") not in SYNC_SOURCES:
        errs.append("source invalid")
    for i, p in enumerate(rec.get("positions") or []):
        if not isinstance(p, dict) or not p.get("symbol"):
            errs.append(f"positions[{i}] needs symbol")
            break
    return (not errs), errs


def detect_conflict(local_rev: Optional[int], cloud_rev: Optional[int],
                    local_updated: Optional[str], cloud_updated: Optional[str],
                    cloud_enabled: bool = False) -> str:
    """Deterministic conflict state. NEVER silently overwrites: 'conflict'
    means both sides advanced and a human (or per-item merge) must resolve."""
    if not cloud_enabled:
        return "disabled"
    lr, cr = local_rev or 0, cloud_rev or 0
    if lr == cr:
        return "clean"
    if lr > cr and (not cloud_updated or (local_updated or "") >= cloud_updated):
        return "local_newer"
    if cr > lr and (not local_updated or (cloud_updated or "") >= local_updated):
        return "cloud_newer"
    return "conflict"


def validate_snapshot(snap: Dict[str, Any]) -> Tuple[bool, List[str]]:
    errs: List[str] = []
    if snap.get("schemaVersion") != SNAPSHOT_SCHEMA_VERSION:
        errs.append(f"schemaVersion must be {SNAPSHOT_SCHEMA_VERSION}")
    for k in ("snapshotId", "asOf", "createdAt", "appVersion"):
        if not snap.get(k):
            errs.append(f"{k} required")
    if snap.get("privacyLevel") not in PRIVACY_LEVELS:
        errs.append("privacyLevel invalid")
    return (not errs), errs


def validate_audit_record(rec: Dict[str, Any]) -> Tuple[bool, List[str]]:
    errs: List[str] = []
    if rec.get("schemaVersion") != AUDIT_SCHEMA_VERSION:
        errs.append(f"schemaVersion must be {AUDIT_SCHEMA_VERSION}")
    if not rec.get("symbol"):
        errs.append("symbol required")
    if rec.get("decisionContext") not in DECISION_CONTEXTS:
        errs.append("decisionContext invalid")
    if rec.get("ownerAction") is not None and rec.get("ownerAction") not in OWNER_ACTIONS:
        errs.append("ownerAction invalid")
    for k in ("futureReturn1d", "futureReturn3d", "futureReturn5d", "futureReturn20d"):
        if k not in rec:
            errs.append(f"{k} placeholder required (null ok)")
    return (not errs), errs


def contains_sensitive(obj: Any) -> List[str]:
    """Recursively find sensitive KEY names — the public-leak tripwire."""
    found: List[str] = []

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in SENSITIVE_FIELDS:
                    found.append(k)
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(obj)
    return sorted(set(found))


def public_sync_status(*, server_sync_enabled: bool, now_iso: str) -> Dict[str, Any]:
    """The ONLY portfolio-sync payload a public endpoint may serve. Contains
    architecture facts, never holdings. Guarded by contains_sensitive in tests."""
    return {
        "schemaVersion": "portfolio-sync-status-v1",
        "asOf": now_iso,
        "syncSchemaVersion": SYNC_SCHEMA_VERSION,
        "snapshotSchemaVersion": SNAPSHOT_SCHEMA_VERSION,
        "storageLayers": {
            "local": {"status": "active", "noteJa": "保有データは端末内(localStorage)に保存。"},
            "privateCloud": {
                "status": "client_encrypted_vault",
                "serverPlaintextSync": "disabled" if not server_sync_enabled else "enabled",
                "noteJa": "端末間同期は既存のパスフレーズ暗号化バックアップ(vault)経由。"
                          "平文の保有データがサーバーに置かれる方式は認証基盤が整うまで無効。",
            },
            "snapshotAudit": {
                "status": "local_appendonly",
                "noteJa": "日次スナップショットと判断監査は端末内に追記保存され、"
                          "暗号化バックアップに含まれて恒久保存・端末間同期される。",
            },
        },
        "privacyNoteJa": "このエンドポイントが保有数量・取得単価・評価額を返すことはない"
                         "(構造的に含まれない)。クラウドに出るのは暗号文のみ。",
        "disclaimerJa": "同期・保存の状態表示であり売買指示ではない。",
    }


def export_manifest(app_version: str, now_iso: str) -> Dict[str, Any]:
    """Envelope the FE export uses — schema contract for future CSV/import
    mapping (SBI/Rakuten/moomoo CSVs map into positions[] later)."""
    return {
        "app": "argus",
        "kind": "portfolio-backup",
        "schemaVersion": SYNC_SCHEMA_VERSION,
        "exportedAt": now_iso,
        "appVersion": app_version,
        "contains": ["positions", "snapshots", "decisionAudit"],
        "forbidden": ["secrets", "tokens", "hmac", "opendCredentials", "brokerCredentials"],
        "warningJa": "このファイルには保有数量・取得単価などの個人投資情報が含まれます。"
                     "iCloud Drive等の安全な場所に保管してください。",
    }
