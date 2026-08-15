"""Deterministic Flask route trust-domain catalog for Recovery Phase A PR B.

Every Flask rule/method contract is declared literally below. The contract
suite compares this catalog with app.url_map so a route addition, deletion or
method change requires an explicit trust-boundary review.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable


TRUST_DOMAINS = frozenset({
    "PUBLIC", "AUTH_OPERATIONAL", "OWNER_SYNC", "RECOVERY_PROOF",
})
AUTH_POLICIES = frozenset({
    "NONE", "ADMIN_TOKEN", "OWNER_SYNC_OR_ADMIN",
    "OPTIONAL_ADMIN_VIEW", "LEGACY_PUBLIC_PROOF",
})


@dataclass(frozen=True)
class RouteCatalogEntry:
    route: str
    methods: tuple[str, ...]
    endpoint: str
    trustDomain: str
    authenticationPolicy: str
    mutatesState: bool
    responseDtoFamily: str
    consumerCategory: str


@dataclass(frozen=True)
class CacheOnlyConsumerContract:
    route: str
    consumers: tuple[str, ...]
    refreshAuthority: str


# Narrow machine-readable contract for public status surfaces whose browser reads
# must never initiate provider/ledger traffic.  Paths are repository-relative and
# intentionally literal so consumer drift is reviewed alongside route drift.
PUBLIC_CACHE_ONLY_CONSUMERS = (
    CacheOnlyConsumerContract(
        "/api/argus/action-labels",
        ("web/src/hooks/useActionLabels.ts",),
        "background judgment, prediction-ledger, or scheduled market acquisition",
    ),
    CacheOnlyConsumerContract(
        "/api/argus/ai-judgment",
        ("web/src/hooks/useAIJudgment.ts",),
        "process bootstrap or authenticated/background AI execution",
    ),
    CacheOnlyConsumerContract(
        "/api/argus/calibration/v4/status",
        ("web/src/hooks/useArgusProStatus.ts",),
        "authenticated/background calibration ledger acquisition",
    ),
    CacheOnlyConsumerContract(
        "/api/argus/decision-value/status",
        ("web/src/hooks/useArgusProStatus.ts",
         "web/src/components/guide/DecisionValueOpsCard.tsx"),
        "authenticated decision-value shadow run or background acquisition",
    ),
    CacheOnlyConsumerContract(
        "/api/argus/event-backbone-status",
        ("web/src/hooks/useEventsActive.ts",),
        "background event snapshot publication and restore",
    ),
    CacheOnlyConsumerContract(
        "/api/argus/events-active",
        ("web/src/hooks/useEventsActive.ts",),
        "process bootstrap or background event snapshot restore",
    ),
    CacheOnlyConsumerContract(
        "/api/argus/integrations",
        ("web/src/hooks/useIntegrations.ts",),
        "authenticated/background integration acquisition",
    ),
    CacheOnlyConsumerContract(
        "/api/argus/japan-watchlist",
        ("web/src/hooks/useJapanWatchlist.ts",),
        "owner-synced Layer-2B membership and background market acquisition",
    ),
    CacheOnlyConsumerContract(
        "/api/argus/learning-memory/status",
        ("web/src/components/guide/DecisionSpineCard.tsx",),
        "admin learning-memory build/restore or background job",
    ),
    CacheOnlyConsumerContract(
        "/api/argus/market-depth",
        ("web/src/hooks/useMarketDepth.ts",),
        "POST /api/argus/ai-judgment/run or scheduled AI judgment refresh",
    ),
    CacheOnlyConsumerContract(
        "/api/argus/market-depth/proof",
        ("web/src/hooks/useArgusProStatus.ts",),
        "POST /api/argus/ai-judgment/run or scheduled AI judgment refresh",
    ),
    CacheOnlyConsumerContract(
        "/api/argus/provider-diagnostics/public",
        ("web/src/hooks/usePaidSources.ts",),
        "GET /api/argus/admin/provider-diagnostics",
    ),
    CacheOnlyConsumerContract(
        "/api/argus/runtime-manifest",
        ("web/src/routes/AIReview.tsx",),
        "authenticated/background status builders",
    ),
    CacheOnlyConsumerContract(
        "/api/argus/source-coverage",
        ("web/src/hooks/useArgusProStatus.ts",),
        "GET /api/argus/admin/provider-diagnostics and scheduled AI judgment refresh",
    ),
    CacheOnlyConsumerContract(
        "/api/argus/source-registry",
        ("web/src/components/guide/SourceRegistryCard.tsx",),
        "GET /api/argus/admin/provider-diagnostics and scheduled AI judgment refresh",
    ),
    CacheOnlyConsumerContract(
        "/api/argus/system-health",
        ("web/src/hooks/useSystemHealth.ts",),
        "authenticated/background integration acquisition",
    ),
    CacheOnlyConsumerContract(
        "/api/argus/us-watchlist",
        ("web/src/hooks/useUSWatchlist.ts",),
        "background judgment, prediction-ledger, or the authenticated provider path",
    ),
    CacheOnlyConsumerContract(
        "/api/argus/visibility-guard",
        ("web/src/hooks/useVisibilityGuard.ts",),
        "POST /api/argus/ai-judgment/run or scheduled AI judgment refresh",
    ),
)


ROUTE_CATALOG = (
    RouteCatalogEntry("/", ("GET",), "index", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/action-alerts", ("GET",), "api_argus_action_alerts", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/action-labels", ("GET",), "api_argus_action_labels", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/action-priority", ("GET",), "api_argus_action_priority", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/action-priority/status", ("GET",), "api_argus_action_priority_status", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/admin/ai/capability-probe", ("POST",), "api_argus_admin_ai_capability_probe", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/admin/bridge/diagnostic", ("GET",), "api_argus_admin_bridge_diagnostic", "AUTH_OPERATIONAL", "ADMIN_TOKEN", False, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/admin/caos-watchtower/refresh", ("POST",), "api_argus_admin_caos_watchtower_refresh", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/admin/caos/patrol-self-check", ("POST",), "api_argus_admin_caos_patrol_self_check", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/admin/checkpoint-v2/stage1/accept", ("POST",), "api_argus_admin_checkpoint_v2_stage1_accept", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/admin/cost-policy", ("POST",), "api_argus_admin_cost_policy", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/admin/decision-ledger/snapshot", ("POST",), "api_argus_admin_dl_snapshot", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/admin/diagnostics/operational", ("GET",), "api_argus_admin_diagnostics_operational", "AUTH_OPERATIONAL", "ADMIN_TOKEN", False, "OPERATIONAL_DIAGNOSTICS_V1", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/admin/foundation-jobs", ("POST",), "api_argus_admin_foundation_jobs_start", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/admin/foundation-jobs/<job_id>/cancel", ("POST",), "api_argus_admin_foundation_jobs_cancel", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/admin/jquants/index-audit", ("POST",), "api_argus_admin_jquants_index_audit", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/admin/learning-memory/build", ("POST",), "api_argus_admin_learning_memory_build", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/admin/learning-memory/restore", ("POST",), "api_argus_admin_learning_memory_restore", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/admin/macro-event-analysis/generate", ("POST",), "api_argus_admin_macro_generate", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/admin/macro-event-analysis/refresh-market-reaction", ("POST",), "api_argus_admin_macro_refresh_market_reaction", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/admin/macro-event-analysis/refresh-results", ("POST",), "api_argus_admin_macro_refresh_results", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/admin/macro-event-analysis/repair-post-release", ("POST",), "api_argus_admin_macro_repair_post_release", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/admin/market-confirmation/refresh", ("POST",), "api_argus_admin_market_confirmation_refresh", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/admin/market-ledger/import", ("POST",), "api_argus_admin_market_ledger_import", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/admin/market-ledger/jquants-backfill", ("POST",), "api_argus_admin_market_ledger_jquants_backfill", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/admin/memory-attribution", ("GET",), "api_argus_admin_memory_attribution", "AUTH_OPERATIONAL", "ADMIN_TOKEN", False, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/admin/missions/tick", ("POST",), "api_argus_admin_missions_tick", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/admin/mover-causes/explain", ("POST",), "api_argus_admin_mover_causes_explain", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/admin/mover-causes/explain/run", ("POST",), "api_argus_admin_mover_causes_explain_run", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/admin/mover-causes/refresh", ("POST",), "api_argus_admin_mover_causes_refresh", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/admin/mover-causes/refresh-queue/run", ("POST",), "api_argus_admin_mover_causes_queue_run", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/admin/news/translate", ("POST",), "api_argus_admin_news_translate", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/admin/news/translate-visible", ("POST",), "api_argus_admin_news_translate_visible", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/admin/official-events/restore", ("POST",), "api_argus_admin_official_events_restore", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/admin/official-events/snapshot", ("POST",), "api_argus_admin_official_events_snapshot", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/admin/osint/agents-run", ("POST",), "api_argus_admin_osint_agents_run", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/admin/osint/benchmark-run", ("POST",), "api_argus_admin_osint_benchmark_run", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/admin/osint/canary-run", ("POST",), "api_argus_admin_osint_canary_run", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/admin/provider-diagnostics", ("GET",), "api_argus_admin_provider_diagnostics", "AUTH_OPERATIONAL", "ADMIN_TOKEN", False, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/admin/remote-journal/commit-receipt", ("POST",), "api_argus_admin_remote_journal_commit_receipt", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/admin/remote-journal/receipts/<operation_id>", ("GET",), "api_argus_admin_remote_journal_receipt_status", "AUTH_OPERATIONAL", "ADMIN_TOKEN", False, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/admin/remote-journal/recovery-sidecar", ("GET",), "api_argus_admin_remote_journal_recovery_sidecar", "RECOVERY_PROOF", "ADMIN_TOKEN", False, "RECOVERY_PROOF_LEGACY", "SERVER_RECOVERY"),
    RouteCatalogEntry("/api/argus/admin/research-benchmark/dry-run", ("POST",), "api_argus_admin_research_benchmark_dry_run", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/admin/research-benchmark/execute", ("POST",), "api_argus_admin_research_benchmark_execute", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/admin/soak/arm", ("POST",), "api_argus_admin_soak_arm", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/ai-cost", ("GET",), "api_argus_ai_cost", "AUTH_OPERATIONAL", "ADMIN_TOKEN", False, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/ai-judgment", ("GET",), "api_argus_ai_judgment", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/ai-judgment/run", ("POST",), "api_argus_ai_judgment_run", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/ai-provider-status", ("GET",), "api_argus_ai_provider_status", "AUTH_OPERATIONAL", "ADMIN_TOKEN", False, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/ai-provider-status/ping", ("POST",), "api_argus_ai_provider_ping", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/attribution-history", ("GET",), "api_argus_attribution_history", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/backup-safety/status", ("GET",), "api_argus_backup_safety_status", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/bridge/heartbeat", ("POST",), "api_argus_bridge_heartbeat", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/bridge/status", ("GET",), "api_argus_bridge_status", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/buy-candidates", ("GET",), "api_argus_buy_candidates", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/buy-candidates/generate", ("POST",), "api_argus_buy_candidates_generate", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/calibration", ("GET",), "api_argus_calibration", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/calibration/clock", ("GET",), "api_argus_calibration_clock", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/calibration/cohorts", ("GET",), "api_argus_calibration_cohorts", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/calibration/epochs", ("GET",), "api_argus_calibration_epochs", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/calibration/layer2b-run", ("POST",), "api_argus_layer2b_run", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/calibration/layer2b-summary", ("GET", "POST"), "api_argus_layer2b_summary", "OWNER_SYNC", "OWNER_SYNC_OR_ADMIN", True, "OWNER_PRIVATE", "OWNER_CLIENT"),
    RouteCatalogEntry("/api/argus/calibration/ops", ("GET",), "api_argus_calibration_ops", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/calibration/posture", ("GET",), "api_argus_calibration_posture", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/calibration/v4/status", ("GET",), "api_argus_calibration_v4_status", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/calibration/watchlist-membership", ("GET", "POST"), "api_argus_watchlist_membership", "OWNER_SYNC", "OWNER_SYNC_OR_ADMIN", True, "OWNER_PRIVATE", "OWNER_CLIENT"),
    RouteCatalogEntry("/api/argus/calibration/watchlist-sync", ("POST",), "api_argus_watchlist_sync", "OWNER_SYNC", "OWNER_SYNC_OR_ADMIN", True, "OWNER_PRIVATE", "OWNER_CLIENT"),
    RouteCatalogEntry("/api/argus/calibration/watchlist-sync-status", ("GET",), "api_argus_watchlist_sync_status", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/caos-watchtower/status", ("GET",), "api_argus_caos_watchtower_status", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/caos/audit", ("GET",), "api_argus_caos_audit", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/caos/deep-research/status", ("GET",), "api_argus_caos_deep_research_status", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/caos/investigate-now", ("POST",), "api_argus_caos_investigate_now", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/caos/patrol-health", ("GET",), "api_argus_caos_patrol_health", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/caos/patrol-plan", ("GET",), "api_argus_caos_patrol_plan", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/caos/source-universe", ("GET",), "api_argus_caos_source_universe", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/caos/watchtower-plan", ("GET",), "api_argus_caos_watchtower_plan", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/catalysts", ("GET",), "api_argus_catalysts", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/cause-attribution", ("GET",), "api_argus_cause_attribution", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/cause-attribution-batch", ("GET",), "api_argus_cause_attribution_batch", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/chart-intelligence", ("GET",), "api_argus_chart_intelligence", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/class-quotes", ("GET",), "api_argus_class_quotes", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/closepin-snapshot", ("GET",), "api_argus_closepin_snapshot", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/cost-policy", ("GET",), "api_argus_cost_policy_status", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/crypto-scan", ("POST",), "api_argus_crypto_scan", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/crypto-watchlist", ("GET",), "api_argus_crypto_watchlist", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/daily-digest", ("GET",), "api_argus_daily_digest", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/dashboard-events", ("GET",), "api_argus_dashboard_events", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/data-quality/status", ("GET",), "api_argus_data_quality_status", "PUBLIC", "NONE", False, "PUBLIC_DIAGNOSTICS_V1", "BROWSER_INFRASTRUCTURE"),
    RouteCatalogEntry("/api/argus/decision-quality/status", ("GET",), "api_argus_decision_quality_status", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/decision-spine/status", ("GET",), "api_argus_decision_spine_status", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/decision-value/policies", ("GET",), "api_argus_decision_value_policies", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/decision-value/shadow-run", ("POST",), "api_argus_decision_value_shadow_run", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/decision-value/shadow-summary", ("GET", "POST"), "api_argus_decision_value_shadow_summary", "OWNER_SYNC", "OWNER_SYNC_OR_ADMIN", True, "OWNER_PRIVATE", "OWNER_CLIENT"),
    RouteCatalogEntry("/api/argus/decision-value/status", ("GET",), "api_argus_decision_value_status", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/decision-value/summary", ("GET",), "api_argus_decision_value_summary", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/downside-history", ("GET",), "api_argus_downside_history", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/downside-incidents", ("GET",), "api_argus_downside_incidents", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/entity-profiles", ("GET",), "api_argus_entity_profiles", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/entity-profiles/edit", ("POST",), "api_argus_entity_profiles_edit", "OWNER_SYNC", "OWNER_SYNC_OR_ADMIN", True, "OWNER_PRIVATE", "OWNER_CLIENT"),
    RouteCatalogEntry("/api/argus/entity-profiles/generate", ("POST",), "api_argus_entity_profiles_generate", "OWNER_SYNC", "OWNER_SYNC_OR_ADMIN", True, "OWNER_PRIVATE", "OWNER_CLIENT"),
    RouteCatalogEntry("/api/argus/entry-scout", ("GET",), "api_argus_entry_scout", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/event-analysis", ("GET",), "api_argus_event_analysis", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/event-analysis/generate", ("POST",), "api_argus_event_analysis_generate", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/event-backbone-status", ("GET",), "api_argus_event_backbone_status", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/event-dossier", ("GET",), "api_argus_event_dossier", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/event-log", ("GET",), "api_argus_event_log", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/event-snapshot", ("GET",), "api_argus_event_snapshot", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/event-test-notify", ("POST",), "api_argus_event_test_notify", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/events", ("GET",), "api_argus_events", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/events-active", ("GET",), "api_argus_events_active", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/events/<symbol>/institutional-intelligence", ("GET",), "api_argus_event_intel", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/events/<symbol>/research-mission", ("GET",), "api_argus_research_mission", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/events/cards", ("GET",), "api_argus_event_cards", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/events/cards/<card_id>", ("GET",), "api_argus_event_cards", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/evidence-pack", ("GET",), "api_argus_evidence_pack", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/fire-core/status", ("GET",), "api_argus_fire_core_status", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/flow-attribution", ("GET",), "api_argus_flow_attribution", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/flow-attribution/status", ("GET",), "api_argus_flow_attribution_status", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/foundation-jobs", ("GET",), "api_argus_foundation_jobs", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/fund-nav", ("GET",), "api_argus_fund_nav", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/important-events", ("GET",), "api_argus_important_events", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/institutional-intel/signals", ("GET",), "api_argus_institutional_intel_signals", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/institutional-intel/status", ("GET",), "api_argus_institutional_intel_status", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/institutional-intelligence", ("GET",), "api_argus_institutional_intelligence", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/institutional-intelligence/brief", ("GET",), "api_argus_intel_brief", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/institutional-intelligence/capture", ("POST",), "api_argus_intel_capture", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/institutional-intelligence/collect", ("POST",), "api_argus_intel_collect", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/institutional-intelligence/institutions", ("GET",), "api_argus_intel_institutions", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/institutional-intelligence/missed", ("GET",), "api_argus_intel_missed_list", "PUBLIC", "OPTIONAL_ADMIN_VIEW", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/institutional-intelligence/missed", ("POST",), "api_argus_intel_missed", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/institutional-intelligence/missed/apply", ("POST",), "api_argus_intel_missed_apply", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/institutional-intelligence/positioning/<symbol>", ("GET",), "api_argus_positioning", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/institutional-intelligence/relationship-graph", ("GET",), "api_argus_relationship_graph", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/institutional-intelligence/source-health", ("GET",), "api_argus_intel_source_health", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/integrations", ("GET",), "api_argus_integrations", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/investment-universe", ("GET",), "api_argus_investment_universe", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/japan-watchlist", ("GET",), "api_argus_japan_watchlist", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/jp-market-movers", ("GET",), "api_argus_jp_market_movers", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/jp-movers-push", ("POST",), "api_argus_jp_movers_push", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/jp-universe", ("GET",), "api_argus_jp_universe", "AUTH_OPERATIONAL", "ADMIN_TOKEN", False, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/jp-watchlist-codes", ("GET",), "api_argus_jp_watchlist_codes", "AUTH_OPERATIONAL", "ADMIN_TOKEN", False, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/learning-memory", ("GET",), "api_argus_learning_memory", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/learning-memory/lesson/<lesson_id>", ("GET",), "api_argus_learning_memory_lesson", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/learning-memory/snapshot", ("GET",), "api_argus_learning_memory_snapshot", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/learning-memory/status", ("GET",), "api_argus_learning_memory_status", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/learning-review/status", ("GET",), "api_argus_learning_review_status", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/ledger-health", ("GET",), "api_argus_ledger_health", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/ledger/recent", ("GET",), "api_argus_ledger_recent", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/macro-event-analysis", ("GET",), "api_argus_macro_event_analysis", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/macro-event-analysis/<eid>", ("GET",), "api_argus_macro_event_analysis_one", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/macro-event-analysis/status", ("GET",), "api_argus_macro_event_analysis_status", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/macro-events/result-status", ("GET",), "api_argus_macro_result_status", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/market-confirmation", ("GET",), "api_argus_market_confirmation", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/market-depth", ("GET",), "api_argus_market_depth", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/market-depth/proof", ("GET",), "api_argus_market_depth_proof", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/market-ledger", ("GET",), "api_argus_market_ledger_view", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/market-movers", ("GET",), "api_argus_market_movers", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/market-news", ("GET",), "api_argus_market_news", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/market-regime", ("GET",), "api_argus_market_regime", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/market-scan", ("POST",), "api_argus_market_scan", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/moomoo-capability", ("GET",), "api_argus_moomoo_capability", "AUTH_OPERATIONAL", "ADMIN_TOKEN", False, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/moomoo-capability-report", ("POST",), "api_argus_moomoo_capability_report", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/mover-causes", ("GET",), "api_argus_mover_causes", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/mover-causes/<market>/<symbol>", ("GET",), "api_argus_mover_cause_detail", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/mover-causes/explain-request", ("POST",), "api_argus_mover_causes_explain_request", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/mover-causes/refresh-queue", ("GET",), "api_argus_mover_causes_refresh_queue", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/mover-causes/snapshot", ("GET",), "api_argus_mover_causes_snapshot", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/mover-causes/status", ("GET",), "api_argus_mover_causes_status", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/news-radar", ("GET",), "api_argus_news_radar", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/news/ja-cache-snapshot", ("GET",), "api_argus_news_ja_cache_snapshot", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/news/translation-request", ("POST",), "api_argus_news_translation_request", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/news/translation-status", ("GET",), "api_argus_news_translation_status", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/notifications/status", ("GET",), "api_argus_notifications_status", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/official-events", ("GET",), "api_argus_official_events", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/official-events/<oid>", ("GET",), "api_argus_official_event_one", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/official-events/<oid>/lifecycle", ("GET",), "api_argus_official_event_lifecycle_view", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/official-events/durability", ("GET",), "api_argus_official_events_durability", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/official-events/snapshot", ("GET",), "api_argus_official_events_snapshot", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/official-events/status", ("GET",), "api_argus_official_events_status", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/official-events/track", ("POST",), "api_argus_official_events_track", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/osint/canary", ("GET",), "api_argus_osint_canary", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/osint/deep-dive", ("POST",), "api_argus_osint_deep_dive", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/osint/investigation", ("GET",), "api_argus_osint_investigation", "PUBLIC", "NONE", False, "PUBLIC_OSINT_INVESTIGATION_V1", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/osint/memory-snapshot", ("GET",), "api_argus_osint_memory_snapshot", "RECOVERY_PROOF", "LEGACY_PUBLIC_PROOF", False, "RECOVERY_PROOF_LEGACY", "SERVER_RECOVERY"),
    RouteCatalogEntry("/api/argus/osint/remote-readback", ("GET",), "api_argus_osint_remote_readback", "RECOVERY_PROOF", "LEGACY_PUBLIC_PROOF", False, "RECOVERY_PROOF_LEGACY", "SERVER_RECOVERY"),
    RouteCatalogEntry("/api/argus/osint/terms", ("POST",), "api_argus_osint_terms", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/osint/url-verify", ("POST",), "api_argus_osint_url_verify", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/osint/verify-gaps", ("POST",), "api_argus_osint_verify_gaps", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/picks/today", ("GET",), "api_argus_picks_today", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/portfolio-strategy/status", ("GET",), "api_argus_portfolio_strategy_status", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/portfolio-sync/pull", ("GET",), "api_argus_portfolio_sync_disabled", "AUTH_OPERATIONAL", "ADMIN_TOKEN", False, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/portfolio-sync/push", ("POST",), "api_argus_portfolio_sync_disabled", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/portfolio-sync/snapshots", ("GET", "POST"), "api_argus_portfolio_sync_disabled", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/portfolio-sync/status", ("GET",), "api_argus_portfolio_sync_status", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/position-exposure/status", ("GET",), "api_argus_position_exposure_status", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/position-plans", ("GET",), "api_argus_position_plans", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/position-plans/status", ("GET",), "api_argus_position_plans_status", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/prediction-snapshot", ("GET",), "api_argus_prediction_snapshot", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/price-history", ("GET",), "api_argus_price_history", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/pro-handoff", ("GET",), "api_argus_pro_handoff", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/provider-diagnostics/public", ("GET",), "api_argus_provider_diagnostics_public", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/quote-push", ("POST",), "api_argus_quote_push", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/rates", ("GET",), "api_argus_rates", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/research-benchmark", ("GET",), "api_argus_research_benchmark_status", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/research-benchmark/v2", ("GET",), "api_argus_research_benchmark_v2_status", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/research-missions", ("GET",), "api_argus_research_missions", "PUBLIC", "NONE", False, "PUBLIC_RESEARCH_MISSION_STATUS_V1", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/review-pack/status", ("GET",), "api_argus_review_pack_status", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/rotation-history", ("GET",), "api_argus_rotation_history", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/runtime-manifest", ("GET",), "api_argus_runtime_manifest", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/scenarios", ("GET",), "api_argus_scenarios", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/scenarios/status", ("GET",), "api_argus_scenarios_status", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/scout-batch", ("GET",), "api_argus_scout_batch", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/security-status", ("GET",), "api_argus_security_status", "AUTH_OPERATIONAL", "ADMIN_TOKEN", False, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/security-unlock", ("POST",), "api_argus_security_unlock", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/sensor-quotes", ("GET",), "api_argus_sensor_quotes", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/session-brief", ("GET",), "api_argus_session_brief", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/session-brief/status", ("GET",), "api_argus_session_brief_status", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/source-coverage", ("GET",), "api_argus_source_coverage", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/source-registry", ("GET",), "api_argus_source_registry", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/supply-demand", ("GET",), "api_argus_supply_demand", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/supply-demand/status", ("GET",), "api_argus_supply_demand_status", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/symbol-search", ("GET",), "api_argus_symbol_search", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/system-health", ("GET",), "api_argus_system_health", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/tdnet-metrics", ("GET",), "api_argus_tdnet_metrics", "AUTH_OPERATIONAL", "ADMIN_TOKEN", False, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/tdnet-recent", ("GET",), "api_argus_tdnet_recent", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/us-movers-push", ("POST",), "api_argus_us_movers_push", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/us-universe", ("GET",), "api_argus_us_universe", "AUTH_OPERATIONAL", "ADMIN_TOKEN", False, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/us-watchlist", ("GET",), "api_argus_us_watchlist", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/vault-pull", ("POST",), "api_argus_vault_pull", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/vault-push", ("POST",), "api_argus_vault_push", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/argus/vault-relay", ("GET",), "api_argus_vault_relay", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/argus/visibility-guard", ("GET",), "api_argus_visibility_guard", "PUBLIC", "NONE", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/api/chart/<symbol>", ("GET",), "api_chart", "AUTH_OPERATIONAL", "ADMIN_TOKEN", False, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/logs", ("GET",), "api_logs", "AUTH_OPERATIONAL", "ADMIN_TOKEN", False, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/margin", ("GET",), "api_margin", "AUTH_OPERATIONAL", "ADMIN_TOKEN", False, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/order_book/<symbol>", ("GET",), "api_order_book", "AUTH_OPERATIONAL", "ADMIN_TOKEN", False, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/price_history/<symbol>", ("GET",), "api_price_history", "AUTH_OPERATIONAL", "ADMIN_TOKEN", False, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/price_now/<symbol>", ("GET",), "api_price_now", "AUTH_OPERATIONAL", "ADMIN_TOKEN", False, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/reset", ("POST",), "api_reset", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/run", ("POST",), "api_run", "AUTH_OPERATIONAL", "ADMIN_TOKEN", True, "LEGACY_OPERATIONAL", "SERVER_OPERATOR"),
    RouteCatalogEntry("/api/state", ("GET",), "api_state", "PUBLIC", "OPTIONAL_ADMIN_VIEW", False, "PUBLIC_PRODUCT", "BROWSER_PUBLIC"),
    RouteCatalogEntry("/healthz", ("GET",), "healthz", "PUBLIC", "NONE", False, "PUBLIC_LIVENESS_V1", "INFRASTRUCTURE"),
    RouteCatalogEntry("/readyz", ("GET",), "readyz", "PUBLIC", "NONE", False, "PUBLIC_READINESS_V1", "INFRASTRUCTURE"),
    RouteCatalogEntry("/static/<path:filename>", ("GET",), "static", "PUBLIC", "NONE", False, "STATIC_ASSET", "BROWSER_PUBLIC"),
)


def route_contract_keys(entries: Iterable[RouteCatalogEntry] = ROUTE_CATALOG):
    return frozenset(
        (row.route, tuple(row.methods), row.endpoint) for row in entries)


def validate_route_catalog(entries: Any = ROUTE_CATALOG) -> tuple[str, ...]:
    errors: list[str] = []
    if type(entries) is not tuple:
        return ("catalog_not_tuple",)
    seen: set[tuple[str, tuple[str, ...], str]] = set()
    for index, row in enumerate(entries):
        if type(row) is not RouteCatalogEntry:
            errors.append(f"row_{index}_invalid")
            continue
        key = (row.route, row.methods, row.endpoint)
        if key in seen:
            errors.append(f"row_{index}_duplicate")
        seen.add(key)
        if not row.route.startswith("/"):
            errors.append(f"row_{index}_route_invalid")
        if not row.methods or tuple(sorted(set(row.methods))) != row.methods:
            errors.append(f"row_{index}_methods_invalid")
        if row.trustDomain not in TRUST_DOMAINS:
            errors.append(f"row_{index}_trust_invalid")
        if row.authenticationPolicy not in AUTH_POLICIES:
            errors.append(f"row_{index}_auth_invalid")
        if type(row.mutatesState) is not bool:
            errors.append(f"row_{index}_mutation_invalid")
        if row.mutatesState != any(
                method in {"POST", "PUT", "PATCH", "DELETE"}
                for method in row.methods):
            errors.append(f"row_{index}_mutation_method_mismatch")
        if row.trustDomain == "PUBLIC" and row.mutatesState:
            errors.append(f"row_{index}_public_mutation")
        if row.trustDomain == "AUTH_OPERATIONAL" and \
                row.authenticationPolicy != "ADMIN_TOKEN":
            errors.append(f"row_{index}_operational_auth_invalid")
    return tuple(errors)


def route_catalog_document() -> dict[str, Any]:
    return {
        "schemaVersion": "argus-route-trust-catalog-v1",
        "entries": [asdict(row) for row in ROUTE_CATALOG],
        "publicCacheOnlyConsumers": [
            asdict(row) for row in PUBLIC_CACHE_ONLY_CONSUMERS
        ],
    }


def validate_public_cache_only_consumers(
        contracts: Any = PUBLIC_CACHE_ONLY_CONSUMERS) -> tuple[str, ...]:
    errors: list[str] = []
    if type(contracts) is not tuple:
        return ("cache_only_contracts_not_tuple",)
    by_route = {row.route: row for row in ROUTE_CATALOG}
    if tuple(contract.route for contract in contracts) != tuple(sorted(
            contract.route for contract in contracts)):
        errors.append("cache_only_contracts_not_sorted")
    seen: set[str] = set()
    for index, contract in enumerate(contracts):
        if type(contract) is not CacheOnlyConsumerContract:
            errors.append(f"cache_only_{index}_invalid")
            continue
        if contract.route in seen:
            errors.append(f"cache_only_{index}_duplicate")
        seen.add(contract.route)
        row = by_route.get(contract.route)
        if row is None:
            errors.append(f"cache_only_{index}_route_missing")
        elif not (row.trustDomain == "PUBLIC" and row.methods == ("GET",)
                  and row.mutatesState is False):
            errors.append(f"cache_only_{index}_route_not_public_read")
        if not contract.consumers or any(
                not consumer.startswith("web/src/")
                for consumer in contract.consumers):
            errors.append(f"cache_only_{index}_consumer_invalid")
        if not contract.refreshAuthority:
            errors.append(f"cache_only_{index}_refresh_authority_missing")
    return tuple(errors)


ROUTE_CATALOG_VALIDATION_ERRORS = validate_route_catalog()
PUBLIC_CACHE_ONLY_VALIDATION_ERRORS = validate_public_cache_only_consumers()
