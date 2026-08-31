"""Focused acceptance for authenticated cold/new-disk recovery restore."""
from __future__ import annotations

import base64
import contextlib
import copy
import json
import os
import pathlib
import tempfile
import types
from unittest import mock

import pytest

import argus_persistent_storage as storage
import argus_remote_journal as journal
import argus_remote_recovery as recovery
import argus_tick_durability as tick_durability


_moomoo = types.ModuleType("moomoo")
_moomoo.OpenQuoteContext = lambda *args, **kwargs: None
_moomoo.OpenSecTradeContext = lambda *args, **kwargs: None
_moomoo.RET_OK = 0
import sys
sys.modules.setdefault("moomoo", _moomoo)
import scanner
from test_argus_persistent_mission_storage import (
    FakeResponse, remote_snapshot, scanner_storage,
)


PINNED_SHA = "d" * 40
BASE_SHA = "b" * 40
FULL_AT = "2026-08-11T20:37:25Z"
RECOVERY_AT = "2026-08-11T21:07:09Z"
FULL_WAL = 4659
RECOVERY_WAL = 4694
BUILD = {"appVersion": "13.4.13", "buildSha": "e" * 40}
CURRENT_ID = "recovery-current-v1"
PREVIOUS_ID = "recovery-previous-v1"
CURRENT_KEY = b"\x11" * 32
PREVIOUS_KEY = b"\x22" * 32
CHECKPOINT_ID = "rcp-" + "5" * 32
PRODUCTION_LEDGER_SHA = "f5f17fcd54e9713f5613ea9fa09b4f230f5662f5"
PRODUCTION_CHECKPOINT_COMMIT_SHA = \
    "abd478a4c32f19c3a10a41b34481fe31b493e841"
PRODUCTION_COMMIT_RESPONSE_BYTES = 86_817
PRODUCTION_LOCAL_WAL = 8968
PRODUCTION_REMOTE_WAL = 8953


def _encoded_key(value):
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _key_env(*, current=CURRENT_KEY, previous=None):
    value = {
        "ARGUS_REMOTE_RECOVERY_CURRENT_KEY_ID": CURRENT_ID,
        "ARGUS_REMOTE_RECOVERY_CURRENT_KEY": _encoded_key(current),
        "RENDER_GIT_COMMIT": BUILD["buildSha"],
    }
    if previous is not None:
        value.update({
            "ARGUS_REMOTE_RECOVERY_PREVIOUS_KEY_ID": PREVIOUS_ID,
            "ARGUS_REMOTE_RECOVERY_PREVIOUS_KEY": _encoded_key(previous),
        })
    return value


def _event(sequence):
    body = {
        "eventId": f"event-{sequence}", "eventType": "mission_completed",
        "aggregateType": "mission", "aggregateId": f"mw-{sequence}",
        "sequence": sequence, "occurredAt": RECOVERY_AT,
        "idempotencyKey": f"mission:mw-{sequence}:completed",
        "privacyClassification": "public_safe",
        "payload": {"missionType": "ordinary"},
    }
    body["integrityHash"] = journal._h(body)
    return body


def _full(wal=FULL_WAL):
    value = remote_snapshot(wal)
    value.update({
        "generatedAt": FULL_AT, "asOf": FULL_AT,
        "buildIdentity": {
            "appVersion": "13.4.12", "buildSha": "f" * 40},
        "missions": [], "missionWindows": [], "forecasts": [],
        "outcomes": [], "incidents": [], "postmortems": [],
        "periodicReports": [], "challengerRuns": [], "agentQueue": {},
        "opsSequenceByAggregate": {},
        "marketLedgerStateHash": "a" * 16,
        "chartIntelligenceStateHash": "b" * 16,
        "todayIntelligenceStateHash": "c" * 16,
        "marketReplayStateHash": "d" * 16,
    })
    return value


def _artifacts(*, key=CURRENT_KEY, key_id=CURRENT_ID, mission_count=300,
               target_wal=RECOVERY_WAL, nonce=b"\xc1" * 12,
               generation_digit="c"):
    events = [_event(target_wal)]
    meta = {
        "totalObserved": 1,
        journal.OPS_SEQUENCE_HIGH_WATER_FIELD: target_wal,
    }
    section = journal.snapshot_journal_section(
        events=events, meta=meta, compacted=[],
        now_iso=RECOVERY_AT)
    durability = {
        "schemaVersion": "argus-mission-batch-v1", "cursor": 300,
        "remainingCount": 0, "lastJobId": f"job-{target_wal}",
        "lastResult": "completed", "lastCompletedAt": RECOVERY_AT,
        "walAppliedSequence": target_wal,
        "remoteWalAppliedSequence": target_wal,
        "verifiedWalSequence": FULL_WAL,
        "compactReceiptHash": None,
    }
    outcome = {"id": f"outcome-{target_wal}", "status": "resolved"}
    outcome["integrityHash"] = journal._h(outcome)
    compact = journal.build_compact_readback_snapshot(
        schema_version=journal.SCHEMA_V3, generated_at=RECOVERY_AT,
        as_of=RECOVERY_AT, build_identity=BUILD, ops_journal=events,
        integrity_manifest=section["integrityManifest"], outcomes=[outcome],
        mission_tick_durability=durability,
        market_ledger_state_hash="1" * 16,
        chart_intelligence_state_hash="2" * 16,
        today_intelligence_state_hash="3" * 16,
        market_replay_state_hash="4" * 16)
    targets = {
        "opsJournal": events, "opsJournalMeta": copy.deepcopy(meta),
        "opsJournalCompacted": [],
        "opsSequenceByAggregate": {
            f"mission:mw-{target_wal}": target_wal},
        "missions": [{"missionId": f"mission-{index}"}
                     for index in range(mission_count)],
        "missionWindows": [{"missionWindowId": f"mw-{target_wal}"}],
        "forecasts": [{"id": f"forecast-{target_wal}"}],
        "outcomes": compact["outcomes"], "incidents": [], "soak": {},
        "postmortems": [{"missionWindowId": f"mw-{target_wal}"}],
        "periodicReports": [{"reportId": f"report-{target_wal}"}],
        "challengerRuns": [{"runId": f"challenger-{target_wal}"}],
        "agentQueue": {"TEST": {"mode": "deep"}},
        "missionTickDurability": durability,
    }
    payload = recovery.build_payload(
        compact_readback=compact, targets=targets,
        generated_at=RECOVERY_AT, build_identity=BUILD,
        checkpoint_id=CHECKPOINT_ID,
        source_checkpoint_hash="a" * 64,
        checkpoint_verified_at=RECOVERY_AT,
        ledger_base_commit_sha=BASE_SHA,
        nonce_authority={
            "schemaVersion": recovery.NONCE_AUTHORITY_SCHEMA,
            "keyMaterialCounters": {
                recovery.nonce_material_domain(key):
                    int.from_bytes(b"\xc1" * 12, "big"),
            },
        })
    envelope = recovery.encrypt_payload(
        payload, key, key_identifier=key_id,
        nonce=nonce,
        generation_id="rrg-" + generation_digit * 32)
    return compact, envelope, targets


def _commit_metadata(sha, parents):
    return FakeResponse(200, {
        "sha": sha, "parents": [{"sha": parent} for parent in parents]})


def _commit_api_url(owner, repository, sha):
    return f"https://api.github.com/repos/{owner}/{repository}/commits/{sha}"


def _linear_compare_value(base, head, distance, *, owner="mitsugue",
                          repository="argus"):
    assert isinstance(distance, int) and distance >= 0
    request_url = (
        f"https://api.github.com/repos/{owner}/{repository}/compare/"
        f"{base}...{head}")
    base_value = {
        "sha": base, "url": _commit_api_url(owner, repository, base)}
    if distance == 0:
        assert head == base
        commits = []
        status = "identical"
    else:
        middle = [f"{index:040x}" for index in range(1, distance)]
        shas = [*middle, head]
        commits = []
        parent = base
        for sha in shas:
            commits.append({
                "sha": sha,
                "url": _commit_api_url(owner, repository, sha),
                "parents": [{
                    "sha": parent,
                    "url": _commit_api_url(owner, repository, parent),
                }],
            })
            parent = sha
        status = "ahead"
    return {
        "url": request_url,
        "status": status,
        "ahead_by": distance,
        "behind_by": 0,
        "total_commits": distance,
        "base_commit": copy.deepcopy(base_value),
        "merge_base_commit": copy.deepcopy(base_value),
        "commits": commits,
        "files": [],
    }


def _linear_compare_response(base, head, distance, *, owner="mitsugue",
                             repository="argus"):
    return FakeResponse(200, _linear_compare_value(
        base, head, distance, owner=owner, repository=repository))


def _linear_commit_responses(base, head, distance, *, limit=8):
    assert distance >= 1
    shas = [base, *[f"{index:040x}" for index in range(1, distance)], head]
    return [
        _commit_metadata(shas[index], [shas[index - 1]])
        for index in range(len(shas) - 1, 0, -1)
    ][:limit]


def _ref_value(sha=PINNED_SHA, *, ref="ledger", owner="mitsugue",
               repository="argus"):
    return {
        "ref": f"refs/heads/{ref}",
        "node_id": "synthetic-node-id",
        "url": (f"https://api.github.com/repos/{owner}/{repository}/git/refs/"
                f"heads/{ref}"),
        "object": {
            "type": "commit",
            "sha": sha,
            "url": (f"https://api.github.com/repos/{owner}/{repository}/git/"
                    f"commits/{sha}"),
        },
    }


def _ref_response(sha=PINNED_SHA, *, ref="ledger", owner="mitsugue",
                  repository="argus"):
    return FakeResponse(200, _ref_value(
        sha, ref=ref, owner=owner, repository=repository))


def _sized_ref_response(size):
    value = _ref_value()
    value["node_id"] = ""
    base = json.dumps(value).encode("utf-8")
    assert len(base) <= size
    value["node_id"] = "x" * (size - len(base))
    response = FakeResponse(200, value)
    assert len(response._encoded) == size
    return response


def _responses(full, readback, recovery_object, *, ancestry=True):
    sidecar = (recovery_object if isinstance(recovery_object, dict) and
               recovery_object.get("schemaVersion") == recovery.SIDECAR_SCHEMA
               else recovery.build_sidecar(readback, recovery_object))
    values = [_ref_response(),
              FakeResponse(200, full), FakeResponse(200, readback),
              FakeResponse(200, sidecar)]
    if ancestry:
        values.extend([
            _commit_metadata(PINNED_SHA, [BASE_SHA]),
            _commit_metadata(BASE_SHA, []),
        ])
    return values


def _required_checkpoint(checkpoint, key_id=CURRENT_ID,
                         checkpoint_id=CHECKPOINT_ID):
    value = copy.deepcopy(checkpoint)
    value["remoteRecoveryRequired"] = {
        "schemaVersion": recovery.SIDECAR_SCHEMA,
        "mode": "encrypted_required",
        "keyId": key_id,
        "checkpointId": checkpoint_id,
    }
    return value


def _verified_legacy_checkpoint(readback, targets):
    value = _full()
    value.update(copy.deepcopy(targets))
    manifest_hash = readback["integrityManifest"]["manifestHash"]
    value["remoteJournalCycle"] = {
        "remoteCommitSha": BASE_SHA,
        "receiptCommitSha": BASE_SHA,
        "committedAt": RECOVERY_AT,
        "readBackAt": RECOVERY_AT,
        "readBackVerified": True,
        "walReadBackVerified": True,
        "expectedHash": manifest_hash,
        "actualHash": manifest_hash,
        "remoteWalAppliedSequence": RECOVERY_WAL,
        "verifiedWalSequence": RECOVERY_WAL,
        "compactReceiptHash": readback["receiptHash"],
        "remoteDurabilityState": "verified",
        "receiptErrorClass": None,
        "errorClass": None,
        "walErrorClass": None,
    }
    return value


def _unverified_first_activation_checkpoint(
        remote_readback, local_targets, *, local_wal=PRODUCTION_LOCAL_WAL,
        remote_wal=PRODUCTION_REMOTE_WAL):
    """Production-shaped sealed-local authority with one stale legacy cycle."""
    value = _full(local_wal)
    value.update(copy.deepcopy(local_targets))
    durability = value["missionTickDurability"]
    durability["walAppliedSequence"] = local_wal
    durability["remoteWalAppliedSequence"] = remote_wal
    durability["verifiedWalSequence"] = max(1, remote_wal - 199)
    manifest_hash = remote_readback["integrityManifest"]["manifestHash"]
    value["remoteJournalCycle"] = {
        "remoteCommitSha": BASE_SHA,
        "receiptCommitSha": BASE_SHA,
        "committedAt": RECOVERY_AT,
        "readBackAt": RECOVERY_AT,
        "readBackVerified": False,
        "walReadBackVerified": False,
        "expectedHash": manifest_hash,
        "actualHash": manifest_hash,
        "remoteWalAppliedSequence": 0,
        "verifiedWalSequence": 0,
        "compactReceiptHash": None,
        "remoteDurabilityState": "verification_pending",
        "receiptErrorClass": "hash_mismatch",
        "errorClass": "hash_mismatch",
        "walErrorClass": None,
    }
    return value


def _pinned_legacy_ledger(commit_sha=PINNED_SHA):
    return {
        "base": ("https://raw.githubusercontent.com/mitsugue/argus/" +
                 commit_sha + "/ledger"),
        "commitSha": commit_sha,
        "owner": "mitsugue",
        "repository": "argus",
        "pathPrefix": "ledger",
    }


def _sealed_local_pair(*, key, key_id, readback, envelope, targets,
                       generation_digit):
    checkpoint = _full()
    checkpoint.update(copy.deepcopy(targets))
    checkpoint["missionTickDurability"]["remoteWalAppliedSequence"] = FULL_WAL
    manifest_hash = readback["integrityManifest"]["manifestHash"]
    checkpoint["remoteJournalCycle"] = {
        "remoteCommitSha": BASE_SHA, "receiptCommitSha": BASE_SHA,
        "readBackVerified": True, "walReadBackVerified": True,
        "remoteDurabilityState": "verified",
        "expectedHash": manifest_hash, "actualHash": manifest_hash,
        "compactReceiptHash": readback["receiptHash"],
        "remoteWalAppliedSequence": envelope["targetWalSequence"],
        "verifiedWalSequence": envelope["targetWalSequence"],
        "errorClass": None, "walErrorClass": None,
        "receiptErrorClass": None,
    }
    checkpoint = _required_checkpoint(checkpoint, key_id)
    sealed = storage.seal_checkpoint(checkpoint)
    payload = recovery.decrypt_envelope(
        envelope, key, key_identifier=key_id)
    payload["sourceCheckpointHash"] = storage._canonical_sha256(sealed)
    payload["payloadHash"] = recovery._hash({
        name: value for name, value in payload.items()
        if name != "payloadHash"})
    local_envelope = recovery.encrypt_payload(
        payload, key, key_identifier=key_id,
        nonce=bytes.fromhex(generation_digit * 24),
        generation_id="rrg-" + generation_digit * 32)
    return sealed, recovery.build_sidecar(readback, local_envelope)


def _urls(request_get):
    return [call.args[0] for call in request_get.call_args_list]


def test_compact_git_ref_resolves_exact_production_ledger_without_commit_body():
    oversized_commit = {
        "sha": PRODUCTION_LEDGER_SHA,
        "files": [{"filename": "ledger/osint/memory.json", "patch": ""}],
    }
    encoded = json.dumps(oversized_commit).encode("utf-8")
    oversized_commit["files"][0]["patch"] = \
        "x" * (PRODUCTION_COMMIT_RESPONSE_BYTES - len(encoded))
    old_response = FakeResponse(200, oversized_commit)
    assert len(old_response._encoded) == PRODUCTION_COMMIT_RESPONSE_BYTES
    assert len(old_response._encoded) > scanner._LEDGER_REF_RESPONSE_MAX_BYTES

    with mock.patch.object(
            scanner.requests, "get",
            return_value=_ref_response(PRODUCTION_LEDGER_SHA)) as request_get:
        pinned = scanner._pinned_ledger_restore_base()

    assert pinned == {
        "base": ("https://raw.githubusercontent.com/mitsugue/argus/" +
                 PRODUCTION_LEDGER_SHA + "/ledger"),
        "commitSha": PRODUCTION_LEDGER_SHA,
        "owner": "mitsugue",
        "repository": "argus",
        "pathPrefix": "ledger",
    }
    request_get.assert_called_once_with(
        "https://api.github.com/repos/mitsugue/argus/git/ref/heads/ledger",
        timeout=(6, 15), stream=True, allow_redirects=False,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })


def test_compact_git_ref_response_exactly_at_bound_is_accepted():
    with mock.patch.object(
            scanner.requests, "get",
            return_value=_sized_ref_response(
                scanner._LEDGER_REF_RESPONSE_MAX_BYTES)):
        pinned = scanner._pinned_ledger_restore_base()
    assert pinned["commitSha"] == PINNED_SHA


@pytest.mark.parametrize(("response", "classification"), (
    (_sized_ref_response(scanner._LEDGER_REF_RESPONSE_MAX_BYTES + 1),
     "ledger_ref_resolution_unreadable"),
    (FakeResponse(200, {"ref": "refs/heads/not-ledger"}),
     "ledger_ref_resolution_invalid"),
    (FakeResponse(200, {"ref": "refs/heads/ledger"}),
     "ledger_ref_resolution_invalid"),
    (_ref_response(ref="not-ledger"), "ledger_ref_resolution_invalid"),
    (FakeResponse(200, {
        **_ref_value(), "object": {
            **_ref_value()["object"], "type": "tag"}}),
     "ledger_ref_resolution_invalid"),
    (FakeResponse(200, {
        **_ref_value(), "object": {
            **_ref_value()["object"], "sha": "not-a-sha"}}),
     "ledger_ref_resolution_invalid"),
    (FakeResponse(200, {
        **_ref_value(),
        "url": "https://api.github.com/repos/other/repo/git/refs/heads/ledger",
     }), "ledger_ref_resolution_invalid"),
    (FakeResponse(404), "ledger_ref_resolution_http_error"),
    (FakeResponse(500), "ledger_ref_resolution_http_error"),
    (FakeResponse(302), "ledger_ref_resolution_http_error"),
))
def test_compact_git_ref_hostile_responses_fail_closed(
        response, classification):
    with mock.patch.object(scanner.requests, "get", return_value=response), \
            pytest.raises(scanner._RemoteRecoveryRestoreError,
                          match=classification):
        scanner._pinned_ledger_restore_base()


def test_compact_git_ref_malformed_json_and_timeout_fail_closed():
    malformed = FakeResponse(200)
    malformed._encoded = b'{"ref":'
    with mock.patch.object(scanner.requests, "get", return_value=malformed), \
            pytest.raises(scanner._RemoteRecoveryRestoreError,
                          match="ledger_ref_resolution_unreadable"):
        scanner._pinned_ledger_restore_base()
    with mock.patch.object(
            scanner.requests, "get",
            side_effect=scanner.requests.Timeout("bounded timeout")), \
            pytest.raises(scanner._RemoteRecoveryRestoreError,
                          match="ledger_ref_resolution_transport_error"):
            scanner._pinned_ledger_restore_base()


@contextlib.contextmanager
def _local_keyed_boot_probe():
    """Supply authoritative no-history evidence to local-only regressions."""
    pinned = {
        "base": ("https://raw.githubusercontent.com/mitsugue/argus/" +
                 PINNED_SHA + "/ledger"),
        "commitSha": PINNED_SHA, "owner": "mitsugue",
        "repository": "argus", "pathPrefix": "ledger",
    }
    with mock.patch.object(
            scanner, "_pinned_ledger_restore_base", return_value=pinned), \
            mock.patch.object(
                scanner, "_probe_pinned_remote_recovery_nonce_floor",
                return_value=None), mock.patch.object(
                scanner, "_pinned_recovery_path_never_existed",
                return_value=True):
        yield


def test_new_disk_restores_exact_targets_and_seeds_wal_floor():
    readback, envelope, targets = _artifacts()
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False):
        with mock.patch.object(scanner.requests, "get", side_effect=_responses(
                _full(), readback, envelope)) as request_get:
            assert scanner._osint_restore_once() == "remote_journal_verified"
        stored = storage.load_checkpoint(paths["checkpoint"], require_seal=True)
        assert stored["missionTickDurability"]["walAppliedSequence"] == \
            RECOVERY_WAL
        marker = stored["remoteRecoveryRequired"]
        assert {name: marker[name] for name in (
            "schemaVersion", "mode", "keyId")} == {
                "schemaVersion": recovery.SIDECAR_SCHEMA,
                "mode": "encrypted_required", "keyId": CURRENT_ID}
        assert recovery.CHECKPOINT_ID_RE.fullmatch(marker["checkpointId"])
        installed_sidecar = scanner._read_local_recovery_sidecar()
        assert installed_sidecar["recovery"]["checkpointId"] == \
            marker["checkpointId"]
        # Compact proof hashes describe the newer producer checkpoint, while
        # these large bodies came from the older full object.  Restore must not
        # pair a compact-only hash with a body that was not recovered.
        assert stored["marketLedgerStateHash"] == _full()[
            "marketLedgerStateHash"]
        assert stored["chartIntelligenceStateHash"] == _full()[
            "chartIntelligenceStateHash"]
        assert scanner._MISSIONS == targets["missions"]
        assert len(scanner._MISSIONS) == 300
        for name, runtime in (
                ("missionWindows", scanner._MISSION_WINDOWS),
                ("forecasts", scanner._FORECAST_LEDGER),
                ("outcomes", scanner._OUTCOME_LEDGER),
                ("incidents", scanner._INCIDENTS),
                ("postmortems", scanner._POSTMORTEMS),
                ("periodicReports", scanner._PERIODIC_REPORTS),
                ("challengerRuns", scanner._CHALLENGER_RUNS),
                ("opsJournal", scanner._OPS_JOURNAL),
                ("opsJournalCompacted", scanner._OPS_JOURNAL_COMPACT)):
            assert runtime == targets[name]
        assert scanner._SOAK == targets["soak"]
        assert scanner._OPS_JOURNAL_META == targets["opsJournalMeta"]
        assert scanner._OPS_SEQ == targets["opsSequenceByAggregate"]
        assert scanner._POSTMORTEMS == targets["postmortems"]
        assert scanner._PERIODIC_REPORTS == targets["periodicReports"]
        assert scanner._CHALLENGER_RUNS == targets["challengerRuns"]
        assert scanner._OSINT_AGENT_QUEUE == targets["agentQueue"]
        wal = tick_durability.read_valid_wal(paths["wal"])
        assert wal["corruptCount"] == 0
        assert wal["maximumSequence"] == RECOVERY_WAL
        assert wal["records"][-1]["kind"] == "checkpoint_verified"
        assert scanner._REMOTE_CYCLE["verifiedWalSequence"] == RECOVERY_WAL
        assert scanner._REMOTE_CYCLE["remoteCommitSha"] == PINNED_SHA
        assert scanner._REMOTE_ACK["ackedKeys"] == [
            events["idempotencyKey"] for events in readback["opsJournal"]]
        scanner._MISSION_TICK_CONTEXT.update({
            "active": True, "ownerThread": scanner.threading.get_ident(),
            "jobId": "next", "walSequence": wal["maximumSequence"],
            "walEventCount": 0, "walAppendMs": 0, "lease": None,
        })
        next_record = scanner._append_tick_wal("transition", {"value": 1})
        assert next_record["sequence"] == RECOVERY_WAL + 1
        assert tick_durability.read_valid_wal(paths["wal"])[
            "maximumSequence"] == RECOVERY_WAL + 1
        assert pathlib.Path(paths["recovery"]).exists()
        scanner._OSINT_PERSIST_STATE.clear()
        scanner._OSINT_PERSIST_STATE.update({"restored": False})
        scanner._MISSIONS.clear()
        scanner._OPS_SEQ.clear()
        with _local_keyed_boot_probe():
            assert scanner._osint_restore_once() == "persistent_local"
        assert scanner._MISSIONS == targets["missions"]
        assert scanner._OPS_SEQ == targets["opsSequenceByAggregate"]
        raw_prefix = ("https://raw.githubusercontent.com/mitsugue/argus/"
                      f"{PINNED_SHA}/ledger")
        assert _urls(request_get) == [
            "https://api.github.com/repos/mitsugue/argus/git/ref/heads/ledger",
            f"{raw_prefix}/osint/memory.json",
            f"{raw_prefix}/osint/readback.json",
            f"{raw_prefix}/osint/recovery.json",
            ("https://api.github.com/repos/mitsugue/argus/git/commits/" +
             PINNED_SHA),
            ("https://api.github.com/repos/mitsugue/argus/git/commits/" +
             BASE_SHA),
        ]


def _install_local_pair(paths, root, sealed, sidecar):
    storage.atomic_write_json(
        paths["checkpoint"], sealed, temp_directory=root)
    storage.atomic_write_json(
        paths["recovery"], sidecar, temp_directory=root)


def _keyed_local_probe_responses(readback, envelope, *, full=None,
                                 ancestry=None):
    sidecar = (envelope if isinstance(envelope, dict) and envelope.get(
        "schemaVersion") == recovery.SIDECAR_SCHEMA else
        recovery.build_sidecar(readback, envelope))
    values = [
        _ref_response(),
        FakeResponse(200, readback),
        FakeResponse(200, sidecar),
    ]
    values.extend(ancestry if ancestry is not None else [
        _commit_metadata(PINNED_SHA, [BASE_SHA]),
        _commit_metadata(BASE_SHA, []),
    ])
    if full is not None:
        values.append(FakeResponse(200, full))
    return values


def _deep_outer_sidecar_response(depth=10_000):
    response = FakeResponse(200)
    response._encoded = (
        b'{"schemaVersion":"' + recovery.SIDECAR_SCHEMA.encode("ascii") +
        b'","readback":{},"recovery":' +
        (b'{"nested":' * depth) + b'null' + (b'}' * depth) + b'}'
    )
    assert len(response._encoded) < scanner._DURABLE_RECOVERY_MAX_BYTES
    return response


def _keyed_local_legacy_probe_responses(
        readback, *, history=None, ancestry=None, pinned_sha=PINNED_SHA):
    """One immutable legacy readback plus proved recovery-path absence."""
    values = [
        _ref_response(pinned_sha),
        FakeResponse(200, readback),
        FakeResponse(404),
        FakeResponse(200, [] if history is None else history),
    ]
    values.extend(ancestry if ancestry is not None else [
        _commit_metadata(PINNED_SHA, [BASE_SHA]),
        _commit_metadata(BASE_SHA, []),
    ])
    return values


def test_keyed_boot_remote_newer_than_local_uses_same_pinned_pair():
    local_wal = RECOVERY_WAL - 10
    local_readback, local_envelope, local_targets = _artifacts(
        target_wal=local_wal, mission_count=1, nonce=b"\xb1" * 12,
        generation_digit="b")
    local_sealed, local_sidecar = _sealed_local_pair(
        key=CURRENT_KEY, key_id=CURRENT_ID, readback=local_readback,
        envelope=local_envelope, targets=local_targets,
        generation_digit="2")
    remote_readback, remote_envelope, remote_targets = _artifacts(
        target_wal=RECOVERY_WAL, mission_count=3)
    with tempfile.TemporaryDirectory() as root, \
            scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False):
        _install_local_pair(paths, root, local_sealed, local_sidecar)
        with mock.patch.object(
                scanner.requests, "get", side_effect=
                _keyed_local_probe_responses(
                    remote_readback, remote_envelope, full=_full())) as get:
            assert scanner._osint_restore_once() == \
                "remote_journal_verified"
        assert scanner._DURABLE_STATE["remoteRecoveryNonceBoot"][
            "authority"] == "pinned_remote"
        assert scanner._MISSIONS == remote_targets["missions"]
        assert scanner._MISSION_BATCH_STATE["walAppliedSequence"] == \
            RECOVERY_WAL
        urls = _urls(get)
        assert sum(url.endswith("/osint/readback.json") for url in urls) == 1
        assert sum(url.endswith("/osint/recovery.json") for url in urls) == 1
        assert sum(url.endswith("/osint/memory.json") for url in urls) == 1


def test_deep_remote_outer_envelope_preserves_healthy_local_checkpoint():
    readback, envelope, targets = _artifacts(mission_count=2)
    sealed, sidecar = _sealed_local_pair(
        key=CURRENT_KEY, key_id=CURRENT_ID, readback=readback,
        envelope=envelope, targets=targets, generation_digit="2")
    with tempfile.TemporaryDirectory() as root, \
            scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False):
        _install_local_pair(paths, root, sealed, sidecar)
        checkpoint_before = pathlib.Path(paths["checkpoint"]).read_bytes()
        responses = [
            _ref_response(),
            FakeResponse(200, readback),
            _deep_outer_sidecar_response(),
            FakeResponse(500),
        ]
        with mock.patch.object(
                scanner.requests, "get", side_effect=responses):
            assert scanner._osint_restore_once() is None

        assert scanner._DURABLE_STATE["remoteRecoveryError"] == \
            "remote_recovery_unreadable_or_oversized"
        assert scanner._DURABLE_STATE["remoteRecoveryLocalError"] == \
            "remote_recovery_unreadable_or_oversized"
        assert not scanner._DURABLE_STATE.get("localCheckpointError")
        assert not scanner._DURABLE_STATE.get("quarantinedCheckpoint")
        assert pathlib.Path(paths["checkpoint"]).read_bytes() == \
            checkpoint_before
        assert pathlib.Path(paths["recovery"]).is_file()
        assert scanner._DURABLE_STATE.get("lastRestoreAt") is None


def test_remote_ledger_http_failure_preserves_seal_valid_canonical():
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False):
        storage.write_checkpoint(
            paths["checkpoint"], remote_snapshot(FULL_WAL),
            temp_directory=root)
        before = pathlib.Path(paths["checkpoint"]).read_bytes()
        with mock.patch.object(
                scanner, "_pinned_ledger_restore_base",
                side_effect=recovery.RecoveryBundleError(
                    "ledger_ref_resolution_http_error")):
            assert scanner._osint_restore_once() is None
        assert pathlib.Path(paths["checkpoint"]).read_bytes() == before
        assert not scanner._DURABLE_STATE.get("quarantinedCheckpoint")
        assert scanner._DURABLE_STATE["restoreDecision"] == {
            "RESTORE_STAGE": "REMOTE_NONCE_BOOT",
            "ERROR_CLASS": "ledger_ref_resolution_http_error",
            "LOCAL_VALIDITY": "VALID",
            "REMOTE_FAILURE_CLASS": "ledger_ref_resolution_http_error",
            "QUARANTINE_DECISION": "PRESERVE",
            "QUARANTINE_REASON": None,
        }
        assert scanner._DURABLE_STATE.get("lastRestoreAt") is None
        assert scanner._OSINT_PERSIST_STATE.get("restored") is not True


def test_remote_object_absent_preserves_marker_only_canonical_fail_closed():
    readback, _envelope, _targets = _artifacts(mission_count=1)
    marker_only = _required_checkpoint(remote_snapshot(FULL_WAL))
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False):
        storage.write_checkpoint(
            paths["checkpoint"], marker_only, temp_directory=root)
        before = pathlib.Path(paths["checkpoint"]).read_bytes()
        with mock.patch.object(
                scanner.requests, "get", side_effect=
                _keyed_local_legacy_probe_responses(readback)):
            assert scanner._osint_restore_once() is None
        assert pathlib.Path(paths["checkpoint"]).read_bytes() == before
        assert not scanner._DURABLE_STATE.get("quarantinedCheckpoint")
        assert scanner._DURABLE_STATE["remoteRecoveryError"] == \
            "recovery_nonce_authority_missing"
        assert scanner._DURABLE_STATE["restoreDecision"][
            "QUARANTINE_DECISION"] == "PRESERVE"
        assert scanner._DURABLE_STATE["restoreDecision"][
            "LOCAL_VALIDITY"] == "VALID"
        assert scanner._DURABLE_STATE.get("lastRestoreAt") is None


def test_proven_corrupt_local_checkpoint_is_quarantined_with_exact_reason():
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.object(scanner.requests, "get", return_value=
                              FakeResponse(503)):
        pathlib.Path(paths["checkpoint"]).write_text(
            '{"schemaVersion":"argus-durable-v3",', encoding="utf-8")
        assert scanner._osint_restore_once() is None
        assert not pathlib.Path(paths["checkpoint"]).exists()
        quarantine = pathlib.Path(
            scanner._DURABLE_STATE["quarantinedCheckpoint"])
        assert quarantine.is_file()
        assert scanner._DURABLE_STATE["restoreDecision"] == {
            "RESTORE_STAGE": "LOCAL_CHECKPOINT_LOAD",
            "ERROR_CLASS": "JSONDecodeError",
            "LOCAL_VALIDITY": "INVALID",
            "REMOTE_FAILURE_CLASS": None,
            "QUARANTINE_DECISION": "QUARANTINED",
            "QUARANTINE_REASON": "local_checkpoint_json_invalid",
        }
        assert scanner._DURABLE_STATE.get("lastRestoreAt") is None


def test_repeated_memory_snapshot_get_does_not_remove_valid_local_state():
    readback, _envelope, _targets = _artifacts(mission_count=1)
    marker_only = _required_checkpoint(remote_snapshot(FULL_WAL))
    responses = (
        _keyed_local_legacy_probe_responses(readback)[:4] +
        _keyed_local_legacy_probe_responses(readback)[:4])
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False), \
            mock.patch.object(scanner.requests, "get", side_effect=responses):
        storage.write_checkpoint(
            paths["checkpoint"], marker_only, temp_directory=root)
        before = pathlib.Path(paths["checkpoint"]).read_bytes()
        client = scanner.app.test_client()
        assert client.get(
            "/api/argus/osint/memory-snapshot").status_code == 200
        assert pathlib.Path(paths["checkpoint"]).read_bytes() == before
        assert client.get(
            "/api/argus/osint/memory-snapshot").status_code == 200
        assert pathlib.Path(paths["checkpoint"]).read_bytes() == before
        assert not scanner._DURABLE_STATE.get("quarantinedCheckpoint")
        assert scanner._DURABLE_STATE.get("lastRestoreAt") is None


def test_keyed_boot_local_newer_than_remote_stays_persistent_local():
    remote_wal = RECOVERY_WAL - 10
    remote_readback, remote_envelope, _remote_targets = _artifacts(
        target_wal=remote_wal, mission_count=1)
    local_readback, local_envelope, local_targets = _artifacts(
        target_wal=RECOVERY_WAL, mission_count=3, nonce=b"\xb1" * 12,
        generation_digit="b")
    local_sealed, local_sidecar = _sealed_local_pair(
        key=CURRENT_KEY, key_id=CURRENT_ID, readback=local_readback,
        envelope=local_envelope, targets=local_targets,
        generation_digit="2")
    with tempfile.TemporaryDirectory() as root, \
            scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False):
        _install_local_pair(paths, root, local_sealed, local_sidecar)
        with mock.patch.object(
                scanner.requests, "get", side_effect=
                _keyed_local_probe_responses(
                    remote_readback, remote_envelope)) as get:
            assert scanner._osint_restore_once() == "persistent_local"
        assert scanner._DURABLE_STATE["remoteRecoveryNonceBoot"][
            "authority"] == "local"
        assert scanner._MISSIONS == local_targets["missions"]
        assert scanner._MISSION_BATCH_STATE["walAppliedSequence"] == \
            RECOVERY_WAL
        assert not any(url.endswith("/osint/memory.json") for url in _urls(get))


def test_keyed_boot_equal_exact_pair_prefers_coherent_local():
    readback, envelope, targets = _artifacts(
        target_wal=RECOVERY_WAL, mission_count=2)
    local_sealed, local_sidecar = _sealed_local_pair(
        key=CURRENT_KEY, key_id=CURRENT_ID, readback=readback,
        envelope=envelope, targets=targets, generation_digit="2")
    with tempfile.TemporaryDirectory() as root, \
            scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False):
        _install_local_pair(paths, root, local_sealed, local_sidecar)
        with mock.patch.object(
                scanner.requests, "get", side_effect=
                _keyed_local_probe_responses(readback, envelope)) as get:
            assert scanner._osint_restore_once() == "persistent_local"
        assert scanner._DURABLE_STATE["remoteRecoveryNonceBoot"][
            "authority"] == "local"
        assert scanner._MISSIONS == targets["missions"]
        assert not any(url.endswith("/osint/memory.json") for url in _urls(get))


def test_keyed_boot_legacy_head_newer_than_local_fails_without_full_fallback():
    local_readback, local_envelope, local_targets = _artifacts(
        target_wal=RECOVERY_WAL - 10, mission_count=1,
        nonce=b"\xb1" * 12, generation_digit="b")
    local_sealed, local_sidecar = _sealed_local_pair(
        key=CURRENT_KEY, key_id=CURRENT_ID, readback=local_readback,
        envelope=local_envelope, targets=local_targets,
        generation_digit="2")
    remote_readback, _remote_envelope, _remote_targets = _artifacts(
        target_wal=RECOVERY_WAL, mission_count=3)
    with tempfile.TemporaryDirectory() as root, \
            scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False):
        _install_local_pair(paths, root, local_sealed, local_sidecar)
        with mock.patch.object(
                scanner.requests, "get", side_effect=
                _keyed_local_legacy_probe_responses(remote_readback)) as get:
            assert scanner._osint_restore_once() is None
        assert scanner._DURABLE_STATE["remoteRecoveryError"] == \
            "recovery_pinned_legacy_newer_than_local"
        assert scanner._DURABLE_STATE.get("lastRestoreAt") is None
        assert scanner._MISSIONS != local_targets["missions"]
        assert not any(url.endswith("/osint/memory.json") for url in _urls(get))


def test_keyed_boot_local_newer_than_legacy_head_stays_local():
    remote_readback, _remote_envelope, _remote_targets = _artifacts(
        target_wal=RECOVERY_WAL - 10, mission_count=1)
    local_readback, local_envelope, local_targets = _artifacts(
        target_wal=RECOVERY_WAL, mission_count=3,
        nonce=b"\xb1" * 12, generation_digit="b")
    local_sealed, local_sidecar = _sealed_local_pair(
        key=CURRENT_KEY, key_id=CURRENT_ID, readback=local_readback,
        envelope=local_envelope, targets=local_targets,
        generation_digit="2")
    with tempfile.TemporaryDirectory() as root, \
            scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False):
        _install_local_pair(paths, root, local_sealed, local_sidecar)
        with mock.patch.object(
                scanner.requests, "get", side_effect=
                _keyed_local_legacy_probe_responses(remote_readback)) as get:
            assert scanner._osint_restore_once() == "persistent_local"
        assert scanner._DURABLE_STATE["remoteRecoveryNonceBoot"][
            "authority"] == "local"
        assert scanner._MISSIONS == local_targets["missions"]
        assert not any(url.endswith("/osint/memory.json") for url in _urls(get))


def test_keyed_boot_equal_exact_legacy_readback_prefers_local():
    readback, envelope, targets = _artifacts(
        target_wal=RECOVERY_WAL, mission_count=2)
    local_sealed, local_sidecar = _sealed_local_pair(
        key=CURRENT_KEY, key_id=CURRENT_ID, readback=readback,
        envelope=envelope, targets=targets, generation_digit="2")
    with tempfile.TemporaryDirectory() as root, \
            scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False):
        _install_local_pair(paths, root, local_sealed, local_sidecar)
        with mock.patch.object(
                scanner.requests, "get", side_effect=
                _keyed_local_legacy_probe_responses(readback)):
            assert scanner._osint_restore_once() == "persistent_local"
        assert scanner._DURABLE_STATE["remoteRecoveryNonceBoot"][
            "authority"] == "local"
        assert scanner._MISSIONS == targets["missions"]


def test_keyed_boot_equal_wal_different_legacy_receipt_fails_closed():
    local_readback, local_envelope, local_targets = _artifacts(
        target_wal=RECOVERY_WAL, mission_count=1,
        nonce=b"\xb1" * 12, generation_digit="b")
    local_sealed, local_sidecar = _sealed_local_pair(
        key=CURRENT_KEY, key_id=CURRENT_ID, readback=local_readback,
        envelope=local_envelope, targets=local_targets,
        generation_digit="2")
    remote_readback = copy.deepcopy(local_readback)
    remote_readback["marketLedgerStateHash"] = "5" * 16
    remote_readback["receiptHash"] = journal._h({
        key: value for key, value in remote_readback.items()
        if key != "receiptHash"
    })
    with tempfile.TemporaryDirectory() as root, \
            scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False):
        _install_local_pair(paths, root, local_sealed, local_sidecar)
        with mock.patch.object(
                scanner.requests, "get", side_effect=
                _keyed_local_legacy_probe_responses(remote_readback)):
            assert scanner._osint_restore_once() is None
        assert scanner._DURABLE_STATE["remoteRecoveryError"] == \
            "recovery_pinned_legacy_receipt_mismatch"
        assert scanner._DURABLE_STATE.get("lastRestoreAt") is None


def test_keyed_boot_legacy_head_sibling_rejects_local_authority():
    local_readback, local_envelope, local_targets = _artifacts(
        target_wal=RECOVERY_WAL, mission_count=2)
    local_sealed, local_sidecar = _sealed_local_pair(
        key=CURRENT_KEY, key_id=CURRENT_ID, readback=local_readback,
        envelope=local_envelope, targets=local_targets,
        generation_digit="2")
    sibling = "c" * 40
    ancestry = [
        _commit_metadata(PINNED_SHA, [sibling]),
        _commit_metadata(sibling, []),
    ]
    with tempfile.TemporaryDirectory() as root, \
            scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False):
        _install_local_pair(paths, root, local_sealed, local_sidecar)
        with mock.patch.object(
                scanner.requests, "get", side_effect=
                _keyed_local_legacy_probe_responses(
                    local_readback, ancestry=ancestry)):
            assert scanner._osint_restore_once() is None
        assert scanner._DURABLE_STATE["remoteRecoveryError"] == \
            "recovery_local_authority_provenance_invalid"
        assert scanner._DURABLE_STATE.get("lastRestoreAt") is None


def test_keyed_boot_legacy_readback_or_history_ambiguity_fails_before_local():
    local_readback, local_envelope, local_targets = _artifacts(
        target_wal=RECOVERY_WAL, mission_count=1)
    local_sealed, local_sidecar = _sealed_local_pair(
        key=CURRENT_KEY, key_id=CURRENT_ID, readback=local_readback,
        envelope=local_envelope, targets=local_targets,
        generation_digit="2")
    malformed = copy.deepcopy(local_readback)
    malformed["receiptHash"] = "0" * 16
    cases = [
        ([_ref_response(), FakeResponse(404),
          FakeResponse(404)],
         "recovery_nonce_remote_legacy_readback_missing"),
        ([_ref_response(), FakeResponse(200, malformed),
          FakeResponse(404)],
         "recovery_nonce_remote_legacy_readback_invalid"),
        ([_ref_response(),
          FakeResponse(200, local_readback), FakeResponse(404),
          FakeResponse(503)],
         "recovery_nonce_history_query_ambiguous"),
        ([_ref_response(),
          FakeResponse(200, local_readback), FakeResponse(404),
          FakeResponse(200, {"sha": BASE_SHA})],
         "recovery_nonce_history_query_ambiguous"),
        ([_ref_response(),
          FakeResponse(200, local_readback), FakeResponse(404),
          FakeResponse(200, [{"sha": BASE_SHA}])],
         "recovery_nonce_remote_history_exists"),
    ]
    for responses, expected in cases:
        with tempfile.TemporaryDirectory() as root, \
                scanner_storage(root) as paths, \
                mock.patch.dict(os.environ, _key_env(), clear=False):
            _install_local_pair(paths, root, local_sealed, local_sidecar)
            with mock.patch.object(
                    scanner.requests, "get", side_effect=responses):
                assert scanner._osint_restore_once() is None
            assert scanner._DURABLE_STATE["remoteRecoveryError"] == expected
            assert scanner._DURABLE_STATE.get("lastRestoreAt") is None
            assert scanner._MISSIONS != local_targets["missions"]


def test_keyed_boot_remote_tag_or_ancestry_ambiguity_precedes_local_authority():
    local_readback, local_envelope, local_targets = _artifacts(
        target_wal=RECOVERY_WAL - 10, mission_count=1,
        nonce=b"\xb1" * 12, generation_digit="b")
    local_sealed, local_sidecar = _sealed_local_pair(
        key=CURRENT_KEY, key_id=CURRENT_ID, readback=local_readback,
        envelope=local_envelope, targets=local_targets,
        generation_digit="2")
    remote_readback, remote_envelope, _remote_targets = _artifacts()
    tampered = recovery.build_sidecar(remote_readback, remote_envelope)
    ciphertext = tampered["recovery"]["ciphertext"]
    replacement = "A" if ciphertext[0] != "A" else "B"
    tampered["recovery"]["ciphertext"] = replacement + ciphertext[1:]
    cases = [
        (_keyed_local_probe_responses(remote_readback, tampered, ancestry=[]),
         "recovery_ciphertext_hash_mismatch"),
        (_keyed_local_probe_responses(
            remote_readback, remote_envelope, ancestry=[
                _commit_metadata(PINNED_SHA, ["c" * 40]),
                _commit_metadata("c" * 40, []),
            ]), "recovery_ledger_commit_nonancestor"),
    ]
    for responses, expected in cases:
        with tempfile.TemporaryDirectory() as root, \
                scanner_storage(root) as paths, \
                mock.patch.dict(os.environ, _key_env(), clear=False):
            _install_local_pair(paths, root, local_sealed, local_sidecar)
            with mock.patch.object(
                    scanner.requests, "get", side_effect=responses) as get:
                assert scanner._osint_restore_once() is None
            assert scanner._DURABLE_STATE["remoteRecoveryError"] == expected
            assert scanner._DURABLE_STATE.get("lastRestoreAt") is None
            assert scanner._MISSIONS != local_targets["missions"]
            assert scanner._remote_recovery_nonce_authority_absent(
                include_lock=True)
            assert not any(
                url.endswith("/osint/memory.json") for url in _urls(get))


def test_previous_key_is_selected_exactly_and_wrong_current_never_falls_back():
    readback, previous_envelope, _ = _artifacts(
        key=PREVIOUS_KEY, key_id=PREVIOUS_ID, mission_count=1)
    with tempfile.TemporaryDirectory() as root, scanner_storage(root), \
            mock.patch.dict(os.environ, _key_env(previous=PREVIOUS_KEY),
                            clear=False), \
            mock.patch.object(scanner.requests, "get", side_effect=_responses(
                _full(), readback, previous_envelope)):
        assert scanner._osint_restore_once() == "remote_journal_verified"

    readback, current_envelope, _ = _artifacts(mission_count=1)
    with tempfile.TemporaryDirectory() as root, scanner_storage(root), \
            mock.patch.dict(os.environ, _key_env(
                current=b"\x33" * 32, previous=CURRENT_KEY), clear=False), \
            mock.patch.object(scanner.requests, "get", side_effect=_responses(
                _full(), readback, current_envelope)):
        assert scanner._osint_restore_once() is None
        assert scanner._DURABLE_STATE["remoteRecoveryError"] == \
            "recovery_authentication_failed"


def test_missing_pair_matrix_and_same_commit_pinning():
    with tempfile.TemporaryDirectory() as root, scanner_storage(root), \
            mock.patch.dict(os.environ, {}, clear=True):
        with mock.patch.object(scanner.requests, "get", side_effect=[
                _ref_response(),
                FakeResponse(200, _full()), FakeResponse(404),
                FakeResponse(404)]) as request_get:
            assert scanner._osint_restore_once() == "remote_journal_verified"
        urls = _urls(request_get)
        assert sum("api.github.com" in url for url in urls) == 1
        assert all(f"/{PINNED_SHA}/ledger/" in url
                   for url in urls if "raw.githubusercontent.com" in url)

    with tempfile.TemporaryDirectory() as root, scanner_storage(root), \
            mock.patch.dict(os.environ, _key_env(), clear=False), \
            mock.patch.object(scanner.requests, "get", side_effect=[
                _ref_response(),
                FakeResponse(200, _full()), FakeResponse(404),
                FakeResponse(404)]):
        assert scanner._osint_restore_once() is None
        assert scanner._DURABLE_STATE["remoteRecoveryError"] == \
            "remote_recovery_missing_for_readback"

    readback, _envelope, _targets = _artifacts(mission_count=1)
    with tempfile.TemporaryDirectory() as root, scanner_storage(root), \
            mock.patch.dict(os.environ, _key_env(), clear=False), \
            mock.patch.object(scanner.requests, "get", side_effect=[
                _ref_response(),
                FakeResponse(200, _full()), FakeResponse(200, readback),
                FakeResponse(404)]):
        assert scanner._osint_restore_once() is None
        assert scanner._DURABLE_STATE["remoteRecoveryError"] == \
            "remote_recovery_missing_for_readback"


def test_present_encrypted_artifact_requires_readback_and_configured_key():
    readback, envelope, _ = _artifacts(mission_count=1)
    sidecar = recovery.build_sidecar(readback, envelope)
    cases = [
        ({}, [FakeResponse(404), FakeResponse(200, sidecar)],
         "recovery_key_not_configured"),
        (_key_env(), [FakeResponse(404), FakeResponse(200, sidecar)],
         "remote_recovery_pair_readback_absent"),
    ]
    for env, tail, expected in cases:
        with tempfile.TemporaryDirectory() as root, scanner_storage(root), \
                mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(scanner.requests, "get", side_effect=[
                    _ref_response(),
                    FakeResponse(200, _full()), *tail]):
            assert scanner._osint_restore_once() is None
            assert scanner._DURABLE_STATE["remoteRecoveryError"] == expected


def test_sidecar_wrapper_and_pair_mismatch_fail_closed():
    readback, envelope, _ = _artifacts(mission_count=1)
    wrapper = recovery.build_sidecar(readback, envelope)
    with tempfile.TemporaryDirectory() as root, scanner_storage(root), \
            mock.patch.dict(os.environ, _key_env(), clear=False), \
            mock.patch.object(scanner.requests, "get", side_effect=_responses(
                _full(), readback, wrapper)):
        assert scanner._osint_restore_once() == "remote_journal_verified"

    bad_readback = copy.deepcopy(readback)
    bad_readback["receiptHash"] = "0" * 16
    with tempfile.TemporaryDirectory() as root, scanner_storage(root), \
            mock.patch.dict(os.environ, _key_env(), clear=False), \
            mock.patch.object(scanner.requests, "get", side_effect=_responses(
                _full(), bad_readback, wrapper)):
        assert scanner._osint_restore_once() is None

    tampered = copy.deepcopy(envelope)
    tampered["bundleHash"] = "0" * 64
    tampered_sidecar = copy.deepcopy(wrapper)
    tampered_sidecar["recovery"] = tampered
    with tempfile.TemporaryDirectory() as root, scanner_storage(root), \
            mock.patch.dict(os.environ, _key_env(), clear=False), \
            mock.patch.object(scanner.requests, "get", side_effect=_responses(
                _full(), readback, tampered_sidecar)):
        assert scanner._osint_restore_once() is None
        assert scanner._DURABLE_STATE["remoteRecoveryError"] == \
            "recovery_bundle_hash_mismatch"


def test_bare_recovery_envelope_is_never_a_cold_restore_artifact():
    readback, envelope, _ = _artifacts(mission_count=1)
    with tempfile.TemporaryDirectory() as root, scanner_storage(root), \
            mock.patch.dict(os.environ, _key_env(), clear=False), \
            mock.patch.object(scanner.requests, "get", side_effect=[
                _ref_response(),
                FakeResponse(200, _full()), FakeResponse(200, readback),
                FakeResponse(200, envelope)]):
        assert scanner._osint_restore_once() is None
        assert scanner._DURABLE_STATE["remoteRecoveryError"] == \
            "recovery_sidecar_required"


def test_cold_restore_requires_bounded_linear_base_to_pinned_commit():
    readback, envelope, _ = _artifacts(mission_count=1)
    sidecar = recovery.build_sidecar(readback, envelope)
    cases = [
        ([
            _commit_metadata(PINNED_SHA, ["c" * 40]),
            _commit_metadata("c" * 40, []),
         ], "recovery_ledger_commit_nonancestor"),
        ([
            _commit_metadata(PINNED_SHA, [BASE_SHA, "c" * 40]),
         ], "recovery_ledger_commit_multiparent"),
    ]
    for ancestry, expected in cases:
        with tempfile.TemporaryDirectory() as root, scanner_storage(root), \
                mock.patch.dict(os.environ, _key_env(), clear=False), \
                mock.patch.object(scanner.requests, "get", side_effect=[
                    _ref_response(),
                    FakeResponse(200, _full()), FakeResponse(200, readback),
                    FakeResponse(200, sidecar), *ancestry]):
            assert scanner._osint_restore_once() is None
            assert scanner._DURABLE_STATE["remoteRecoveryError"] == expected


@pytest.mark.parametrize("distance", [0, 1, 7])
def test_commit_path_fast_path_accepts_old_boundary(distance):
    base = BASE_SHA
    head = base if distance == 0 else PINNED_SHA
    if distance == 0:
        metadata = [{"sha": base, "parents": []}]
    else:
        shas = [base, *[f"{index:040x}"
                        for index in range(1, distance)], head]
        metadata = [
            {"sha": shas[index], "parents": [shas[index - 1]]}
            for index in range(len(shas) - 1, 0, -1)
        ]
        metadata.append({"sha": base, "parents": []})
    with mock.patch.object(
            scanner, "_bounded_ledger_commit_metadata",
            side_effect=metadata) as commit_get, \
            mock.patch.object(scanner, "_bounded_ledger_compare") as compare:
        assert scanner._verify_authenticated_ledger_commit_path(
            base, head, owner="mitsugue", repository="argus") == {
                "status": "verified", "ledgerBaseCommitSha": base,
                "exactCommitSha": head, "distance": distance}
    assert commit_get.call_count == distance + 1
    compare.assert_not_called()


@pytest.mark.parametrize("distance", [8, 11, 250])
def test_bounded_compare_accepts_complete_linear_contract(distance):
    response = _linear_compare_response(BASE_SHA, PINNED_SHA, distance)
    with mock.patch.object(scanner.requests, "get", return_value=response) as get:
        assert scanner._bounded_ledger_compare(
            "mitsugue", "argus", BASE_SHA, PINNED_SHA) == {
                "status": "verified", "ledgerBaseCommitSha": BASE_SHA,
                "exactCommitSha": PINNED_SHA, "distance": distance}
    get.assert_called_once_with(
        "https://api.github.com/repos/mitsugue/argus/compare/" +
        BASE_SHA + "..." + PINNED_SHA,
        timeout=(6, 15), stream=True, allow_redirects=False,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })


def test_bounded_compare_rejects_provider_boundary_plus_one():
    value = _linear_compare_value(BASE_SHA, PINNED_SHA, 250)
    value.update({"ahead_by": 251, "total_commits": 251})
    with mock.patch.object(
            scanner.requests, "get", return_value=FakeResponse(200, value)), \
            pytest.raises(
                recovery.RecoveryBundleError,
                match="recovery_ledger_compare_incomplete"):
        scanner._bounded_ledger_compare(
            "mitsugue", "argus", BASE_SHA, PINNED_SHA)


def test_bounded_compare_rejects_merge_fork_cycle_and_identity_mutation():
    merge = _linear_compare_value(BASE_SHA, PINNED_SHA, 1)
    merge["commits"][0]["parents"].append({
        "sha": "e" * 40,
        "url": _commit_api_url("mitsugue", "argus", "e" * 40),
    })
    fork = _linear_compare_value(BASE_SHA, PINNED_SHA, 1)
    fork.update({"status": "diverged", "behind_by": 1})
    descendant = _linear_compare_value(BASE_SHA, PINNED_SHA, 1)
    descendant.update({"status": "behind", "ahead_by": 0,
                       "behind_by": 1, "total_commits": 0, "commits": []})
    cycle = _linear_compare_value(BASE_SHA, PINNED_SHA, 2)
    cycle["commits"][1]["parents"][0]["sha"] = \
        cycle["commits"][1]["sha"]
    wrong_repository = _linear_compare_value(
        BASE_SHA, PINNED_SHA, 1, owner="other", repository="repo")
    mutated_head = _linear_compare_value(BASE_SHA, PINNED_SHA, 1)
    mutated_head["commits"][-1]["sha"] = "e" * 40
    malformed = {"url": "https://api.github.com/invalid"}
    cases = [
        (merge, "recovery_ledger_commit_multiparent"),
        (fork, "recovery_ledger_commit_nonancestor"),
        (descendant, "recovery_ledger_commit_nonancestor"),
        (cycle, "recovery_ledger_commit_nonancestor"),
        (wrong_repository, "recovery_ledger_compare_invalid"),
        (mutated_head, "recovery_ledger_compare_invalid"),
        (malformed, "recovery_ledger_compare_invalid"),
    ]
    for value, expected in cases:
        with mock.patch.object(
                scanner.requests, "get",
                return_value=FakeResponse(200, value)), \
                pytest.raises(recovery.RecoveryBundleError, match=expected):
            scanner._bounded_ledger_compare(
                "mitsugue", "argus", BASE_SHA, PINNED_SHA)


def test_bounded_compare_rejects_missing_http_timeout_and_oversized():
    with mock.patch.object(
            scanner.requests, "get", return_value=FakeResponse(404)), \
            pytest.raises(
                recovery.RecoveryBundleError,
                match="recovery_ledger_compare_http_error"):
        scanner._bounded_ledger_compare(
            "mitsugue", "argus", BASE_SHA, PINNED_SHA)

    with mock.patch.object(
            scanner.requests, "get",
            side_effect=scanner.requests.Timeout("synthetic")), \
            pytest.raises(
                recovery.RecoveryBundleError,
                match="recovery_ledger_compare_transport_error"):
        scanner._bounded_ledger_compare(
            "mitsugue", "argus", BASE_SHA, PINNED_SHA)

    oversized = FakeResponse(200)
    oversized._encoded = b"x" * 17
    with mock.patch.object(scanner.requests, "get", return_value=oversized), \
            mock.patch.object(
                scanner, "_LEDGER_COMPARE_RESPONSE_MAX_BYTES", 16), \
            pytest.raises(
                recovery.RecoveryBundleError,
                match="recovery_ledger_compare_oversized"):
        scanner._bounded_ledger_compare(
            "mitsugue", "argus", BASE_SHA, PINNED_SHA)


def test_stale_or_wal_regressing_remote_recovery_never_bootstraps():
    readback, envelope, _ = _artifacts(mission_count=1)
    stale_full = _full()
    stale_full["generatedAt"] = "2026-08-11T22:00:00Z"
    stale_full["asOf"] = stale_full["generatedAt"]
    cases = [
        (stale_full, "recovery_timestamp_regressed"),
        (_full(RECOVERY_WAL + 1), "recovery_target_behind_full"),
    ]
    for full, expected in cases:
        with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
                mock.patch.dict(os.environ, _key_env(), clear=False), \
                mock.patch.object(scanner.requests, "get", side_effect=_responses(
                    full, readback, envelope)):
            assert scanner._osint_restore_once() is None
            assert scanner._DURABLE_STATE["remoteRecoveryError"] == expected
            assert not pathlib.Path(paths["checkpoint"]).exists()
            assert scanner._DURABLE_STATE.get("lastRestoreAt") is None


def test_local_keyed_checkpoint_requires_exact_sidecar_and_key():
    readback, envelope, targets = _artifacts(mission_count=1)
    checkpoint = _full()
    checkpoint.update(copy.deepcopy(targets))
    # Local producer's raw checkpoint keeps its prior remote WAL scalar.
    checkpoint["missionTickDurability"]["remoteWalAppliedSequence"] = FULL_WAL
    checkpoint = _required_checkpoint(checkpoint)
    sealed = storage.seal_checkpoint(checkpoint)
    checkpoint_hash = storage._canonical_sha256(sealed)
    payload = recovery.decrypt_envelope(
        envelope, CURRENT_KEY, key_identifier=CURRENT_ID)
    payload["sourceCheckpointHash"] = checkpoint_hash
    payload["payloadHash"] = recovery._hash({
        key: value for key, value in payload.items() if key != "payloadHash"})
    local_envelope = recovery.encrypt_payload(
        payload, CURRENT_KEY, key_identifier=CURRENT_ID,
        nonce=b"\x91" * 12,
        generation_id="rrg-" + "9" * 32)
    sidecar = recovery.build_sidecar(readback, local_envelope)

    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths:
        storage.atomic_write_json(paths["checkpoint"], sealed,
                                  temp_directory=root)
        storage.atomic_write_json(paths["recovery"], sidecar,
                                  temp_directory=root)
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(scanner.requests, "get", side_effect=[
                    FakeResponse(503)]):
            assert scanner._osint_restore_once() is None
        assert scanner._DURABLE_STATE["localCheckpointError"] == \
            "RecoveryBundleError"
        assert scanner._DURABLE_STATE.get("lastRestoreAt") is None
        assert pathlib.Path(paths["checkpoint"]).exists()

    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False), \
            _local_keyed_boot_probe(), \
            mock.patch.object(scanner.requests, "get", side_effect=[
                FakeResponse(503)]):
        storage.atomic_write_json(paths["checkpoint"], sealed,
                                  temp_directory=root)
        assert scanner._osint_restore_once() is None
        assert scanner._DURABLE_STATE["remoteRecoveryLocalError"] == \
            "recovery_nonce_authority_missing"
        assert scanner._DURABLE_STATE.get("lastRestoreAt") is None

    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths:
        legacy = remote_snapshot(FULL_WAL)
        storage.write_checkpoint(paths["checkpoint"], legacy,
                                 temp_directory=root)
        with mock.patch.dict(os.environ, {}, clear=True):
            assert scanner._osint_restore_once() == "persistent_local"


def test_orphan_encrypted_sidecar_without_keys_blocks_legacy_fallback():
    readback, envelope, _targets = _artifacts(mission_count=1)
    sidecar = recovery.build_sidecar(readback, envelope)
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, {}, clear=True), \
            mock.patch.object(scanner.requests, "get") as request_get:
        storage.atomic_write_json(paths["recovery"], sidecar,
                                  temp_directory=root)
        assert scanner._osint_restore_once() is None
        assert scanner._DURABLE_STATE["remoteRecoveryLocalError"] == \
            "recovery_key_not_configured"
        assert scanner._DURABLE_STATE.get("lastRestoreAt") is None
        request_get.assert_not_called()


def test_local_keyed_checkpoint_validates_sidecar_before_authority():
    readback, envelope, targets = _artifacts(mission_count=1)
    checkpoint = _full()
    checkpoint.update(copy.deepcopy(targets))
    checkpoint["missionTickDurability"]["remoteWalAppliedSequence"] = FULL_WAL
    checkpoint = _required_checkpoint(checkpoint)
    sealed = storage.seal_checkpoint(checkpoint)
    payload = recovery.decrypt_envelope(
        envelope, CURRENT_KEY, key_identifier=CURRENT_ID)
    payload["sourceCheckpointHash"] = storage._canonical_sha256(sealed)
    payload["payloadHash"] = recovery._hash({
        key: value for key, value in payload.items() if key != "payloadHash"})
    local_envelope = recovery.encrypt_payload(
        payload, CURRENT_KEY, key_identifier=CURRENT_ID,
        nonce=b"\x81" * 12,
        generation_id="rrg-" + "8" * 32)
    sidecar = recovery.build_sidecar(readback, local_envelope)
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False), \
            _local_keyed_boot_probe():
        storage.atomic_write_json(paths["checkpoint"], sealed,
                                  temp_directory=root)
        storage.atomic_write_json(paths["recovery"], sidecar,
                                  temp_directory=root)
        assert scanner._osint_restore_once() == "persistent_local"
        assert scanner._DURABLE_STATE["remoteRecoveryLocal"][
            "status"] == "verified"
        assert scanner._MISSIONS == targets["missions"]
        assert scanner._OPS_SEQ == targets["opsSequenceByAggregate"]
        assert tick_durability.read_valid_wal(paths["wal"])[
            "maximumSequence"] == RECOVERY_WAL

    tampered = copy.deepcopy(sidecar)
    ciphertext = tampered["recovery"]["ciphertext"]
    replacement = "A" if ciphertext[0] != "A" else "B"
    tampered["recovery"]["ciphertext"] = replacement + ciphertext[1:]
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False), \
            _local_keyed_boot_probe(), \
            mock.patch.object(scanner.requests, "get", side_effect=[
                FakeResponse(503)]):
        storage.atomic_write_json(paths["checkpoint"], sealed,
                                  temp_directory=root)
        storage.atomic_write_json(paths["recovery"], tampered,
                                  temp_directory=root)
        assert scanner._osint_restore_once() is None
        assert scanner._DURABLE_STATE.get("lastRestoreAt") is None
        assert scanner._MISSIONS != targets["missions"]


def test_configured_legacy_checkpoint_migrates_before_authority():
    readback, _envelope, targets = _artifacts(mission_count=2)
    legacy = _verified_legacy_checkpoint(readback, targets)
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False), \
            _local_keyed_boot_probe():
        storage.write_checkpoint(paths["checkpoint"], legacy,
                                 temp_directory=root)
        assert not pathlib.Path(paths["recovery"]).exists()
        assert scanner._osint_restore_once() == "persistent_local"
        installed = storage.load_checkpoint(
            paths["checkpoint"], require_seal=True)
        marker = installed["remoteRecoveryRequired"]
        assert {name: marker[name] for name in (
            "schemaVersion", "mode", "keyId")} == {
                "schemaVersion": recovery.SIDECAR_SCHEMA,
                "mode": "encrypted_required", "keyId": CURRENT_ID}
        assert recovery.CHECKPOINT_ID_RE.fullmatch(marker["checkpointId"])
        sidecar = scanner._read_local_recovery_sidecar()
        assert sidecar["recovery"]["keyId"] == CURRENT_ID
        assert sidecar["recovery"]["checkpointId"] == marker["checkpointId"]
        assert recovery.validate_pair(
            sidecar["readback"], sidecar["recovery"], CURRENT_KEY,
            key_identifier=CURRENT_ID)["targets"]["missions"] == \
            targets["missions"]
        assert scanner._DURABLE_STATE["remoteRecoveryMigration"] == {
            "status": "verified", "keyId": CURRENT_ID,
            "targetWalSequence": RECOVERY_WAL}
        assert scanner._DURABLE_STATE.get("lastRestoreAt") is not None


def test_production_shaped_first_activation_accepts_live_distance_11_from_nonce_32():
    remote_readback, _remote_envelope, _remote_targets = _artifacts(
        target_wal=PRODUCTION_REMOTE_WAL, mission_count=1)
    _local_readback, _local_envelope, local_targets = _artifacts(
        target_wal=PRODUCTION_LOCAL_WAL, mission_count=3,
        nonce=b"\x91" * 12, generation_digit="9")
    legacy = _unverified_first_activation_checkpoint(
        remote_readback, local_targets)
    legacy["remoteJournalCycle"].update({
        "remoteCommitSha": PRODUCTION_CHECKPOINT_COMMIT_SHA,
        "receiptCommitSha": PRODUCTION_CHECKPOINT_COMMIT_SHA,
    })
    pinned = _pinned_legacy_ledger(PRODUCTION_LEDGER_SHA)
    captured_capabilities = []

    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False):
        storage.write_checkpoint(paths["checkpoint"], legacy,
                                 temp_directory=root)
        configured = recovery.configured_keys()
        with mock.patch.object(
                scanner, "_probe_pinned_remote_recovery_nonce_floor",
                return_value=None), mock.patch.object(
                    scanner, "_pinned_recovery_path_never_existed",
                    return_value=True):
            boot = scanner._prepare_keyed_local_recovery_nonce_boot(
                storage.load_checkpoint(
                    paths["checkpoint"], require_seal=True),
                configured, pinned)
        assert boot["status"] == "activated_genesis"
        consumed = [int.from_bytes(
            scanner._next_remote_recovery_nonce(CURRENT_ID), "big")
            for _ in range(32)]
        assert consumed == list(range(1, 33))
        before = scanner._verify_remote_recovery_nonce_authority(configured)
        domain = recovery.nonce_material_domain(CURRENT_KEY)
        assert before["generation"] == 32
        assert before["keyMaterialCounters"] == {domain: 32}
        assert not pathlib.Path(paths["recovery"]).exists()

        ancestry_once = [
            *_linear_commit_responses(
                PRODUCTION_CHECKPOINT_COMMIT_SHA,
                PRODUCTION_LEDGER_SHA, 11),
            _linear_compare_response(
                PRODUCTION_CHECKPOINT_COMMIT_SHA,
                PRODUCTION_LEDGER_SHA, 11),
        ]
        responses = _keyed_local_legacy_probe_responses(
            remote_readback, ancestry=[*ancestry_once, *ancestry_once],
            pinned_sha=PRODUCTION_LEDGER_SHA)
        real_mint = scanner._mint_legacy_recovery_ledger_base_capability

        def capture_capability(*args, **kwargs):
            capability = real_mint(*args, **kwargs)
            captured_capabilities.append(capability)
            return capability

        with mock.patch.object(
                scanner.requests, "get", side_effect=responses), \
                mock.patch.object(
                    scanner,
                    "_mint_legacy_recovery_ledger_base_capability",
                    side_effect=capture_capability):
            assert scanner._osint_restore_once() == "persistent_local"

        assert len(captured_capabilities) == 1
        assert captured_capabilities[0]._consumed is True
        installed = storage.load_checkpoint(
            paths["checkpoint"], require_seal=True)
        assert installed["missionTickDurability"][
            "walAppliedSequence"] == PRODUCTION_LOCAL_WAL
        assert installed["remoteJournalCycle"]["readBackVerified"] is False
        assert installed["remoteJournalCycle"][
            "walReadBackVerified"] is False
        assert installed["remoteJournalCycle"][
            "compactReceiptHash"] is None
        sidecar = scanner._read_local_recovery_sidecar()
        payload = recovery.validate_pair(
            sidecar["readback"], sidecar["recovery"], CURRENT_KEY,
            key_identifier=CURRENT_ID)
        assert payload["targetWalSequence"] == PRODUCTION_LOCAL_WAL
        assert payload["ledgerBaseCommitSha"] == \
            PRODUCTION_CHECKPOINT_COMMIT_SHA
        assert payload["targets"]["missions"] == local_targets["missions"]
        assert int.from_bytes(recovery._b64_decode(
            sidecar["recovery"]["nonce"], "test_nonce_invalid"), "big") == 33
        after = scanner._verify_remote_recovery_nonce_authority(configured)
        assert after["generation"] == 33
        assert after["keyMaterialCounters"] == {domain: 33}
        assert scanner._DURABLE_STATE["remoteRecoveryNonceBoot"][
            "authority"] == "local"
        with pytest.raises(
                recovery.RecoveryBundleError,
                match="recovery_legacy_ledger_base_capability_invalid"):
            scanner._consume_legacy_recovery_ledger_base_capability(
                captured_capabilities[0], installed, sidecar["readback"],
                configured, captured_capabilities[0]._restore_token)


def test_first_activation_same_wal_conflict_fails_before_nonce_reservation():
    remote_readback, _remote_envelope, _remote_targets = _artifacts(
        target_wal=PRODUCTION_REMOTE_WAL, mission_count=1)
    _local_readback, _local_envelope, local_targets = _artifacts(
        target_wal=PRODUCTION_REMOTE_WAL, mission_count=3,
        nonce=b"\x92" * 12, generation_digit="9")
    legacy = _unverified_first_activation_checkpoint(
        remote_readback, local_targets,
        local_wal=PRODUCTION_REMOTE_WAL,
        remote_wal=PRODUCTION_REMOTE_WAL)
    legacy["marketLedgerStateHash"] = "9" * 16
    pinned = _pinned_legacy_ledger()

    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False):
        storage.write_checkpoint(paths["checkpoint"], legacy,
                                 temp_directory=root)
        canonical_before = pathlib.Path(paths["checkpoint"]).read_bytes()
        configured = recovery.configured_keys()
        with mock.patch.object(
                scanner, "_probe_pinned_remote_recovery_nonce_floor",
                return_value=None), mock.patch.object(
                    scanner, "_pinned_recovery_path_never_existed",
                    return_value=True):
            scanner._prepare_keyed_local_recovery_nonce_boot(
                storage.load_checkpoint(
                    paths["checkpoint"], require_seal=True),
                configured, pinned)
        for _ in range(16):
            scanner._next_remote_recovery_nonce(CURRENT_ID)
        domain = recovery.nonce_material_domain(CURRENT_KEY)
        before = scanner._verify_remote_recovery_nonce_authority(configured)
        assert before["generation"] == 16
        assert before["keyMaterialCounters"] == {domain: 16}

        with mock.patch.object(
                scanner.requests, "get", side_effect=
                _keyed_local_legacy_probe_responses(remote_readback)):
            assert scanner._osint_restore_once() is None
        after = scanner._verify_remote_recovery_nonce_authority(configured)
        assert after == before
        assert not pathlib.Path(paths["recovery"]).exists()
        assert pathlib.Path(paths["checkpoint"]).read_bytes() == \
            canonical_before
        assert scanner._DURABLE_STATE["remoteRecoveryLocalError"] == \
            "recovery_legacy_migration_failed"
        with pytest.raises(ValueError, match="recovery_ledger_base_unverified"):
            scanner._recovery_ledger_base(legacy)


def test_first_activation_capability_mutation_and_stale_use_fail_closed():
    remote_readback, _remote_envelope, _remote_targets = _artifacts(
        target_wal=PRODUCTION_REMOTE_WAL, mission_count=1)
    _local_readback, _local_envelope, local_targets = _artifacts(
        target_wal=PRODUCTION_LOCAL_WAL, mission_count=2,
        nonce=b"\x93" * 12, generation_digit="9")
    checkpoint = _unverified_first_activation_checkpoint(
        remote_readback, local_targets)
    checkpoint["remoteRecoveryRequired"] = {
        "schemaVersion": recovery.SIDECAR_SCHEMA,
        "mode": "encrypted_required",
        "keyId": CURRENT_ID,
        "checkpointId": CHECKPOINT_ID,
    }
    sealed = storage.seal_checkpoint(checkpoint)
    pinned = _pinned_legacy_ledger()
    restore_token = object()
    ancestry = {
        "status": "verified", "ledgerBaseCommitSha": BASE_SHA,
        "exactCommitSha": PINNED_SHA, "distance": 1,
    }

    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False), \
            mock.patch.object(
                scanner, "_verify_authenticated_ledger_commit_path",
                return_value=ancestry):
        configured = recovery.configured_keys()

        def mint(evidence=None):
            return scanner._mint_legacy_recovery_ledger_base_capability(
                sealed, configured, pinned,
                evidence or scanner._AuthenticatedPinnedLegacyReadbackEvidence(
                    pinned, remote_readback, restore_token),
                restore_token)

        mutated = mint()
        mutated._base_commit = "c" * 40
        with pytest.raises(
                recovery.RecoveryBundleError,
                match="recovery_legacy_ledger_base_capability_invalid"):
            scanner._consume_legacy_recovery_ledger_base_capability(
                mutated, sealed, {}, configured, restore_token)

        stale = mint()
        with pytest.raises(
                recovery.RecoveryBundleError,
                match="recovery_legacy_ledger_base_capability_invalid"):
            scanner._consume_legacy_recovery_ledger_base_capability(
                stale, sealed, {}, configured, object())

        changed_evidence = scanner._AuthenticatedPinnedLegacyReadbackEvidence(
            pinned, remote_readback, restore_token)
        changed = mint(changed_evidence)
        changed_evidence._readback["receiptHash"] = "0" * 16
        with pytest.raises(
                recovery.RecoveryBundleError,
                match="recovery_pinned_legacy_evidence_invalid"):
            scanner._consume_legacy_recovery_ledger_base_capability(
                changed, sealed, {}, configured, restore_token)

        newer_readback, _newer_envelope, _newer_targets = _artifacts(
            target_wal=PRODUCTION_LOCAL_WAL + 1, mission_count=1)
        newer = scanner._AuthenticatedPinnedLegacyReadbackEvidence(
            pinned, newer_readback, restore_token)
        with pytest.raises(
                recovery.RecoveryBundleError,
                match="recovery_legacy_ledger_base_authority_invalid"):
            scanner._mint_legacy_recovery_ledger_base_capability(
                sealed, configured, pinned, newer, restore_token)

        with mock.patch.dict(
                os.environ, _key_env(previous=PREVIOUS_KEY), clear=False), \
                pytest.raises(
                    recovery.RecoveryBundleError,
                    match="recovery_legacy_ledger_base_key_invalid"):
            scanner._mint_legacy_recovery_ledger_base_capability(
                sealed, recovery.configured_keys(), pinned,
                scanner._AuthenticatedPinnedLegacyReadbackEvidence(
                    pinned, remote_readback, restore_token),
                restore_token)

        assert scanner._remote_recovery_nonce_authority_absent(
            include_lock=False)
        assert not pathlib.Path(paths["recovery"]).exists()


def test_configured_legacy_migration_failure_never_becomes_authority():
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False), \
            _local_keyed_boot_probe(), \
            mock.patch.object(scanner.requests, "get", side_effect=[
                FakeResponse(503)]):
        storage.write_checkpoint(
            paths["checkpoint"], remote_snapshot(FULL_WAL),
            temp_directory=root)
        prior = pathlib.Path(paths["checkpoint"]).read_bytes()
        assert scanner._osint_restore_once() is None
        assert scanner._DURABLE_STATE["remoteRecoveryLocalError"] == \
            "recovery_legacy_migration_failed"
        assert scanner._DURABLE_STATE.get("lastRestoreAt") is None
        assert scanner._OSINT_PERSIST_STATE.get("restored") is not True
        assert pathlib.Path(paths["checkpoint"]).read_bytes() == prior


def _post_genesis_mismatch_fixture(paths):
    readback, envelope, targets = _artifacts(
        target_wal=PRODUCTION_LOCAL_WAL, mission_count=3,
        nonce=(33).to_bytes(12, "big"), generation_digit="3")
    old_checkpoint, old_sidecar = _sealed_local_pair(
        key=CURRENT_KEY, key_id=CURRENT_ID, readback=readback,
        envelope=envelope, targets=targets, generation_digit="3")
    old_payload = recovery.validate_pair(
        old_sidecar["readback"], old_sidecar["recovery"], CURRENT_KEY,
        key_identifier=CURRENT_ID)
    old_payload["ledgerBaseCommitSha"] = \
        PRODUCTION_CHECKPOINT_COMMIT_SHA
    old_payload["nonceAuthority"]["keyMaterialCounters"] = {
        recovery.nonce_material_domain(CURRENT_KEY): 33}
    old_payload["payloadHash"] = recovery._hash({
        name: value for name, value in old_payload.items()
        if name != "payloadHash"})
    old_envelope = recovery.encrypt_payload(
        old_payload, CURRENT_KEY, key_identifier=CURRENT_ID,
        nonce=(33).to_bytes(12, "big"),
        generation_id="rrg-" + "3" * 32)
    old_sidecar = recovery.build_sidecar(readback, old_envelope)

    current = copy.deepcopy(old_checkpoint)
    current["remoteRecoveryRequired"]["checkpointId"] = \
        "rcp-" + "6" * 32
    current["remoteJournalCycle"].update({
        "remoteCommitSha": None, "receiptCommitSha": None,
        "readBackVerified": False, "walReadBackVerified": False,
        "remoteDurabilityState": "not_started",
        "remoteWalAppliedSequence": 0, "verifiedWalSequence": 0,
        "compactReceiptHash": None,
    })
    current = storage.seal_checkpoint(current)

    legacy = copy.deepcopy(current)
    legacy.pop("remoteRecoveryRequired")
    legacy = storage.seal_checkpoint(legacy)
    storage.atomic_write_json(
        paths["checkpoint"], legacy, temp_directory=paths["tempDirectory"])
    configured = recovery.configured_keys()
    pinned = _pinned_legacy_ledger()
    with mock.patch.object(
            scanner, "_probe_pinned_remote_recovery_nonce_floor",
            return_value=None), mock.patch.object(
                scanner, "_pinned_recovery_path_never_existed",
                return_value=True):
        scanner._prepare_keyed_local_recovery_nonce_boot(
            storage.load_checkpoint(
                paths["checkpoint"], require_seal=True), configured, pinned)
    for _ in range(33):
        scanner._next_remote_recovery_nonce(CURRENT_ID)
    storage.atomic_write_json(
        paths["checkpoint"], current,
        temp_directory=paths["tempDirectory"])
    storage.atomic_write_json(
        paths["recovery"], old_sidecar,
        temp_directory=paths["tempDirectory"])
    return current, old_sidecar, old_payload, old_checkpoint


def _post_genesis_repair_expected(paths, current, sidecar, payload):
    checkpoint_identity = scanner._post_genesis_repair_file_identity(
        paths["checkpoint"])
    sidecar_identity = scanner._post_genesis_repair_file_identity(
        paths["recovery"])
    history = scanner._read_only_remote_recovery_nonce_authority(
        recovery.configured_keys())
    return {
        "schemaVersion": scanner._POST_GENESIS_PAIR_REPAIR_SCHEMA,
        "liveBuildSha": BUILD["buildSha"],
        "currentCheckpoint": {
            "path": paths["checkpoint"],
            "sha256": checkpoint_identity["sha256"],
            "bytes": checkpoint_identity["bytes"],
            "wal": PRODUCTION_LOCAL_WAL,
            "sealValid": True,
            "checkpointId": current["remoteRecoveryRequired"][
                "checkpointId"],
        },
        "currentSidecar": {
            "path": paths["recovery"],
            "sha256": sidecar_identity["sha256"],
            "bytes": sidecar_identity["bytes"],
            "boundCheckpointSha256": payload[
                "sourceCheckpointHash"],
            "boundCheckpointId": payload["checkpointId"],
        },
        "currentKeyId": CURRENT_ID,
        "previousKeyAbsent": True,
        "nonceAuthority": {
            "generation": history["generation"],
            "maximumCounter": max(
                history["keyMaterialCounters"].values()),
            "artifacts": scanner._post_genesis_repair_nonce_artifacts(),
        },
        "writersFenced": True,
        "activeWriters": 0,
        "ec2TimerDisabled": True,
        "ec2TimerInactive": True,
        "recoveryReadback": "UNAVAILABLE_PAIR_MISMATCH",
        "previousMatchingCheckpointArtifact": "NOT_PROVEN",
        "forensicBackupDirectory": os.path.join(
            paths["root"], "argus-recovery-post-genesis-forensic-test"),
    }


def test_post_genesis_mismatch_repair_plan_is_exact_and_read_only():
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False):
        current, sidecar, payload, _old = \
            _post_genesis_mismatch_fixture(paths)
        expected = _post_genesis_repair_expected(
            paths, current, sidecar, payload)
        observed_paths = [
            paths["checkpoint"], paths["recovery"],
            *[row["path"] for row in expected[
                "nonceAuthority"]["artifacts"].values()],
        ]
        before = {path: pathlib.Path(path).read_bytes()
                  for path in observed_paths}

        plan = scanner._execute_post_genesis_pair_repair(expected)

        assert plan["status"] == "DRY_RUN_PASS"
        assert plan["mutationAuthorized"] is False
        assert plan["previousMatchingCheckpointArtifact"] == "NOT_PROVEN"
        assert plan["projectionEquality"] == "PROVEN"
        assert plan["nonceGeneration"] == 33
        assert plan["nonceMaximumCounter"] == 33
        assert {path: pathlib.Path(path).read_bytes()
                for path in observed_paths} == before
        assert not pathlib.Path(plan["forensicBackupDirectory"]).exists()


def test_post_genesis_repair_rebinds_and_cold_boots_without_nonce_35():
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False):
        current, sidecar, payload, _old = \
            _post_genesis_mismatch_fixture(paths)
        expected = _post_genesis_repair_expected(
            paths, current, sidecar, payload)
        current_before = pathlib.Path(paths["checkpoint"]).read_bytes()
        sidecar_before = pathlib.Path(paths["recovery"]).read_bytes()

        result = scanner._execute_post_genesis_pair_repair(
            expected, execute=True)

        assert result["status"] == "REPAIR_APPLIED_KEYED_PAIR_VERIFIED"
        assert result["nonceGeneration"] == 34
        assert result["nonceMaximumCounter"] == 34
        assert pathlib.Path(paths["checkpoint"]).read_bytes() == \
            current_before
        installed = scanner._read_local_recovery_sidecar()
        assert pathlib.Path(paths["recovery"]).read_bytes() != sidecar_before
        installed_payload = recovery.validate_pair(
            installed["readback"], installed["recovery"], CURRENT_KEY,
            key_identifier=CURRENT_ID)
        assert installed_payload["sourceCheckpointHash"] == \
            storage._canonical_sha256(current)
        assert installed_payload["checkpointId"] == \
            current["remoteRecoveryRequired"]["checkpointId"]
        assert installed_payload["targets"] == payload["targets"]
        assert installed_payload["ledgerBaseCommitSha"] == \
            PRODUCTION_CHECKPOINT_COMMIT_SHA
        scanner._verify_local_recovery_sidecar(
            current, allow_legacy_migration=False)
        backup = pathlib.Path(result["forensicBackupDirectory"])
        assert backup.is_dir()
        assert (backup / "checkpoint.json").read_bytes() == current_before
        assert (backup / "sidecar.json").read_bytes() == sidecar_before
        assert (backup / "manifest.json").is_file()
        assert (backup / "manifest.sha256").is_file()

        remote_readback, _remote_envelope, _remote_targets = _artifacts(
            target_wal=PRODUCTION_REMOTE_WAL, mission_count=1)
        ancestry = [
            *_linear_commit_responses(
                PRODUCTION_CHECKPOINT_COMMIT_SHA,
                PRODUCTION_LEDGER_SHA, 11),
            _linear_compare_response(
                PRODUCTION_CHECKPOINT_COMMIT_SHA,
                PRODUCTION_LEDGER_SHA, 11),
        ]
        pair_before_boot = {
            paths["checkpoint"]: pathlib.Path(
                paths["checkpoint"]).read_bytes(),
            paths["recovery"]: pathlib.Path(paths["recovery"]).read_bytes(),
        }
        nonce_before_boot = scanner._verify_remote_recovery_nonce_authority(
            recovery.configured_keys())
        nonce_artifacts_before_boot = {
            name: pathlib.Path(identity["path"]).read_bytes()
            for name, identity in
            scanner._post_genesis_repair_nonce_artifacts().items()
        }

        with mock.patch.object(
                scanner.requests, "get", side_effect=
                _keyed_local_legacy_probe_responses(
                    remote_readback, ancestry=ancestry,
                    pinned_sha=PRODUCTION_LEDGER_SHA)):
            assert scanner._osint_restore_once() == "persistent_local"

        nonce_after_boot = scanner._verify_remote_recovery_nonce_authority(
            recovery.configured_keys())
        assert nonce_before_boot["generation"] == 34
        assert max(nonce_before_boot["keyMaterialCounters"].values()) == 34
        assert nonce_after_boot == nonce_before_boot
        assert {
            name: pathlib.Path(identity["path"]).read_bytes()
            for name, identity in
            scanner._post_genesis_repair_nonce_artifacts().items()
        } == nonce_artifacts_before_boot
        assert {
            path: pathlib.Path(path).read_bytes()
            for path in pair_before_boot
        } == pair_before_boot
        assert scanner._DURABLE_STATE["remoteRecoveryNonceBoot"][
            "authority"] == "local"
        assert scanner._MISSIONS == payload["targets"]["missions"]


def test_absent_checkpoint_ledger_commit_requires_bounded_ancestry():
    local = types.SimpleNamespace(
        _payload={"ledgerBaseCommitSha": BASE_SHA}, _ledger_commit=None)
    pinned = _pinned_legacy_ledger()
    remote = types.SimpleNamespace()
    verified = {
        "status": "verified", "ledgerBaseCommitSha": BASE_SHA,
        "exactCommitSha": PINNED_SHA, "distance": 11,
    }
    with mock.patch.object(
            scanner, "_verify_authenticated_ledger_commit_path",
            return_value=verified) as ancestry:
        assert scanner._local_recovery_pair_has_pinned_provenance(
            local, remote, pinned) is True
    ancestry.assert_called_once_with(
        BASE_SHA, PINNED_SHA, owner="mitsugue", repository="argus")

    with mock.patch.object(
            scanner, "_verify_authenticated_ledger_commit_path",
            side_effect=recovery.RecoveryBundleError(
                "recovery_ledger_commit_nonancestor")):
        assert scanner._local_recovery_pair_has_pinned_provenance(
            local, remote, pinned) is False


def test_present_checkpoint_ledger_commit_mismatch_remains_strict():
    local = types.SimpleNamespace(
        _payload={"ledgerBaseCommitSha": BASE_SHA},
        _ledger_commit="c" * 40)
    with mock.patch.object(
            scanner, "_verify_authenticated_ledger_commit_path") as ancestry:
        assert scanner._local_recovery_pair_has_pinned_provenance(
            local, types.SimpleNamespace(), _pinned_legacy_ledger()) is False
    ancestry.assert_not_called()


def test_post_genesis_mismatch_repair_rejects_projection_change_and_old_file():
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False):
        current, sidecar, payload, _old = \
            _post_genesis_mismatch_fixture(paths)
        expected = _post_genesis_repair_expected(
            paths, current, sidecar, payload)
        changed = copy.deepcopy(current)
        changed["missions"] = [{"missionId": "unproven-new-state"}]
        changed = storage.seal_checkpoint(changed)
        storage.atomic_write_json(
            paths["checkpoint"], changed,
            temp_directory=paths["tempDirectory"])
        identity = scanner._post_genesis_repair_file_identity(
            paths["checkpoint"])
        expected["currentCheckpoint"].update({
            "sha256": identity["sha256"], "bytes": identity["bytes"]})
        with pytest.raises(
                recovery.RecoveryBundleError,
                match="recovery_post_genesis_repair_projection_mismatch"):
            scanner._plan_post_genesis_pair_repair(expected)

    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False):
        current, sidecar, payload, old = \
            _post_genesis_mismatch_fixture(paths)
        expected = _post_genesis_repair_expected(
            paths, current, sidecar, payload)
        matching = os.path.join(root, "forensic-old-checkpoint.json")
        assert storage._canonical_sha256(old) == payload[
            "sourceCheckpointHash"]
        pathlib.Path(matching).write_bytes(storage._canonical(old))
        with pytest.raises(
                recovery.RecoveryBundleError,
                match="recovery_post_genesis_repair_previous_checkpoint_found"):
            scanner._plan_post_genesis_pair_repair(expected)
        assert not scanner._DURABLE_STATE.get("quarantinedCheckpoint")


def test_legacy_migration_installs_sidecar_before_checkpoint_and_retries_crash():
    readback, _envelope, targets = _artifacts(mission_count=2)
    legacy = _verified_legacy_checkpoint(readback, targets)
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False), \
            _local_keyed_boot_probe(), \
            mock.patch.object(scanner.requests, "get", side_effect=[
                FakeResponse(503)]):
        storage.write_checkpoint(paths["checkpoint"], legacy,
                                 temp_directory=root)
        prior = pathlib.Path(paths["checkpoint"]).read_bytes()
        real_replace = os.replace
        observed = {"blocked": False}

        def interrupt_before_pointer(source, destination):
            if os.path.abspath(destination) == os.path.abspath(
                    paths["checkpoint"]) and str(source).endswith(
                        ".recovery-migration-checkpoint"):
                observed["blocked"] = True
                raise OSError("simulated_pointer_crash")
            return real_replace(source, destination)

        with mock.patch.object(
                scanner.os, "replace", side_effect=interrupt_before_pointer):
            assert scanner._osint_restore_once() is None
        assert observed["blocked"] is True
        assert pathlib.Path(paths["checkpoint"]).read_bytes() == prior
        assert pathlib.Path(paths["recovery"]).is_file()
        assert not scanner._DURABLE_STATE.get("quarantinedCheckpoint")

        # The orphaned, authenticated sidecar supplies a nonce floor.  A
        # clean retry stages a fresh pair and atomically switches the
        # checkpoint without ever applying the old plaintext authority.
        assert scanner._osint_restore_once() == "persistent_local"
        installed = storage.load_checkpoint(
            paths["checkpoint"], require_seal=True)
        verified = scanner._verify_local_recovery_sidecar(
            installed, allow_legacy_migration=False)
        assert verified["remoteRecoveryProvenance"][
            "targetWalSequence"] == RECOVERY_WAL


def test_required_marker_is_exact_and_bound_to_sidecar_key_id():
    readback, envelope, targets = _artifacts(mission_count=1)
    sealed, sidecar = _sealed_local_pair(
        key=CURRENT_KEY, key_id=CURRENT_ID, readback=readback,
        envelope=envelope, targets=targets, generation_digit="7")
    invalid = copy.deepcopy(sealed)
    invalid["remoteRecoveryRequired"]["unexpected"] = True
    invalid = storage.seal_checkpoint(invalid)
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False), \
            _local_keyed_boot_probe(), \
            mock.patch.object(scanner.requests, "get", side_effect=[
                FakeResponse(503)]):
        storage.atomic_write_json(paths["checkpoint"], invalid,
                                  temp_directory=root)
        storage.atomic_write_json(paths["recovery"], sidecar,
                                  temp_directory=root)
        assert scanner._osint_restore_once() is None
        assert scanner._DURABLE_STATE["remoteRecoveryLocalError"] == \
            "recovery_required_marker_invalid"

    previous_readback, previous_envelope, previous_targets = _artifacts(
        key=PREVIOUS_KEY, key_id=PREVIOUS_ID, mission_count=1)
    previous_sealed, previous_sidecar = _sealed_local_pair(
        key=PREVIOUS_KEY, key_id=PREVIOUS_ID, readback=previous_readback,
        envelope=previous_envelope, targets=previous_targets,
        generation_digit="6")
    mismatch = copy.deepcopy(previous_sealed)
    mismatch["remoteRecoveryRequired"]["keyId"] = CURRENT_ID
    mismatch = storage.seal_checkpoint(mismatch)
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(previous=PREVIOUS_KEY),
                            clear=False), \
            _local_keyed_boot_probe(), \
            mock.patch.object(scanner.requests, "get", side_effect=[
                FakeResponse(503)]):
        storage.atomic_write_json(paths["checkpoint"], mismatch,
                                  temp_directory=root)
        storage.atomic_write_json(paths["recovery"], previous_sidecar,
                                  temp_directory=root)
        assert scanner._osint_restore_once() is None
        assert scanner._DURABLE_STATE["remoteRecoveryLocalError"] == \
            "recovery_required_marker_key_mismatch"


def test_previous_key_local_sidecar_restores_for_rotation_compatibility():
    readback, envelope, targets = _artifacts(
        key=PREVIOUS_KEY, key_id=PREVIOUS_ID, mission_count=1)
    sealed, sidecar = _sealed_local_pair(
        key=PREVIOUS_KEY, key_id=PREVIOUS_ID, readback=readback,
        envelope=envelope, targets=targets, generation_digit="5")
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(previous=PREVIOUS_KEY),
                            clear=False), _local_keyed_boot_probe():
        storage.atomic_write_json(paths["checkpoint"], sealed,
                                  temp_directory=root)
        storage.atomic_write_json(paths["recovery"], sidecar,
                                  temp_directory=root)
        assert scanner._osint_restore_once() == "persistent_local"
        assert scanner._DURABLE_STATE["remoteRecoveryLocal"]["keyId"] == \
            PREVIOUS_ID
        assert scanner._MISSIONS == targets["missions"]


def test_remote_recovery_wrapper_cap_fails_closed_before_json_parse():
    readback, envelope, _targets = _artifacts(mission_count=1)
    with tempfile.TemporaryDirectory() as root, scanner_storage(root), \
            mock.patch.dict(os.environ, _key_env(), clear=False), \
            mock.patch.object(scanner, "_DURABLE_RECOVERY_MAX_BYTES", 128), \
            mock.patch.object(scanner.requests, "get", side_effect=_responses(
                _full(), readback, envelope)):
        assert scanner._osint_restore_once() is None
        assert scanner._DURABLE_STATE["remoteRecoveryError"] == \
            "remote_recovery_unreadable_or_oversized"


def test_streamed_oversized_readback_cannot_bypass_decompressed_byte_cap():
    response = FakeResponse(200)
    response._encoded = b"[" + (
        b" " * journal.MAX_COMPACT_READBACK_BYTES)
    with mock.patch.object(scanner.requests, "get", return_value=response), \
            pytest.raises(
                recovery.RecoveryBundleError,
                match="remote_readback_unreadable_or_oversized"):
        scanner._fetch_pinned_recovery_object(
            "https://immutable.invalid/readback.json",
            scanner._DURABLE_READBACK_MAX_BYTES, "readback")


def test_local_sidecar_reader_rejects_symlink_and_growth_before_json_parse():
    readback, envelope, _ = _artifacts(mission_count=1)
    sidecar = recovery.build_sidecar(readback, envelope)
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths:
        real = pathlib.Path(root, "real-sidecar.json")
        real.write_text(recovery._canonical(sidecar).decode("utf-8"),
                        encoding="utf-8")
        pathlib.Path(paths["recovery"]).symlink_to(real)
        try:
            scanner._read_local_recovery_sidecar()
        except recovery.RecoveryBundleError as exc:
            assert exc.classification in (
                "recovery_local_sidecar_invalid",
                "recovery_local_sidecar_unreadable")
        else:
            raise AssertionError("sidecar symlink accepted")

    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths:
        pathlib.Path(paths["recovery"]).write_text(
            "{}", encoding="utf-8")
        original_read = scanner.os.read
        first = True

        def grow_then_read(descriptor, size):
            nonlocal first
            if first:
                first = False
                with open(paths["recovery"], "ab") as handle:
                    handle.write(b" " * (recovery.MAX_SIDECAR_BYTES + 1))
            return original_read(descriptor, size)

        with mock.patch.object(scanner.os, "read", side_effect=grow_then_read):
            try:
                scanner._read_local_recovery_sidecar()
            except recovery.RecoveryBundleError as exc:
                assert exc.classification == "recovery_local_sidecar_invalid"
            else:
                raise AssertionError("growing sidecar accepted")


def test_deep_local_sidecar_and_outer_tree_fail_in_recovery_domain():
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths:
        pathlib.Path(paths["recovery"]).write_bytes(
            _deep_outer_sidecar_response()._encoded)
        try:
            scanner._read_local_recovery_sidecar()
        except recovery.RecoveryBundleError as exc:
            assert exc.classification == "recovery_local_sidecar_unreadable"
        else:
            raise AssertionError("deep local sidecar accepted")

    nested = None
    for _ in range(recovery.MAX_DEPTH + 1):
        nested = {"nested": nested}
    try:
        recovery.validate_sidecar({
            "schemaVersion": recovery.SIDECAR_SCHEMA,
            "readback": {},
            "recovery": nested,
        })
    except recovery.RecoveryBundleError as exc:
        assert exc.classification == "recovery_outer_bounds_invalid"
    else:
        raise AssertionError("deep in-memory outer sidecar accepted")


def test_late_apply_failure_rolls_back_and_never_sets_restore_success():
    readback, envelope, _ = _artifacts(mission_count=1)
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            mock.patch.dict(os.environ, _key_env(), clear=False), \
            mock.patch.object(scanner.requests, "get", side_effect=_responses(
                _full(), readback, envelope)), \
            mock.patch.object(scanner, "_persist_durability_metadata",
                              side_effect=OSError("late")):
        scanner._MISSIONS[:] = [{"missionId": "pre-restore"}]
        scanner._OPS_SEQ.update({"mission:pre-restore": 73})
        scanner._OSINT_AGENT_QUEUE.update({"BEFORE": {"mode": "deep"}})
        before = copy.deepcopy(scanner._MISSIONS)
        before_sequence = copy.deepcopy(scanner._OPS_SEQ)
        before_queue = copy.deepcopy(scanner._OSINT_AGENT_QUEUE)
        assert scanner._osint_restore_once() is None
        assert scanner._MISSIONS == before
        assert scanner._OPS_SEQ == before_sequence
        assert scanner._OSINT_AGENT_QUEUE == before_queue
        assert not pathlib.Path(paths["wal"]).exists()
        assert scanner._DURABLE_STATE.get("remoteRecoveryWalFloor") is None
        assert scanner._DURABLE_STATE.get("lastRestoreAt") is None
        assert scanner._DURABLE_STATE.get("restoreSource") != \
            "remote_journal_verified"
        assert scanner._OSINT_PERSIST_STATE.get("restored") is not True


def test_wal_floor_readback_failure_removes_only_new_anchor():
    blob = {
        "missionTickDurability": {"walAppliedSequence": RECOVERY_WAL},
        "remoteRecoveryProvenance": {
            "targetWalSequence": RECOVERY_WAL,
            "compactReceiptHash": "1" * 16,
            "bundleHash": "2" * 64,
            "ledgerCommitSha": PINNED_SHA,
            "checkpointVerifiedAt": RECOVERY_AT,
            "buildIdentity": BUILD,
        },
    }
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths:
        original = tick_durability.read_valid_wal
        calls = 0

        def corrupt_first_readback(path, *, after_sequence=0):
            nonlocal calls
            calls += 1
            value = original(path, after_sequence=after_sequence)
            if calls == 2:
                value["corruptCount"] = 1
            return value

        with mock.patch.object(
                scanner.argus_tick_durability, "read_valid_wal",
                side_effect=corrupt_first_readback):
            try:
                scanner._seed_remote_recovery_wal_floor(blob)
            except scanner._RemoteRecoveryRestoreError as exc:
                assert str(exc) == "recovery_wal_floor_readback_failed"
            else:
                raise AssertionError("corrupt WAL floor read-back accepted")
        assert not pathlib.Path(paths["wal"]).exists()
