import React from 'react';
import { useWatchtowerStatus } from '../../hooks/useWatchtowerStatus';

// ARGUS V11.5.3 — C.A.O.S.はどの情報源を見ているのか。Core Portfolioの資産クラス別に
// 監視ソース・鮮度・制限を可視化する(公開cache-onlyのwatchtower statusを読むだけ)。

const CLASS_JA: Record<string, string> = {
  JP_EQUITY: '日本個別株', US_EQUITY: '米国個別株', GOLD_GLD: '金 (GLD)',
  BONDS_TLT: '米国債 (TLT)', REITS_XLRE: 'REIT (XLRE)', CRYPTO_BTC_ETH: '暗号資産',
  FX_USDJPY: 'ドル円', CASH: '現金・待機資金', FUND_ACCUMULATION: '積立ファンド',
};
const STATUS_JA: Record<string, { ja: string; tone: string }> = {
  live: { ja: 'LIVE', tone: 'var(--value-positive, #34d399)' },
  partial: { ja: 'partial', tone: 'var(--amber, #fbbf24)' },
  stale: { ja: 'stale', tone: 'var(--amber, #fbbf24)' },
  error: { ja: 'error', tone: 'var(--value-negative, #f87171)' },
  not_configured: { ja: '未構成', tone: 'var(--text-faint)' },
  requires_contract: { ja: '要契約', tone: 'var(--text-faint)' },
  disabled: { ja: '停止', tone: 'var(--text-faint)' },
  missing: { ja: 'なし', tone: 'var(--value-negative, #f87171)' },
};

function age(h: number | null | undefined): string {
  if (h == null) return '—';
  if (h < 1) return '1h以内';
  if (h < 24) return `${Math.floor(h)}h前`;
  return `${Math.floor(h / 24)}d前`;
}

export const SourceUniverseCard: React.FC = () => {
  const { data } = useWatchtowerStatus();
  const [open, setOpen] = React.useState(false);
  const cov = data?.coverageByAssetClass || {};

  return (
    <section className="card">
      <h2 style={{ margin: '0 0 4px', fontSize: 15 }}>C.A.O.S.はどの情報源を見ているのか</h2>
      <p style={{ margin: '4px 0 10px', color: 'var(--text-sub)', fontSize: 12, lineHeight: 1.8 }}>
        ARGUS Proでは、Core Portfolioの投資対象ごとに監視ソースを分けています。日本個別株は
        TDnet/EDINET/企業IR/日銀・経産省/日経・ロイター・NHK等の公開メタデータ、米国個別株は
        SEC/Fed/Finnhub/Bloomberg・CNBC・MarketWatch・Yahoo Finance等、金は金利・ドル・公式マクロ指標、
        債券はFed/財務省/FRED、REITは金利・SEC提出書類、暗号資産はCoinGecko/CoinDesk/Cointelegraph、
        ドル円は日銀/Fed/財務省/FRED、現金は金利・イベントリスク・Visibility Guardを見ます。
        <b>Google Newsはニュースの発見手段であり、情報源そのものとしては扱いません</b>(見出しは真の発行元に
        解決して評価)。古いニュースや弱いソースは現在材料から降格します。監視はnear-real-time(約15分巡回)で、
        Bloomberg/Reuters端末の完全代替ではありません。
      </p>

      {/* asset-class coverage summary */}
      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', fontSize: 11.5, width: '100%' }}>
          <thead>
            <tr style={{ color: 'var(--text-faint)', textAlign: 'left' }}>
              <th style={{ padding: '2px 8px 2px 0' }}>資産クラス</th>
              <th style={{ padding: '2px 8px' }}>カバレッジ</th>
              <th style={{ padding: '2px 8px' }}>liveソース</th>
              <th style={{ padding: '2px 8px' }}>最新アイテム</th>
            </tr>
          </thead>
          <tbody>
            {Object.keys(CLASS_JA).map((ac) => {
              const c = cov[ac];
              const st = STATUS_JA[c?.status || 'missing'] || STATUS_JA.missing;
              return (
                <tr key={ac} style={{ borderTop: '1px solid var(--line)' }}>
                  <td style={{ padding: '3px 8px 3px 0' }}>{CLASS_JA[ac]}</td>
                  <td style={{ padding: '3px 8px', color: st.tone, fontWeight: 600 }}>{c ? st.ja : '—'}</td>
                  <td style={{ padding: '3px 8px' }}>{c ? `${c.liveSources}/${c.totalSources}` : '—'}</td>
                  <td style={{ padding: '3px 8px' }}>{age(c?.newestItemAgeHours)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {(data?.alerts?.length ?? 0) > 0 && (
        <p style={{ margin: '8px 0 0', fontSize: 11.5, color: 'var(--amber, #fbbf24)' }}>
          {data!.alerts.map((a, i) => <span key={i}>⚠ {a.messageJa} </span>)}
        </p>
      )}

      {/* per-source detail (collapsed by default) */}
      <button type="button" onClick={() => setOpen(!open)}
              style={{ marginTop: 10, fontSize: 11.5, cursor: 'pointer', background: 'transparent',
                       color: 'var(--accent)', border: '1px solid var(--line)', borderRadius: 6, padding: '3px 10px' }}>
        {open ? 'ソース一覧を閉じる' : `ソース一覧を見る (${data?.sources?.length ?? 0})`}
      </button>
      {open && data && (
        <div style={{ overflowX: 'auto', marginTop: 8 }}>
          <table style={{ borderCollapse: 'collapse', fontSize: 11, width: '100%' }}>
            <thead>
              <tr style={{ color: 'var(--text-faint)', textAlign: 'left' }}>
                <th style={{ padding: '2px 8px 2px 0' }}>ソース</th>
                <th style={{ padding: '2px 8px' }}>状態</th>
                <th style={{ padding: '2px 8px' }}>最終確認</th>
                <th style={{ padding: '2px 8px' }}>最新</th>
                <th style={{ padding: '2px 8px' }}>本日</th>
                <th style={{ padding: '2px 8px' }}>制限</th>
              </tr>
            </thead>
            <tbody>
              {data.sources.map((s) => {
                const st = STATUS_JA[s.status] || STATUS_JA.not_configured;
                return (
                  <tr key={s.sourceId} style={{ borderTop: '1px solid var(--line)' }}>
                    <td style={{ padding: '3px 8px 3px 0', whiteSpace: 'nowrap' }}>
                      {s.name}{s.isDiscoveryLayer ? ' 🔍' : ''}
                    </td>
                    <td style={{ padding: '3px 8px', color: st.tone, fontWeight: 600, whiteSpace: 'nowrap' }}>{st.ja}</td>
                    <td style={{ padding: '3px 8px', whiteSpace: 'nowrap' }}>
                      {s.lastCheckAt ? String(s.lastCheckAt).slice(11, 16) : '—'}
                    </td>
                    <td style={{ padding: '3px 8px', whiteSpace: 'nowrap' }}>{age(s.newestAgeHours)}</td>
                    <td style={{ padding: '3px 8px' }}>{s.itemsToday ?? 0}</td>
                    <td style={{ padding: '3px 8px', color: 'var(--text-faint)' }}>
                      {(s.limitationsJa || []).join(' / ') || '—'}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p style={{ margin: '6px 0 0', fontSize: 10.5, color: 'var(--text-faint)' }}>
            🔍=発見手段(discovery layer)。有料本文は権利がない限り取得しません(公開メタデータのみ)。
          </p>
        </div>
      )}
    </section>
  );
};
