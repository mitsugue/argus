# -*- coding: utf-8 -*-
"""ARGUS Dual-Plane — v12.2.1 Phase 0(純・stdlibのみ)。

二面実行アーキテクチャ:
- Research Plane(サーバ/cron・24x365) — 公開安全データのみ。保有/数量/取得単価/
  PnL/FIRE/私的メモは構造的に知らない。
- Private Decision Plane(端末PWA/将来のオーナー管理worker) — 保有文脈はここだけ。
偽りの24x365主張の禁止: private workerが実在・検証されるまで
「保有判断も24時間稼働」とは言わない。
"""
from typing import Any, Dict

EXECUTION_PLANES = ("research_server", "private_client", "private_worker",
                    "public_redacted")
PRIVATE_AGENT_STATUSES = ("client_only", "private_worker_not_configured",
                          "private_worker_ready", "private_worker_degraded",
                          "unknown")

RESEARCH_24X365_JA = ("市場・ニュース調査は24時間稼働しています。"
                      "保有情報を含む個人判断は、端末でARGUSを開いた時に更新されます。")
FORBIDDEN_CLAIM_JA = "保有判断も24時間365日稼働中"


def dual_plane_status(*, private_worker_configured: bool = False,
                      private_worker_verified: bool = False,
                      scheduler_alive: bool = True) -> Dict[str, Any]:
    """二面ステータス。private worker未検証なら正直にclient_only。"""
    if private_worker_configured and private_worker_verified:
        pstatus = "private_worker_ready"
    elif private_worker_configured:
        pstatus = "private_worker_degraded"
    else:
        pstatus = "client_only"
    return {
        "researchPlane": {
            "plane": "research_server",
            "active24x365": bool(scheduler_alive),
            "mayAccessPrivate": False,
            "ownerReadableJa": ("リサーチ面: サーバ/cronで継続稼働"
                                if scheduler_alive else
                                "リサーチ面: スケジューラ停止の可能性"),
        },
        "privateDecisionPlane": {
            "plane": ("private_worker" if pstatus == "private_worker_ready"
                      else "private_client"),
            "status": pstatus,
            "active24x365": pstatus == "private_worker_ready",
            "ownerReadableJa": (RESEARCH_24X365_JA
                                if pstatus != "private_worker_ready" else
                                "私的判断面: オーナー管理workerが検証済みで稼働"),
        },
        "honestClaimJa": RESEARCH_24X365_JA,
    }


def plane_may_access_private(plane: str) -> bool:
    return plane in ("private_client", "private_worker")
