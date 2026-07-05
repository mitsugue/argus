import React, { useMemo } from 'react';
import { PageShell } from './PageShell';
import { AlertCard } from '../components/dashboard/AlertCard';
import { useActionAlerts } from '../hooks/useActionAlerts';
import { useAssets } from '../hooks/useAssets';
import { DecisionQualityCard } from '../components/dashboard/DecisionQualityCard';
import { LearningDashboardCard } from '../components/dashboard/LearningDashboardCard';
import { useJapanWatchlist } from '../hooks/useJapanWatchlist';
import { useUSWatchlist } from '../hooks/useUSWatchlist';
import { useCryptoWatchlist } from '../hooks/useCryptoWatchlist';
import { useRatesSnapshot } from '../hooks/useRatesSnapshot';
import { useFundNav } from '../hooks/useFundNav';
import { buildExposure } from '../lib/portfolio';
import { coingeckoIdOf } from '../lib/cryptoIds';
import { jpDisplay } from '../lib/displayName';
import { buildPositionExposure } from '../domain/positionExposure';
import { publishExposure, latestScenarios, latestPlans, latestStrategy } from '../lib/positionExposureShare';
import { buildPortfolioScenario, DOM_JA, DOM_TONE } from '../domain/scenario';
import { planPortfolioSummary } from '../domain/positionPlan';
import { FIRE_TONE, BUDGET_JA, STRATEGY_COMPLIANCE_JA } from '../domain/portfolioStrategy';
import { FireCoreCard } from '../components/dashboard/FireCoreCard';
import { coreActionFor } from '../lib/todayCall';
import { genreOf } from '../types/assetItem';
import type { CorePosition } from '../types/dashboard';
import { SignedValue } from '../components/common/SignedValue';
import { getNumericTone, TONE_VAR } from '../lib/numericTone';
import { useLocale, t, tEn } from '../i18n';
import '../components/dashboard/Dashboard.css';

// 資産クラス司令室 (command-center-v1, v10.13 — user-approved 案A):
// 旧「Core Portfolio」(mockの積立表示)を、目標②「金・REIT・債券・仮想通貨の
// 追加/利確/比率調整」のための1ページに作り替え。
//   1. あなたの配分(実保有の現在地・円換算)
//   2. 8資産クラスのライブ判断(保有していないクラスもここで見る)
//   3. 積立方針(実際のコアファンド+姿勢連動の方針)
// 数量・取得単価は端末内のみ(従来どおり)。

const fmtJpy = (v: number) => `¥${Math.round(v).toLocaleString('ja-JP')}`;

export const CorePortfolio: React.FC = () => {
  useLocale();   // re-render on locale switch
  const { cards, posture, phase } = useActionAlerts();
  const assetsApi = useAssets();
  const { assets } = assetsApi;
  const { funds: navFunds } = useFundNav();   // 投信 基準価額(NAV) follow
  const rates = useRatesSnapshot();
  const usdJpy = rates.data?.usdJpy?.latestValue ?? null;

  const jpSyms = useMemo(() => assets.filter((a) => a.market === 'JP').map((a) => a.symbol), [assets]);
  const usSyms = useMemo(() => assets.filter((a) => a.market === 'US').map((a) => a.symbol), [assets]);
  const jp = useJapanWatchlist(jpSyms);
  const us = useUSWatchlist(usSyms);
  const cryptoPairs = useMemo(
    () => assets
      .filter((a) => a.market === 'CRYPTO')
      .map((a) => ({ symbol: a.symbol, id: coingeckoIdOf(a) }))
      .filter((p) => p.id),
    [assets],
  );
  const crypto = useCryptoWatchlist(useMemo(() => cryptoPairs.map((p) => p.id), [cryptoPairs]));

  const priceOf = useMemo(() => {
    // value at the last known price (live OR delayed close), not just live — so a closed
    // market's holdings (e.g. JP after 15:30) still price and its currency total shows.
    const ok = (st?: string) => st != null && st !== 'mock';
    const m = new Map<string, number>();
    for (const s of jp.data?.stocks ?? []) if (ok(s.status) && Number.isFinite(s.price)) m.set(s.symbol, s.price);
    for (const s of us.data?.stocks ?? []) if (ok(s.status) && Number.isFinite(s.price)) m.set(s.symbol, s.price);
    for (const p of cryptoPairs) {
      const q = crypto.byId[p.id];
      if (q && ok(q.status) && Number.isFinite(q.priceUsd)) m.set(p.symbol, q.priceUsd);
    }
    return (a: { symbol: string }) => m.get(a.symbol);
  }, [jp.data, us.data, crypto.byId, cryptoPairs]);

  const exp = useMemo(() => buildExposure(assets, priceOf, usdJpy), [assets, priceOf, usdJpy]);
  // V11.8.0 exposure dashboard — themes/currency/top positions/risk flags.
  // Device-local math over localStorage holdings; nothing is uploaded.
  const pe = useMemo(() => {
    const out = buildPositionExposure(assets, priceOf, usdJpy, {});
    publishExposure(out);
    return out;
  }, [assets, priceOf, usdJpy]);

  // 積立方針 — ユーザーの実ファンド + 姿勢連動アクション(Action Alertsと同一ロジック)。
  const funds: CorePosition[] = useMemo(() => {
    const act = coreActionFor(posture ?? undefined);
    return assets
      .filter((a) => genreOf(a) === 'funds')
      .slice()
      .sort((a, b) => a.sortOrder - b.sortOrder)
      .map((a) => ({
        symbol: a.symbol,
        name: a.displayNameJa || a.displayName,
        market: 'JP' as const,
        action: act.action,
        reason: act.reason,
      }));
  }, [assets, posture]);

  return (
    <PageShell
      title={tEn('nav.corePortfolio')}
      subtitle={
        <span>
          資産クラス司令室 — 配分の現在地と、クラスごとの「いま取るべき構え」。
          <span className="today-phase"> - {phase === 'connecting' ? 'connecting...' : phase}{posture ? ` · posture ${posture}` : ''}</span>
        </span>
      }
    >
      <section>
        <div className="section-head">
          <span className="section-head__title">{t('cp.yourAllocation')}</span>
          <span className="section-head__count">
            {exp.combinedJpy != null ? `${t('cp.total')} ${fmtJpy(exp.combinedJpy)}` : t('cp.noLivePos')}
          </span>
        </div>
        <div className="card cmd-alloc">
          {exp.byGenre.length > 0 ? (
            <>
              {exp.byGenre.map((g) => (
                <div className="cmd-alloc__row" key={g.key}>
                  <span className="cmd-alloc__name">{g.title}</span>
                  <span className="cmd-alloc__bar"><span style={{ width: `${Math.min(100, g.pct)}%` }} /></span>
                  <span className="cmd-alloc__pct">{g.pct.toFixed(1)}%</span>
                  <span className="cmd-alloc__val">{fmtJpy(g.valueJpy)}</span>
                </div>
              ))}
              {exp.combinedPlJpy != null && (
                <div className="cmd-alloc__pl" style={{ color: TONE_VAR[getNumericTone(exp.combinedPlJpy)] }}>
                  {t('cp.unrealizedPl')} {exp.combinedPlJpy >= 0 ? '+' : ''}{fmtJpy(exp.combinedPlJpy)}
                </div>
              )}
              {exp.unpriced.length > 0 && (
                <div className="cmd-alloc__note">{t('cp.unpriced')} {exp.unpriced.join(', ')}</div>
              )}
            </>
          ) : (
            <p className="cmd-alloc__empty">
              {t('cp.emptyAlloc')}
            </p>
          )}
        </div>
      </section>

      {/* PORTFOLIO SCENARIO (v11.17.0) — 保有全体の条件付き分岐(端末内合成)。
          Todayを開いた後に計算済みシナリオから合成。単一予測・売買指示なし。 */}
      {(() => {
        const allSets = latestScenarios();
        const heldSets = allSets.filter((s) => s.isHeld);
        const ps = buildPortfolioScenario(heldSets);
        return (
          <section>
            <div className="section-head">
              <span className="section-head__title">PORTFOLIO SCENARIO</span>
              <span className="section-head__count">条件付き分岐 · 売買指示なし</span>
            </div>
            <div className="card cmd-alloc">
              {!ps ? (
                <p className="cmd-alloc__note">
                  {allSets.length === 0
                    ? 'Todayページを一度開くと、保有銘柄の支配シナリオからポートフォリオ全体の分岐を表示します(端末内計算)。'
                    : '保有数量が未入力のため、ポートフォリオ・シナリオは表示できません(Watchlistで保有数量を入力すると端末内で合成されます。捏造しません)。'}
                </p>
              ) : (
                <>
                  <p className="cmd-alloc__note" style={{ fontSize: 12.5 }}>
                    <b style={{ color: DOM_TONE[ps.dominant] }}>{DOM_JA[ps.dominant]}</b>
                    <span style={{ marginLeft: 6 }}>{ps.summaryJa}</span>
                  </p>
                  <p className="cmd-alloc__note" style={{ color: 'var(--text-faint)' }}>{ps.detailJa}</p>
                  <p className="cmd-alloc__note" style={{ fontSize: 10, color: 'var(--text-faint)' }}>
                    条件付きシナリオであり予測でも売買指示でもありません(確率は帯のみ)。銘柄別の無効化条件はTodayの各カード→SCENARIOSで。
                  </p>
                </>
              )}
            </div>
          </section>
        );
      })()}

      {/* FIRE CORE / MUTUAL FUNDS (v11.19.1) — 投信=FIREの本丸資産の追跡。
          口数×日次NAV or 手動評価額・積立・口座区分。端末内のみ。 */}
      <FireCoreCard assetsApi={assetsApi} />

      {/* PORTFOLIO STRATEGY / FIRE ALIGNMENT (v11.19.0) — 短期の計画とFIRE目的を
          接続する戦略層(端末内合成)。免許業の助言ではない・売買指示でもない。 */}
      {(() => {
        const s = latestStrategy();
        return (
          <section>
            <div className="section-head">
              <span className="section-head__title">PORTFOLIO STRATEGY / FIRE ALIGNMENT</span>
              <span className="section-head__count">概算 · 助言ではない</span>
            </div>
            <div className="card cmd-alloc">
              {!s ? (
                <p className="cmd-alloc__note">
                  Todayページを一度開くと、保有構成から戦略判定(コア/サテライト/戦術枠・FIRE整合)を端末内で合成します。
                </p>
              ) : (
                <>
                  <p className="cmd-alloc__note" style={{ fontSize: 12.5 }}>
                    <b style={{ color: FIRE_TONE[s.fireStatus], border: `1px solid ${FIRE_TONE[s.fireStatus]}`,
                                borderRadius: 999, padding: '0 8px' }}>
                      FIRE整合: {s.fireStatusJa}
                    </b>
                    <span style={{ marginLeft: 6, color: 'var(--text-sub)' }}>{s.summaryJa}</span>
                  </p>
                  {!s.noHoldings && (
                    <p className="cmd-alloc__note" style={{ color: 'var(--text-sub)' }}>
                      戦術枠(短期勝負): <b>{BUDGET_JA[s.tacticalBudget]}</b>(約{Math.round(s.tacticalPct)}%)
                      · AIテーマ合計 約{Math.round(s.aiThemePct)}%
                      · 金 約{Math.round(s.goldPct)}% · 暗号資産 約{Math.round(s.cryptoPct)}%
                    </p>
                  )}
                  <p className="cmd-alloc__note">{s.riskJa}</p>
                  {s.warningsJa.map((w) => (
                    <p key={w.slice(0, 12)} className="cmd-alloc__note" style={{ color: 'var(--amber, #fbbf24)' }}>⚠ {w}</p>
                  ))}
                  {s.opportunitiesJa.map((o) => (
                    <p key={o.slice(0, 12)} className="cmd-alloc__note" style={{ color: 'var(--text-sub)' }}>◇ {o}</p>
                  ))}
                  {s.stressNotesJa.length > 0 && (
                    <details>
                      <summary style={{ cursor: 'pointer', fontSize: 10, color: 'var(--text-faint)' }}>ポートフォリオのストレスシナリオを見る</summary>
                      {s.stressNotesJa.map((n) => (
                        <p key={n.slice(0, 12)} className="cmd-alloc__note" style={{ fontSize: 10.5 }}>・{n}</p>
                      ))}
                    </details>
                  )}
                  <p className="cmd-alloc__note" style={{ fontSize: 10.5, color: 'var(--text-faint)' }}>
                    次の確認: {s.nextChecksJa.join(' / ')}
                  </p>
                  <p className="cmd-alloc__note" style={{ fontSize: 10.5, color: 'var(--text-faint)' }}>
                    不足データ: {s.missingDataJa.join(' / ')}(不足分は判定に使わず、捏造しません)
                  </p>
                  <p className="cmd-alloc__note" style={{ fontSize: 10, color: 'var(--text-faint)' }}>
                    {STRATEGY_COMPLIANCE_JA} 判定は帯のみで、達成見込みの精密計算はしません。
                  </p>
                </>
              )}
            </div>
          </section>
        );
      })()}

      {/* PORTFOLIO PLANNING (v11.18.0) — どこで追加可/ブロック/利確検討/イベント
          待ちか(端末内合成)。計画であり売買指示ではない。 */}
      {(() => {
        const ps = planPortfolioSummary(latestPlans());
        if (!ps) return null;
        return (
          <section>
            <div className="section-head">
              <span className="section-head__title">PORTFOLIO PLANNING</span>
              <span className="section-head__count">計画サマリ · 売買指示なし</span>
            </div>
            <div className="card cmd-alloc">
              <p className="cmd-alloc__note" style={{ fontSize: 12 }}>{ps.summaryJa}</p>
              {ps.rows.map((r) => (
                <p key={r.label} className="cmd-alloc__note" style={{ margin: '3px 0 0' }}>
                  <b style={{ color: r.tone }}>{r.label}</b>
                  <span style={{ marginLeft: 6, color: 'var(--text-sub)' }}>{r.names.join(' / ')}</span>
                </p>
              ))}
              <p className="cmd-alloc__note" style={{ fontSize: 10, color: 'var(--text-faint)' }}>
                比率の高い銘柄は追加より先にリスク確認。詳細条件はTodayの各カード→POSITION PLANで。
                これは計画であり売買指示ではありません(注文機能はありません)。
              </p>
            </div>
          </section>
        );
      })()}

      {/* v11.19.1 (owner request): PORTFOLIO SYNC & BACKUP moved to the new
          Backup page — all backup ops now live in ONE place. Pointer only. */}
      <p className="cmd-alloc__note" style={{ margin: '2px 0 8px', fontSize: 11.5, color: 'var(--text-faint)' }}>
        バックアップ操作(暗号化バックアップ設定・JSON書き出し/読み込み・スナップショット・復元ドリル)は
        左ナビの「<b>Backup</b>」ページに集約しました。
      </p>

      {/* DECISION QUALITY (v11.11.0) — 過去判断の答え合わせ(端末内・成績断定なし) */}
      <DecisionQualityCard />

      {/* LEARNING DASHBOARD (v11.15.0) — ラベル別の学習レビュー(端末内・成績断定なし) */}
      <LearningDashboardCard />

      {/* EXPOSURE DASHBOARD (v11.8.0) — テーマ/通貨/集中度/リスクフラグ。
          保有未入力なら未入力と正直に表示(端末内計算・売買指示なし)。 */}
      <section>
        <div className="section-head">
          <span className="section-head__title">EXPOSURE DASHBOARD</span>
          <span className="section-head__count">偏りの点検 · 端末内計算</span>
        </div>
        <div className="card cmd-alloc">
          {pe.noHoldings ? (
            <p className="cmd-alloc__empty">
              ポジション数量・取得単価が未入力のため、保有リスクは暫定です。
              Watchlistの銘柄行で入力すると、テーマ集中・通貨偏り・銘柄集中を判定します(端末内のみ)。
            </p>
          ) : (
            <>
              {pe.byTheme.slice(0, 6).map((tRow) => (
                <div className="cmd-alloc__row" key={tRow.key}>
                  <span className="cmd-alloc__name">{tRow.ja}</span>
                  <span className="cmd-alloc__bar"><span style={{ width: `${Math.min(100, tRow.pct)}%` }} /></span>
                  <span className="cmd-alloc__pct">{tRow.pct.toFixed(1)}%</span>
                  <span className="cmd-alloc__val">{fmtJpy(tRow.valueJpy)}</span>
                </div>
              ))}
              {pe.jpyPct != null && pe.usdPct != null && (
                <div className="cmd-alloc__note">通貨: 円建て {pe.jpyPct.toFixed(0)}% / ドル建て {pe.usdPct.toFixed(0)}%</div>
              )}
              {pe.top1Symbol && pe.top1Pct != null && (
                <div className="cmd-alloc__note">
                  最大集中: {jpDisplay(pe.top1Symbol, pe.notes[pe.top1Symbol]?.name)} {pe.top1Pct.toFixed(0)}%
                  {pe.singleNameRisk === 'critical' ? '(危険水準 — 1銘柄依存)'
                    : pe.singleNameRisk === 'high' ? '(高い)'
                    : pe.singleNameRisk === 'medium' ? '(やや高い)' : ''}
                </div>
              )}
              {pe.risks.slice(0, 3).map((r, i) => (
                <div className="cmd-alloc__note" key={i} style={{ color: r.riskLevel === 'high' || r.riskLevel === 'critical' ? 'var(--value-negative)' : undefined }}>
                  ⚠ {r.whyJa}
                </div>
              ))}
              {pe.unpriced.length > 0 && (
                <div className="cmd-alloc__note">価格未取得(暫定): {pe.unpriced.join(', ')}</div>
              )}
              <div className="cmd-alloc__note" style={{ fontSize: 10 }}>
                リスク点検であり売買指示ではありません。数量・単価は端末内のみ。
              </div>
            </>
          )}
        </div>
      </section>

      <section>
        <div className="section-head">
          <span className="section-head__title">{t('cp.classCalls')}</span>
          <span className="section-head__count">{cards.length} classes</span>
        </div>
        {/* Vocabulary legend (v10.191) — "待機/WAIT" was ambiguous ("do nothing?").
            Spell out that holding is fine; only NEW entries wait. */}
        <p className="alert-legend">
          <b>WAIT</b>=新規エントリーは見送り(保有は継続でOK) ・ <b>HOLD</b>=保有継続 ・
          <b>現金比率を上げる</b>=待機資金を厚くする ・ <b>TRIM/EXIT</b>=縮小/撤退。
          「待機」は“何もするな”ではなく“今は新規を入れない・持ち高は維持”の意味です。
        </p>
        <div className="alert-grid">
          {cards.map((c) => (
            <AlertCard key={c.assetClass} card={c} />
          ))}
        </div>
      </section>

      {/* 積立方針 + 基準価額を1つに統合 (v10.63): 各投信に「NAV・前日比」と
          「地合い連動の積立コメント」を同じ行で表示(重複セクションを解消)。 */}
      <section>
        <div className="section-head">
          <span className="section-head__title">{t('cp.accumPlan')}</span>
          <span className="section-head__count">{navFunds.length} funds</span>
        </div>
        <div className="card core-list">
          {navFunds.length > 0 ? navFunds.map((f) => {
            const act = coreActionFor(posture ?? undefined);
            const isCont = act.action === 'CONTINUE';
            return (
              <div className="core-row" key={f.code}>
                <div className="core-row__body">
                  <span className="core-row__top">{f.name}</span>
                  <span className="core-row__reason">{f.code} · {f.date} — {t(isCont ? 'cp.dca.continueReason' : 'cp.dca.deferReason')}</span>
                </div>
                <div style={{ textAlign: 'right', flex: 'none' }}>
                  <div style={{ fontWeight: 700 }}>¥{Math.round(f.navYen).toLocaleString('en-US')}</div>
                  <div style={{ fontSize: 12 }}>
                    {t('cp.dayChange')} {f.changePct == null ? '—' : <SignedValue value={f.changePct} suffix="%" arrow={false} />}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--value-positive)', marginTop: 2 }}>
                    ● {t(isCont ? 'cp.dca.continue' : 'cp.dca.deferLump')}
                  </div>
                </div>
              </div>
            );
          }) : <p className="cmd-alloc__empty">{t('cp.navLoading')}</p>}
          <div className="cmd-alloc__note" style={{ marginTop: 8 }}>
            基準価額=投信総合ライブラリー(資産運用業協会)の日次。積立方針は地合い連動(ドルコスト平均)で、個別の基準価額チャート判断ではありません。
          </div>
        </div>
      </section>
    </PageShell>
  );
};
