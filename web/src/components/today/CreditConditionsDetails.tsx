import React from 'react';
import type { MarketBrief } from '../../lib/marketBrief';
import './CreditConditionsDetails.css';
import { useCreditConditions } from '../../hooks/useCreditConditions';

type Row = Record<string, unknown>;
const object = (value: unknown): value is Row => !!value && typeof value === 'object' && !Array.isArray(value);
const rows = (value: unknown): Row[] => Array.isArray(value) ? value.filter(object) : [];
const text = (value: unknown, fallback = '未確認') => typeof value === 'string' ? value : fallback;
const labels: Record<string, string> = { borrowingCost: '貸出金利', creditGrowth: '貸出の伸び', creditQuality: '信用の質', lendingStance: '貸出態度' };
const directions: Record<string, string> = { RISING: '上昇', STABLE: '横ばい', FALLING: '低下', EXPANDING: '拡大', CONTRACTING: '縮小', EASING: '緩和方向', NEUTRAL: '変化なし', TIGHTENING: '慎重化方向', IMPROVING: '改善方向', DETERIORATING: '悪化方向' };
const states: Record<string, string> = { AVAILABLE: '取得済み', DEGRADED: '保存値あり・更新失敗', STALE: '古い値・更新待ち', FAILED: '取得失敗', NOT_ACQUIRED: '未取得', NOT_RUN: '未実行', VERIFIED: '数値確認済み', VERIFIED_STATEMENT: '要旨確認済み', UNVERIFIED: '抽出未確認', NOT_PUBLIC: '詳細データの公開未確認', ARGUS_NOT_ELIGIBLE: '利用資格未確認' };
const metrics: Record<string, string> = { new_loan_rate: '新規の貸出金利', stock_short_loan_rate: '既存の短期貸出金利', loan_balance: '貸出残高', loan_growth_yoy: '貸出の前年比', lending_attitude_large: '大企業の貸出態度', lending_attitude_medium: '中堅企業の貸出態度', lending_attitude_small: '小企業の貸出態度', total_credit: '全国銀行の総与信', problem_exposure: '全国銀行の金融再生法開示債権', npl_ratio: '全国銀行の不良債権比率' };
const units: Record<string, string> = { PERCENT: '%', DI_POINTS: 'ポイント', '100_MILLION_JPY': '億円' };
const sourceLabels: Record<string, string> = { boj_credit_cost: '貸出金利', boj_credit_growth: '貸出残高', boj_credit_stance: '貸出態度', fsa_notes: '研究資料', boj_fsr: '金融システムレポート', fsa_npl: '不良債権', joint_data_platform: '共同データ基盤' };
const time = (value: unknown) => {
  if (typeof value !== 'string' || !value.includes('T') || !Number.isFinite(Date.parse(value))) return '未確認';
  return new Date(value).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo', year: 'numeric', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
};
const period = (row: Row) => row.dataAsOfBasis === 'QUARTER_END_LABEL' && /^\d{4}0[1-4]$/.test(text(row.observationPeriod, ''))
  ? `${text(row.observationPeriod).slice(0, 4)}年第${text(row.observationPeriod).slice(-1)}四半期` : text(row.dataAsOf);
const source = (value: unknown) => {
  try { const url = new URL(text(value, '')); return url.protocol === 'https:' && !url.username && !url.password ? url.href : null; }
  catch { return null; }
};
export function CreditConditionsDetails({ brief }: { brief?: Pick<MarketBrief, 'creditConditions'> }) {
  const current = useCreditConditions();
  const doc = current.denied ? null : current.document ?? brief?.creditConditions;
  if (!object(doc) || doc.schemaVersion !== 'credit-conditions-v1' || doc.actionAuthority !== false || !object(doc.dimensions)) return null;
  const dimensions = doc.dimensions;
  return <section className="credit-conditions" aria-label="信用環境の公式根拠" data-credit-snapshot={text(doc.snapshotId, '')}>
    {doc.showToday === true && <p className="credit-conditions__notice">信用環境：{Object.entries(labels).filter(([key]) => object(dimensions[key]) && dimensions[key].status === 'OBSERVED').map(([key, label]) => `${label}は${directions[text((dimensions[key] as Row).direction)] ?? '未分類'}`).join('、') || '入力の取得待ち'}。全体の分類は未検証です。</p>}
    <details className="argus-editorial__evidence"><summary>信用環境の根拠・取得状況</summary>
      <small>公式観測の保存値です。上のAI見立てとは作成時点が異なる場合があります。</small>
      {current.readFailed && <p>信用環境の最新の保存値を確認できません。取得済みの値を表示しています。</p>}
      {doc.collectionStatus === 'FAILED' && <p>信用環境の更新に失敗しました。受領済みの保存値を表示しています。</p>}
      <p>月次・四半期・半期の統計です。個社の借入金利や、毎日の売買タイミングを示すものではありません。</p>
      <dl>{Object.entries(labels).map(([key, label]) => {
        const row = object(dimensions[key]) ? dimensions[key] : {};
        return <React.Fragment key={key}><dt>{label}</dt><dd>{row.status === 'OBSERVED' ? `${directions[text(row.direction)]} · ${typeof row.value === 'number' ? row.value.toLocaleString('ja-JP') : '未確認'}${units[text(row.unit)] ?? ''} · 対象 ${period(row)}` : row.reason === 'STALE' ? `古い観測のため現状判定は保留 · 対象 ${period(row)}` : key === 'creditQuality' ? '比較できる数値が不足' : '更新・比較に必要な入力が不足'}</dd></React.Fragment>;
      })}</dl>
      <p>日銀の政策伝達：貸出金利と態度の観測を使います。利上げとの因果関係や伝達の強弱は未分類です。</p>
      <details><summary>数値と公式資料</summary>{rows(doc.evidence).slice(0, 12).map((row, index) => <div key={text(row.observationId, String(index))}>
        <p>{text(row.statementJa, metrics[text(row.metric)] ?? text(row.title))}{typeof row.value === 'number' ? `：${row.value.toLocaleString('ja-JP')}${units[text(row.unit)] ?? ''}` : ''}</p>
        <small>対象 {period(row)} · 公表日 {text(row.publicationDate)} · 公表時刻 {time(row.publicationAt)}<br/>受領 {time(row.retrievedAt)} · {states[text(row.validationStatus)] ?? '未確認'} · 改訂 {typeof row.revision === 'number' ? row.revision : '未確認'}<br/>{text(row.tablePageFigureRef)}</small>
        {source(row.sourceUrl) && <a href={source(row.sourceUrl)!} target="_blank" rel="noopener noreferrer">{text(row.publisher, '公式')}の原資料</a>}
      </div>)}</details>
      <details><summary>配信元の状態</summary>{rows(doc.sourceHealth).map((row, index) => <p key={text(row.sourceId, String(index))}>
        {text(row.publisher)} · {sourceLabels[text(row.sourceId)] ?? '公式資料'} · {states[text(row.status)] ?? '未確認'}{row.lastFetchStatus === 'FAILED' ? ' · 次回取得で再確認' : ''}<br/>
        対象 {text(row.dataAsOf)} · 最新取得 {time(row.lastSuccessAt)} · 次回点検 {time(row.nextCheckAt)} · {typeof row.count === 'number' ? row.count : 0}件<br/>
        {row.sourceId === 'joint_data_platform' ? '貸出明細への外部アクセス条件・ARGUSの資格は未確認です。' : text(row.cadence) === 'MONTHLY' ? '月次' : text(row.cadence) === 'QUARTERLY' ? '四半期' : '公表時に点検'}
      </p>)}</details>
      <small>FUTURE MAPの検証用候補です。予測の入力・成績は変更していません。今回取得した過去値を、当時の受領値として使いません。</small>
    </details>
  </section>;
}
