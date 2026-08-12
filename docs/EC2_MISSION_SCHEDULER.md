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
bash scripts/install_argus_mission_timer.sh --dry-run
sudo bash scripts/install_argus_mission_timer.sh --apply
sudo systemctl list-timers argus-mission-tick.timer --no-pager
sudo bash /opt/argus/scripts/check_argus_mission_timer.sh
```

timerはUTCの毎時07分・37分に自然起動します。`Persistent=true`ですが、
backendのcatch-up候補は最大2 windowで、古いwindowを現在扱いで無制限実行
しません。

Remote Journal re-armは別のoneshot timerとしてUTC毎時13分・43分に動き、
直前のmissionをブロックしません。installerはファイルを配置するだけで、
`daemon-reload`、enable、start、restartを実行しません。新timerの初回有効化は
実行直前の別途明示owner承認が必要なEC2変更です。今回のコード/Draft PR/CI
承認には含まれません。

re-arm専用credentialは、installer実行前にsecret managerなどのout-of-band
手段で`/etc/argus-remote-journal-rearm.env`へ配置します。owner/group/modeは
`root:argus-rearm 0640`（書込みを禁止する場合は`0440`も可）とし、空行・commentを
除く内容は次の1 assignmentだけにします。値をshell history、引数、journal、
installer出力へ記録しません。installerはこのfileを作成、上書き、backup
しません。専用system user/group `argus-rearm`もout-of-bandで作成し、installerは
存在とfile可読性を検証するだけで作成・変更しません。

```text
ARGUS_REMOTE_JOURNAL_REARM_PAT=<redacted>
```

fine-grained PATはrepositoryを`mitsugue/argus`だけに限定し、repository
permissionはActionsのwrite（workflow dispatch）だけを付与します。Metadataの
readはGitHubが自動付与する範囲だけとし、Contents、Administration、Secrets等の
追加権限は付与しません。期限と失効手順もsecret manager側で管理します。

配置内容、credential preflight、dry-run、applyのread-backを確認した後、
次の2 commandはre-arm timerだけを対象とし、実行直前にownerが別途明示承認
した後にのみ実行します。

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now argus-remote-journal-rearm.timer
```

この初回操作は新しいre-arm timerだけが対象です。既存mission serviceや
backendをrestartしません。

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
