#!/usr/bin/env python3
"""Acquire and admit the exact accepted V13 source for V13.5 release control.

The release starts from an intentionally shallow checkout.  This module always
asks the configured remote for the exact accepted commit, binds FETCH_HEAD to
that request, verifies its tree, and then performs the product semantic diff.
Pre-merge and production call this same implementation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
import urllib.parse
from typing import Any, Dict, Mapping, Optional


SCHEMA = "argus-v13-5-source-provenance-v1"
PRODUCT_VERSION = "v13.7.46"
ACCEPTED_V13_SOURCE = "f79548bb274c5c5acc4075c181195834c252d54d"
ACCEPTED_V13_TREE = "bdba7c970872b92b88bc6e7cc7b0b8afe4785a96"
CANONICAL_REMOTE = "https://github.com/mitsugue/argus.git"
ROOT = pathlib.Path(__file__).resolve().parents[1]

# A renamed historical report is identified by its accepted source blob, not
# by embedding its retired path in the current product or audit output.
# This permits removal only with the named replacement present and changed.
HISTORICAL_REPLACED_BLOBS = {
    "a9ce5f34b3b377819256d274fa18c4bd0a6c5cb9":
        "artifacts/round2-jp-market-engine-registry-coverage-v1.json",
}

# Reviewed model and operational fixes, limited to these exact file contents.
# These paths are NOT added to the general allowlist; future edits fail closed.
REVIEWED_EXTENSION_BLOBS = {
    'ops/imports/acquisition_20260920/ACCEPTANCE_CRITERIA.md': '918375dfb7c134b0792b401b90356178635e5f1a',
    'ops/imports/acquisition_20260920/source_registry.json': '9d843748819442f1d8650135f768827df9392f7f',
    'ops/imports/acquisition_20260920/data_contract.json': 'f0a1b3f58a4d25d399d6048a6d1e9e02b63f0354',
    'ops/imports/acquisition_20260920/provenance.json': 'd720c7898b1fcfb23eae4959c1fb8403d574e665',
    'docs/V13_7_ACQUISITION_PACK_ACCEPTANCE.md': '6857081ce69e53bca54d900562800b54e4384897',
    'scripts/import_index_valuation.py': 'bd9278e7a166855aff8777cb41aa1628bcd07420',
    'test_jp_market_acquisition.py': '76cadfcabf7e3ebe48c4e00f2055e203b7792968',
    'jp_market_acquisition.py': 'b0964e2d2d1a78769b717ef7928898ab7dd7ae9a',
    'ops/imports/README.md': '0c3a8010eebfa90f6c20be3d46e0d59fd3039404',
    'web/src/components/today/SectorHeatmap.css': '0bdc3b1e84dcbc03f447ac34fa1754b4d8941f8b',
    'web/src/components/today/SectorHeatmap.tsx': 'b621436144d448055255243e2304c1287fced869',
    'test_jp_sector_heatmap_api.py': '4b93b1bd5fa1eed37baff43912b3a86cbd9f00e9',
    'test_jp_sector_heatmap_runtime.py': '3bb33a56d1305e1f5daac3e804f62ddb93099de7',
    'test_jp_sector_heatmap.py': '1f6abcd332dba7406db0d1d998437d647b76967e',
    'jp_sector_heatmap_runtime.py': 'f31cb749d4bc365db5b235fdb3bf8350b9e37686',
    'jp_sector_heatmap.py': 'e7f762925f14e36463419f38ef68d3c3b44c8700',
    'test_argus_material_translation.py': '80f68a5abad282c920926dbb8b9541d97da016ae',
    'test_argus_queue_v1152_backend.py': 'ec3d8c65c5b48755539e0dfdc0f93ccf6362cfb1',
    'test_argus_shared_bridge.py': '71830cb29c437a727688cabf14aa4e955bf95ffb',
    'bridge/README.md': '9bcd2afec193b966d963ad7382c43136ed283e7c',
    'bridge/bridge.env.example': 'dffbcc62907f9dd05594495bd6ffada6e43d1fa5',
    'bridge/moomoo_push.py': '5268c303608bad317a6e47bbe891a64860959674',
    'test_argus_saved_overview.py': 'a0a24d21fa9d37ee44d3e69a9e2991b3dbbe910a',
    'test_argus_overview_policy.py': '3051e457321f71c6e7a4ba1e9ce34179e42a0877',
    'argus_overview_policy.py': '15a4a5cea4eb079ca2589484bd94c4cf54c102ca',
    'test_jp_market_feature_delta.py': '5cf423e0f9514fa1a87841277adc4b50ea0ad035',
    'web/src/domain/watchlistProjection.ts': '36b5e0c3eba3a67ce9fec128f422ce3af89498cc',
    'web/scripts/watchlist-retirement.test.cjs': '55e0d87e492fba0322787e821c1b5e0f21c36d88',
    'web/scripts/positions-risk.test.cjs': '24378a48ec140668b53aa6442cb87356ede43790',
    'web/src/lib/tradeJournal.ts': '149dec98cbf3d17e9860e235c91c28248aa6c2d1',
    'web/src/components/dashboard/TradeJournalCard.tsx': '9b4e4f073a281cc61cb75e49134266fde9392bce',
    'web/scripts/polling-singleton.test.mjs': 'de34e0e33bc46871c009f4264d85881a7d2e74ca',
    'test_argus_institutional_backend_v1160.py': 'd8065d151883cdf13ff7ebfa79358482d40cc8fc',
    'docs/V13_7_SHAPEUP_REQUIREMENTS.md': '9756717ff26e5cf159dcf5d20cb578d99ab225ed',
    'docs/V13_7_SHAPEUP_ACCEPTANCE.md': 'c86aa8bb3da05f49b0a14b848439cb5ea2a26b94',
    'test_rules.py': '99fad6a22f968ddc518a8b7b359d4adfdf8fd9e0',
    'bridge/trigger_closepin.sh': '83ee01384660bb8799a863e080021a7fa35c1e3d',
    '.github/workflows/closepin-pin.yml': 'ea693b3ca6140d4cf6fa66c48d91c6a03f603baa',
    'scripts/run_breadth_freshness.py': '93922a3409750a1562fb928eb34933f5feb22a68',
    'test_breadth_freshness_workflow.py': '4a7926a32e990576327d14db059504e57f7cc2a8',
    'argus_tick_durability.py': 'fd2f2a97652cf1f3bb18084fd1aa5f54a19247da',
    'argus_jp_fiscal_monitor.py': '3584e845b3c66c2ebdbb41aae6e8b3bfd9866117',
    'argus_jp_fiscal_runtime.py': '5ba1577db358b3fe270b81e8f4685efb0f20d87e',
    'argus_jp_fiscal_sources.py': 'cf2b63e3062a193eab8b3c990005e5e4033a6150',
    'docs/V13_7_JP_FISCAL_MONITOR.md': '58498e9819208825f203c37acff3d5c33c473dff',
    'ops/fiscal/cao_20260730.json': '72b7f9ded706ebf1aa9ae92ebb4396b8bf055ae6',
    'scripts/extract_cao_fiscal_table.py': '7b274ad6a393577802e0c6efb0d09882c244df32',
    'test_argus_jp_fiscal_monitor.py': 'c15814b4a0ca8f0c38e137e882320b0d377315e5',
    'test_argus_jp_fiscal_runtime.py': '147ff4d092920be0090fdfe56951a817457c2298',
    'test_argus_jp_fiscal_sources.py': '240b86e2e5df5cde777742bc52d34c47c9f91ea3',
    'web/src/components/today/FiscalEnvironmentDetails.css': 'c5830b9d9414c8b7fafb69b5fa4f7d4a0db83700',
    'web/src/components/today/FiscalEnvironmentDetails.tsx': 'd696c18bf0e8e18abbd3ca167e135fe02d581386',
    'web/src/lib/revealNewsArticle.ts': '807735f5bd95556ed64af7019cf0b3f26608a07c',
    'web/scripts/news-delivery-grouping.test.cjs': 'f197d0b0a32ce7efbc2192b1ae80a762300017f3',
    'docs/V13_7_INDEX_ANALOG_COVERAGE.md': '905dca1b82c5c24ed1e7e11ce6278e8503221564',
    'test_argus_index_history.py': 'ce4a258925493926854d121d0d43e1f3559597e1',
    'argus_index_history.py': 'f4f50d4bcb69d60e35f831647c4308dc0432b8ad',
    "docs/V13_7_NUMERICAL_RESEARCH_INVENTORY.md": "827158b6cc590cd7aebc60b8539806c50c82ef91",
    "test_jp_market_valuation.py": "f431c1327159ca980923bfce3dfff7e32786eafe",
    "test_argus_index_research_cache.py": "bad74c16b576650ff0ff7c0c95e50574ee1adc63",
    "argus_index_research_cache.py": "5e1a8d8252ca758c099a1ee7e87b958017e02033",
    'test_argus_research_calculation_reuse.py': '0aec958de8cffbd8caca9e1e56c9c52dc3227cad',
    'web/src/components/today/NumericalResearchDetails.tsx': '48bab6718ecaf2626c6409791f495c029c7dd9ab',
    'test_argus_jp_market_research.py': '238a026b12986c454f44e93ed0d97dff1ddf6220',

    "test_jp_market_engine.py": "142cc381d94e879def14ee46bf107ae411ddbbd9",
    "test_argus_japan_valuation.py": "e7daf10f9e931db0492155b424ffd0d4745cfa2f",
    "test_argus_valuation_addendum.py": "f5d413b959fba23f0103ec9c131fba8a94f30c0d",
    "scripts/verify_index_valuation_anchors.py": "b6520b17bcf79cb8376b12c975dc6f8d8010ba7e",
    'argus_jp_market_research.py': '643a18e14be0387234172f934c473077825f2fe0',
    'test_argus_owner_dialogue_compression.py': '2cb55fe8e96b350d9d951401acf5cde43785b6c2',
    'test_argus_owner_overview_pending.py': '3bbebf3d717ad4d4f30e175d14fd2402e64396cf',
    'test_argus_analysis_history_compact.py': 'a62aa02724f8e1456a2e191eb327f15c1cb915e3',
    'argus_analysis_history_compact.py': '013d0927c21cc753a223d07a22cb574293fa38d3',
    'argus_event_prediction_results.py': 'dc3475083bfbed3df6ae49885667d0a5308385e4',
    'test_argus_event_prediction_results.py': '030f5233dd2e3fc0b31cc1b5d68a3ca2ddb75fd8',
    'scripts/export_event_prediction_results.py': '179bde75c50c32f426a42fffc117f2584c6e45a7',
    'argus_event_result_source.py': '5d19291205687f62f00f77c43c2cd50225ebe363',
    'test_argus_event_result_source.py': 'cf0a4dca842fd1763341002dcc9a82b2ef49b6ad',
    # Cost-first cadence: bounded material-event windows retain the official
    # result and reaction path while removing unchanged two-hour reruns.
    '.github/workflows/macro-event-analysis.yml': '4b77fff3c377df98c4baae6bb64963f0fe9ab9c5',
    'test_macro_schedule.py': '0a33bb9b772f9ef1ee036fa2f5e4e49cad21661d',
    'test_macro_readiness.py': 'd1348cbcc814fb28857bd42095007f355728cd5a',
    'scripts/macro_readiness.py': 'd9d736333960d220a5ce3fc55951abc901ea47f0',
    'docs/V13_7_REQUIREMENTS.md': '6ae5091a2167249af1a5c8e1bfc75c5f8ed3d928',
    'web/src/hooks/useOsintInvestigation.ts': 'ada26a80e0f0f439f97cb75858407647dc7c5d8d',
    'web/src/components/guide/Layer2BSyncCard.tsx': 'b54f946a7a4176390d086dfc302588fe7e45a26f',
    'web/src/components/dashboard/ProHandoffButton.tsx': 'a7e9d2c235333fa504f306fb6ad743d3a4eda972',
    'web/src/components/dashboard/OsintDeepDive.tsx': '875c23041a7d765379aa834bbfe70ae24abf0f05',
    'web/src/components/dashboard/AddAssetModal.tsx': '56b5df9a55e8238db3538c829f1e29fd157398ce',
    'web/src/components/assetDesk/AssetResearchPanel.tsx': '74487e1942385ade5ccef2209a9ca63bf5d3e4e1',
    'test_argus_v12_3_1.py': 'c26d3849a5c7219d537c1cdd8a3484c5087e4da1',
    'web/src/components/dashboard/SystemHealthPopover.tsx': '3893f26c3bef9812d841600832a96193231000ed',
    'web/src/routes/DataQualityPage.tsx': 'c86b933832c2e50f3d694f4ca1ac79428096fe55',
    'web/src/components/common/TriangleStepLoader.tsx': '218b53b03160f619d00d3e6c3b2eec90fe7922c6',
    'web/src/components/common/TriangleStepLoader.css': '189ca3825669144c1ecec4248f9cc72376d77387',
    'web/src/i18n/index.ts': '933221ee4ca1f3adccdb8ebf5c950419fe7ce019',
    # Owner-authorized v13.6.1 prediction-ledger continuity regression proof.
    'test_prediction_ledger_workflow.py': 'c56ab18cdedbf04fd37c7362209172fe92e409cf',
    'web/src/lib/assetMerge.ts': '486d7ecb06b35fef782a83be46121a856d82eb94',
    'web/src/hooks/useAssets.ts': '7378e41e1b7fdf6ff6b14f29e5271639054f370b',
    'web/src/components/dialogue/OwnerOverview.tsx': '237fac885c233c84baf128924f0b4cc92aa7e334',
    'web/src/components/dialogue/OwnerOverview.css': 'e608b1f63bbbf8596454a9e0100cea6ee8a41a0f',
    'web/scripts/product-integrity.test.cjs': 'ab517d81f9118ecb74163ed2b4efc62ff99521ac',
    'web/src/lib/presentationIntent.ts': '77c0c79423a2291fc3e28a58e1b0397b11a83828',
    'web/src/components/today/ArgusEditorialSurface.tsx': 'e9b5df8e1944de37961b78d85382f0f055b2bf30',
    'web/src/components/today/ArgusEditorialSurface.css': 'c11ff9b79ce546d415e55cb7e8eb29b928b80fc5',
    'test_argus_presentation_intent.py': 'e79beae902a1382fae9e5ea3359e09301abf9733',
    'docs/V13_6_PRESENTATION_INTENT.md': '88d35d6f5f603628e7e89bae56308e16b7c76ea6',
    'argus_presentation_intent.py': 'd2e9404d0fa2b51a21870970232996b8ce0b8624',
    'argus_persistent_storage.py': '822f60d3ce54a7f5dfbf16638ff79727cb7e4e64',
    'web/src/components/today/ReadingHierarchy.css': 'f031a35a7ec9cb1aac772bbae8c0ab1de44c4a85',
    'web/src/components/AppShell.tsx': 'fa34bd3703246744c9eeec4411783b6234777a77',
    'web/src/routes/BackupPage.tsx': '7d082a20c08964bb00dc4de227827f7bcfc19abb',
    'web/src/navigation.ts': '7bbea49bee28dd07ead0273ea84f1092255a3ca3',
    'web/src/lib/webPush.ts': '87c83b0bf874ecbf453d2af786dde6f502006b6f',
    'web/src/lib/ownerVaultReceipt.ts': 'bdfeb6b79dd52052ae051638869609d6cf74bf4a',
    'web/src/lib/ownerVaultAutoSave.ts': 'd5c382797e024265beb70baba4a9f1aa0df7d97c',
    'web/src/lib/ownerVault.ts': 'df5d6d6331a029790ef8030f6a265140bf205f1e',
    'web/src/lib/ownerRestoreGuard.ts': '53e425d51bb10dec6e53a584bc0bd6f5fb35b953',
    'web/src/lib/backupSafety.ts': 'c7ef1e0e4b44c4b4fc4bcb8bb2cfb36effc05a09',
    'web/src/lib/backupMeta.ts': '908c1801a85b9b392bc58043046a9411d7c73703',
    'web/src/lib/aiUsageView.ts': '033d8391844e4fa00f80945858a483b0c98393bf',
    'web/src/components/settings/WebPushPanel.tsx': 'ac2f4b64143d3e1220b918d9f23a772bba2c734b',
    'web/src/components/settings/WebPushPanel.css': '00b2bef993a8eca959afedbf2015796b5746e724',
    'web/src/components/settings/OwnerVaultPanel.tsx': '981ca9ecbbcc6af8068297d384ef786d874f6846',
    'web/src/components/settings/AiUsagePanel.tsx': 'b17e0d0a666b2c00ec5e5d7098086e54b1eb0615',
    'web/src/components/settings/AiUsagePanel.css': 'eb215c910039c200f8b5fb01287672f3f4eb6376',
    'web/src/components/dashboard/PortfolioSyncCard.tsx': 'd960fa95c19fb63fc8a8784be7bea1879fb6969a',
    'web/scripts/web-push.test.mjs': '220bdd38d81b8cf506d9559a01787076d56b113b',
    'web/scripts/owner-vault.test.cjs': '2458ab4b91f044bdc69fb6894705cd949af8ffbb',
    'web/scripts/owner-vault-legacy-isolation.test.cjs': 'b58bd43566481f8ebb60dc2272dd95ab3b5e2fac',
    'web/scripts/owner-vault-auto-save.test.cjs': '7181233ba2be7d1cd5111b8c11386b545e511c29',
    'web/scripts/owner-restore-guard.test.cjs': 'a6711358fc81ad10afaab52af2b118f79133d7ce',
    'web/scripts/owner-protection-consistency.test.cjs': 'f6365d9edfda291084bc17ee05e8d2499bc2774b',
    'web/scripts/lean-surface.test.mjs': '117dc9b3576f59665d81bea626fcb35ec973243c',
    'web/scripts/ai-usage-view.test.cjs': '558e8ef36130e5a59e26f8973176ee2ce741db8a',
    'web/public/push-worker.js': '3934f69c999ae680856bf3e6b23a3ba8f97e514d',
    'test_argus_web_push.py': '69118b280db79fae69bcd3d76db20521714056a2',
    'test_argus_owner_vault.py': '64c3c8bec19581962309873e1b93fb31cdc2cbe2',
    'test_argus_ai_usage_view.py': '729a3e9155a2106069ad68d8b9efb590ab10f3a9',
    'requirements.txt': 'acfc928655cc76a36ad7c41e3ced58247d27c81c',
    'jp_market_valuation.py': '8813012bcab02e9269007a8850870da2ef050565',
    'docs/V13_6_INDEX_VALUATION.md': 'aa7a1a35a12be9657139cb3e9488ea4b136f087b',
    'argus_web_push.py': 'e6ea726935fb8ceb60bc16deaf1a4b50cb9f8355',
    'argus_owner_vault.py': '9c3d105716b1115a205bc69dbbbd18e3a7356457',
    'argus_ai_usage_view.py': 'cd86138feaaa5f61a305b2eaa4e74f2b8de3b163',
    'argus_ai_usage_runtime.py': 'f65f5bd3196c162ad1152a1468a5d2be531f778b',
    'argus_analysis_history_backup.py': 'ae9013e5b81e9bf743821cd6ef0ea17c1b829ceb',
    'argus_explanation_contract.py': '3c052634c6bfa2f9cfd045444472cafe15ca46ed',
    'argus_owner_dialogue.py': '1d89a5ae5edadba3e02bcac45217b0785c22ac8d',
    'argus_owner_dialogue_api.py': 'e8733b755e1c47c5677e56fe42112a8ca5a22359',
    'argus_owner_dialogue_backup.py': '4560f85996da2d78a68ff0cb4e28a1cdb8bf50bc',
    'argus_owner_dialogue_recovery.py': 'bfc92ba9d12514167c622df5bcf04f87e945d721',
    'argus_owner_dialogue_store.py': '72422e35451def9da106bb200acd49e880a9a2f1',
    'argus_subject_materials.py': 'd23a8ed213d7baf211d1293d394ee300c626ebf6',
    'docs/V13_6_AI_USAGE.md': 'f455ad3d0a366f2fad38564bbea7bc4e6bbf3856',
    'docs/V13_6_MARKET_INTERNALS.md': 'f57f78cac4a3d6398f6bb68430dca549661a9003',
    'docs/V13_6_OWNER_DIALOGUE.md': '6363817a4c2378931c8ba2fb9f30dc3fd691ac21',
    'jp_market_internals.py': '289cf25368b32e1a53aa3d23528c72543e9a6c77',
    # PR #459 owner-approved GPT-only cost-cap regression coverage.  Keep the
    # exact reviewed blob pin; future test edits require separate review.
    'test_argus_ai_usage_runtime.py': '4b765dd3c8dde089634331897eb9d7010404feec',
    'test_argus_analysis_history_backup.py': 'd0b721fe82d01f830727a98ef29a70f51a73df2f',
    'test_argus_owner_cached_inputs.py': '444cb79f894d9a756d42d0ad47ce646a3f1b36ea',
    'test_argus_owner_dialogue.py': 'bb51131cb51b1c0670050b0c0594b7113c1a0aec',
    'test_argus_owner_dialogue_api.py': '9312928ff4a8417db892455cbc2ce597c9745326',
    'test_argus_owner_dialogue_backup.py': 'cf675c0f2f17840c35e762a35feafc090cab8338',
    'test_argus_owner_dialogue_recovery.py': 'acf706ac87e3ea5a686768bb22d9239e4576c126',
    'test_argus_subject_materials.py': '321b8881f911e5ce356e1684a471c68413498a3d',
    'test_jp_market_internals.py': '49eb3f360af263f28847f3fb9fceae31c8a539d5',
    'web/scripts/pwa-recovery.test.mjs': 'd2fc2ff86480cb685328e1341e61d4415285d8a6',
    'web/scripts/shared-market-context.test.cjs': '6ba958105e283011e25af76c3ce538e14833c75b',
    'web/src/components/assetDesk/AssetMarketContext.tsx': '4a4c82e59357536a41ee5487c9afe5667832798a',
    'web/src/components/dialogue/OwnerDialogue.css': '99f542e0fc1391a58a1cb60ac1c5bec249fe9a28',
    'web/src/components/dialogue/OwnerDialogue.tsx': '5e8f6f1e4f9ae850f804d55069dcdd3b412199e6',
    'web/src/components/today/MarketBriefCard.tsx': '7b8f0305a0346a43cea572f8954bae9f87cc8359',
    'web/src/components/today/MarketInternalsCard.tsx': '0ff16f3dca77ff41bbab3d4101dc8a5e594bd23f',
    'web/src/components/today/SharedMarketContext.tsx': 'dde94d5b6d12989bd4ea8a3c0dded9c9462892f5',
    'web/src/lib/marketInternals.ts': 'cf96a5b15512e7f20ef9bcf211d6295307ccec9a',
    'web/src/lib/pwaRecovery.ts': '038fe1dc3e55433a0f72e8a06ca1701176155438',
    'web/src/components/today/MarketAnalysisHistory.tsx': '7a986421fdd00c28c53e563a09287dbbc314694e',
    'test_argus_analysis_history.py': '4a9c705d81507ebf9f6cecafea1f583572b13fc0',
    'argus_analysis_history.py': '5bb5fc8be9cec151eb61634f3cded2d9ef6d541a',
    'argus_market_ledger.py': '562841f6de02f9e778591c82eb6f9642756199d9',
    'jp_market_positioning.py': '37661655f15f27baf2beec9e08fb2b5977cfbe9f',
    'test_jp_market_positioning.py': 'f6134d86859e836ca26ab54b0c707ed7b7c8aa14',
    'web/scripts/jpy-position.test.cjs': '250fc6fde44ad782d5be85c1325c04f86692f716',
    'web/src/components/today/JpyPositionCard.tsx': '17fd54006ba230e31bfa0d12ab324430017a9afd',
    # Owner-authorized staged analysis delivery; exact tested file contents only.
    'argus_ai_usage_receipt.py': 'c0795a8d95ff367d79fe2b14abf5323052fba9c2',
    'argus_ai_usage_store.py': 'bc0ccd94eeb2b601da72ecb4a847c8ba3bbf07e1',
    'argus_macro_event_store.py': '0f3bf526a88c83a22576abbf06490bc2861af433',
    'argus_macro_results.py': '4d6e3c0c88fd8be18595f9a25d9c9465f14ec19e',
    'docs/V13_6_ANALYSIS_ACCEPTANCE.md': '5f3f34d75eefb1a18abb18c8d2407d6921bcd57a',
    'docs/V13_6_COMPUTE_CONTRACT.md': '4ad0e52d419c261b24be8775d9c635bd310e9417',
    'jp_market_analogs.py': 'b9fe5ea4f538829e617e4f0f2f759238495d9385',
    'jp_market_dynamics.py': '6949bb8b2cc4a1526f09016fb0c0e10369ce488d',
    'jp_market_events.py': '08adce36b4bc2dfdb7ade550ba15b8937e8e16a0',
    'jp_market_features.py': 'f1099ffc61fd96816c41ac3228de09186d72779c',
    'jp_market_price_paths.py': '1ea2873b8bab0dfa245cfb24d4b379f7be654df7',
    'jp_market_source_adapters.py': 'a89b745791fe493522388766ef88611ebcbc6aeb',
    'ops/calendar/jp_index_sq_2026.json': 'd55cbf1e1362d4d86b21fe413cc2de35b035bd62',
    'test_argus_ai_usage_receipt.py': '00d50f40807d5eea8e149115e1664272b4e4408a',
    'test_argus_ai_usage_store.py': '03dce630d6b901cc3e4277c78a7a241b2fac724a',
    'test_argus_macro_result_revisions.py': '0745614163ed8614560868201a64d117b0e77e22',
    'test_argus_macro_results.py': '647520e693f5f87f902033bb1e2a0c0762bfc407',
    'test_argus_unified_brief.py': 'b5b384bce57d18d260a0bf6dc08d8473b6680f3c',
    'test_jp_market_analogs.py': '5717118c03d35c47c979d26c2fc253af0bee0fc1',
    'test_jp_market_comparison_runtime.py': '588b4441415d9e22856835f23bbcf2ad20dfebf3',
    'test_jp_market_dynamics.py': 'dab9901948bb7c6ab339ee5d4b7a8244eeb79cf6',
    'test_jp_market_events.py': 'c18777fb3a7eb629ac1161cc16533923f4e20424',
    'test_jp_market_events_runtime.py': '76c27382d35b39c8745e5de09450942da852342d',
    'test_jp_market_features.py': '9255e905406bb42aa9138cb06abd0193ac005753',
    'test_jp_market_margin_runtime.py': 'd89cf0d2b0b6cd7d67b9798ab583c23fd6fb11f7',
    'test_jp_market_price_paths.py': 'c0b334a81292efde995c585836ca81ac1b97ab3b',
    'test_jp_market_source_adapters.py': 'ea39ec595aa0c5f42726b42beb2f2ca84f41e401',
    'web/scripts/japan-market-comparison.test.cjs': 'c3a76e4193883de463cd2d53cdc412dd7d5a46a5',
    'web/scripts/japan-sq-calendar.test.cjs': '41fc84761bab22b8218bb5c1347767521472a2c6',
    'web/scripts/macro-result-details.test.cjs': 'b2bcdb290db61a0ef8d8ffcd090a55e5020e10a1',
    'web/scripts/margin-dynamics.test.cjs': '2ab221c47cfeb6afa4d0adcb1dfebd17b862b608',
    'web/scripts/market-brief-response.test.cjs': 'a0b9296048de2038a4f4e647c1583af010d1c3e5',
    'web/src/components/chart/JapanMarketComparisonChart.css': '6cf24f6f680e6ee50aba8c8c45645882ab55ca8f',
    'web/src/components/chart/JapanMarketComparisonChart.tsx': '434c5af8691586562cb34ba35a3b4856e39ec4d5',
    'web/src/components/chart/JapanMarketComparisonPanel.tsx': '8f9123239e7f904694640b0b9854bc20b2fee063',
    'web/src/components/dashboard/JapanSqCalendarCard.css': 'a8bfb645823551f415e2d05e8f6721273c09083b',
    'web/src/components/dashboard/JapanSqCalendarCard.tsx': '77f4e4fa1edee0e5f42db6d82597a4ec1ad82083',
    'web/src/components/dashboard/MacroResultDetails.tsx': '1ae4f62354c917002f6b60b1b8e72de1a126a3f6',
    'web/src/components/today/MarginDynamicsCard.tsx': '916091e12c4362a7340ad5cb5dff373b1d36300e',
    'web/src/hooks/useJapanMarketComparison.ts': '23226d5fa95e4acdcefe2f156bc7ac6de95df61a',
    'web/src/hooks/useJapanSqCalendar.ts': '3bd95e491810c395faf23203356d85eb7d0d385e',
    'web/src/lib/japanMarketComparison.ts': 'c3958e252e93031fa1ad0dac7a63512b7f8530b2',
    'web/src/lib/japanSqCalendar.ts': '947b1c9121f7b6f8a5e7b501211b8b43449b329b',
    'web/src/lib/marketBrief.ts': 'c28f0bb61c21b8e347ef81343a6671a670608a65',
    'web/src/types/japanMarketComparison.ts': 'f57468b6758aadeaf926a4a95ee7a5d95d605dac',
    "test_ai_cost.py": "e2e1a3094c0fe315993d027592de6e1db9a5b784",
    'web/scripts/news-polling-recovery.test.mjs': 'a5675fb01973b14712491809f7eb30c5814851f0',
    "test_argus_prediction_read_latency.py": "731d0705813a323169ba286315811cac5b06e0f7",
    "web/scripts/news-presentation.test.mjs": "163019b4aa4c6a454a5351b7ad8c68ff5024712a",
    "web/src/domain/newsPresentation.ts": "88361ceaf9b7da66ff5b6344e118d4707a8d6dea",
    "test_argus_ai_execution_settings.py": "91724952d7a992ea4d0c58a8f9bfaaf567f70a64",
    "argus_research_benchmark.py": "0afebef7261abeb95da017f4b5aa327da55874a1",
    "argus_ai_gate.py": "d0e19fb4d25527e6f0ca70d73c8b21a41bc2a866",
    'test_smoke_cached_cause.py': '547735d7be278e5650341bd067b50c1fa87dd855',
    'smoke_test.py': 'e6c003c4d7b3c499744950b98457860f4bc71a77',
    'web/src/components/guide/BackupCard.tsx': '7af09b55b37840fc69c2c14234d1cb429b2624de',
    "web/src/components/system/BackupStatusOverview.tsx": "39488f34de87013943edf08bb3faddce91f7b996",
    "web/src/lib/vault.ts": "9180eba851c0b62a99ac449166f90f2404e18370",
    "web/scripts/news-history.test.mjs": "766b69d112dc01d32631025446007b506d7e55f6",
    "web/scripts/public-market-acceptance.mjs": "2b2d476948053f06f4db95cb243484f333a4ad3b",
    "web/scripts/canonical-snapshot-selection.mjs": "85eff19fcf41a5edb651cbec91291cf4625d8182",
    "web/scripts/index-chart-isolation.test.mjs": "470dcf9598714a89b9ebba9dd53cfc2f6315092f",
    "argus_osint_engine.py": "82c928299eed09004067283d72cc4b67b07753c5",
    "test_argus_v12_1_1.py": "fcb2a56c79822f5177ae776dfdaf07972da0a49e",
    "test_argus_v12_1_3.py": "ec334f206cc43a94f3e2dc8c7ea5015b341a0957",
    ".github/workflows/ai-rejudge.yml": "3fff3c5530adf4ca322e93d72dffb38d52ad7520",
    "test_argus_official_lifecycle.py": "94895d787c27281d6699182cce75a415c7ad896b",
    "test_workflow_http.py": "3b02814b97563c1b089de97697d0bb471bee1578",
    # v13.7.18 owner-required Today consolidation: these exact acceptance
    # assertions remove the legacy four-index selector and its duplicate
    # outlook without relaxing the underlying research/truth contracts.
    "test_argus_v12_0_6.py": "14c660ebc25f8f0fe50743da58d2c50eb6e26256",
    "test_argus_v13_1_1.py": "0dcfbd099dd00f4e84b89df51da6a03fa96c2e4f",
    # Owner-authorized v13.7 operating-cost reduction: retire redundant
    # scheduled workflows while retaining manual recovery and product tests.
    ".github/workflows/ai-rejudge.yml": "9674c680ad54973f71bbc03a2dc335eb299c373b",
    ".github/workflows/crypto-watch.yml": "1c996e5db84e8211ea09daa762c5f7d5d5554f7d",
    ".github/workflows/mover-causes.yml": "d78d91aac76c377b68c67638bbea93176a7c7f89",
    "test_retired_background_workflows.py": "bbfe02c081353b142cde8e106ac619f67cec6dd0",
    # Owner-authorized Gemini retirement regression coverage. This fixes only
    # the exact Terra-only operational workflow test; later edits fail closed.
    "test_gpt_only_workflow_operations.py": "b048c5bcdf0d6b73a3e8eb955b9020d896ef1066",
    # Owner-authorized v13.7.46 Today consolidation: the live editorial surface
    # no longer duplicates the current five-day chart; archived editions retain it.
    "web/scripts/owner-functional-ui.test.mjs": "31a1a8f37c99c50b2a8735adbc845a08a68eb740",
    # Owner-authorized v13.7.44 surface consolidation: the standalone Alerts
    # route is retired, its navigation position is the read-only 13M link,
    # and legacy notification hashes resolve to Today. These exact product
    # files are pinned; any later surface change requires separate review.
    "web/scripts/lean-surface.test.mjs": "38a9ced36b2aae61e8a4c1b759d85745d007af18",
    "web/src/components/NavRail.tsx": "f1a1fef74709852f39d488aaf370428ce2697fe2",
    "web/src/navigation.ts": "5a29e9dc8a1e1d0ed160288e6bd2e54713b6a725",
    # v13.7.44 regression assertions synchronized with the approved Alerts-to-13M surface.
    "test_argus_v12_2_12.py": "9aef4250a8a68e76dcda4ff8a079d04fed17cf9a",
    "test_argus_v12_rc.py": "d6d462465f7556f748ee0900e3f88820410e284f",
    # Owner-authorized cost reduction: the active-event reader shares one
    # lifecycle and pauses while the page is not visible. These pins bind the
    # later product PR to the reviewed, read-only transport semantics.
    "web/src/hooks/useEventsActive.ts": "4c1c42354a44bdf152a3fc1b92af4b5ae750f4c8",
    "web/scripts/polling-singleton.test.mjs": "3833a92b51421fc67b08c14ce1b675f13a771b09",
    # Owner-authorized cost reduction: the fail-closed visibility authority
    # has one visible-page lifecycle and does not poll while hidden.
    "web/src/hooks/useVisibilityGuard.ts": "0396f6d2f3fa94351887432b02eeb0e7620f80f3",
    "web/scripts/polling-singleton.test.mjs": "726accbaf256fc7e3fa8141c3c9f31ade7efbb24",
}

AUTHORIZED_EXTENSION_PATHS = frozenset({
    # Bounded chart display publication and its regression coverage.
    "argus_asset_chart_cache.py",
    "test_argus_asset_chart_cache.py",
    # Chart refresh paths already included in the owner-approved PR #319.
    "test_argus_asset_chart_precompute.py",
    "web/src/types/chartIntelligence.ts",
    "argus_product_naming.py",
    "test_argus_runtime_naming.py",
    "docs/ops/paired-migration-admission.md",
    # Owner-authorized 13.5 stabilization: tracked collection completion and
    # recent-event smoke coverage; no trade or calibration authority change.
    "scripts/run_intel_collect.py",
    "test_run_intel_collect.py",
    "test_smoke_nfp_lifecycle.py",
    "docs/V13_5_CODEX_STATUS.md",
    "docs/V13_6_REQUIREMENTS.md",
    ".github/workflows/market-watch.yml",
    # Owner-required functional naming, explanation policy and data-preserving
    # migration. Formula/action parity is verified separately from name IDs.
    ".github/workflows/product-naming.yml",
    "AGENTS.md",
    "README.md",
    "argus_evidence_pack.py",
    "argus_market_intelligence.py",
    "argus_research_compute.py",
    "artifacts/round2-jp-market-engine-registry-coverage-v1.json",
    "artifacts/round2-research-coverage-v1.json",
    "docs/JP_MARKET_ENGINE_MIGRATION_STATUS.md",
    "docs/JP_MARKET_ENGINE_REQUIREMENTS.md",
    "docs/ops/round2-macro-convergence.md",
    "docs/ops/round2a-market-truth-prediction-ledger.md",
    "docs/ops/round2a-single-decision-authority.md",
    "scripts/migrate_analysis_names.py",
    "scripts/analysis_migration_restore.py",
    "scripts/product_naming_guard.py",
    "scripts/deploy_scope.py",
    "render.yaml",
    "test_render_deploy_guard.py",
    "scripts/round2_resource_probe.py",
    "test_argus_decision_spine.py",
    "test_argus_research_compute.py",
    "test_argus_risk_discipline.py",
    "test_migrate_analysis_names.py",
    "test_product_naming_guard.py",
    "web/scripts/single-decision-authority.test.cjs",
    # v13.5.65 (stabilization item 5): weekly JPX credit import, per-input
    # freshness on the conditioning line, stored-data notes.
    "scripts/jpx_credit_weekly.py",
    "test_jpx_credit_weekly.py",
    ".github/workflows/jpx-credit-weekly.yml",
    ".github/workflows/research-benchmark.yml",
    "argus_today_intelligence.py",
    "test_jp_market_engine_conditioning.py",
    "test_argus_notification_eligibility.py",
    "web/src/domain/deskCoverage.ts",
    "docs/V13_6_HANDOVER.md",
    "docs/checkpoint-v2-mapping-attribution.md",
    # v13.5.64 (release path): allocator bound split with normal-use evidence,
    "scripts/verify_public_candidate_release.py",
    # successor-sha acceptance, post-deploy warm for Recovery merges.
    "scripts/checkpoint_v2_mapping_probe.py",
    "docs/checkpoint-v2-mapping-attribution.md",
    "test_argus_mapping_attribution.py",
    ".github/workflows/backend-warm-after-deploy.yml",
    ".github/workflows/macro-event-analysis.yml",
    "test_argus_notification_eligibility.py",
    # v13.5.63 (GPT additional items 1-6): runnable BUY validation, desk
    # coverage reconciliation, event-AI run record, GPT-6 pricing.
    "scripts/reversal_buy_validation.py",
    "docs/REVERSAL_BUY_VALIDATION.md",
    "web/src/domain/deskCoverage.ts",
    "argus_ai_cost.py",
    "test_argus_macro_event_analysis.py",
    "web/src/components/dashboard/Dashboard.css",
    "web/src/hooks/useMacroEventAnalysis.ts",
    # v13.5.36 owner-functional correction: compact iPhone navigation, concise
    # Japanese news projection, source-diverse market evidence, and semantic
    # de-duplication of recurring long-end-rate conditions.  Investment and
    # calibration authority stay outside this list and remain fail-closed.
    # owner-authorized path set for interaction performance (off-thread
    # verification, idle-sliced device ledger appends, keep-mounted Today),
    # the name-selector Today UX, the compact Seven Sign surface, the
    # market-shock (Major News) pipeline, the Prediction Ledger workflow
    # correction (canonical steps before private-store extras + precise
    # diagnostics), the checkpoint-v2 capacity budgets, and the v13.5.x
    # identity. The accepted baseline is the LIVE v13.5.0 release
    # (f79548bb…); anything outside this list fails the release closed.
    # v13.5.36 SCHEDULED_AI enablement (owner 「有効にして」 2026-08-23/24):
    # bounded cost-policy mode + quarantine review. Decision authority remains
    # deterministic and fail-closed.
    "argus_cost_policy.py",
    "smoke_test.py",
    "argus_market_clock.py",
    "test_argus_daily_authority_calendar.py",
    "test_argus_d07_production_supply.py",
    "web/src/domain/glossary.ts",
    "web/src/components/common/GlossaryTip.tsx",
    "web/scripts/glossary.test.cjs",
    "web/src/routes/CommandCenter.tsx",
    "jp_market_engine.py",
    "test_etf_ts_cache.py",
    "test_jp_mover_tiers.py",
    "test_legacy_provider_source_authority.py",
    "test_argus_single_decision.py",
    "test_argus_market_truth_scanner.py",
    "argus_single_decision.py",
    "web/src/domain/singleDecisionAuthority.ts",
    "argus_market_brief.py",
    "test_argus_market_brief.py",
    "test_argus_market_brief_non_authority.py",
    "web/scripts/brief-non-authority.test.cjs",
    "web/src/hooks/useMarketBrief.ts",
    # v13.5.53 (owner 2026-09-04: 「仮想通貨も何も表示できていない」). The client's
    # crypto freshness budget was shorter than the delivery chain it had to
    # cover (a 90 s server cache over a source that is already ~30-60 s behind),
    # so every CoinGecko quote was rejected and every crypto row rendered with
    # no price. Correcting that budget — and the test that now pins it to the
    # server cache TTL plus the source lag — needs these two display-authority
    # paths. Investment and calibration authority stay outside this list.
    "web/src/domain/liveAuthority.ts",
    "web/scripts/live-authority.test.cjs",
    # v13.5.54 (same owner report, second cause). The desk row rebuilt the
    # crypto quote from `date` + `status` alone and threw away the source-time
    # evidence the payload already carried, so the ONE genuinely 24h-live feed
    # rendered as 「asOf <date> (日付のみ) · age 未検証」. This declares the
    # fields the payload has always sent; the LIVE claim still has to clear
    # classifyDelay's own age proof. Display authority only.
    "web/src/types/crypto.ts",
    # v13.5.59 (owner iPhone review): the pre-release AI-scenario line states
    # the cost policy that governs it instead of "waiting". Pure display text.
    "web/src/lib/eventAiScenarioNote.ts",
    # v13.5.60 (owner iPhone review 2026-09-07): the Alerts page becomes three
    # named sections with stable anchors (news-intel / asset-alerts /
    # important-events); the news section renders the same news-intelligence
    # and market-shock documents Today summarises. Display only — no action
    # authority, no new fetch loop.
    "web/src/components/notifications/NewsAlertsPanel.tsx",
    "web/src/components/notifications/NewsAlertsPanel.css",
    "web/src/components/NotificationPanel.tsx",
    "web/src/routes/NotificationsPage.tsx",
    # v13.5.61 (owner iPhone review 2026-09-07): one-button runtime diagnostics
    # (thread locations + memory phases, secret-free), a display-only cleaner
    # for digest mail headlines, and the closed-market cold fill test surface.
    ".github/workflows/runtime-diagnostics.yml",
    "scripts/runtime_diagnostics_summary.py",
    "web/src/lib/newsHeadline.ts",
    # v13.5.62 (GPT review 2026-09-07): decision evidence for every registered
    # symbol (pure batching helper), one plain quote-freshness line, the most
    # severe risk per symbol, the digest-mail splitter test, and the JP/US
    # forecast method table. Display and pure helpers only; no authority moves.
    "web/src/lib/decisionEvidenceBatches.ts",
    "web/src/domain/liveQuote.ts",
    "web/src/domain/positionExposure.ts",
    "web/src/components/assetDesk/AssetDataQuality.tsx",
    "test_argus_news_digest_split.py",
    "docs/forecast-method-jp-us.md",
    "test_argus_v12_0_8.py",
    # v13.5.54 (owner 2026-09-05: Twelve Data plan is BASIC, 8 credits/min,
    # 800/day; the ninth US symbol must not be silently dropped and the plan
    # must never be impersonated). Pure, provider-free warm-scheduler core:
    # rotation under the request batch cap, UTC-day credit ledger, market-aware
    # cadence, owner-authorized universe assembly, and symbol-free budget
    # diagnostics. scanner.py wiring travels separately through Recovery.
    "argus_td_warm.py",
    "test_argus_td_warm.py",
    # v13.5.54 (production measurement 2026-09-04). The verifier compares
    # methodVersion with strict equality; the frontend pin stopped at three
    # segments when scanner.py grew a fourth in v13.5.14, so every verified
    # snapshot was rejected as method_incompatible, the client cache held
    # zero records, and each release's seed-warm-profile job timed out,
    # skipping the downstream acceptance jobs. The asset-chart pin had the
    # same drift. These paths correct the two consumer pins to the producer
    # identities and pin the equality in CI (reading the real backend value)
    # so a future method change fails until the frontend is deliberately
    # updated. Verification is not weakened; no prefix matching.
    "web/src/lib/assetChartCache.ts",
    "web/scripts/verified-snapshot.test.mjs",
    "web/scripts/asset-chart-policy.test.cjs",
    "web/scripts/method-version-contract.mjs",
    "test_argus_method_version_contract.py",
    # v13.5.53 (owner 2026-09-04: 「イベントが何もないことはないはず」). The asset
    # card asserted 「直近の関連イベント・材料の紐付けはありません」 and EVENT
    # EXPOSURE 「直近紐付けなし」 whenever the important-events feed had not been
    # read, turning an unread feed into a claim about the calendar. These three
    # display paths carry the "not known" distinction. Investment and
    # calibration authority stay outside this list.
    "web/src/components/assetDesk/types.ts",
    "web/src/components/assetDesk/AssetEventsPanel.tsx",
    "web/src/components/assetDesk/AssetPositionPanel.tsx",
    "web/src/components/assetDesk/AssetEvidenceSummary.tsx",
    # v13.5.54 (owner 2026-09-04: 「日経平均などの指数がトップに表示されていない、
    # まだETF」). The Today headline draws the index the owner reasons in; the
    # verified ETF snapshot remains the decision anchor and the panel discloses
    # it. Display authority only — investment and calibration authority stay
    # outside this list.
    "web/src/domain/marketInstruments.ts",
    "test_argus_cost_policy.py",
    "test_argus_foundation_jobs.py",
    "test_argus_research_benchmark.py",
    "test_argus_v12_3_0.py",
    "web/src/types/marketLedger.ts",
    ".github/actions/v13-5-pre-mutation-rehearsal/action.yml",
    ".github/workflows/caos-scan.yml",
    ".github/workflows/deploy-pages.yml",
    ".github/workflows/market-public-acceptance.yml",
    ".github/workflows/news-intake-ops.yml",
    ".github/workflows/prediction-ledger.yml",
    ".github/workflows/release-gate.yml",
    "argus_breadth_worker.py",
    "argus_causal_event_memory.py",
    "argus_checkpoint_v2.py",
    "argus_gmail_intake.py",
    "argus_market_shock.py",
    "argus_news_i18n.py",
    "argus_news_intelligence.py",
    "argus_route_catalog.py",
    "argus_today_headline.py",
    "backend-version.json",
    "bridge/moomoo_push.py",
    "docs/ARGUS_V13_5_4_CAUSAL_EVENT_MEMORY.md",
    "product-version.json",
    "release/v13-accepted-fix-manifest.json",
    "scanner.py",
    "scripts/checkpoint_v2_isolated_probe.py",
    "scripts/news_gmail_authorize.py",
    "scripts/normalized_hash_resource_probe.py",
    "scripts/checkpoint_v2_resource_probe.py",
    "scripts/release_gate.sh",
    "scripts/v13_5_pre_mutation_rehearsal.py",
    "scripts/v13_5_release_certificate.py",
    "scripts/v13_5_source_provenance.py",
    "scripts/workflow_http.py",
    "test_argus_deploy_scope.py",
    "test_argus_causal_event_memory.py",
    "test_argus_causal_event_memory_backend.py",
    "test_argus_bridge_v1157.py",
    "test_argus_mission_tick_durability.py",
    "test_jp_market_engine_non_regression.py",
    "test_argus_gmail_intake.py",
    "test_argus_market_shock.py",
    "test_argus_news_i18n.py",
    "test_argus_news_intelligence.py",
    "test_argus_news_pipeline.py",
    "test_argus_notification_eligibility.py",
    "test_argus_public_operational_boundary.py",
    "test_argus_release_identity.py",
    "test_argus_v12_2_12.py",
    "test_argus_v12_4_0.py",
    "test_argus_v13_1_0.py",
    "test_caos_workflow_recovery.py",
    "test_remote_journal_rearm.py",
    "test_v13_5_release_certificate.py",
    "test_v13_5_pre_mutation_rehearsal.py",
    "test_v13_5_source_provenance.py",
    "test_verify_public_candidate_release.py",
    "web/package-lock.json",
    "web/package.json",
    "web/scripts/full-release-simulation.mjs",
    "web/scripts/argus-engine.test.cjs",
    "web/scripts/asset-desk.test.cjs",
    "web/scripts/causal-event-memory.test.mjs",
    "web/scripts/iphone-profile.mjs",
    "web/scripts/market-data-truth.test.cjs",
    "web/scripts/market-system-integrity.test.cjs",
    "web/scripts/mobile-today-acceptance.mjs",
    "web/scripts/mobile-today-integrity.test.mjs",
    "web/scripts/owner-functional-ui.test.mjs",
    "web/scripts/release-state-machine.mjs",
    "web/scripts/release-state-machine.test.mjs",
    "web/scripts/release-fixture-target.mjs",
    "web/scripts/acceptance-runtime.test.mjs",
    "web/scripts/round3-product-final.test.mjs",
    "web/scripts/runtime-version-truth.test.mjs",
    "web/scripts/today-benchmark.mjs",
    "web/src/App.tsx",
    "web/index.html",
    "web/src/main.tsx",
    "web/vite.config.ts",
    "web/src/components/dashboard/MobileStickyCommand.css",
    "web/src/components/NavRail.css",
    "web/src/components/assetDesk/AssetDecisionCard.tsx",
    "web/src/components/assetDesk/AssetDecisionDetails.tsx",
    "web/src/components/assetDesk/AssetDecisionSummary.tsx",
    "web/src/components/assetDesk/AssetDesk.css",
    "web/src/components/assetDesk/AssetDeskList.tsx",
    "web/src/components/chart/ChartIntelligencePanel.css",
    "web/src/components/chart/ChartIntelligencePanel.tsx",
    "web/src/components/today/ArgusToday.css",
    "web/src/components/today/ArgusTodayPanel.tsx",
    "web/src/hooks/useAssetIntel.ts",
    # v13.5.36 (external-review conformance batch): JP_MARKET_ENGINE CORE production
    # wiring (item B), MARKET VIEW/ACTION separation display (item A), event
    # constraint tiering + uncapped imminent feed (item C), and the
    # degraded-feed kernel split (item F).
    "web/src/domain/importantEventsTier.ts",
    "web/src/domain/newsSignalGate.ts",
    "web/scripts/news-signal-gate.test.cjs",
    # v13.5.36 owner directive: internal engine names removed from every
    # user-visible surface (jargon-free UI sweep).
    "web/src/components/dashboard/DownsideIncidentCard.tsx",
    "web/src/domain/assetDecision.ts",
    "web/src/routes/CorePortfolio.tsx",
    "web/src/hooks/useImportantEvents.ts",
    "web/scripts/important-events-tier.test.cjs",
    "web/src/hooks/useChartIntelligence.ts",
    "web/src/hooks/useMarketNews.ts",
    "web/src/components/settings/NewsIntakePanel.tsx",
    "web/src/hooks/useMarketShock.ts",
    "web/src/hooks/useNewsIntelligence.ts",
    "web/src/hooks/useTodayHeadline.ts",
    "web/src/domain/assetDesk.ts",
    "web/src/domain/argusTodayView.ts",
    "web/src/lib/notifications.ts",
    "web/src/routes/Settings.tsx",
    "web/src/lib/sdaDeviceLocal.ts",
    "web/src/lib/todayHeadline.ts",
    "web/src/lib/verifiedSnapshot.ts",
    # v13.5.57: the canonical contract names the DECISION SUBJECT (verified
    # ETF), not the drawn index series. These acceptance-contract test lanes
    # pinned the old attribute expression and now pin the subject form.
    "web/scripts/market-replay.test.mjs",
    "web/scripts/public-market-acceptance.contract.test.mjs",
    "web/src/lib/verify.worker.ts",
    "web/src/lib/verifyWorkerClient.ts",
    "web/src/routes/CommandCenter.tsx",
    "web/src/routes/PageShell.tsx",
    "web/src/routes/Watchlist.tsx",
    "web/src/types/assetItem.ts",
    # v13.5.36 owner spec conformance (2026-08-22): news-risk ⊥ market
    # confirmation, tri-state Action Priority context, honest probability-truth
    # evidence, the canonical artifact resolver boundary (backend
    # decision-evidence route + device resolver + SDA registration seam),
    # canonical candidateAction in issued decisions, and the encrypted-vault
    # ride-along for the append-only device SDA ledger.
    "argus_action_priority.py",
    "argus_single_decision.py",
    "argus_today_intelligence.py",
    "test_argus_action_priority.py",
    "test_jp_market_engine_conditioning.py",
    "test_argus_decision_evidence.py",
    "test_argus_market_truth_scanner.py",
    "test_argus_v12_rc.py",
    "web/scripts/backup-protection-contract.test.cjs",
    "web/scripts/canonical-decision-evidence.test.cjs",
    "web/scripts/device-local-sda-ledger.test.cjs",
    "web/src/domain/actionPriority.ts",
    "web/src/domain/canonicalDecisionEvidence.ts",
    "web/src/domain/probabilityTruth.ts",
    "web/src/main.tsx",
    "web/src/domain/singleDecisionAuthority.ts",
    "web/src/hooks/useDecisionEvidence.ts",
    "web/src/lib/backup.ts",
    # Recovery-only merges (PR #235-#251) were admitted to protected main
    # through the independent Recovery certificate route
    # (scripts/recovery_admission.py, pinned payload digest), not through this
    # product certificate.  They are already on main; this PR authors no change
    # to any of them.  Listing them keeps the product semantic diff against the
    # accepted v13.5.0 source closed and computable for later product
    # candidates.  Recovery authority, Soak, and acceptance clock stay untouched.
    ".github/workflows/caos-watchtower.yml",
    ".github/workflows/checkpoint-v2-gate.yml",
    ".github/workflows/ci.yml",
    ".github/workflows/memory-attribution.yml",
    "argus_recovery_phase_a_adapter.py",
    "argus_remote_journal.py",
    "argus_remote_receipt_queue.py",
    "argus_remote_recovery.py",
    "argus_remote_recovery_limits.py",
    "docs/EC2_MISSION_SCHEDULER.md",
    "docs/ops/permanent-scheduler-identity-and-soak.md",
    "docs/ops/recovery-phase-a-integration.md",
    "ops/systemd/argus-remote-journal-rearm.service",
    "ops/systemd/argus-remote-journal-rearm.timer",
    "ops/systemd/argus-watchtower-writer.service",
    "ops/systemd/argus-watchtower-writer.timer",
    "scripts/argus_remote_journal_rearm.py",
    "scripts/argus_watchtower_writer_dispatch.py",
    "scripts/install_argus_mission_timer.sh",
    "scripts/install_argus_remote_journal_rearm.sh",
    "scripts/install_argus_watchtower_writer.sh",
    "scripts/prepare_remote_journal_publish.py",
    "scripts/recovery_admission.py",
    "scripts/remote_journal_publish_policy.py",
    "scripts/remote_receipt_drain.py",
    "test_argus_checkpoint_v2_isolated.py",
    "test_argus_identity_installer.py",
    "test_argus_persistent_mission_storage.py",
    "test_argus_recovery_phase_a_adapter.py",
    "test_argus_v12_3_2.py",
    "test_argus_v13_4_2_remote_receipts.py",
    "test_recovery_admission.py",
    "test_remote_receipt_drain.py",
    "test_remote_recovery_nonce_bootstrap.py",
    "test_remote_recovery_publish.py",
    "test_remote_recovery_restore.py",
    # Tachibana e-Branch v4r10 READ-ONLY SHADOW market-data provider, disabled
    # by default (candidate a6648da1, tree ec101b16).  A new isolated package
    # with no scanner import, no public route, no order/amend/cancel surface,
    # and no path to SDA authority; enable flags default to
    # ENABLED=false / SHADOW_ONLY=true / AUTHORITATIVE=false.
    "argus_providers/__init__.py",
    "argus_providers/tachibana/__init__.py",
    "argus_providers/tachibana/client.py",
    "argus_providers/tachibana/config.py",
    "argus_providers/tachibana/cross_validation.py",
    "argus_providers/tachibana/event_stream.py",
    "argus_providers/tachibana/evidence.py",
    "argus_providers/tachibana/models.py",
    "argus_providers/tachibana/normalization.py",
    "argus_providers/tachibana/redaction.py",
    "argus_providers/tachibana/runtime.py",
    "argus_providers/tachibana/sensor.py",
    "argus_providers/tachibana/session.py",
    "argus_providers/tachibana/session_truth.py",
    "argus_providers/tachibana/singleton.py",
    "docs/evidence/tachibana-v4r10-2026-09-01.md",
    "docs/operations/tachibana-live-shadow.md",
    "requirements-tachibana.txt",
    "scripts/tachibana_live_acceptance.py",
    "scripts/tachibana_live_sensor_service.py",
    "scripts/tachibana_readonly_smoke.py",
    "test_argus_tachibana_sensor.py",
    # v13.5.38 Tachibana LIVE product integration: the single product-owned
    # adapter boundary (argus_tachibana_live), the owner-facing MARKET SIGNALS
    # SIG-01..07 projection (argus_market_signals, embedded in the JP_MARKET_ENGINE market
    # view), and the Today surfaces that render them.  No scanner/route
    # change is authored here (those stay under the Recovery admission pin).
    "argus_market_signals.py",
    "argus_tachibana_live.py",
    "test_argus_market_signals.py",
    "test_argus_tachibana_live.py",
    "web/src/domain/marketSignals.ts",
    "web/src/domain/tachibanaLive.ts",
    "web/src/components/assetDesk/deskFormat.ts",
    "web/src/hooks/useSystemHealth.ts",
    "web/src/lib/assetStrategy.ts",
    "argus_chart_bootstrap.py",
    "argus_japan_valuation.py",
    "argus_important_events.py",
    "test_important_events.py",
    "test_argus_dashboard_event_summary.py",
    "web/src/lib/dashboardEventState.ts",
    "web/src/hooks/useDashboardEvents.ts",
    "web/src/domain/eventTitleJa.ts",
    "web/src/components/dashboard/ImportantEventsCard.tsx",
    "web/src/components/dashboard/ImportantEventsCard.css",
    "web/scripts/live-intelligence-cache.test.cjs",
    "web/scripts/event-title-ja.test.cjs",
    "test_argus_japan_valuation.py",
    "test_jp_market_engine.py",
    "web/src/hooks/useJapanWatchlist.ts",
    "web/src/domain/jpWatchFallback.ts",
    "web/scripts/jp-watch-fallback.test.cjs",
    "test_argus_chart_bootstrap.py",
    "argus_dashboard_event_summary.py",
    "argus_macro_event_analysis.py",
    "test_argus_important_events_product_correctness.py",
    "argus_news_freshness.py",
    "argus_mover_cause.py",
    "argus_chart_intelligence.py",
    "argus_decision_evidence_bundle.py",
    "argus_scheduler.py",
    "argus_verified_snapshot.py",
    "argus_risk_discipline.py",
    "argus_research.py",
    "argus_fastdate.py",
    "test_argus_fastdate.py",
    "test_argus_dashboard_events_backend.py",
    "test_argus_macro_v115_backend.py",
    "web/scripts/frontend-market-event-truth.test.cjs",
    "web/scripts/market-signals.test.cjs",
    "web/scripts/tachibana-live.test.cjs",
    "docs/operations/tachibana-live-shadow.md",
})


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def sha256_hex(value: Any) -> str:
    raw = value if isinstance(value, bytes) else canonical_bytes(value)
    return hashlib.sha256(raw).hexdigest()


def _is_sha(value: Any) -> bool:
    return type(value) is str and len(value) == 40 \
        and all(character in "0123456789abcdef" for character in value)


def _load(path: pathlib.Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"source_provenance_json_invalid:{path}") from exc
    if type(value) is not dict:
        raise ValueError(f"source_provenance_json_object_required:{path}")
    return value


def _write(path: pathlib.Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(
        value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8")


def _git(repo: pathlib.Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False)
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().replace("\n", " ")
        raise ValueError(f"git_{args[0].replace('-', '_')}_failed:{detail[:300]}")
    return result.stdout.strip() if result.returncode == 0 else ""


def _resolve(repo: pathlib.Path, ref: str, kind: str) -> str:
    if kind not in {"commit", "tree"}:
        raise ValueError("source_provenance_internal_kind")
    value = _git(repo, "rev-parse", "--verify", f"{ref}^{{{kind}}}")
    if not _is_sha(value):
        raise ValueError(f"{kind}_identity_invalid")
    return value


def _sanitize_remote(url: str) -> str:
    if url.startswith("git@github.com:"):
        return "https://github.com/" + url.split(":", 1)[1]
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme in {"http", "https"}:
        host = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""
        return urllib.parse.urlunsplit(
            (parsed.scheme, host + port, parsed.path, "", ""))
    return url


def _validate_remote(url: str, *, allow_local_remote: bool) -> str:
    clean = _sanitize_remote(url)
    normalized = clean[:-1] if clean.endswith("/") else clean
    canonical = CANONICAL_REMOTE[:-4] if CANONICAL_REMOTE.endswith(".git") \
        else CANONICAL_REMOTE
    candidate = normalized[:-4] if normalized.endswith(".git") else normalized
    if not allow_local_remote and candidate != canonical:
        raise ValueError(f"accepted_source_remote_mismatch:{clean}")
    return clean


def _certificate_identity(path: pathlib.Path) -> Dict[str, Any]:
    value = _load(path)
    digest = value.get("certificateDigest")
    body = dict(value)
    body.pop("certificateDigest", None)
    if type(digest) is not str or len(digest) != 64 \
            or digest != sha256_hex(body):
        raise ValueError("source_provenance_certificate_digest_invalid")
    return value


def _manifest_identity(repo: pathlib.Path) -> Dict[str, Any]:
    manifest = _load(repo / "release/v13-accepted-fix-manifest.json")
    source = manifest.get("canonicalSource")
    if type(source) is not dict or source.get("head") != ACCEPTED_V13_SOURCE \
            or source.get("tree") != ACCEPTED_V13_TREE:
        raise ValueError("accepted_source_authority_conflict")
    return manifest


def validate_product_semantic_diff(
        candidate_ref: str, *, repo: pathlib.Path = ROOT) -> Dict[str, Any]:
    accepted_commit = _resolve(repo, ACCEPTED_V13_SOURCE, "commit")
    accepted_tree = _resolve(repo, accepted_commit, "tree")
    if accepted_commit != ACCEPTED_V13_SOURCE:
        raise ValueError("accepted_v13_source_commit_mismatch")
    if accepted_tree != ACCEPTED_V13_TREE:
        raise ValueError("accepted_v13_source_tree_mismatch")
    candidate_commit = _resolve(repo, candidate_ref, "commit")
    changed = _git(repo, "diff", "--name-only", accepted_commit,
                   candidate_commit).splitlines()
    if len(changed) != len(set(changed)):
        raise ValueError("product_semantic_diff_duplicate_path")
    unauthorized = sorted(set(changed) - AUTHORIZED_EXTENSION_PATHS)
    reviewed = []
    for path in unauthorized:
        expected = REVIEWED_EXTENSION_BLOBS.get(path)
        if expected and _git(repo, "rev-parse", "--verify",
                             f"{candidate_commit}:{path}", check=False) == expected:
            reviewed.append({"path": path, "blobSha": expected})
    unauthorized = sorted(set(unauthorized) - {item["path"] for item in reviewed})
    replaced, removed_paths = [], set()
    for path in unauthorized:
        if _git(repo, "cat-file", "-t", f"{candidate_commit}:{path}", check=False):
            continue
        old_blob = _git(repo, "rev-parse", "--verify", f"{accepted_commit}:{path}", check=False)
        target = HISTORICAL_REPLACED_BLOBS.get(old_blob)
        if (not target or target not in AUTHORIZED_EXTENSION_PATHS
                or target not in changed
                or _git(repo, "cat-file", "-t", f"{candidate_commit}:{target}", check=False) != "blob"):
            continue
        if any(item["acceptedBlobSha"] == old_blob for item in replaced):
            raise ValueError("historical_replacement_ambiguous")
        replaced.append({"acceptedBlobSha": old_blob, "replacementPath": target})
        removed_paths.add(path)
    unauthorized = sorted(set(unauthorized) - removed_paths)
    if unauthorized:
        path_ids = [hashlib.sha256(path.encode("utf-8")).hexdigest()[:16]
                    for path in unauthorized]
        raise ValueError(
            "product_semantic_change_required:path_ids=" + ",".join(path_ids))
    result = {
        "status": "PASS",
        "acceptedSource": accepted_commit,
        "acceptedTree": accepted_tree,
        "changedPaths": sorted(set(changed) - removed_paths),
        "productSemanticChange": False,
    }
    if reviewed:
        result["reviewedExtensionBlobs"] = reviewed
    if replaced:
        result["removedHistoricalBlobs"] = sorted(replaced, key=lambda item: item["acceptedBlobSha"])
    return result


def acquire_source(
        *, repo: pathlib.Path, remote: str, accepted_source: str,
        accepted_tree: str, candidate_sha: str, candidate_tree: str,
        certificate_path: pathlib.Path, release_merge_sha: Optional[str] = None,
        release_merge_tree: Optional[str] = None,
        allow_local_remote: bool = False) -> Dict[str, Any]:
    repo = repo.resolve()
    if accepted_source != ACCEPTED_V13_SOURCE \
            or accepted_tree != ACCEPTED_V13_TREE:
        raise ValueError("accepted_source_authority_conflict")
    if not _is_sha(candidate_sha) or not _is_sha(candidate_tree):
        raise ValueError("candidate_identity_invalid")
    if (release_merge_sha is None) != (release_merge_tree is None):
        raise ValueError("release_merge_identity_incomplete")
    if release_merge_sha is not None \
            and (not _is_sha(release_merge_sha)
                 or not _is_sha(release_merge_tree)):
        raise ValueError("release_merge_identity_invalid")

    _manifest_identity(repo)
    product = _load(repo / "product-version.json")
    if product != {"schemaVersion": "argus-product-version-v1",
                   "productVersion": PRODUCT_VERSION}:
        raise ValueError("product_version_not_v13_5")
    certificate = _certificate_identity(certificate_path)
    if certificate.get("candidate") != {
            "commitSha": candidate_sha, "treeSha": candidate_tree}:
        raise ValueError("source_provenance_certificate_candidate_mismatch")
    if certificate.get("acceptedV13Source") != {
            "commitSha": accepted_source, "treeSha": accepted_tree}:
        raise ValueError("source_provenance_certificate_source_mismatch")
    if certificate.get("productVersion") != PRODUCT_VERSION:
        raise ValueError("source_provenance_certificate_product_mismatch")

    remote_url = _validate_remote(
        _git(repo, "remote", "get-url", remote),
        allow_local_remote=allow_local_remote)
    shallow_before = _git(repo, "rev-parse", "--is-shallow-repository") == "true"
    present_before = bool(_git(
        repo, "rev-parse", "--verify", f"{accepted_source}^{{commit}}",
        check=False))

    fetch = subprocess.run([
        "git", "fetch", "--force", "--no-tags", "--no-recurse-submodules",
        "--depth=1", remote, accepted_source,
    ], cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
       check=False)
    if fetch.returncode != 0:
        detail = (fetch.stderr or fetch.stdout).strip().replace("\n", " ")
        raise ValueError(f"accepted_source_fetch_failed:{detail[:300]}")
    fetched_commit = _resolve(repo, "FETCH_HEAD", "commit")
    if fetched_commit != accepted_source:
        raise ValueError("accepted_source_fetch_head_mismatch")
    resolved_commit = _resolve(repo, accepted_source, "commit")
    if resolved_commit != accepted_source:
        raise ValueError("accepted_source_commit_mismatch")
    resolved_tree = _resolve(repo, resolved_commit, "tree")
    if resolved_tree != accepted_tree:
        raise ValueError("accepted_source_tree_mismatch")

    resolved_candidate = _resolve(repo, candidate_sha, "commit")
    resolved_candidate_tree = _resolve(repo, resolved_candidate, "tree")
    if resolved_candidate != candidate_sha:
        raise ValueError("candidate_commit_mismatch")
    if resolved_candidate_tree != candidate_tree:
        raise ValueError("candidate_tree_mismatch")

    release: Optional[Dict[str, Any]] = None
    if release_merge_sha is not None:
        resolved_release = _resolve(repo, release_merge_sha, "commit")
        resolved_release_tree = _resolve(repo, resolved_release, "tree")
        if resolved_release != release_merge_sha:
            raise ValueError("release_merge_commit_mismatch")
        if resolved_release_tree != release_merge_tree:
            raise ValueError("release_merge_tree_mismatch")
        if resolved_release_tree != candidate_tree:
            raise ValueError("release_merge_candidate_tree_mismatch")
        parents = _git(
            repo, "rev-list", "--parents", "-n", "1", resolved_release).split()
        if len(parents) != 3 or parents[0] != resolved_release \
                or parents[2] != candidate_sha:
            raise ValueError("release_merge_candidate_parent_mismatch")
        release = {"commitSha": resolved_release,
                   "treeSha": resolved_release_tree,
                   "candidateParentSha": parents[2]}

    semantic = validate_product_semantic_diff(candidate_sha, repo=repo)
    manifest = _manifest_identity(repo)
    body: Dict[str, Any] = {
        "schemaVersion": SCHEMA,
        "status": "PASS",
        "remote": {"name": remote, "url": remote_url},
        "fetch": {
            "requestedCommitSha": accepted_source,
            "fetchHeadCommitSha": fetched_commit,
            "depth": 1,
            "noTags": True,
            "sourcePresentBeforeFetch": present_before,
            "initialCheckoutShallow": shallow_before,
            "postFetchShallow": _git(
                repo, "rev-parse", "--is-shallow-repository") == "true",
        },
        "acceptedSource": {"commitSha": resolved_commit,
                           "treeSha": resolved_tree},
        "candidate": {"commitSha": resolved_candidate,
                      "treeSha": resolved_candidate_tree},
        "releaseMerge": release,
        "productVersion": PRODUCT_VERSION,
        "certificateDigest": certificate["certificateDigest"],
        "acceptedFixManifestDigest": sha256_hex(manifest),
        "semanticDiff": semantic,
    }
    body["provenanceDigest"] = sha256_hex(body)
    return body


def validate_receipt(
        value: Mapping[str, Any], *, candidate_sha: str, candidate_tree: str,
        certificate_digest: str, release_merge_sha: Optional[str] = None,
        release_merge_tree: Optional[str] = None,
        repo: pathlib.Path = ROOT) -> Dict[str, Any]:
    if type(value) is not dict:
        raise ValueError("source_provenance_receipt_object_required")
    receipt = dict(value)
    digest = receipt.pop("provenanceDigest", None)
    expected_keys = {
        "schemaVersion", "status", "remote", "fetch", "acceptedSource",
        "candidate", "releaseMerge", "productVersion", "certificateDigest",
        "acceptedFixManifestDigest", "semanticDiff",
    }
    if set(receipt) != expected_keys or type(digest) is not str \
            or len(digest) != 64 or digest != sha256_hex(receipt) \
            or receipt.get("schemaVersion") != SCHEMA \
            or receipt.get("status") != "PASS" \
            or receipt.get("acceptedSource") != {
                "commitSha": ACCEPTED_V13_SOURCE,
                "treeSha": ACCEPTED_V13_TREE} \
            or receipt.get("candidate") != {
                "commitSha": candidate_sha, "treeSha": candidate_tree} \
            or receipt.get("productVersion") != PRODUCT_VERSION \
            or receipt.get("certificateDigest") != certificate_digest:
        raise ValueError("source_provenance_receipt_invalid")
    fetch = receipt.get("fetch")
    remote = receipt.get("remote")
    if type(fetch) is not dict or set(fetch) != {
            "requestedCommitSha", "fetchHeadCommitSha", "depth", "noTags",
            "sourcePresentBeforeFetch", "initialCheckoutShallow",
            "postFetchShallow"} \
            or fetch.get("requestedCommitSha") != ACCEPTED_V13_SOURCE \
            or fetch.get("fetchHeadCommitSha") != ACCEPTED_V13_SOURCE \
            or fetch.get("depth") != 1 or fetch.get("noTags") is not True \
            or type(fetch.get("sourcePresentBeforeFetch")) is not bool \
            or type(fetch.get("initialCheckoutShallow")) is not bool \
            or type(fetch.get("postFetchShallow")) is not bool \
            or type(remote) is not dict or set(remote) != {"name", "url"} \
            or remote.get("name") != "origin" \
            or _validate_remote(remote.get("url", ""), allow_local_remote=False) \
            != remote.get("url"):
        raise ValueError("source_provenance_fetch_receipt_invalid")
    expected_release = None
    if release_merge_sha is not None or release_merge_tree is not None:
        if release_merge_sha is None or release_merge_tree is None:
            raise ValueError("release_merge_identity_incomplete")
        expected_release = {"commitSha": release_merge_sha,
                            "treeSha": release_merge_tree,
                            "candidateParentSha": candidate_sha}
    if receipt.get("releaseMerge") != expected_release:
        raise ValueError("source_provenance_release_merge_mismatch")
    semantic = validate_product_semantic_diff(candidate_sha, repo=repo)
    if receipt.get("semanticDiff") != semantic:
        raise ValueError("source_provenance_semantic_diff_mismatch")
    if receipt.get("acceptedFixManifestDigest") != sha256_hex(
            _manifest_identity(repo)):
        raise ValueError("source_provenance_manifest_mismatch")
    receipt["provenanceDigest"] = digest
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=str(ROOT))
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--accepted-source", required=True)
    parser.add_argument("--accepted-tree", required=True)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--candidate-tree", required=True)
    parser.add_argument("--release-merge-sha", default="")
    parser.add_argument("--release-merge-tree", default="")
    parser.add_argument("--certificate", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    receipt = acquire_source(
        repo=pathlib.Path(args.repo_root), remote=args.remote,
        accepted_source=args.accepted_source, accepted_tree=args.accepted_tree,
        candidate_sha=args.candidate_sha, candidate_tree=args.candidate_tree,
        certificate_path=pathlib.Path(args.certificate),
        release_merge_sha=args.release_merge_sha or None,
        release_merge_tree=args.release_merge_tree or None)
    _write(pathlib.Path(args.out), receipt)
    print("V13_5_ACCEPTED_SOURCE_PROVENANCE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
