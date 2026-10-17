# ARGUS AI Call Paths — Inventory (v12.2.0 Phase 0)

Baseline: HEAD 9acf1c4 / v12.1.7 / 1579 tests green.
全プロバイダ呼び出しの台帳。v12.2.0以降、新しい直接呼び出しの追加は
`test_argus_v12_2_0.py` のgrepガードで失敗する(承認リスト方式)。

| # | file:function | provider | model source | 用途 | tools | privacy | store | usage捕捉 | cost捕捉 | fallback | bench適格 | trigger |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | scanner.py:gemini_score_stocks | Gemini | 固定 gemini-2.5-flash | 旧スコアリング(レガシー・低使用) | なし | redacted設計 | n/a | あり | あり | なし | 不可 | 内部 |
| 2 | scanner.py:_openai_judge | OpenAI | _OPENAI_MODEL | AI判定(主判定) | なし | owner文脈(サーバー内) | **store=False必須(v12.2.0)** | 同一応答 | _ai_record_cost | chat.completions(degraded) | 不可 | cron/admin |
| 3 | scanner.py:_gemini_check | Gemini | _GEMINI_JUDGE_MODEL | 判定の検算 | なし | 同上 | n/a | 同一応答 | あり | flash fallback | 不可 | cron/admin |
| 4 | scanner.py:_openai_prose | OpenAI | _OPENAI_MODEL | 解説文(状態管理済み) | なし | redacted | **store=False必須** | 同一応答 | あり | chat(degraded) | 不可 | cron/admin |
| 5 | scanner.py:12706/12727 | OpenAI/Gemini | _OPENAI_MODEL/_GEMINI_JUDGE_MODEL | 再判定/レフェリー | なし | owner文脈 | **store=False必須** | 同一応答 | あり | chat(degraded) | 不可 | cron/admin |
| 6 | scanner.py:12861 | Gemini | _GEMINI_FALLBACK_MODEL | 翻訳/軽処理 | なし | 公開見出しのみ | n/a | あり | あり | なし | 不可 | cron |
| 7 | scanner.py:_openai_research | OpenAI | role router(v12.2.0) | LIVE web調査(なぜ動いた/GPTスカウト) | web_search | redacted | **store=False必須** | 同一応答 | あり | **no-tool=model_only(明示ラベル・検証済み調査に偽装不可)** | web_search時のみ | cron/admin |
| 8 | scanner.py:_gemini_osint | Gemini | _GEMINI_JUDGE_MODEL | OSINTスカウト(grounding) | google_search | redacted既定 | n/a | 同一応答 | grounding/call | なし | 可 | cron/admin |
| 9 | scanner.py:_gpt_osint | OpenAI | role router(v12.2.0) | OSINTスカウト(web_search) | web_search | redacted既定 | **store=False必須** | 同一応答 | あり | model_onlyは`aiEvidenceLevel=model_only` | web_search時のみ | cron/admin |

## v12.2.0 ルール(AI Integrity Gate)

- すべての `responses.create` は `store=False` 必須(grepテストで恒久ガード)。
- usageは**同一応答オブジェクト**から取得(共有グローバル禁止)。
- `_openai_research` の no-tool フォールバックは `model_only` として返り、
  検証済み調査・主因証拠・ベンチマーク基準に使用不可。
- chat.completions フォールバックは degraded(bench不適格・DQ表示)。
- 新しい直接呼び出しは `argus_ai_gate.APPROVED_CALL_SITES` に登録がなければテスト失敗。
- 公開ルートからの外部AI起動なし(全てcron/admin経路)。

## モデル設定(v12.2.0 Phase 2)

- `ARGUS_OPENAI_MODEL_EXTRACT` / `_STANDARD` / `_WAR_ROOM` / `_REFEREE` / `_ROLLBACK`
- `ARGUS_OPENAI_SHADOW_ENABLED`(既定0) / `ARGUS_OPENAI_SHADOW_SAMPLE_RATE`
- GPT-5.6系は**能力プローブ(admin)で確認されるまで使用しない**。昇格はゲート後のみ。
