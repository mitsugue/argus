# Recovery Phase A — Public / Operational Boundary

## Outcome

PR B established the contracted boundary. V13 Compression Round 1 now reduces
that inventory to 158 contracts while preserving every authenticated
operator, owner-sync, and recovery-proof route. It is an API/product-boundary
change, not a recovery-authority change.

## Deterministic route inventory

`argus_route_catalog.py` declares every Flask rule with:

- route and methods;
- endpoint;
- trust domain and authentication policy;
- semantic mutation flag;
- response DTO family;
- consumer category.

The catalog contract test compares exact `(route, methods, endpoint)` tuples
with `app.url_map` and pins the accepted split:

- `PUBLIC=62`
- `AUTH_OPERATIONAL=87`
- `OWNER_SYNC=6`
- `RECOVERY_PROOF=3`

## Consumer disposition

| Surface/consumer | Disposition | Current contract |
|---|---|---|
| `/healthz` | `KEEP_PUBLIC` | minimal liveness/build DTO |
| `/readyz` | `KEEP_PUBLIC` | minimal readiness/build DTO; 200/503 truth unchanged |
| `/api/argus/data-quality/status` | `PRODUCT_DTO` | canonical fixed public diagnostics plus closed `systemHealth`; `/data-quality` and `/system-health` aliases retired |
| `/api/argus/events-active` | `PRODUCT_DTO` | active event list plus product-facing backbone fields; `/event-backbone-status` retired |
| remaining Action Label/JP-US quote/AI/visibility/Learning Memory snapshot consumers | `PRODUCT_DTO` | public GET is state-free and provider/ledger-cache-only; process-bootstrap/authenticated/background paths retain refresh authority |
| cached OSINT investigation | `PRODUCT_DTO` | verified-source allowlist; owner terms/raw agent claims excluded |
| Watchtower | `MOVE_TO_AUTH_OPERATIONAL` | existing Actions admin secret |
| breadth freshness runner | `MOVE_TO_AUTH_OPERATIONAL` | existing workflow admin secret |
| EC2 re-arm | `KEEP_PUBLIC` trigger + authenticated workflow verification | no new EC2 credential |
| memory snapshot/readback proof transport | `DEFER_TO_RECOVERY_PROOF` | cataloged; unchanged in PR B |
| static Data Quality/Command Center | `PRODUCT_DTO` | public-safe summary; rich panel removed |
| browser investigation/translation/vault mutations | `REMOVE` pending Security Gate | local no-op; no browser secret |

## DTO contracts

`argus_diagnostics_contract.py` is the sole serializer for the new DTOs.
Builders construct literal allowlists from scalar inputs. They do not spread or
copy internal dictionaries.

PublicDiagnosticsDTO is capped at 8 KiB and exposes only:

- response timestamp;
- liveness/readiness/overall state;
- semantic backend version and exact build SHA when available;
- coarse freshness counts and expected-disabled count;
- closed, bounded system-health lamps (`key`, `labelJa`, `status`, `detailJa`);
- conservative, non-authoritative recovery labels.

OperationalDiagnosticsDTO is capped at 512 KiB and exposes reviewed scalar
service, freshness, storage, durability, Remote Journal, feature, scheduler,
registry, OSINT, and cost-policy metadata. It never includes credentials,
owner payloads, prompts/model outputs, target/state identifiers, raw exception
strings, or extension maps.

## Hostile-field and error behavior

Tests inject eleven distinctive private-domain sentinels into Remote Journal
cycle, durable state, incidents, OSINT, mission/report/challenger/postmortem
collections, model output, owner data, AI integrity, and checkpoint V2 state.
Every one of the catalogued unauthenticated GET routes is requested with
network access disabled; none may serialize a sentinel. The mixed OSINT
investigation surface uses an explicit nested allowlist so raw agent synthesis,
owner terms, and future fields are not part of the public contract. Future
nested diagnostic fields must leave the public DTO byte-equivalent when
response time is fixed.

Unauthenticated operational requests and moved POSTs return a fixed 401 (or a
fixed 503 when admin auth is unavailable). Diagnostic builder failures return
fixed safe fallbacks. New code does not log tokens or raw exceptions.

## Intentional product changes

The static Data Quality page and AppShell consume one shared public diagnostics
snapshot containing service, freshness, system-health, and recovery-claim
lamps; the persistent `/system-health` polling lifecycle is gone. Rich
unauthenticated operational details are intentionally unavailable. Browser
buttons that formerly mutated server queues are intentionally non-operational
until a separate owner-authenticated browser architecture exists; they do not
fall back to exposing a token.

## Explicit non-regression boundary

PR B must remain byte/behavior neutral for WAL append/replay/framing,
checkpoint write/readback, compaction, recovery authority and encryption,
Remote Journal promotion/receipt authority, Stage1/V2 authority, Soak, and
investment decisions. No production environment/configuration change,
deployment, restart, or key enablement is part of this PR.

## 取得更新と分析窓の管理専用点検（準備）

既存の管理者認証付き診断へ `collectionHealth` を接続する。公開DTOは不変。
固定した六つの取得経路について、対象期間・データ更新・確認時刻・件数を別々に示す。
週次系列は保存時刻だけで鮮度を判定せず、対象週も読む。信用残は売残と買残が
両方そろう最新週、評価損益率は六入力の監査に合格した行だけを対象とする。
過去月報の補完を最新週の到着に見せない。名称設定は設定の妥当性だけを示し、
設定本文や検査対象の文字列は返さない。

VIX・TOPIX・米10年金利・ドル円の入力窓は3,000セッションの8割から警告する。
これは分析に渡す窓の件数であり、取得元の保存済み原表の容量ではない。
取得元の選択履歴は別に保持されるため、窓から外れたことを原本削除と混同しない。
ニュースのデータ更新時刻は新規記事が入った時だけ進め、同じ記事の巡回では進めない。
古い保存形式にこの時刻がない場合は不明とする。分析履歴の再計算成功は確認時刻だけに
使い、入力の実更新時刻が未計測の間は不明とする。表示・判断・実運用の完了は別に確認する。

この追加は管理用点検の入口である。取得元別の公式公表期限、定期ジョブの実行結果との
照合、手作業期限、本人認証された画面への表示、原本の容量・遠隔復元は未完了。

信用残と評価入力の定期取得点検は、対象週の古さとは別に「公表済みの最新対象週」
と「次の公表予定」を照合する。公式暦の実営業日2日後16時の計算を収集処理と
共有し、祝日を含める。暦の収録範囲外は不明、期限到来後に最新週がない場合は
取得遅れとして記録する。この予定時刻を当時の公表・受信時刻として保存しない。
