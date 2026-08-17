"""ARGUS V12.2.6 — 運用実証(耐久マップ/releaseSafety表示)の恒久ガード。"""
import os

import scanner

ROOT = os.path.dirname(__file__)


def test_operational_state_doc_exists():
    src = open(os.path.join(ROOT, "docs", "ARGUS_OPERATIONAL_STATE.md"),
               encoding="utf-8").read()
    for k in ("write-through", "corrupt_ignored", "local/vault only",
              "サーバ非保存"):
        assert k in src, k


def test_dq_release_safety_honest():
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/data-quality").get_json() or {}
        rs = d.get("releaseSafety") or {}
        assert "owner-pending" in str(rs.get("ownerSettingsPending"))
        assert "CI artifact" in rs.get("manifestSource", "")
        body = str(d)
        for banned in ("passphrase", "hmac", "OPENAI_API_KEY", "quantity"):
            assert banned not in body
