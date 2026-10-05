"""合成銘柄だけで競合・非公開保存・保存失敗を確認する。"""
import base64
import copy
import json
import hashlib
from urllib.parse import urlsplit

import pytest
import argus_watchlist_sync as W
from argus_private_membership import PrivateMembershipStore, MembershipConflict, MembershipStoreError

JP = {"symbol": "1234", "market": "JP", "ownerState": "protected", "priority": "high"}
US = {"symbol": "TEST", "market": "US"}
OLD = "a" * 40
NEW = "b" * 40
BLOB = "c" * 40
TREE = "d" * 40


def snapshot(items):
    ok, cleaned, _ = W.validate_sync_payload({"items": items})
    assert ok
    return W.build_membership_snapshot(cleaned["items"], effective_date="2026-10-05",
                                      generated_at="2026-10-05T10:00:00Z", snapshot_id="synthetic")


def blob_version(value):
    raw = json.dumps(value, ensure_ascii=False, indent=2).encode()
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


class Response:
    def __init__(self, code, body):
        self.status_code = code
        self.body = body
    def json(self):
        return self.body


class Git:
    def __init__(self, initial=None, daily=None, race=False, error=None):
        self.files = {}
        if initial is not None:
            self.files["membership/latest.json"] = initial
        if daily is not None:
            self.files["membership/2026-10-05.json"] = daily
        self.old_files = copy.deepcopy(self.files)
        self.staged = None
        self.race = race
        self.error = error
        self.calls = []
        self.public = False
        self.readback_corrupt = False

    def get(self, url, **kwargs):
        path = urlsplit(url).path.removeprefix("/repos/example/private")
        self.calls.append(("get", path))
        if self.error:
            return Response(self.error, {"message": "private response must never appear"})
        if not path:
            return Response(200, {"private": not self.public, "default_branch": "main"})
        if path == "/git/ref/heads/main":
            return Response(200, {"object": {"sha": OLD}})
        if path == "/git/commits/" + OLD:
            return Response(200, {"tree": {"sha": TREE}})
        if path.startswith("/contents/"):
            name = path.removeprefix("/contents/")
            files = self.files if urlsplit(url).query == "ref=" + NEW else self.old_files
            if name not in files:
                return Response(404, {})
            value = {} if self.readback_corrupt and files is self.files else files[name]
            return Response(200, {"sha": blob_version(value) if files is self.files else BLOB, "content": base64.b64encode(json.dumps(value).encode()).decode()})
        raise AssertionError(path)

    def post(self, url, **kwargs):
        path = urlsplit(url).path.removeprefix("/repos/example/private")
        body = kwargs["json"]
        self.calls.append(("post", path))
        if path == "/git/trees":
            assert body["base_tree"] == TREE
            self.staged = copy.deepcopy(self.files)
            for entry in body["tree"]:
                self.staged[entry["path"]] = json.loads(entry["content"])
            return Response(201, {"sha": TREE})
        if path == "/git/commits":
            assert body["parents"] == [OLD]
            return Response(201, {"sha": NEW})
        raise AssertionError(path)

    def patch(self, url, **kwargs):
        assert kwargs["json"] == {"sha": NEW, "force": False}
        self.calls.append(("patch", "/git/refs/heads/main"))
        if self.race:
            return Response(422, {"message": "competing private writer"})
        self.files = self.staged
        return Response(200, {"object": {"sha": NEW}})


def store(git):
    return PrivateMembershipStore("example/private", {"Authorization": "synthetic"}, git)


def test_legacy_old_and_empty_devices_cannot_remove_remote_members_or_flags():
    for local in ([], [US], [{**JP, "enabled": False, "ownerState": "watch"}]):
        items, mode = W.apply_membership_changes({"items": local}, [JP, US])
        assert not mode
        assert {(x["market"], x["symbol"]) for x in items} == {("JP", "1234"), ("US", "TEST")}
        preserved = next(x for x in items if x["symbol"] == "1234")
        assert preserved["ownerState"] == "protected" and preserved["priority"] == "high"


def test_explicit_removal_only_removes_its_identity_and_add_is_idempotent():
    payload = {"syncMode": W.CHANGE_SCHEMA_VERSION, "changes": [
        {"action": "remove", "item": JP}, {"action": "add", "item": US}]}
    result, mode = W.apply_membership_changes(payload, [JP, US])
    again, _ = W.apply_membership_changes(payload, result)
    assert mode and again == result and result[0]["symbol"] == "TEST"


def test_case_insensitive_identity_does_not_duplicate_existing_flags():
    items, _ = W.apply_membership_changes({"items": [{**US, "symbol": "test"}]}, [US])
    assert len(items) == 1


@pytest.mark.parametrize("bad", [None, 123, {}, {"market": "JP", "symbol": 1234}])
def test_malformed_change_item_rejected(bad):
    with pytest.raises(ValueError):
        W.apply_membership_changes({"syncMode": W.CHANGE_SCHEMA_VERSION,
                                    "changes": [{"action": "add", "item": bad}]}, [])


@pytest.mark.parametrize("field", sorted(W.FORBIDDEN_FIELDS))
def test_forbidden_fields_rejected_inside_changes(field):
    with pytest.raises(ValueError):
        W.apply_membership_changes({"syncMode": W.CHANGE_SCHEMA_VERSION,
            "changes": [{"action": "add", "item": US, "extra": {field: 123}}]}, [])


def test_first_write_publishes_daily_and_latest_in_same_commit_and_reads_back():
    git = Git()
    snap = snapshot([JP])
    assert store(git).save(snap, "absent")["version"] == blob_version(snap)
    assert git.files == {"membership/latest.json": snap, "membership/2026-10-05.json": snap}
    assert sum(method == "patch" for method, _ in git.calls) == 1


def test_daily_is_immutable_even_when_latest_changes():
    first = snapshot([JP])
    git = Git(first, first)
    store(git).save(snapshot([JP, US]), BLOB)
    assert git.files["membership/2026-10-05.json"] == first
    assert len(git.files["membership/latest.json"]["members"]) == 2


def test_newer_remote_version_rejects_before_creating_objects():
    git = Git(snapshot([JP]))
    with pytest.raises(MembershipConflict):
        store(git).save(snapshot([US]), "absent")
    assert all(method == "get" for method, _ in git.calls)


def test_branch_race_does_not_publish_daily_or_latest():
    git = Git(race=True)
    with pytest.raises(MembershipConflict):
        store(git).save(snapshot([JP]), "absent")
    assert git.files == {}


@pytest.mark.parametrize("status", [401, 403, 404, 429, 502])
def test_read_failure_is_not_empty_and_never_exposes_private_response(status):
    with pytest.raises(MembershipStoreError) as failure:
        store(Git(error=status)).read_latest()
    assert str(failure.value) == "private_store_http_" + str(status)


def test_public_repository_is_rejected_before_reading_or_writing_members():
    git = Git(); git.public = True
    with pytest.raises(MembershipStoreError, match="private_store_required"):
        store(git).save(snapshot([JP]), "absent")
    assert git.calls == [("get", "")]


def test_readback_failure_never_acknowledges_success():
    git = Git(); git.readback_corrupt = True
    with pytest.raises(MembershipStoreError):
        store(git).save(snapshot([JP]), "absent")


def test_route_distinguishes_unavailable_store_from_empty(monkeypatch):
    import scanner
    monkeypatch.setenv("ARGUS_OWNER_SYNC_TOKEN", "synthetic")
    monkeypatch.setattr(scanner, "_layer2b_store_configured", lambda: True)
    monkeypatch.setattr(scanner, "_layer2b_private_store", lambda: store(Git(error=403)))
    response = scanner.app.test_client().post("/api/argus/calibration/watchlist-membership",
                                             json={"ownerToken": "synthetic"})
    assert response.status_code == 503 and response.json["status"] == "failed"
    assert "private response" not in response.get_data(as_text=True)


def test_route_rejects_stale_revision_without_publishing_or_updating_cache(monkeypatch):
    import scanner
    git = Git(snapshot([JP]))
    monkeypatch.setenv("ARGUS_OWNER_SYNC_TOKEN", "synthetic")
    monkeypatch.setattr(scanner, "_layer2b_store_configured", lambda: True)
    monkeypatch.setattr(scanner, "_layer2b_private_store", lambda: store(git))
    before = copy.deepcopy(scanner._OWNER_SYMS_CACHE)
    response = scanner.app.test_client().post("/api/argus/calibration/watchlist-sync", json={
        "ownerToken": "synthetic", "syncMode": W.CHANGE_SCHEMA_VERSION,
        "batchId": "12345678-1234-4234-8234-123456789abc", "baseVersion": "absent", "changes": [{"action": "remove", "item": JP}]})
    assert response.status_code == 409
    assert scanner._OWNER_SYMS_CACHE == before
    assert git.files["membership/latest.json"]["members"][0]["symbol"] == "1234"


def test_route_only_updates_analysis_and_push_caches_after_verified_write(monkeypatch):
    import scanner
    git = Git(snapshot([JP, US]))
    monkeypatch.setenv("ARGUS_OWNER_SYNC_TOKEN", "synthetic")
    monkeypatch.setattr(scanner, "_layer2b_store_configured", lambda: True)
    monkeypatch.setattr(scanner, "_layer2b_private_store", lambda: store(git))
    monkeypatch.setattr(scanner, "_OWNER_SYMS_CACHE", {"syms": {"1234": {}, "TEST": {}}, "ts": 0})
    monkeypatch.setattr(scanner, "_OWNER_OVERVIEW_MEMBERSHIP", {})
    monkeypatch.setattr(scanner, "_LAYER2B_STATE", {})
    response = scanner.app.test_client().post("/api/argus/calibration/watchlist-sync", json={
        "ownerToken": "synthetic", "syncMode": W.CHANGE_SCHEMA_VERSION,
        "batchId": "12345678-1234-4234-8234-123456789abc", "baseVersion": BLOB, "changes": [{"action": "remove", "item": JP}]})
    assert response.status_code == 200 and response.json["status"] == "synced"
    assert response.json["version"] == blob_version(git.files["membership/latest.json"])
    assert set(scanner._OWNER_SYMS_CACHE["syms"]) == {"TEST"}
    assert len(scanner._OWNER_OVERVIEW_MEMBERSHIP["members"]) == 1


def test_failed_write_does_not_stamp_success_hash_or_update_cache(monkeypatch):
    import scanner
    git = Git(snapshot([JP])); git.readback_corrupt = True
    monkeypatch.setenv("ARGUS_OWNER_SYNC_TOKEN", "synthetic")
    monkeypatch.setattr(scanner, "_layer2b_store_configured", lambda: True)
    monkeypatch.setattr(scanner, "_layer2b_private_store", lambda: store(git))
    monkeypatch.setattr(scanner, "_LAYER2B_STATE", {"lastHash": "previous", "symbolCount": 9})
    before = copy.deepcopy(scanner._OWNER_SYMS_CACHE)
    response = scanner.app.test_client().post("/api/argus/calibration/watchlist-sync", json={
        "ownerToken": "synthetic", "syncMode": W.CHANGE_SCHEMA_VERSION,
        "batchId": "12345678-1234-4234-8234-123456789abc", "baseVersion": BLOB, "changes": [{"action": "add", "item": US}]})
    assert response.json["ok"] is False and response.json["status"] == "failed"
    assert scanner._LAYER2B_STATE["lastHash"] == "previous"
    assert scanner._OWNER_SYMS_CACHE == before


@pytest.mark.parametrize("batch", [None, "bad", "../../latest", 123, "A" * 36])
def test_invalid_receipt_identity_cannot_address_private_paths(batch):
    with pytest.raises(MembershipStoreError, match="membership_batch_invalid"):
        PrivateMembershipStore.receipt_path(batch)


def test_receipt_and_membership_are_published_atomically():
    git = Git()
    batch = "12345678-1234-4234-8234-123456789abc"
    snap = snapshot([JP])
    store(git).save(snap, "absent", batch_id=batch, digest="synthetic-digest")
    receipt = git.files[PrivateMembershipStore.receipt_path(batch)]
    assert receipt["changesDigest"] == "synthetic-digest"
    assert len(git.files) == 3
    assert not any(field in json.dumps(receipt) for field in ("symbol", "quantity", "ownerToken"))


def test_receipt_makes_uncertain_retry_idempotent_after_reregistration(monkeypatch):
    import scanner
    batch = "12345678-1234-4234-8234-123456789abc"
    git = Git(snapshot([JP]))  # Another device has re-added the item.
    git.old_files[PrivateMembershipStore.receipt_path(batch)] = {
        "batchId": batch, "changesDigest": __import__("hashlib").sha256(json.dumps([
            {"action": "remove", "item": JP}], sort_keys=True,
            ensure_ascii=False, separators=(",", ":")).encode()).hexdigest(),
        "version": BLOB}
    monkeypatch.setenv("ARGUS_OWNER_SYNC_TOKEN", "synthetic")
    monkeypatch.setattr(scanner, "_layer2b_store_configured", lambda: True)
    monkeypatch.setattr(scanner, "_layer2b_private_store", lambda: store(git))
    monkeypatch.setattr(scanner, "_OWNER_SYMS_CACHE", {"syms": {}, "ts": 0})
    monkeypatch.setattr(scanner, "_OWNER_OVERVIEW_MEMBERSHIP", {})
    monkeypatch.setattr(scanner, "_LAYER2B_STATE", {})
    response = scanner.app.test_client().post("/api/argus/calibration/watchlist-sync", json={
        "ownerToken": "synthetic", "syncMode": W.CHANGE_SCHEMA_VERSION,
        "batchId": batch, "baseVersion": "absent", "changes": [{"action": "remove", "item": JP}]})
    assert response.json["alreadyApplied"] is True
    assert set(scanner._OWNER_SYMS_CACHE["syms"]) == {"1234"}
    assert scanner._OWNER_SYMS_CACHE["syms"]["1234"]["ownerState"] == "protected"
    assert git.files["membership/latest.json"]["members"][0]["symbol"] == "1234"
    assert all(method == "get" for method, _ in git.calls)



def test_backend_busy_rejects_without_consuming_a_batch(monkeypatch):
    import scanner
    monkeypatch.setenv("ARGUS_OWNER_SYNC_TOKEN", "synthetic")
    scanner._LAYER2B_SYNC_LOCK.acquire()
    try:
        response = scanner.app.test_client().post("/api/argus/calibration/watchlist-sync",
            json={"ownerToken": "synthetic", "items": [JP]})
        assert response.status_code == 409 and response.json["error"] == "membership_sync_busy"
    finally:
        scanner._LAYER2B_SYNC_LOCK.release()
