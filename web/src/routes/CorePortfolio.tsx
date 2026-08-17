import React, { useMemo } from 'react';
import type { UseAssets } from '../hooks/useAssets';
import type { AssetIntel } from '../hooks/useAssetIntel';
import { DecisionQualityCard } from '../components/dashboard/DecisionQualityCard';
import { LearningDashboardCard } from '../components/dashboard/LearningDashboardCard';
import { PortfolioExposureCard } from '../components/dashboard/PortfolioExposureCard';
import { PortfolioDecisionOverview } from '../components/dashboard/PortfolioDecisionOverview';
import { jpDisplay } from '../lib/displayName';
import { buildPortfolioDecisionOverview } from '../domain/portfolioDecisionView';
import { buildPortfolioScenario, DOM_JA, DOM_TONE } from '../domain/scenario';
import { planPortfolioSummary } from '../domain/positionPlan';
import { FIRE_TONE, BUDGET_JA, STRATEGY_COMPLIANCE_JA } from '../domain/portfolioStrategy';
import { FireCoreCard } from '../components/dashboard/FireCoreCard';
import { buildReviewPackMarkdown, copyPack } from '../lib/reviewPack';
import { genreOf } from '../types/assetItem';
import { SignedValue } from '../components/common/SignedValue';
import { getNumericTone, TONE_VAR } from '../lib/numericTone';
import { useLocale, t } from '../i18n';
import '../components/dashboard/Dashboard.css';

// 資産クラス司令室 (command-center-v1, v10.13 — user-approved 案A):
// 旧「Core Portfolio」(mockの積立表示)を、目標②「金・REIT・債券・仮想通貨の
// 追加/利確/比率調整」のための1ページに作り替え。
//   1. あなたの配分(実保有の現在地・円換算)
//   2. 8資産クラスのライブ判断(保有していないクラスもここで見る)
//   3. 積立方針(実際のコアファンド+姿勢連動の方針)
// 数量・取得単価は端末内のみ(従来どおり)。

const fmtJpy = (v: number) => `¥${Math.round(v).toLocaleString('ja-JP')}`;

export const CorePortfolio: React.FC<{
  assetsApi: UseAssets;
  portfolioIntel: AssetIntel;
}> = ({ assetsApi, portfolioIntel }) => {
  useLocale();   // re-render on locale switch
  const { assets } = assetsApi;
  const navFunds = portfolioIntel.fundNav.funds;
  const pe = portfolioIntel.positionExposure;
  const exp = pe.base;
  const portfolioOverview = useMemo(() => buildPortfolioDecisionOverview({
    combinedJpy: exp.combinedJpy,
    combinedPlJpy: exp.combinedPlJpy,
    pricedCount: exp.holdings.length,
    unpriced: pe.unpriced,
    noHoldings: pe.noHoldings,
    top1Symbol: pe.top1Symbol,
    top1Pct: pe.top1Pct,
    topThemeJa: pe.byTheme[0]?.ja ?? null,
    topThemePct: pe.byTheme[0]?.pct ?? null,
    jpyPct: pe.jpyPct,
    usdPct: pe.usdPct,
    risks: pe.risks,
    stressConditions: portfolioIntel.portfolioStrategy.stressNotesJa,
    nextPortfolioChecks: portfolioIntel.portfolioStrategy.nextChecksJa,
  }), [exp.combinedJpy, exp.combinedPlJpy, exp.holdings.length, pe,
    portfolioIntel.portfolioStrategy]);

  const content = (
    <>
      <PortfolioDecisionOverview view={portfolioOverview} />
      <details className="cp-workspace">
        <summary>Allocation / Risk / Plan / History</summary>
        <div className="cp-workspace__body">
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

      {/* Portfolio exposure remains contextual inside Holdings. */}
      <PortfolioExposureCard assets={assets} exp={exp} />

      {/* PORTFOLIO SCENARIO (v11.17.0) — 保有全体の条件付き分岐(端末内合成)。
          このrouteの正本フックから直接合成。単一予測・売買指示なし。 */}
      {(() => {
        const allSets = portfolioIntel.scenarioSets;
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
                    ? '銘柄別シナリオ履歴がまだないため、ポートフォリオ分岐は未算出です。次の判断更新後に端末内で合成します。'
                    : '保有数量が未入力のため、ポートフォリオ・シナリオは表示できません(Holdings / Watchlistの銘柄詳細で保有数量を入力すると端末内で合成されます。捏造しません)。'}
                </p>
              ) : (
                <>
                  <p className="cmd-alloc__note" style={{ fontSize: 12.5 }}>
                    <b style={{ color: DOM_TONE[ps.dominant] }}>{DOM_JA[ps.dominant]}</b>
                    <span style={{ marginLeft: 6 }}>{ps.summaryJa}</span>
                  </p>
                  <p className="cmd-alloc__note" style={{ fontSize: 10, color: 'var(--text-faint)' }}>
                    条件付きシナリオであり予測でも売買指示でもありません(確率は帯のみ)。銘柄別の無効化条件はHoldings / Watchlistの各銘柄→Decisionで。
                  </p>
                </>
              )}
            </div>
          </section>
        );
      })()}

      {/* FIRE CORE / MUTUAL FUNDS (v11.19.1) — 投信=FIREの本丸資産の追跡。
          口数×日次NAV or 手動評価額・積立・口座区分。端末内のみ。 */}
      <FireCoreCard assetsApi={assetsApi} fireCore={portfolioIntel.fireCore} />

      {/* v11.20.0: Portfolio / FIRE Review Pack copy(端末内合成・自動送信なし) */}
      {(() => {
        const CopyBtns: React.FC = () => {
          const [msg, setMsg] = React.useState<string | null>(null);
          const doCopy = async (pm: 'owner_copy' | 'redacted') => {
            const md = buildReviewPackMarkdown({ packType: 'portfolio', privacyMode: pm,
              length: 'full', appVersion: __APP_VERSION__ });
            setMsg(await copyPack(md) ? '✓ コピーしました(貼り先に注意)' : 'コピー失敗');
            window.setTimeout(() => setMsg(null), 2500);
          };
          return (
            <p className="cmd-alloc__note" style={{ margin: '2px 0 8px', fontSize: 11.5 }}>
              ポートフォリオ/FIREをAIに相談:
              <button type="button" style={{ fontSize: 11, cursor: 'pointer', marginLeft: 6,
                background: 'transparent', color: 'var(--accent)', border: '1px solid var(--line)',
                borderRadius: 5, padding: '2px 8px' }} onClick={() => void doCopy('owner_copy')}>フルでコピー</button>
              <button type="button" style={{ fontSize: 11, cursor: 'pointer', marginLeft: 6,
                background: 'transparent', color: 'var(--accent)', border: '1px solid var(--line)',
                borderRadius: 5, padding: '2px 8px' }} onClick={() => void doCopy('redacted')}>redactedでコピー</button>
              {msg && <span style={{ marginLeft: 6, color: 'var(--value-positive)' }}>{msg}</span>}
            </p>
          );
        };
        return <CopyBtns />;
      })()}

      {/* PORTFOLIO STRATEGY / FIRE ALIGNMENT (v11.19.0) — 短期の計画とFIRE目的を
          接続する戦略層(端末内合成)。免許業の助言ではない・売買指示でもない。 */}
      {(() => {
        const s = portfolioIntel.portfolioStrategy;
        return (
          <section>
            <div className="section-head">
              <span className="section-head__title">PORTFOLIO STRATEGY / FIRE ALIGNMENT</span>
              <span className="section-head__count">概算 · 助言ではない</span>
            </div>
            <div className="card cmd-alloc">
              {!s ? (
                <p className="cmd-alloc__note">
                  戦略履歴がまだないため、コア/サテライト/戦術枠・FIRE整合は未算出です。
                  次の判断更新後に端末内で合成します。
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
        const ps = planPortfolioSummary(portfolioIntel.positionPlans);
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
                比率の高い銘柄は追加より先にリスク確認。詳細条件はHoldings / Watchlistの各銘柄→DECISIONで。
                これは計画であり売買指示ではありません(注文機能はありません)。
              </p>
            </div>
          </section>
        );
      })()}

      {/* Lean v13: owner backup/recovery controls live under Settings. */}
      <p className="cmd-alloc__note" style={{ margin: '2px 0 8px', fontSize: 11.5, color: 'var(--text-faint)' }}>
        ローカルJSONの書き出し/読み込み、保存済み暗号文の読取復元、復元ドリルは
        「<b>Settings / Recovery</b>」に集約しました。
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
              Holdings / Watchlistの銘柄詳細で入力すると、テーマ集中・通貨偏り・銘柄集中を判定します(端末内のみ)。
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
              {pe.unpriced.length > 0 && (
                <div className="cmd-alloc__note">検証済み評価価格を取得できないため暫定: {pe.unpriced.join(', ')}</div>
              )}
              <div className="cmd-alloc__note" style={{ fontSize: 10 }}>
                リスク点検であり売買指示ではありません。数量・単価は端末内のみ。
              </div>
            </>
          )}
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
            return (
              <div className="core-row" key={f.code}>
                <div className="core-row__body">
                  <span className="core-row__top">{f.name}</span>
                  <span className="core-row__reason">{f.code} · {f.date} — 日次NAV証拠(積立アクションはSDAに未接続)</span>
                </div>
                <div style={{ textAlign: 'right', flex: 'none' }}>
                  <div style={{ fontWeight: 700 }}>¥{Math.round(f.navYen).toLocaleString('en-US')}</div>
                  <div style={{ fontSize: 12 }}>
                    {t('cp.dayChange')} {f.changePct == null ? '—' : <SignedValue value={f.changePct} suffix="%" arrow={false} />}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-faint)', marginTop: 2 }}>
                    EVIDENCE ONLY
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
        </div>
      </details>
    </>
  );

  return <div className="cp-embedded">{content}</div>;
};
