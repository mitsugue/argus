import type { MarketBrief } from './marketBrief';

type Return = { status:string; instrumentId:string; returnPct:number|null; startDate:string;endDate:string;receivedAt?:string; reason?:string };
type Sector = Return & { sector17Code:string; nameJa:string; relativeToBenchmarkPct:number|null };
type Asset = Return & { sectorNameJa:string|null; relativeToSectorPct:number|null;relativeToNikkeiPct:number|null };
type Counts = { advancers:number; decliners:number; unchanged:number; available:number;expected:number;missing:number };
type Period = { horizonSessions:number;startDate:string;endDate:string;index:Return;benchmark:Return;sectors:Sector[];assets:Asset[];sample:{isWholeMarket:false;counts:Counts};indexContributions:{status:string} };
export type MarketInternalsDocument = { schemaVersion:string;evidenceId:string;asOfDate:string;periods:Record<string,Period>;actionAuthority:false;predictiveProbabilityVerified:false;limitationsJa:string[];
  breadth:{status:string;periodEnd?:string;universeLabelJa?:string;receivedAt?:string;counts?:{advancers:number;decliners:number;unchanged:number;unavailable:number;totalUniverseCount:number}};
  acquisition?:{status:string;lastSuccessfulAcquisitionAt?:string;failedSymbols?:string[]} };
const obj=(v:unknown):v is Record<string,any>=>!!v&&typeof v==='object'&&!Array.isArray(v);
const num=(v:unknown)=>typeof v==='number'&&Number.isFinite(v);
const nullable=(v:unknown)=>v===null||num(v);
const returnRow=(r:unknown):r is Return=>obj(r)&&['AVAILABLE','UNAVAILABLE'].includes(r.status)&&typeof r.instrumentId==='string'
  &&(r.status==='AVAILABLE'?num(r.returnPct):r.returnPct===null)&&typeof r.startDate==='string'&&typeof r.endDate==='string';
export function validMarketInternals(v:unknown):v is MarketInternalsDocument {
  if(!obj(v)||v.schemaVersion!=='jp-market-internals-v1'||v.actionAuthority!==false||v.predictiveProbabilityVerified!==false
    ||typeof v.evidenceId!=='string'||! /^[a-f0-9]{64}$/.test(v.evidenceId)||!obj(v.periods)||!obj(v.breadth)
    ||!['AVAILABLE','UNAVAILABLE'].includes(v.breadth.status)||Object.keys(v.periods).length===0
    ||!Array.isArray(v.limitationsJa)||!v.limitationsJa.every((x:unknown)=>typeof x==='string'))return false;
  if(v.breadth.status==='AVAILABLE') {
    const counts=v.breadth.counts;
    if(!obj(counts)||!['advancers','decliners','unchanged','unavailable','totalUniverseCount'].every(k=>Number.isSafeInteger(counts[k])&&counts[k]>=0)
      ||counts.advancers+counts.decliners+counts.unchanged+counts.unavailable!==counts.totalUniverseCount
      ||typeof v.breadth.periodEnd!=='string'||typeof v.breadth.universeLabelJa!=='string')return false;
  }
  return Object.entries(v.periods).every(([key,r])=>obj(r)&&[1,5,10,20].includes(Number(key))&&r.horizonSessions===Number(key)
    &&returnRow(r.index)&&returnRow(r.benchmark)&&r.benchmark.startDate===r.startDate&&r.benchmark.endDate===r.endDate&&Array.isArray(r.sectors)&&r.sectors.length<=17
    &&r.sectors.every((s:unknown)=>obj(s)&&typeof s.nameJa==='string'&&nullable(s.relativeToBenchmarkPct)&&returnRow(s))
    &&Array.isArray(r.assets)&&r.assets.length<=100&&r.assets.every((a:unknown)=>obj(a)&&nullable(a.relativeToSectorPct)&&nullable(a.relativeToNikkeiPct)&&returnRow(a))
    &&obj(r.sample)&&r.sample.isWholeMarket===false&&obj(r.sample.counts)
    &&['advancers','decliners','unchanged','available','expected','missing'].every(k=>Number.isSafeInteger(r.sample.counts[k])&&r.sample.counts[k]>=0)
    &&r.sample.counts.advancers+r.sample.counts.decliners+r.sample.counts.unchanged===r.sample.counts.available
    &&r.sample.counts.available+r.sample.counts.missing===r.sample.counts.expected
    &&r.sample.counts.expected===r.assets.length&&r.index.startDate===r.startDate&&r.index.endDate===r.endDate
    &&r.sectors.every((s:Sector)=>s.startDate===r.startDate&&s.endDate===r.endDate)
    &&r.assets.every((a:Asset)=>a.startDate===r.startDate&&a.endDate===r.endDate));
}

export function selectMarketInternals(brief:MarketBrief|null, latest:unknown, horizon:number) {
  const saved=brief?.calculationSnapshots?.[String(horizon)]?.marketInternals;
  const accepted=brief?.unifiedSummary;
  if(accepted?.schemaVersion==='argus-unified-brief-v1'&&accepted.actionAuthority===false&&accepted.contextId===brief?.unifiedContext?.contextId&&validMarketInternals(saved)
    &&saved.periods[String(horizon)]&&brief.unifiedContext.facts.some(f=>f.source==='market_internals_calculation'
      &&f.provenance?.eventId===`market-internals-${horizon}`&&f.provenance?.sourceRowSha256===saved.evidenceId)) {
    return {document:saved,binding:'AI_SNAPSHOT' as const};
  }
  return {document:validMarketInternals(latest)?latest:null,
    binding:accepted?'LATEST_SEPARATE' as const:'AWAITING_AI' as const};
}
