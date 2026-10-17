# ARGUS Forecast Issuance (v12.2.7)
- 冪等キー: symbol×セッション日×targetType×horizon×epoch(issuedAtは一意性に使わない)。
- v12.2.6でlive予測0だった診断: 発行ミッション(JP 08:30)がデプロイ直後のコールド期に消費され、同日回収の条件(warm_consumed同日checkpoint)が狭すぎた。
- v12.2.7: forecast_issuance_decision — eligible/wait_next_session/recovered_intraday_eligible/stale_opportunity/insufficient_data/mock_blocked/duplicate。回収発行はザラ場(09:00-13:00 JST)のみ・**backdate禁止(informationCutoffAt=実時刻)**・13時以降は「意味が薄い」として翌セッション待ち。曖昧な「未発行」は出さない(DQに判定+次機会)。
- 発行は耐久ジャーナル(forecast_issued)へ即時記録後に成立扱い。
