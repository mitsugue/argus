import React, {useState, useSyncExternalStore} from 'react';
import {createSharedPollingStore} from '../../lib/sharedPollingStore';
import {validMarketInternals} from '../../lib/marketInternals';
import {useAssets} from '../../hooks/useAssets';
import {TriangleStepLoader} from '../common/TriangleStepLoader';
import './SectorHeatmap.css';
type Period={startDate:string;endDate:string;returnPct:number|null;relativeToBenchmarkPct:number|null};
type Row={symbol:string;nameJa:string;state:string;sourceTimestamp:string|null;source:string;periods:Record<string,Period>};
type Document={schemaVersion:string;targetDate:string;isToday:boolean;session:{session:string};rows:Row[];collectionErrors:Record<string,unknown>};
const store=createSharedPollingStore<{data:Document|null;error:boolean;loading:boolean}>({data:null,error:false,loading:true},(set)=>{
  let alive=true;let controller:AbortController|null=null;
  async function read(){
    controller=new AbortController();const timeout=setTimeout(()=>controller?.abort(),12000);
    try{
      const base=import.meta.env.VITE_ARGUS_BACKEND_URL;if(!base)throw new Error('no_backend');
      const response=await fetch(base.replace(/\/$/,'')+'/api/argus/sector-heatmap',{signal:controller.signal});
      if(!response.ok)throw new Error('unavailable');const data=await response.json();
      if(data.schemaVersion!=='jp-sector-heatmap-v1'||!Array.isArray(data.rows)||data.rows.length>17)throw new Error('invalid');
      if(alive)set({data,error:false,loading:false});
    }catch{if(alive)set(old=>({...old,error:true,loading:false}));}finally{clearTimeout(timeout);}
  }
  void read();const timer=setInterval(()=>void read(),120000);
  return()=>{alive=false;controller?.abort();clearInterval(timer);};
});
const pct=(value:number|null|undefined,relative=false)=>typeof value==='number'&&Number.isFinite(value)?`${value>0?'+':''}${value.toFixed(2)}${relative?'pt':'%'}`:'未取得';
const stamp=(value:string|null)=>value?new Date(value).toLocaleString('ja-JP',{timeZone:'Asia/Tokyo'}):'時刻未確認';
export function SectorHeatmap({internals}:{internals:unknown}){
  const {data,error,loading}=useSyncExternalStore(store.subscribe,store.getSnapshot,store.getSnapshot);
  const [period,setPeriod]=useState('1'),[relative,setRelative]=useState(false),[selected,setSelected]=useState<string|null>(null);
  const {assets}=useAssets();
  const row=data?.rows.find(r=>r.symbol===selected);
  const context=validMarketInternals(internals)?internals.periods[period]:null;
  const names=new Set(assets.filter(a=>a.market==='JP').map(a=>a.symbol));
  const members=context?.assets.filter(a=>names.has(a.instrumentId.replace('.T',''))&&a.sectorNameJa===row?.nameJa)??[];
  return <section className="card sector-heatmap" aria-label="業種ヒートマップ">
    <h3>業種の強弱</h3><p>日本株・業種ETFによる比較</p>
    {loading&&<TriangleStepLoader label="業種データを読み込んでいます"/>}
    {error&&<p role="status">最新データを読み込めません。取得済みの値は元の時点を確認してください。</p>}
    {data&&<>
      <p>{data.isToday?'当日':'休場・直近営業日'} {data.targetDate} · 遅延データ</p>
      <div className="sector-heatmap__controls"><label>期間 <select value={period} onChange={e=>setPeriod(e.target.value)}><option value="1">1営業日</option><option value="5">5営業日</option><option value="20">20営業日</option></select></label>
        <label>比較 <select value={relative?'relative':'return'} onChange={e=>setRelative(e.target.value==='relative')}><option value="return">騰落率</option><option value="relative">TOPIX連動ETFとの差</option></select></label></div>
      <p className="sector-heatmap__legend">緑：{relative?'市場比で上位':'上昇'} ／ 赤：{relative?'市場比で下位':'下落'} ／ 灰：未取得</p>
      <div className="sector-heatmap__grid">{data.rows.map(r=>{
        const value=r.periods[period]?.[relative?'relativeToBenchmarkPct':'returnPct'];
        const known=typeof value==='number'&&Number.isFinite(value);
        return <button key={r.symbol} aria-pressed={selected===r.symbol} className={!known?'missing':value>0?'positive':value<0?'negative':'flat'} onClick={()=>setSelected(r.symbol)}>
          <span>{r.nameJa}</span><strong>{pct(value,relative)}</strong><small>{r.state==='NOT_UPDATED'?'本日未更新':r.state==='DELAYED'?'更新に遅れ':r.symbol}</small></button>;
      })}</div>
      {row&&<div className="sector-heatmap__detail"><h4>{row.nameJa} · {row.symbol}</h4><p>{row.periods[period]?.startDate} → {row.periods[period]?.endDate}</p>
        <p>価格の時点：{stamp(row.sourceTimestamp)}（日本時間）</p><p>取得元：{row.source||'未取得'}</p>
        <p>登録銘柄との比較</p>{members.length?members.map(a=><p key={a.instrumentId}><a href={`#asset/${encodeURIComponent(a.instrumentId.replace('.T',''))}`}>{a.instrumentId}</a> · 確定終値の比較 {pct(a.returnPct)}（{a.endDate}）</p>):<p>この業種に対応付けを確認できた登録銘柄はありません。未確認の分類は推測しません。</p>}
      </div>}
      <p>場中は約20分間隔で取得します。配信元の遅延が加わります。色は価格の変化で、資金流入量や売買サインではありません。正式な33業種指数ではなく8業種ETFの比較です。</p>
      {Object.keys(data.collectionErrors??{}).length>0&&<p role="status">一部の取得に失敗しました。以前の価格時点を維持しています。</p>}
    </>}
  </section>;
}
