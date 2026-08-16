import React, { useState } from 'react';
import type { DeskCardData } from './types';
import { getNote, saveNote } from '../../lib/researchNotes';
import { buildReviewPackMarkdown, copyPack } from '../../lib/reviewPack';
import { bestAssetName } from '../../lib/assetStrategy';
import { OsintDeepDive } from '../dashboard/OsintDeepDive';
import { decisionHistoryFor } from '../../lib/decisionQuality';
import { pastPatternLineJa } from '../../lib/learningReview';
import { refreshMarketLedger } from '../../hooks/useMarketLedger';

// V12.2.12 — RESEARCH & NOTES(§7-9)。旧Watchlistのリサーチメモ/AI相談/Removeと
// 旧TodayのReview Packコピー/OSINT Deep Dive/DECISION HISTORYを統合。
// コピーは全て手動(自動送信なし)・メモは端末内のみ(不変)。

const aiBtn: React.CSSProperties = { fontSize: 10.5, cursor: 'pointer', marginLeft: 5,
  background: 'transparent', color: 'var(--accent)', border: '1px solid var(--line)',
  borderRadius: 5, padding: '1px 7px' };

// LLM相談 (v10.30): ONE handoff prompt — ARGUSにしか見えない情報(大口フロー/
// 日証金/開示空売り/校正実績)を先頭に置くモート起点プロンプト。移設のみ。
async function buildAndCopyConsult(d: DeskCardData,
                                   provider: 'ChatGPT' | 'Gemini'): Promise<boolean> {
  const name0 = bestAssetName(d.asset, d.liveName ?? d.card?.name);
  const strat = d.strat;
  const L: string[] = [];
  const [market, chart] = await Promise.all([
    refreshMarketLedger().then((s) => s.ledger).catch(() => null),
    (() => {
      const backend = (import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined)?.replace(/\/$/, '');
      if (!backend) return Promise.resolve(null);
      const params = new URLSearchParams({ scope: 'asset', symbol: d.asset.symbol,
        market: d.asset.market, timeframe: 'daily' });
      return fetch(`${backend}/api/argus/chart-intelligence?${params}`, { method: 'GET' })
        .then((r) => r.ok ? r.json() as Promise<{ critique?: Array<{ label: string; text: string }> }> : null)
        .catch(() => null);
    })(),
  ]);
  L.push(`# ${provider} consultation pack (clipboard only — API call 0)`);
  L.push(`あなたは投資の専門家です。私の判断支援アプリARGUSが出した「${d.asset.symbol} ${name0}」(${d.asset.market})の診断を渡します。`);
  L.push('大前提: ニュースや一般的な地合いはあなたの方が詳しい。だからここでは、ARGUSが掴んでいる「Web検索だけでは取れない情報」を軸に判断してほしい。');
  L.push('');
  L.push('【ARGUSにしか見えない情報 — これを最重視して】');
  const flow = strat.bigFlowRatio;
  if (flow != null) L.push(`■ 大口資金フロー(moomoo板・純流入率): ${(flow * 100).toFixed(0)}%`);
  L.push(`■ 旧ルール(EVIDENCE ONLY): ${d.decision?.rule.action ?? strat.action ?? '未確認'}`);
  L.push(`■ 保有情報(端末内から手動コピー): ${d.pn?.held ? `保有中・数量${d.pn.quantity ?? '未入力'}・取得単価${d.pn.avgCost ?? '未入力'}・損益${d.pn.pnlPct ?? '未計算'}%` : '未保有/監視'}`);
  if (d.eventTags.length) L.push(`■ 主要イベント: ${d.eventTags.map((e) => `${e.code} ${e.countdown}`).join(' / ')}`);
  if (market) L.push(`■ Market Ledger要約: ${Object.entries(market.summary).map(([k, v]) => `${k}=${v}`).join(' / ')}`);
  else L.push('■ Market Ledger要約: 未取得');
  L.push('');
  L.push('【参考(あなたの方が詳しいはず)】');
  if (strat.status !== 'mock' && strat.price != null) L.push(`■ 現在値 ${strat.price}（前日比 ${strat.changePct != null ? `${strat.changePct >= 0 ? '+' : ''}${strat.changePct.toFixed(2)}%` : '—'}）`);
  L.push(`■ Chart Intelligence: ${chart?.critique?.map((x) => `${x.label}: ${x.text}`).join(' / ') || '未取得'}`);
  L.push(`■ データ品質: quote=${strat.status} / market-ledger=${market ? market.remoteReadBack.verificationStatus : '未取得'}`);
  if (strat.catalystNoteJa) L.push(`■ 直近の材料(ARGUS把握分): ${strat.catalystNoteJa}`);
  L.push('');
  L.push('依頼:');
  L.push('(1) Web/Deep ResearchのOSINT(直近2週の開示・決算・大株主/空売り/自社株買い・業界/国策)で、上のARGUSの需給読みを「補強 or 反証」して');
  L.push('(2) 強気材料と弱気材料を対比');
  L.push('(3) 強気/弱気/不明の証拠を分離し、確信度・根拠・出典URL・次に確認する条件を列挙して。売買アクションは選ばないで。');
  L.push(`(4) ${provider}として、上のMarket Ledgerと個別チャートが矛盾する点、不足している確認事項を列挙して。`);
  L.push('AI出力はSingle Decision Authorityへの挑戦/反証証拠だけで、Primary Actionを上書きしません。');
  const text = L.join('\n');
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    window.prompt('コピーできませんでした。手動で選択してください:', text);
    return false;
  }
}

export const AssetResearchPanel: React.FC<{
  d: DeskCardData;
  onRemove: (id: string) => void;
}> = ({ d, onRemove }) => {
  const [note, setNote] = useState(() => getNote(d.asset.symbol)?.text ?? '');
  const [noteSaved, setNoteSaved] = useState(false);
  const [llmCopied, setLlmCopied] = useState<string | null>(null);
  const [packMsg, setPackMsg] = useState<string | null>(null);
  const doCopyPack = async (privacyMode: 'owner_copy' | 'redacted', length: 'full' | 'short') => {
    const md = buildReviewPackMarkdown({ packType: 'asset', privacyMode, length,
      appVersion: __APP_VERSION__, symbol: d.asset.symbol });
    setPackMsg(await copyPack(md) ? '✓ コピーしました(貼り先に注意)' : 'コピー失敗 — もう一度お試しください');
    window.setTimeout(() => setPackMsg(null), 2500);
  };
  const hist = decisionHistoryFor(d.asset.symbol, 2);
  return (
    <>
      <div className="asset-detail__note">
        <span className="asset-detail__k">📝 リサーチメモ(Gemini/GPTの回答を貼り付け・端末内のみ。保護は完全バックアップJSON書き出し)</span>
        <textarea
          className="asset-detail__note-area"
          value={note}
          placeholder="Gemini OSINTの結論などをここに保存…"
          onChange={(e) => { setNote(e.target.value); setNoteSaved(false); }}
          onBlur={() => { saveNote(d.asset.symbol, note); setNoteSaved(true); }}
        />
        {noteSaved && <span className="asset-detail__note-saved">✓ 保存</span>}
      </div>

      {/* v11.20.0: Asset Review Pack copy(端末内合成・自動送信なし) */}
      <p className="uac-next" style={{ margin: '4px 0 0', fontSize: 10.5 }}>
        この銘柄をAIに相談:
        <button type="button" style={aiBtn} onClick={() => void doCopyPack('owner_copy', 'full')}>フル</button>
        <button type="button" style={aiBtn} onClick={() => void doCopyPack('owner_copy', 'short')}>短縮</button>
        <button type="button" style={aiBtn} onClick={() => void doCopyPack('redacted', 'full')}>redacted</button>
        {(['ChatGPT', 'Gemini'] as const).map((provider) => <button key={provider} type="button" style={aiBtn}
                title={`${provider}用の相談文をコピーします。APIは呼びません。`}
                onClick={() => void buildAndCopyConsult(d, provider).then((ok) => {
                  if (ok) { setLlmCopied(provider); window.setTimeout(() => setLlmCopied(null), 2500); }
                })}>
          {llmCopied === provider ? '✓ コピー完了' : `${provider}に相談`}
        </button>)}
        {packMsg && <span style={{ marginLeft: 6, color: 'var(--value-positive)' }}>{packMsg}</span>}
      </p>

      {/* v12.1.0: マルチエージェントOSINT(計画→収集→Gemini/GPT→検証→統合) */}
      <OsintDeepDive symbol={d.asset.symbol} market={d.asset.market} held={!!d.pn?.held} />

      {/* DECISION HISTORY (v11.11.0) — 端末内記録の答え合わせ */}
      {hist.length > 0 && (
        <div className="uac-sec">
          <div className="uac-sec-t">DECISION HISTORY</div>
          {(() => { const pl = pastPatternLineJa(d.asset.symbol);
            return pl ? <p className="uac-next" style={{ marginBottom: 2, color: 'var(--text-faint)' }}>{pl}</p> : null; })()}
          {hist.map((h) => (
            <p key={h.id} className="uac-next" style={{ marginBottom: 2 }}>
              <span style={{ color: 'var(--text-faint)' }}>{h.asOf.slice(0, 10)}</span>
              <span style={{ marginLeft: 5 }}>[{h.decisionContext}]</span>
              {h.outcome?.outcomeReturn5d != null && (
                <span style={{ marginLeft: 5, color: h.outcome.outcomeReturn5d >= 0 ? 'var(--value-positive)' : 'var(--value-negative)' }}>
                  5d {h.outcome.outcomeReturn5d >= 0 ? '+' : ''}{h.outcome.outcomeReturn5d.toFixed(1)}%
                </span>
              )}
              {h.outcome?.outcomeReadableJa && (
                <span style={{ marginLeft: 5, color: 'var(--text-faint)' }}>{h.outcome.outcomeReadableJa}</span>
              )}
              {!h.outcome?.outcomeReadableJa && <span style={{ marginLeft: 5, color: 'var(--text-faint)' }}>結果待ち</span>}
            </p>
          ))}
        </div>
      )}

      <p className="uac-next" style={{ margin: '6px 0 0' }}>
        <button className="asset-mini asset-mini--danger" aria-label={`Remove ${d.asset.symbol}`}
                onClick={() => onRemove(d.asset.id)}>Remove(登録解除)</button>
      </p>
    </>
  );
};
