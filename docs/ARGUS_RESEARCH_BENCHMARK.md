# Research Benchmark (v12.6.2)
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

Gemini preflightは本文を保存せず、candidate/finishReason/parts/thinking usageを
最大3回確認する。previewが3回ともprovider defectで、Models APIが返す最新の
明示的stable Proだけが最小応答に成功した場合に限り、そのexact model IDを
baselineへ記録して一度限りの正式runを閉じる。
