"""Canonical bytes, detached ownership, and temporary save lifetime."""
import copy
import hashlib
import inspect
import json
import weakref
from unittest import mock

import pytest

from test_remote_recovery_publish import (
    KEY, KEY_ID, _pair, recovery, scanner, storage, scanner_storage,
    _key_environment, _reset_recovery_targets, _append_verified_cycle,
    _activate_clean_legacy_nonce_authority, _advance_nonce_floor_to_33,
)


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except RecursionError as exc:
        raise recovery.RecoveryBundleError("recovery_json_too_deep") from exc
    except (TypeError, ValueError) as exc:
        raise recovery.RecoveryBundleError("recovery_json_invalid") from exc


def outcome(action):
    try:
        return "ok", action()
    except Exception as exc:
        return "error", type(exc), str(exc)


@pytest.mark.parametrize("length", [0, 1, 65535, 65536, 65537, 1048576])
@pytest.mark.parametrize("alphabet", ["Az_+/-=09", 'a"\\\n\t', "abc日本"])
def test_envelope_and_sidecar_canonical_parity(length, alphabet):
    _, sidecar = _pair()
    envelope = sidecar["recovery"]
    envelope["ciphertext"] = (alphabet * (length // len(alphabet) + 1))[:length]
    body = {k: v for k, v in envelope.items() if k != "bundleHash"}
    assert recovery._envelope_metrics(envelope) == (
        len(canonical(envelope)), hashlib.sha256(canonical(body)).hexdigest())
    assert recovery._sidecar_size(sidecar) == len(canonical(sidecar))


@pytest.mark.parametrize("value", [None, [], {}, False, 1, float("nan"),
                                   {"a": set()}, {"a": "\ud800"}])
@pytest.mark.parametrize("section", ["readback", "recovery"])
def test_sidecar_unusual_values_keep_canonical_errors(section, value):
    _, sidecar = _pair()
    sidecar[section] = value
    assert outcome(lambda: recovery._sidecar_size(sidecar)) == outcome(
        lambda: len(canonical(sidecar)))


@pytest.mark.parametrize("section", ["readback", "recovery"])
def test_sidecar_cyclic_value_keeps_canonical_error(section):
    _, sidecar = _pair()
    sidecar[section]["extra"] = sidecar
    assert outcome(lambda: recovery._sidecar_size(sidecar)) == outcome(
        lambda: len(canonical(sidecar)))


@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_exact_sidecar_size_limit(monkeypatch, offset):
    compact, sidecar = _pair()
    monkeypatch.setattr(recovery, "MAX_SIDECAR_BYTES",
                        len(canonical(sidecar)) + offset)
    for action in (lambda: recovery.validate_sidecar(sidecar),
                   lambda: recovery.build_sidecar(compact, sidecar["recovery"])):
        if offset < 0:
            with pytest.raises(recovery.RecoveryBundleError,
                               match="^recovery_sidecar_oversized$"):
                action()
        else:
            assert action() == sidecar


def build(payload):
    return recovery.build_payload(
        compact_readback=payload["compactReadback"],
        targets=payload["targets"], generated_at=payload["generatedAt"],
        build_identity=payload["buildIdentity"],
        source_checkpoint_hash=payload["sourceCheckpointHash"],
        checkpoint_id=payload["checkpointId"],
        checkpoint_verified_at=payload["checkpointVerifiedAt"],
        ledger_base_commit_sha=payload["ledgerBaseCommitSha"],
        nonce_authority=payload["nonceAuthority"])


def test_public_and_fresh_payload_ownership():
    _, sidecar = _pair()
    envelope = sidecar["recovery"]
    source = recovery.decrypt_envelope(envelope, KEY, key_identifier=KEY_ID)
    original = copy.deepcopy(source)
    built = build(source)
    assert built == original
    source["targets"]["missions"].append({"id": "input"})
    assert built == original
    built["targets"]["missions"].append({"id": "output"})
    assert source["targets"]["missions"] == [{"id": "input"}]
    for action in (
        lambda: recovery.validate_payload(original),
        lambda: recovery.decrypt_envelope(envelope, KEY, key_identifier=KEY_ID),
    ):
        detached = action()
        detached["targets"]["missions"].append({"id": "detached"})
        assert action() == original
    validated = recovery.validate_envelope(envelope)
    validated["buildIdentity"]["appVersion"] = "changed"
    assert recovery.validate_envelope(envelope) == envelope


def test_nonce_and_ciphertext_are_decoded_once_within_decrypt():
    _, sidecar = _pair()
    calls = []
    original = recovery._b64_decode

    def decode(value, code):
        calls.append(code)
        return original(value, code)

    with mock.patch.object(recovery, "_b64_decode", side_effect=decode):
        recovery.decrypt_envelope(sidecar["recovery"], KEY, key_identifier=KEY_ID)
    assert calls.count("recovery_nonce_invalid") == 1
    assert calls.count("recovery_ciphertext_invalid") == 1


@pytest.mark.parametrize("field,text,error,code", [
    ("nonce", "%", recovery.RecoveryBundleError, "recovery_nonce_invalid"),
    ("ciphertext", "%", recovery.RecoveryBundleError, "recovery_ciphertext_invalid"),
    ("nonce", "broken", ValueError, "Nonce must be between 8 and 128 bytes"),
    ("ciphertext", "broken", recovery.RecoveryBundleError, "recovery_authentication_failed"),
])
def test_copy_time_mutation_still_fails(field, text, error, code):
    _, sidecar = _pair()
    original = copy.deepcopy

    def changed(value, *args, **kwargs):
        result = original(value, *args, **kwargs)
        if isinstance(result, dict) and result.get("schemaVersion") == recovery.SCHEMA:
            result[field] = text
        return result

    with mock.patch.object(recovery.copy, "deepcopy", side_effect=changed):
        with pytest.raises(error, match=code):
            recovery.decrypt_envelope(sidecar["recovery"], KEY, key_identifier=KEY_ID)


def test_save_releases_temporary_checkpoint_and_payload(tmp_path):
    class Tracked(dict):
        pass

    checkpoints, payloads, observations = [], [], []
    real_load = storage.load_checkpoint
    real_build = recovery.build_payload
    real_sidecar = recovery.build_sidecar

    def loading(*args, **kwargs):
        value = real_load(*args, **kwargs)
        if inspect.currentframe().f_back.f_code.co_name == "_persist_remote_recovery_sidecar_once":
            value = Tracked(value)
            checkpoints.append(weakref.ref(value))
        return value

    def building(*args, **kwargs):
        value = Tracked(real_build(*args, **kwargs))
        payloads.append(weakref.ref(value))
        return value

    producers = []

    def sidecar(*args, **kwargs):
        if inspect.currentframe().f_back.f_code.co_name == "_persist_remote_recovery_sidecar_once":
            observations.append((sum(r() is not None for r in checkpoints),
                                 sum(r() is not None for r in payloads)))
            # Name the producer: a third sidecar means a background thread
            # (never this test) persisted concurrently; report which one.
            import threading
            producers.append((threading.current_thread().name, [
                frame.function for frame in inspect.stack()[2:9]]))
        return real_sidecar(*args, **kwargs)

    with scanner_storage(str(tmp_path)) as paths, _key_environment(configured=True), \
            mock.patch.object(scanner, "_CHECKPOINT_V2_STAGE1_ENABLED", False):
        _reset_recovery_targets()
        _append_verified_cycle(paths, sequence=1)
        _activate_clean_legacy_nonce_authority(paths)
        with mock.patch.object(storage, "load_checkpoint", loading), \
                mock.patch.object(recovery, "build_payload", building), \
                mock.patch.object(recovery, "build_sidecar", sidecar):
            assert scanner._osint_persist()["verified"] is True
            _advance_nonce_floor_to_33()
            _append_verified_cycle(paths, sequence=2)
            assert scanner._osint_persist()["verified"] is True
        canonical_checkpoint = storage.load_checkpoint(paths["checkpoint"], require_seal=True)
        scanner._verify_local_recovery_sidecar(
            canonical_checkpoint, allow_legacy_migration=False)
    assert observations == [(0, 0), (0, 0)], producers
    assert all(ref() is None for ref in checkpoints + payloads)
