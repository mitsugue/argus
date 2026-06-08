# A.R.G.U.S. — Autonomous Risk and Global Uncertainty Scanner (backend, velvet-razor)
# US Market High-Resolution AI Scanner
import os, time, requests, anthropic, json, threading, re, math, statistics, concurrent.futures
try:
    from google import genai as google_genai
    from google.genai import types as genai_types
except Exception:
    google_genai = None
    genai_types  = None
try:
    from moomoo import OpenQuoteContext, OpenSecTradeContext, RET_OK
    MOOMOO_AVAILABLE = True
except ImportError:
    MOOMOO_AVAILABLE = False
import pytz
from datetime import datetime, timedelta
from flask import Flask, jsonify, request
from collections import deque
import argus_ledger  # Local — A.R.G.U.S. prediction ledger
try:
    from flask_cors import CORS  # optional; only needed for /api/argus/* cross-origin
except Exception:
    CORS = None

# ━━━ Environment Variables ━━━
FINNHUB_API_KEY   = os.environ.get("FINNHUB_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY", "")
NEWS_API_KEY      = os.environ.get("NEWS_API_KEY", "")
NTFY_CHANNEL      = os.environ.get("NTFY_CHANNEL", "mitsugu-stock-scanner")
MOOMOO_HOST       = os.environ.get("MOOMOO_HOST", "127.0.0.1")
MOOMOO_PORT       = int(os.environ.get("MOOMOO_PORT", 11111))
PORT              = int(os.environ.get("PORT", 8080))

# ━━━ DST Auto-Detection & Market Time ━━━
TZ_ET  = pytz.timezone("US/Eastern")
TZ_JST = pytz.timezone("Asia/Tokyo")

def is_dst_now():
    return bool(datetime.now(TZ_ET).dst())

def get_jst_schedule():
    dst = is_dst_now()
    offset = 13 if dst else 14
    return {
        "ph1":   f"{8+offset:02d}:30",
        "ph2":   f"{8+offset:02d}:50",
        "ph3":   f"{9+offset:02d}:10",
        "ph4":   f"{9+offset:02d}:20",
        "ph5_1": f"{9+offset:02d}:30",
        "ph5_2": f"{10+offset:02d}:00",
    }

MARKET_OPEN_ET  = (9, 30)
MARKET_CLOSE_ET = (16, 0)

def is_market_open():
    """Check if US market is currently open (regular + pre-market)"""
    now_et = datetime.now(TZ_ET)
    if now_et.weekday() >= 5:  # Weekend
        return False, "closed_weekend"
    h, m = now_et.hour, now_et.minute
    if h < 4:
        return False, "closed"
    elif h < 9 or (h == 9 and m < 30):
        return True, "premarket"
    elif h < 16:
        return True, "regular"
    elif h < 20:
        return True, "afterhours"
    return False, "closed"

DRY_RUN_MODE = False  # Set True when manual scan during closed market

# ━━━ Exit State Machine Constants ━━━
EXIT_STATE_OPEN_DISCOVERY  = "S0"
EXIT_STATE_SHAKEOUT        = "S1"
EXIT_STATE_HEALTHY_UPTREND = "S2"
EXIT_STATE_DISTRIBUTION    = "S3"
EXIT_STATE_THESIS_BROKEN   = "S4"
EXIT_STATE_PARABOLIC       = "S5"

GRADE_KEYWORDS = {
    "A": ["earnings beat","raised guidance","buyback","record revenue","dividend increase"],
    "B": ["AI","semiconductor","defense","cloud","data center","EV","GLP-1"],
    "C": ["theme","momentum","trending","sector rotation"],
    "D": ["meme","short squeeze","penny","speculative"],
}
WHALE_FIRMS = ["Goldman Sachs","JP Morgan","Morgan Stanley","Bank of America",
               "Citigroup","Wells Fargo","UBS","Deutsche Bank","Barclays"]

# ━━━ Global State ━━━
LOG_BUFFER = deque(maxlen=200)
PRICE_HISTORY = {}
CHART_CACHE = {}
SYMBOL_CACHE = None
SYMBOL_CACHE_TIME = 0
SCHEDULED_RUN = False
BACKGROUND_TASK_RUNNING = False
MOOMOO_QUOTE_CTX = None
MOOMOO_TRADE_CTX = None
_finnhub_calls = deque(maxlen=60)

def finnhub_rate_limit():
    now = time.time()
    while _finnhub_calls and _finnhub_calls[0] < now - 60:
        _finnhub_calls.popleft()
    if len(_finnhub_calls) >= 55:
        wait = 60 - (now - _finnhub_calls[0])
        if wait > 0:
            time.sleep(wait)
    _finnhub_calls.append(time.time())
# ━━━ HTML UI (US Market Version) ━━━
HTML = """<!DOCTYPE html>
<html lang="ja"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>A.R.G.U.S. — backend</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;700&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0d0d0d;color:#c8c8c8;font-family:'JetBrains Mono',monospace;font-size:12px;padding:10px;max-width:600px;margin:0 auto;-webkit-text-size-adjust:100%}
header{display:flex;align-items:center;margin-bottom:10px;padding-bottom:8px;border-bottom:1px solid #1e1e1e}
.logo{font-size:16px;font-weight:700;color:#74fafd;letter-spacing:2px;cursor:pointer}
.sub{font-size:10px;color:#4a4a4a;margin-top:2px}
.time{font-size:14px;color:#74fafd;font-weight:700;letter-spacing:1px}
.lbl{color:#4a4a4a;font-size:10px;margin:8px 0 4px;letter-spacing:2px;text-transform:uppercase}
.phase-bar{display:flex;gap:3px;margin-bottom:8px}
.ph{flex:1;height:6px;background:#1a1a1a;border-radius:1px;position:relative;overflow:hidden;transition:background .3s}
.ph.done{background:#4ec94e}.ph.active{background:#74fafd;animation:pulse .8s infinite alternate}
@keyframes pulse{from{opacity:1}to{opacity:.4}}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes fadeIn{from{opacity:0}to{opacity:1}}
.btn-row{display:flex;gap:4px;margin-bottom:8px;flex-wrap:wrap}
.ph-btn{flex:1;min-width:50px;padding:8px 2px;background:#1a1a1a;border:1px solid #2a2a2a;color:#74fafd;font-family:inherit;font-size:10px;text-align:center;cursor:pointer;border-radius:3px;line-height:1.4;transition:all .15s;-webkit-tap-highlight-color:transparent}
.ph-btn:active{background:#2a2a2a;transform:scale(.96)}
.ph-btn:disabled{opacity:.3;cursor:default}
.spinner{display:inline-block;width:10px;height:10px;border:2px solid #333;border-top-color:#74fafd;border-radius:50%;animation:spin .6s linear infinite;vertical-align:middle;margin-right:4px}
.sentinel-box{background:#1a1a1a;border:1px solid #2a2a2a;border-radius:3px;margin-bottom:8px;font-size:10px;overflow:hidden}
.sentinel-header{display:flex;align-items:center;gap:8px;padding:8px 10px;cursor:pointer}
.sentinel-body{max-height:0;overflow:hidden;transition:max-height .3s;padding:0 10px;font-size:10px;color:#888}
.sentinel-body.open{max-height:400px;padding:8px 10px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.info-box{background:#1a1a1a;border:1px solid #1e1e1e;border-radius:3px;padding:8px 10px}
.info-lbl{font-size:10px;color:#4a4a4a;margin-bottom:4px}
.info-val{font-size:11px;color:#c8c8c8;line-height:1.5;word-break:break-all}
.log-box{background:#0a0a0a;border:1px solid #1e1e1e;border-radius:3px;padding:8px 10px;max-height:200px;overflow-y:auto;font-size:10px;line-height:1.6;color:#888;-webkit-overflow-scrolling:touch}
.cursor{display:inline-block;width:6px;height:12px;background:#74fafd;animation:pulse 1s infinite;vertical-align:text-bottom;margin-left:2px}
.stock-tabs{display:flex;gap:2px;margin-bottom:6px;flex-wrap:wrap}
.stock-tabs button{padding:5px 10px;background:#1a1a1a;border:1px solid #2a2a2a;color:#888;font-family:inherit;font-size:10px;cursor:pointer;border-radius:3px;transition:all .15s}
.stock-tabs button.on{background:#2a2a2a;color:#74fafd;border-color:#74fafd}
.card{background:#1a1a1a;border:1px solid #2a2a2a;border-left:3px solid #3d9ea1;border-radius:3px;padding:10px;margin-bottom:6px;cursor:pointer;transition:all .15s}
.card.sel{border-color:#74fafd;background:#1e2a2e}
.card-hd{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.c-code{color:#74fafd;font-weight:700;font-size:12px}
.c-name{color:#c8c8c8;font-size:11px}
.c-chg{font-size:11px;font-weight:700;margin-left:auto}
.c-tgt{color:#4a4a4a;font-size:10px}
.meta-row{display:flex;align-items:center;gap:8px;margin-top:4px;flex-wrap:wrap}
.stars{color:#f0a500;font-size:10px}
.tag{background:#1e2a1e;color:#4ec94e;font-size:9px;padding:1px 6px;border-radius:2px}
.reason,.stoploss{font-size:10px;margin-top:4px;line-height:1.5;color:#888}
.stoploss{color:#f44747}
.reason em,.stoploss em{font-style:normal;color:#4a4a4a}
.action-banner{margin-top:8px;padding:8px;background:#0d1a1e;border:1px solid #74fafd;border-radius:3px}
.action-title{color:#74fafd;font-size:11px;font-weight:700;margin-bottom:6px}
.action-row{display:flex;gap:4px;flex-wrap:wrap}
.action-btn{padding:6px 12px;border:1px solid #2a2a2a;border-radius:3px;font-family:inherit;font-size:10px;cursor:pointer;transition:all .15s}
.action-btn.primary{background:#1e3a3e;color:#74fafd;border-color:#74fafd}
.action-btn.secondary{background:#1a1a1a;color:#c8c8c8}
.action-btn.cancel{background:#1a1a1a;color:#888;border-color:#444}
.action-note{font-size:9px;color:#4a4a4a;margin-top:6px}
.ob-panel{margin-top:6px;padding:6px;background:#0a0a0a;border:1px solid #1e1e1e;border-radius:3px;font-size:9px}
.ob-title{color:#4a4a4a;font-size:9px;margin-bottom:4px;letter-spacing:1px}
.ob-row{display:flex;gap:4px;margin:1px 0}
.ob-bid{color:#4ec94e}.ob-ask{color:#f44747}.ob-vol{color:#4a4a4a;margin-left:auto}
.margin-alert{background:#2a1a1a;border:1px solid #f44747;border-radius:3px;padding:6px 8px;margin-top:6px;font-size:10px;color:#f44747}
.ph5-result{margin-bottom:14px;padding:10px 12px;background:#1e2a1e;border:1px solid #2d4a2d;border-radius:3px;animation:fadeIn .3s}
.ph5-overall{color:#4ec94e;font-size:11px;font-weight:700;margin-bottom:6px}
.ph5-eval{margin:4px 0;font-size:10px;color:#c8c8c8;line-height:1.5}
.ph5-eval .ev-code{color:#74fafd;font-weight:700}
.ph5-eval .ev-advice{color:#3d9ea1;margin-left:8px}
.price-tag{font-size:11px;color:#74fafd;margin-left:auto;font-weight:700}
.price-chg-up{color:#4ec94e}.price-chg-dn{color:#f44747}
</style></head><body>
<header>
  <div><div class="logo" id="logoBtn" onclick="location.reload()">A.R.G.U.S.</div><div class="sub">velvet-razor v2.0 — Autonomous Risk and Global Uncertainty Scanner</div></div>
  <div style="margin-left:auto;text-align:right">
  <div class="time" id="clk">--:--:-- ET</div>
  <div id="statusBadge" style="font-size:11px;font-weight:700;color:#4ec94e;margin-top:2px">&#9679; ONLINE</div>
</div>
</header>
<div style="display:flex;align-items:center;margin-bottom:6px">
  <span class="lbl" style="margin:0">-- PHASE PROGRESS --</span>
  <span id="marketSession" style="margin-left:auto;font-size:10px;color:#4a4a4a">Detecting...</span>
</div>
<div class="phase-bar" id="phBar"></div>
<div class="lbl">-- MANUAL SCAN --</div>
<div class="btn-row">
  <button class="ph-btn" id="b1" data-phase="1">&#128225;<br>Ph.1</button>
  <button class="ph-btn" id="b2" data-phase="2">&#128300;<br>Ph.2</button>
  <button class="ph-btn" id="b3" data-phase="3">&#9889;<br>Ph.3</button>
  <button class="ph-btn" id="b4" data-phase="4">&#127942;<br>Ph.4</button>
  <button class="ph-btn" id="b5" data-phase="5">&#128200;<br>Ph.5</button>
  <button class="ph-btn" id="b0" data-phase="0">&#128640;<br>All Ph.</button>
  <button class="ph-btn" id="bReset" onclick="resetScan()" style="border-color:#666;color:#888">&#8635;<br>Reset</button>
</div>
<div class="sentinel-box" id="sentBox">
  <div class="sentinel-header" id="sentHdr">
    <span id="sentStatus" style="color:#74fafd;font-weight:700;min-width:150px">&#9632; SENTINEL: HOLD</span>
    <span id="sentBars" style="color:#ce9178;letter-spacing:3px">&#9617;&#9617;&#9617;&#9617;&#9617;</span>
    <span id="sentRisk" style="color:#4a4a4a">(0/5)</span>
    <span id="sentShort" style="color:#3d9ea1;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">-- Loading...</span>
    <span id="sentArr" style="color:#4a4a4a;font-size:10px">&#9660;</span>
  </div>
  <div class="sentinel-body" id="sentBody"></div>
</div>
<div class="grid2">
  <div class="info-box"><div class="info-lbl">&#128202; Market</div><div class="info-val" id="mkt">-</div></div>
  <div class="info-box"><div class="info-lbl">&#127760; Macro</div><div class="info-val" id="mac">-</div></div>
</div>
<div class="grid2" style="margin-top:6px">
  <div class="info-box"><div class="info-lbl">&#128200; VIX / S&amp;P500</div><div class="info-val" id="finnhubVal">VIX: -- &nbsp; S&P500: --</div></div>
  <div class="info-box" id="finnhubAlertBox" style="display:none"><div class="info-lbl" style="color:#f44747">&#9888; Macro Alert</div><div class="info-val" id="finnhubAlert" style="color:#f44747;font-size:11px">-</div></div>
</div>
<div class="lbl">-- SCAN LOG --</div>
<div class="log-box" id="log"><span style="color:#3d9ea1">Initializing...<span class="cursor"></span></span></div>
<div class="lbl" style="margin-top:14px">-- TODAY'S CANDIDATES --</div>
<div class="stock-tabs" id="stockTabs"></div>
<div id="stockList"><div style="color:#4a4a4a;font-size:11px;padding:12px">No scan results yet.</div></div>
<script>
var sel=null,busy=false,sentOpen=false,curTab=4,lastState={},userChoseTab=false;
var scanningPhase=0,scanStartTime=0,progressInterval=null;
var phaseEstimates={1:45,2:40,3:50,4:30,5:30,0:200};
var phaseActions={1:['Fetching stocks','Sentinel check','AI analyzing','Narrowing'],2:['Re-scoring','AI analyzing','Ranking'],3:['Cross-checking','Rating check','Gemini grounding'],4:['Order book','Selecting TOP3','Verify'],5:['Prices','Momentum','Order book']};
var btnLabels={0:'&#128640;<br>All Ph.',1:'&#128225;<br>Ph.1',2:'&#128300;<br>Ph.2',3:'&#9889;<br>Ph.3',4:'&#127942;<br>Ph.4',5:'&#128200;<br>Ph.5'};
var medals=['&#127941;','&#127942;','&#127943;'];

function startProgressTimer(p){scanningPhase=p;scanStartTime=Date.now();if(progressInterval)clearInterval(progressInterval);progressInterval=setInterval(function(){var e=(Date.now()-scanStartTime)/1000,d=scanningPhase>0?scanningPhase:p,est=phaseEstimates[d]||90,pct=Math.min(100,Math.round(e/est*100));if(window._pcm&&window._pcm[d])pct=100;var b=document.getElementById('statusBadge');if(b&&scanningPhase>0){var a=phaseActions[d]||['Processing'],ai=Math.min(Math.floor(pct/100*a.length),a.length-1);b.innerHTML='<span style="display:inline-block;width:7px;height:7px;border:2px solid #333;border-top-color:#74fafd;border-radius:50%;animation:spin .6s linear infinite;vertical-align:middle;margin-right:4px"></span>Ph.'+d+' '+a[ai]+' '+pct+'%';b.style.color='#74fafd';}},500);}
function stopProgressTimer(){scanningPhase=0;if(progressInterval){clearInterval(progressInterval);progressInterval=null;}}

setInterval(function(){
  var now=new Date();
  var etStr=now.toLocaleString('en-US',{timeZone:'America/New_York',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false});
  var jstStr=now.toLocaleString('ja-JP',{timeZone:'Asia/Tokyo',hour:'2-digit',minute:'2-digit',hour12:false});
  var etDate=new Date(now.toLocaleString('en-US',{timeZone:'America/New_York'}));
  var days=['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
  document.getElementById('clk').textContent=days[etDate.getDay()]+' '+etStr+' ET ('+jstStr+' JST)';
  var h=etDate.getHours(),m=etDate.getMinutes(),dow=etDate.getDay();
  var ms=document.getElementById('marketSession');
  if(ms){var s,c;if(dow===0||dow===6){s='Closed (Weekend)';c='#4a4a4a';}else if(h<4){s='Closed';c='#4a4a4a';}else if(h<9||(h===9&&m<30)){s='Pre-Market';c='#ce9178';}else if(h<16){s='MARKET LIVE';c='#f44747';}else if(h<20){s='After Hours';c='#3d9ea1';}else{s='Closed';c='#4a4a4a';}ms.textContent=s;ms.style.color=c;}
},1000);

setInterval(function(){fetchState();},3000);

document.getElementById('sentHdr').addEventListener('click',function(){sentOpen=!sentOpen;document.getElementById('sentBody').classList.toggle('open',sentOpen);document.getElementById('sentArr').innerHTML=sentOpen?'&#9650;':'&#9660;';});
document.querySelectorAll('[data-phase]').forEach(function(btn){btn.addEventListener('click',function(){run(parseInt(this.dataset.phase));});});
document.getElementById('stockTabs').addEventListener('click',function(e){var b=e.target;while(b&&b!==this&&!b.dataset.tab)b=b.parentNode;if(!b||!b.dataset.tab)return;curTab=parseInt(b.dataset.tab);userChoseTab=true;render(lastState);});

async function resetScan(){if(busy)return;if(!confirm('Reset scan data?'))return;try{await fetch('/api/reset',{method:'POST'});sel=null;curTab=1;lastState={};userChoseTab=false;await fetchState();}catch(e){}}
async function fetchState(){try{var r=await fetch('/api/state?t='+Date.now());var d=await r.json();lastState=d;render(d);if(d.scanning&&!busy){busy=true;if(scanningPhase===0)startProgressTimer((d.phase||0)+1);}}catch(e){}}

function render(d){if(!d)return;
  var pb=document.getElementById('phBar');if(pb){var h='';for(var i=1;i<=5;i++){var c='ph';if(d.phase>=i)c+=' done';else if(d.scanning&&d.phase===i-1)c+=' active';h+='<div class="'+c+'"></div>';}pb.innerHTML=h;}
  var me=document.getElementById('mkt');if(me)me.textContent=d.market_condition||'-';
  var ma=document.getElementById('mac');if(ma)ma.textContent=d.macro_summary||'-';
  var fm=d.finnhub_macro||{},fv=document.getElementById('finnhubVal');
  if(fv)fv.innerHTML='VIX: '+(fm.vix||'--')+' &nbsp; S&P500: '+(fm.sp500_change!=null?(fm.sp500_change>=0?'+':'')+fm.sp500_change+'%':'--');
  var fab=document.getElementById('finnhubAlertBox'),fa=document.getElementById('finnhubAlert');
  if(fm.fear_level&&fm.fear_level!=='NORMAL'&&fm.fear_level!=='CALM'){if(fab)fab.style.display='';if(fa)fa.textContent=fm.fear_level+' (VIX: '+(fm.vix_spike_pct||0).toFixed(1)+'%)';}else{if(fab)fab.style.display='none';}
  var sent=d.sentinel||{},ss=document.getElementById('sentStatus');
  if(ss){if(sent.action==='SELL_ALL'){ss.innerHTML='SENTINEL: SELL ALL';ss.style.color='#f44747';}else{ss.innerHTML='SENTINEL: HOLD';ss.style.color='#74fafd';}}
  var sb=document.getElementById('sentBody');if(sb&&sent.reason)sb.innerHTML='<div style="color:#f44747">'+sent.reason+'</div>';
  var le=document.getElementById('log');
  if(le&&d.log&&d.log.length){le.innerHTML=d.log.map(function(l){var c='#888';if(l.indexOf('ERROR')>=0)c='#f44747';else if(l.indexOf('complete')>=0||l.indexOf('HOLD')>=0)c='#4ec94e';else if(l.indexOf('Ph.')>=0)c='#74fafd';return '<div style="color:'+c+'">'+l+'</div>';}).join('');le.scrollTop=le.scrollHeight;}
  var tabs=document.getElementById('stockTabs');
  if(tabs){var hd=[d.top20&&d.top20.length?1:0,d.top10&&d.top10.length?2:0,d.top5&&d.top5.length?3:0,d.top3_final&&d.top3_final.length?4:0,d.post_open_result?5:0].filter(function(x){return x>0;});if(hd.length){tabs.innerHTML=hd.map(function(t){var l=['','Ph.1(20)','Ph.2(10)','Ph.3(5)','TOP3','Ph.5'][t];return '<button data-tab="'+t+'" class="'+(curTab===t?'on':'')+'">'+l+'</button>';}).join('');}if(!userChoseTab&&hd.length)curTab=hd[hd.length-1];}
  var stocks=[];var isFinal=false;
  if(curTab===1)stocks=d.top20||[];else if(curTab===2)stocks=d.top10||[];else if(curTab===3)stocks=d.top5||[];else if(curTab===4){stocks=d.top3_final||[];isFinal=true;}else if(curTab===5){renderPh5(d);return;}
  renderStocks(stocks,isFinal,d.realtime_prices||{});
  if(!d.scanning){var bg=document.getElementById('statusBadge');if(bg&&scanningPhase===0){bg.innerHTML='&#9679; ONLINE';bg.style.color='#4ec94e';}}
  // Dry Run badge
  var ms2=document.getElementById('marketSession');
  if(ms2&&d.dry_run){ms2.textContent='🔬 DRY RUN (Closed Market)';ms2.style.color='#f0a500';}
}

function renderPh5(d){var el=document.getElementById('stockList');var por=d.post_open_result||{};var evals=por.evaluations||[];var pr=d.realtime_prices||{};var h='';
  if(por.overall){h+='<div class="ph5-result"><div class="ph5-overall">'+por.overall+'</div>';evals.forEach(function(ev){var ic=ev.status==='HOLD'?'OK':'ALERT';var p=pr[ev.code]||{};var pt=p.change_pct!=null?'<span class="price-tag '+(p.change_pct>=0?'price-chg-up':'price-chg-dn')+'">'+(p.change_pct>=0?'+':'')+p.change_pct+'%</span>':'';h+='<div class="ph5-eval"><span class="ev-code">'+ic+' '+ev.code+'</span>'+pt+'<br>'+ev.message+'<span class="ev-advice"> -> '+ev.action_advice+'</span></div>';});h+='</div>';}
  if(d.margin_alert)h+='<div class="margin-alert">'+d.margin_alert+'</div>';
  var obs=d.order_book||{};Object.keys(obs).forEach(function(sym){var ob=obs[sym];h+='<div class="ob-panel"><div class="ob-title">ORDER BOOK: '+sym+'</div>';h+='<div style="color:#4a4a4a">AR:'+(ob.absorption_ratio!=null?ob.absorption_ratio.toFixed(2):'-')+' Vacuum:'+(ob.downside_efficiency!=null?ob.downside_efficiency.toFixed(2):'-')+'</div>';if(ob.bids)ob.bids.slice(0,5).forEach(function(b){h+='<div class="ob-row"><span class="ob-bid">BID $'+b[0]+'</span><span class="ob-vol">x'+b[1]+'</span></div>';});if(ob.asks)ob.asks.slice(0,5).forEach(function(a){h+='<div class="ob-row"><span class="ob-ask">ASK $'+a[0]+'</span><span class="ob-vol">x'+a[1]+'</span></div>';});h+='</div>';});
  el.innerHTML=h||'<div style="color:#4a4a4a;font-size:11px;padding:12px">Ph.5 not yet executed.</div>';}

function renderStocks(stocks,isFinal,prices){prices=prices||{};
  var h=stocks.map(function(s,i){var isSel=sel===s.symbol;var conf=s.confidence||0;var stars='\u2605'.repeat(conf)+'\u2606'.repeat(5-conf);var score=s.score||s.final_score||'-';var chg=s.change_pct!=null?(s.change_pct>=0?'+':'')+Number(s.change_pct).toFixed(2)+'%':'';var bl=isFinal?(i===0?'#74fafd':i===1?'#3d9ea1':'#4a4a4a'):'#3d9ea1';var pf=isFinal&&i<3?medals[i]+' ':'#'+(i+1)+' ';
    var ah='';if(isSel){ah='<div class="action-banner"><div class="action-title">'+s.symbol+' - '+(s.name||'')+'</div><div class="action-row"><button class="action-btn primary" data-action="copy" data-code="'+s.symbol+'">Copy Ticker</button><button class="action-btn secondary" data-action="yahoo" data-code="'+s.symbol+'">Yahoo Finance</button><button class="action-btn secondary" data-action="moomoo" data-code="'+s.symbol+'">moomoo</button><button class="action-btn cancel" data-action="cancel">X</button></div><div class="action-note">Copy ticker and place order on moomoo at 09:30 ET</div></div>';}
    var mh='';if(s.margin_deadline)mh='<div class="margin-alert">Margin 20%: -'+s.margin_drop_pct+'% ($'+s.margin_deadline+')</div>';
    return '<div class="card'+(isSel?' sel':'')+'" data-code="'+s.symbol+'" style="border-left-color:'+bl+'"><div class="card-hd"><span style="color:#4a4a4a;font-size:11px;min-width:24px">'+pf+'</span><span class="c-code">'+s.symbol+'</span><span class="c-name">'+(s.name||'')+'</span>'+(chg?'<span class="c-chg '+(s.change_pct>=0?'price-chg-up':'price-chg-dn')+'">'+chg+'</span>':'')+'</div><div class="meta-row">'+(conf?'<span class="stars">'+stars+'</span>':'')+'<span style="color:#74fafd;font-size:10px">Score:'+score+'</span>'+(s.theme?'<span class="tag">'+s.theme+'</span>':'')+(s.grade?'<span class="tag" style="background:#1e1e2a;color:#ce9178">Grade:'+s.grade+'</span>':'')+'</div><div class="reason"><em>根拠: </em>'+(s.reason||s.buy_reason||'')+'</div>'+(s.sell_trigger?'<div class="stoploss"><em>損切り: </em>'+s.sell_trigger+'</div>':'')+(s.whale_signal?'<div style="font-size:10px;color:#f0a500;margin-top:4px">'+s.whale_signal+'</div>':'')+mh+ah+'</div>';}).join('');
  document.getElementById('stockList').innerHTML=h||'<div style="color:#4a4a4a;font-size:11px;padding:12px">No data.</div>';}

document.addEventListener('click',function(e){var ab=e.target.closest('[data-action]');if(ab){var act=ab.dataset.action;if(act==='copy'){navigator.clipboard.writeText(ab.dataset.code);var m=document.createElement('div');m.style.cssText='position:fixed;top:20px;right:20px;background:#4ec94e;color:#1a1a1a;padding:10px 16px;border-radius:3px;font-family:monospace;font-size:12px;font-weight:700;z-index:9999';m.textContent=ab.dataset.code+' copied';document.body.appendChild(m);setTimeout(function(){m.remove();},2500);}else if(act==='yahoo'){window.open('https://finance.yahoo.com/quote/'+ab.dataset.code,'_blank');}else if(act==='moomoo'){window.open('https://www.moomoo.com/stock/'+ab.dataset.code+'-US','_blank');}else if(act==='cancel'){sel=null;render(lastState);}return;}var card=e.target.closest('[data-code]');if(card){var code=card.dataset.code;sel=sel===code?null:code;render(lastState);}});

async function run(id){if(busy)return;busy=true;var prev=lastState.phase||0;startProgressTimer(id===0?1:id);document.querySelectorAll('[data-phase]').forEach(function(b){b.disabled=true;});var tgt=document.getElementById('b'+id);if(tgt)tgt.innerHTML='<span class="spinner"></span>Run';
  try{await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({phase:id})});var to=0;while(to<300){await new Promise(function(r){setTimeout(r,3000);});to+=3;var resp=await fetch('/api/state?t='+Date.now());var d2=await resp.json();lastState=d2;render(d2);var np=d2.phase||0;var rp=scanningPhase;var ll=d2.log?d2.log.slice(-5).join(' '):'';if(ll.indexOf('Ph.5:')>=0)rp=5;else if(ll.indexOf('Ph.4:')>=0)rp=4;else if(ll.indexOf('Ph.3:')>=0)rp=3;else if(ll.indexOf('Ph.2:')>=0)rp=2;var nx=Math.max(np>=5?5:np+1,rp);if((np>0&&np>=scanningPhase)||nx>scanningPhase){var cp=scanningPhase;if(progressInterval){clearInterval(progressInterval);progressInterval=null;}var b2=document.getElementById('statusBadge');if(b2&&cp>0){if(!window._pcm)window._pcm={};window._pcm[cp]=true;b2.innerHTML='<span style="color:#4ec94e">Ph.'+cp+' DONE</span>';}scanningPhase=nx;setTimeout(function(){scanStartTime=Date.now();if(scanningPhase<5)startProgressTimer(scanningPhase);},3000);}var p5d=(id===5)&&(d2.post_open_result!=null&&d2.post_open_result.overall);var done;if(id===0)done=np>=4;else if(id<prev)done=np===id;else done=p5d||(np>prev||np>=id);if(done)break;}}catch(e){}
  stopProgressTimer();busy=false;document.querySelectorAll('[data-phase]').forEach(function(b){var pid=parseInt(b.dataset.phase);b.innerHTML=btnLabels[pid];b.disabled=false;});if(id>0&&id<=5){curTab=id;userChoseTab=true;}await fetchState();}

(async function(){try{var r=await fetch('/api/state?t='+Date.now());if(r.ok){var d=await r.json();lastState=d;render(d);}}catch(e){}})();
</script></body></html>
"""
# ━━━ Flask App & State Management ━━━
claude     = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
STATE_FILE = "/tmp/scan_state.json"
app        = Flask(__name__)

# CORS for /api/argus/* — lets the React frontend (Vercel, GitHub Pages,
# and localhost dev) call the ledger / rates endpoints. Other routes
# stay same-origin.
if CORS is not None:
    CORS(app, resources={r"/api/argus/*": {"origins": [
        re.compile(r"^http://localhost(:\d+)?$"),
        re.compile(r"^http://127\.0\.0\.1(:\d+)?$"),
        # Pin Vercel to this project's deploys (argus*.vercel.app) rather than
        # any *.vercel.app — the latter let any attacker-controlled Vercel
        # subdomain read the /api/argus/* endpoints. Adjust the prefix if the
        # Vercel project is ever renamed.
        re.compile(r"^https://argus[a-z0-9-]*\.vercel\.app$"),
        re.compile(r"^https://mitsugue\.github\.io$"),
    ]}})

@app.after_request
def add_no_cache(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

def safe_json(text):
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text).strip()
    try:
        from json_repair import repair_json
        return json.loads(repair_json(text))
    except Exception: pass
    try:
        fixed = re.sub(r'(?<=": ")(.*?)(?=")', lambda m: m.group(0).replace('\n', ' '), text, flags=re.DOTALL)
        return json.loads(fixed)
    except Exception: pass
    try: return json.loads(text.replace('\n', ' '))
    except Exception: return {}

# Reentrant lock guarding STATE_FILE: serializes reads/writes across the scan
# worker, scheduler, and request threads. Reentrant so a load→modify→save done
# while already holding the lock (see add_log) doesn't deadlock.
_STATE_LOCK = threading.RLock()

def load_state():
    with _STATE_LOCK:
        try:
            with open(STATE_FILE, "r") as f: return json.load(f)
        except Exception: return {"phase": 0, "log": []}

def save_state(state):
    # Atomic write: dump to a temp file then os.replace, so a concurrent reader
    # never sees a half-written (truncated) file — which previously surfaced as
    # load_state() falling back to {"phase": 0} and momentarily resetting phase.
    with _STATE_LOCK:
        try:
            tmp = f"{STATE_FILE}.{os.getpid()}.tmp"
            with open(tmp, "w") as f: json.dump(state, f, ensure_ascii=False, default=str)
            os.replace(tmp, STATE_FILE)
        except Exception: pass

def clear_state():
    save_state({"phase": 0, "log": []})

def add_log(msg):
    now = datetime.now(TZ_JST)
    entry = f"[{now.strftime('%H:%M:%S')}] {msg}"
    LOG_BUFFER.append(entry)
    # Hold the lock across the whole read-modify-write so concurrent add_log
    # calls can't clobber each other's appended lines.
    with _STATE_LOCK:
        state = load_state()
        logs = state.get("log", [])
        logs.append(entry)
        state["log"] = logs[-50:]
        save_state(state)

def push_notify(title, msg, priority="default"):
    if not SCHEDULED_RUN: return
    try:
        requests.post(f"https://ntfy.sh/{NTFY_CHANNEL}", data=msg.encode("utf-8"),
            headers={"Title": title, "Priority": priority,
                     "Tags": "chart_with_upwards_trend" if "📈" in title else "warning"}, timeout=10)
    except Exception as e:
        add_log(f"[WARN] ntfy failed: {e}")

# ━━━ Finnhub API Functions ━━━
def finnhub_get(endpoint, params=None):
    finnhub_rate_limit()
    params = params or {}
    params["token"] = FINNHUB_API_KEY
    try:
        r = requests.get(f"https://finnhub.io/api/v1/{endpoint}", params=params, timeout=10)
        if r.status_code == 200: return r.json()
    except Exception: pass
    return None

def get_us_symbols():
    global SYMBOL_CACHE, SYMBOL_CACHE_TIME
    now = time.time()
    if SYMBOL_CACHE and now - SYMBOL_CACHE_TIME < 86400: return SYMBOL_CACHE
    data = finnhub_get("stock/symbol", {"exchange": "US"})
    if data:
        symbols = [s for s in data if s.get("type") in ("Common Stock", "EQS")
                   and s.get("symbol") and "." not in s["symbol"] and len(s["symbol"]) <= 5]
        SYMBOL_CACHE = symbols
        SYMBOL_CACHE_TIME = now
        return symbols
    return []

def get_quote(symbol):
    data = finnhub_get("quote", {"symbol": symbol})
    if data and data.get("c"):
        return {"current": data["c"], "open": data["o"], "high": data["h"], "low": data["l"],
                "prev_close": data["pc"],
                "change_pct": round((data["c"] - data["pc"]) / data["pc"] * 100, 2) if data["pc"] else 0,
                "volume": data.get("t", 0)}
    return None

def get_quotes_batch(symbols):
    results = {}
    for sym in symbols:
        q = get_quote(sym)
        if q: results[sym] = q
    return results

WATCHLIST = [
    "AAPL","MSFT","GOOGL","AMZN","NVDA","META","TSLA","AMD","AVGO","CRM",
    "NFLX","ADBE","INTC","QCOM","MU","MRVL","SMCI","ARM","PLTR","SNOW",
    "COIN","MSTR","SOFI","RIVN","LCID","NIO","BABA","JD","PDD","LI",
    "ORCL","IBM","PANW","CRWD","NET","DDOG","ZS","FTNT",
    "LLY","UNH","JNJ","PFE","MRNA","ABBV",
    "JPM","GS","MS","BAC","WFC","C",
    "BA","RTX","LMT","NOC","GD",
    "XOM","CVX","COP","OXY","SLB",
    "CAT","DE","HON","GE",
    "DIS","CMCSA","V","MA","PYPL","SQ",
    "HD","LOW","TGT","WMT","COST",
    "UBER","LYFT","ABNB","DASH","SHOP",
    "DELL","HPE","ANET","TSM","ASML","LRCX","KLAC","AMAT",
]

def get_premarket_movers():
    global DRY_RUN_MODE
    market_open, session = is_market_open()

    if not market_open:
        # ━━━ DRY RUN MODE: Market closed → use Last Close data ━━━
        DRY_RUN_MODE = True
        add_log("🔍 [DRY RUN] Market closed — scanning with Last Close data...")
        movers = []
        for sym in WATCHLIST:
            q = get_quote(sym)
            if q and q.get("prev_close", 0) > 0:
                # Use last close as current price; change_pct may be 0 or stale
                chg = q.get("change_pct", 0)
                movers.append({
                    "symbol": sym, "name": sym,
                    "current": q.get("current", q["prev_close"]),
                    "change_pct": chg if chg != 0 else round((q.get("current",0) - q["prev_close"]) / q["prev_close"] * 100, 2),
                    "prev_close": q["prev_close"],
                })
        # Sort by absolute daily change (even if small / 0)
        movers.sort(key=lambda x: abs(x["change_pct"]), reverse=True)
        add_log(f"  [DRY RUN] Loaded {len(movers)} stocks (Last Close basis, no min threshold)")
        return movers[:50]
    else:
        # ━━━ LIVE MODE: Market open → filter by movement ━━━
        DRY_RUN_MODE = False
        add_log(f"🔍 Scanning movers ({session})...")
        movers = []
        for sym in WATCHLIST:
            q = get_quote(sym)
            if q and q["prev_close"] > 0:
                chg = q["change_pct"]
                if abs(chg) >= 1.0:
                    movers.append({"symbol": sym, "name": sym, "current": q["current"],
                                   "change_pct": chg, "prev_close": q["prev_close"]})
        movers.sort(key=lambda x: abs(x["change_pct"]), reverse=True)
        add_log(f"  Found {len(movers)} movers (>1% change)")
        return movers[:50]

def get_stock_candles(symbol, resolution="D", days=30):
    now = int(time.time())
    data = finnhub_get("stock/candle", {"symbol": symbol, "resolution": resolution,
                                         "from": now - days * 86400, "to": now})
    if data and data.get("s") == "ok":
        return [{"timestamp": data["t"][i], "open": data["o"][i], "high": data["h"][i],
                 "low": data["l"][i], "close": data["c"][i], "volume": data["v"][i]}
                for i in range(len(data.get("c", [])))]
    return []

def get_upgrade_downgrade(symbol):
    data = finnhub_get("stock/upgrade-downgrade", {"symbol": symbol})
    if not data: return []
    cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    return [d for d in data if d.get("gradeDate", "") >= cutoff][:10]

def get_company_news(symbol, days=3):
    today = datetime.now().strftime("%Y-%m-%d")
    from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    data = finnhub_get("company-news", {"symbol": symbol, "from": from_date, "to": today})
    return (data or [])[:10]

def get_insider_transactions(symbol):
    data = finnhub_get("stock/insider-transactions", {"symbol": symbol})
    if data and data.get("data"): return data["data"][:10]
    return []

def get_finnhub_macro():
    result = {"vix": None, "vix_20d_avg": None, "vix_spike_pct": 0,
              "fear_level": "NORMAL", "sp500_change": None, "alerts": []}
    for vix_sym in ["^VIX", "VIX", "VIXY"]:
        try:
            finnhub_rate_limit()
            r = requests.get("https://finnhub.io/api/v1/quote",
                params={"symbol": vix_sym, "token": FINNHUB_API_KEY}, timeout=6)
            if r.status_code == 200:
                d = r.json()
                if d.get("c") and d["c"] > 0:
                    result["vix"] = round(d["c"], 2); break
        except Exception: continue
    if result["vix"]:
        try:
            finnhub_rate_limit()
            now_ts = int(time.time())
            r = requests.get("https://finnhub.io/api/v1/indicator",
                params={"symbol": "^VIX", "resolution": "D", "from": now_ts - 30*86400,
                        "to": now_ts, "indicator": "sma", "timeperiod": 20,
                        "token": FINNHUB_API_KEY}, timeout=8)
            if r.status_code == 200:
                d = r.json()
                sma_vals = [v for v in (d.get("sma") or []) if v]
                if sma_vals:
                    result["vix_20d_avg"] = round(sma_vals[-1], 2)
                    spike = (result["vix"] - result["vix_20d_avg"]) / result["vix_20d_avg"] * 100
                    result["vix_spike_pct"] = round(spike, 1)
                    if spike >= 30:
                        result["fear_level"] = "SPIKE"
                        result["alerts"].append(f"🚨 VIX SPIKE: +{spike:.1f}%")
                    elif spike >= 15:
                        result["fear_level"] = "ELEVATED"
                        result["alerts"].append(f"⚠️ VIX ELEVATED: +{spike:.1f}%")
                    elif spike <= -15:
                        result["fear_level"] = "CALM"
        except Exception: pass
    try:
        finnhub_rate_limit()
        r = requests.get("https://finnhub.io/api/v1/quote",
            params={"symbol": "SPY", "token": FINNHUB_API_KEY}, timeout=6)
        if r.status_code == 200:
            d = r.json()
            if d.get("c") and d.get("pc"):
                chg = round((d["c"] - d["pc"]) / d["pc"] * 100, 2)
                result["sp500_change"] = chg
                if chg <= -2.0:
                    result["alerts"].append(f"🚨 S&P500 Risk-off: {chg}%")
    except Exception: pass
    return result
# ━━━ moomoo OpenAPI Functions ━━━
# A failed connect (often a transient OpenD hiccup / connect timeout) used to
# latch moomoo off for the whole process lifetime. Instead, back off for a
# bounded window and retry automatically, so a single boot-time blip doesn't
# permanently disable order book / margin features.
_MOOMOO_RETRY_AFTER = 0.0   # epoch seconds; skip moomoo attempts until this time
_MOOMOO_BACKOFF_SEC = 600   # 10 min cool-down after a failure

def _moomoo_blocked():
    return time.time() < _MOOMOO_RETRY_AFTER

def _moomoo_mark_failed():
    global _MOOMOO_RETRY_AFTER
    _MOOMOO_RETRY_AFTER = time.time() + _MOOMOO_BACKOFF_SEC

def moomoo_connect_quote():
    global MOOMOO_QUOTE_CTX
    if not MOOMOO_AVAILABLE or _moomoo_blocked(): return None
    try:
        if MOOMOO_QUOTE_CTX is None:
            import socket
            # Quick connectivity test (3s timeout) before expensive OpenQuoteContext
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            sock.connect((MOOMOO_HOST, MOOMOO_PORT))
            sock.close()
            MOOMOO_QUOTE_CTX = OpenQuoteContext(host=MOOMOO_HOST, port=MOOMOO_PORT)
        return MOOMOO_QUOTE_CTX
    except Exception as e:
        add_log(f"[WARN] moomoo unavailable ({e}) — order book disabled for {_MOOMOO_BACKOFF_SEC // 60} min")
        MOOMOO_QUOTE_CTX = None
        _moomoo_mark_failed()
        return None

def moomoo_connect_trade():
    global MOOMOO_TRADE_CTX
    if not MOOMOO_AVAILABLE or _moomoo_blocked(): return None
    try:
        if MOOMOO_TRADE_CTX is None:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            sock.connect((MOOMOO_HOST, MOOMOO_PORT))
            sock.close()
            MOOMOO_TRADE_CTX = OpenSecTradeContext(filter_trdmarket=None, host=MOOMOO_HOST, port=MOOMOO_PORT, security_firm=None)
        return MOOMOO_TRADE_CTX
    except Exception as e:
        add_log(f"[WARN] moomoo unavailable ({e}) — margin features disabled for {_MOOMOO_BACKOFF_SEC // 60} min")
        MOOMOO_TRADE_CTX = None
        _moomoo_mark_failed()
        return None

def get_order_book(symbol, num=10):
    ctx = moomoo_connect_quote()
    if not ctx: return None
    try:
        ret, data = ctx.get_order_book(f"US.{symbol}", num=num)
        if ret == RET_OK:
            bids = [(row["Bid"], row["BidVol"]) for _, row in data.iterrows() if row.get("Bid")]
            asks = [(row["Ask"], row["AskVol"]) for _, row in data.iterrows() if row.get("Ask")]
            return {"bids": bids, "asks": asks}
    except Exception as e:
        add_log(f"[WARN] Order book failed {symbol}: {e}")
    return None

def calc_absorption_ratio(snapshots):
    if not snapshots or len(snapshots) < 2: return 1.0
    total_bid_r, total_ask_c = 0, 0
    for i in range(1, len(snapshots)):
        prev, curr = snapshots[i-1], snapshots[i]
        pb = sum(b[1] for b in prev.get("bids", []))
        cb = sum(b[1] for b in curr.get("bids", []))
        if cb > pb: total_bid_r += (cb - pb)
        pa = sum(a[1] for a in prev.get("asks", []))
        ca = sum(a[1] for a in curr.get("asks", []))
        if ca < pa: total_ask_c += (pa - ca)
    return round(total_bid_r / total_ask_c, 3) if total_ask_c else 1.0

def calc_downside_efficiency(ob):
    if not ob: return 0.0
    bids = ob.get("bids", [])
    if len(bids) < 2: return 0.0
    prices = [b[0] for b in bids if b[0] > 0]
    if len(prices) < 2: return 0.0
    gaps, total = 0, len(prices) - 1
    avg_spread = (prices[0] - prices[-1]) / total if total > 0 else 0
    for i in range(1, len(prices)):
        if prices[i-1] - prices[i] > avg_spread * 2: gaps += 1
    return round(gaps / max(total, 1), 3)

def calc_whale_threshold_ewma(order_sizes, span=20):
    if not order_sizes or len(order_sizes) < 5: return 1000
    alpha = 2 / (span + 1)
    ewma = order_sizes[0]
    for size in order_sizes[1:]: ewma = alpha * size + (1 - alpha) * ewma
    sorted_s = sorted(order_sizes)
    p95 = sorted_s[min(int(len(sorted_s) * 0.95), len(sorted_s)-1)]
    return int(max(p95, ewma * 2))

def analyze_order_book(symbol):
    ob = get_order_book(symbol)
    if not ob:
        return {"available": False, "absorption_ratio": 1.0, "downside_efficiency": 0.0,
                "whale_threshold": 1000, "bids": [], "asks": [], "whale_detected": False}
    de = calc_downside_efficiency(ob)
    all_sizes = [b[1] for b in ob.get("bids", [])] + [a[1] for a in ob.get("asks", [])]
    whale_th = calc_whale_threshold_ewma(all_sizes)
    whale_bids = [b for b in ob.get("bids", []) if b[1] >= whale_th]
    return {"available": True, "absorption_ratio": 1.0, "downside_efficiency": de,
            "whale_threshold": whale_th, "bids": ob["bids"][:5], "asks": ob["asks"][:5],
            "whale_detected": len(whale_bids) > len([a for a in ob.get("asks", []) if a[1] >= whale_th]),
            "whale_bid_vol": sum(b[1] for b in whale_bids)}

def get_account_info():
    ctx = moomoo_connect_trade()
    if not ctx: return None
    try:
        ret, data = ctx.accinfo_query()
        if ret == RET_OK and not data.empty:
            row = data.iloc[0]
            return {"total_assets": row.get("total_assets", 0), "cash": row.get("cash", 0),
                    "market_val": row.get("market_val", 0)}
    except Exception as e:
        add_log(f"[WARN] Account info failed: {e}")
    return None

def get_positions():
    ctx = moomoo_connect_trade()
    if not ctx: return []
    try:
        ret, data = ctx.position_list_query()
        if ret == RET_OK and not data.empty:
            return [{"symbol": row.get("code", "").replace("US.", ""),
                     "qty": row.get("qty", 0), "cost_price": row.get("cost_price", 0),
                     "market_val": row.get("market_val", 0)}
                    for _, row in data.iterrows()]
    except Exception as e:
        add_log(f"[WARN] Position query failed: {e}")
    return []

def _calc_margin_deadzone(account_info, positions, current_prices):
    if not account_info or not positions: return None
    total_assets = account_info.get("total_assets", 0)
    market_val = account_info.get("market_val", 0)
    cash = account_info.get("cash", 0)
    if market_val <= 0: return None
    borrowed = max(0, market_val - cash)
    if borrowed <= 0:
        return {"margin_pct": 100.0, "allowed_drop_pct": 100.0, "deadlines": {}, "alert_level": "SAFE"}
    equity = total_assets - borrowed
    margin_pct = (equity / market_val) * 100 if market_val > 0 else 100
    allowed_drop_pct = max(0, round(((equity - 0.20 * market_val) / (market_val * 0.80)) * 100, 2))
    deadlines = {}
    for pos in positions:
        sym = pos["symbol"]
        price = current_prices.get(sym, {}).get("current", pos.get("cost_price", 0))
        if price > 0 and allowed_drop_pct < 100:
            deadlines[sym] = {"current_price": price,
                              "deadline_price": round(price * (1 - allowed_drop_pct / 100), 2),
                              "drop_pct": allowed_drop_pct, "qty": pos.get("qty", 0)}
    alert_level = "URGENT" if margin_pct <= 25 else "HIGH" if margin_pct <= 30 else "WARNING" if margin_pct <= 40 else "SAFE"
    return {"margin_pct": round(margin_pct, 2), "allowed_drop_pct": allowed_drop_pct,
            "deadlines": deadlines, "alert_level": alert_level}

# ━━━ News & OSINT ━━━
def get_news():
    articles = []
    if NEWS_API_KEY:
        try:
            r = requests.get("https://newsapi.org/v2/everything",
                params={"q": "stock market OR Wall Street OR Federal Reserve OR earnings",
                        "language": "en", "sortBy": "publishedAt", "pageSize": 20,
                        "apiKey": NEWS_API_KEY}, timeout=10)
            if r.status_code == 200:
                for a in r.json().get("articles", []):
                    articles.append({"title": a.get("title", ""), "source": a.get("source", {}).get("name", "")})
        except Exception: pass
    for feed_url in ["https://rsshub.app/telegram/channel/warmonitor3",
                     "https://rsshub.app/telegram/channel/intelslava"]:
        try:
            r = requests.get(feed_url, timeout=8)
            if r.status_code == 200:
                titles = re.findall(r"<title>(.*?)</title>", r.text)
                for t in titles[1:6]:
                    articles.append({"title": t, "source": "OSINT"})
        except Exception: pass
    return articles

LEAK_KEYWORDS = ["sources say","according to sources","is considering","emergency rate",
    "circuit breaker","breaking:","unexpected","fed pivot","rate cut","tariff","sanctions"]

def detect_leaks(articles):
    leaks = []
    for a in articles:
        tl = a.get("title", "").lower()
        if any(kw in tl for kw in LEAK_KEYWORDS):
            leaks.append(a)
    return leaks

def sentinel_check(news, extra=""):
    if not news: return {"action": "HOLD", "risk": 0, "reason": ""}
    crisis = ["nuclear","invasion","war declared","financial crisis","bank collapse",
              "emergency fed","market crash","circuit breaker triggered","debt default"]
    risk, reasons = 0, []
    for a in news:
        tl = a.get("title", "").lower()
        for kw in crisis:
            if kw in tl: risk += 2; reasons.append(a["title"][:60])
    if risk >= 4:
        return {"action": "SELL_ALL", "risk": min(risk, 5), "reason": " | ".join(reasons[:3])}
    return {"action": "HOLD", "risk": min(risk, 5), "reason": " | ".join(reasons[:3]) if reasons else ""}

def process_whale_ratings(upgrades, quote):
    if not upgrades: return 0, ""
    score_adj, signals = 0, []
    for u in upgrades:
        company = u.get("company", "")
        is_whale = any(f.lower() in company.lower() for f in WHALE_FIRMS)
        if not is_whale: continue
        action = u.get("action", "").lower()
        to_grade = u.get("toGrade", "").lower()
        is_upgrade = action in ("upgrade", "init") and to_grade in ("buy", "overweight", "outperform")
        is_downgrade = action in ("downgrade",) and to_grade in ("sell", "underweight", "underperform")
        if is_upgrade:
            if quote and abs(quote.get("change_pct", 0)) < 0.5:
                score_adj -= 10
                signals.append(f"⚠️ {company}: Buy but low momentum (Distribution?)")
            else:
                score_adj += 10
                signals.append(f"✅ {company}: Upgrade to {to_grade}")
        elif is_downgrade:
            score_adj -= 15
            signals.append(f"🚨 {company}: Downgrade to {to_grade}")
    return score_adj, " | ".join(signals)
# ━━━ Material Grade & Gemini Scoring ━━━
def classify_catalyst_grade(reason_text):
    text_lower = (reason_text or "").lower()
    for grade, keywords in GRADE_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in text_lower: return grade
    return "C"

def gemini_score_stocks(stocks, context=""):
    if not google_genai or not GEMINI_API_KEY:
        add_log("[WARN] Gemini not available")
        return {}
    try: client = google_genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        add_log(f"[WARN] Gemini init failed: {e}"); return {}
    results = {}
    for s in stocks:
        symbol = s.get("symbol", "")
        prompt = f"""Evaluate US stock {symbol} ({s.get('name',symbol)}) using real-time web search.
AI Buy Reason: {s.get('reason','')}
{context}
Verify: 1) Is reason accurate NOW? 2) Negative news/SEC issues? 3) Market sentiment? 4) Upcoming events?
Return ONLY JSON: {{"score": 0-100, "red_flag": true/false, "reason": "1-2 sentences"}}
Score: 80+=Strong, 60-79=Moderate, 40-59=Weak, <40=Red flag"""
        try:
            response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt,
                config=genai_types.GenerateContentConfig(
                    tools=[genai_types.Tool(google_search=genai_types.GoogleSearch())], temperature=0.3))
            data = safe_json(response.text or "{}")
            results[symbol] = {"score": data.get("score", 50), "red_flag": data.get("red_flag", False),
                               "reason": data.get("reason", "")}
            add_log(f"  🔮 Gemini: {symbol} → {data.get('score','?')}/100" +
                    (" 🚩RED" if data.get("red_flag") else ""))
        except Exception as e:
            add_log(f"  [WARN] Gemini {symbol}: {e}")
            results[symbol] = {"score": 50, "red_flag": False, "reason": "unavailable"}
    return results

# ━━━ Exit State Machine ━━━
def calc_hold_score(ctx):
    score = 50
    grade = ctx.get("catalyst_grade", "C")
    if grade == "A": score += 25
    elif grade == "B": score += 15
    elif grade == "D": score -= 20
    if ctx.get("vwap_reclaimed"): score += 15
    if ctx.get("recovered_to_positive"): score += 20
    fear = ctx.get("vix_fear_level", "NORMAL")
    if fear == "SPIKE": score -= 30
    elif fear == "ELEVATED": score -= 15
    if ctx.get("whale_detected"): score += 10
    ar = ctx.get("absorption_ratio", 1.0)
    if ar > 1.2: score += 10
    elif ar < 0.5: score -= 10
    return max(0, min(100, score))

def calc_exit_score(ctx):
    score = 0
    if ctx.get("thesis_broken"): return 100
    score += ctx.get("vwap_failed_count", 0) * 15
    fear = ctx.get("vix_fear_level", "NORMAL")
    if fear == "SPIKE": score += 35
    elif fear == "ELEVATED": score += 15
    grade = ctx.get("catalyst_grade", "C")
    pnl = ctx.get("pnl_pct", 0)
    if grade in ("C", "D") and pnl <= -3: score += 20
    if ctx.get("volume_increasing_on_drop"): score += 20
    if ctx.get("downside_efficiency", 0) > 0.3: score += 15
    if ctx.get("absorption_ratio", 1.0) < 0.5: score += 10
    return min(100, score)

def determine_exit_state(ctx):
    hold_sc = calc_hold_score(ctx)
    exit_sc = calc_exit_score(ctx)
    pnl = ctx.get("pnl_pct", 0)
    grade = ctx.get("catalyst_grade", "C")
    elapsed = ctx.get("elapsed_min", 0)
    if ctx.get("thesis_broken") or exit_sc >= 80:
        return EXIT_STATE_THESIS_BROKEN, hold_sc, exit_sc, "EXIT_ALL"
    if pnl >= 10 and ctx.get("momentum_decaying"):
        return EXIT_STATE_PARABOLIC, hold_sc, exit_sc, "TAKE_PROFIT"
    if pnl >= 12:
        return EXIT_STATE_PARABOLIC, hold_sc, exit_sc, "TAKE_PROFIT"
    if exit_sc >= 50 and pnl < 0:
        return EXIT_STATE_DISTRIBUTION, hold_sc, exit_sc, "EXIT_ALL"
    if exit_sc >= 40:
        return EXIT_STATE_DISTRIBUTION, hold_sc, exit_sc, "WARN"
    if pnl >= 2 and hold_sc >= 60:
        return EXIT_STATE_HEALTHY_UPTREND, hold_sc, exit_sc, "HOLD"
    if pnl < -2 and hold_sc >= 50:
        return EXIT_STATE_SHAKEOUT, hold_sc, exit_sc, "HOLD"
    if elapsed >= 30:
        if grade == "D": return EXIT_STATE_THESIS_BROKEN, hold_sc, exit_sc, "EXIT_ALL"
        if grade == "C" and pnl < 1: return EXIT_STATE_DISTRIBUTION, hold_sc, exit_sc, "EXIT_ALL"
    if elapsed < 5: return EXIT_STATE_OPEN_DISCOVERY, hold_sc, exit_sc, "HOLD"
    if pnl >= 0: return EXIT_STATE_HEALTHY_UPTREND, hold_sc, exit_sc, "HOLD"
    return EXIT_STATE_SHAKEOUT, hold_sc, exit_sc, "HOLD"

def evaluate_vwap_reclaim(symbol, open_price, current_price, history):
    if not history: return current_price >= open_price, open_price
    total_pv, total_v = 0, 0
    for h in history:
        p, v = h.get("price", 0), h.get("volume", 1)
        total_pv += p * v; total_v += v
    vwap = total_pv / total_v if total_v > 0 else open_price
    return current_price >= vwap, round(vwap, 2)

def get_realtime_prices(symbols):
    prices = {}
    ctx = moomoo_connect_quote()
    if ctx:
        try:
            moomoo_syms = [f"US.{s}" for s in symbols]
            ret, data = ctx.get_market_snapshot(moomoo_syms)
            if ret == RET_OK:
                for _, row in data.iterrows():
                    sym = row.get("code", "").replace("US.", "")
                    if sym:
                        prices[sym] = {"current": row.get("last_price", 0), "open": row.get("open_price", 0),
                                       "high": row.get("high_price", 0), "low": row.get("low_price", 0),
                                       "volume": row.get("volume", 0),
                                       "change_pct": round(row.get("price_change_rate", 0) or 0, 2)}
                        now_str = datetime.now(TZ_ET).strftime("%H:%M")
                        if sym not in PRICE_HISTORY: PRICE_HISTORY[sym] = []
                        PRICE_HISTORY[sym].append({"time": now_str, "price": row.get("last_price", 0),
                                                    "volume": row.get("volume", 0)})
                        if len(PRICE_HISTORY[sym]) > 200: PRICE_HISTORY[sym] = PRICE_HISTORY[sym][-200:]
                return prices
        except Exception as e:
            add_log(f"[WARN] moomoo snapshot failed: {e}")
    for sym in symbols:
        q = get_quote(sym)
        if q: prices[sym] = q
    return prices
# ━━━ Phase 1: Broad Scan ━━━
def phase1_broad_scan():
    add_log("📡 Ph.1: Broad Scan starting...")
    state = load_state(); state["phase"] = 0; save_state(state)
    movers = get_premarket_movers()
    if not movers:
        add_log("[ERROR] No movers found"); state["phase"] = 1; state["top20"] = []; save_state(state); return
    finnhub = get_finnhub_macro(); state["finnhub_macro"] = finnhub
    for alert in finnhub.get("alerts", []): add_log(f"  {alert}")
    news = get_news(); sentinel = sentinel_check(news)
    state["sentinel"] = sentinel; state["news"] = [{"title": n.get("title","")} for n in news[:15]]
    if sentinel.get("action") == "SELL_ALL" and not DRY_RUN_MODE:
        add_log("🚨 SENTINEL: SELL_ALL"); push_notify("🚨 SELL ALL", sentinel.get("reason",""), priority="urgent")
        state["phase"] = 1; save_state(state); return
    leaks = detect_leaks(news)
    if leaks: add_log(f"  🔍 {len(leaks)} leak signals")
    movers_text = "\n".join([f"{m['symbol']}: {m.get('change_pct',0):+.2f}% (${m.get('current',0):.2f})" for m in movers[:50]])
    news_text = "\n".join([f"- {n.get('title','')}" for n in news[:10]])
    leak_text = "\n".join([f"⚡ {l.get('title','')}" for l in leaks[:5]])
    macro_text = f"VIX: {finnhub.get('vix','N/A')} ({finnhub.get('fear_level','N/A')}, {finnhub.get('vix_spike_pct',0):+.1f}%)\nS&P500: {finnhub.get('sp500_change','N/A')}%"
    # Dry Run context injection
    dry_run_ctx = ""
    if DRY_RUN_MODE:
        dry_run_ctx = ("\n\n⚠️ IMPORTANT CONTEXT: The US market is currently CLOSED. "
                       "This is a DRY RUN / SIMULATION analysis based on the most recent closing data. "
                       "Analyze using last confirmed close prices and recent news. "
                       "Identify stocks with the strongest setup for the NEXT trading session. "
                       "All change_pct values reflect the last trading day's movement.")
    prompt = f"""You are a US stock AI predator. Find stocks that will SURGE {'at the next market open' if DRY_RUN_MODE else 'today'}.
PHILOSOPHY: All or Nothing. Whale tracking. Risk visualization.{dry_run_ctx}
{'LAST CLOSE DATA' if DRY_RUN_MODE else 'PRE-MARKET MOVERS'}:\n{movers_text}\nMACRO:\n{macro_text}\nNEWS:\n{news_text or 'None'}\nLEAKS:\n{leak_text or 'None'}
Select TOP 20 most likely to surge {'at next open' if DRY_RUN_MODE else 'after 09:30 ET open'}.
IMPORTANT: "reason" and "sell_trigger" fields MUST be written in JAPANESE (日本語で記述せよ).
Return ONLY JSON array: [{{"symbol":"TICKER","name":"Company Name","change_pct":X.XX,"reason":"日本語で買い根拠を1行で","confidence":1-5,"theme":"sector","sell_trigger":"日本語で損切り条件"}}]"""
    add_log(f"🤖 Claude analyzing{' (DRY RUN)' if DRY_RUN_MODE else ''}...")
    try:
        res = claude.messages.create(model="claude-opus-4-6", max_tokens=3000, messages=[{"role":"user","content":prompt}])
        top20 = safe_json(res.content[0].text if res.content else "[]")
        if isinstance(top20, dict): top20 = top20.get("stocks", top20.get("top20", []))
        if not isinstance(top20, list): top20 = []
        top20 = top20[:20]
    except Exception as e:
        add_log(f"[ERROR] Claude Ph.1: {e}"); top20 = []
    mode_label = "🔬 DRY RUN" if DRY_RUN_MODE else "Pre-market"
    add_log(f"✅ Ph.1 complete: {len(top20)} candidates ({mode_label})")
    for i, s in enumerate(top20[:5]): add_log(f"  #{i+1} {s.get('symbol','')} {s.get('change_pct',0):+.2f}%")
    state["phase"] = 1; state["top20"] = top20
    state["dry_run"] = DRY_RUN_MODE
    state["market_condition"] = f"{'🔬 DRY RUN (Closed Market)' if DRY_RUN_MODE else mode_label}: {len(movers)} stocks"
    state["macro_summary"] = macro_text; save_state(state)
    push_notify(f"📡 Ph.1 Complete{' [DRY RUN]' if DRY_RUN_MODE else ''}", f"TOP20 from {len(movers)}\nVIX: {finnhub.get('vix','?')}")

# ━━━ Phase 2: Re-Scoring ━━━
def phase2_rescore():
    add_log("🔬 Ph.2: Re-scoring...")
    state = load_state(); top20 = state.get("top20", [])
    if not top20: add_log("[WARN] No TOP20"); state["phase"] = 2; save_state(state); return
    symbols = [s.get("symbol","") for s in top20 if s.get("symbol")]
    fresh = get_quotes_batch(symbols[:20])
    vol_data = {}
    for sym in symbols[:10]:
        candles = get_stock_candles(sym, days=30)
        if candles and len(candles) >= 5:
            closes = [c["close"] for c in candles]
            rets = [(closes[i]-closes[i-1])/closes[i-1] for i in range(1,len(closes))]
            vol_data[sym] = round(statistics.stdev(rets) * (252**0.5) * 100, 1) if len(rets) >= 2 else 0
    refresh_text = "\n".join([f"{sym}: ${q.get('current',0):.2f} ({q.get('change_pct',0):+.2f}%) Vol:{vol_data.get(sym,'N/A')}%" for sym, q in fresh.items()])
    top20_text = "\n".join([f"{s.get('symbol','')}: {s.get('reason','')} (Conf:{s.get('confidence',0)}/5)" for s in top20])
    dry_ctx = ("\n⚠️ DRY RUN: Market is CLOSED. Use last close data for simulation analysis. "
               "Evaluate based on confirmed closing prices and technical setup for next session." if DRY_RUN_MODE else "")
    prompt = f"""Re-score TOP20→TOP10 for US stocks.{dry_ctx}\nTOP20:\n{top20_text}\nUPDATED QUOTES:\n{refresh_text}\nConsider: {'technical setup and catalyst strength for next open' if DRY_RUN_MODE else 'momentum change, volatility, priced-in moves'}.\nIMPORTANT: "reason" and "sell_trigger" MUST be in JAPANESE (日本語).
Return ONLY JSON array of TOP 10: [{{"symbol":"TICKER","name":"Name","score":0-100,"change_pct":X.XX,"reason":"日本語で根拠","confidence":1-5,"theme":"theme","sell_trigger":"日本語で損切り条件","volatility":"high/med/low"}}]"""
    add_log(f"🤖 Claude re-scoring{' (DRY RUN)' if DRY_RUN_MODE else ''}...")
    try:
        res = claude.messages.create(model="claude-opus-4-6", max_tokens=2000, messages=[{"role":"user","content":prompt}])
        top10 = safe_json(res.content[0].text if res.content else "[]")
        if isinstance(top10, dict): top10 = top10.get("stocks", top10.get("top10", []))
        if not isinstance(top10, list): top10 = []
        top10 = top10[:10]
    except Exception as e:
        add_log(f"[ERROR] Claude Ph.2: {e}"); top10 = top20[:10]
    add_log(f"✅ Ph.2 complete: {len(top10)} candidates")
    state["phase"] = 2; state["top10"] = top10; save_state(state)
    push_notify("🔬 Ph.2 Complete", f"TOP10 from {len(top20)}")

# ━━━ Phase 3: Cross-Check ━━━
def phase3_crosscheck():
    add_log("⚡ Ph.3: Cross-check...")
    state = load_state(); top10 = state.get("top10", [])
    if not top10: add_log("[WARN] No TOP10"); state["phase"] = 3; save_state(state); return
    whale_signals = {}
    for s in top10[:10]:
        sym = s.get("symbol", "")
        if not sym: continue
        upgrades = get_upgrade_downgrade(sym); quote = get_quote(sym)
        adj, sig = process_whale_ratings(upgrades, quote)
        if sig: whale_signals[sym] = {"score_adj": adj, "signal": sig}; add_log(f"  🐳 {sym}: {sig}")
    company_news = {}
    for s in top10[:5]:
        sym = s.get("symbol", "")
        if sym:
            cn = get_company_news(sym)
            if cn: company_news[sym] = [n.get("headline", n.get("summary", ""))[:80] for n in cn[:3]]
    add_log("🔮 Gemini grounding...")
    gemini_scores = gemini_score_stocks(top10[:10], context=f"VIX: {state.get('finnhub_macro',{}).get('fear_level','NORMAL')}")
    state["gemini_scores"] = gemini_scores
    whale_text = "\n".join([f"{s}: {w['signal']} ({w['score_adj']:+d})" for s, w in whale_signals.items()]) or "None"
    gemini_text = "\n".join([f"{s}: {g.get('score',0)}/100 {'🚩RED' if g.get('red_flag') else ''} - {g.get('reason','')}" for s, g in gemini_scores.items()]) or "N/A"
    top10_text = "\n".join([f"{s.get('symbol','')}: Score:{s.get('score',0)} - {s.get('reason','')}" for s in top10])
    dry_ctx3 = ("\n⚠️ DRY RUN: Market is CLOSED. This is a simulation using confirmed close data. "
                "Evaluate catalyst quality and institutional signals for the next trading session." if DRY_RUN_MODE else "")
    prompt = f"""Cross-check TOP10→TOP5.{dry_ctx3}\nCRITICAL: "Buy without volume"=TRAP(penalize). "Price target raise+vol>300%"=REAL(boost).\nTOP10:\n{top10_text}\nWHALE RATINGS:\n{whale_text}\nGEMINI:\n{gemini_text}\nRules: red_flag→EXCLUDE, score<40→EXCLUDE, 40-59→warn, Combined=Claude70%+Gemini30%\nIMPORTANT: "reason" and "sell_trigger" MUST be in JAPANESE (日本語).
Return ONLY JSON array TOP5: [{{"symbol":"TICKER","name":"Name","score":0-100,"combined_score":0-100,"reason":"日本語で買い根拠","confidence":1-5,"theme":"theme","sell_trigger":"日本語で損切り条件","grade":"A/B/C/D","whale_signal":"","gemini_score":0-100}}]"""
    add_log(f"🤖 Claude cross-checking{' (DRY RUN)' if DRY_RUN_MODE else ''}...")
    try:
        res = claude.messages.create(model="claude-opus-4-6", max_tokens=2000, messages=[{"role":"user","content":prompt}])
        top5 = safe_json(res.content[0].text if res.content else "[]")
        if isinstance(top5, dict): top5 = top5.get("stocks", top5.get("top5", []))
        if not isinstance(top5, list): top5 = []
        top5 = top5[:5]
    except Exception as e:
        add_log(f"[ERROR] Claude Ph.3: {e}"); top5 = top10[:5]
    filtered = []
    for s in top5:
        sym = s.get("symbol", ""); gs = gemini_scores.get(sym, {})
        if gs.get("red_flag"): add_log(f"  🚩 {sym} KILLED (red flag)"); continue
        if gs.get("score", 50) < 40: add_log(f"  ❌ {sym} KILLED (score {gs.get('score',0)})"); continue
        filtered.append(s)
    top5 = filtered[:5]
    add_log(f"✅ Ph.3 complete: {len(top5)} after Gemini filter")
    state["phase"] = 3; state["top5"] = top5; state["whale_signals"] = whale_signals; save_state(state)
    push_notify("⚡ Ph.3 Complete", "\n".join([f"{s.get('symbol','')} ({s.get('combined_score','?')})" for s in top5]))

# ━━━ Phase 4: Final TOP3 ━━━
def phase4_final_top3():
    add_log("🏆 Ph.4: Final TOP3...")
    state = load_state(); top5 = state.get("top5", [])
    if not top5: add_log("[WARN] No TOP5"); state["phase"] = 4; save_state(state); return
    ob_results = {}
    for s in top5:
        sym = s.get("symbol", "")
        if sym:
            add_log(f"  📊 Order book: {sym}")
            ob = analyze_order_book(sym); ob_results[sym] = ob
            if ob.get("available"):
                add_log(f"    AR:{ob.get('absorption_ratio','-')} Vacuum:{ob.get('downside_efficiency','-')} {'🐳WHALE' if ob.get('whale_detected') else ''}")
    margin_info = None
    account = get_account_info(); positions = get_positions()
    if account and positions:
        syms = [s.get("symbol","") for s in top5]; cp = get_quotes_batch(syms)
        margin_info = _calc_margin_deadzone(account, positions, cp)
        if margin_info: add_log(f"  💰 Margin:{margin_info['margin_pct']:.1f}% Drop:{margin_info['allowed_drop_pct']:.1f}% {margin_info['alert_level']}")
    scored = []
    for s in top5:
        sym = s.get("symbol", ""); ob = ob_results.get(sym, {})
        combined = s.get("combined_score", s.get("score", 50))
        if ob.get("available"):
            if ob.get("whale_detected"): combined += 10
            if ob.get("downside_efficiency", 0) > 0.3: combined -= 15
        s["final_score"] = min(100, max(0, combined)); s["order_book"] = ob
        if margin_info and margin_info.get("deadlines", {}).get(sym):
            dl = margin_info["deadlines"][sym]; s["margin_deadline"] = dl["deadline_price"]; s["margin_drop_pct"] = dl["drop_pct"]
        scored.append(s)
    scored.sort(key=lambda x: x.get("final_score", 0), reverse=True)
    top3 = scored[:3]
    if not top3:
        add_log("⏭️ All killed. Skip today.")
        push_notify("⏭️ Skip", "No candidates passed.", priority="default")
        state["phase"] = 4; state["top3_final"] = []; save_state(state); return
    medal = ["🥇","🥈","🥉"]
    for i, s in enumerate(top3):
        sym = s.get("symbol",""); grade = s.get("grade", classify_catalyst_grade(s.get("reason",""))); s["grade"] = grade
        margin_str = f"\n⚠️ Margin 20%: -${s.get('margin_drop_pct',0):.1f}% (${s.get('margin_deadline','')})" if s.get("margin_deadline") else ""
        msg = f"{medal[i]} {sym}\nScore:{s.get('final_score',0)} Grade:{grade}\n{s.get('reason','')}\nStop: {s.get('sell_trigger','')}{margin_str}"
        add_log(f"  {medal[i]} {sym} Score:{s.get('final_score',0)} Grade:{grade}")
        push_notify(f"{medal[i]} TOP3 #{i+1}: {sym}", msg, priority="high" if i==0 else "default")
    if margin_info and margin_info.get("alert_level") in ("URGENT","HIGH"):
        push_notify("⚠️ MARGIN ALERT", f"Margin:{margin_info['margin_pct']:.1f}% Drop:{margin_info['allowed_drop_pct']:.1f}%",
            priority="urgent" if margin_info["alert_level"]=="URGENT" else "high")
    state["phase"] = 4; state["top3_final"] = top3; state["dry_run"] = DRY_RUN_MODE
    state["order_book"] = {s.get("symbol",""): ob_results.get(s.get("symbol",""),{}) for s in top3}
    if margin_info: state["margin_alert"] = f"Margin:{margin_info['margin_pct']:.1f}% Drop:{margin_info['allowed_drop_pct']:.1f}% {margin_info['alert_level']}"
    if DRY_RUN_MODE: state["market_condition"] = "🔬 DRY RUN (Closed Market) — Simulation complete"
    # A.R.G.U.S. ledger — best-effort log of each pick so calibration
    # endpoints accumulate real history. Never break the scan flow.
    if not DRY_RUN_MODE:
        try:
            for s in top3:
                argus_ledger.log_prediction(
                    code=str(s.get("symbol", "")),
                    name=s.get("name") or s.get("company_name"),
                    direction="up",
                    probability=argus_ledger.score_to_probability(s.get("final_score")),
                    horizon="1d",
                    price_at_prediction=float(s.get("price") or s.get("last_price") or 0),
                    reason_code=str(s.get("grade") or s.get("reason") or "TOP3")[:32],
                )
        except Exception as _e:
            add_log("⚠️ ledger.log_prediction failed: " + str(_e)[:120])
    save_state(state); add_log(f"✅ Ph.4 complete: TOP3 confirmed{' [DRY RUN]' if DRY_RUN_MODE else ''}")
# ━━━ Phase 5: Dynamic Exit Engine ━━━
def phase5_post_open():
    add_log("📈 Ph.5: Dynamic Exit Engine...")
    state = load_state(); top3 = state.get("top3_final", [])
    if not top3: add_log("[WARN] No TOP3"); return
    finnhub = state.get("finnhub_macro", {}); codes = [s.get("symbol","") for s in top3 if s.get("symbol")]
    contexts, ob_history = {}, {}
    for s in top3:
        sym = s.get("symbol","")
        if not sym: continue
        grade = s.get("grade", classify_catalyst_grade(s.get("reason","")))
        contexts[sym] = {"catalyst_grade": grade, "vix_fear_level": finnhub.get("fear_level","NORMAL"),
            "vix_spike_pct": finnhub.get("vix_spike_pct",0), "open_price": 0, "current_price": 0,
            "pnl_pct": 0, "drawdown_pct": 0, "vwap_reclaimed": False, "vwap_failed_count": 0,
            "volume_increasing_on_drop": False, "volume_decreasing_on_drop": False,
            "recovered_to_positive": False, "momentum_decaying": False, "thesis_broken": False,
            "elapsed_min": 0, "prev_volume": 0, "state": EXIT_STATE_OPEN_DISCOVERY,
            "whale_detected": False, "absorption_ratio": 1.0, "downside_efficiency": 0.0}
        ob_history[sym] = []
    state["post_open_result"] = {"evaluations": [], "overall": "⏳ Tracking..."}; save_state(state)
    add_log("📊 Fetching opening prices...")
    prices_open = get_realtime_prices(codes)
    # A.R.G.U.S. — resolve any pending ledger entries against today's open.
    try:
        resolved_n = argus_ledger.resolve_outcomes(
            lambda sym, _ts: (prices_open.get(sym, {}) or {}).get("current"),
        )
        if resolved_n:
            add_log(f"📒 ledger: resolved {resolved_n} pending predictions")
    except Exception as _e:
        add_log("⚠️ ledger.resolve_outcomes failed: " + str(_e)[:120])
    for s in top3:
        sym = s.get("symbol","")
        if sym in prices_open:
            p = prices_open[sym]; contexts[sym]["open_price"] = p.get("open", p.get("current",0))
            contexts[sym]["current_price"] = p.get("current",0); contexts[sym]["pnl_pct"] = p.get("change_pct",0)
            contexts[sym]["prev_volume"] = p.get("volume",0)
            add_log(f"  {'📈' if p.get('change_pct',0)>=0 else '📉'} {sym} {'+' if p.get('change_pct',0)>=0 else ''}{p.get('change_pct',0)}% Grade:{contexts[sym]['catalyst_grade']}")
    news = get_news(); sentinel_now = sentinel_check(news)
    if sentinel_now.get("action") == "SELL_ALL":
        push_notify("🚨 SELL ALL", sentinel_now.get("reason",""), priority="urgent"); add_log("🚨 SELL_ALL!"); return
    decided = {}
    for i in range(3):
        time.sleep(600); elapsed = (i+1)*10; prices_now = get_realtime_prices(codes)
        for s in top3:
            sym = s.get("symbol","")
            if sym in decided or sym not in prices_now: continue
            p = prices_now[sym]; ctx = contexts[sym]
            op = ctx["open_price"] if ctx["open_price"] > 0 else p.get("open",0)
            ctx["current_price"] = p.get("current",0); ctx["elapsed_min"] = elapsed
            ctx["pnl_pct"] = p.get("change_pct",0); ctx["drawdown_pct"] = p.get("change_pct",0)
            hist = PRICE_HISTORY.get(sym, [])
            vwap_ok, vwap_val = evaluate_vwap_reclaim(sym, op, p.get("current",0), hist)
            if not vwap_ok: ctx["vwap_failed_count"] += 1
            ctx["vwap_reclaimed"] = vwap_ok
            vol_now = p.get("volume",0); vol_prev = ctx["prev_volume"]
            if p.get("change_pct",0) < 0:
                ctx["volume_increasing_on_drop"] = vol_now > vol_prev * 1.1
                ctx["volume_decreasing_on_drop"] = vol_now < vol_prev * 0.9
            if p.get("change_pct",0) >= 0: ctx["recovered_to_positive"] = True
            ctx["prev_volume"] = vol_now
            ob = get_order_book(sym)
            if ob:
                ob_history[sym].append(ob); ctx["downside_efficiency"] = calc_downside_efficiency(ob)
                if len(ob_history[sym]) >= 2: ctx["absorption_ratio"] = calc_absorption_ratio(ob_history[sym])
                all_sz = [b[1] for b in ob.get("bids",[])] + [a[1] for a in ob.get("asks",[])]
                ctx["whale_detected"] = any(b[1] >= calc_whale_threshold_ewma(all_sz) for b in ob.get("bids",[]))
            new_state, hold_sc, exit_sc, action = determine_exit_state(ctx); ctx["state"] = new_state
            sign = "+" if p.get("change_pct",0) >= 0 else ""
            st_em = {"S0":"⏳","S1":"🔍","S2":"✅","S3":"⚠️","S4":"🚨","S5":"💰"}.get(new_state,"?")
            add_log(f"  {sym} {elapsed}min {sign}{p.get('change_pct',0)}% | {st_em}{new_state} H:{hold_sc} E:{exit_sc}")
            state["realtime_prices"] = prices_now
            if ob:
                if "order_book" not in state: state["order_book"] = {}
                state["order_book"][sym] = {"bids": ob.get("bids",[])[:5], "asks": ob.get("asks",[])[:5],
                    "absorption_ratio": ctx["absorption_ratio"], "downside_efficiency": ctx["downside_efficiency"],
                    "whale_threshold": calc_whale_threshold_ewma(all_sz) if ob else 0}
            save_state(state)
            if action == "EXIT_ALL":
                reason = "Thesis broken" if ctx.get("thesis_broken") else f"ExitScore:{exit_sc}"
                add_log(f"  🚨 {sym} EXIT → {reason}")
                push_notify(f"🚨 STOP: {sym}", f"{elapsed}min: {sign}{p.get('change_pct',0)}%\n{reason}", priority="urgent")
                decided[sym] = {"action": action, "reason": reason, "pnl": p.get("change_pct",0)}
            elif action == "TAKE_PROFIT":
                add_log(f"  💰 {sym} PROFIT → +{p.get('change_pct',0)}%")
                push_notify(f"💰 PROFIT: {sym}", f"{elapsed}min: +{p.get('change_pct',0)}%", priority="high")
                decided[sym] = {"action": action, "reason": "Parabolic", "pnl": p.get("change_pct",0)}
            elif action == "HOLD" and ctx.get("recovered_to_positive") and i > 0:
                push_notify(f"✅ HOLD: {sym}", f"{elapsed}min: {sign}{p.get('change_pct',0)}% Grade:{ctx['catalyst_grade']}")
    # Final Claude eval
    prices_final = get_realtime_prices(codes)
    top3_text = "\n".join([f"{s.get('symbol','')} Grade:{contexts.get(s.get('symbol',''),{}).get('catalyst_grade','?')} State:{contexts.get(s.get('symbol',''),{}).get('state','?')} "
        + (f"Price:{prices_final[s.get('symbol','')].get('change_pct',0)}%" if s.get('symbol','') in prices_final else "") for s in top3])
    try:
        prompt = f"Final 30min US stock tracking eval.\n[TOP3]\n{top3_text}\nReturn JSON:{{\"evaluations\":[{{\"code\":\"TICKER\",\"status\":\"HOLD/SELL\",\"message\":\"summary\",\"action_advice\":\"advice\"}}],\"overall\":\"assessment\"}}"
        res = claude.messages.create(model="claude-haiku-4-5-20251001", max_tokens=800, messages=[{"role":"user","content":prompt}])
        result = safe_json(res.content[0].text if res.content else "{}")
        msg = "📈 30min Complete\n" + result.get("overall","") + "\n"
        for e in result.get("evaluations",[]):
            msg += f"{'✅' if e.get('status')=='HOLD' else '⚠️'} {e.get('code','')} {e.get('message','')}\n→ {e.get('action_advice','')}\n"
        margin_str = ""
        account = get_account_info(); positions = get_positions()
        if account and positions:
            mi = _calc_margin_deadzone(account, positions, prices_final)
            if mi:
                margin_str = f"\n💰 Margin:{mi['margin_pct']:.1f}% Drop:{mi['allowed_drop_pct']:.1f}%"
                for ds, dl in mi.get("deadlines",{}).items():
                    margin_str += f"\n  ⚠️ {ds}: ${ dl['deadline_price']} (-{dl['drop_pct']:.1f}%)"
                msg += margin_str
                state["margin_alert"] = f"Margin:{mi['margin_pct']:.1f}% Drop:{mi['allowed_drop_pct']:.1f}% {mi['alert_level']}"
        state["phase"] = 5; state["post_open_result"] = result; state["realtime_prices"] = prices_final
        state["exit_contexts"] = {k: {kk: vv for kk, vv in v.items() if isinstance(vv, (str,int,float,bool))} for k, v in contexts.items()}
        save_state(state); push_notify("📈 30min Complete", msg); add_log(f"✅ Ph.5 complete: {result.get('overall','')}")
    except Exception as e:
        add_log(f"[ERROR] Ph.5 final: {e}")

# ━━━ Flask Routes ━━━
@app.route("/")
def index(): return HTML

@app.route("/api/state")
def api_state():
    global BACKGROUND_TASK_RUNNING
    state = load_state(); saved = state.get("log",[]); live = list(LOG_BUFFER)[-50:]
    seen = set(saved); merged = list(saved)
    for l in live:
        if l not in seen: merged.append(l); seen.add(l)
    state["log"] = merged[-50:]; state["server_ready"] = True; state["scanning"] = BACKGROUND_TASK_RUNNING
    state["dst_active"] = is_dst_now(); state["schedule"] = get_jst_schedule()
    return jsonify(state)

@app.route("/api/run", methods=["POST"])
def api_run():
    data = request.get_json(force=True, silent=True) or {}; phase = data.get("phase", 0)
    def run_bg():
        global BACKGROUND_TASK_RUNNING
        BACKGROUND_TASK_RUNNING = True
        try:
            if phase == 0: phase1_broad_scan(); phase2_rescore(); phase3_crosscheck(); phase4_final_top3()
            elif phase == 1: phase1_broad_scan()
            elif phase == 2: phase2_rescore()
            elif phase == 3: phase3_crosscheck()
            elif phase == 4: phase4_final_top3()
            elif phase == 5: phase5_post_open()
        finally: BACKGROUND_TASK_RUNNING = False
    threading.Thread(target=run_bg, daemon=True).start()
    return jsonify({"status": "started", "phase": phase})

@app.route("/api/reset", methods=["POST"])
def api_reset():
    clear_state(); LOG_BUFFER.clear(); PRICE_HISTORY.clear()
    return jsonify({"status": "reset"})

@app.route("/api/logs")
def api_logs(): return jsonify({"logs": list(LOG_BUFFER)[-100:]})

@app.route("/api/chart/<symbol>")
def api_chart(symbol):
    cached = CHART_CACHE.get(symbol)
    if cached and time.time() < cached["expires"]: return jsonify(cached["data"])
    candles = get_stock_candles(symbol, days=30)
    rows = [{"date": datetime.fromtimestamp(c["timestamp"], TZ_ET).strftime("%m/%d"),
             "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"],
             "volume": c.get("volume",0)} for c in candles]
    result = {"code": symbol, "daily": rows}
    if rows: CHART_CACHE[symbol] = {"data": result, "expires": time.time() + 600}
    return jsonify(result)

@app.route("/api/price_history/<symbol>")
def api_price_history(symbol): return jsonify({"code": symbol, "history": PRICE_HISTORY.get(symbol, [])})

@app.route("/api/price_now/<symbol>")
def api_price_now(symbol): return jsonify(get_realtime_prices([symbol]).get(symbol, {}))

@app.route("/api/order_book/<symbol>")
def api_order_book(symbol): return jsonify(analyze_order_book(symbol))

@app.route("/api/margin")
def api_margin():
    account = get_account_info(); positions = get_positions()
    if not account: return jsonify({"error": "moomoo not connected"})
    syms = [p["symbol"] for p in positions]; cp = get_quotes_batch(syms) if syms else {}
    return jsonify(_calc_margin_deadzone(account, positions, cp) or {"error": "No data"})

# ━━━ A.R.G.U.S. — calibration ledger API (React frontend) ━━━
@app.route("/api/argus/calibration")
def api_argus_calibration():
    """Aggregate hit-rate / Brier / reliability over the rolling window."""
    try:
        window = int(request.args.get("window", "30"))
    except (TypeError, ValueError):
        window = 30
    window = max(1, min(window, 365))
    return jsonify(argus_ledger.aggregate_stats(window_days=window))


@app.route("/api/argus/picks/today")
def api_argus_picks_today():
    """Today's top-3 picks pulled from the current scan state."""
    state = load_state() or {}
    top3 = state.get("top3_final") or []
    picks = []
    for s in top3:
        score = s.get("final_score")
        picks.append({
            "code": s.get("symbol", ""),
            "name": s.get("name") or s.get("company_name"),
            "price": s.get("price") or s.get("last_price"),
            "combinedScore": score,
            "probability": argus_ledger.score_to_probability(score),
            "direction": "up",
            "horizon": "1d",
            "reason": s.get("reason"),
            "grade": s.get("grade"),
            "tags": s.get("tags") or [],
        })
    return jsonify({
        "phase": state.get("phase", 0),
        "dryRun": bool(state.get("dry_run")),
        "asOf": state.get("updated_at") or int(time.time() * 1000),
        "picks": picks,
    })


@app.route("/api/argus/ledger/recent")
def api_argus_ledger_recent():
    """Debug — most recent N entries from the raw ledger."""
    try:
        limit = int(request.args.get("limit", "50"))
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(limit, 500))
    return jsonify({"entries": argus_ledger.list_recent(limit=limit)})


# ━━━ FRED rates snapshot ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Server-side only — never expose FRED_API_KEY to the frontend.

_FRED_API_KEY = os.environ.get("FRED_API_KEY")
_FRED_BASE    = "https://api.stlouisfed.org/fred/series/observations"
_FRED_SERIES  = {
    "DGS10":  "US 10Y Treasury yield",
    "DGS2":   "US 2Y Treasury yield",
    "DFII10": "US 10Y real yield",
    "VIXCLS": "VIX",
}
# Plausible "Tuesday before US CPI" mock state — used when FRED_API_KEY
# is absent or any per-series fetch fails. Each tuple is (latest, prev).
_FRED_MOCK = {
    "DGS10":  (4.42, 4.30),
    "DGS2":   (4.65, 4.60),
    "DFII10": (1.85, 1.82),
    "VIXCLS": (17.4, 17.0),
}

def _fred_normalize(series_id, latest, prev, latest_date, status):
    change = float(latest) - float(prev)
    return {
        "seriesId":      series_id,
        "label":         _FRED_SERIES.get(series_id, series_id),
        "latestValue":   round(float(latest), 4),
        "previousValue": round(float(prev),   4),
        "change":        round(change, 4),
        # For rates (DGS*), values are in percentage points → bps = ×100.
        # For VIX it's a vol index; the same multiplier still gives a
        # readable centi-unit move (1.0 → 100). Frontends should treat
        # VIX changeBp as informational only.
        "changeBp":      round(change * 100, 1),
        "latestDate":    latest_date,
        "status":        status,
    }

def _fred_mock_series(series_id):
    latest, prev = _FRED_MOCK[series_id]
    return _fred_normalize(
        series_id, latest, prev,
        datetime.now().strftime("%Y-%m-%d"),
        "mock",
    )

def fetch_fred_series(series_id):
    """Fetch latest two non-missing observations for a FRED series.

    Returns a normalized dict on success, the mock fallback on failure.
    Never raises — failure modes (no key / network error / missing data)
    all degrade to mock so the UI always renders.
    """
    if series_id not in _FRED_SERIES:
        return None
    if not _FRED_API_KEY:
        return _fred_mock_series(series_id)
    try:
        r = requests.get(_FRED_BASE, params={
            "series_id":  series_id,
            "api_key":    _FRED_API_KEY,
            "file_type":  "json",
            "sort_order": "desc",
            # FRED uses '.' for missing values; pull a small safety margin
            # so we always have two real observations to diff.
            "limit":      8,
        }, timeout=8)
        r.raise_for_status()
        obs = [o for o in r.json().get("observations", [])
               if o.get("value") not in (None, ".", "")]
        if len(obs) < 2:
            return _fred_mock_series(series_id)
        return _fred_normalize(
            series_id,
            obs[0]["value"], obs[1]["value"],
            obs[0]["date"],
            "live",
        )
    except Exception:
        return _fred_mock_series(series_id)

def _classify_rates_pressure(dgs10_change):
    """Per v8.4 spec — based on the absolute US 10Y change (pp)."""
    c = dgs10_change
    if c >  0.08: return "High"
    if c >= 0.03: return "Medium"
    if c < -0.03: return "Relief"
    return "Neutral"

def _classify_risk_volatility(vix_level):
    # Inclusive lower edges (matching the Medium edge in
    # _classify_rates_pressure): VIX >= 22 = High fear, >= 18 = elevated.
    if vix_level >= 22: return "High"
    if vix_level >= 18: return "Medium"
    return "Low"

# Server-side cache for the rates snapshot. FRED rates update at most daily,
# yet each call fans out to 4 FRED requests; without a cache every hit paid
# that cost and slowed the cold-start path. Only a genuinely-live snapshot is
# cached — a mock result is never pinned, so a transient FRED failure is
# retried on the next request instead of being served for the whole TTL.
_RATES_CACHE     = {"data": None, "expires": 0.0}
_RATES_CACHE_TTL = 600  # seconds (10 min)

def get_rates_snapshot():
    """Combined snapshot of the four watched series + derived signals."""
    now = time.time()
    if _RATES_CACHE["data"] is not None and now < _RATES_CACHE["expires"]:
        return _RATES_CACHE["data"]
    # Fetch the four series concurrently (previously sequential: up to 4×8s).
    # fetch_fred_series never raises, so each future resolves to a normalized
    # dict or the per-series mock fallback. dict(zip(...)) keeps FRED-id order.
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(_FRED_SERIES)) as ex:
        series = dict(zip(_FRED_SERIES, ex.map(fetch_fred_series, _FRED_SERIES)))
    us10y  = series["DGS10"]
    vix    = series["VIXCLS"]
    rates_pressure  = _classify_rates_pressure(us10y["change"])
    risk_volatility = _classify_risk_volatility(vix["latestValue"])
    # Top-level status reflects the data behind the *displayed signals*:
    # ratesPressure derives from DGS10 and riskVolatility from VIXCLS, and the
    # summary is built from both. The secondary cells (2Y, real 10Y) don't
    # drive any signal, so a flaky DFII10/DGS2 must NOT flip the whole snapshot
    # to "mock" while 10Y + VIX are genuinely live. Each series still carries
    # its own per-series `status` for cell-level accuracy.
    overall_status  = "live" if us10y["status"] == "live" and vix["status"] == "live" else "mock"
    summary = (
        f"10Y {us10y['latestValue']:.2f}% ({us10y['changeBp']:+.0f}bp), "
        f"VIX {vix['latestValue']:.1f}. "
        f"Pressure: {rates_pressure}, Vol: {risk_volatility}."
    )
    snapshot = {
        "us10y":          series["DGS10"],
        "us2y":           series["DGS2"],
        "usReal10y":      series["DFII10"],
        "vix":            series["VIXCLS"],
        "ratesPressure":  rates_pressure,
        "riskVolatility": risk_volatility,
        "summary":        summary,
        "status":         overall_status,
    }
    if overall_status == "live":
        _RATES_CACHE["data"]    = snapshot
        _RATES_CACHE["expires"] = now + _RATES_CACHE_TTL
    return snapshot

@app.route("/api/argus/rates")
def api_argus_rates():
    return jsonify(get_rates_snapshot())


# ━━━ J-Quants V2 (live Japan watchlist) ━━━
# J-Quants migrated v1 → V2: the old mailaddress/password token flow is
# discontinued (returns HTTP 410). V2 uses a single API key from the dashboard,
# passed in the `x-api-key` header. The key lives ONLY in Render env — never
# exposed to the frontend, never a VITE_ var.
_JQUANTS_BASE    = "https://api.jquants.com/v2"
_JQUANTS_API_KEY = os.environ.get("JQUANTS_API_KEY")

# The watched names. `symbol` is the TSE code passed straight to V2 (4-char
# codes incl. the alphanumeric 285A are accepted). `name` is the Japanese display
# name. `mock` holds plausible fallback values so the mock state renders sensibly
# when the key is unset or a fetch fails — they are NOT real quotes.
# IMPORTANT: symbol↔name mapping must NOT be guessed. 8058 = 三菱商事 (Mitsubishi
# Corporation), NOT 三菱重工 (Mitsubishi Heavy Industries, which is 7011). Verify
# any new code against the official issue list before adding it here.
_JP_WATCHLIST = [
    {"symbol": "8058", "name": "三菱商事", "mock": {"price": 2900.0, "changeAbs": 26.0,  "changePct": 0.90,  "volume": 9_800_000}},
    {"symbol": "9984", "name": "ソフトバンクグループ",              "mock": {"price": 9_800.0, "changeAbs": -180.0, "changePct": -1.80, "volume": 8_100_000}},
    {"symbol": "5801", "name": "古河電気工業",           "mock": {"price": 6_400.0, "changeAbs": 120.0,  "changePct": 1.91,  "volume": 3_200_000}},
    {"symbol": "5803", "name": "フジクラ",                    "mock": {"price": 7_200.0, "changeAbs": 210.0,  "changePct": 3.01,  "volume": 11_500_000}},
    {"symbol": "6584", "name": "三櫻工業",            "mock": {"price": 1_480.0, "changeAbs": -8.0,   "changePct": -0.54, "volume": 410_000}},
    {"symbol": "285A", "name": "キオクシアホールディングス",             "mock": {"price": 1_820.0, "changeAbs": 35.0,   "changePct": 1.96,  "volume": 5_600_000}},
    {"symbol": "9501", "name": "東京電力ホールディングス",        "mock": {"price": 720.0,   "changeAbs": -4.0,   "changePct": -0.55, "volume": 14_200_000}},
]

_JP_CACHE     = {"data": None, "expires": 0.0}
_JP_CACHE_TTL = 600

def _jp_mock_quote(s):
    m = s["mock"]
    return {
        "symbol": s["symbol"], "name": s["name"], "nameJa": s["name"],
        "price": m["price"], "changeAbs": m["changeAbs"], "changePct": m["changePct"],
        "volume": m["volume"], "date": None, "status": "mock",
    }

def _q_close(q):
    # V2 abbreviated fields: C = close; fall back to AdjC (adjusted close).
    v = q.get("C")
    return v if v is not None else q.get("AdjC")

def _jquants_fetch_quote(s, headers):
    """Latest + previous daily bar for one symbol → normalized dict or mock."""
    try:
        # Window the query (~150d) so we get the two most recent rows without
        # pulling full history; covers the free plan's ~12-week lag plus buffer.
        frm = (datetime.now(TZ_JST) - timedelta(days=150)).strftime("%Y-%m-%d")
        rows = []
        params = {"code": s["symbol"], "from": frm}
        for _ in range(6):  # follow pagination defensively (usually one page)
            r = requests.get(f"{_JQUANTS_BASE}/equities/bars/daily",
                             headers=headers, params=params, timeout=10)
            r.raise_for_status()
            body = r.json()
            rows.extend(body.get("data", []))
            pk = body.get("pagination_key")
            if not pk:
                break
            params["pagination_key"] = pk
        rows = [q for q in rows if _q_close(q) is not None]
        rows.sort(key=lambda q: q.get("Date", ""))
        if len(rows) < 2:
            return _jp_mock_quote(s)
        latest, prev = rows[-1], rows[-2]
        close  = float(_q_close(latest))
        pclose = float(_q_close(prev))
        change = round(close - pclose, 2)
        vol    = latest.get("Vo")
        return {
            "symbol": s["symbol"], "name": s["name"], "nameJa": s["name"],
            "price": close,
            "changeAbs": change,
            "changePct": round((change / pclose) * 100, 2) if pclose else 0.0,
            "volume": int(vol) if vol is not None else 0,
            "date": latest.get("Date"),
            "status": "live",
        }
    except Exception:
        return _jp_mock_quote(s)

def _jp_mock_snapshot():
    return {"status": "mock", "asOf": None,
            "stocks": [_jp_mock_quote(s) for s in _JP_WATCHLIST]}

def get_japan_watchlist_snapshot():
    """Live snapshot of the watched Japan names (price/change/volume/date).

    Mirrors the rates snapshot: parallel fetch, 10-min cache (live only), and
    a mock fallback so the UI always renders. `asOf` is the latest data date
    actually returned, so freshness (free plan ~12wk lag vs paid T-1) is
    surfaced honestly rather than assumed.
    """
    now = time.time()
    if _JP_CACHE["data"] is not None and now < _JP_CACHE["expires"]:
        return _JP_CACHE["data"]
    if not _JQUANTS_API_KEY:
        return _jp_mock_snapshot()  # no API key configured
    headers = {"x-api-key": _JQUANTS_API_KEY}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(_JP_WATCHLIST)) as ex:
        stocks = list(ex.map(lambda s: _jquants_fetch_quote(s, headers), _JP_WATCHLIST))
    overall = "live" if any(q["status"] == "live" for q in stocks) else "mock"
    as_of   = max((q["date"] for q in stocks if q.get("date")), default=None)
    snapshot = {"status": overall, "asOf": as_of, "stocks": stocks}
    if overall == "live":
        _JP_CACHE["data"]    = snapshot
        _JP_CACHE["expires"] = now + _JP_CACHE_TTL
    return snapshot

@app.route("/api/argus/japan-watchlist")
def api_argus_japan_watchlist():
    return jsonify(get_japan_watchlist_snapshot())


# ━━━ Twelve Data (live US watchlist) ━━━
# A single dashboard API key, sent as the `apikey` query param. The key lives
# ONLY in Render env — never exposed to the frontend, never a VITE_ var.
# Twelve Data's /quote accepts comma-separated symbols, so all four names are
# fetched in ONE request (4 credits) per cache refresh — free-tier-safe.
_TWELVEDATA_API_KEY = os.environ.get("TWELVEDATA_API_KEY")
_TWELVEDATA_QUOTE   = "https://api.twelvedata.com/quote"

# `mock` holds plausible fallback values (NOT real quotes) for the mock state.
_US_WATCHLIST = [
    {"symbol": "NVDA", "name": "NVIDIA",         "mock": {"price": 142.30, "changeAbs": -1.32, "changePct": -0.92, "volume": 240_000_000}},
    {"symbol": "AAPL", "name": "Apple",          "mock": {"price": 218.40, "changeAbs": -0.74, "changePct": -0.34, "volume": 52_000_000}},
    {"symbol": "TSLA", "name": "Tesla",          "mock": {"price": 178.20, "changeAbs": -5.74, "changePct": -3.12, "volume": 98_000_000}},
    {"symbol": "META", "name": "Meta Platforms", "mock": {"price": 487.10, "changeAbs": 3.78,  "changePct": 0.78,  "volume": 14_000_000}},
]

_US_CACHE     = {"data": None, "expires": 0.0}
_US_CACHE_TTL = 600

def _us_mock_quote(s):
    m = s["mock"]
    return {
        "symbol": s["symbol"], "name": s["name"], "nameJa": s["name"],
        "price": m["price"], "changeAbs": m["changeAbs"], "changePct": m["changePct"],
        "volume": m["volume"], "date": None, "status": "mock",
    }

def _us_mock_snapshot():
    return {"status": "mock", "asOf": None, "provider": "twelvedata",
            "stocks": [_us_mock_quote(s) for s in _US_WATCHLIST]}

def _td_parse_row(s, q):
    """Normalize one Twelve Data quote object → live row, or None if invalid.

    A per-symbol error from Twelve Data is a dict with status=='error' (and no
    price fields), so anything missing the core fields returns None.
    """
    try:
        if not isinstance(q, dict):
            return None
        if str(q.get("status", "")).lower() == "error":
            return None
        close = q.get("close")
        chg   = q.get("change")
        pct   = q.get("percent_change")
        if close is None or chg is None or pct is None:
            return None
        vol = q.get("volume")
        dt  = q.get("datetime")
        return {
            "symbol": s["symbol"], "name": s["name"],
            "price": round(float(close), 2),
            "changeAbs": round(float(chg), 2),
            "changePct": round(float(pct), 2),
            "volume": int(float(vol)) if vol not in (None, "") else 0,
            "date": (str(dt)[:10] if dt else None),
            "status": "live",
        }
    except Exception:
        return None

def get_us_watchlist_snapshot():
    """Live snapshot of the watched US names (price/change/volume/date).

    Mirrors the Japan/FRED pattern: one batched request, 10-min cache (live
    only), mock fallback. Per the spec, top-level status is "live" only when
    ALL target symbols parse to valid live rows — otherwise the whole snapshot
    falls back to mock rather than presenting partial fake-live data.
    """
    now = time.time()
    if _US_CACHE["data"] is not None and now < _US_CACHE["expires"]:
        return _US_CACHE["data"]
    if not _TWELVEDATA_API_KEY:
        return _us_mock_snapshot()
    try:
        symbols = ",".join(s["symbol"] for s in _US_WATCHLIST)
        r = requests.get(_TWELVEDATA_QUOTE,
                         params={"symbol": symbols, "apikey": _TWELVEDATA_API_KEY},
                         timeout=10)
        r.raise_for_status()
        body = r.json()
        # A top-level error (bad key / quota) is a flat dict with status=error.
        if isinstance(body, dict) and str(body.get("status", "")).lower() == "error":
            return _us_mock_snapshot()
        rows = []
        for s in _US_WATCHLIST:
            # Multi-symbol responses are keyed by symbol; single is flat.
            q = body.get(s["symbol"]) if (isinstance(body, dict) and s["symbol"] in body) else body
            row = _td_parse_row(s, q)
            if row is None:
                return _us_mock_snapshot()  # any miss → full mock, never partial fake-live
            rows.append(row)
        as_of = max((row["date"] for row in rows if row.get("date")), default=None)
        snapshot = {"status": "live", "asOf": as_of, "provider": "twelvedata", "stocks": rows}
        _US_CACHE["data"]    = snapshot
        _US_CACHE["expires"] = now + _US_CACHE_TTL
        return snapshot
    except Exception:
        return _us_mock_snapshot()

@app.route("/api/argus/us-watchlist")
def api_argus_us_watchlist():
    return jsonify(get_us_watchlist_snapshot())


# ━━━ Event Radar (live official calendar) ━━━
# Phase 1 = schedule/risk timing only (no forecast/actual/consensus). Sources:
#   - TreasuryDirect: fetched LIVE at runtime (machine-readable JSON API).
#   - FOMC / BOJ / BLS / BEA: curated from official calendars + the OMB/OIRA
#     PFEI CY2026 release schedule. These are official, fixed published dates —
#     served directly rather than scraped at runtime (robust, no brittle HTML).
#     Refresh this table for 2027. Escalation/daysUntil are recomputed every
#     request (Asia/Tokyo perspective); only the TreasuryDirect fetch is cached.
_EVENTS_CURATED_ASOF = "2026-06-08"
_TZ_ET               = pytz.timezone("America/New_York")
_EVENT_HORIZON_DAYS  = 60   # only surface events within ~2 months (calm radar)

_FOMC_2026 = ["2026-06-17", "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09"]
_BOJ_2026  = ["2026-06-16", "2026-07-31", "2026-09-18", "2026-10-30", "2026-12-18"]
_BOJ_OUTLOOK = {"2026-07-31", "2026-10-30"}
_CPI_2026  = ["2026-06-10", "2026-07-14", "2026-08-12", "2026-09-11", "2026-10-14", "2026-11-10", "2026-12-10"]
_PPI_2026  = ["2026-06-11", "2026-07-15", "2026-08-13", "2026-09-10", "2026-10-15", "2026-11-13", "2026-12-15"]
_NFP_2026  = ["2026-06-05", "2026-07-02", "2026-08-07", "2026-09-04", "2026-10-02", "2026-11-06", "2026-12-04"]
_PCE_2026  = ["2026-06-25", "2026-07-30", "2026-08-26", "2026-09-30", "2026-10-29", "2026-11-25", "2026-12-23"]
_GDP_2026  = ["2026-06-25", "2026-07-30", "2026-08-26", "2026-09-30", "2026-10-29", "2026-11-25", "2026-12-23"]
_JOLTS_2026 = ["2026-06-30", "2026-08-04", "2026-09-01", "2026-09-29", "2026-11-03", "2026-12-01"]

_EVENT_RATIONALE = {
    "fomc":    "金利・ドル円・米国グロース株のリスク許容度を左右するため、イベント前後はポジションサイズと追いかけ買いを抑える。",
    "cpi":     "インフレ再加速は米金利上昇とグロース株のバリュエーション圧迫につながるため、発表前後の指数・金利・為替を確認する。",
    "ppi":     "卸売物価はCPIの先行指標で米金利に影響するため、発表後の金利方向を確認する。",
    "nfp":     "雇用の強弱は利下げ期待と景気減速懸念の両方に影響するため、発表後の金利方向を優先して確認する。",
    "jolts":   "求人件数は労働市場の需給と賃金圧力を示すため、金利・ドル円・グロース株の反応を確認する。",
    "pce":     "FRBが重視するインフレ指標。再加速は米金利上昇とグロース株圧迫につながるため、発表前後の金利・為替を確認する。",
    "gdp":     "成長の強弱は景気見通しと金利方向を左右するため、発表後の金利・株指数の反応を確認する。",
    "boj":     "円金利・ドル円・日本株グロース/輸出株の地合いに影響するため、会合前後は円高・金利上昇・銀行株/輸出株の反応を見る。",
    "auction": "国債入札の弱さは長期金利上昇を通じてNASDAQや高PER株に圧力をかけるため、入札前後のUS10YとQQQを確認する。",
}

# (dates, et_time, kind, title, category, country, source, impact, linkedAssets)
_EVENT_SPECS = [
    (_FOMC_2026, "14:00", "fomc", "FOMC Rate Decision",                "central_bank", "US", "Federal Reserve",             "high",   ["USDJPY", "US10Y", "US2Y", "QQQ", "NVDA"]),
    (_CPI_2026,  "08:30", "cpi",  "US CPI (Consumer Price Index)",     "inflation",    "US", "Bureau of Labor Statistics",  "high",   ["US10Y", "USDJPY", "QQQ", "SPY"]),
    (_NFP_2026,  "08:30", "nfp",  "US Employment Situation",           "jobs",         "US", "Bureau of Labor Statistics",  "high",   ["US10Y", "USDJPY", "SPY", "QQQ"]),
    (_JOLTS_2026, "10:00", "jolts", "US JOLTS Job Openings",           "jobs",         "US", "Bureau of Labor Statistics",  "medium", ["US10Y", "USDJPY", "SPY", "QQQ"]),
    (_PPI_2026,  "08:30", "ppi",  "US PPI (Producer Price Index)",     "inflation",    "US", "Bureau of Labor Statistics",  "medium", ["US10Y", "QQQ"]),
    (_PCE_2026,  "08:30", "pce",  "US PCE / Personal Income & Outlays", "inflation",   "US", "Bureau of Economic Analysis", "high",   ["US10Y", "USDJPY", "QQQ"]),
    (_GDP_2026,  "08:30", "gdp",  "US GDP",                            "growth",       "US", "Bureau of Economic Analysis", "high",   ["US10Y", "SPY", "USDJPY"]),
    (_BOJ_2026,  None,    "boj",  "BOJ Monetary Policy Meeting",       "central_bank", "JP", "Bank of Japan",               "high",   ["USDJPY", "JP10Y", "9984", "8058"]),
]

# Each source maps to its curated lastUpdated marker; TreasuryDirect is dynamic.
_EVENT_SOURCE_NAMES = ["Federal Reserve", "Bureau of Labor Statistics",
                       "Bureau of Economic Analysis", "Bank of Japan"]

_TD_CACHE = {"data": None, "status": None, "expires": 0.0}

def _event_timing(date_str, et_time, today_jst):
    """Return (eventTimeUtc, localTimeJst, daysUntil) computed from Tokyo time.

    When a precise ET time is known we localize → UTC → JST so the JST date (and
    thus escalation) reflects the user's timezone. Date-only events (BOJ — no
    fixed announcement time) keep UTC/JST null and use the published date.
    """
    if et_time:
        et = _TZ_ET.localize(datetime.strptime(f"{date_str} {et_time}", "%Y-%m-%d %H:%M"))
        utc = et.astimezone(pytz.utc)
        jst = et.astimezone(TZ_JST)
        return (utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                jst.strftime("%Y-%m-%d %H:%M JST"),
                (jst.date() - today_jst).days)
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    return (None, None, (d - today_jst).days)

def _escalation(days):
    if days == 0:        return "D"
    if days == 1:        return "D-1"
    if days in (2, 3):   return "D-3"
    if 4 <= days <= 7:   return "D-7"
    if days == -1:       return "D+1"
    return "normal"

def _build_curated_events(today_jst):
    out = []
    for dates, et_time, kind, title, cat, country, source, impact, assets in _EVENT_SPECS:
        for d in dates:
            utc, jst_local, days = _event_timing(d, et_time, today_jst)
            if days < -1 or days > _EVENT_HORIZON_DAYS:
                continue
            t = title + " (Outlook Report)" if (kind == "boj" and d in _BOJ_OUTLOOK) else title
            prefix = "jp" if country == "JP" else "us"
            out.append({
                "id": f"{prefix}-{kind}-{d}",
                "title": t, "category": cat, "country": country, "source": source,
                "impact": impact, "eventTimeUtc": utc, "eventDate": d,
                "localTimeJst": jst_local, "daysUntil": days,
                "escalation": _escalation(days), "rationaleJa": _EVENT_RATIONALE[kind],
                "linkedAssets": assets, "status": "live",
            })
    return out

def _fetch_treasury_raw():
    """Fetch upcoming Treasury auctions (live JSON). Returns (list, status)."""
    tenors = {"2-Year", "5-Year", "7-Year", "10-Year", "20-Year", "30-Year"}
    try:
        r = requests.get("https://www.treasurydirect.gov/TA_WS/securities/upcoming",
                         params={"format": "json"}, timeout=10)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list):
            return [], "error"
        rows, seen = [], set()
        for a in data:
            if not isinstance(a, dict):
                continue
            if a.get("securityType") not in ("Note", "Bond"):
                continue
            # Reopenings carry a fractional securityTerm (e.g. "9-Year 11-Month")
            # but originalSecurityTerm is the clean tenor ("10-Year") — match on
            # that so monthly 10Y/20Y/30Y/5Y reopenings aren't dropped.
            term = a.get("originalSecurityTerm") or a.get("securityTerm")
            auc  = a.get("auctionDate")
            if term not in tenors or not auc:
                continue
            date_str = str(auc)[:10]
            key = (term, date_str)
            if key in seen:
                continue
            seen.add(key)
            rows.append({"term": term, "date": date_str,
                         "impact": "high" if term in ("10-Year", "20-Year", "30-Year") else "medium"})
        return rows, "live"
    except Exception:
        return [], "error"

def _treasury_auctions_cached():
    now = time.time()
    if _TD_CACHE["data"] is not None and now < _TD_CACHE["expires"]:
        return _TD_CACHE["data"], _TD_CACHE["status"]
    rows, status = _fetch_treasury_raw()
    _TD_CACHE["data"], _TD_CACHE["status"] = rows, status
    # Cache a good fetch for 6h; back off only briefly on error so it recovers.
    _TD_CACHE["expires"] = now + (6 * 3600 if status == "live" else 300)
    return rows, status

def _build_auction_events(today_jst):
    rows, status = _treasury_auctions_cached()
    out = []
    for a in rows:
        days = (datetime.strptime(a["date"], "%Y-%m-%d").date() - today_jst).days
        if days < -1 or days > _EVENT_HORIZON_DAYS:
            continue
        slug = a["term"].lower().replace("-", "")
        out.append({
            "id": f"us-treasury-{slug}-{a['date']}",
            "title": f"US Treasury {a['term']} Auction",
            "category": "treasury", "country": "US", "source": "TreasuryDirect",
            "impact": a["impact"], "eventTimeUtc": None, "eventDate": a["date"],
            "localTimeJst": None, "daysUntil": days, "escalation": _escalation(days),
            "rationaleJa": _EVENT_RATIONALE["auction"],
            "linkedAssets": ["US10Y", "QQQ"], "status": "live",
        })
    return out, status

def get_events_snapshot():
    """Aggregated official event calendar for ARGUS Event Radar (Phase 1).

    Curated sources (Fed/BLS/BEA/BOJ) are always available; TreasuryDirect is
    fetched live. Top-level status is "live" when the auction fetch succeeds,
    "partial" when it fails (curated calendar still served), "mock" only if the
    whole build fails.
    """
    try:
        today_jst = datetime.now(TZ_JST).date()
        events = _build_curated_events(today_jst)
        auctions, td_status = _build_auction_events(today_jst)
        events += auctions
        td_src_status = "live" if td_status == "live" else "error"
        sources = [{"name": n, "status": "live", "lastUpdated": f"{_EVENTS_CURATED_ASOF}T00:00:00Z"}
                   for n in _EVENT_SOURCE_NAMES]
        sources.append({
            "name": "TreasuryDirect", "status": td_src_status,
            "lastUpdated": (datetime.now(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if td_status == "live" else None),
        })
        status = "live" if td_status == "live" else "partial"
        return {
            "status": status,
            "asOf": datetime.now(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "timezone": "Asia/Tokyo",
            "sources": sources,
            "events": events,
        }
    except Exception:
        return _events_mock_snapshot()

def _events_mock_snapshot():
    # Last-resort fallback only (curated build is offline, so this is unlikely).
    return {
        "status": "mock",
        "asOf": None,
        "timezone": "Asia/Tokyo",
        "sources": [{"name": n, "status": "mock", "lastUpdated": None}
                    for n in _EVENT_SOURCE_NAMES + ["TreasuryDirect"]],
        "events": [{
            "id": "us-fomc-mock", "title": "FOMC Rate Decision", "category": "central_bank",
            "country": "US", "source": "Federal Reserve", "impact": "high",
            "eventTimeUtc": None, "eventDate": None, "localTimeJst": None,
            "daysUntil": 0, "escalation": "normal", "rationaleJa": _EVENT_RATIONALE["fomc"],
            "linkedAssets": ["USDJPY", "US10Y", "QQQ"], "status": "mock",
        }],
    }

@app.route("/api/argus/events")
def api_argus_events():
    return jsonify(get_events_snapshot())


# ━━━ Action Label Engine v0 (rule-based, internal) ━━━
# Classifies the watched names into ARGUS action categories using EXISTING live
# data only (rates + watchlists + events). No external LLM, no new APIs, no
# invented VWAP/flow/news. Conservative by design: prefers WAIT/HOLD when
# unsure, never EXIT, and never TRIM in v0 (no trend/flow confirmation yet).
_ACTION_SYMBOLS = [
    {"symbol": "8058", "market": "JP", "name": "三菱商事", "cls": "jp_industrial"},
    {"symbol": "9984", "market": "JP", "name": "ソフトバンクグループ",              "cls": "jp_momentum"},
    {"symbol": "5801", "market": "JP", "name": "古河電気工業",           "cls": "jp_momentum"},
    {"symbol": "5803", "market": "JP", "name": "フジクラ",                    "cls": "jp_momentum"},
    {"symbol": "6584", "market": "JP", "name": "三櫻工業",            "cls": "jp_momentum"},
    {"symbol": "285A", "market": "JP", "name": "キオクシアホールディングス",             "cls": "jp_momentum"},
    {"symbol": "9501", "market": "JP", "name": "東京電力ホールディングス",        "cls": "jp_utility"},
    {"symbol": "NVDA", "market": "US", "name": "NVIDIA",                      "cls": "us_growth"},
    {"symbol": "AAPL", "market": "US", "name": "Apple",                       "cls": "us_growth"},
    {"symbol": "TSLA", "market": "US", "name": "Tesla",                       "cls": "us_growth"},
    {"symbol": "META", "market": "US", "name": "Meta Platforms",             "cls": "us_growth"},
]

def _rates_posture(rates):
    # Derived from the snapshot's ratesPressure (computed from the 10Y change
    # FRED gives us — a real signal), stated cautiously. No intraday claims.
    rp = rates.get("ratesPressure") if isinstance(rates, dict) else None
    if rp in ("High", "Medium"): return "elevated"
    if rp == "Relief":           return "easing"
    return "neutral"

def _region_event_escalation(events, region):
    """Most severe relevant high-impact escalation for a region (or None)."""
    sev = {"D": 3, "D-1": 3, "D-3": 2}
    best, best_sev = None, 0
    for e in events:
        if e.get("impact") != "high":
            continue
        esc = e.get("escalation")
        if esc not in sev:
            continue
        t = e.get("title", "")
        rel = ("BOJ" in t) if region == "JP" else (
            e.get("country") == "US" and any(k in t for k in ("FOMC", "CPI", "PCE", "Employment")))
        if rel and sev[esc] > best_sev:
            best, best_sev = esc, sev[esc]
    return best

def _classify_symbol(meta, chg, esc, posture):
    """Transparent v0 rules. Returns (action, risk, confidence, reasonJa, nextJa)."""
    high_beta = meta["cls"] in ("us_growth", "jp_momentum")
    imminent  = esc in ("D", "D-1")
    near      = esc == "D-3"
    elevated_event = imminent or near

    if chg <= -7:
        action, risk, conf = "WAIT", "high", 0.82
        reason = "下落モメンタムが大きく、急落の途中で拾うのは避ける。"
        nxt = "下げ止まり・下げ幅の縮小・翌セッションでの確認を待つ。"
    elif chg <= -5:
        action, risk, conf = "WAIT", "high", 0.70
        reason = "大きめの下落でリスクが高く、急落の途中で拾うのは避ける。"
        nxt = "株価が下げ止まり、出来高を伴って安定するかを確認する。"
    elif chg >= 5:
        action, risk, conf = "WAIT FOR PULLBACK", "medium", 0.65
        reason = "大きく上昇した直後で、追いかけ買いは避ける。"
        nxt = "押し目を作り過熱が和らぐかを確認する。"
    elif 2 <= chg < 5:
        if imminent or (near and high_beta):
            action, risk, conf = "WAIT FOR PULLBACK", "medium", 0.55
            reason = "上昇後かつ重要イベント接近のため、追いかけ買いを避ける。"
            nxt = "イベント通過後の反応と押し目の有無を確認する。"
        else:
            action, risk, conf = "HOLD", "medium", 0.50
            reason = "緩やかな上昇でトレンドは継続。新規の追いかけは控える。"
            nxt = "上昇の継続性と次のイベント日程を確認する。"
    elif -2 < chg < 2:
        if elevated_event and high_beta:
            action, risk, conf = "WAIT", "medium", 0.55
            reason = "値動きは小さいが重要イベントが近く、高ベータ銘柄は様子見。"
            nxt = "イベント通過後の金利・為替・指数の反応を確認する。"
        else:
            action, risk, conf = "HOLD", ("medium" if elevated_event else "low"), 0.45
            reason = "値動きは限定的でトレンドに変化なし。"
            nxt = "次のイベントと値動きの変化を確認する。"
    else:  # -5 < chg <= -2
        if elevated_event or posture == "elevated":
            action, risk, conf = "WAIT", "medium", 0.55
            reason = "やや軟調かつイベント/金利のリスクがあり、新規は様子見。"
            nxt = "下げ止まりとイベント通過後の方向を確認する。"
        else:
            action, risk, conf = "HOLD", "medium", 0.45
            reason = "やや軟調だが過度な売り材料はなく保有継続。"
            nxt = "下げ幅の拡大や地合いの悪化がないかを確認する。"

    # Rate-sensitive growth/momentum caution wording (v0 — no intraday claim).
    if high_beta and posture == "elevated":
        reason += " 金利水準がグロース株の上値を抑えやすい点も考慮。"
    return action, risk, round(conf, 2), reason, nxt

def get_action_labels():
    """Rule-based action labels for the watched names, aggregated server-side."""
    rates = get_rates_snapshot()
    jp    = get_japan_watchlist_snapshot()
    us    = get_us_watchlist_snapshot()
    ev    = get_events_snapshot()
    events  = ev.get("events", []) if isinstance(ev, dict) else []
    posture = _rates_posture(rates)
    esc_by_market = {"US": _region_event_escalation(events, "US"),
                     "JP": _region_event_escalation(events, "JP")}

    quotes = {}
    for snap in (jp, us):
        for s in (snap.get("stocks", []) if isinstance(snap, dict) else []):
            quotes[s["symbol"]] = s

    labels, changes = [], []
    for meta in _ACTION_SYMBOLS:
        q   = quotes.get(meta["symbol"])
        esc = esc_by_market[meta["market"]]
        if not q or q.get("status") != "live":
            labels.append({
                "symbol": meta["symbol"], "market": meta["market"], "name": meta["name"],
                "action": "HOLD", "confidence": 0.2, "risk": "low",
                "reasonJa": "ライブ価格が未取得のため中立で保留。",
                "supportingData": {"changePct": (q or {}).get("changePct", 0), "volume": (q or {}).get("volume", 0),
                                   "eventEscalation": esc or "normal", "ratesPosture": posture},
                "nextConditionJa": "ライブデータ復帰後に再評価する。",
                "status": "mock",
            })
            continue
        chg = float(q.get("changePct", 0))
        changes.append(chg)
        action, risk, conf, reason, nxt = _classify_symbol(meta, chg, esc, posture)
        labels.append({
            "symbol": meta["symbol"], "market": meta["market"], "name": meta["name"],
            "action": action, "confidence": conf, "risk": risk, "reasonJa": reason,
            "supportingData": {"changePct": chg, "volume": q.get("volume", 0),
                               "eventEscalation": esc or "normal", "ratesPosture": posture},
            "nextConditionJa": nxt, "status": "live",
        })

    imminent_any = esc_by_market["US"] in ("D", "D-1") or esc_by_market["JP"] in ("D", "D-1")
    avg = sum(changes) / len(changes) if changes else 0.0
    if imminent_any:
        mp, mp_ja = "EVENT_WAIT", "重要イベントが目前のため、新規ポジションを抑えイベント通過後に判断する。"
    elif avg <= -2.0:
        mp, mp_ja = "RISK_OFF", "ウォッチリスト全体が軟調で、リスク回避寄りの地合い。"
    elif avg >= 1.5:
        mp, mp_ja = "RISK_ON", "ウォッチリスト全体が堅調で、リスク選好寄りの地合い。"
    else:
        mp, mp_ja = "CAUTIOUS", "方向感は限定的で、慎重なスタンスを継続する。"

    rates_live = isinstance(rates, dict) and rates.get("status") == "live"
    jp_live    = isinstance(jp, dict) and jp.get("status") == "live"
    us_live    = isinstance(us, dict) and us.get("status") == "live"
    ev_ok      = isinstance(ev, dict) and ev.get("status") in ("live", "partial")
    if rates_live and jp_live and us_live and ev_ok:
        status = "live"
    elif jp_live or us_live:
        status = "partial"   # some live prices → conservative labels still produced
    else:
        status = "mock"

    return {
        "status": status,
        "asOf": datetime.now(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "engineVersion": "action-v0",
        "marketPosture": {"label": mp, "rationaleJa": mp_ja},
        "labels": labels,
    }

@app.route("/api/argus/action-labels")
def api_argus_action_labels():
    return jsonify(get_action_labels())


# ━━━ AI Judgment Layer (OpenAI primary + Gemini double-check) — DORMANT ━━━
# NOTE: The OpenAI/Gemini judge functions below are kept for a FUTURE version
# (GPT-5.5 API + Gemini double-check, v8.10.x+). They are NOT wired to any
# endpoint in this version — no OpenAI/Gemini call is made. The live AI run path
# is replaced by the Security Gate v1 placeholder + the manual GPT-5.5 Pro
# handoff export below.
_OPENAI_API_KEY        = os.environ.get("OPENAI_API_KEY", "")
_OPENAI_MODEL          = os.environ.get("OPENAI_MODEL", "") or "gpt-5.5"
_GEMINI_JUDGE_MODEL    = os.environ.get("GEMINI_JUDGE_MODEL", "") or "gemini-2.5-flash"
_ARGUS_ADMIN_TOKEN     = os.environ.get("ARGUS_ADMIN_TOKEN", "")

# ── AI safety / Security Gate v1 config ──────────────────────────────
_AI_JUDGE_ENABLED  = os.environ.get("AI_JUDGE_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
def _int_env(name, default):
    try: return int(os.environ.get(name, str(default)) or default)
    except Exception: return default
_AI_JUDGE_MAX_RUNS      = _int_env("AI_JUDGE_MAX_RUNS_PER_DAY", 3)
_AI_JUDGE_MIN_INTERVAL  = _int_env("AI_JUDGE_MIN_INTERVAL_MINUTES", 30)
_AI_JUDGE_LOCKED_ENV    = os.environ.get("AI_JUDGE_LOCKED", "false").strip().lower() in ("1", "true", "yes", "on")
_AI_JUDGE_ALLOW_COUNTRIES = [c.strip().upper() for c in os.environ.get("AI_JUDGE_ALLOW_COUNTRIES", "JP").split(",") if c.strip()]
_SECURITY_ALERT_EMAIL    = os.environ.get("SECURITY_ALERT_EMAIL", "")
_SECURITY_ALERT_PROVIDER = os.environ.get("SECURITY_ALERT_PROVIDER", "")
_SECURITY_ALERT_WEBHOOK  = os.environ.get("SECURITY_ALERT_WEBHOOK", "")

# In-memory run ledger + security state (v1). NOTE: in-memory only — resets on
# dyno restart. Move to a persistent store (Render disk / DB) if durable limits
# are needed later.
_AI_LOCK = threading.Lock()
_AI_GATE_STATE = {
    "date": None,            # JST date string for the daily counter
    "count": 0,              # runs counted today
    "lastRunTs": 0.0,        # epoch of last allowed run (min-interval)
    "failedAttempts": 0,     # consecutive bad/unauthorized admin attempts
    "softLocked": False,     # runtime soft lock after repeated failures
}
_FAILED_ATTEMPTS_LOCK_THRESHOLD = 5

# Final AI-judgment cache (v9.1). GET reads this; only an admin-gated POST run
# writes it. In-memory (resets on dyno restart).
_AI_CACHE_TTL = _int_env("AI_JUDGE_CACHE_TTL_MINUTES", 30) * 60
_AI_RESULT_CACHE = {"data": None, "expires": 0.0}

_AI_CONSERVATIVE = {"WAIT", "HOLD", "WAIT FOR PULLBACK"}
_AI_RANK = {"EXIT": 0, "TRIM": 1, "WAIT FOR PULLBACK": 2, "WAIT": 3, "BUY DIP": 4, "ADD": 5, "HOLD": 6}

def _ai_most_conservative(a, b):
    # Smaller rank = more defensive; prefer the more defensive of the two.
    return a if _AI_RANK.get(a, 99) <= _AI_RANK.get(b, 99) else b

def _build_ai_snapshot():
    """Compact, secret-free structured snapshot for the AI judges."""
    al = get_action_labels()
    rates = get_rates_snapshot()
    ev = get_events_snapshot()
    urgent = [{"title": e["title"], "country": e["country"], "impact": e["impact"],
               "escalation": e["escalation"], "daysUntil": e["daysUntil"]}
              for e in (ev.get("events", []) if isinstance(ev, dict) else [])
              if e.get("escalation") in ("D", "D-1", "D-3")]
    labels = [{"symbol": l["symbol"], "market": l["market"], "name": l["name"],
               "ruleAction": l["action"], "risk": l["risk"], "confidence": l["confidence"],
               "changePct": l["supportingData"]["changePct"], "volume": l["supportingData"]["volume"],
               "eventEscalation": l["supportingData"]["eventEscalation"],
               "reasonJa": l["reasonJa"], "nextConditionJa": l["nextConditionJa"]}
              for l in al.get("labels", [])]
    snap = {
        "marketPosture": al.get("marketPosture"),
        "rates": {k: rates.get(k) for k in ("ratesPressure", "riskVolatility", "summary")} if isinstance(rates, dict) else {},
        "urgentEvents": urgent,
        "labels": labels,
    }
    return snap, al

_OPENAI_SYSTEM = (
    "You are the ARGUS AI judgment layer. ARGUS is NOT a prediction engine: it classifies current "
    "market conditions into action categories and explains stance/reason/risk/confidence/what-would-"
    "change. You REVIEW and critique a deterministic rule engine's labels using ONLY the provided "
    "structured snapshot. Do NOT fabricate news, VWAP, order flow, order book, or analyst data, and "
    "do NOT claim intraday rate direction. Be conservative: prefer WAIT/HOLD/WAIT FOR PULLBACK. "
    "ADD/BUY DIP require explicit stabilization or a positive setup in the data; EXIT/TRIM require a "
    "severe rule condition or clear risk evidence; if uncertain, choose WAIT or HOLD. State data "
    "limitations honestly. All *Ja fields must be concise Japanese. Return STRICT JSON only."
)

def _openai_judge(snapshot):
    if not _OPENAI_API_KEY:
        return None, "unavailable"
    user = ("Review these rule-based ARGUS labels and return STRICT JSON with keys: status, model, "
            "asOf, summaryJa, marketRiskJa, modelPosture (RISK_ON|CAUTIOUS|RISK_OFF|EVENT_WAIT), and "
            "labels[] each with symbol, aiView (confirm|caution|disagree), suggestedAction "
            "(EXIT|TRIM|WAIT|WAIT FOR PULLBACK|BUY DIP|ADD|HOLD), confidence (0..1), risk "
            "(low|medium|high), reasonJa, whatCouldChangeJa, redFlags[], dataLimitations[]. "
            "Snapshot:\n" + json.dumps(snapshot, ensure_ascii=False))
    try:
        import openai
        client = openai.OpenAI(api_key=_OPENAI_API_KEY)
        text = None
        try:
            # Current best practice for gpt-5.x: the Responses API.
            resp = client.responses.create(model=_OPENAI_MODEL, instructions=_OPENAI_SYSTEM,
                                            input=user, timeout=60)
            text = getattr(resp, "output_text", None)
        except Exception:
            # Fallback for SDKs/models without the Responses API.
            resp = client.chat.completions.create(
                model=_OPENAI_MODEL,
                messages=[{"role": "system", "content": _OPENAI_SYSTEM}, {"role": "user", "content": user}],
                response_format={"type": "json_object"}, timeout=60)
            text = resp.choices[0].message.content
        out = safe_json(text or "")
        if not isinstance(out, dict) or not isinstance(out.get("labels"), list):
            return None, "partial"
        return out, "live"
    except Exception as e:
        add_log(f"[AI] openai judge failed: {type(e).__name__}")
        return None, "unavailable"

def _gemini_check(snapshot, openai_out):
    """Returns (out|None, status, grounding_enabled)."""
    if not google_genai or not GEMINI_API_KEY:
        return None, "unavailable", False
    grounding_enabled = False
    try:
        client = google_genai.Client(api_key=GEMINI_API_KEY)
        prompt = (
            "あなたはARGUSの独立検証役です。以下の市場スナップショット・ルールラベル・GPTの提案を検証し、"
            "(1)裏付けのない主張、(2)直近の重大リスク(web情報があれば反映)、(3)GPT提案が強気/積極的すぎないか、"
            "(4)注意すべき銘柄、(5)最終アクションを引き下げるべきか、を点検してください。捏造は禁止。"
            "STRICT JSONのみを返す。キー: status, model, summaryJa, disagreements[] "
            "(symbol, issueJa, severity(low|medium|high), recommendedConservativeAction(WAIT|HOLD|WAIT FOR PULLBACK)), "
            "globalRedFlags[], groundingSources[] (title,url)。\n"
            "SNAPSHOT:\n" + json.dumps(snapshot, ensure_ascii=False) +
            "\nGPT:\n" + json.dumps(openai_out or {}, ensure_ascii=False))
        cfg = None
        try:
            from google.genai import types as _gt
            cfg = _gt.GenerateContentConfig(tools=[_gt.Tool(google_search=_gt.GoogleSearch())])
            grounding_enabled = True
        except Exception:
            cfg, grounding_enabled = None, False
        resp = (client.models.generate_content(model=_GEMINI_JUDGE_MODEL, contents=prompt, config=cfg)
                if cfg else client.models.generate_content(model=_GEMINI_JUDGE_MODEL, contents=prompt))
        out = safe_json(getattr(resp, "text", "") or "")
        if not isinstance(out, dict) or "disagreements" not in out:
            return None, "partial", grounding_enabled
        # Best-effort: pull real grounding citations from response metadata.
        try:
            srcs = []
            for c in (getattr(resp, "candidates", []) or []):
                gm = getattr(c, "grounding_metadata", None)
                for ch in (getattr(gm, "grounding_chunks", []) or []):
                    web = getattr(ch, "web", None)
                    if web:
                        srcs.append({"title": getattr(web, "title", "") or "", "url": getattr(web, "uri", "") or ""})
            if srcs and not out.get("groundingSources"):
                out["groundingSources"] = srcs[:5]
        except Exception:
            pass
        return out, "live", grounding_enabled
    except Exception as e:
        add_log(f"[AI] gemini check failed: {type(e).__name__}")
        return None, "unavailable", grounding_enabled

def _arbitrate_ai(al, openai_out, gemini_out):
    oai_by = {l.get("symbol"): l for l in (openai_out.get("labels", []) if isinstance(openai_out, dict) else [])}
    gem_by = {d.get("symbol"): d for d in (gemini_out.get("disagreements", []) if isinstance(gemini_out, dict) else [])}
    labels = []
    for rl in al.get("labels", []):
        sym = rl["symbol"]
        rule_action = rl["action"]
        oai = oai_by.get(sym)
        gem = gem_by.get(sym)
        final = rule_action
        view = "unavailable"
        reason = rl["reasonJa"]
        what = rl["nextConditionJa"]
        oai_reason = ""
        gem_check = ""
        redflags, datalim = [], []
        conf, risk = rl["confidence"], rl["risk"]

        if isinstance(oai, dict):
            view = oai.get("aiView", "caution")
            oai_reason = (oai.get("reasonJa") or "")[:240]
            what = (oai.get("whatCouldChangeJa") or what) or what
            redflags = [str(x)[:120] for x in (oai.get("redFlags") or [])][:4]
            datalim = [str(x)[:120] for x in (oai.get("dataLimitations") or [])][:4]
            if isinstance(oai.get("confidence"), (int, float)):
                conf = round(float(oai["confidence"]), 2)
            if oai.get("risk") in ("low", "medium", "high"):
                risk = oai["risk"]
            sug = oai.get("suggestedAction", "")
            if sug in _AI_CONSERVATIVE:
                final = sug
            elif sug in ("ADD", "BUY DIP"):
                final = rule_action; view = "caution"
                datalim = datalim + ["v1ではADD/BUY DIPは採用しない(確証データ不足)"]
            elif sug in ("EXIT", "TRIM"):
                final = "WAIT"; view = "caution"
                datalim = datalim + ["v1ではEXIT/TRIMは採用せずWAITに留める"]
            reason = oai_reason or reason

        if isinstance(gem, dict):
            gem_check = (gem.get("issueJa") or "")[:240]
            sev = gem.get("severity", "low")
            rec = gem.get("recommendedConservativeAction", "WAIT")
            if rec not in _AI_CONSERVATIVE:
                rec = "WAIT"
            if sev == "high":
                final = rec; view = "disagree"
                reason = gem_check or reason
            elif sev == "medium":
                final = _ai_most_conservative(final, rec)
                if view == "confirm":
                    view = "caution"

        labels.append({
            "symbol": sym, "market": rl["market"], "ruleAction": rule_action,
            "aiFinalAction": final, "aiView": view, "confidence": conf, "risk": risk,
            "reasonJa": reason, "whatCouldChangeJa": what,
            "openaiReasonJa": oai_reason, "geminiCheckJa": gem_check,
            "redFlags": redflags, "dataLimitations": datalim,
            "status": rl.get("status", "live"),
        })
    return labels

def _ai_now_iso():
    return datetime.now(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _ai_disabled_payload(status="disabled", reason="AI judgment is not enabled yet."):
    return {"status": status, "reason": reason,
            "asOf": _ai_now_iso(), "engineVersion": "ai-judge-v1", "runMode": "cached",
            "models": {"primary": _OPENAI_MODEL, "checker": _GEMINI_JUDGE_MODEL},
            "summaryJa": "", "marketRiskJa": "", "labels": [],
            "globalRedFlags": [], "groundingSources": []}

def _execute_ai_judgment(run_mode="manual"):
    """Run a fresh AI judgment (GPT-5.5 primary + Gemini double-check), arbitrate,
    cache, return. Never raises. The security gate / run limits are enforced by
    the caller (POST route) — this function performs the actual model work."""
    snap, al = _build_ai_snapshot()
    openai_out, oai_status = _openai_judge(snap)
    gemini_out, gem_status, grounding_enabled = _gemini_check(snap, openai_out)
    labels = _arbitrate_ai(al, openai_out, gemini_out)

    ai_ok = (1 if oai_status == "live" else 0) + (1 if gem_status == "live" else 0)
    if al.get("status") == "mock":
        status = "mock"
    elif ai_ok == 2:
        status = "live"
    else:
        status = "partial"

    summary = (openai_out.get("summaryJa") if isinstance(openai_out, dict) else "") or \
              (al.get("marketPosture", {}) or {}).get("rationaleJa", "")
    market_risk = (openai_out.get("marketRiskJa") if isinstance(openai_out, dict) else "") or ""
    global_flags, grounding = [], []
    if isinstance(gemini_out, dict):
        global_flags = [str(x)[:120] for x in (gemini_out.get("globalRedFlags") or [])][:5]
        grounding = [{"title": str(g.get("title", ""))[:160], "url": str(g.get("url", ""))[:300]}
                     for g in (gemini_out.get("groundingSources") or []) if isinstance(g, dict)][:5]

    payload = {
        "status": status, "asOf": _ai_now_iso(), "engineVersion": "ai-judge-v1", "runMode": run_mode,
        "models": {"primary": (_OPENAI_MODEL if oai_status == "live" else None),
                   "checker": (_GEMINI_JUDGE_MODEL if gem_status == "live" else None)},
        "summaryJa": summary[:400], "marketRiskJa": market_risk[:400], "labels": labels,
        "globalRedFlags": global_flags, "groundingSources": grounding,
    }
    if status != "mock":
        _AI_RESULT_CACHE["data"] = payload
        _AI_RESULT_CACHE["expires"] = time.time() + _AI_CACHE_TTL
    add_log(f"[AI] run mode={run_mode} models={_OPENAI_MODEL}/{_GEMINI_JUDGE_MODEL} symbols={len(labels)} "
            f"oai={oai_status} gem={gem_status} grounding={grounding_enabled} status={status}")
    return payload

# ━━━ Security Gate v1 (protects future expensive AI runs) ━━━
def _client_meta():
    """Best-effort client metadata from common proxy headers. No secrets."""
    h = request.headers
    fwd = (h.get("X-Forwarded-For", "").split(",")[0] or "").strip()
    return {
        "ip": h.get("CF-Connecting-IP") or fwd or (request.remote_addr or ""),
        "country": (h.get("CF-IPCountry") or "").upper(),
        "userAgent": (h.get("User-Agent") or "")[:160],
    }

def _is_locked():
    return _AI_JUDGE_LOCKED_ENV or _AI_GATE_STATE["softLocked"]

def send_security_alert(event):
    """Phase-1 security alert: structured log only (never fails the app, never
    logs the admin token). Phase-2 (documented, not built): wire Resend/SendGrid
    using SECURITY_ALERT_* with subject/timestamp/IP/country/user-agent and
    signed "It was me / It was not me" action links."""
    try:
        meta = event.get("meta", {})
        add_log(f"[SECURITY] {event.get('type', 'event')} ip={meta.get('ip', '')} "
                f"country={meta.get('country', '')} ua={(meta.get('userAgent', '') or '')[:60]} "
                f"failed={_AI_GATE_STATE['failedAttempts']} locked={_is_locked()}")
        if _SECURITY_ALERT_EMAIL and not _SECURITY_ALERT_PROVIDER:
            add_log("[SECURITY] SECURITY_ALERT_EMAIL set but no SECURITY_ALERT_PROVIDER (no-op in v1)")
    except Exception:
        pass

def _require_admin():
    """(authorized, error_payload, http_code). 503 if token unconfigured; 401 if
    missing/wrong (tracks failed attempts → soft lock). Never logs the token."""
    if not _ARGUS_ADMIN_TOKEN:
        return False, {"error": "admin_unconfigured",
                       "message": "Admin token is not configured on the server."}, 503
    token = request.headers.get("X-ARGUS-ADMIN-TOKEN", "")
    if not token or token != _ARGUS_ADMIN_TOKEN:
        with _AI_LOCK:
            _AI_GATE_STATE["failedAttempts"] += 1
            if _AI_GATE_STATE["failedAttempts"] >= _FAILED_ATTEMPTS_LOCK_THRESHOLD:
                _AI_GATE_STATE["softLocked"] = True
        send_security_alert({"type": "admin_auth_failed", "meta": _client_meta()})
        return False, {"error": "unauthorized"}, 401
    return True, None, 200

def _ai_run_gate():
    """(allowed, payload, http_code). Validates enabled/locked/country/interval/
    daily-limit. Records the run when allowed. In-memory ledger (resets on dyno
    restart — move to persistent storage if durable limits are needed)."""
    now = time.time()
    meta = _client_meta()
    if not _AI_JUDGE_ENABLED:
        return False, {"status": "disabled", "reason": "AI judgment is not enabled yet.",
                       "asOf": _ai_now_iso(), "locked": _is_locked()}, 200
    if _is_locked():
        send_security_alert({"type": "run_blocked_locked", "meta": meta})
        return False, {"status": "locked", "reason": "AI run gate is locked.",
                       "locked": True, "asOf": _ai_now_iso()}, 403
    if _AI_JUDGE_ALLOW_COUNTRIES and meta["country"] and meta["country"] not in _AI_JUDGE_ALLOW_COUNTRIES:
        send_security_alert({"type": "run_blocked_country", "meta": meta})
        return False, {"status": "blocked", "reason": f"country {meta['country']} not in allow list.",
                       "asOf": _ai_now_iso()}, 403
    with _AI_LOCK:
        today = datetime.now(TZ_JST).strftime("%Y-%m-%d")
        if _AI_GATE_STATE["date"] != today:
            _AI_GATE_STATE["date"] = today
            _AI_GATE_STATE["count"] = 0
        last = _AI_GATE_STATE["lastRunTs"]
        if last and (now - last) < _AI_JUDGE_MIN_INTERVAL * 60:
            wait_m = int((_AI_JUDGE_MIN_INTERVAL * 60 - (now - last)) // 60) + 1
            return False, {"status": "rate_limited",
                           "reason": f"min interval {_AI_JUDGE_MIN_INTERVAL}m; retry in ~{wait_m}m",
                           "runCountToday": _AI_GATE_STATE["count"], "asOf": _ai_now_iso()}, 429
        if _AI_GATE_STATE["count"] >= _AI_JUDGE_MAX_RUNS:
            return False, {"status": "rate_limited",
                           "reason": f"daily limit {_AI_JUDGE_MAX_RUNS} reached",
                           "runCountToday": _AI_GATE_STATE["count"], "asOf": _ai_now_iso()}, 429
        _AI_GATE_STATE["count"] += 1
        _AI_GATE_STATE["lastRunTs"] = now
        _AI_GATE_STATE["failedAttempts"] = 0
        count = _AI_GATE_STATE["count"]
    return True, {"runCountToday": count}, 200

@app.route("/api/argus/ai-judgment")
def api_argus_ai_judgment():
    # Public + frontend-safe. Reads the cached judgment ONLY — never calls a model.
    if not _AI_JUDGE_ENABLED:
        return jsonify(_ai_disabled_payload("disabled", "AI judgment is not enabled yet."))
    cached = _AI_RESULT_CACHE["data"]
    if cached and time.time() < _AI_RESULT_CACHE["expires"]:
        return jsonify({**cached, "runMode": "cached"})
    return jsonify(_ai_disabled_payload("no_cached_result",
                                        "No cached AI judgment yet — an admin-triggered run is required."))

@app.route("/api/argus/ai-judgment/run", methods=["POST"])
def api_argus_ai_judgment_run():
    # Admin-gated fresh run: GPT-5.5 primary + Gemini double-check. NEVER reachable
    # from the public frontend (admin token required).
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    allowed, info, code = _ai_run_gate()
    if not allowed:
        return jsonify(info), code
    return jsonify(_execute_ai_judgment(run_mode="manual"))

@app.route("/api/argus/security-status")
def api_argus_security_status():
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    with _AI_LOCK:
        today = datetime.now(TZ_JST).strftime("%Y-%m-%d")
        count = _AI_GATE_STATE["count"] if _AI_GATE_STATE["date"] == today else 0
        return jsonify({
            "asOf": _ai_now_iso(), "locked": _is_locked(), "lockedByEnv": _AI_JUDGE_LOCKED_ENV,
            "softLocked": _AI_GATE_STATE["softLocked"], "failedAttempts": _AI_GATE_STATE["failedAttempts"],
            "allowedCountries": _AI_JUDGE_ALLOW_COUNTRIES, "runCountToday": count,
            "minIntervalMinutes": _AI_JUDGE_MIN_INTERVAL, "dailyLimit": _AI_JUDGE_MAX_RUNS,
            "aiJudgeEnabled": _AI_JUDGE_ENABLED, "alertEmailConfigured": bool(_SECURITY_ALERT_EMAIL),
        })

@app.route("/api/argus/security-unlock", methods=["POST"])
def api_argus_security_unlock():
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    with _AI_LOCK:
        _AI_GATE_STATE["softLocked"] = False
        _AI_GATE_STATE["failedAttempts"] = 0
    send_security_alert({"type": "security_unlocked", "meta": _client_meta()})
    return jsonify({"status": "unlocked", "softLocked": False, "failedAttempts": 0,
                    "lockedByEnv": _AI_JUDGE_LOCKED_ENV, "locked": _is_locked(), "asOf": _ai_now_iso()})


# ━━━ GPT-5.5 Pro Handoff Export (manual review — NO API call, NO cost) ━━━
_PRO_HANDOFF_CACHE = {"data": None, "expires": 0.0}
_PRO_HANDOFF_TTL   = 180  # 3 min

def _compose_pro_prompt(rates, jp, us, ev, al, cat=None, aij_status="disabled"):
    now_jst = datetime.now(TZ_JST)
    L = []
    L.append("# A.R.G.U.S. — GPT-5.5 Pro Handoff")
    L.append("You are GPT-5.5 Pro acting as a second-opinion investment decision reviewer for ARGUS.")
    L.append("")

    # ── 1. Product Identity (static constitution) ──
    L.append("## 1. Product Identity")
    L.append("- A.R.G.U.S. = Autonomous Risk and Global Uncertainty Scanner.")
    L.append("- A personal action-decision engine for daily investing. NOT a chart app. NOT a prediction engine.")
    L.append("- A calm investment command center that classifies CURRENT market conditions into action categories.")
    L.append("- It answers: today's call, the risk, the reason, what to touch, what to avoid, what to wait for, and what would change the posture.")
    L.append("")

    # ── 2. Design / Interpretation Rules (static) ──
    L.append("## 2. Design / Interpretation Rules")
    L.append("- Market visuals are supporting evidence, not the primary experience.")
    L.append("- Intentional bilingual: English chrome + Japanese reasoning.")
    L.append("- Calm Bloomberg Terminal + Linear + Raycast + Stripe Dashboard direction. No HUD / cyberpunk / neon / fake terminal styling.")
    L.append("- Tactical action labels: EXIT / TRIM / WAIT / WAIT FOR PULLBACK / BUY DIP / ADD / HOLD.")
    L.append("- Core (long-term index) labels: CONTINUE / GRADUAL ADD / DEFER LUMP SUM / NO SELL ACTION.")
    L.append("")

    # ── 3. Current Live State (generated from backend snapshots) ──
    L.append("## 3. Current Live State")
    L.append(f"- asOf: {now_jst.strftime('%Y-%m-%d %H:%M')} JST (Asia/Tokyo)")
    def _st(x):
        return x.get("status", "unavailable") if isinstance(x, dict) else "unavailable"
    L.append("- Source statuses: "
             f"rates={_st(rates)}, japanWatchlist={_st(jp)}, usWatchlist={_st(us)}, events={_st(ev)}, "
             f"actionLabels={_st(al)}, catalysts={_st(cat) if isinstance(cat, dict) else 'unavailable'}, "
             f"proHandoff=live, aiJudgment={aij_status}")
    if isinstance(rates, dict):
        def _rv(k):
            d = rates.get(k) or {}
            return f"{d.get('latestValue')} ({d.get('latestDate', '')})"
        L.append("### Rates / VIX")
        L.append(f"- US10Y {_rv('us10y')} | US2Y {_rv('us2y')} | Real10Y {_rv('usReal10y')} | VIX {_rv('vix')}")
        L.append(f"- ratesPressure={rates.get('ratesPressure')} | riskVolatility={rates.get('riskVolatility')} | status={rates.get('status')}")
    if isinstance(ev, dict):
        L.append("### Event Radar (urgent first)")
        order = {"D": 0, "D-1": 1, "D-3": 2, "D-7": 3, "D+1": 4, "normal": 5}
        evs = sorted(ev.get("events", []), key=lambda e: (order.get(e.get("escalation"), 9), e.get("daysUntil", 999)))
        for e in evs[:14]:
            when = e.get("localTimeJst") or e.get("eventDate") or ""
            assets = ",".join(e.get("linkedAssets", []) or [])
            L.append(f"- [{e.get('escalation')}] {e.get('title')} | {e.get('country')}/{e.get('category')} | {when} | "
                     f"impact={e.get('impact')} | assets:{assets} | {e.get('source')}({e.get('status')}) | {e.get('rationaleJa', '')}")
    def _wl(snap, label):
        if not isinstance(snap, dict):
            return
        L.append(f"### {label} (status={snap.get('status')}{', asOf ' + snap['asOf'] if snap.get('asOf') else ''})")
        for s in snap.get("stocks", []):
            L.append(f"- {s.get('symbol')} {s.get('name')}: {s.get('price')} ({s.get('changePct')}%) "
                     f"vol={s.get('volume')} {s.get('date') or ''} [{s.get('status')}]")
    _wl(jp, "Japan Watchlist")
    _wl(us, "US Watchlist")
    if isinstance(al, dict):
        mp = al.get("marketPosture", {}) or {}
        L.append(f"### Action Label Engine ({al.get('engineVersion', 'action-v0')}, status={al.get('status')}) — "
                 f"marketPosture: {mp.get('label')} ({mp.get('rationaleJa', '')})")
        for l in al.get("labels", []):
            sd = l.get("supportingData", {}) or {}
            L.append(f"- {l.get('symbol')} [{l.get('market')}]: ruleAction={l.get('action')} risk={l.get('risk')} "
                     f"conf={l.get('confidence')} | chg={sd.get('changePct')}% ev={sd.get('eventEscalation')} "
                     f"rates={sd.get('ratesPosture')} | {l.get('reasonJa', '')} | next: {l.get('nextConditionJa', '')}")
    if isinstance(cat, dict):
        L.append(f"### Corporate Catalysts ({cat.get('engineVersion', 'catalyst-v1')}, status={cat.get('status')})")
        L.append("- Sources: " + ", ".join(f"{s.get('name')}={s.get('status')}" for s in cat.get("sources", [])))
        for it in cat.get("items", []):
            e = it.get("earnings", {}) or {}
            parts = [f"risk={it.get('catalystRisk')}", f"impact={it.get('actionImpact')}"]
            if e.get("date"):
                parts.append(f"earnings {e.get('date')} (D-{e.get('daysUntil')})")
            if it.get("filings"):
                f0 = it["filings"][0]
                parts.append(f"recent {f0.get('form')} {f0.get('filingDate')} ({f0.get('url', '')}) +{len(it['filings'])} filings")
            if it.get("news"):
                parts.append(f"news {len(it['news'])} (7d)")
            for d in it.get("disclosures", []):
                if d.get("status") == "live":
                    parts.append(f"disclosure {d.get('type')} {d.get('date')}")
            L.append(f"- {it.get('symbol')} [{it.get('market')}]: " + " | ".join(parts) + f" | {it.get('summaryJa', '')}")
            if it.get("news"):
                n0 = it["news"][0]
                L.append(f"    news: {n0.get('headline', '')} — {n0.get('publisher', '')} {n0.get('url', '')}")
    L.append("")

    # ── 4. Current AI State (explicit) ──
    L.append("## 4. Current AI State")
    L.append("- The action labels above are RULE-BASED (Action Label Engine v0). They are NOT generated by GPT or Gemini.")
    L.append(f"- Automated OpenAI/Gemini judgment is {'LIVE' if aij_status == 'live' else 'PENDING / DISABLED'} (/api/argus/ai-judgment status={aij_status}).")
    L.append("- This Pro Handoff does NOT call OpenAI or Gemini and costs nothing.")
    L.append("- The user manually pastes this prompt into ChatGPT GPT-5.5 Pro for a high-stakes second opinion.")
    L.append("")

    # ── 5. Data Limitations (true current limitations) ──
    L.append("## 5. Data Limitations")
    if aij_status != "live":
        L.append("- No automatic OpenAI/Gemini AI judgment yet (currently disabled/pending).")
    L.append("- No moomoo order flow / order book / tape yet. No VWAP (no real source).")
    if isinstance(cat, dict):
        L.append("- Catalysts are metadata only (SEC filing metadata + Finnhub earnings/news + J-Quants disclosure dates) — NO filing-text/article-body analysis; JP earnings calendar covers ~next business day; TDnet add-on pending.")
        L.append("- No earnings interpretation (actual vs consensus) yet.")
    else:
        L.append("- No corporate catalyst layer / earnings interpretation yet.")
    L.append("- Market Regime is not live-scored yet (mock). Alerts scanner is not live yet (mock).")
    L.append("- No historical judgment log and no user-specific exposure weighting yet.")
    L.append("- Today/CommandCenter compact previews may still use seed data.")
    L.append("- Action Label Engine v0 is conservative and does NOT output EXIT/TRIM/ADD/BUY DIP (only HOLD/WAIT/WAIT FOR PULLBACK) until later upgraded.")
    L.append("")

    # ── 6. GPT-5.5 Pro Review Task ──
    L.append("## 6. GPT-5.5 Pro Review Task")
    L.append("Produce, using this exact structure:")
    L.append("- Executive Judgment")
    L.append("- Today's Action Map (what to touch / avoid / wait for)")
    L.append("- Symbol Review (confirm / caution / disagree with each ARGUS rule label)")
    L.append("- Event/Rates Risk")
    L.append("- What Changes the Decision")
    L.append("- Data Limitations")
    L.append("- Final Command (concise command-center summary)")
    L.append("")
    L.append("Instructions:")
    L.append("- Reason in Japanese; keep action labels in English.")
    L.append("- Do NOT fabricate news, VWAP, flow, order book, analyst ratings, or any unprovided data.")
    L.append("- Do NOT treat this as certain financial advice — it is decision support.")
    L.append("- Review whether ARGUS rule labels are too aggressive, too conservative, or appropriate.")
    L.append("- When in doubt, downgrade to WAIT/HOLD.")
    L.append("- Clearly separate what is supported by the current data, what is inference, and what is missing.")
    return "\n".join(L)

def _build_pro_handoff():
    rates = get_rates_snapshot(); jp = get_japan_watchlist_snapshot()
    us = get_us_watchlist_snapshot(); ev = get_events_snapshot(); al = get_action_labels()
    cat = get_catalysts_snapshot()
    def _st(x): return x.get("status", "mock") if isinstance(x, dict) else "mock"
    # Automated AI judgment is pending/disabled (the /api/argus/ai-judgment GET
    # returns disabled); reflect that truthfully without affecting data status.
    aij_status = "live" if _AI_JUDGE_ENABLED else "disabled"
    src = {"rates": _st(rates), "japanWatchlist": _st(jp), "usWatchlist": _st(us),
           "events": _st(ev), "actionLabels": _st(al), "catalysts": _st(cat)}
    warnings = [f"{k} is {v}" for k, v in src.items() if v != "live"]
    prompt = _compose_pro_prompt(rates, jp, us, ev, al, cat, aij_status)
    live_n = sum(1 for v in src.values() if v == "live")
    status = "live" if live_n == len(src) else ("partial" if live_n > 0 else "mock")
    source_statuses = {**src, "proHandoff": "live", "aiJudgment": aij_status}
    return {"status": status, "asOf": _ai_now_iso(), "engineVersion": "pro-handoff-v1",
            "title": "ARGUS GPT-5.5 Pro Handoff", "promptText": prompt, "charCount": len(prompt),
            "sourceStatuses": source_statuses, "warnings": warnings}

@app.route("/api/argus/pro-handoff")
def api_argus_pro_handoff():
    # Frontend-safe: aggregates cached snapshots into a copy-paste prompt. No
    # admin token, no secrets, no OpenAI/Gemini call. Short cache (3 min).
    now = time.time()
    if _PRO_HANDOFF_CACHE["data"] and now < _PRO_HANDOFF_CACHE["expires"]:
        return jsonify(_PRO_HANDOFF_CACHE["data"])
    payload = _build_pro_handoff()
    _PRO_HANDOFF_CACHE["data"] = payload
    _PRO_HANDOFF_CACHE["expires"] = now + _PRO_HANDOFF_TTL
    return jsonify(payload)


# ━━━ Corporate Catalyst Layer v1 ━━━
# Company-specific catalysts behind watchlist moves: US filings (SEC EDGAR,
# keyless), US earnings + news (Finnhub, key optional), JP earnings + financial
# disclosure (J-Quants V2). No filing-text scraping, no long article bodies, no
# fabrication — sources degrade to unavailable/partial honestly. TDnet is a
# pending optional add-on. Cached to avoid provider abuse.
_SEC_CIK = {"NVDA": "0001045810", "AAPL": "0000320193", "TSLA": "0001318605", "META": "0001326801"}
_SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "") or "ARGUS/1.0 contact@example.com"
_SEC_FORMS = {"8-K", "10-Q", "10-K"}
_CAT_HORIZON_DAYS = 90
_JQUANTS_TDNET_ENABLED = os.environ.get("JQUANTS_TDNET_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")

_US_CAT_SYMBOLS = [("NVDA", "NVIDIA"), ("AAPL", "Apple"), ("TSLA", "Tesla"), ("META", "Meta Platforms")]
_JP_CAT_SYMBOLS = [("8058", "三菱商事"), ("9984", "ソフトバンクグループ"),
                   ("5801", "古河電気工業"), ("5803", "フジクラ"), ("6584", "三櫻工業"),
                   ("285A", "キオクシアホールディングス"), ("9501", "東京電力ホールディングス")]

_SEC_CACHE  = {}                                   # symbol -> {data, expires}
_FINN_CACHE = {}                                   # symbol -> {data, expires}
_JQ_CAT_CACHE = {"data": None, "expires": 0.0}
_CAT_CACHE  = {"data": None, "expires": 0.0}       # assembled snapshot, 30 min

def _sec_filings(symbol):
    cik = _SEC_CIK.get(symbol)
    if not cik:
        return [], "unavailable"
    c = _SEC_CACHE.get(symbol)
    if c and time.time() < c["expires"]:
        return c["data"], "live"
    try:
        r = requests.get(f"https://data.sec.gov/submissions/CIK{cik}.json",
                         headers={"User-Agent": _SEC_USER_AGENT, "Accept-Encoding": "gzip"}, timeout=12)
        r.raise_for_status()
        rec = r.json().get("filings", {}).get("recent", {})
        forms = rec.get("form", []); dates = rec.get("filingDate", [])
        accs = rec.get("accessionNumber", []); docs = rec.get("primaryDocument", [])
        out = []
        for i in range(len(forms)):
            if forms[i] not in _SEC_FORMS:
                continue
            acc = accs[i] if i < len(accs) else ""
            doc = docs[i] if i < len(docs) else ""
            url = (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{doc}"
                   if acc and doc else f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}")
            out.append({"source": "SEC EDGAR", "form": forms[i], "filingDate": dates[i] if i < len(dates) else None,
                        "accessionNumber": acc, "url": url, "status": "live"})
            if len(out) >= 5:
                break
        _SEC_CACHE[symbol] = {"data": out, "expires": time.time() + 6 * 3600}
        return out, "live"
    except Exception:
        return [], "error"

def _finnhub_catalyst(symbol):
    if not FINNHUB_API_KEY:
        return {"earnings": None, "news": []}, "unavailable"
    c = _FINN_CACHE.get(symbol)
    if c and time.time() < c["expires"]:
        return c["data"], "live"
    earnings, news = None, []
    got = False
    try:
        today = datetime.now(pytz.utc).date()
        ec = finnhub_get("calendar/earnings",
                         {"from": today.isoformat(), "to": (today + timedelta(days=_CAT_HORIZON_DAYS)).isoformat(),
                          "symbol": symbol})
        cal = (ec or {}).get("earningsCalendar", []) if isinstance(ec, dict) else []
        cal = [e for e in cal if e.get("date")]
        if cal:
            e = sorted(cal, key=lambda x: x["date"])[0]
            earnings = {"date": e.get("date"), "epsEstimate": e.get("epsEstimate"),
                        "revenueEstimate": e.get("revenueEstimate"), "epsActual": e.get("epsActual"),
                        "revenueActual": e.get("revenueActual")}
        got = True
    except Exception:
        pass
    try:
        u = datetime.now(pytz.utc).date()
        nws = finnhub_get("company-news", {"symbol": symbol,
                          "from": (u - timedelta(days=7)).isoformat(), "to": u.isoformat()})
        for a in (nws or [])[:6]:
            ts = a.get("datetime")
            iso = datetime.fromtimestamp(ts, pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if ts else None
            news.append({"source": "Finnhub", "headline": (a.get("headline", "") or "")[:200],
                         "publisher": a.get("source", ""), "publishedAt": iso, "url": a.get("url", ""),
                         "status": "live"})
        got = True
    except Exception:
        pass
    if not got:
        return {"earnings": None, "news": []}, "error"
    data = {"earnings": earnings, "news": news}
    _FINN_CACHE[symbol] = {"data": data, "expires": time.time() + 2700}  # 45 min
    return data, "live"

def _jquants_catalysts():
    if _JQ_CAT_CACHE["data"] is not None and time.time() < _JQ_CAT_CACHE["expires"]:
        return _JQ_CAT_CACHE["data"], "live"
    if not _JQUANTS_API_KEY:
        return {"nextEarn": {}, "details": {}}, "unavailable"
    headers = {"x-api-key": _JQUANTS_API_KEY}
    next_earn, details = {}, {}
    any_ok = False
    try:  # next-business-day earnings announcements (whole list, match our codes)
        r = requests.get(f"{_JQUANTS_BASE}/equities/earnings-calendar", headers=headers, timeout=10)
        if r.status_code == 200:
            for row in r.json().get("data", []):
                code4 = str(row.get("Code", ""))[:4]
                if row.get("Date") and code4:
                    next_earn[code4] = row["Date"]
            any_ok = True
    except Exception:
        pass
    for sym, _ in _JP_CAT_SYMBOLS:  # latest disclosed financials (DisclosedDate)
        try:
            r = requests.get(f"{_JQUANTS_BASE}/fins/details", headers=headers, params={"code": sym}, timeout=10)
            if r.status_code == 200:
                body = r.json()
                rows = body.get("data") or body.get("details") or body.get("fins_details") or []
                rows = [x for x in rows if isinstance(x, dict) and x.get("DisclosedDate")]
                if rows:
                    latest = sorted(rows, key=lambda x: x["DisclosedDate"])[-1]
                    details[sym] = {"date": latest.get("DisclosedDate"),
                                    "type": latest.get("TypeOfDocument", "") or "financial_summary"}
                    any_ok = True
        except Exception:
            pass
    data = {"nextEarn": next_earn, "details": details}
    _JQ_CAT_CACHE["data"] = data
    _JQ_CAT_CACHE["expires"] = time.time() + 6 * 3600
    return data, ("live" if any_ok else "unavailable")

def _days_until(date_str, today):
    try:
        return (datetime.strptime(date_str[:10], "%Y-%m-%d").date() - today).days
    except Exception:
        return None

def _catalyst_assess(earnings_days, recent_filing_days, news_24h, jp_disc_days):
    # Conservative priority: earnings > material filing > news spike > JP disclosure.
    if earnings_days is not None and 0 <= earnings_days <= 3:
        return "high", "wait_for_event"
    if earnings_days is not None and 0 <= earnings_days <= 7:
        return "medium", "wait_for_event"
    if recent_filing_days is not None and 0 <= recent_filing_days <= 3:
        return "medium", "caution"
    if news_24h >= 3:
        return "medium", "caution"
    if jp_disc_days is not None and 0 <= jp_disc_days <= 7:
        return "medium", "post_event_review"
    return "low", "none"

def get_catalysts_snapshot():
    if _CAT_CACHE["data"] is not None and time.time() < _CAT_CACHE["expires"]:
        return _CAT_CACHE["data"]
    today = datetime.now(TZ_JST).date()
    sec_statuses, finn_statuses = [], []
    items = []

    # US — SEC filings + Finnhub earnings/news
    for sym, name in _US_CAT_SYMBOLS:
        filings, sec_st = _sec_filings(sym); sec_statuses.append(sec_st)
        fdata, finn_st = _finnhub_catalyst(sym); finn_statuses.append(finn_st)
        earnings = fdata.get("earnings")
        news = fdata.get("news", [])
        e_days = _days_until(earnings["date"], today) if earnings and earnings.get("date") else None
        recent_filing_days = None
        for f in filings:
            if f.get("form") in ("8-K", "10-Q", "10-K") and f.get("filingDate"):
                d = (today - datetime.strptime(f["filingDate"], "%Y-%m-%d").date()).days
                if d >= 0 and (recent_filing_days is None or d < recent_filing_days):
                    recent_filing_days = d
        n24 = 0
        for n in news:
            if n.get("publishedAt"):
                try:
                    age = (datetime.now(pytz.utc) - datetime.strptime(n["publishedAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.utc)).total_seconds()
                    if age <= 86400:
                        n24 += 1
                except Exception:
                    pass
        risk, impact = _catalyst_assess(e_days, recent_filing_days, n24, None)
        bits = []
        if e_days is not None:
            bits.append(f"決算まで{e_days}日")
        if recent_filing_days is not None and recent_filing_days <= 3:
            bits.append("直近の重要開示(8-K等)あり")
        if n24 >= 3:
            bits.append(f"24h以内のニュース{n24}件")
        summary = "、".join(bits) if bits else "目立つ銘柄固有イベントなし"
        rationale = {
            "wait_for_event": "決算など重要イベント前のため、イベント通過まで新規の追いかけを避ける。",
            "caution": "銘柄固有の材料が出ており、過度な追いかけを避け値動きを確認する。",
            "post_event_review": "直近の開示後のため、織り込みと反応を確認してから判断する。",
            "none": "銘柄固有の触媒は乏しく、相場全体の地合いに従う。",
        }[impact]
        item_status = "live" if (sec_st == "live" or finn_st == "live") else "partial"
        items.append({
            "symbol": sym, "market": "US", "name": name, "catalystRisk": risk, "summaryJa": summary,
            "earnings": {"status": "live" if earnings else ("unavailable" if finn_st != "live" else "live"),
                         "date": (earnings or {}).get("date"), "daysUntil": e_days if e_days is not None else 0,
                         "epsEstimate": (earnings or {}).get("epsEstimate"),
                         "revenueEstimate": (earnings or {}).get("revenueEstimate")},
            "filings": filings, "news": news, "disclosures": [],
            "rationaleJa": rationale, "actionImpact": impact, "status": item_status,
        })

    # JP — J-Quants earnings calendar + financial disclosure
    jq, jq_st = _jquants_catalysts()
    for sym, name in _JP_CAT_SYMBOLS:
        e_date = jq.get("nextEarn", {}).get(sym)
        e_days = _days_until(e_date, today) if e_date else None
        disc = jq.get("details", {}).get(sym)
        disc_days = _days_until(disc["date"], today) if disc and disc.get("date") else None
        disclosures = []
        if disc:
            disclosures.append({"source": "J-Quants", "type": "financial_summary",
                                "date": disc.get("date"), "title": disc.get("type", "financial summary"),
                                "status": "live"})
        if _JQUANTS_TDNET_ENABLED is False:
            disclosures.append({"source": "J-Quants", "type": "tdnet_pending", "date": None,
                                "title": "TDnet add-on pending", "status": "pending_addon"})
        risk, impact = _catalyst_assess(e_days, None, 0, disc_days)
        bits = []
        if e_days is not None:
            bits.append(f"決算発表まで{e_days}日")
        if disc_days is not None and disc_days <= 7:
            bits.append("直近の財務開示あり")
        summary = "、".join(bits) if bits else "目立つ銘柄固有イベントなし"
        rationale = {
            "wait_for_event": "決算発表が近いため、発表通過まで新規の追いかけを避ける。",
            "caution": "銘柄固有の材料があり、過度な追いかけを避ける。",
            "post_event_review": "直近の開示後のため、内容と市場の反応を確認してから判断する。",
            "none": "銘柄固有の触媒は乏しく、相場全体の地合いに従う。",
        }[impact]
        items.append({
            "symbol": sym, "market": "JP", "name": name, "catalystRisk": risk, "summaryJa": summary,
            "earnings": {"status": "live" if e_date else "unavailable", "date": e_date,
                         "daysUntil": e_days if e_days is not None else 0,
                         "epsEstimate": None, "revenueEstimate": None},
            "filings": [], "news": [], "disclosures": disclosures,
            "rationaleJa": rationale, "actionImpact": impact,
            "status": "live" if jq_st == "live" else "partial",
        })

    sec_overall = "live" if "live" in sec_statuses else ("error" if "error" in sec_statuses else "unavailable")
    finn_overall = ("live" if "live" in finn_statuses else
                    ("error" if "error" in finn_statuses else "unavailable"))
    live_sources = sum(1 for s in (sec_overall, finn_overall, jq_st) if s == "live")
    status = "live" if live_sources == 3 else ("partial" if live_sources >= 1 else "mock")
    now_iso = _ai_now_iso()
    snapshot = {
        "status": status, "asOf": now_iso, "engineVersion": "catalyst-v1", "horizonDays": _CAT_HORIZON_DAYS,
        "sources": [
            {"name": "SEC EDGAR", "status": sec_overall, "lastUpdated": now_iso if sec_overall == "live" else None},
            {"name": "Finnhub", "status": finn_overall, "lastUpdated": now_iso if finn_overall == "live" else None},
            {"name": "J-Quants", "status": jq_st, "lastUpdated": now_iso if jq_st == "live" else None},
            {"name": "TDnet Add-on", "status": "pending_addon"},
        ],
        "items": items,
    }
    _CAT_CACHE["data"] = snapshot
    _CAT_CACHE["expires"] = time.time() + 1800  # 30 min assembly cache
    return snapshot

@app.route("/api/argus/catalysts")
def api_argus_catalysts():
    return jsonify(get_catalysts_snapshot())


# ━━━ Scheduler ━━━
def is_us_trading_day():
    return datetime.now(TZ_ET).weekday() < 5

def scheduled_run_all():
    global SCHEDULED_RUN
    if not is_us_trading_day(): add_log("⏭️ Weekend"); return
    SCHEDULED_RUN = True
    try: phase1_broad_scan(); phase2_rescore(); phase3_crosscheck(); phase4_final_top3()
    finally: SCHEDULED_RUN = False

def scheduled_ph5():
    global SCHEDULED_RUN
    if not is_us_trading_day(): return
    SCHEDULED_RUN = True
    try: phase5_post_open()
    finally: SCHEDULED_RUN = False

def run_scheduler():
    add_log("⏰ Scheduler started (DST auto-detect)")
    sched = get_jst_schedule()
    add_log(f"  DST:{'Summer' if is_dst_now() else 'Winter'} Ph.1:{sched['ph1']} Ph.5:{sched['ph5_1']} JST")
    ran_today = set()
    while True:
        now = datetime.now(TZ_JST); today_str = now.strftime("%Y-%m-%d"); hhmm = now.strftime("%H:%M")
        sched = get_jst_schedule()
        if not any(k.startswith(today_str) for k in ran_today): ran_today = set()
        key = f"{today_str}_{hhmm}"
        if hhmm == sched["ph1"] and key not in ran_today:
            ran_today.add(key); add_log(f"🚀 Scheduled Ph.1-4 ({hhmm} JST)")
            threading.Thread(target=scheduled_run_all, daemon=True).start()
        elif hhmm == sched["ph5_1"] and key not in ran_today:
            ran_today.add(key); add_log(f"🚀 Scheduled Ph.5 ({hhmm} JST)")
            threading.Thread(target=scheduled_ph5, daemon=True).start()
        elif hhmm == sched["ph5_2"] and key not in ran_today:
            ran_today.add(key); add_log(f"🚀 Scheduled Ph.5 re-run ({hhmm} JST)")
            threading.Thread(target=scheduled_ph5, daemon=True).start()
        time.sleep(30)

if __name__ == "__main__":
    sched = get_jst_schedule()
    add_log(f"🚀 A.R.G.U.S. backend v2.0 ({'Summer DST' if is_dst_now() else 'Winter'})")
    add_log(f"  Ph.1:{sched['ph1']} Ph.5:{sched['ph5_1']} JST")
    if MOOMOO_AVAILABLE: add_log(f"  moomoo: {MOOMOO_HOST}:{MOOMOO_PORT}")
    else: add_log("  ⚠️ moomoo-api not installed")
    threading.Thread(target=run_scheduler, daemon=True).start()
    add_log("🟢 Boot complete — IDLING")
    add_log("💡 Ph.1 to start / Auto: daily per schedule")
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
