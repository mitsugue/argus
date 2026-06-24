import React, { useMemo } from 'react';
import { PageShell } from './PageShell';
import { AlertCard } from '../components/dashboard/AlertCard';
import { CoreRow } from '../components/dashboard/CoreRow';
import { useActionAlerts } from '../hooks/useActionAlerts';
import { useAssets } from '../hooks/useAssets';
import { useJapanWatchlist } from '../hooks/useJapanWatchlist';
import { useUSWatchlist } from '../hooks/useUSWatchlist';
import { useCryptoWatchlist } from '../hooks/useCryptoWatchlist';
import { useRatesSnapshot } from '../hooks/useRatesSnapshot';
import { useFundNav } from '../hooks/useFundNav';
import { buildExposure } from '../lib/portfolio';
import { coreActionFor } from '../lib/todayCall';
import { genreOf } from '../types/assetItem';
import type { CorePosition } from '../types/dashboard';
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

export const CorePortfolio: React.FC = () => {
  useLocale();   // re-render on locale switch
  const { cards, posture, phase } = useActionAlerts();
  const { assets } = useAssets();
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
      .map((a) => ({ symbol: a.symbol, id: (a.memo ?? '').startsWith('coingecko:') ? (a.memo as string).slice('coingecko:'.length) : '' }))
      .filter((p) => p.id),
    [assets],
  );
  const crypto = useCryptoWatchlist(useMemo(() => cryptoPairs.map((p) => p.id), [cryptoPairs]));

  const priceOf = useMemo(() => {
    const m = new Map<string, number>();
    for (const s of jp.data?.stocks ?? []) if (s.status === 'live') m.set(s.symbol, s.price);
    for (const s of us.data?.stocks ?? []) if (s.status === 'live') m.set(s.symbol, s.price);
    for (const p of cryptoPairs) {
      const q = crypto.byId[p.id];
      if (q && q.status === 'live') m.set(p.symbol, q.priceUsd);
    }
    return (a: { symbol: string }) => m.get(a.symbol);
  }, [jp.data, us.data, crypto.byId, cryptoPairs]);

  const exp = useMemo(() => buildExposure(assets, priceOf, usdJpy), [assets, priceOf, usdJpy]);

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
      title={t('nav.corePortfolio')}
      subtitle={
        <span>
          資産クラス司令室 — 配分の現在地と、クラスごとの「いま取るべき構え」。
          <span className="today-phase"> - {phase === 'connecting' ? 'connecting...' : phase}{posture ? ` · posture ${posture}` : ''}</span>
        </span>
      }
    >
      <section>
        <div className="section-head">
          <span className="section-head__title">あなたの配分</span>
          <span className="section-head__count">
            {exp.combinedJpy != null ? `合計 ${fmtJpy(exp.combinedJpy)}` : 'live価格の保有なし'}
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
                <div className="cmd-alloc__note">価格未取得のため除外: {exp.unpriced.join(', ')}(投信の基準価額は今後対応予定)</div>
              )}
            </>
          ) : (
            <p className="cmd-alloc__empty">
              Watchlistで銘柄の行を開いて「保有数量・平均取得単価」を入力すると、ここに配分の現在地が表示されます(データは端末内のみ)。
            </p>
          )}
        </div>
      </section>

      <section>
        <div className="section-head">
          <span className="section-head__title">クラス判断</span>
          <span className="section-head__count">{cards.length} classes</span>
        </div>
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
          <span className="section-head__title">積立方針 + 投信 基準価額</span>
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
          }) : <p className="cmd-alloc__empty">基準価額を取得中…(投信総合ライブラリー)</p>}
          <div className="cmd-alloc__note" style={{ marginTop: 8 }}>
            基準価額=投信総合ライブラリー(資産運用業協会)の日次。積立方針は地合い連動(ドルコスト平均)で、個別の基準価額チャート判断ではありません。
          </div>
        </div>
      </section>
    </PageShell>
  );
};
