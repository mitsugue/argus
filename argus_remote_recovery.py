# -*- coding: utf-8 -*-
"""Encrypted, checkpoint-bound recovery for compact Remote Journal progress.

The public ledger stores only an AES-GCM envelope.  Plaintext recovery targets
exist transiently inside the backend while a verified checkpoint is produced,
or while that backend verifies/restores an immutable ledger commit.  The
compact read-back remains public-safe and is cryptographically bound to the
encrypted target map.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import os
import re
import secrets
from datetime import datetime
from typing import Any, Dict, Mapping, Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

import argus_remote_journal
import argus_remote_recovery_limits as recovery_limits


PAYLOAD_SCHEMA = "argus-remote-recovery-payload-v1"
NONCE_AUTHORITY_SCHEMA = "argus-remote-recovery-nonce-authority-v1"
NONCE_DOMAIN_CONTEXT = b"argus:remote-journal:recovery:nonce-domain:v2"
SCHEMA = "argus-remote-recovery-envelope-v1"
SIDECAR_SCHEMA = "argus-remote-recovery-sidecar-v1"
ALGORITHM = "AES-256-GCM"
KEY_DERIVATION = "HKDF-SHA-256"
KEY_DERIVATION_SALT_BYTES = 32
HKDF_INFO_DOMAIN = b"argus:remote-journal:recovery:data-key:v1"
AAD_DOMAIN = "argus:remote-journal:recovery:v1"
MAX_ENCODED_BYTES = recovery_limits.MAX_RECOVERY_ENCODED_BYTES
# Compatibility export only.  The canonical authority lives with the compact
# producer/validator and is imported by every Recovery consumer.
MAX_READBACK_BYTES = argus_remote_journal.MAX_COMPACT_READBACK_BYTES
MAX_SIDECAR_BYTES = recovery_limits.MAX_RECOVERY_SIDECAR_BYTES
MAX_PLAINTEXT_BYTES = recovery_limits.MAX_RECOVERY_PLAINTEXT_BYTES
PADDED_PLAINTEXT_BYTES = MAX_PLAINTEXT_BYTES + 4
MAX_NODES = 160_000
MAX_DEPTH = 32
MAX_STRING_CHARS = 1024 * 1024
MAX_NONCE_AUTHORITY_DOMAINS = 16
SHA_RE = re.compile(r"[0-9a-f]{40}")
HASH_RE = re.compile(r"[0-9a-f]{64}")
VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?")
KEY_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,63}")
GENERATION_ID_RE = re.compile(r"rrg-[0-9a-f]{32}")
CHECKPOINT_ID_RE = re.compile(r"rcp-[0-9a-f]{32}")
TARGET_KEYS = (
    "opsJournal", "opsJournalMeta", "opsJournalCompacted",
    "opsSequenceByAggregate", "missions", "missionWindows", "forecasts",
    "outcomes", "incidents", "soak", "postmortems", "periodicReports",
    "challengerRuns", "agentQueue", "missionTickDurability",
)
LIST_LIMITS = {
    "opsJournal": 400,
    "opsJournalCompacted": 40,
    "missions": 300,
    "missionWindows": 240,
    "forecasts": 200,
    "outcomes": 200,
    "incidents": 20,
    "postmortems": 30,
    "periodicReports": 12,
    "challengerRuns": 8,
}
DICT_LIMITS = {
    "opsJournalMeta": 16,
    "opsSequenceByAggregate": 4096,
    "soak": 64,
    "agentQueue": 12,
    "missionTickDurability": 32,
}


class RecoveryBundleError(ValueError):
    """A fixed, payload-free classification safe for telemetry."""

    def __init__(self, classification: str):
        self.classification = str(classification)
        super().__init__(self.classification)


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, ensure_ascii=False,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except RecursionError as exc:
        raise RecoveryBundleError("recovery_json_too_deep") from exc
    except (TypeError, ValueError) as exc:
        raise RecoveryBundleError("recovery_json_invalid") from exc


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _timestamp(value: Any) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else None


def _build_identity(value: Any) -> Dict[str, str]:
    if not isinstance(value, Mapping):
        raise RecoveryBundleError("recovery_build_identity_invalid")
    version = str(value.get("appVersion") or "")
    sha = str(value.get("buildSha") or "").lower()
    if not VERSION_RE.fullmatch(version) or not SHA_RE.fullmatch(sha):
        raise RecoveryBundleError("recovery_build_identity_invalid")
    return {"appVersion": version, "buildSha": sha}


def decode_key(value: Any) -> bytes:
    """Decode exactly one urlsafe-base64 AES-256 key without logging it."""
    text = str(value or "").strip()
    try:
        padding = "=" * ((4 - len(text) % 4) % 4)
        key = base64.b64decode(
            (text + padding).encode("ascii"), altchars=b"-_", validate=True)
    except (ValueError, UnicodeError) as exc:
        raise RecoveryBundleError("recovery_key_invalid") from exc
    if len(key) != 32:
        raise RecoveryBundleError("recovery_key_invalid")
    return key


def validate_key_id(value: Any) -> str:
    identifier = str(value or "").strip()
    if not KEY_ID_RE.fullmatch(identifier):
        raise RecoveryBundleError("recovery_key_id_invalid")
    return identifier


def nonce_material_domain(key: bytes) -> str:
    """Return the private stable domain used only inside encrypted state."""
    if not isinstance(key, bytes) or len(key) != 32:
        raise RecoveryBundleError("recovery_key_invalid")
    return hmac.new(key, NONCE_DOMAIN_CONTEXT, hashlib.sha256).hexdigest()


def _b64_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64_decode(value: Any, classification: str) -> bytes:
    text = str(value or "")
    try:
        padding = "=" * ((4 - len(text) % 4) % 4)
        return base64.b64decode(
            (text + padding).encode("ascii"), altchars=b"-_", validate=True)
    except (ValueError, UnicodeError) as exc:
        raise RecoveryBundleError(classification) from exc


def _decode_key_derivation_salt(value: Any) -> bytes:
    """Decode the one canonical, unpadded 256-bit public KDF salt."""
    if not isinstance(value, str) or len(value) > 64:
        raise RecoveryBundleError("recovery_key_derivation_salt_invalid")
    salt = _b64_decode(value, "recovery_key_derivation_salt_invalid")
    if len(salt) != KEY_DERIVATION_SALT_BYTES or _b64_encode(salt) != value:
        raise RecoveryBundleError("recovery_key_derivation_salt_invalid")
    return salt


def _strict_positive_int(value: Any, classification: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RecoveryBundleError(classification)
    return value


def _validate_outer_json_tree(value: Any) -> None:
    """Bound untrusted public containers without recursive Python calls."""
    nodes = 0
    pending = [(value, 0)]
    while pending:
        current, depth = pending.pop()
        nodes += 1
        if nodes > MAX_NODES or depth > MAX_DEPTH:
            raise RecoveryBundleError("recovery_outer_bounds_invalid")
        if isinstance(current, Mapping):
            pending.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            pending.extend((item, depth + 1) for item in current)


def _validate_json_tree(value: Any) -> None:
    nodes = 0

    def visit(current: Any, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > MAX_NODES or depth > MAX_DEPTH:
            raise RecoveryBundleError("recovery_target_bounds_invalid")
        if current is None or isinstance(current, (bool, int)):
            return
        if isinstance(current, float):
            if current != current or current in (float("inf"), float("-inf")):
                raise RecoveryBundleError("recovery_target_type_invalid")
            return
        if isinstance(current, str):
            if len(current) > MAX_STRING_CHARS:
                raise RecoveryBundleError("recovery_target_bounds_invalid")
            return
        if isinstance(current, Mapping):
            for key, item in current.items():
                if not isinstance(key, str) or len(key) > 256:
                    raise RecoveryBundleError("recovery_target_type_invalid")
                visit(item, depth + 1)
            return
        if isinstance(current, list):
            for item in current:
                visit(item, depth + 1)
            return
        raise RecoveryBundleError("recovery_target_type_invalid")

    visit(value, 0)


def _validate_targets(targets: Any, target_wal: int) -> Dict[str, Any]:
    if not isinstance(targets, Mapping) or set(targets) != set(TARGET_KEYS):
        raise RecoveryBundleError("recovery_target_coverage_invalid")
    for key, limit in LIST_LIMITS.items():
        value = targets.get(key)
        if not isinstance(value, list) or len(value) > limit or any(
                not isinstance(row, dict) for row in value):
            raise RecoveryBundleError("recovery_target_bounds_invalid")
    for key, limit in DICT_LIMITS.items():
        value = targets.get(key)
        if not isinstance(value, dict) or len(value) > limit:
            raise RecoveryBundleError("recovery_target_bounds_invalid")
    sequences = targets["opsSequenceByAggregate"]
    for key, value in sequences.items():
        if not isinstance(key, str) or not key or len(key) > 256 or \
                isinstance(value, bool) or not isinstance(value, int) or \
                value <= 0:
            raise RecoveryBundleError("recovery_ops_sequence_invalid")
    try:
        bounded_sequences, bounded_meta = \
            argus_remote_journal.bounded_sequence_allocator_state(
                sequences=sequences, events=targets["opsJournal"],
                meta=targets["opsJournalMeta"])
    except ValueError as exc:
        raise RecoveryBundleError("recovery_ops_sequence_invalid") from exc
    if bounded_sequences != sequences or \
            bounded_meta != targets["opsJournalMeta"]:
        raise RecoveryBundleError("recovery_ops_sequence_invalid")
    _validate_json_tree(targets)
    durability = targets["missionTickDurability"]
    applied = _strict_positive_int(
        durability.get("walAppliedSequence"), "recovery_target_wal_invalid")
    exported = _strict_positive_int(
        durability.get("remoteWalAppliedSequence"),
        "recovery_target_wal_invalid")
    verified = durability.get("verifiedWalSequence")
    if isinstance(verified, bool) or not isinstance(verified, int) or \
            verified < 0 or applied != target_wal or exported != target_wal or \
            verified > target_wal:
        raise RecoveryBundleError("recovery_target_wal_invalid")
    return copy.deepcopy(dict(targets))


def validate_nonce_authority(value: Any) -> Dict[str, Any]:
    """Validate the private carry-forward map sealed inside the ciphertext.

    Material domains and counters never appear in the public envelope or
    sidecar metadata.  Keeping the map in the fixed-size AES-GCM plaintext
    lets the latest immutable pair retain floors across key rotation without
    an unbounded Git-history walk.
    """
    if not isinstance(value, Mapping) or set(value) != {
            "schemaVersion", "keyMaterialCounters"} or value.get(
                "schemaVersion") != NONCE_AUTHORITY_SCHEMA:
        raise RecoveryBundleError("recovery_nonce_authority_invalid")
    raw = value.get("keyMaterialCounters")
    if not isinstance(raw, Mapping) or len(raw) > \
            MAX_NONCE_AUTHORITY_DOMAINS:
        raise RecoveryBundleError("recovery_nonce_authority_invalid")
    counters = {}
    for domain, counter in raw.items():
        if not isinstance(domain, str) or not HASH_RE.fullmatch(domain) or \
                isinstance(counter, bool) or not isinstance(counter, int) or \
                counter <= 0 or counter >= (1 << 96):
            raise RecoveryBundleError("recovery_nonce_authority_invalid")
        counters[domain] = counter
    return {
        "schemaVersion": NONCE_AUTHORITY_SCHEMA,
        "keyMaterialCounters": counters,
    }


def build_payload(
        *, compact_readback: Mapping[str, Any], targets: Mapping[str, Any],
        generated_at: str, build_identity: Mapping[str, Any],
        source_checkpoint_hash: str,
        checkpoint_id: str,
        checkpoint_verified_at: str,
        ledger_base_commit_sha: str,
        nonce_authority: Mapping[str, Any]) -> Dict[str, Any]:
    """Build one exact plaintext recovery projection in backend memory."""
    compact = copy.deepcopy(dict(compact_readback))
    if not argus_remote_journal.verify_strict_compact_readback_snapshot(
            compact):
        raise RecoveryBundleError("recovery_compact_readback_invalid")
    identity = _build_identity(build_identity)
    if _build_identity(compact.get("buildIdentity")) != identity:
        raise RecoveryBundleError("recovery_compact_build_mismatch")
    generated = str(generated_at or "")
    if _timestamp(generated) is None or str(
            compact.get("generatedAt") or compact.get("asOf") or "") != generated:
        raise RecoveryBundleError("recovery_timestamp_invalid")
    checkpoint_hash = str(source_checkpoint_hash or "").lower()
    if not HASH_RE.fullmatch(checkpoint_hash):
        raise RecoveryBundleError("recovery_checkpoint_hash_invalid")
    verified_at = str(checkpoint_verified_at or "")
    if _timestamp(verified_at) is None:
        raise RecoveryBundleError("recovery_checkpoint_verified_at_invalid")
    exact_checkpoint_id = str(checkpoint_id or "")
    if not CHECKPOINT_ID_RE.fullmatch(exact_checkpoint_id):
        raise RecoveryBundleError("recovery_checkpoint_id_invalid")
    base_commit = str(ledger_base_commit_sha or "").lower()
    if not SHA_RE.fullmatch(base_commit):
        raise RecoveryBundleError("recovery_ledger_base_commit_invalid")
    durability = compact.get("missionTickDurability") or {}
    target_wal = _strict_positive_int(
        durability.get("walAppliedSequence"), "recovery_target_wal_invalid")
    if durability.get("remoteWalAppliedSequence") != target_wal:
        raise RecoveryBundleError("recovery_target_wal_invalid")
    exact_targets = _validate_targets(targets, target_wal)
    if exact_targets["opsJournal"] != compact.get("opsJournal") or \
            exact_targets["outcomes"] != compact.get("outcomes") or \
            exact_targets["missionTickDurability"] != durability:
        raise RecoveryBundleError("recovery_compact_target_mismatch")
    section = argus_remote_journal.snapshot_journal_section(
        events=exact_targets["opsJournal"],
        meta=exact_targets["opsJournalMeta"],
        compacted=exact_targets["opsJournalCompacted"], now_iso=generated)
    if section["opsJournal"] != exact_targets["opsJournal"] or \
            section["integrityManifest"] != compact.get("integrityManifest"):
        raise RecoveryBundleError("recovery_journal_manifest_mismatch")
    payload = {
        "schemaVersion": PAYLOAD_SCHEMA,
        "durableSchemaVersion": argus_remote_journal.SCHEMA_V3,
        "generatedAt": generated,
        "buildIdentity": identity,
        "targetWalSequence": target_wal,
        "compactReceiptHash": compact.get("receiptHash"),
        "sourceCheckpointHash": checkpoint_hash,
        "checkpointId": exact_checkpoint_id,
        "checkpointVerifiedAt": verified_at,
        "ledgerBaseCommitSha": base_commit,
        "nonceAuthority": validate_nonce_authority(nonce_authority),
        "compactReadback": compact,
        "targets": exact_targets,
        "targetStateHash": _hash(exact_targets),
    }
    payload["payloadHash"] = _hash(payload)
    if len(_canonical(payload)) > MAX_PLAINTEXT_BYTES:
        raise RecoveryBundleError("recovery_payload_oversized")
    validate_payload(payload)
    return payload


def validate_payload(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, Mapping) or payload.get(
            "schemaVersion") != PAYLOAD_SCHEMA:
        raise RecoveryBundleError("recovery_payload_schema_invalid")
    if set(payload) != {
            "schemaVersion", "durableSchemaVersion", "generatedAt",
            "buildIdentity", "targetWalSequence", "compactReceiptHash",
            "sourceCheckpointHash", "checkpointVerifiedAt",
            "checkpointId",
            "ledgerBaseCommitSha", "nonceAuthority", "compactReadback", "targets",
            "targetStateHash", "payloadHash"}:
        raise RecoveryBundleError("recovery_payload_envelope_invalid")
    if payload.get("durableSchemaVersion") != argus_remote_journal.SCHEMA_V3:
        raise RecoveryBundleError("recovery_durable_schema_invalid")
    if len(_canonical(payload)) > MAX_PLAINTEXT_BYTES:
        raise RecoveryBundleError("recovery_payload_oversized")
    expected_hash = str(payload.get("payloadHash") or "")
    body = {key: value for key, value in payload.items()
            if key != "payloadHash"}
    if not HASH_RE.fullmatch(expected_hash) or _hash(body) != expected_hash:
        raise RecoveryBundleError("recovery_payload_hash_mismatch")
    identity = _build_identity(payload.get("buildIdentity"))
    generated = str(payload.get("generatedAt") or "")
    if _timestamp(generated) is None:
        raise RecoveryBundleError("recovery_timestamp_invalid")
    if not HASH_RE.fullmatch(str(payload.get("sourceCheckpointHash") or "")):
        raise RecoveryBundleError("recovery_checkpoint_hash_invalid")
    if not CHECKPOINT_ID_RE.fullmatch(str(payload.get("checkpointId") or "")):
        raise RecoveryBundleError("recovery_checkpoint_id_invalid")
    if _timestamp(payload.get("checkpointVerifiedAt")) is None:
        raise RecoveryBundleError("recovery_checkpoint_verified_at_invalid")
    if not SHA_RE.fullmatch(str(payload.get("ledgerBaseCommitSha") or "")):
        raise RecoveryBundleError("recovery_ledger_base_commit_invalid")
    validate_nonce_authority(payload.get("nonceAuthority"))
    target_wal = _strict_positive_int(
        payload.get("targetWalSequence"), "recovery_target_wal_invalid")
    compact = payload.get("compactReadback")
    if not isinstance(compact, Mapping) or not \
            argus_remote_journal.verify_strict_compact_readback_snapshot(
                dict(compact)):
        raise RecoveryBundleError("recovery_compact_readback_invalid")
    if _build_identity(compact.get("buildIdentity")) != identity or \
            str(compact.get("generatedAt") or compact.get("asOf") or "") != \
            generated or compact.get("receiptHash") != \
            payload.get("compactReceiptHash"):
        raise RecoveryBundleError("recovery_compact_binding_mismatch")
    if (compact.get("missionTickDurability") or {}).get(
            "walAppliedSequence") != target_wal:
        raise RecoveryBundleError("recovery_target_wal_invalid")
    targets = _validate_targets(payload.get("targets"), target_wal)
    if not HASH_RE.fullmatch(str(payload.get("targetStateHash") or "")) or \
            _hash(targets) != payload.get("targetStateHash"):
        raise RecoveryBundleError("recovery_target_state_hash_mismatch")
    if targets["opsJournal"] != compact.get("opsJournal") or \
            targets["outcomes"] != compact.get("outcomes") or \
            targets["missionTickDurability"] != compact.get(
                "missionTickDurability"):
        raise RecoveryBundleError("recovery_compact_target_mismatch")
    section = argus_remote_journal.snapshot_journal_section(
        events=targets["opsJournal"], meta=targets["opsJournalMeta"],
        compacted=targets["opsJournalCompacted"], now_iso=generated)
    if section["opsJournal"] != targets["opsJournal"] or \
            section["integrityManifest"] != compact.get("integrityManifest"):
        raise RecoveryBundleError("recovery_journal_manifest_mismatch")
    return copy.deepcopy(dict(payload))


def _public_header(
        payload: Mapping[str, Any], *, key_identifier: str,
        generation_id: str, key_derivation_salt: bytes) -> Dict[str, Any]:
    identifier = validate_key_id(key_identifier)
    generation = str(generation_id or "")
    if not GENERATION_ID_RE.fullmatch(generation):
        raise RecoveryBundleError("recovery_generation_id_invalid")
    if not isinstance(key_derivation_salt, bytes) or len(
            key_derivation_salt) != KEY_DERIVATION_SALT_BYTES:
        raise RecoveryBundleError("recovery_key_derivation_salt_invalid")
    return {
        "schemaVersion": SCHEMA,
        "algorithm": ALGORITHM,
        "keyDerivation": KEY_DERIVATION,
        "keyDerivationSalt": _b64_encode(key_derivation_salt),
        "keyId": identifier,
        "generationId": generation,
        "generatedAt": payload["generatedAt"],
        "buildIdentity": copy.deepcopy(payload["buildIdentity"]),
        "targetWalSequence": payload["targetWalSequence"],
        "compactReceiptHash": payload["compactReceiptHash"],
        "checkpointVerifiedAt": payload["checkpointVerifiedAt"],
        "checkpointId": payload["checkpointId"],
        "ledgerBaseCommitSha": payload["ledgerBaseCommitSha"],
    }


def _aad(header: Mapping[str, Any]) -> bytes:
    return AAD_DOMAIN.encode("ascii") + b"\x00" + _canonical(header)


def _hkdf_info(header: Mapping[str, Any]) -> bytes:
    """Bind a data key to the canonical public semantic header."""
    return HKDF_INFO_DOMAIN + b"\x00" + _canonical(dict(header))


def _derive_data_key(root_key: bytes, header: Mapping[str, Any]) -> bytes:
    """Derive one envelope-scoped AES-256 key without exposing key material."""
    if not isinstance(root_key, bytes) or len(root_key) != 32:
        raise RecoveryBundleError("recovery_key_invalid")
    if header.get("schemaVersion") != SCHEMA or \
            header.get("algorithm") != ALGORITHM or \
            header.get("keyDerivation") != KEY_DERIVATION:
        raise RecoveryBundleError("recovery_key_derivation_invalid")
    validate_key_id(header.get("keyId"))
    if not CHECKPOINT_ID_RE.fullmatch(str(header.get("checkpointId") or "")):
        raise RecoveryBundleError("recovery_checkpoint_id_invalid")
    salt = _decode_key_derivation_salt(header.get("keyDerivationSalt"))
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=salt,
        info=_hkdf_info(header)).derive(root_key)


def _padded_plaintext(payload: Mapping[str, Any]) -> bytes:
    encoded = _canonical(payload)
    if len(encoded) > MAX_PLAINTEXT_BYTES:
        raise RecoveryBundleError("recovery_payload_oversized")
    prefix = len(encoded).to_bytes(4, "big")
    used = len(prefix) + len(encoded)
    padded = PADDED_PLAINTEXT_BYTES
    if used > padded:
        raise RecoveryBundleError("recovery_payload_oversized")
    return prefix + encoded + (b"\x00" * (padded - used))


def _unpadded_plaintext(value: bytes) -> bytes:
    if len(value) != PADDED_PLAINTEXT_BYTES:
        raise RecoveryBundleError("recovery_padding_invalid")
    length = int.from_bytes(value[:4], "big")
    if length <= 0 or length > MAX_PLAINTEXT_BYTES or 4 + length > len(value):
        raise RecoveryBundleError("recovery_padding_invalid")
    if any(value[4 + length:]):
        raise RecoveryBundleError("recovery_padding_invalid")
    return value[4:4 + length]


def _validate_nonce_authority_binding(
        payload: Mapping[str, Any], key: bytes, nonce: bytes) -> None:
    authority = validate_nonce_authority(payload.get("nonceAuthority"))
    domain = nonce_material_domain(key)
    counter = int.from_bytes(nonce, "big")
    if len(nonce) != 12 or counter <= 0 or authority[
            "keyMaterialCounters"].get(domain, 0) < counter:
        raise RecoveryBundleError("recovery_nonce_authority_binding_invalid")


def encrypt_payload(
        payload: Mapping[str, Any], key: bytes, *, key_identifier: str,
        nonce: bytes,
        generation_id: Optional[str] = None) -> Dict[str, Any]:
    """Encrypt with an envelope-scoped data key and a reserved nonce.

    Nonce generation is intentionally not available as a convenience fallback:
    production callers must reserve the value in the persistent, interprocess
    nonce ledger before any AES-GCM operation can occur.  The configured key is
    a root key only: a fresh 256-bit CSPRNG salt derives a distinct AES-256 key
    for every invocation, including after rollback of unpublished local state.
    """
    if not isinstance(nonce, bytes) or len(nonce) != 12:
        raise RecoveryBundleError("recovery_nonce_invalid")
    if not isinstance(key, bytes) or len(key) != 32:
        raise RecoveryBundleError("recovery_key_invalid")
    verified = validate_payload(payload)
    _validate_nonce_authority_binding(verified, key, nonce)
    generation = generation_id or f"rrg-{os.urandom(16).hex()}"
    salt = secrets.token_bytes(KEY_DERIVATION_SALT_BYTES)
    if not isinstance(salt, bytes) or len(salt) != \
            KEY_DERIVATION_SALT_BYTES:
        raise RecoveryBundleError("recovery_key_derivation_salt_invalid")
    header = _public_header(
        verified, key_identifier=key_identifier, generation_id=generation,
        key_derivation_salt=salt)
    data_key = _derive_data_key(key, header)
    ciphertext = AESGCM(data_key).encrypt(
        nonce, _padded_plaintext(verified), _aad(header))
    envelope = {
        **header,
        "nonce": _b64_encode(nonce),
        "ciphertext": _b64_encode(ciphertext),
        "ciphertextSha256": hashlib.sha256(ciphertext).hexdigest(),
    }
    envelope["bundleHash"] = _hash(envelope)
    if len(_canonical(envelope)) > MAX_ENCODED_BYTES:
        raise RecoveryBundleError("recovery_envelope_oversized")
    validate_envelope(envelope)
    return envelope


def validate_envelope(envelope: Any) -> Dict[str, Any]:
    if not isinstance(envelope, Mapping) or envelope.get(
            "schemaVersion") != SCHEMA:
        raise RecoveryBundleError("recovery_schema_invalid")
    if set(envelope) != {
            "schemaVersion", "algorithm", "generatedAt", "buildIdentity",
            "targetWalSequence", "compactReceiptHash", "checkpointVerifiedAt",
            "checkpointId", "ledgerBaseCommitSha", "keyId", "generationId",
            "keyDerivation", "keyDerivationSalt", "nonce", "ciphertext",
            "ciphertextSha256", "bundleHash"}:
        raise RecoveryBundleError("recovery_envelope_invalid")
    _validate_outer_json_tree(envelope)
    if envelope.get("algorithm") != ALGORITHM or \
            envelope.get("keyDerivation") != KEY_DERIVATION or \
            _timestamp(envelope.get("generatedAt")) is None:
        raise RecoveryBundleError("recovery_envelope_invalid")
    _build_identity(envelope.get("buildIdentity"))
    if _timestamp(envelope.get("checkpointVerifiedAt")) is None or not \
            GENERATION_ID_RE.fullmatch(str(envelope.get("generationId") or "")):
        raise RecoveryBundleError("recovery_envelope_invalid")
    if not CHECKPOINT_ID_RE.fullmatch(str(envelope.get("checkpointId") or "")):
        raise RecoveryBundleError("recovery_checkpoint_id_invalid")
    validate_key_id(envelope.get("keyId"))
    _strict_positive_int(
        envelope.get("targetWalSequence"), "recovery_target_wal_invalid")
    if not SHA_RE.fullmatch(str(envelope.get("ledgerBaseCommitSha") or "")):
        raise RecoveryBundleError("recovery_ledger_base_commit_invalid")
    if not re.fullmatch(
            r"[0-9a-f]{16}", str(envelope.get("compactReceiptHash") or "")):
        raise RecoveryBundleError("recovery_envelope_invalid")
    # Bound base64 text before allocating decoded ciphertext.
    if len(str(envelope.get("keyDerivationSalt") or "")) > 64 or len(str(
            envelope.get("nonce") or "")) > 32 or len(str(
            envelope.get("ciphertext") or "")) > \
            ((MAX_ENCODED_BYTES * 4) // 3 + 8) or \
            len(_canonical(envelope)) > MAX_ENCODED_BYTES:
        raise RecoveryBundleError("recovery_envelope_oversized")
    _decode_key_derivation_salt(envelope.get("keyDerivationSalt"))
    nonce = _b64_decode(envelope.get("nonce"), "recovery_nonce_invalid")
    ciphertext = _b64_decode(
        envelope.get("ciphertext"), "recovery_ciphertext_invalid")
    if len(nonce) != 12 or len(ciphertext) < 17:
        raise RecoveryBundleError("recovery_envelope_oversized")
    digest = str(envelope.get("ciphertextSha256") or "")
    if not HASH_RE.fullmatch(digest) or \
            hashlib.sha256(ciphertext).hexdigest() != digest:
        raise RecoveryBundleError("recovery_ciphertext_hash_mismatch")
    bundle_hash = str(envelope.get("bundleHash") or "")
    if not HASH_RE.fullmatch(bundle_hash) or _hash({
            key_name: value for key_name, value in envelope.items()
            if key_name != "bundleHash"}) != bundle_hash:
        raise RecoveryBundleError("recovery_bundle_hash_mismatch")
    return copy.deepcopy(dict(envelope))


def decrypt_envelope(
        envelope: Mapping[str, Any], key: bytes, *,
        key_identifier: str) -> Dict[str, Any]:
    verified = validate_envelope(envelope)
    if not isinstance(key, bytes) or len(key) != 32:
        raise RecoveryBundleError("recovery_key_invalid")
    if verified["keyId"] != validate_key_id(key_identifier):
        raise RecoveryBundleError("recovery_key_id_mismatch")
    header = {key_name: verified[key_name] for key_name in (
        "schemaVersion", "algorithm", "keyDerivation",
        "keyDerivationSalt", "generatedAt", "buildIdentity",
        "targetWalSequence", "compactReceiptHash", "checkpointVerifiedAt",
        "checkpointId", "ledgerBaseCommitSha", "keyId", "generationId")}
    nonce = _b64_decode(verified["nonce"], "recovery_nonce_invalid")
    ciphertext = _b64_decode(
        verified["ciphertext"], "recovery_ciphertext_invalid")
    try:
        data_key = _derive_data_key(key, header)
        plaintext = AESGCM(data_key).decrypt(
            nonce, ciphertext, _aad(header))
    except InvalidTag as exc:
        raise RecoveryBundleError("recovery_authentication_failed") from exc
    try:
        payload = json.loads(_unpadded_plaintext(plaintext).decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise RecoveryBundleError("recovery_payload_unreadable") from exc
    payload = validate_payload(payload)
    _validate_nonce_authority_binding(payload, key, nonce)
    if _public_header(
            payload, key_identifier=key_identifier,
            generation_id=verified["generationId"],
            key_derivation_salt=_decode_key_derivation_salt(
                verified["keyDerivationSalt"])) != header:
        raise RecoveryBundleError("recovery_envelope_binding_mismatch")
    return payload


def validate_pair(
        readback: Any, envelope: Any, key: bytes, *,
        key_identifier: str) -> Dict[str, Any]:
    if not isinstance(readback, Mapping) or not \
            argus_remote_journal.verify_strict_compact_readback_snapshot(
                dict(readback)):
        raise RecoveryBundleError("recovery_pair_readback_invalid")
    payload = decrypt_envelope(
        envelope, key, key_identifier=key_identifier)
    if payload["compactReadback"] != dict(readback) or \
            payload["compactReceiptHash"] != readback.get("receiptHash"):
        raise RecoveryBundleError("recovery_pair_mismatch")
    return payload


def build_sidecar(
        readback: Mapping[str, Any], envelope: Mapping[str, Any]) -> Dict[str, Any]:
    """Bind the public compact proof and encrypted recovery as one fsynced file."""
    compact = copy.deepcopy(dict(readback))
    verified = validate_envelope(envelope)
    if not argus_remote_journal.verify_strict_compact_readback_snapshot(
            compact):
        raise RecoveryBundleError("recovery_pair_readback_invalid")
    if len(_canonical(compact)) > MAX_READBACK_BYTES:
        raise RecoveryBundleError("recovery_readback_oversized")
    if verified["compactReceiptHash"] != compact.get("receiptHash") or \
            verified["targetWalSequence"] != (
                compact.get("missionTickDurability") or {}).get(
                    "walAppliedSequence") or \
            verified["generatedAt"] != compact.get("generatedAt") or \
            verified["buildIdentity"] != compact.get("buildIdentity"):
        raise RecoveryBundleError("recovery_pair_mismatch")
    sidecar = {
        "schemaVersion": SIDECAR_SCHEMA,
        "readback": compact,
        "recovery": verified,
    }
    if len(_canonical(sidecar)) > MAX_SIDECAR_BYTES:
        raise RecoveryBundleError("recovery_sidecar_oversized")
    return sidecar


def validate_sidecar(sidecar: Any) -> Dict[str, Any]:
    if not isinstance(sidecar, Mapping) or set(sidecar) != {
            "schemaVersion", "readback", "recovery"} or \
            sidecar.get("schemaVersion") != SIDECAR_SCHEMA:
        raise RecoveryBundleError("recovery_sidecar_schema_invalid")
    _validate_outer_json_tree(sidecar)
    if len(_canonical(sidecar)) > MAX_SIDECAR_BYTES:
        raise RecoveryBundleError("recovery_sidecar_oversized")
    return build_sidecar(sidecar.get("readback"), sidecar.get("recovery"))


def verify_sidecar(sidecar: Any) -> bool:
    try:
        validate_sidecar(sidecar)
        return True
    except RecoveryBundleError:
        return False


def configured_keys(environ: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """Return current/previous key material with deterministic safe status."""
    env = os.environ if environ is None else environ
    current_id = str(env.get("ARGUS_REMOTE_RECOVERY_CURRENT_KEY_ID") or "")
    current_raw = str(env.get("ARGUS_REMOTE_RECOVERY_CURRENT_KEY") or "")
    previous_id = str(env.get("ARGUS_REMOTE_RECOVERY_PREVIOUS_KEY_ID") or "")
    previous_raw = str(env.get("ARGUS_REMOTE_RECOVERY_PREVIOUS_KEY") or "")
    if not current_id and not current_raw and not previous_id and not previous_raw:
        return {"status": "not_configured", "current": None, "previous": None}
    if not current_id or not current_raw or bool(previous_id) != bool(previous_raw):
        raise RecoveryBundleError("recovery_key_config_invalid")
    current = {"keyId": validate_key_id(current_id),
               "key": decode_key(current_raw)}
    previous = None
    if previous_id:
        previous = {"keyId": validate_key_id(previous_id),
                    "key": decode_key(previous_raw)}
        if previous["keyId"] == current["keyId"]:
            raise RecoveryBundleError("recovery_key_id_duplicate")
        # A key-ID-only rename is represented for one rotation window by the
        # same 32-byte material in current and previous under distinct IDs.
        # Nonce authority is material-domain keyed, so this cannot fork the
        # counter; encryption still uses current while previous is decrypt-only.
    return {"status": "configured", "current": current,
            "previous": previous}


def decrypt_configured(
        envelope: Mapping[str, Any], keys: Mapping[str, Any]) -> Dict[str, Any]:
    """Select exactly the configured key ID; never probe unrelated keys."""
    verified = validate_envelope(envelope)
    identifier = verified["keyId"]
    for slot in ("current", "previous"):
        selected = keys.get(slot) if isinstance(keys, Mapping) else None
        if isinstance(selected, Mapping) and selected.get("keyId") == identifier:
            return decrypt_envelope(
                verified, selected.get("key"), key_identifier=identifier)
    raise RecoveryBundleError("recovery_key_id_unavailable")


def verify_bundle(
        envelope: Any, key: Optional[bytes] = None, *,
        key_identifier: Optional[str] = None) -> bool:
    try:
        validate_envelope(envelope)
        if key is not None:
            decrypt_envelope(
                envelope, key, key_identifier=str(key_identifier or ""))
        return True
    except RecoveryBundleError:
        return False


def overlay_verified_bundle(
        full_blob: Mapping[str, Any], envelope: Mapping[str, Any], key: bytes,
        *, key_identifier: str,
        ledger_commit_sha: Optional[str] = None) -> Dict[str, Any]:
    """Decrypt and overlay every WAL-mutated target onto a verified full base."""
    if not isinstance(full_blob, Mapping) or \
            full_blob.get("schemaVersion") != argus_remote_journal.SCHEMA_V3 or \
            argus_remote_journal.parse_remote_snapshot(dict(full_blob)).get(
                "status") != "ok":
        raise RecoveryBundleError("recovery_full_snapshot_invalid")
    payload = decrypt_envelope(
        envelope, key, key_identifier=key_identifier)
    full_time = _timestamp(full_blob.get("generatedAt") or full_blob.get("asOf"))
    payload_time = _timestamp(payload["generatedAt"])
    if full_time is None or payload_time is None or payload_time < full_time:
        raise RecoveryBundleError("recovery_timestamp_regressed")
    full_durability = full_blob.get("missionTickDurability")
    if not isinstance(full_durability, Mapping):
        raise RecoveryBundleError("recovery_full_wal_invalid")
    full_wal = full_durability.get("walAppliedSequence")
    if isinstance(full_wal, bool) or not isinstance(full_wal, int) or \
            full_wal < 0 or full_wal > payload["targetWalSequence"]:
        raise RecoveryBundleError("recovery_target_behind_full")
    if ledger_commit_sha is not None and not SHA_RE.fullmatch(
            str(ledger_commit_sha).lower()):
        raise RecoveryBundleError("recovery_ledger_commit_invalid")
    merged = copy.deepcopy(dict(full_blob))
    for target in TARGET_KEYS:
        if target == "opsSequenceByAggregate":
            continue
        merged[target] = copy.deepcopy(payload["targets"][target])
    merged["opsSequenceByAggregate"] = copy.deepcopy(
        payload["targets"]["opsSequenceByAggregate"])
    merged["integrityManifest"] = copy.deepcopy(
        payload["compactReadback"]["integrityManifest"])
    merged["generatedAt"] = payload["generatedAt"]
    merged["asOf"] = payload["generatedAt"]
    merged["remoteRecoveryProvenance"] = {
        "schemaVersion": SCHEMA,
        "buildIdentity": copy.deepcopy(payload["buildIdentity"]),
        "targetWalSequence": payload["targetWalSequence"],
        "compactReceiptHash": payload["compactReceiptHash"],
        "payloadHash": payload["payloadHash"],
        "sourceCheckpointHash": payload["sourceCheckpointHash"],
        "checkpointVerifiedAt": payload["checkpointVerifiedAt"],
        "targetStateHash": payload["targetStateHash"],
        "bundleHash": validate_envelope(envelope)["bundleHash"],
        "ledgerCommitSha": (str(ledger_commit_sha).lower()
                            if ledger_commit_sha is not None else None),
        "baseGeneratedAt": full_blob.get("generatedAt") or full_blob.get("asOf"),
        "baseWalSequence": full_wal,
    }
    return merged
