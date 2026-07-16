import React from 'react';
import type { UseAssets } from '../../hooks/useAssets';
import { latestFireCore } from '../../lib/positionExposureShare';
import { fundMeta, saveFundMeta, OWNER_RULE_JA, RATIO_BAND_JA,
  type AccountType, ACCOUNT_JA } from '../../lib/fireCore';
import { jpDisplay } from '../../lib/displayName';

// V11.19.1 — FIRE CORE / MUTUAL FUNDS (Core Portfolio)。投資信託=FIREの本丸資産。
// 口数×日次NAV(既存追跡)または現在評価額の手動入力。口座区分・毎月積立額もここで
// 入力する。全て端末内+暗号化バックアップのみ・証券会社連携なし・NAV捏造なし。

const fmtJpy = (v: number | null) =>
  v == null ? '未入力' : `¥${Math.round(v).toLocaleString('ja-JP')}`;
const jstToday = () => new Date(Date.now() + 9 * 3600_000).toISOString().slice(0, 10);

export const FireCoreCard: React.FC<{ assetsApi: UseAssets }> = ({ assetsApi }) => {
  const [, bump] = React.useReducer((x: number) => x + 1, 0);
  const f = latestFireCore();
  const funds = assetsApi.assets.filter((a) => (a.assetType === 'core_fund' || a.assetType === 'manual_fund'));

  return (
    <section>
      <div className="section-head">
        <span className="section-head__title">FIRE CORE / MUTUAL FUNDS</span>
        <span className="section-head__count">本丸資産 · 端末内のみ · 日次/手動更新</span>
      </div>
      <div className="card cmd-alloc">
        <p className="cmd-alloc__note" style={{ fontSize: 12 }}>
          FIREの本丸資産として投資信託を追跡します。{OWNER_RULE_JA}
        </p>
        {/* v12.0.6: 手動更新でOKなことを明示(GPT既知課題 — 更新頻度の不安を消す) */}
        <p className="cmd-alloc__note" style={{ fontSize: 11, color: 'var(--text-sub)' }}>
          投資信託はリアルタイムでなくてOKです。週1程度の評価額更新でもFIRE Core判定に使えます。
        </p>

        {!f || !funds.length ? (
          <p className="cmd-alloc__note">
            投資信託が未登録です。Asset Deskでファンドを追加し口数を入力するか、
            追加後にこの欄で現在評価額を手動入力してください(リアルタイム価格は不要です)。
          </p>
        ) : (
          <>
            <p className="cmd-alloc__note" style={{ fontSize: 12.5 }}>
              <b>投信合計 {fmtJpy(f.mutualFundTotal)}</b>
              {f.fireCoreShare != null && <> · 既知資産の約{f.fireCoreShare.toFixed(0)}%</>}
              {' '}· 毎月積立 {fmtJpy(f.monthlyContributionTotal)}
              {f.tacticalToCoreRatio != null && (
                <> · 戦術枠/Core比 {f.tacticalToCoreRatio.toFixed(2)}({RATIO_BAND_JA[f.tacticalToCoreBand]})</>
              )}
            </p>
            {f.warningsJa.map((w) => (
              <p key={w.slice(0, 12)} className="cmd-alloc__note" style={{ color: 'var(--amber, #fbbf24)' }}>⚠ {w}</p>
            ))}
            {f.opportunitiesJa.map((o) => (
              <p key={o.slice(0, 12)} className="cmd-alloc__note" style={{ color: 'var(--text-sub)' }}>◇ {o}</p>
            ))}

            {/* 各ファンドの入力行(端末内のみ) */}
            {f.positions.map((p) => {
              const m = fundMeta(p.symbol);
              return (
                <div key={p.symbol} style={{ border: '1px solid var(--line)', borderRadius: 6,
                                             padding: 8, margin: '6px 0' }}>
                  <p className="cmd-alloc__note" style={{ margin: 0, fontSize: 12 }}>
                    <b>{jpDisplay(p.symbol, p.fundName)}</b>
                    <span style={{ marginLeft: 6 }}>
                      評価額 {fmtJpy(p.marketValue)}
                      {p.valueSource === 'units_x_nav' && ' (口数×日次NAV)'}
                      {p.valueSource === 'manual_value' && ` (手動 ${p.lastValueDate ?? '日付不明'})`}
                    </span>
                    {/* v12.0.6: 日付+次の一歩を添える(週1手動更新は正常運用 — 過剰警告しない) */}
                    {p.stale === true && (
                      <b style={{ marginLeft: 6, color: 'var(--amber, #fbbf24)' }}>
                        更新が古い(最終 {p.lastValueDate ?? '不明'} → 下の欄で評価額を更新)
                      </b>
                    )}
                    {p.unrealizedPnlPct != null && (
                      <span style={{ marginLeft: 6, color: p.unrealizedPnlPct >= 0 ? 'var(--value-positive)' : 'var(--value-negative)' }}>
                        {p.unrealizedPnlPct >= 0 ? '+' : ''}{p.unrealizedPnlPct.toFixed(1)}%
                      </span>
                    )}
                  </p>
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 6, alignItems: 'center' }}>
                    <label style={lbl}>口座
                      <select value={m.accountType ?? 'unknown'} style={inp}
                              onChange={(e) => { saveFundMeta(p.symbol, { accountType: e.target.value as AccountType }); bump(); }}>
                        {(Object.keys(ACCOUNT_JA) as AccountType[]).map((k) => (
                          <option key={k} value={k}>{ACCOUNT_JA[k]}</option>
                        ))}
                      </select>
                    </label>
                    <label style={lbl}>毎月積立(円)
                      <input type="number" min={0} placeholder="未入力" style={inp}
                             defaultValue={m.monthlyContribution ?? ''}
                             onBlur={(e) => { const v = e.target.value === '' ? null : Number(e.target.value);
                               saveFundMeta(p.symbol, { monthlyContribution: v != null && v >= 0 ? v : null }); bump(); }} />
                    </label>
                    {p.valueSource !== 'units_x_nav' && (
                      <label style={lbl}>現在評価額(円・手動)
                        <input type="number" min={0} placeholder="未入力" style={inp}
                               defaultValue={m.manualValue ?? ''}
                               onBlur={(e) => { const v = e.target.value === '' ? null : Number(e.target.value);
                                 saveFundMeta(p.symbol, { manualValue: v != null && v > 0 ? v : null,
                                   manualValueDate: v != null && v > 0 ? jstToday() : null }); bump(); }} />
                      </label>
                    )}
                  </div>
                  <p style={{ margin: '3px 0 0', fontSize: 9.5, color: 'var(--text-faint)' }}>
                    {p.valueSource === 'units_x_nav'
                      ? '評価額は口数×日次NAV(投信ライブラリー)で自動追跡中。コスト未入力なら損益は表示しません(捏造なし)。'
                      : '口数未入力のため手動評価額を使用。入力すると入力日でstale判定します。'}
                  </p>
                </div>
              );
            })}

            {f.missingDataJa.length > 0 && (
              <p className="cmd-alloc__note" style={{ fontSize: 10.5, color: 'var(--text-faint)' }}>
                不足データ: {f.missingDataJa.join(' / ')}(不足分は判定に使わず、捏造しません)
              </p>
            )}
          </>
        )}
        <p className="cmd-alloc__note" style={{ fontSize: 10, color: 'var(--text-faint)' }}>
          ファンド名・口数・評価額・積立額・口座区分は端末内+暗号化バックアップのみ(サーバー送信なし)。
          証券会社ログイン・口座連携はありません。将来見込みの精密計算もしません。
        </p>
      </div>
    </section>
  );
};

const lbl: React.CSSProperties = { fontSize: 10.5, color: 'var(--text-faint)',
  display: 'flex', flexDirection: 'column', gap: 2 };
const inp: React.CSSProperties = { fontSize: 12, background: 'transparent',
  color: 'var(--text-main, #ddd)', border: '1px solid var(--line)', borderRadius: 6,
  padding: '3px 8px', minWidth: 110 };

export default FireCoreCard;
