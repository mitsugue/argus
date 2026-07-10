# Research Benchmark (v12.2.0)
- 基準runにepochId刻印(provider:model:promptVersion:toolMode:schemaVersion)。異エポック比較禁止。
- rubric-v2(argus_osint_engine.RUBRIC_VERSION)— 重みの無言変更禁止。
- ホールドアウト3ケース(stale/no_news/direct_disclosure)=チューニング不使用。
- 2xゲート: 校正済み+confidence medium以上+比2.0+具体未回収ゼロ+一次強度+not cold/budget/degraded/mock。
- 単発run比率はlegacy/provisional表示。比率は2.0でキャップされない(3x/4x可)。
