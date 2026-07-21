# Research Benchmark (v12.7.9)

Protocol v1はholdout消費済みのまま`closed_invalid`としてappend-only保存し、
再実行しない。Protocol v2は新規36ケースpoolからSHA256 seedでcalibration 6、
holdout 12、reserve 18を層化抽出する。transport/parse/一回性等のprotocol
validityと、一次情報・証拠・時点規律・捏造等の品質点を分離する。

正式v2はGemini `gemini-3.1-pro-preview`、ARGUS generator
`gpt-5.6-sol`、blind referee `gpt-5.6-terra`を用い、requested modelと
実response modelを保存する。generator/referee同一modelはfail-closed、
hard capは2,000円、定期実行とholdout再利用は禁止する。
- 基準runにepochId刻印(provider:model:promptVersion:toolMode:schemaVersion)。異エポック比較禁止。
- rubric-v2(argus_osint_engine.RUBRIC_VERSION)— 重みの無言変更禁止。
- ホールドアウト3ケース(stale/no_news/direct_disclosure)=チューニング不使用。
- 2xゲート: 校正済み+confidence medium以上+比2.0+具体未回収ゼロ+一次強度+not cold/budget/degraded/mock。
- 単発run比率はlegacy/provisional表示。比率は2.0でキャップされない(3x/4x可)。

正式runはadmin確認付き`RESEARCH_BENCHMARK` background jobからだけ開始する。
通常schedule/page loadは開始不可。2026-07-20 pricing contractはGemini
`gemini-3.1-pro-preview`、ARGUS generator `gpt-5.6-sol`、blind referee
`gpt-5.6-terra`で、各応答のexact model IDとusageを保存する。generatorと
refereeの実応答modelが同一、dataset hash不一致、hard cap 2,000円超過、
またはholdout消費済みの場合はfail-closedとする。

GPT-5.6 generator/refereeはResponses APIでreasoning effort `low`、出力上限
4,096 tokenに固定する。正式run前のpipeline preflightは検索・referee契約だけを
確認し、dataset採点・holdout消費を行わない。provider失敗がcalibration完了前かつ
holdout未消費の場合だけ、証跡を保持したままcalibration試行を合計3回まで許可する。
Provider可用性は非空応答・usage・実model ID・errorなしで判定し、指定文字列との
完全一致は診断証拠として分離する。正式run内のprobeはCost Policyの
`research_benchmark`用途で認可し、case実行前のpreflight失敗はcalibration試行へ
算入しない。

`remoteJournalReadBack` gateはRemote Journal cycleのverified receipt、expected/
actual hash一致、remote commit SHAを確認する。再deployで失われるMarket Ledger補助
フラグを正式benchmark validityの正本にはしない。

Gemini preflightは本文を保存せず、candidate/finishReason/parts/thinking usageを
最大3回確認する。previewが3回ともprovider defectで、Models APIが返す最新の
明示的stable Proだけが最小応答に成功した場合に限り、そのexact model IDを
baselineへ記録して一度限りの正式runを閉じる。
