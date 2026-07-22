# EC2 Primary Mission Scheduler

A.R.G.U.S. v12.3.2以降、30分mission tickのauthorityは次の順です。

1. `ec2_systemd` — primary
2. `github_schedule` — backup
3. `manual` — diagnostic only

同一`missionWindowId`はbackendのleaseを最初に取得した1回だけ処理されます。
後続sourceは`duplicate_suppressed`となり、Outcome retry、Journal event、Soak
heartbeat、AI処理を重複実行しません。

## EC2への配置

EC2上のrepository rootで実行します。既存`/etc/argus-bridge.env`の
`ARGUS_ADMIN_TOKEN`を再利用し、値を引数やjournalへ出しません。

```bash
sudo bash scripts/install_argus_mission_timer.sh
sudo systemctl list-timers argus-mission-tick.timer --no-pager
sudo bash /opt/argus/scripts/check_argus_mission_timer.sh
```

timerはUTCの毎時07分・37分に自然起動します。`Persistent=true`ですが、
backendのcatch-up候補は最大2 windowで、古いwindowを現在扱いで無制限実行
しません。

## 監視

```bash
systemctl status argus-mission-tick.timer --no-pager
journalctl -u argus-mission-tick.service -n 20 --no-pager
```

journalは公開安全な構造化項目だけです。自然30分テストでは異なる2つの
`missionWindowId`、`triggerSource=ec2_systemd`、Journal read-back、Outcome
retry、Soak heartbeat、build SHA、Cost PolicyのAI実行0を確認します。

## Build identityの自動同期 (v13.0.1)

各tickの直前に、公開GitHub main refを独立した期待SHAとして取得し、backendの
`/healthz`が返す実SHAと照合します。backend側の自己申告だけで期待SHAを決める
ことはありません。main先行時は15分のdeploy移行graceとしてexpected skipし、
一致後にroot-owned stateへ確認済みSHAを原子的保存します。GitHub一時不達時は、
backendと一致する最後の確認済みSHAだけを復元利用します。不一致がgraceを超えた
場合は`deployment_transition_timeout`で赤く失敗します。

Soak開始後はruntime、version、scheduler設定、Soak定義を変更しません。
