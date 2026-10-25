// Shared renderer for persisted integrated explanations and historical records.
import React from 'react';
import type {MarketBrief} from '../../lib/marketBrief';
import type {JapanMarketComparison} from '../../types/japanMarketComparison';
import {validJapanMarketComparison} from '../../lib/japanMarketComparison';
import {JapanMarketComparisonChart} from '../chart/JapanMarketComparisonChart';
import '../today/ArgusEditorialSurface.css';

type Section={textJa:string;kind:string;evidenceIds:string[]};
export type Job={remoteBackup?:{status?:string;lastVerifiedAt?:string;pending?:boolean};requestId:string;status:string;persistenceStatus:string;remoteRecoveryVerified:boolean;
  overviewReuse?:{checkedAt:string;baseMarketContextId:string;inputsDigest:string;originalCompletedAt:string};
  previousOverview?:Job|null;context:{referenceEdition?:{recordId:string;recordedAt:string;isCurrentMarketAnalysis:false};intent?:string;eventFocus?:{eventId:string;snapshot?:{relatedMemory?:{policyVersion?:string;records?:Array<{outcomeWindows?:Array<{status:string}>}>}}};contextId:string;question:string;subject:{symbol:string;market:string};horizonSessions:number;baseMarketContextId:string;
    facts:Array<{evidenceId:string;text:string;provenance?:{url?:string;sourceLabel?:string}}>;
    retrievalRecord?:{policyVersion:string;scope:string;archiveSearchStatus:string;counterevidenceSearchStatus:string;selection:{mandatoryCurrent:string[];previousDistinct:string[];previousSharedWithCurrent:string[]}};
    indexComparison?:JapanMarketComparison;indexComparisonEvidenceId?:string;
    calculatedHypothesis?:{status:string;value?:number;unit?:string;noteJa?:string;baselinePressurePoints?:number;comparisonPoints?:Array<{usdJpy:number;value:number}>}};
  result?:{answer?:{sections:Record<string,Section>;presentationStatus?:string;presentationPlan?:MarketBrief['presentationPlan']};provider?:{returnedModel?:string;completedAt?:string}}};
const labels:Record<string,string>={view:'今の見立て',reasons:'重要な理由',changes:'前回からの変化',impact:'自分への影響',next:'次に確認すること',invalidation:'見方を変える条件'};
const states:Record<string,string>={RUNNING:'AIが根拠を確認しています。履歴は引き続き読めます。',INTERRUPTED:'再起動で処理が中断しました。課金の重複を避けるため、自動再実行はしていません。',REJECTED:'回答の根拠と表現を検証できなかったため、表示を保留しました。',UNAVAILABLE:'AIが応答を返せませんでした。取得済みの市場情報は利用できます。',FAILED:'回答処理に失敗しました。',SAVE_FAILED:'回答の保存に失敗しました。この端末表示だけでは復元を保証できません。'};
const errors:Record<string,string>={saved_market_reference_unavailable:'表示していた説明の保存データを復旧中です。復旧後に同じ質問を再送できます。',unauthorized:'所有者の接続キーを確認してください。',owner_sync_unconfigured:'サーバーの所有者認証が未設定です。',durable_storage_unavailable:'履歴の保存先が利用できないため、質問を送信できません。',market_context_changed:'市場の根拠が更新されました。更新後に新しい質問として送信してください。',dialogue_recovery_pending:'保存した会話を復旧中、または遠隔保存の接続を確認できていません。二重実行を防ぐため、復旧確認後に質問できます。',dialogue_busy:'別の質問に回答中です。履歴から進行状況を確認できます。',dialogue_input_invalid:'入力した対象・期間・仮定を確認してください。'};
export const validJob=(x:any):x is Job=>!!x&&typeof x.requestId==='string'&&typeof x.status==='string'&&x.context?.subject&&Array.isArray(x.context?.facts)
  &&typeof x.context?.question==='string'&&(!x.result?.answer||Object.keys(labels).every(k=>typeof x.result.answer.sections?.[k]?.textJa==='string'));

function dialogueChoices(job: Job | null) {
  const answer=job?.result?.answer;const plan=answer?.presentationPlan;
  const hasChart=job?.context.subject.symbol==='N225'&&job.context.subject.market==='JP'
    &&validJapanMarketComparison(job.context.indexComparison,job.context.horizonSessions);
  const expected=hasChart?[...Object.keys(labels),'nikkei-comparison']:Object.keys(labels);
  if(answer?.presentationStatus==='GENERATED'&&plan?.schemaVersion==='argus-presentation-intent-v1'
    &&plan.actionAuthority===false&&plan.surface==='dialogue'&&plan.contextId===job?.context.contextId
    &&plan.subject===job?.context.subject.symbol&&plan.horizonSessions===job?.context.horizonSessions
    &&Array.isArray(plan.elements)&&plan.elements.length===expected.length&&new Set(plan.elements.map(row=>row?.id)).size===expected.length
    &&plan.elements.filter(row=>row?.emphasis==='primary').length===1
    &&plan.elements.every(row=>row&&expected.includes(row.id)&&['lead','support','detail'].includes(row.placement)
      &&['primary','normal','quiet'].includes(row.emphasis)&&!(['view','impact','invalidation','nikkei-comparison'].includes(row.id)&&row.placement==='detail')))
    return plan.elements;
  return Object.keys(labels).map(id=>({id,placement:'support',emphasis:'normal',purposeJa:''}));
}

export function OwnerAnswerBody({job,compact=false}:{job:Job;compact?:boolean}) {
  const answer=job.result?.answer;
  if(!answer)return null;
  return <div className="argus-editorial owner-dialogue__answer">
    {/* 2026-10-25 (owner): no disclaimers on screen; a saved edition says its time. */}
    {job.context.referenceEdition&&<p className="argus-editorial__retained">{new Date(job.context.referenceEdition.recordedAt).toLocaleString('ja-JP',{timeZone:'Asia/Tokyo'})}の保存版</p>}
    {dialogueChoices(job).map(choice=>{
        if(choice.id==='nikkei-comparison')return <section className={`argus-editorial__element is-${choice.emphasis} placement-${choice.placement}`} key={choice.id}>
          <JapanMarketComparisonChart document={job.context.indexComparison!}/>
        </section>;
        const content=<p className="argus-editorial__text">{answer.sections[choice.id].textJa}</p>;
        const className=`argus-editorial__element is-${choice.emphasis} placement-${choice.placement} element-${choice.id}`;
        return choice.placement==='detail'||compact&&['reasons','changes','next'].includes(choice.id)?<details className={className} key={choice.id}><summary>{labels[choice.id]}</summary>{content}</details>
          :<section className={className} key={choice.id}><h2>{labels[choice.id]}</h2>{content}</section>;
      })}
    </div>;
}
