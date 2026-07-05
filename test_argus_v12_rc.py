"""V12.0.0 Pro RC — cross-cutting integration/consistency/leak guards.

新機能ではなく「全域の規律」を恒久固定するテスト:
  - 公開エンドポイント全数: 漏洩ゼロ・執行語ゼロ・確率断定ゼロ・JP稼働主張ゼロ
  - 用語統一: Py/TS両エンジンの日本語ラベル一致
  - FEソース: 旧Backup参照ゼロ・ナビにBackup/Data Quality
"""
import json
import os
import re

import scanner
import argus_trade_plan
import argus_supply_demand
import argus_data_quality

WEB = os.path.join(os.path.dirname(__file__), "web", "src")

PUBLIC_GETS = [
    "/api/argus/bridge/status",
    "/api/argus/data-quality", "/api/argus/data-quality/status",
    "/api/argus/review-pack/status", "/api/argus/fire-core/status",
    "/api/argus/portfolio-strategy/status",
    "/api/argus/position-plans", "/api/argus/position-plans/status",
    "/api/argus/scenarios", "/api/argus/scenarios/status",
    "/api/argus/backup-safety/status", "/api/argus/learning-review/status",
    "/api/argus/notifications/status", "/api/argus/session-brief/status",
    "/api/argus/action-priority", "/api/argus/action-priority/status",
    "/api/argus/supply-demand/status", "/api/argus/decision-quality/status",
    "/api/argus/position-exposure/status", "/api/argus/flow-attribution/status",
    "/api/argus/institutional-intel/status", "/api/argus/pro-handoff",
]

EXEC_WORDS = ("今すぐ買", "今すぐ売", "buy now", "sell now", "place order",
              "成行で買", "全力買い", "注文を出し")
SECRET_WORDS = ("vaultPass", "passphrase=", "X-ARGUS-ADMIN-TOKEN", "login_pwd",
                "Bearer ", "HMAC-SHA", "OPEND_PWD", "moomoo_pwd")
PROB_PAT = re.compile(r"\d{1,3}\s*[%％]の確率|の確率で(上|下)がる|到達年|達成確率|リタイア確率")
JP_RT_CLAIM_PAT = re.compile(r"JPリアルタイム(が|は)?(稼働|正常|有効|動作)")


class _Boom:
    def __getattr__(self, name):
        raise AssertionError(f"network call attempted via requests.{name}")


def test_all_public_endpoints_clean(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())
    with scanner.app.test_client() as c:
        for path in PUBLIC_GETS:
            r = c.get(path)
            assert r.status_code == 200, path
            d = r.get_json()
            blob = json.dumps(d, ensure_ascii=False)
            low = blob.lower()
            for w in EXEC_WORDS:
                assert w.lower() not in low, (path, w)
            for w in SECRET_WORDS:
                assert w not in blob, (path, w)
            assert not PROB_PAT.search(blob), (path, "probability claim")
            assert not JP_RT_CLAIM_PAT.search(blob), (path, "JP realtime claim")
            assert scanner.argus_portfolio_sync.contains_sensitive(d) == [], path


def test_terminology_parity_py_ts():
    """標準用語がPy/TS両エンジンに存在(片側のリネーム事故を検知)。"""
    checks = [
        ("web/src/domain/positionPlan.ts", ["買うなら押し目限定", "追いかけ買い注意",
                                            "一部利確を検討する局面", "リスク確認が先", "判定保留"]),
        ("web/src/domain/actionPriority.ts", ["買うなら押し目限定", "追いかけ買い注意",
                                              "イベント待ち"]),
        ("web/src/domain/portfolioStrategy.ts", ["戦術枠", "サテライト", "ヘッジ"]),
        ("web/src/lib/fireCore.ts", ["本丸資産"]),
    ]
    for rel, words in checks:
        src = open(os.path.join(os.path.dirname(__file__), rel), encoding="utf-8").read()
        for w in words:
            assert w in src, (rel, w)
    for w in ("買うなら押し目限定", "追いかけ買い注意", "一部利確を検討する局面",
              "リスク確認が先", "判定保留"):
        assert w in list(argus_trade_plan.STANCE_JA.values()), w
    assert "改善中だが信用買い残はまだ重い" in argus_supply_demand.CONDITION_JA.values() \
        or any("改善中だが" in v for v in argus_supply_demand.CONDITION_JA.values())
    assert len(argus_data_quality.EXPECTED_DISABLED) == 3


def test_no_stale_backup_references_in_frontend():
    """Backupページ移設後の旧参照(恒久ガード)。"""
    banned = ("Guideの「バックアップと同期」", "Core Portfolio → BACKUP SAFETY",
              "Core Portfolio→BACKUP SAFETY")
    for root, _dirs, files in os.walk(WEB):
        for fn in files:
            if not fn.endswith((".ts", ".tsx")):
                continue
            p = os.path.join(root, fn)
            src = open(p, encoding="utf-8").read()
            for b in banned:
                assert b not in src, (p, b)


def test_frontend_no_execution_wording():
    """FEの表示文言にも執行語なし(コメント/禁止リスト定義は除外)。"""
    for root, _dirs, files in os.walk(WEB):
        for fn in files:
            if not fn.endswith((".ts", ".tsx")):
                continue
            p = os.path.join(root, fn)
            for i, line in enumerate(open(p, encoding="utf-8"), 1):
                s = line.strip()
                if s.startswith("//") or s.startswith("*") or s.startswith("/*"):
                    continue
                if "FORBIDDEN" in line or "banned" in line or "禁止" in line \
                        or "出さない" in line or "含めない" in line or "ではない" in line:
                    continue
                for w in ("今すぐ買", "今すぐ売", "成行で買", "全力買い"):
                    assert w not in line, (p, i, w)


def test_mobile_nav_reaches_backup_and_data_quality():
    src = open(os.path.join(WEB, "components", "NavRail.tsx"), encoding="utf-8").read()
    assert "Backup" in src and "Data Quality" in src
    app = open(os.path.join(WEB, "App.tsx"), encoding="utf-8").read()
    assert "'backup'" in app and "'quality'" in app


def test_unknown_never_positive():
    """unknown/stale入力が好条件として扱われないことの回帰ガード。"""
    plan = argus_trade_plan.build_plan("5803", "JP", {
        "isHeld": False, "assetName": "T", "sdRank": None, "flowClass": None,
        "scenarioDominant": None, "marketOpen": True}, "2026-07-06T09:00:00+09:00")
    assert plan["planType"] == "unknown"
    assert plan["currentStance"] == "unknown"          # 好条件に化けない
    assert argus_data_quality.freshness_bucket(None, "daily") == "unknown"
