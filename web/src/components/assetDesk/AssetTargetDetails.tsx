import React from 'react';
import type { DeskCardData } from './types';
import { useAnalystTargetState } from '../../hooks/useAnalystTargets';
import { outlookMoney, outlookDay } from '../../domain/assetOutlook';

/** アナリスト集計とARGUSの参考水準は別の根拠。平均はカード先頭で表示する。 */
export function AssetTargetDetails({ d }: { d: DeskCardData }) {
  const state = useAnalystTargetState();
  const market = d.genre === 'jp' ? 'JP' : d.genre === 'us' ? 'US' : null;
  const target = market ? state.items[`${market}:${d.decisionFirst.symbol.toUpperCase()}`] : undefined;
  const positive = (v: number | null) => v != null && Number.isFinite(v) && v > 0;
  const range = target && positive(target.low) && positive(target.high) && target.high! >= target.low!;
  return <div className="ad-target-details">
    {market && <section aria-label="アナリスト目標の内訳">
      <h4>アナリスト目標の内訳</h4>
      {target ? <>
        <dl className="ad-detail-facts">
          <div><dt>最低〜最高</dt><dd>{range ? `${outlookMoney(target.low!, market)}〜${outlookMoney(target.high!, market)}` : '未取得'}</dd></div>
          <div><dt>中央値</dt><dd>{positive(target.median) ? outlookMoney(target.median!, market) : '未取得'}</dd></div>
        </dl>
        <p className="ad-detail-note">{target.source} · {outlookDay(target.fetchedAt)}取得 · {target.analysts}人</p>
        {(state.refreshFailed || (target.acquisitionStatus && target.acquisitionStatus !== 'AVAILABLE')) &&
          <p className="ad-overview__warning">更新を確認できないため、保存した目標株価の内訳です。</p>}
      </> : <p className="ad-detail-note">{state.loading ? '目標株価の内訳を読み込んでいます。' :
        state.availability[`${market}:${d.decisionFirst.symbol.toUpperCase()}`]?.status === 'NO_TARGET'
          ? '取得元に目標株価の集計がありません。' : '目標株価の内訳は未取得です。'}</p>}
      <p className="ad-detail-note">複数のアナリストの目標を集計したものです。到達の保証や、今日の証券会社の変更速報ではありません。</p>
    </section>}
    {(d.decisionFirst.targets.length > 0 || d.decisionFirst.invalidation) && <section aria-label="ARGUSの参考水準">
      <h4>ARGUSの参考水準</h4>
      <dl className="ad-detail-facts">
        {d.decisionFirst.targets.map((t, index) => <div key={index}><dt>参考目標{d.decisionFirst.targets.length > 1 ? ` ${index + 1}` : ''}</dt><dd>{t.value} {t.unit}</dd></div>)}
        {d.decisionFirst.invalidation && <div><dt>見直し水準</dt><dd>{d.decisionFirst.invalidation.value} {d.decisionFirst.invalidation.unit}</dd></div>}
      </dl>
    </section>}
  </div>;
}
