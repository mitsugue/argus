const assert=require('node:assert/strict'),fs=require('node:fs'),ts=require('typescript');
require.extensions['.ts']=(mod,file)=>mod._compile(ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,file);
const {todayEventSchedule}=require('../src/lib/todayEventSchedule.ts');
const now=Date.parse('2026-10-05T09:00:00+09:00');
const macro=(code,date,title,state='pre')=>({eventId:`${code}-${date}-${title}`,displayEventId:`${code}-${date}-${title}`,eventCode:code,eventDate:date,eventTimeUtc:null,title,state,importance:'high',officialResult:{available:false},caos:{},display:{}});
const legacy=(code,date,title)=>({eventId:`legacy-${code}-${date}`,eventCode:code,date,title,displayImpact:'high',lifecycle:'SCHEDULED'});
const equity=(kind,date)=>({eventId:`jp-${kind}-${date}`,kind,date,at:date,dateOnly:true,titleJa:kind,daysUntil:4});
const d=[macro('CPI','2026-10-14','US CPI'),macro('AUCTION','2026-10-07','US Treasury 10-Year Auction'),macro('NFP','2026-10-02','US Employment Situation','post_result')];
const l=[legacy('CPI','2026-10-14','US CPI'),legacy('CPI','2026-11-13','US CPI'),legacy('AUCTION','2026-10-07','US Treasury 30-Year Auction'),legacy('SQ','2026-10-09','SQ')];
const e=[equity('SQ','2026-10-09'),equity('SQ','2026-11-13'),equity('JP_CPI','2026-10-23')];
const before=JSON.stringify([d,l,e]);const rows=todayEventSchedule(d,l,e,now);
assert.equal(rows.filter(r=>r.day==='2026-10-14'&&r.event.eventCode==='CPI').length,1);
assert.equal(rows.filter(r=>r.day==='2026-10-07').length,2,'different bond maturities stay separate');
assert.equal(rows.filter(r=>r.day==='2026-10-09').length,1,'SQ appears once across calendars');
assert.equal(rows.filter(r=>r.day==='2026-11-13').length,2,'a later CPI and SQ remain');
assert.equal(rows[0].day,'2026-10-07');assert.equal(rows.at(-1).event.eventCode,'NFP');assert.equal(rows.at(-1).released,true);
assert.equal(JSON.stringify([d,l,e]),before,'sorting never mutates canonical feeds');
const boundary=macro('FOMC','2026-10-28','FOMC');boundary.eventTimeUtc='2026-10-28T18:00:00Z';
assert.equal(todayEventSchedule([boundary],[],[],now)[0].day,'2026-10-29','uses Japan date, not UTC date');
assert.equal(todayEventSchedule([],[],[equity('JP_CPI','2026-11-20')],now).length,0,'45-day window stays exact');
const aged=macro('NFP','2026-09-01','US Employment Situation','post_result');
assert.equal(todayEventSchedule([aged],[],[],now).length,0,'old releases do not reappear');
const undated={...macro('CPI',null,'US CPI'),eventDate:null};
assert.equal(todayEventSchedule([undated],[],[],now).length,1,'unconfirmed date is not silently lost');
const early={...legacy('CPI','2026-10-14','US CPI'),jstTime:'2026-10-14 08:30 JST'},late={...legacy('PPI','2026-10-14','US PPI'),jstTime:'2026-10-14 21:30 JST'};
assert.equal(todayEventSchedule([], [late,early], [], now)[0].event.eventCode,'CPI','same-day events use the published Japan time');
console.log('日付順の予定：重複除去・別の開催日・日本時間・45日・発表結果・元データ保持を確認');
const releasedCpi={...macro('CPI','2026-10-14','CPI','post_result'),eventTimeUtc:'2026-10-14T12:30:00Z'};
const imminentPpi={...macro('PPI','2026-10-15','PPI'),eventTimeUtc:'2026-10-15T12:30:00Z'};
const clock=Date.parse('2026-10-15T00:00:00Z');
assert.equal(todayEventSchedule([imminentPpi,releasedCpi],[],[],clock)[0].event.eventCode,'CPI','last night result leads upcoming event');
const laterEvent={...imminentPpi,eventDate:'2026-10-16',eventTimeUtc:'2026-10-16T13:00:00Z'};
assert.equal(todayEventSchedule([laterEvent,releasedCpi],[],[],Date.parse('2026-10-16T12:30:00Z'))[0].event.eventCode,'PPI','48h exact end unpins result');
const {prominentResult}=require('../src/lib/todayEventSchedule.ts');
assert.equal(prominentResult(todayEventSchedule([macro('CPI','2026-10-14','date only','post_result')],[],[],clock)[0],clock),false,'date only never invents an exact release time');
assert.equal(prominentResult(todayEventSchedule([{...releasedCpi,eventTimeUtc:'2026-10-15T12:30:00Z'}],[],[],clock)[0],clock),false,'future timestamp is not a recent result');

const event=(symbol)=>({eventId:'earnings-'+symbol,kind:'CORPORATE_EARNINGS',date:'2026-10-30',dateOnly:true,at:'2026-10-30T00:00:00-04:00',rangeEndAt:'2026-10-30T23:59:59.999999-04:00',sourceFromDate:'2026-10-30',sourceToDate:'2026-10-30',market:'US',titleJa:symbol+' 決算（推定）'});
const corporateNow=Date.parse('2026-10-31T01:00:00Z');
const corporateValues=[event('AAA'),event('BBB')];const corporateOriginal=JSON.stringify(corporateValues);const corporateRows=todayEventSchedule([],[],corporateValues,corporateNow);
assert.equal(corporateRows.length,2,'same day companies stay distinct');assert.equal(JSON.stringify(corporateValues),corporateOriginal);
assert(corporateRows.every(r=>!r.released&&!prominentResult(r,corporateNow)),'unknown time never becomes actual release');
assert.equal(todayEventSchedule([],[],corporateValues,Date.parse('2026-10-31T04:01:00Z')).length,0,'past local date range is removed');
assert.equal(require('../src/lib/japanEquityCalendar.ts').equityEventWhen(corporateValues[0]),'10/30 米国');
assert.equal(require('../src/lib/japanEquityCalendar.ts').equityEventWhen({...corporateValues[0],sourceToDate:'2026-11-02'}),'10/30〜11/02 米国');
assert.equal(require('../src/lib/japanEquityCalendar.ts').equityEventWhen({kind:'SQ',date:'2026-11-13',dateOnly:true}),'11/13(金)','existing calendars unchanged');
console.log('同日複数社・米国日付の末尾・推定範囲・発表未確認・既存の表示を確認');

// The top tile and fixed bar read the same calendar as EVENTS, without feeding the risk gate.
const {todayEventHighlights}=require('../src/lib/todayEventSchedule.ts');
const electionNow=Date.parse('2026-11-03T07:30:00Z');
const election={...equity('US_ELECTION_DAY','2026-11-03'),titleJa:'米国 中間選挙の投票日(2026年)',importance:'high'};
const near={...macro('MEDIUM','2026-11-03','検査用の予定'),importance:'medium',eventTimeUtc:'2026-11-03T08:00:00Z'};
const nfp={...macro('NFP','2026-11-06','US Employment Situation'),eventTimeUtc:'2026-11-06T13:30:00Z'};
const oldResult={...macro('CPI','2026-11-02','CPI','post_result'),eventTimeUtc:'2026-11-02T13:30:00Z'};
const inputs=[[nfp,near,oldResult],[legacy('NFP','2026-11-06','US Employment Situation')],[election]];
const unchanged=JSON.stringify(inputs),scheduled=todayEventSchedule(...inputs,electionNow),scheduleBefore=JSON.stringify(scheduled);
const highlights=todayEventHighlights(scheduled,electionNow);
assert.equal(highlights.featured.name,election.titleJa,'high-impact election is picked up even though absent from macro feed');
assert.deepEqual(highlights.next.map(e=>e.name),['検査用の予定',election.titleJa,'米雇用統計'],'footer carries the nearest three, chronological and deduplicated');
assert.equal(highlights.featured.remaining,null,'a date-only election has no fabricated countdown');
assert.match(highlights.featured.when,/11\/3.*時刻未公表/);
assert.equal(highlights.next[0].remaining,'あと30分');
assert(!highlights.next.some(e=>e.name==='米消費者物価'),'released results never become next events');
assert.equal(JSON.stringify(inputs),unchanged);assert.equal(JSON.stringify(scheduled),scheduleBefore);
assert.equal(todayEventHighlights(todayEventSchedule([],[],[{...equity('US_ELECTION_DAY','2026-11-12'),importance:'high'}],electionNow),electionNow).featured,null,'far or unclassified events are not promoted');
assert.equal(todayEventHighlights([],electionNow).next.length,0);
assert.equal(todayEventHighlights(corporateRows,corporateNow).next.length,2,'current US-local earnings dates remain eligible');
assert.match(todayEventHighlights(todayEventSchedule([nfp],[],[],electionNow),electionNow).next[0].when,/22:30/,'post-DST clock stays Japan time');
console.log('選挙の重要予定・日付順3件・発表済み除外・同日重複・時刻未公表・米国日付と夏時間を確認');
const nativeElection={...election,market:'US',sourceTimezone:'America/New_York',sourceFromDate:'2026-11-03',sourceToDate:'2026-11-03',
 at:'2026-11-03T00:00:00-05:00',rangeEndAt:'2026-11-03T23:59:59-05:00'};
const japanNextDay=Date.parse('2026-11-04T08:00:00+09:00');
const electionRows=todayEventSchedule([],[],[nativeElection],japanNextDay);
assert.equal(electionRows.length,1,'US voting date remains visible after Japan midnight');
const electionPreview=todayEventHighlights(electionRows,japanNextDay);
assert.equal(electionPreview.featured.name,nativeElection.titleJa);
assert.equal(electionPreview.next[0].remaining,null,'native midnight boundaries never become a release countdown');
assert.match(electionPreview.next[0].when,/11\/3.*米国.*時刻未公表/);
assert.equal(require('../src/lib/japanEquityCalendar.ts').equityEventDistance(nativeElection,japanNextDay),'米国の今日');
assert.equal(todayEventSchedule([],[],[nativeElection],Date.parse('2026-11-04T05:00:00Z')).length,0,'exact local-date end removes the upcoming event');
// 2026-11-13 (audit): the dashboard feed names PPI by its family, the important-events feed by itself.
{
  const ppiNow=Date.parse('2026-11-13T22:50:00+09:00');
  const dash={...macro('INFLATION','2026-11-13','US PPI (Producer Price Index)','released_pending_result'),eventTimeUtc:'2026-11-13T13:30:00Z'};
  const old={...legacy('PPI','2026-11-13','US PPI (Producer Price Index)'),eventTimeUtc:'2026-11-13T13:30:00Z',lifecycle:'IMMINENT'};
  const later={...legacy('PPI','2026-12-15','US PPI (Producer Price Index)'),eventTimeUtc:'2026-12-15T13:30:00Z'};
  const joined=todayEventSchedule([dash],[old,later],[],ppiNow);
  assert.equal(joined.filter(r=>r.day==='2026-11-13').length,1,'one PPI row on the release day');
  assert.equal(joined.find(r=>r.day==='2026-11-13').kind,'dashboard','the released feed row is kept');
  assert.equal(joined.filter(r=>r.day==='2026-12-15').length,1,'the next PPI stays');
  const other={...legacy('CPI','2026-11-13','US CPI (Consumer Price Index)'),eventTimeUtc:'2026-11-13T13:30:00Z'};
  assert.equal(todayEventSchedule([dash],[other],[],ppiNow).length,2,'a different indicator on the same day stays');
  console.log('同じ日の同じ指標を、識別子が違っても1行にまとめる PASS');
}
// 2026-11-13 (audit): the live Today view (the editorial surface) never received the
// schedule's next event, so 次の山場 showed the explanation's chip (SQ 今日 at 22:50).
{
  const surface=fs.readFileSync('src/components/today/ArgusEditorialSurface.tsx','utf8');
  const card=fs.readFileSync('src/components/today/MarketBriefCard.tsx','utf8');
  assert.equal((surface.match(/<TodayDecisionStrip [^>]*featuredEvent=\{featuredEvent\}/g)||[]).length,2,'both strips get the event');
  assert.ok(/<ArgusEditorialSurface [^]*?featuredEvent=\{featuredEvent\} \/>/.test(card),'the card hands it to the surface');
  console.log('見立ての面の「次の山場」に予定の一覧をつなぐ PASS');
}
