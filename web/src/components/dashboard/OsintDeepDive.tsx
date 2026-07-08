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
  const { inv, running, runDeepDive, postTerms, progress, queuePosition, etaMin, reload,
          verifyGaps, verifyUrl } = useOsintInvestigation(symbol, market);
  const [dismissed, setDismissed] = React.useState<Set<string>>(() => {
    try { return new Set(JSON.parse(localStorage.getItem('argus.osintGapDismiss.v1') ?? '[]') as string[]); }
    catch { return new Set(); }
  });
  const dismissGap = (id: string) => {
    const next = new Set(dismissed); next.add(id);
    setDismissed(next);
    try { localStorage.setItem('argus.osintGapDismiss.v1', JSON.stringify([...next].slice(-60))); } catch { /* noop */ }
  };
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
      superiorityJa: inv.superiority?.superiorityJa,
      superiorityVerdictJa: inv.superiority?.ownerReadableVerdictJa,
      unresolvedCount: inv.superiority?.argusMissedImportantCount,
      verificationRatePct: inv.superiority ? Math.round(inv.superiority.sourceVerificationRate * 100) : undefined,
      researchPowerJa: inv.researchPower?.displayJa,
      researchPowerVerdictJa: inv.researchPower?.ownerReadableVerdictJa,
      contradictionWarningsJa: inv.contradictionReportV2?.ownerReadableWarningsJa,
      sourceCoverageJa: inv.sourceCoverage
        ? `${inv.sourceCoverage.filter((r) => r.state === 'checked').length}/${inv.sourceCoverage.length}カテゴリ探索済み`
        : undefined,
      conclusionJa: inv.ownerConclusion
        ? `${inv.ownerConclusion.directCompanyEvidenceJa} / ${inv.ownerConclusion.whyJa}`
        : undefined,
      causalJa: inv.causalRelevanceSummary?.ownerReadableJa,
      primarySourceJa: inv.primarySourceChecks
        ? `一次ソース検証済み${inv.primarySourceChecks.filter((c) => c.status === 'verified').length}/${inv.primarySourceChecks.length}カテゴリ`
        : undefined,
      gapGroupsJa: inv.gapLedger?.length
        ? `具体未回収${inv.gapLedger.filter((g) => g.resolutionStatus === 'still_unresolved_important').length}件/未検証仮説${inv.gapLedger.filter((g) => g.resolutionStatus === 'hypothesis_not_source').length}件/探索方向${inv.gapLedger.filter((g) => g.resolutionStatus === 'search_direction_only').length}件/参照不能${inv.gapLedger.filter((g) => g.resolutionStatus === 'inaccessible').length}件`
        : undefined,
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

      {/* v12.1.1: 進捗(手動実行が黙って待たない) */}
      {progress && progress.stage !== 'complete' && (
        <p style={{ margin: '2px 0 4px', fontSize: 10.5, color: 'var(--accent)' }}>
          進捗: {({ planning: '計画中', gemini_scout: 'Geminiスカウト実行中',
                    gpt_scout: 'GPTスカウト実行中', verification: 'ソース検証中',
                    research_loop: `再探索${progress.loop}/${progress.maxLoops}`,
                    synthesis: '統合中', queued_for_agents: 'スカウト実行待ち',
                    failed: '失敗' } as Record<string, string>)[progress.stage] ?? progress.stage}
          {queuePosition != null && queuePosition > 0 && ` · キュー${queuePosition}番目`}
          {etaMin != null && ` · 次回実行まで約${etaMin}分`}
          {progress.notesJa.length > 0 && (
            <span style={{ display: 'block', color: 'var(--text-faint)' }}>{progress.notesJa[progress.notesJa.length - 1]}</span>
          )}
          {/* v12.1.3: Autopilot 14段階(failed_safe=途中結果保持を正直表示) */}
          {progress.autopilot && (
            <span style={{ display: 'block', fontSize: 10, color: progress.autopilot.status === 'failed_safe'
              ? 'var(--amber, #fbbf24)' : 'var(--text-faint)' }}>
              Autopilot {progress.autopilot.doneCount}/{progress.autopilot.totalStages}段階
              {progress.autopilot.status === 'failed_safe'
                ? ` · 安全停止: ${progress.autopilot.failReasonJa}`
                : progress.autopilot.currentStageJa ? ` · 現在: ${progress.autopilot.currentStageJa}` : ''}
            </span>
          )}
          <button type="button" style={{ ...{ fontSize: 10, cursor: 'pointer', marginLeft: 6,
            background: 'transparent', color: 'var(--accent)', border: '1px solid var(--line)',
            borderRadius: 5, padding: '1px 6px' } }} onClick={() => reload()}>更新</button>
        </p>
      )}

      {inv && (
        <>
          {/* v12.1.1: 優位性チップ(未回収があればGemini未満と正直表示) */}
          {inv.superiority && (
            <p style={{ margin: '0 0 3px', fontSize: 11.5 }}>
              <b style={{ color: inv.superiority.superiorityStatus === 'exceeds_gemini' ? 'var(--value-positive)'
                : inv.superiority.superiorityStatus === 'below_gemini' ? 'var(--amber, #fbbf24)'
                : 'var(--text-sub)',
                border: '1px solid var(--line)', borderRadius: 999, padding: '0 8px' }}>
                {inv.superiority.superiorityJa}
              </b>
              <span style={{ marginLeft: 6, fontSize: 10, color: 'var(--text-faint)' }}>
                検証率 {Math.round(inv.superiority.sourceVerificationRate * 100)}%
                · 未回収 {inv.superiority.argusMissedImportantCount}件
                · 重なり検証済み {inv.superiority.verifiedOverlapCount}件
                · ARGUS独自検証済み {inv.superiority.argusOnlyVerifiedCount}件
              </span>
              <span style={{ display: 'block', fontSize: 10.5, color: 'var(--text-sub)' }}>
                {inv.superiority.ownerReadableVerdictJa}
              </span>
              {inv.superiority.contextEdgeJa && (
                <span style={{ display: 'block', fontSize: 10, color: 'var(--text-faint)' }}>
                  {inv.superiority.contextEdgeJa}
                </span>
              )}
            </p>
          )}
          {/* v12.1.3: Research Powerチップ(Gemini基準比 — 生件数では2xにならない) */}
          {inv.researchPower && (
            <p style={{ margin: '0 0 3px', fontSize: 11.5 }}>
              <b style={{ color: inv.researchPower.status === 'exceeds_gemini_2x' ? 'var(--value-positive)'
                : inv.researchPower.status === 'exceeds_gemini' ? 'var(--value-positive)'
                : inv.researchPower.status === 'below_gemini' ? 'var(--amber, #fbbf24)'
                : 'var(--text-sub)',
                border: '1px solid var(--line)', borderRadius: 999, padding: '0 8px' }}>
                Research Power: {inv.researchPower.statusJa}
              </b>
              <span style={{ marginLeft: 6, fontSize: 10.5, color: 'var(--text-sub)' }}>
                {inv.researchPower.displayJa}
              </span>
              <span style={{ display: 'block', fontSize: 10.5, color: 'var(--text-sub)' }}>
                {inv.researchPower.ownerReadableVerdictJa}
              </span>
              {inv.researchPower.blockersJa.length > 0 && (
                <span style={{ display: 'block', fontSize: 10, color: 'var(--text-faint)' }}>
                  2x未達の要因: {inv.researchPower.blockersJa.join(' / ')}
                </span>
              )}
              {(inv.researchPower.strengthsJa?.length ?? 0) > 0 && (
                <span style={{ display: 'block', fontSize: 10, color: 'var(--text-faint)' }}>
                  強み: {inv.researchPower.strengthsJa!.slice(0, 3).join(' / ')}
                </span>
              )}
            </p>
          )}
          {/* v12.1.3: ソースカバレッジ(checkedの捏造なし)+主張ガード */}
          {inv.sourceCoverage && (
            <p style={{ margin: '0 0 3px', fontSize: 10, color: 'var(--text-faint)' }}>
              探索カバレッジ: {inv.sourceCoverage.filter((r) => r.state === 'checked').length}
              /{inv.sourceCoverage.length}カテゴリ探索済み
              {inv.sourceCoverage.some((r) => r.state !== 'checked') &&
                ` — 未探索: ${inv.sourceCoverage.filter((r) => r.state !== 'checked')
                  .map((r) => r.labelJa).slice(0, 3).join('・')}`}
              {(inv.coverageGuardsJa?.length ?? 0) > 0 && (
                <span style={{ display: 'block', color: 'var(--amber, #fbbf24)' }}>
                  {inv.coverageGuardsJa!.join(' / ')}
                </span>
              )}
            </p>
          )}
          {/* v12.1.4: 新鮮候補アラート(検証中 — 決定的原因にしない) */}
          {inv.freshCandidateAlertJa && (
            <p style={{ margin: '0 0 3px', fontSize: 10.5, color: 'var(--accent)' }}>
              {inv.freshCandidateAlertJa}({inv.freshCandidateCount}件 — 検証されるまで原因として扱いません)
            </p>
          )}
          {/* v12.1.4: 具体ソース欠落と仮説の分離表示 */}
          {(inv.gapLedger?.length ?? 0) > 0 && (() => {
            const n = (sts: string[]) => inv.gapLedger!.filter((g) => sts.includes(g.resolutionStatus)).length;
            const concrete = n(['still_unresolved_important']);
            const hyp = n(['hypothesis_not_source']);
            const dir = n(['search_direction_only']);
            const inf = n(['inference_only']);
            const inac = n(['inaccessible']);
            return (
              <p style={{ margin: '0 0 3px', fontSize: 10, color: concrete > 0 ? 'var(--amber, #fbbf24)' : 'var(--text-faint)' }}>
                未回収の具体ソース {concrete}件 · 未検証仮説 {hyp}件 · 探索方向 {dir}件
                {inf > 0 && ` · 推論のみ ${inf}件`}{inac > 0 && ` · 参照不能 ${inac}件`}
                (優位性をブロックするのは具体ソースのみ)
              </p>
            );
          })()}
          {/* v12.1.5: オーナー結論(直接/業界/VCを区別・曖昧な原因未特定なし) */}
          {inv.ownerConclusion && (
            <div style={{ margin: '0 0 4px', fontSize: 10.5, color: 'var(--text-sub)',
                          border: '1px solid var(--line)', borderRadius: 6, padding: '4px 8px' }}>
              <b style={{ fontSize: 11 }}>結論</b>
              <span style={{ display: 'block' }}>{inv.ownerConclusion.directCompanyEvidenceJa}</span>
              <span style={{ display: 'block', color: 'var(--text-faint)' }}>
                {inv.ownerConclusion.industryEvidenceJa} · {inv.ownerConclusion.valueChainEvidenceJa}
              </span>
              <span style={{ display: 'block', color: 'var(--text-faint)' }}>
                {inv.ownerConclusion.externalFoundJa} · {inv.ownerConclusion.argusVerifiedJa} · {inv.ownerConclusion.unverifiedJa}
              </span>
              <span style={{ display: 'block' }}>{inv.ownerConclusion.whyJa}</span>
              <span style={{ display: 'block', color: 'var(--text-faint)' }}>
                次アクション: {inv.ownerConclusion.nextActionJa}
              </span>
            </div>
          )}
          {/* v12.1.5: 因果関連度(ソースはあっても主因とは限らない) */}
          {inv.causalRelevanceSummary && (
            <p style={{ margin: '0 0 3px', fontSize: 10, color: inv.causalRelevanceSummary.weakCausalOnly
              ? 'var(--amber, #fbbf24)' : 'var(--text-faint)' }}>
              因果関連度: {inv.causalRelevanceSummary.ownerReadableJa}
            </p>
          )}
          {(inv.primaryAbsenceGuardsJa?.length ?? 0) > 0 && (
            <p style={{ margin: '0 0 3px', fontSize: 10, color: 'var(--amber, #fbbf24)' }}>
              {inv.primaryAbsenceGuardsJa!.join(' / ')}
            </p>
          )}
          {/* v12.1.5: 一次ソース取得状況(折りたたみ) */}
          {inv.primarySourceChecks && (
            <details style={{ fontSize: 10, margin: '0 0 3px' }}>
              <summary style={{ cursor: 'pointer', color: 'var(--text-faint)' }}>
                一次ソース取得: 検証済み{inv.primarySourceChecks.filter((c) => c.status === 'verified').length}
                /{inv.primarySourceChecks.length}カテゴリ
              </summary>
              {inv.primarySourceChecks.map((c) => (
                <span key={c.sourceCategory} style={{ display: 'block', color: 'var(--text-faint)' }}>
                  {c.ownerReadableJa}
                </span>
              ))}
            </details>
          )}
          {inv.valueChainGraph?.incomplete && inv.valueChainGraph.incompleteNoteJa && (
            <p style={{ margin: '0 0 3px', fontSize: 10, color: 'var(--text-faint)' }}>
              {inv.valueChainGraph.incompleteNoteJa}
            </p>
          )}
          {/* v12.1.3: 矛盾・因果規律の警告(ソースが増えても確信は増やさない) */}
          {(inv.contradictionReportV2?.ownerReadableWarningsJa?.length ?? 0) > 0 && (
            <p style={{ margin: '0 0 3px', fontSize: 10.5, color: 'var(--amber, #fbbf24)' }}>
              {inv.contradictionReportV2!.ownerReadableWarningsJa.map((w, i) => (
                <span key={i} style={{ display: 'block' }}>⚠ {w}</span>
              ))}
            </p>
          )}
          {/* v12.1.3: 価値連鎖規則(テーマ→個社は昇格させない注意つき) */}
          {inv.valueChainContext && (
            <p style={{ margin: '0 0 3px', fontSize: 10.5, color: 'var(--text-faint)' }}>
              価値連鎖: {inv.valueChainContext.labelJa} — {inv.valueChainContext.cautionJa}
            </p>
          )}
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

          {/* v12.1.2 Part I: ギャップ台帳 — 未回収は必ず理由つき・曖昧な「未回収N件」を廃止 */}
          {(inv.gapLedger?.length ?? 0) > 0 && (
            <div style={{ marginTop: 3 }}>
              {(inv.superiority?.gapProgressLinesJa ?? []).map((ln, i) => (
                <p key={`gl${i}`} style={{ margin: '1px 0 0', fontSize: 10.5, color: 'var(--text-sub)' }}>{ln}</p>
              ))}
              <details>
                <summary style={{ cursor: 'pointer', fontSize: 10, color: 'var(--text-faint)' }}>
                  ギャップ台帳を見る({inv.gapLedger!.length}件 · 予算: {inv.budget?.maxCostLabel ?? '—'})
                </summary>
                {inv.gapLedger!.filter((g) => !dismissed.has(g.id)).map((g) => (
                  <div key={g.id} style={{ margin: '3px 0', fontSize: 10.5, borderLeft: '2px solid var(--line)', paddingLeft: 6 }}>
                    <span style={{ color: g.resolutionStatus === 'still_unresolved_important'
                      ? 'var(--amber, #fbbf24)' : g.resolutionStatus === 'verified_integrated'
                        ? 'var(--value-positive)' : 'var(--text-faint)',
                      border: '1px solid var(--line)', borderRadius: 999, padding: '0 6px', fontSize: 9.5 }}>
                      {g.resolutionStatusJa}
                    </span>
                    <span style={{ marginLeft: 4, color: 'var(--text-sub)' }}>{g.sourceTitle.slice(0, 48)}</span>
                    <span style={{ display: 'block', color: 'var(--text-faint)' }}>
                      理由: {g.resolutionReasonJa}(提示: {g.providedBy})
                    </span>
                    {g.resolutionStatus === 'still_unresolved_important' && (
                      <span style={{ display: 'block' }}>
                        {g.sourceUrl && (
                          <button type="button" style={btn} onClick={async () => {
                            const r = await verifyUrl(g.sourceUrl!);
                            flash(r?.ok ? '✓ URL検証キューに追加' : '追加失敗');
                          }}>このURLを検証</button>
                        )}
                        <button type="button" style={btn} onClick={() => {
                          dismissGap(g.id);
                          flash('✓ 重要でないとして除外(端末内の判断・サーバー判定は不変)');
                        }}>重要でないとして除外</button>
                      </span>
                    )}
                  </div>
                ))}
                {inv.gapLedger!.some((g) => dismissed.has(g.id)) && (
                  <p style={{ margin: '2px 0 0', fontSize: 9.5, color: 'var(--text-faint)' }}>
                    オーナー判断で除外: {inv.gapLedger!.filter((g) => dismissed.has(g.id)).length}件(端末内のみ)
                  </p>
                )}
              </details>
              <button type="button" style={btn} onClick={async () => {
                const r = await verifyGaps();
                flash(r?.ok ? '✓ 未回収を再判定しました(重複/古い/無関係は即時解決)' : '再判定失敗');
              }}>未回収を再探索</button>
            </div>
          )}

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
        <button type="button" style={btn} disabled={running}
          onClick={async () => {
            const r = await runDeepDive(privacy);
            flash(r?.duplicate ? 'ジョブ進行中(二重実行しません)' : '✓ 再探索をキューしました');
          }}>再探索する</button>
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
          }}>このニュースをARGUSに学習させる</button>
        </div>
      )}

      <p style={{ margin: '3px 0 0', fontSize: 9.5, color: 'var(--text-faint)' }}>
        外部AIスカウトは管理側の定期実行のみ(公開画面から起動しません)。LLMの回答は検証されるまで証拠として扱いません。
      </p>
    </div>
  );
};

export default OsintDeepDive;
