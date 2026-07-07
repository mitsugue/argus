import React from 'react';
import { useOsintInvestigation } from '../../hooks/useOsintInvestigation';
import { publishOsintDeep } from '../../lib/positionExposureShare';

// ARGUS V12.1.0 — OSINT DEEP DIVE(カード内)。
// ARGUS自身が 計画→収集→Gemini/GPTスカウト→検証→統合 を編成し、単体Geminiに
// 負けたら missed_by_argus として正直に表示・学習する。外部AIは公開画面から
// 起動せず(キュー→管理側実行)、redacted既定で私的情報は送らない。

const COVERAGE_TONE: Record<string, string> = {
  strong: 'var(--value-positive)', medium: 'var(--accent)',
  weak: 'var(--amber, #fbbf24)', insufficient: 'var(--value-negative)',
  failed: 'var(--value-negative)',
};

const PASTE_KEY = 'argus.osintPaste.v1';
const MISSED_KEY = 'argus.osintMissed.v1';

function pushLocal(key: string, rec: Record<string, unknown>): void {
  try {
    const cur = JSON.parse(localStorage.getItem(key) ?? '[]') as unknown[];
    cur.unshift({ ...rec, at: new Date().toISOString() });
    localStorage.setItem(key, JSON.stringify(cur.slice(0, 30)));
  } catch { /* storage不可でも壊れない */ }
}

/** 貼り戻しテキストから探索語候補を抽出(固有名詞/カタカナ語のみ・本文は送らない)。 */
function extractTerms(text: string): string[] {
  const out: string[] = [];
  for (const m of text.matchAll(/[A-Z][A-Za-z0-9\-]{2,24}|[ァ-ヶー]{3,14}/g)) {
    if (!out.includes(m[0])) out.push(m[0]);
  }
  return out.slice(0, 8);
}

export const OsintDeepDive: React.FC<{ symbol: string; market: string; held?: boolean }>
  = ({ symbol, market, held }) => {
  const { inv, running, runDeepDive, postTerms } = useOsintInvestigation(symbol, market);
  const [privacy, setPrivacy] = React.useState<'redacted' | 'owner_context' | 'full_private'>('redacted');
  const [msg, setMsg] = React.useState<string | null>(null);
  const [pasteOpen, setPasteOpen] = React.useState(false);
  const [pasteText, setPasteText] = React.useState('');
  const [missedOpen, setMissedOpen] = React.useState(false);
  const [missedTitle, setMissedTitle] = React.useState('');

  React.useEffect(() => {
    if (!inv) return;
    publishOsintDeep({
      symbol: inv.symbol,
      summaryJa: inv.ownerReadableSummaryJa,
      coverageJa: inv.coverageScore.totalCoverageJa,
      reliabilityJa: inv.reliabilityScore.overallJa,
      benchmarkJa: `ARGUS ${inv.benchmark.argusCount} / Gemini ${inv.benchmark.geminiCount} / GPT ${inv.benchmark.gptCount} / 重なり ${inv.benchmark.overlapCount} / ARGUS未検出 ${inv.benchmark.missedByArgusCount}`,
      disagreementJa: inv.contradictionReport,
      verifiedTitlesJa: inv.verifiedSources.map((v) => v.titleJa).slice(0, 5),
      missingAreasJa: inv.missingAreasJa,
    });
  }, [inv]);

  const flash = (m: string) => { setMsg(m); window.setTimeout(() => setMsg(null), 3000); };

  const weak = inv && ['weak', 'insufficient', 'failed'].includes(inv.coverageScore.totalCoverage);
  const btn: React.CSSProperties = { fontSize: 10.5, cursor: 'pointer', marginRight: 5,
    background: 'transparent', color: 'var(--accent)', border: '1px solid var(--line)',
    borderRadius: 5, padding: '2px 8px' };

  return (
    <div className="uac-sec">
      <div className="uac-sec-t">OSINT DEEP DIVE</div>

      {/* 弱カバレッジ警告(保有/P1相当は特に) */}
      {(!inv || weak) && (
        <p style={{ margin: '2px 0 4px', fontSize: 11.5,
                    color: held ? 'var(--amber, #fbbf24)' : 'var(--text-sub)' }}>
          ニュース探索が不十分です。深掘りOSINTまたはGemini/GPT比較を推奨。
        </p>
      )}

      {inv && (
        <>
          <p style={{ margin: 0, fontSize: 12 }}>
            <b>{inv.catalystVerdict.verdictJa}</b>
            <span style={{ marginLeft: 6, fontSize: 10.5, color: COVERAGE_TONE[inv.coverageScore.totalCoverage] }}>
              探索カバレッジ: {inv.coverageScore.totalCoverageJa}
            </span>
            <span style={{ marginLeft: 6, fontSize: 10.5, color: 'var(--text-faint)' }}>
              信頼度: {inv.reliabilityScore.overallJa} · 検証率 {Math.round(inv.reliabilityScore.verificationRate * 100)}%
            </span>
          </p>
          <p style={{ margin: '2px 0 0', fontSize: 11.5, color: 'var(--text-sub)' }}>{inv.ownerReadableSummaryJa}</p>
          {inv.catalystVerdict.missingEvidenceJa.map((x, i) => (
            <p key={i} style={{ margin: '1px 0 0', fontSize: 10.5, color: 'var(--amber, #fbbf24)' }}>{x}</p>
          ))}

          {/* Gemini/GPTベンチマーク */}
          <p style={{ margin: '3px 0 0', fontSize: 10.5, color: 'var(--text-faint)' }}>
            ベンチマーク: ARGUS {inv.benchmark.argusCount}件
            {' '}/ Gemini {inv.agentRuns.find((r) => r.provider === 'gemini')?.status === 'ok'
              ? `${inv.benchmark.geminiCount}件` : inv.agentRuns.find((r) => r.provider === 'gemini')?.status === 'queued'
                ? '実行待ち' : '未実行'}
            {' '}/ GPT {inv.agentRuns.find((r) => r.provider === 'gpt')?.status === 'ok'
              ? `${inv.benchmark.gptCount}件` : inv.agentRuns.find((r) => r.provider === 'gpt')?.status === 'queued'
                ? '実行待ち' : '未実行'}
            {inv.benchmark.argusOnlyCount > 0 && ` / ARGUS独自検出 ${inv.benchmark.argusOnlyCount}件`}
          </p>
          {inv.benchmark.notesJa.map((n, i) => (
            <p key={i} style={{ margin: '1px 0 0', fontSize: 10.5,
                                color: n.includes('未検出') ? 'var(--amber, #fbbf24)' : 'var(--text-faint)' }}>{n}</p>
          ))}

          <details style={{ marginTop: 2 }}>
            <summary style={{ cursor: 'pointer', fontSize: 10, color: 'var(--text-faint)' }}>Gemini/GPT比較・証拠台帳を見る</summary>
            <div style={{ fontSize: 10.5, color: 'var(--text-sub)', lineHeight: 1.7 }}>
              <p style={{ margin: '2px 0' }}>クエリ {inv.queryPlan.queryCount}本(直接/セクター/バリューチェーン/海外/下落理由)</p>
              {inv.verifiedSources.slice(0, 5).map((v, i) => (
                <p key={i} style={{ margin: '1px 0' }}>✓ [{v.labelJa}] {v.titleJa}
                  <span style={{ color: 'var(--text-faint)' }}> ({v.sourceName ?? '—'} · {v.freshness})</span></p>
              ))}
              {inv.rejectedSources.slice(0, 4).map((v, i) => (
                <p key={`r${i}`} style={{ margin: '1px 0', color: 'var(--text-faint)' }}>× [{v.labelJa}] {v.titleJa}</p>
              ))}
              {inv.contradictionReport.map((x, i) => (
                <p key={`c${i}`} style={{ margin: '1px 0', color: 'var(--amber, #fbbf24)' }}>⚠ {x}</p>
              ))}
              {inv.missingAreasJa.length > 0 && (
                <p style={{ margin: '2px 0' }}>不足領域: {inv.missingAreasJa.join(' / ')}</p>
              )}
              {inv.nextResearchJa.map((x, i) => (
                <p key={`n${i}`} style={{ margin: '1px 0' }}>→ {x}</p>
              ))}
            </div>
          </details>
        </>
      )}

      {/* 実行コントロール — redacted既定・full時は警告必須 */}
      <p style={{ margin: '4px 0 0', fontSize: 10.5 }}>
        <select value={privacy} onChange={(e) => setPrivacy(e.target.value as typeof privacy)}
          style={{ fontSize: 10, background: 'var(--surface-soft)', color: 'var(--text-sub)',
                   border: '1px solid var(--line)', borderRadius: 4, marginRight: 5 }}>
          <option value="redacted">redacted(既定・私的情報なし)</option>
          <option value="owner_context">短い文脈のみ</option>
          <option value="full_private">フル文脈(注意)</option>
        </select>
        <button type="button" style={btn} disabled={running}
          onClick={async () => {
            const r = await runDeepDive(privacy);
            flash(r ? '✓ 決定論調査を実行・Gemini/GPTスカウトをキューしました' : '実行失敗');
          }}>{running ? '調査中…' : '深掘りOSINTを実行'}</button>
        <button type="button" style={btn} onClick={() => setPasteOpen((v) => !v)}>Gemini/GPT結果を貼り戻す</button>
        <button type="button" style={btn} onClick={() => setMissedOpen((v) => !v)}>このニュースが抜けている</button>
        {msg && <span style={{ marginLeft: 4, color: 'var(--value-positive)' }}>{msg}</span>}
      </p>
      {privacy === 'full_private' && (
        <p style={{ margin: '2px 0 0', fontSize: 10, color: 'var(--amber, #fbbf24)' }}>
          ⚠ Gemini/GPTを使った深掘りOSINT — 外部AIに送信する内容を確認してください(保有・数量・口座情報は送らないでください)。
        </p>
      )}

      {/* 貼り戻し: 本文は端末内のみ・サーバーには探索語(≤8)だけ */}
      {pasteOpen && (
        <div style={{ marginTop: 4 }}>
          <textarea value={pasteText} onChange={(e) => setPasteText(e.target.value)}
            placeholder="GeminiやGPTのOSINT回答を貼り付け(本文は端末内に保存・サーバーへは探索語のみ)"
            style={{ width: '100%', minHeight: 60, fontSize: 11, background: 'var(--surface-soft)',
                     color: 'var(--text-main)', border: '1px solid var(--line)', borderRadius: 6 }} />
          <button type="button" style={btn} onClick={async () => {
            if (!pasteText.trim()) return;
            pushLocal(PASTE_KEY, { symbol, text: pasteText.slice(0, 4000) });
            const terms = extractTerms(pasteText);
            await postTerms(terms);
            setPasteText(''); setPasteOpen(false);
            flash(`✓ 端末内に保存・探索語${terms.length}件を追加(自動では信用しません — 次回調査で検証)`);
          }}>保存して探索語に反映</button>
        </div>
      )}

      {/* 見逃しニュース申告: ローカル台帳+探索語learning */}
      {missedOpen && (
        <div style={{ marginTop: 4 }}>
          <input value={missedTitle} onChange={(e) => setMissedTitle(e.target.value)}
            placeholder="抜けているニュースのタイトル/URL"
            style={{ width: '100%', fontSize: 11, background: 'var(--surface-soft)',
                     color: 'var(--text-main)', border: '1px solid var(--line)', borderRadius: 6, padding: '3px 6px' }} />
          <button type="button" style={btn} onClick={async () => {
            if (!missedTitle.trim()) return;
            pushLocal(MISSED_KEY, { symbol, title: missedTitle.slice(0, 200) });
            await postTerms(extractTerms(missedTitle));
            setMissedTitle(''); setMissedOpen(false);
            flash('✓ 見逃しとして記録(端末内)・探索語に追加しました');
          }}>見逃しとして記録</button>
        </div>
      )}

      <p style={{ margin: '3px 0 0', fontSize: 9.5, color: 'var(--text-faint)' }}>
        外部AIスカウトは管理側の定期実行のみ(公開画面から起動しません)。LLMの回答は検証されるまで証拠として扱いません。
      </p>
    </div>
  );
};

export default OsintDeepDive;
