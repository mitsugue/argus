"""Conditional writes to the existing private membership store.

Daily first-save and latest are published in one Git commit. Branch advancement
is non-force: another writer makes the whole transaction conflict, never a
partly published daily record. Errors contain status classes, not private bodies.
"""
from __future__ import annotations

import base64
import json
import hashlib
import uuid
import re
import time
from urllib.parse import quote

ABSENT_VERSION = "absent"


class MembershipStoreError(RuntimeError):
    pass


class MembershipConflict(MembershipStoreError):
    pass


class PrivateMembershipStore:
    def __init__(self, repo, headers, http, *, clock=time.monotonic):
        self.base = "https://api.github.com/repos/" + repo
        self.headers = headers
        self.http = http
        self.clock = clock
        self.deadline = clock() + 55

    def _request(self, method, path, *, missing=False, conflict=False, **kwargs):
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            raise MembershipStoreError("private_store_timeout")
        try:
            response = getattr(self.http, method)(self.base + path,
                headers=self.headers, timeout=min(12, remaining), **kwargs)
        except Exception:
            raise MembershipStoreError("private_store_unreachable") from None
        if missing and response.status_code == 404:
            return None
        if conflict and response.status_code in (409, 422):
            raise MembershipConflict("membership_changed")
        if response.status_code not in (200, 201):
            raise MembershipStoreError("private_store_http_" + str(response.status_code))
        try:
            data = response.json()
        except Exception:
            raise MembershipStoreError("private_store_invalid_response") from None
        if not isinstance(data, dict):
            raise MembershipStoreError("private_store_invalid_response")
        return data

    def _repository(self):
        repo = self._request("get", "")
        if repo.get("private") is not True:
            raise MembershipStoreError("private_store_required")
        branch = repo.get("default_branch")
        if not isinstance(branch, str) or not branch:
            raise MembershipStoreError("private_store_branch_missing")
        return quote(branch, safe="")

    def _file(self, path, ref=None, *, membership=True):
        suffix = "?ref=" + quote(ref, safe="") if ref else ""
        entry = self._request("get", "/contents/" + path + suffix, missing=True)
        if entry is None:
            return None, ABSENT_VERSION
        version = entry.get("sha")
        if not isinstance(version, str) or not re.fullmatch(r"[0-9a-f]{40}", version):
            raise MembershipStoreError("private_store_version_invalid")
        try:
            content = json.loads(base64.b64decode(entry["content"], validate=False).decode("utf-8"))
        except Exception:
            raise MembershipStoreError("private_store_content_invalid") from None
        if not isinstance(content, dict) or (membership and not isinstance(content.get("members"), list)):
            raise MembershipStoreError("private_store_membership_invalid")
        return content, version

    def read_latest(self):
        self._repository()  # Never mistake an inaccessible repository for empty.
        return self._file("membership/latest.json")

    @staticmethod
    def receipt_path(batch_id):
        try:
            if str(uuid.UUID(batch_id)) != batch_id:
                raise ValueError()
        except (ValueError, AttributeError, TypeError):
            raise MembershipStoreError("membership_batch_invalid") from None
        return "membership/receipts/" + batch_id + ".json"

    def read_receipt(self, batch_id, digest, ref=None):
        receipt, _ = self._file(self.receipt_path(batch_id), ref, membership=False)
        if receipt is not None:
            if receipt.get("batchId") != batch_id or not isinstance(receipt.get("version"), str) or not re.fullmatch(r"[0-9a-f]{40}", receipt["version"]):
                raise MembershipStoreError("membership_receipt_invalid")
            if receipt.get("changesDigest") != digest:
                raise MembershipStoreError("membership_batch_reused")
        return receipt

    def save(self, snapshot, expected_version, *, batch_id=None, digest=None):
        branch = self._repository()
        ref = self._request("get", "/git/ref/heads/" + branch)
        parent = ref.get("object", {}).get("sha")
        if not isinstance(parent, str) or not re.fullmatch(r"[0-9a-f]{40}", parent):
            raise MembershipStoreError("private_store_head_invalid")
        if batch_id:
            receipt = self.read_receipt(batch_id, digest, parent)
            if receipt is not None:
                if receipt.get("changesDigest") != digest:
                    raise MembershipStoreError("membership_batch_reused")
                return {"version": receipt["version"], "alreadyApplied": True}
        current, version = self._file("membership/latest.json", parent)
        if version != expected_version:
            raise MembershipConflict("membership_changed")
        eff = snapshot.get("effectiveFrom", "")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", eff):
            raise MembershipStoreError("membership_day_invalid")
        # This file is the first save of the day, never a replacement of history.
        daily, _ = self._file("membership/" + eff + ".json", parent)
        parent_commit = self._request("get", "/git/commits/" + parent)
        tree_sha = parent_commit.get("tree", {}).get("sha")
        if not isinstance(tree_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", tree_sha):
            raise MembershipStoreError("private_store_tree_invalid")
        content = json.dumps(snapshot, ensure_ascii=False, indent=2)
        entry = {"mode": "100644", "type": "blob", "content": content}
        entries = [{**entry, "path": "membership/latest.json"}]
        if daily is None:
            entries.append({**entry, "path": "membership/" + eff + ".json"})
        if batch_id:
            raw = content.encode("utf-8")
            blob_version = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
            receipt = {"batchId": batch_id, "changesDigest": digest, "version": blob_version,
                       "savedAt": snapshot["generatedAt"]}
            entries.append({**entry, "path": self.receipt_path(batch_id),
                            "content": json.dumps(receipt, ensure_ascii=False, indent=2)})
        tree = self._request("post", "/git/trees", json={"base_tree": tree_sha, "tree": entries})
        commit = self._request("post", "/git/commits", json={
            "message": "登録銘柄の変更を保存 " + eff, "tree": tree["sha"], "parents": [parent]})
        sha = commit.get("sha")
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise MembershipStoreError("private_store_commit_invalid")
        self._request("patch", "/git/refs/heads/" + branch,
                      conflict=True, json={"sha": sha, "force": False})
        saved, saved_version = self._file("membership/latest.json", sha)
        if saved != snapshot:
            raise MembershipStoreError("membership_readback_mismatch")
        if batch_id:
            verified_receipt = self.read_receipt(batch_id, digest, sha)
            if verified_receipt is None or verified_receipt["version"] != saved_version:
                raise MembershipStoreError("membership_receipt_readback_mismatch")
        return {"version": saved_version, "alreadyApplied": False}
