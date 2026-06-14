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

# ── Per-IP rate limit (v9.10) ────────────────────────────────────────
# The /api/argus/* endpoints are public; a hostile loop could drain the
# Twelve Data daily credits (dynamic ?symbols= sets) or hammer J-Quants.
# Simple in-memory sliding window per IP: generous for the SPA (~10 calls
# per page load), stricter for "heavy" requests that can bust caches via
# query params. OPTIONS (CORS preflight) is never limited.
_RL_LOCK    = threading.Lock()
_RL_BUCKETS = {}          # ip -> deque[timestamps]
_RL_WINDOW  = 60.0        # seconds
_RL_MAX     = 120         # default requests / IP / minute
# Heavy (cache-busting) budget: was 30/min pre-15s-polling. Legit usage is now
# ~10-12/min PER DEVICE (jp+us watchlist every 15s + action-labels) and one
# home IP often runs phone+Mac+preview simultaneously — 30 made the app
# rate-limit ITSELF (observed 2026-06-13). 90 keeps 3 devices + scout taps
# comfortable while still bounding abuse (all heavy endpoints are cached).
_RL_MAX_HEAVY = 90
_RL_MAX_IPS = 5000        # memory bound on a public endpoint

def _rl_client_ip():
    fwd = (request.headers.get("X-Forwarded-For", "").split(",")[0] or "").strip()
    return request.headers.get("CF-Connecting-IP") or fwd or (request.remote_addr or "?")

@app.before_request
def _rate_limit():
    p = request.path
    if not p.startswith("/api/argus/") or request.method == "OPTIONS":
        return None
    heavy = ("symbol-search" in p) or any(k in request.args for k in ("symbols", "jp", "us", "ids", "q", "symbol"))
    limit = _RL_MAX_HEAVY if heavy else _RL_MAX
    now = time.time()
    ip = _rl_client_ip()
    with _RL_LOCK:
        if len(_RL_BUCKETS) > _RL_MAX_IPS:
            _RL_BUCKETS.clear()
        dq = _RL_BUCKETS.setdefault(ip, deque())
        while dq and now - dq[0] > _RL_WINDOW:
            dq.popleft()
        if len(dq) >= limit:
            return jsonify({"error": "rate_limited",
                            "message": "Too many requests — wait a minute and retry."}), 429
        dq.append(now)
    return None

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
    # ICE BofA US High Yield OAS (credit-spread stress gauge). Used ONLY by the
    # Market Regime engine — get_rates_snapshot() ignores it, so the /rates
    # response shape is unchanged; it just rides the same free FRED fetch path.
    "BAMLH0A0HYM2": "ICE BofA US High Yield OAS",
    # USD/JPY (daily) — for the Portfolio Exposure JPY conversion (v10.0).
    # Exposed additively as `usdJpy` in the rates snapshot.
    "DEXJPUS": "USD/JPY",
}
# Plausible "Tuesday before US CPI" mock state — used when FRED_API_KEY
# is absent or any per-series fetch fails. Each tuple is (latest, prev).
_FRED_MOCK = {
    "DGS10":  (4.42, 4.30),
    "DGS2":   (4.65, 4.60),
    "DFII10": (1.85, 1.82),
    "VIXCLS": (17.4, 17.0),
    "BAMLH0A0HYM2": (3.10, 3.05),  # ~310bp HY OAS — benign/neutral mock
    "DEXJPUS": (157.2, 156.8),     # USD/JPY mock
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
        "usdJpy":         series["DEXJPUS"],  # additive (v10.0 — JPY conversion)
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

def _jq_fetch_bar_row(code, name, headers):
    """Latest + previous daily bar for one code → normalized dict, or None."""
    try:
        # Window the query (~150d) so we get the two most recent rows without
        # pulling full history; covers the free plan's ~12-week lag plus buffer.
        frm = (datetime.now(TZ_JST) - timedelta(days=150)).strftime("%Y-%m-%d")
        rows = []
        params = {"code": code, "from": frm}
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
            return None
        latest, prev = rows[-1], rows[-2]
        close  = float(_q_close(latest))
        pclose = float(_q_close(prev))
        change = round(close - pclose, 2)
        vol    = latest.get("Vo")
        return {
            "symbol": code, "name": name, "nameJa": name,
            "price": close,
            "changeAbs": change,
            "changePct": round((change / pclose) * 100, 2) if pclose else 0.0,
            "volume": int(vol) if vol is not None else 0,
            "date": latest.get("Date"),
            "status": "live",
        }
    except Exception:
        return None

def _jquants_fetch_quote(s, headers):
    """Curated-list fetch: live bar row, or the per-symbol mock fallback."""
    row = _jq_fetch_bar_row(s["symbol"], s["name"], headers)
    return row if row is not None else _jp_mock_quote(s)

def _jp_mock_snapshot():
    return {"status": "mock", "asOf": None,
            "stocks": [_jp_mock_quote(s) for s in _JP_WATCHLIST]}

# Dynamic (user-watchlist) symbol support. The engine list is no longer fixed:
# the frontend passes its actual assets via ?symbols=. Public endpoint →
# sanitize hard, cap the count, and bound the per-set cache.
_JP_SYM_RE      = re.compile(r"^[0-9A-Z]{4}$")   # TSE 4-char codes incl. 285A
_US_SYM_RE      = re.compile(r"^[A-Z][A-Z.\-]{0,9}$")
_JP_DYN_MAX     = 20
_US_DYN_MAX     = 8     # Twelve Data free tier: 8 credits/min — one batch stays safe
_DYN_CACHE_MAX  = 16
_JP_DYN_CACHE   = {}    # symbols-tuple -> {"data":..., "expires":...}
_US_DYN_CACHE   = {}

def _sanitize_symbols(raw, pattern, cap):
    out = []
    for s in (raw or []):
        s = s.strip().upper()
        if s and pattern.match(s) and s not in out:
            out.append(s)
    return out[:cap]

def _jq_name_for(code4):
    """Japanese company name from the cached J-Quants master ('' if unknown)."""
    for r in _jq_master():
        if r["code4"] == code4:
            return r["ja"] or r["en"] or ""
    return ""

def _get_japan_watchlist_core(symbols=None):
    """Live snapshot of watched Japan names (price/change/volume/date).

    With `symbols=None` → the curated list with mock fallback (cached 10 min,
    live only). With a user symbol list → dynamic fetch with names from the
    J-Quants master; rows that fail are OMITTED (no fake prices), cached per
    symbol-set. `asOf` surfaces the real data date (free plan lags ~12wk).
    """
    now = time.time()
    if symbols:
        syms = tuple(_sanitize_symbols(symbols, _JP_SYM_RE, _JP_DYN_MAX))
        if not syms:
            return {"status": "mock", "asOf": None, "stocks": []}
        hit = _JP_DYN_CACHE.get(syms)
        if hit and now < hit["expires"]:
            return hit["data"]
        if not _JQUANTS_API_KEY:
            return {"status": "mock", "asOf": None, "stocks": []}
        headers = {"x-api-key": _JQUANTS_API_KEY}
        def fetch(code):
            return _jq_fetch_bar_row(code, _jq_name_for(code) or code, headers)
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(syms))) as ex:
            stocks = [q for q in ex.map(fetch, syms) if q is not None]
        overall = "live" if len(stocks) == len(syms) else ("partial" if stocks else "mock")
        as_of   = max((q["date"] for q in stocks if q.get("date")), default=None)
        snapshot = {"status": overall, "asOf": as_of, "stocks": stocks}
        if stocks:
            if len(_JP_DYN_CACHE) >= _DYN_CACHE_MAX:
                _JP_DYN_CACHE.clear()
            _JP_DYN_CACHE[syms] = {"data": snapshot, "expires": now + _JP_CACHE_TTL}
        return snapshot

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

def get_japan_watchlist_snapshot(symbols=None):
    """Core snapshot + real-time overlay: quotes pushed from the local moomoo
    bridge (fresh ≤ 10 min) override the J-Quants T-1 rows (v9.11)."""
    snap = _get_japan_watchlist_core(symbols)
    requested = (_sanitize_symbols(symbols, _JP_SYM_RE, _JP_DYN_MAX) if symbols
                 else [s["symbol"] for s in _JP_WATCHLIST])
    return _overlay_pushed(snap, "JP", requested)

@app.route("/api/argus/japan-watchlist")
def api_argus_japan_watchlist():
    raw = (request.args.get("symbols") or "")
    symbols = [s for s in raw.split(",") if s.strip()] or None
    return jsonify(get_japan_watchlist_snapshot(symbols))


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

def _get_us_watchlist_core(symbols=None):
    """Live snapshot of the watched US names (price/change/volume/date).

    With `symbols=None` → the curated list (one batched request, 10-min cache,
    full-mock on any miss). With a user symbol list → dynamic batch capped at
    8 symbols (Twelve Data free tier = 8 credits/min); failed rows are OMITTED
    (no fake prices) and the per-set cache is bounded.
    """
    now = time.time()
    if symbols:
        syms = tuple(_sanitize_symbols(symbols, _US_SYM_RE, _US_DYN_MAX))
        if not syms:
            return {"status": "mock", "asOf": None, "provider": "twelvedata", "stocks": []}
        hit = _US_DYN_CACHE.get(syms)
        if hit and now < hit["expires"]:
            return hit["data"]
        if not _TWELVEDATA_API_KEY:
            return {"status": "mock", "asOf": None, "provider": "twelvedata", "stocks": []}
        try:
            r = requests.get(_TWELVEDATA_QUOTE,
                             params={"symbol": ",".join(syms), "apikey": _TWELVEDATA_API_KEY},
                             timeout=10)
            r.raise_for_status()
            body = r.json()
            if isinstance(body, dict) and str(body.get("status", "")).lower() == "error":
                return {"status": "mock", "asOf": None, "provider": "twelvedata", "stocks": []}
            rows = []
            for sym in syms:
                q = body.get(sym) if (isinstance(body, dict) and sym in body) else (body if len(syms) == 1 else None)
                # Dynamic rows take the name from the quote itself.
                meta = {"symbol": sym, "name": (q or {}).get("name") or sym}
                row = _td_parse_row(meta, q)
                if row is not None:
                    rows.append(row)
            overall = "live" if len(rows) == len(syms) else ("partial" if rows else "mock")
            as_of = max((row["date"] for row in rows if row.get("date")), default=None)
            snapshot = {"status": overall, "asOf": as_of, "provider": "twelvedata", "stocks": rows}
            if rows:
                if len(_US_DYN_CACHE) >= _DYN_CACHE_MAX:
                    _US_DYN_CACHE.clear()
                _US_DYN_CACHE[syms] = {"data": snapshot, "expires": now + _US_CACHE_TTL}
            return snapshot
        except Exception:
            return {"status": "mock", "asOf": None, "provider": "twelvedata", "stocks": []}

    if _US_CACHE["data"] is not None and now < _US_CACHE["expires"]:
        return _US_CACHE["data"]
    if not _TWELVEDATA_API_KEY:
        return _us_mock_snapshot()
    try:
        symbols_q = ",".join(s["symbol"] for s in _US_WATCHLIST)
        r = requests.get(_TWELVEDATA_QUOTE,
                         params={"symbol": symbols_q, "apikey": _TWELVEDATA_API_KEY},
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

# Finnhub fallback for US symbols Twelve Data's free plan omits entirely
# (user hit this with IONQ on 2026-06-11: NVDA returned, IONQ silently absent).
# 1 quote call per missing symbol, bounded by the dynamic cap; 10-min cache.
_FINNHUB_QUOTE_CACHE = {}   # symbol -> {"row": dict|None, "ts": epoch}
_FINNHUB_QUOTE_TTL = 600

def _finnhub_quote_row(sym):
    if not FINNHUB_API_KEY:
        return None
    now = time.time()
    c = _FINNHUB_QUOTE_CACHE.get(sym)
    if c and now - c["ts"] <= _FINNHUB_QUOTE_TTL:
        return c["row"]
    row = None
    try:
        r = requests.get("https://finnhub.io/api/v1/quote",
                         params={"symbol": sym, "token": FINNHUB_API_KEY}, timeout=6)
        d = r.json() if r.ok else {}
        price = d.get("c")
        if isinstance(price, (int, float)) and price > 0:
            ts = d.get("t") or 0
            row = {"symbol": sym, "name": sym, "price": float(price),
                   "changeAbs": float(d.get("d") or 0), "changePct": float(d.get("dp") or 0),
                   "volume": 0,
                   "date": datetime.fromtimestamp(ts, pytz.utc).strftime("%Y-%m-%d") if ts else None,
                   "status": "live", "source": "finnhub"}
    except Exception:
        row = None
    _FINNHUB_QUOTE_CACHE[sym] = {"row": row, "ts": now}
    return row

def get_us_watchlist_snapshot(symbols=None):
    """Core snapshot + real-time overlay from the local moomoo bridge (v9.11).
    Symbols Twelve Data's free plan omits are back-filled via Finnhub (v10.12.1)."""
    snap = _get_us_watchlist_core(symbols)
    requested = (_sanitize_symbols(symbols, _US_SYM_RE, _US_DYN_MAX) if symbols
                 else [s["symbol"] for s in _US_WATCHLIST])
    snap = _overlay_pushed(snap, "US", requested)
    try:
        have = {s.get("symbol") for s in (snap.get("stocks") or [])}
        missing = [s for s in requested if s not in have]
        if missing and FINNHUB_API_KEY:
            filled = [r for r in (_finnhub_quote_row(s) for s in missing) if r]
            if filled:
                snap = {**snap, "stocks": list(snap.get("stocks") or []) + filled}
                if snap.get("status") == "mock":
                    snap = {**snap, "status": "partial"}
    except Exception:
        pass
    return snap

@app.route("/api/argus/us-watchlist")
def api_argus_us_watchlist():
    raw = (request.args.get("symbols") or "")
    symbols = [s for s in raw.split(",") if s.strip()] or None
    return jsonify(get_us_watchlist_snapshot(symbols))


# ━━━ moomoo real-time quote push (v9.11) ━━━
# A small bridge script (bridge/moomoo_push.py) runs NEXT TO the user's OpenD
# (AWS, 24h) and POSTs real-time JP/US quotes here. Admin-token gated — the
# public frontend cannot push. Pushed quotes OVERRIDE the slower providers
# (J-Quants T-1 / Twelve Data) while fresh, then everything falls back
# automatically. Account credentials never leave the user's machine.
_PUSHED_QUOTES = {"JP": {}, "US": {}}   # market -> {symbol: {"row":…, "ts":…}}
_PUSH_TTL  = 600                        # use pushed quotes for ≤ 10 min
_PUSH_MAX  = 50                         # symbols per push request

def _overlay_pushed(snapshot, market, requested):
    """Copy of a watchlist snapshot with fresh pushed quotes overlaid (and
    holes filled for requested symbols the provider missed). Cache-safe —
    never mutates the cached object. No fresh pushes → snapshot unchanged."""
    try:
        if not isinstance(snapshot, dict):
            return snapshot
        now = time.time()
        fresh = {sym: p["row"] for sym, p in (_PUSHED_QUOTES.get(market) or {}).items()
                 if now - p["ts"] <= _PUSH_TTL}
        if not fresh:
            return snapshot
        stocks, seen, overlaid = [], set(), 0
        for q in snapshot.get("stocks", []):
            sym = q.get("symbol")
            seen.add(sym)
            if sym in fresh:
                stocks.append({**q, **fresh[sym]})
                overlaid += 1
            else:
                stocks.append(q)
        for sym in requested or []:
            if sym in fresh and sym not in seen:
                name = (_jq_name_for(sym) or sym) if market == "JP" else sym
                stocks.append({**fresh[sym], "name": name, "nameJa": name})
                overlaid += 1
        if overlaid == 0:
            return snapshot
        out = {**snapshot, "stocks": stocks, "realtimeCount": overlaid}
        if out.get("status") == "mock":
            out["status"] = "partial"   # real pushed data beats an all-mock claim
        return out
    except Exception:
        return snapshot

def _push_last_age_sec():
    """Seconds since the most recent pushed quote (None if never)."""
    ts = [p["ts"] for m in _PUSHED_QUOTES.values() for p in m.values()]
    return (time.time() - max(ts)) if ts else None

@app.route("/api/argus/quote-push", methods=["POST"])
def api_argus_quote_push():
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    body = request.get_json(silent=True) or {}
    stocks = body.get("stocks")
    if not isinstance(stocks, list):
        return jsonify({"error": "bad_payload", "message": "expected {stocks: [...]}"}), 400
    now, accepted = time.time(), 0
    for s in stocks[:_PUSH_MAX]:
        try:
            market = str(s.get("market", "")).upper()
            sym    = str(s.get("symbol", "")).strip().upper()
            if market not in ("JP", "US"):
                continue
            if not (_JP_SYM_RE if market == "JP" else _US_SYM_RE).match(sym):
                continue
            price = float(s["price"])
            if not (price > 0 and math.isfinite(price)):
                continue
            row = {"symbol": sym,
                   "price": round(price, 4),
                   "changeAbs": round(float(s.get("changeAbs") or 0.0), 4),
                   "changePct": round(float(s.get("changePct") or 0.0), 4),
                   "volume": int(float(s.get("volume") or 0)),
                   "date": datetime.now(TZ_JST).strftime("%Y-%m-%d"),
                   "status": "live", "source": "moomoo-rt"}
            # Optional big-money flow (v10.2): today's cumulative in/out split
            # by order size from the bridge. Normalized here so the ratio
            # formula stays transparent and server-side.
            fl = s.get("flow")
            if isinstance(fl, dict):
                try:
                    big_in, big_out = float(fl["bigIn"]), float(fl["bigOut"])
                    all_in  = float(fl.get("allIn") or 0.0)
                    all_out = float(fl.get("allOut") or 0.0)
                    denom = all_in + all_out
                    if denom > 0 and all(math.isfinite(x) for x in (big_in, big_out, denom)):
                        row["flow"] = {
                            "bigNetRatio": round((big_in - big_out) / denom, 4),
                            "bigIn": round(big_in, 2), "bigOut": round(big_out, 2),
                        }
                except (KeyError, TypeError, ValueError):
                    pass
            _PUSHED_QUOTES[market][sym] = {"row": row, "ts": now}
            accepted += 1
        except Exception:
            continue
    return jsonify({"accepted": accepted, "asOf": _ai_now_iso(),
                    "held": {m: len(v) for m, v in _PUSHED_QUOTES.items()}})


# ━━━ CoinGecko crypto watchlist (keyless, free) ━━━
# Live USD quotes for the crypto assets the user watches. CoinGecko's
# /simple/price needs NO API key; we stay polite with a 10-min cache per
# ids-set and a hard cap on accepted ids (public endpoint — sanitize input).
_COINGECKO_PRICE   = "https://api.coingecko.com/api/v3/simple/price"
_CRYPTO_DEFAULT_IDS = ["bitcoin", "ethereum"]
_CRYPTO_ID_RE      = re.compile(r"^[a-z0-9-]{1,50}$")
_CRYPTO_MAX_IDS    = 15
_CRYPTO_CACHE      = {}          # ids-tuple -> {"data":..., "expires":...}
_CRYPTO_CACHE_MAX  = 16          # bound memory on a public endpoint
_CRYPTO_CACHE_TTL  = 600         # 10 min
# Plausible fallback values (NOT real quotes) so the UI renders in mock state.
_CRYPTO_MOCK = {
    "bitcoin":  {"price": 68_200.0, "changePct": 1.2, "volume": 28_000_000_000},
    "ethereum": {"price": 3_820.0,  "changePct": 0.8, "volume": 14_000_000_000},
}

def get_crypto_watchlist_snapshot(ids):
    ids = tuple(sorted(set(i for i in ids if _CRYPTO_ID_RE.match(i)))[:_CRYPTO_MAX_IDS]) \
          or tuple(_CRYPTO_DEFAULT_IDS)
    now = time.time()
    hit = _CRYPTO_CACHE.get(ids)
    if hit and now < hit["expires"]:
        return hit["data"]

    def _mock_rows():
        return [{"id": i, "priceUsd": m["price"], "changePct": m["changePct"],
                 "volume": int(m["volume"]), "date": None, "status": "mock"}
                for i, m in ((i, _CRYPTO_MOCK[i]) for i in ids if i in _CRYPTO_MOCK)]
    try:
        r = requests.get(_COINGECKO_PRICE, params={
            "ids": ",".join(ids), "vs_currencies": "usd",
            "include_24hr_change": "true", "include_24hr_vol": "true",
            "include_last_updated_at": "true",
        }, timeout=10)
        r.raise_for_status()
        body = r.json() if isinstance(r.json(), dict) else {}
        rows = []
        for i in ids:
            q = body.get(i)
            if not isinstance(q, dict) or q.get("usd") is None:
                continue
            ts = q.get("last_updated_at")
            rows.append({
                "id": i,
                "priceUsd": round(float(q["usd"]), 2),
                "changePct": round(float(q.get("usd_24h_change") or 0.0), 2),
                "volume": int(float(q.get("usd_24h_vol") or 0)),
                "date": (datetime.fromtimestamp(ts, pytz.utc).strftime("%Y-%m-%d") if ts else None),
                "status": "live",
            })
        if not rows:
            return {"status": "mock", "asOf": None, "provider": "coingecko", "quotes": _mock_rows()}
        status = "live" if len(rows) == len(ids) else "partial"
        as_of  = max((x["date"] for x in rows if x["date"]), default=None)
        snapshot = {"status": status, "asOf": as_of, "provider": "coingecko", "quotes": rows}
        if len(_CRYPTO_CACHE) >= _CRYPTO_CACHE_MAX:
            _CRYPTO_CACHE.clear()
        _CRYPTO_CACHE[ids] = {"data": snapshot, "expires": now + _CRYPTO_CACHE_TTL}
        return snapshot
    except Exception:
        return {"status": "mock", "asOf": None, "provider": "coingecko", "quotes": _mock_rows()}

def _crypto_last_status():
    """Last fetched crypto snapshot status for /integrations ('unknown' if none yet)."""
    now = time.time()
    for hit in _CRYPTO_CACHE.values():
        if now < hit["expires"]:
            return hit["data"].get("status", "unknown")
    return "unknown"

@app.route("/api/argus/crypto-watchlist")
def api_argus_crypto_watchlist():
    raw = (request.args.get("ids") or "").lower()
    ids = [s.strip() for s in raw.split(",") if s.strip()]
    return jsonify(get_crypto_watchlist_snapshot(ids))


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


# ━━━ Market Regime + Capital Rotation Engine v1 (rule-based, NO LLM) ━━━
# Classifies the CURRENT cross-asset environment from FRED macro (rates / VIX /
# HY OAS) + a small Twelve Data ETF proxy universe + JP watchlist breadth.
# Transparent rule scoring only — NO OpenAI/Gemini, NO prediction. ETF rotation
# is a PROXY for capital flow, not direct flow. Credit-safe: ONE batched
# 8-symbol Twelve Data time_series request per refresh, cached 6h.
_TWELVEDATA_TS = "https://api.twelvedata.com/time_series"

# 8-symbol universe → 8 credits in one batched request (within the free
# 8-credit/min cap). Deliberately small; XLF/XLE/SMH/LQD/DIA/EWJ are future
# additions once a higher-credit plan or per-minute pacing is in place.
_REGIME_ETFS = ["SPY", "QQQ", "IWM", "XLK", "XLU", "GLD", "TLT", "HYG"]

_ROTATION_GROUPS = [
    {"id": "us-growth",  "label": "US Growth",        "assets": ["QQQ", "XLK"], "role": "Risk"},
    {"id": "us-broad",   "label": "US Broad Risk",    "assets": ["SPY"],        "role": "Risk"},
    {"id": "small-caps", "label": "Small Caps",       "assets": ["IWM"],        "role": "Risk"},
    {"id": "defensive",  "label": "Defensive / Gold", "assets": ["XLU", "GLD"], "role": "Defensive"},
    {"id": "duration",   "label": "Duration / Bonds", "assets": ["TLT"],        "role": "Duration"},
    {"id": "credit",     "label": "Credit Risk",      "assets": ["HYG"],        "role": "Risk"},
]

# Matrix orientation priors by role (the score nudges around these anchors).
_ROLE_GROWTH = {"Risk": 0.5, "Defensive": -0.5, "Hedge": -0.4, "Duration": -0.6, "Liquidity": -0.2}
_ROLE_RISK   = {"Risk": 0.6, "Defensive": -0.2, "Hedge": -0.1, "Duration": -0.7, "Liquidity": -0.3}

_REGIME_SUMMARY_JA = {
    "RISK_ON":   "リスク資産が広く優位で、クレジットも安定。リスク選好寄りの地合い。",
    "RISK_OFF":  "ディフェンシブ・債券・金が優位で、株式とクレジットが弱含み。リスク回避寄り。",
    "CAUTIOUS":  "方向感は限定的で、金利・VIX・イベントのリスクがくすぶる。慎重なスタンス。",
    "EVENT_WAIT": "重要イベントが目前で、新規エントリーを抑えイベント通過後に再評価する局面。",
    "MIXED":     "明確な主導役がなく、資金の方向感は限定的。",
}

_REGIME_CACHE     = {"data": None, "expires": 0.0}
_REGIME_CACHE_TTL = 6 * 3600  # 6h — non-intraday regime scoring, credit-safe

def _clip(v, lo, hi):
    return lo if v < lo else hi if v > hi else v

def _scale_ret(r):
    """Decimal return → [-1, 1] via a ±10% cap (transparent, no z-score)."""
    return _clip(r, -0.10, 0.10) / 0.10

# Latest ETF closes stashed by _td_timeseries — consumed by the prediction
# ledger's class predictions and the /class-quotes scoring endpoint (v10.5).
_ETF_LAST_PRICE = {}   # sym -> {"price": float, "m1d": float, "ts": epoch}

def _td_timeseries(symbols):
    """Batched daily closes for the ETF universe.

    Returns {symbol: [latest_close, ..., older]} (newest-first) for each symbol
    that parsed, or {} on no key / error / rate limit. Never raises. ONE
    request, len(symbols) credits — keep len(symbols) <= 8 for the free cap.
    """
    if not _TWELVEDATA_API_KEY:
        return {}
    try:
        r = requests.get(_TWELVEDATA_TS, params={
            "symbol": ",".join(symbols), "interval": "1day",
            "outputsize": 22, "apikey": _TWELVEDATA_API_KEY,
        }, timeout=15)
        r.raise_for_status()
        body = r.json()
        # Top-level error (bad key / quota / rate limit) → flat dict status=error.
        if isinstance(body, dict) and str(body.get("status", "")).lower() == "error":
            return {}
        out = {}
        for sym in symbols:
            # Multi-symbol responses are keyed by symbol; single is flat.
            if isinstance(body, dict) and sym in body:
                node = body.get(sym)
            elif len(symbols) == 1:
                node = body
            else:
                node = None
            if not isinstance(node, dict) or str(node.get("status", "ok")).lower() == "error":
                continue
            closes = []
            for v in (node.get("values") or []):
                c = v.get("close")
                if c not in (None, ""):
                    try:
                        closes.append(float(c))
                    except (TypeError, ValueError):
                        pass
            if len(closes) >= 2:
                out[sym] = closes  # Twelve Data returns newest-first
                # Side stash for the prediction ledger (v10.5): latest close +
                # 1d move per ETF, refreshed whenever ANY caller fetches.
                _ETF_LAST_PRICE[sym] = {
                    "price": closes[0],
                    "m1d": round((closes[0] / closes[1] - 1) * 100, 2),
                    "ts": time.time(),
                }
        return out
    except Exception:
        return {}

def _etf_momentum(closes):
    """1d/5d/20d returns + composite score from a newest-first close list."""
    c0 = closes[0]
    def ret(n):
        if len(closes) > n and closes[n]:
            return c0 / closes[n] - 1.0
        return None
    m1, m5, m20 = ret(1), ret(5), ret(20)
    if m5 is not None and m20 is not None:
        score = 0.45 * _scale_ret(m5) + 0.35 * _scale_ret(m20) + 0.20 * _scale_ret(m1 or 0.0)
    elif m5 is not None:
        score = 0.60 * _scale_ret(m5) + 0.40 * _scale_ret(m1 or 0.0)
    else:
        score = _scale_ret(m1 or 0.0)
    return {
        "momentum1d":  round((m1 or 0.0) * 100, 2),
        "momentum5d":  round(m5 * 100, 2) if m5 is not None else None,
        "momentum20d": round(m20 * 100, 2) if m20 is not None else None,
        "score":       round(_clip(score, -1.0, 1.0), 3),
        "limited":     (m20 is None or m5 is None),
    }

def _group_rationale_ja(label, score, status, available):
    if not available:
        return f"{label} はデータ取得待ちのため評価を保留。"
    if status == "inflow":
        return f"{label} に資金流入の傾向（スコア {score:+.2f}）。"
    if status == "outflow":
        return f"{label} から資金流出の傾向（スコア {score:+.2f}）。"
    return f"{label} は中立（スコア {score:+.2f}）。"

def _regime_rates_backdrop(rates, hy):
    us10y = (rates.get("us10y") if isinstance(rates, dict) else None) or {}
    us2y  = (rates.get("us2y") if isinstance(rates, dict) else None) or {}
    real  = (rates.get("usReal10y") if isinstance(rates, dict) else None) or {}
    vix   = (rates.get("vix") if isinstance(rates, dict) else None) or {}
    hy    = hy or {}
    vix_lvl   = float(vix.get("latestValue") or 0)
    dgs10_chg = float(us10y.get("change") or 0)
    real_lvl  = float(real.get("latestValue") or 0)
    hy_lvl    = float(hy.get("latestValue") or 0)
    hy_chg    = float(hy.get("change") or 0)
    if vix_lvl >= 26 or hy_lvl >= 5.0 or hy_chg >= 0.5:
        posture, ja = "stress", "VIX上昇または信用スプレッド拡大で、ストレスの兆候。"
    elif dgs10_chg >= 0.08 or real_lvl >= 2.3:
        posture, ja = "tightening", "長期・実質金利の上昇が、リスク資産の上値を抑えやすい地合い。"
    elif 0 < vix_lvl < 16 and 0 < hy_lvl < 3.5 and dgs10_chg <= 0.03:
        posture, ja = "supportive", "低VIX・タイトな信用スプレッド・落ち着いた金利で、リスク選好を支えやすい。"
    else:
        posture, ja = "neutral", "金利・VIX・信用スプレッドはおおむね中立圏。"
    return {
        "us10y":   round(float(us10y.get("latestValue") or 0), 2),
        "us2y":    round(float(us2y.get("latestValue") or 0), 2),
        "real10y": round(real_lvl, 2),
        "vix":     round(vix_lvl, 1),
        "hyOas":   round(hy_lvl, 2),
        "posture": posture,
        "rationaleJa": ja,
    }

def get_market_regime_snapshot():
    """Live/partial rule-based market-regime + capital-rotation scoring."""
    now = time.time()
    if _REGIME_CACHE["data"] is not None and now < _REGIME_CACHE["expires"]:
        return _REGIME_CACHE["data"]

    rates = get_rates_snapshot()
    ev    = get_events_snapshot()
    jp    = get_japan_watchlist_snapshot()
    hy    = fetch_fred_series("BAMLH0A0HYM2")  # live or per-series mock

    etf = {sym: _etf_momentum(cl) for sym, cl in _td_timeseries(_REGIME_ETFS).items()}
    etf_full = len(etf) == len(_REGIME_ETFS)
    etf_live = len(etf) >= max(1, len(_REGIME_ETFS) // 2)

    def sym_score(sym):
        return etf.get(sym, {}).get("score")

    groups = []
    for g in _ROTATION_GROUPS:
        scores = [sym_score(s) for s in g["assets"] if sym_score(s) is not None]
        if scores:
            gscore = sum(scores) / len(scores)
            status = "inflow" if gscore > 0.15 else "outflow" if gscore < -0.15 else "neutral"
            avail = True
        else:
            gscore, status, avail = 0.0, "neutral", False
        def agg(key):
            vs = [etf[s][key] for s in g["assets"] if s in etf and etf[s].get(key) is not None]
            return round(sum(vs) / len(vs), 2) if vs else None
        groups.append({
            "id": g["id"], "label": g["label"], "assets": g["assets"], "role": g["role"],
            "score": round(gscore, 3),
            "momentum1d": agg("momentum1d"), "momentum5d": agg("momentum5d"), "momentum20d": agg("momentum20d"),
            "status": status, "available": avail,
            "rationaleJa": _group_rationale_ja(g["label"], gscore, status, avail),
        })
    gmap = {g["id"]: g for g in groups}
    def gsc(gid):
        g = gmap.get(gid)
        return g["score"] if g and g["available"] else 0.0

    growth_lead    = (gsc("us-growth") + gsc("us-broad") + gsc("small-caps")) / 3.0
    defensive_lead = (gsc("defensive") + gsc("duration")) / 2.0
    credit_lead    = gsc("credit")
    risk_lead      = (gsc("us-broad") + gsc("small-caps") + gsc("us-growth") + credit_lead) / 4.0
    growth_value_axis  = _clip(growth_lead - defensive_lead, -1.0, 1.0)
    risk_duration_axis = _clip(risk_lead - gsc("duration"), -1.0, 1.0)

    events = ev.get("events", []) if isinstance(ev, dict) else []
    esc_us = _region_event_escalation(events, "US")
    esc_jp = _region_event_escalation(events, "JP")
    imminent = esc_us in ("D", "D-1") or esc_jp in ("D", "D-1")

    backdrop     = _regime_rates_backdrop(rates, hy)
    vix_elevated = backdrop["vix"] >= 20
    hy_stress    = backdrop["posture"] == "stress"

    # ── Regime classification (transparent precedence) ──
    if imminent and abs(risk_lead) < 0.30:
        label = "EVENT_WAIT"
    elif risk_lead >= 0.20 and credit_lead >= -0.05 and not vix_elevated and not hy_stress:
        label = "RISK_ON"
    elif risk_lead <= -0.20 and defensive_lead >= risk_lead and (vix_elevated or hy_stress or defensive_lead > 0.10):
        label = "RISK_OFF"
    elif vix_elevated or hy_stress or backdrop["posture"] == "tightening" or imminent:
        label = "CAUTIOUS"
    elif abs(risk_lead) < 0.10 and abs(growth_value_axis) < 0.10:
        label = "MIXED"
    elif risk_lead > 0:
        label = "RISK_ON"
    else:
        label = "CAUTIOUS"

    # ── Confidence: source availability + signal agreement ──
    signs = [1 if risk_lead > 0.1 else -1 if risk_lead < -0.1 else 0,
             1 if credit_lead > 0.1 else -1 if credit_lead < -0.1 else 0,
             -1 if defensive_lead > 0.1 else 1 if defensive_lead < -0.1 else 0]
    nz = [s for s in signs if s != 0]
    agree = abs(sum(nz)) / len(nz) if nz else 0.0
    conf = 0.35
    conf += 0.20 if etf_full else 0.10 if etf_live else 0.0
    if isinstance(rates, dict) and rates.get("status") == "live": conf += 0.10
    if hy and hy.get("status") == "live": conf += 0.07
    if isinstance(jp, dict) and jp.get("status") == "live": conf += 0.05
    conf += 0.15 * agree
    if label == "MIXED": conf = min(conf, 0.5)
    confidence = round(_clip(conf, 0.1, 0.9), 2)

    # ── Status / sources ──
    rates_live = isinstance(rates, dict) and rates.get("status") == "live"
    jp_has     = isinstance(jp, dict) and any(s.get("status") == "live" for s in jp.get("stocks", []))
    if etf_full and rates_live:
        status = "live"
    elif etf_live or rates_live:
        status = "partial"
    else:
        status = "mock"
    source_statuses = {
        "fred":           "live" if rates_live else "mock",
        "twelveData":     "live" if etf_full else "partial" if etf_live else "unavailable",
        "jquants":        "partial" if jp_has else "unavailable",  # breadth proxy, not sector rotation
        "manualFallback": "unused" if etf_live else "mock",
    }

    # ── Capital rotation: top rotations ──
    def rot(a_id, b_id, label_txt, direction):
        a, b = gmap.get(a_id), gmap.get(b_id)
        if not (a and b and a["available"] and b["available"]):
            return None
        spread = b["score"] - a["score"]
        if spread <= 0.15:
            return None
        return {"label": label_txt, "direction": direction, "score": round(spread, 3),
                "evidenceJa": f"{a['label']}（{a['score']:+.2f}）から {b['label']}（{b['score']:+.2f}）へ資金がシフト。"}
    cand = [
        rot("us-growth",  "defensive",  "Growth -> Defensive",   "outflow"),
        rot("small-caps", "duration",   "Small Caps -> Duration", "outflow"),
        rot("credit",     "defensive",  "Credit -> Defensive",   "outflow"),
        rot("defensive",  "us-growth",  "Defensive -> Growth",   "inflow"),
        rot("duration",   "us-broad",   "Bonds -> Equities",     "inflow"),
    ]
    top_rotations = [c for c in cand if c][:3]
    avail_groups = [g for g in groups if g["available"]]
    if not top_rotations and avail_groups:
        srt = sorted(avail_groups, key=lambda g: g["score"])
        lo, hi = srt[0], srt[-1]
        if hi["score"] - lo["score"] > 0.1:
            top_rotations.append({
                "label": f"{lo['label']} -> {hi['label']}",
                "direction": "inflow" if hi["role"] == "Risk" else "outflow",
                "score": round(hi["score"] - lo["score"], 3),
                "evidenceJa": f"{lo['label']} が相対的に弱く、{hi['label']} が優位。",
            })

    # ── Matrix context points ──
    points = []
    for g in groups:
        if not g["available"]:
            continue
        px = _clip(_ROLE_GROWTH.get(g["role"], 0.0) * 0.6 + g["score"] * 0.5, -1.0, 1.0)
        py = _clip(_ROLE_RISK.get(g["role"], 0.0) * 0.6 + g["score"] * 0.5, -1.0, 1.0)
        points.append({"label": g["label"], "x": round(px, 2), "y": round(py, 2)})

    # ── Supporting evidence (only what we actually have) ──
    evidence = []
    if gmap["us-broad"]["available"] or gmap["small-caps"]["available"]:
        evidence.append(f"米国広範リスク(SPY) {gsc('us-broad'):+.2f}、小型株(IWM) {gsc('small-caps'):+.2f}、グロース {gsc('us-growth'):+.2f}。")
    if gmap["credit"]["available"]:
        evidence.append(f"ハイイールド(HYG) {credit_lead:+.2f}、HY OAS {backdrop['hyOas']}%（{'live' if hy and hy.get('status') == 'live' else 'mock'}）。")
    evidence.append(f"VIX {backdrop['vix']}、金利地合いは {backdrop['posture']}。")
    jp_live_stocks = [s for s in (jp.get("stocks", []) if isinstance(jp, dict) else []) if s.get("status") == "live"]
    if jp_live_stocks:
        jp_breadth = round(sum(float(s.get("changePct", 0)) for s in jp_live_stocks) / len(jp_live_stocks), 2)
        evidence.append(f"日本株ウォッチリストの騰落率平均 {jp_breadth:+.2f}%（暫定プロキシ）。")
    if imminent:
        evidence.append(f"重要イベントが接近（US={esc_us or '—'}, JP={esc_jp or '—'}）。")

    # ── Data limitations (honest) ──
    limitations = [
        "ETF rotation is a proxy for capital flow, not direct capital flow.",
        "ETF universe is a focused 8-symbol subset (SPY/QQQ/IWM/XLK/XLU/GLD/TLT/HYG); financials/energy/semis and the LQD credit pair are pending.",
        "No order book / tape / moomoo flow yet.",
        "Japan regime uses watchlist breadth as a temporary proxy, not index/sector rotation.",
    ]
    if not etf_full:
        limitations.append("Some ETF history was unavailable this refresh — scoring is partial.")
    limitations.append("Crypto risk appetite (BTC/ETH) not yet folded into regime scoring.")

    matrix_ja = (f"横軸グロース対ディフェンシブ {growth_value_axis:+.2f}、縦軸リスク対デュレーション "
                 f"{risk_duration_axis:+.2f}。{_REGIME_SUMMARY_JA.get(label, '')}")

    payload = {
        "status": status,
        "asOf": datetime.now(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "engineVersion": "regime-v1",
        "regime": {
            "label": label,
            "growthValueAxis": round(growth_value_axis, 3),
            "riskDurationAxis": round(risk_duration_axis, 3),
            "summaryJa": _REGIME_SUMMARY_JA.get(label, ""),
            "confidence": confidence,
        },
        "ratesBackdrop": backdrop,
        "rotationGroups": groups,
        "topRotations": top_rotations,
        "matrix": {
            "x": round(growth_value_axis, 3),
            "y": round(risk_duration_axis, 3),
            "xLabel": "Growth vs Defensive",
            "yLabel": "Risk vs Duration",
            "points": points,
            "rationaleJa": matrix_ja,
        },
        "supportingEvidence": evidence,
        "sourceStatuses": source_statuses,
        "dataLimitations": limitations,
    }
    if status != "mock":
        _REGIME_CACHE["data"]    = payload
        # A partial WITHOUT ETF data (cold start hitting the Twelve Data
        # per-minute credit cap) must not stick for 6h — retry in 5 min so the
        # rotation board / class predictions self-heal quickly.
        _REGIME_CACHE["expires"] = now + (_REGIME_CACHE_TTL if etf_live else 300)
    return payload

@app.route("/api/argus/market-regime")
def api_argus_market_regime():
    return jsonify(get_market_regime_snapshot())


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

def _quote_lag_days(date_str):
    """Calendar days between a quote's data date and today (JST), or None."""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        return (datetime.now(TZ_JST).date() - d).days
    except Exception:
        return None

_QUOTE_STALE_DAYS = 7  # older than this → label confidence is damped + flagged

def _action_metas(jp, us, jp_symbols, us_symbols):
    """Engine symbol list. Default = curated _ACTION_SYMBOLS; with user symbol
    lists → dynamic metas (names from the snapshots / J-Quants master; unknown
    symbols default to the HIGH-BETA class so the engine stays conservative)."""
    if jp_symbols is None and us_symbols is None:
        return _ACTION_SYMBOLS
    known = {m["symbol"]: m for m in _ACTION_SYMBOLS}
    names = {}
    for snap in (jp, us):
        for s in (snap.get("stocks", []) if isinstance(snap, dict) else []):
            names[s["symbol"]] = s.get("name") or s["symbol"]
    metas = []
    for sym in _sanitize_symbols(jp_symbols or [], _JP_SYM_RE, _JP_DYN_MAX):
        metas.append(known.get(sym) or
                     {"symbol": sym, "market": "JP", "name": names.get(sym, sym), "cls": "jp_momentum"})
    for sym in _sanitize_symbols(us_symbols or [], _US_SYM_RE, _US_DYN_MAX):
        metas.append(known.get(sym) or
                     {"symbol": sym, "market": "US", "name": names.get(sym, sym), "cls": "us_growth"})
    return metas

def _flow_adjust(action, conf, reason, nxt, chg, ratio, esc, posture, reg_label):
    """v0.5 — REAL large-order flow confirmation (moomoo bridge, v10.2).

    The v0 engine deliberately never emitted BUY DIP/ADD because it had no
    flow/trend confirmation. Big-money net-flow ratio (大口純流入/全売買代金,
    -1..+1) now provides exactly that — used conservatively and symmetrically:
      - BUY DIP only on a MILD dip (-5 < chg <= -2) with strong big inflow
        (>= +0.20), no imminent event, no elevated rates, no risk-off regime.
      - Strong big OUTFLOW (<= -0.25) tightens a complacent HOLD to WAIT.
      - Otherwise the ratio is annotated as evidence, never overriding rules.
    Returns (action, conf, reasonJa, nextJa)."""
    imminent = esc in ("D", "D-1")
    if (action in ("HOLD", "WAIT") and -5 < chg <= -2 and ratio >= 0.20
            and not imminent and posture != "elevated"
            and reg_label not in ("RISK_OFF", "EVENT_WAIT")):
        return ("BUY DIP", round(min(0.6, conf + 0.10), 2),
                reason + f" 大口資金の純流入({ratio:+.0%})が下値を支えており、押し目買い候補。",
                "下げ止まりと大口流入の継続を確認しながら段階的に。")
    if action == "HOLD" and ratio <= -0.25:
        return ("WAIT", conf,
                reason + f" 大口資金の純流出({ratio:+.0%})が続いており、新規は様子見。",
                "大口フローの反転(流出の縮小)を確認する。")
    if ratio >= 0.20:
        return (action, conf, reason + f" 大口は純流入({ratio:+.0%})。", nxt)
    if ratio <= -0.20:
        return (action, conf, reason + f" 大口は純流出({ratio:+.0%})。", nxt)
    return (action, conf, reason, nxt)

# ── Calibration plumbing (calibration-v1, v10.8) ─────────────────────────────
# Closes the learning loop: the daily ledger scores (summary.json on the ledger
# branch) feed back into label confidence. Context bucket = the day's rates
# posture — the scorer groups scenario rows the same way, so the comparison is
# apples-to-apples. Sample guards keep this honest: ~11 scenario rows are
# scored per day, so a bucket needs ≥3 days of evidence (33 rows) before it may
# move confidence at all; until then the factor is exactly 1.0 and the UI says
# 蓄積中. The bands are deliberately wide — argmax hit rate on ±2% buckets is
# noisy, so only a clear pattern (≥60% / <40%) earns an adjustment.
_CAL_MIN_N = 33
_CAL_TRUST_HIT = 0.60
_CAL_DOUBT_HIT = 0.40
_CAL_UP, _CAL_DOWN = 1.05, 0.85
_LEDGER_SUMMARY_CACHE = {"data": None, "expires": 0.0}

def _ledger_summary():
    """summary.json from the ledger branch via GitHub raw. 30-min cache,
    10-min fail back-off, never raises."""
    now = time.time()
    if now < _LEDGER_SUMMARY_CACHE["expires"]:
        return _LEDGER_SUMMARY_CACHE["data"]
    try:
        r = requests.get(f"{_LEDGER_RAW_BASE}/summary.json", timeout=6)
        d = r.json() if r.status_code == 200 else None
        _LEDGER_SUMMARY_CACHE["data"] = d if isinstance(d, dict) else None
        _LEDGER_SUMMARY_CACHE["expires"] = now + (1800 if isinstance(d, dict) else 600)
    except Exception:
        _LEDGER_SUMMARY_CACHE["data"] = None
        _LEDGER_SUMMARY_CACHE["expires"] = now + 600
    return _LEDGER_SUMMARY_CACHE["data"]

def _calibration_for(summary, posture):
    """Pure (unit-tested): ledger summary + today's posture →
    {factor, basisJa, n, hitRate}. Malformed input → neutral factor."""
    try:
        b = ((summary or {}).get("byPosture") or {}).get(posture) or {}
        n = int(b.get("n") or 0)
        hr = b.get("hitRate")
        if n >= _CAL_MIN_N and isinstance(hr, (int, float)):
            if hr >= _CAL_TRUST_HIT:
                f, verdict = _CAL_UP, "確信度を僅かに引き上げ"
            elif hr < _CAL_DOUBT_HIT:
                f, verdict = _CAL_DOWN, "確信度を引き下げ"
            else:
                f, verdict = 1.0, "調整なし(ノイズ域)"
            return {"factor": f, "n": n, "hitRate": hr,
                    "basisJa": f"姿勢{posture}での過去的中率{hr:.0%}(n={n}) → {verdict}"}
        total = int(((summary or {}).get("overall") or {}).get("n") or 0)
        return {"factor": 1.0, "n": n,
                "hitRate": hr if isinstance(hr, (int, float)) else None,
                "basisJa": f"校正データ蓄積中(この姿勢n={n}/必要{_CAL_MIN_N}・全体n={total}) — 確信度は未調整"}
    except Exception:
        return {"factor": 1.0, "n": 0, "hitRate": None,
                "basisJa": "校正不可(summary形式不明) — 確信度は未調整"}

def get_action_labels(jp_symbols=None, us_symbols=None):
    """Rule-based action labels, aggregated server-side. Accepts the user's
    actual watchlist symbols (dynamic) — default is the curated list."""
    rates = get_rates_snapshot()
    jp    = get_japan_watchlist_snapshot(jp_symbols)
    us    = get_us_watchlist_snapshot(us_symbols)
    ev    = get_events_snapshot()
    reg   = get_market_regime_snapshot()  # 6h-cached; no extra cost when warm
    reg_status = reg.get("status") if isinstance(reg, dict) else "mock"
    reg_block  = reg.get("regime", {}) if isinstance(reg, dict) else {}
    reg_label  = reg_block.get("label")
    reg_ready  = reg_status in ("live", "partial") and reg_label
    events  = ev.get("events", []) if isinstance(ev, dict) else []
    posture = _rates_posture(rates)
    esc_by_market = {"US": _region_event_escalation(events, "US"),
                     "JP": _region_event_escalation(events, "JP")}
    # calibration-v1: the ledger's scored track record for today's posture
    # adjusts label confidence (neutral 1.0 until enough evidence accumulates).
    cal = _calibration_for(_ledger_summary(), posture)

    quotes = {}
    for snap in (jp, us):
        for s in (snap.get("stocks", []) if isinstance(snap, dict) else []):
            quotes[s["symbol"]] = s

    labels, changes = [], []
    for meta in _action_metas(jp, us, jp_symbols, us_symbols):
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
        high_beta = meta["cls"] in ("us_growth", "jp_momentum")
        # Broad-market regime nudge (conservative, one-directional): under
        # RISK_OFF / EVENT_WAIT, high-beta names that the per-symbol rule left
        # at HOLD are lifted to WAIT. Never loosens caution (RISK_ON does not
        # auto-ADD); it only defers entries when the market backdrop disagrees.
        if reg_ready and high_beta and reg_label in ("RISK_OFF", "EVENT_WAIT") and action == "HOLD":
            action = "WAIT"
            conf = round(min(0.6, conf + 0.05), 2)
            reason += f" 市場レジームが{reg_label}のため、高ベータは様子見に引き上げ。"
        # Big-money flow confirmation (v10.2) — only present while the moomoo
        # bridge is pushing fresh quotes with capital-distribution data.
        flow_ratio = None
        fl = q.get("flow")
        if isinstance(fl, dict) and isinstance(fl.get("bigNetRatio"), (int, float)):
            flow_ratio = float(fl["bigNetRatio"])
            action, conf, reason, nxt = _flow_adjust(
                action, conf, reason, nxt, chg, flow_ratio, esc, posture,
                reg_label if reg_ready else None)
        # Data-freshness honesty: J-Quants free plan lags ~12 weeks. A label
        # computed from an old price must say so and carry LESS confidence —
        # never present a stale-data judgment as a fresh one.
        lag = _quote_lag_days(q.get("date") or "")
        if lag is not None and lag > _QUOTE_STALE_DAYS:
            conf = round(conf * 0.5, 2)
            reason = f"【価格データ{lag}日遅れ】" + reason
        if cal["factor"] != 1.0:
            conf = round(min(0.9, max(0.05, conf * cal["factor"])), 2)
        labels.append({
            "symbol": meta["symbol"], "market": meta["market"], "name": meta["name"],
            "action": action, "confidence": conf, "risk": risk, "reasonJa": reason,
            "supportingData": {"changePct": chg, "volume": q.get("volume", 0),
                               "eventEscalation": esc or "normal", "ratesPosture": posture,
                               "marketRegime": reg_label or "n/a",
                               "quoteDate": q.get("date"), "quoteLagDays": lag,
                               "bigFlowRatio": flow_ratio},
            "nextConditionJa": nxt, "status": "live",
        })

    imminent_any = esc_by_market["US"] in ("D", "D-1") or esc_by_market["JP"] in ("D", "D-1")
    avg = sum(changes) / len(changes) if changes else 0.0
    if reg_ready:
        # The Market Regime engine reads the broad cross-asset backdrop, so when
        # it is live/partial it sets the headline posture; the watchlist-average
        # rule below is the fallback for when regime is unavailable.
        mp, mp_ja = reg_label, reg_block.get("summaryJa", "") + "（Market Regime エンジン）"
    elif imminent_any:
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
        "marketRegime": {
            "label": reg_label or "n/a",
            "confidence": reg_block.get("confidence"),
            "status": reg_status,
            "growthValueAxis": reg_block.get("growthValueAxis"),
            "riskDurationAxis": reg_block.get("riskDurationAxis"),
        },
        "calibration": cal,
        "labels": labels,
    }

@app.route("/api/argus/action-labels")
def api_argus_action_labels():
    def _parse(name):
        raw = (request.args.get(name) or "")
        vals = [s for s in raw.split(",") if s.strip()]
        return vals or None
    jp_syms, us_syms = _parse("jp"), _parse("us")
    return jsonify(get_action_labels(jp_syms, us_syms))


# ━━━ AI Judgment Layer (OpenAI primary + Gemini double-check) — DORMANT ━━━
# NOTE: The OpenAI/Gemini judge functions below are kept for a FUTURE version
# (GPT-5.5 API + Gemini double-check, v8.10.x+). They are NOT wired to any
# endpoint in this version — no OpenAI/Gemini call is made. The live AI run path
# is replaced by the Security Gate v1 placeholder + the manual GPT-5.5 Pro
# handoff export below.
_OPENAI_API_KEY        = os.environ.get("OPENAI_API_KEY", "")
_OPENAI_MODEL          = os.environ.get("OPENAI_MODEL", "") or "gpt-5.5"
_GEMINI_JUDGE_MODEL    = os.environ.get("GEMINI_JUDGE_MODEL", "") or "gemini-2.5-flash"
# Free-tier quota for the pro model is tiny (observed 429 RESOURCE_EXHAUSTED on
# 2026-06-11) — on quota errors the checker falls back to this model once so
# the double-check DEGRADES instead of disappearing.
_GEMINI_FALLBACK_MODEL = os.environ.get("GEMINI_FALLBACK_MODEL", "") or "gemini-2.5-flash"
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

# Last-run per-model diagnostics (admin-only surface). No secrets, no payloads —
# just the status of the most recent admin-triggered run, if any.
_AI_LAST_RUN = {"oai": None, "gem": None, "groundingEnabled": None, "at": None}

# ── AI judgment persistence (ai-persist-v1) ──────────────────────────────────
# The in-memory cache dies on every free-dyno sleep/restart and its 30-min TTL
# expires long before the next daily 16:05 JST run — so the app said "not run
# yet" for most of the day even though a real run existed. The daily workflow
# now persists each run to the ledger branch (ledger/ai/latest.json) and a
# fresh/expired dyno silently restores it from GitHub raw. The persisted JSON
# is exactly what the public GET already serves — no secrets involved.
_LEDGER_RAW_BASE = os.environ.get(
    "LEDGER_RAW_BASE", "https://raw.githubusercontent.com/mitsugue/argus/ledger/ledger")
_AI_RESTORE_MAX_AGE_H = 120          # weekend/holiday tolerance; UI stamps run age
_AI_RESTORE_BACKOFF_S = 600
_AI_RESTORE_STATE = {"lastTry": 0.0}

def _ai_restore_validate(d, now_utc=None):
    """Pure validation of a persisted AI payload (unit-tested). Accepts only a
    real run (live/partial, non-empty labels, parseable asOf) no older than
    _AI_RESTORE_MAX_AGE_H. Returns the dict or None — never raises."""
    if not isinstance(d, dict) or d.get("status") not in ("live", "partial"):
        return None
    if not isinstance(d.get("labels"), list) or not d["labels"] or not d.get("asOf"):
        return None
    try:
        run_at = datetime.strptime(d["asOf"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.utc)
    except Exception:
        return None
    now = now_utc or datetime.now(pytz.utc)
    age_h = (now - run_at).total_seconds() / 3600
    if age_h > _AI_RESTORE_MAX_AGE_H or age_h < -1:
        return None
    return d

def _ai_try_restore():
    """Fetch the last persisted run from the ledger branch. Bounded (10-min
    back-off, 6s timeout), never raises."""
    now = time.time()
    if now - _AI_RESTORE_STATE["lastTry"] < _AI_RESTORE_BACKOFF_S:
        return None
    _AI_RESTORE_STATE["lastTry"] = now
    try:
        r = requests.get(f"{_LEDGER_RAW_BASE}/ai/latest.json", timeout=6)
        if r.status_code != 200:
            return None
        d = _ai_restore_validate(r.json())
        if not d:
            return None
        d["runMode"] = "restored"
        _AI_RESULT_CACHE["data"] = d
        _AI_RESULT_CACHE["expires"] = time.time() + _AI_CACHE_TTL
        add_log(f"[AI] restored persisted judgment from ledger (asOf={d.get('asOf')}, status={d.get('status')})")
        return d
    except Exception as e:
        add_log(f"[AI] ledger restore failed: {type(e).__name__}")
        return None

def _ai_cached_result():
    """The valid in-memory AI run, else a ledger-restored one, else None."""
    cached = _AI_RESULT_CACHE["data"]
    if cached and time.time() < _AI_RESULT_CACHE["expires"]:
        return cached
    return _ai_try_restore()

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

        def _gen(model, config):
            return (client.models.generate_content(model=model, contents=prompt, config=config)
                    if config else client.models.generate_content(model=model, contents=prompt))

        model_used = _GEMINI_JUDGE_MODEL
        try:
            resp = _gen(model_used, cfg)
        except Exception as e:
            msg = str(e)
            # Quota exhausted on the configured (pro) model → degrade to the
            # fallback model rather than losing the double-check entirely.
            if ("429" in msg or "RESOURCE_EXHAUSTED" in msg) and _GEMINI_FALLBACK_MODEL != model_used:
                model_used = _GEMINI_FALLBACK_MODEL
                add_log(f"[AI] gemini quota hit — falling back to {model_used}")
                resp = _gen(model_used, cfg)
            else:
                raise
        _AI_LAST_RUN["gemModel"] = model_used
        out = safe_json(getattr(resp, "text", "") or "")
        if not isinstance(out, dict) or "disagreements" not in out:
            # Grounding-tool responses often aren't pure JSON. Retry ONCE in
            # strict JSON mode (tools and response_mime_type can't combine).
            try:
                from google.genai import types as _gt
                cfg2 = _gt.GenerateContentConfig(response_mime_type="application/json")
                resp = _gen(model_used, cfg2)
                out = safe_json(getattr(resp, "text", "") or "")
                grounding_enabled = False
            except Exception as e2:
                _AI_LAST_RUN["gemError"] = f"json-retry {type(e2).__name__}: {str(e2)[:140]}"
        if not isinstance(out, dict) or "disagreements" not in out:
            _AI_LAST_RUN["gemError"] = ("parse: no 'disagreements' key; head=" +
                                        (getattr(resp, "text", "") or "")[:100])
            return None, "partial", grounding_enabled
        _AI_LAST_RUN["gemError"] = None
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
        _AI_LAST_RUN["gemError"] = f"{type(e).__name__}: {str(e)[:140]}"
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

def _ai_judgment_truth():
    """Single source of truth for the automated-AI-judgment status.

    Truthful, key-aware status (NEVER 'live' merely because AI_JUDGE_ENABLED is
    true). Reads cache + env presence only — no model call, no secret exposed.
      disabled         — AI_JUDGE_ENABLED is false
      missing_keys     — enabled, but neither OpenAI nor Gemini key configured
      partial          — enabled, exactly one provider key configured, no live cache
      no_cached_result — enabled + keys present, but no successful run cached
      live/partial/mock— a fresh non-expired cached run exists (its real status)
    """
    enabled = _AI_JUDGE_ENABLED
    oai = bool(_OPENAI_API_KEY)
    gem = bool(GEMINI_API_KEY)
    admin = bool(_ARGUS_ADMIN_TOKEN)
    # In-memory cache, falling back to the run persisted on the ledger branch
    # (survives dyno restarts and the 30-min TTL — ai-persist-v1).
    cached = _ai_cached_result() if (enabled and (oai or gem)) else _AI_RESULT_CACHE["data"]
    has_cache = bool(cached) and time.time() < _AI_RESULT_CACHE["expires"]
    cached_status = (cached.get("status") if has_cache else ("expired" if cached else "none"))
    last_run_at = (cached.get("asOf") if cached else None) or _AI_LAST_RUN.get("at")

    if not enabled:
        status = "disabled"
    elif not oai and not gem:
        status = "missing_keys"
    elif has_cache:
        status = cached.get("status", "no_cached_result")  # real run result
    elif not (oai and gem):
        status = "partial"        # only one provider configured; cannot be fully live
    else:
        status = "no_cached_result"

    # publicGetStatus mirrors exactly what GET /api/argus/ai-judgment returns.
    if not enabled:
        public_get = "disabled"
    elif not oai and not gem:
        public_get = "missing_keys"
    elif has_cache:
        public_get = cached.get("status", "no_cached_result")
    else:
        public_get = "no_cached_result"

    return {
        "status": status,
        "enabled": enabled,
        "openaiConfigured": oai,
        "geminiConfigured": gem,
        "adminTokenConfigured": admin,
        "hasCachedResult": has_cache,
        "cachedStatus": cached_status,
        "lastRunAt": last_run_at,
        "publicGetStatus": public_get,
    }

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
                   # The checker may have quota-degraded to the fallback model —
                   # report what actually ran, not what was configured.
                   "checker": ((_AI_LAST_RUN.get("gemModel") or _GEMINI_JUDGE_MODEL)
                               if gem_status == "live" else None)},
        "summaryJa": summary[:400], "marketRiskJa": market_risk[:400], "labels": labels,
        "globalRedFlags": global_flags, "groundingSources": grounding,
    }
    if status != "mock":
        _AI_RESULT_CACHE["data"] = payload
        _AI_RESULT_CACHE["expires"] = time.time() + _AI_CACHE_TTL
    _AI_LAST_RUN.update({"oai": oai_status, "gem": gem_status,
                         "groundingEnabled": grounding_enabled, "at": _ai_now_iso()})
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
    if not _OPENAI_API_KEY and not GEMINI_API_KEY:
        return jsonify(_ai_disabled_payload(
            "missing_keys", "AI judgment is enabled but no OpenAI/Gemini API key is configured on the server."))
    cached = _ai_cached_result()
    if cached:
        run_mode = "restored" if cached.get("runMode") == "restored" else "cached"
        return jsonify({**cached, "runMode": run_mode})
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

@app.route("/api/argus/ai-provider-status")
def api_argus_ai_provider_status():
    # Admin-gated AI provider diagnostics. Returns SAFE booleans/status only —
    # never the key values, never a model call. 503 if admin token unconfigured,
    # 401 if missing/wrong.
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    t = _ai_judgment_truth()
    with _AI_LOCK:
        today = datetime.now(TZ_JST).strftime("%Y-%m-%d")
        count = _AI_GATE_STATE["count"] if _AI_GATE_STATE["date"] == today else 0
    expires_at = (datetime.fromtimestamp(_AI_RESULT_CACHE["expires"], pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                  if _AI_RESULT_CACHE["data"] and _AI_RESULT_CACHE["expires"] else None)
    return jsonify({
        "asOf": _ai_now_iso(),
        "adminTokenConfigured": bool(_ARGUS_ADMIN_TOKEN),
        "aiJudgeEnabled": _AI_JUDGE_ENABLED,
        "openai": {
            "apiKeyConfigured": bool(_OPENAI_API_KEY),
            "model": _OPENAI_MODEL,
            "lastRunStatus": _AI_LAST_RUN.get("oai"),
            "lastErrorType": None,
        },
        "gemini": {
            "apiKeyConfigured": bool(GEMINI_API_KEY),
            "model": _GEMINI_JUDGE_MODEL,
            "lastRunStatus": _AI_LAST_RUN.get("gem"),
            "groundingAvailable": (bool(google_genai) if GEMINI_API_KEY else None),
            "lastErrorType": _AI_LAST_RUN.get("gemError"),
        },
        "cache": {
            "hasCachedResult": t["hasCachedResult"],
            "expiresAt": expires_at,
            "status": t["cachedStatus"],
        },
        "runGate": {
            "runCountToday": count,
            "dailyLimit": _AI_JUDGE_MAX_RUNS,
            "minIntervalMinutes": _AI_JUDGE_MIN_INTERVAL,
            "locked": _is_locked(),
            "allowedCountries": _AI_JUDGE_ALLOW_COUNTRIES,
        },
    })


@app.route("/api/argus/ai-provider-status/ping", methods=["POST"])
def api_argus_ai_provider_ping():
    """Admin-only MINIMAL test call to each AI provider ("reply: pong") so a
    renewed key can be verified in one command without burning a full judgment
    run. Costs a few tokens. Never returns key values; error type + a short
    provider message only."""
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    out = {"asOf": _ai_now_iso()}

    if not _OPENAI_API_KEY:
        out["openai"] = {"ok": False, "error": "missing_key"}
    else:
        try:
            import openai
            client = openai.OpenAI(api_key=_OPENAI_API_KEY)
            try:
                r = client.responses.create(model=_OPENAI_MODEL,
                                            input="Reply with the single word: pong", timeout=30)
                reply = (getattr(r, "output_text", "") or "")[:40]
            except Exception:
                r = client.chat.completions.create(
                    model=_OPENAI_MODEL,
                    messages=[{"role": "user", "content": "Reply with the single word: pong"}],
                    timeout=30)
                reply = (r.choices[0].message.content or "")[:40]
            out["openai"] = {"ok": True, "model": _OPENAI_MODEL, "reply": reply}
        except Exception as e:
            out["openai"] = {"ok": False, "model": _OPENAI_MODEL,
                             "error": type(e).__name__, "message": str(e)[:140]}

    if not GEMINI_API_KEY:
        out["gemini"] = {"ok": False, "error": "missing_key"}
    elif not google_genai:
        out["gemini"] = {"ok": False, "error": "sdk_unavailable"}
    else:
        try:
            client = google_genai.Client(api_key=GEMINI_API_KEY)
            r = client.models.generate_content(model=_GEMINI_JUDGE_MODEL,
                                               contents="Reply with the single word: pong")
            out["gemini"] = {"ok": True, "model": _GEMINI_JUDGE_MODEL,
                             "reply": (getattr(r, "text", "") or "")[:40]}
        except Exception as e:
            out["gemini"] = {"ok": False, "model": _GEMINI_JUDGE_MODEL,
                             "error": type(e).__name__, "message": str(e)[:140]}
    return jsonify(out)


# ━━━ News Radar (news-v1, v10.6) — black-swan CAUSE detection ━━━
# The market-REACTION detectors (VIX zones, stress backdrop) catch that
# something happened; this catches WHAT: crisis-grade headlines via GDELT
# (free, keyless, strictly 1 request / 5s → ONE combined query, 30-min cache,
# never refetched on failure within a cool-down). Headline COUNTS are a crude
# proxy — surfaced as 参考(見出しベース), never as verified fact.
_GDELT_DOC = "https://api.gdeltproject.org/api/v2/doc/doc"
_NEWS_THEMES = [
    {"key": "geopolitics", "labelJa": "地政学(侵攻・攻撃)",
     "phrases": ["invasion", "military strike", "missile attack", "declares war"]},
    {"key": "fx_policy", "labelJa": "為替・金融政策の急変",
     "phrases": ["currency intervention", "yen intervention", "emergency rate cut"]},
    {"key": "financial_stress", "labelJa": "金融システム不安",
     "phrases": ["bank collapse", "bank failure", "trading halted", "circuit breaker", "debt default"]},
    {"key": "policy_shock", "labelJa": "緊急会見・政変",
     "phrases": ["emergency press conference", "emergency meeting", "prime minister resigns"]},
    {"key": "disaster", "labelJa": "災害・非常事態",
     "phrases": ["state of emergency", "major earthquake"]},
]
_NEWS_CACHE     = {"data": None, "expires": 0.0}
_NEWS_TTL       = 1800   # 30 min — GDELT politeness
_NEWS_FAIL_TTL  = 600    # back off 10 min after a failure (429 etc.)

def _news_theme_level(count):
    """Headline-count band per theme over the 6h window (transparent)."""
    if count >= 20: return "high"
    if count >= 8:  return "elevated"
    return "calm"

# ── Market News feed (news-v2, v10.12) ───────────────────────────────────────
# GDELT's News Radar counts CRISIS headlines only — a scheduled ECB hike never
# shows up (user caught this gap on 2026-06-11: ECB +0.25% was invisible).
# This feed pulls Finnhub's general market news (free tier) and flags
# market-moving topics so the Top screen surfaces them within minutes.
# Honest limits: headlines are English, unverified, and informational — the
# judgment engine does NOT consume them (reaction-based signals stay primary).
_MARKET_NEWS_CACHE = {"data": None, "expires": 0.0}
_MARKET_NEWS_TTL = 600        # 10 min — Finnhub free tier is generous but finite
_MARKET_NEWS_FAIL_TTL = 300
_NEWS_MAJOR_RE = re.compile(
    r"\b(fed|fomc|ecb|boe|boj|bank of japan|rate (hike|cut|decision)|raises? rates?|"
    r"cuts? rates?|interest rate|intervention|yen|emergency|default|bankruptc|crash|"
    r"tariff|sanction|war|missile|inflation|cpi|jobs report|payrolls|"
    # Geopolitics vocab (2026-06-12: "US will hit Iran" was not flagged):
    r"iran|israel|taiwan|north korea|nuclear|strikes?|attacks?|invasion|opec)\b", re.I)

def _translate_headlines_ja(headlines):
    """Batch-translate headlines via the cheap Gemini flash model. Best-effort:
    any failure returns {} and the UI falls back to English. Called at most
    once per news-cache refill (10 min), so cost is negligible."""
    if not google_genai or not GEMINI_API_KEY or not headlines:
        return {}
    try:
        client = google_genai.Client(api_key=GEMINI_API_KEY)
        prompt = ("以下の英語ニュース見出しを自然な日本語に翻訳してください。固有名詞は一般的な日本語表記、"
                  "誇張や意訳はしない。STRICT JSONのみで返す: {\"translations\": [\"...\"]} 順序は入力どおり、件数も同じ。\n"
                  + json.dumps(headlines, ensure_ascii=False))
        from google.genai import types as _gt
        cfg = _gt.GenerateContentConfig(response_mime_type="application/json")
        resp = client.models.generate_content(model=_GEMINI_FALLBACK_MODEL, contents=prompt, config=cfg)
        out = safe_json(getattr(resp, "text", "") or "")
        tr = out.get("translations") if isinstance(out, dict) else None
        if isinstance(tr, list):
            return {i: str(t)[:200] for i, t in enumerate(tr) if t}
    except Exception as e:
        add_log(f"[news] headline translate failed: {type(e).__name__}")
    return {}

def get_market_news():
    if not FINNHUB_API_KEY:
        return {"status": "missing_key", "asOf": _ai_now_iso(), "items": [],
                "noteJa": "FINNHUB_API_KEY未設定のため市場速報は停止中。"}
    now = time.time()
    if _MARKET_NEWS_CACHE["data"] and now < _MARKET_NEWS_CACHE["expires"]:
        return _MARKET_NEWS_CACHE["data"]
    try:
        r = requests.get("https://finnhub.io/api/v1/news",
                         params={"category": "general", "token": FINNHUB_API_KEY}, timeout=8)
        r.raise_for_status()
        items = []
        for n in (r.json() or [])[:40]:
            h = str(n.get("headline") or "")[:200]
            if not h:
                continue
            items.append({
                "headline": h,
                "source": str(n.get("source") or "")[:40],
                "url": str(n.get("url") or "")[:300],
                "datetime": n.get("datetime"),   # unix seconds
                "major": bool(_NEWS_MAJOR_RE.search(h)),
            })
            if len(items) >= 14:
                break
        # Japanese headlines (news-v2.1): one flash call per 10-min refill.
        tr = _translate_headlines_ja([i["headline"] for i in items])
        for idx, item in enumerate(items):
            if idx in tr:
                item["headlineJa"] = tr[idx]
        out = {"status": "live", "asOf": _ai_now_iso(), "items": items,
               "noteJa": "Finnhub市場ニュース(見出しは自動翻訳・参考情報)。⚡=金融政策/介入/地政学などの重要キーワード検出。判断エンジンには入力されない。"}
        _MARKET_NEWS_CACHE["data"] = out
        _MARKET_NEWS_CACHE["expires"] = now + _MARKET_NEWS_TTL
        return out
    except Exception as e:
        add_log(f"[news] finnhub market news failed: {type(e).__name__}")
        _MARKET_NEWS_CACHE["expires"] = now + _MARKET_NEWS_FAIL_TTL
        return _MARKET_NEWS_CACHE["data"] or {
            "status": "unavailable", "asOf": _ai_now_iso(), "items": [],
            "noteJa": "市場速報を一時取得できません(自動リトライ)。"}

@app.route("/api/argus/market-news")
def api_argus_market_news():
    return jsonify(get_market_news())

def get_news_radar():
    now = time.time()
    if _NEWS_CACHE["data"] is not None and now < _NEWS_CACHE["expires"]:
        return _NEWS_CACHE["data"]

    all_phrases = [p for t in _NEWS_THEMES for p in t["phrases"]]
    q = "(" + " OR ".join(f'"{p}"' if " " in p else p for p in all_phrases) + ") sourcelang:eng"
    themes_out, status = [], "live"
    try:
        r = requests.get(_GDELT_DOC, params={
            "query": q, "mode": "artlist", "maxrecords": 150,
            "timespan": "6h", "format": "json", "sort": "datedesc",
        }, headers={"User-Agent": "argus-news-radar/1.0"}, timeout=25)
        r.raise_for_status()
        body = r.json() if r.text.strip().startswith("{") else {}
        articles = body.get("articles", []) or []
        for t in _NEWS_THEMES:
            hits, seen_domains = [], set()
            for a in articles:
                title = (a.get("title") or "")
                tl = title.lower()
                if any(p.lower() in tl for p in t["phrases"]):
                    dom = a.get("domain") or ""
                    if dom in seen_domains:
                        continue          # one headline per outlet per theme
                    seen_domains.add(dom)
                    hits.append({"title": title[:140], "url": a.get("url", ""),
                                 "source": dom, "seen": a.get("seendate", "")})
            themes_out.append({
                "key": t["key"], "labelJa": t["labelJa"],
                "count": len(hits), "level": _news_theme_level(len(hits)),
                "headlines": hits[:3],
            })
    except Exception:
        status = "unavailable"
        themes_out = [{"key": t["key"], "labelJa": t["labelJa"],
                       "count": 0, "level": "calm", "headlines": []}
                      for t in _NEWS_THEMES]

    levels = [t["level"] for t in themes_out]
    overall = "high" if "high" in levels else "elevated" if "elevated" in levels else "calm"
    top = max(themes_out, key=lambda t: t["count"]) if themes_out else None
    payload = {
        "status": status,
        "asOf": _ai_now_iso(),
        "engineVersion": "news-v1",
        "level": overall if status == "live" else "unknown",
        "topThemeKey": top["key"] if top and top["count"] > 0 else None,
        "themes": themes_out,
        "noteJa": "GDELTの英語ヘッドライン件数(直近6時間・媒体重複除外)による参考指標。事実検証はしていない。",
        "dataLimitations": [
            "見出しの件数ベース(内容の真偽・重要度は未検証)。",
            "英語ソースのみ(日本語ヘッドラインは未対応)。",
            "30分キャッシュ(GDELTのレート制限尊重)。",
        ],
    }
    _NEWS_CACHE["data"] = payload
    _NEWS_CACHE["expires"] = now + (_NEWS_TTL if status == "live" else _NEWS_FAIL_TTL)
    return payload

@app.route("/api/argus/news-radar")
def api_argus_news_radar():
    return jsonify(get_news_radar())


# ━━━ Action Alerts (alerts-v1, v10.4) — one judgment per asset class ━━━
# The user's priority-② layer: gold / REIT / bonds / crypto / FX / cash beside
# the JP/US stock aggregates. Rule-based composition over EXISTING data plus a
# tiny dedicated ETF batch (GLD/TLT/XLRE = 3 Twelve Data credits, 6h cache).
_ALERT_ETF_SYMS  = ["GLD", "TLT", "XLRE"]
_ALERT_ETF_CACHE = {"data": None, "expires": 0.0}
_ALERT_ETF_TTL   = 6 * 3600
_ALERTS_CACHE    = {"data": None, "expires": 0.0}
_ALERTS_TTL      = 600

def _alert_etf_momentum():
    now = time.time()
    if _ALERT_ETF_CACHE["data"] is not None and now < _ALERT_ETF_CACHE["expires"]:
        return _ALERT_ETF_CACHE["data"]
    out = {sym: _etf_momentum(cl) for sym, cl in _td_timeseries(_ALERT_ETF_SYMS).items()}
    if out:
        _ALERT_ETF_CACHE["data"] = out
        _ALERT_ETF_CACHE["expires"] = now + _ALERT_ETF_TTL
    return out

def _alert_action_for_etf(m, cautious):
    """Class action from ETF momentum (pure). m = _etf_momentum dict.
    Conservative vocabulary only — never EXIT/TRIM at the class level in v1."""
    s = m["score"]
    if s >= 0.4:
        return ("WAIT FOR PULLBACK", "med", "med",
                f"直近モメンタムが強く(スコア{s:+.2f})、追いかけ買いは避ける。",
                "押し目の形成を待ち、分割で検討する。")
    if s >= 0.15:
        return ("HOLD", "med", "med" if cautious else "low",
                f"緩やかな上昇トレンド(スコア{s:+.2f})。",
                "トレンドの継続と地合いの変化を確認する。")
    if s > -0.15:
        return (("WAIT" if cautious else "HOLD"), "low", "low",
                f"方向感は限定的(スコア{s:+.2f})。",
                "明確なトレンド発生か地合いの改善を待つ。")
    if s > -0.4:
        return ("WAIT", "med", "med",
                f"軟調(スコア{s:+.2f})。新規は様子見。",
                "下げ止まりと出来高の安定を確認する。")
    return ("WAIT", "med", "high",
            f"下落モメンタムが強い(スコア{s:+.2f})。",
            "売られすぎの反転サインを待つ。")

def get_action_alerts():
    now = time.time()
    if _ALERTS_CACHE["data"] is not None and now < _ALERTS_CACHE["expires"]:
        return _ALERTS_CACHE["data"]

    al     = get_action_labels()
    reg    = get_market_regime_snapshot()
    rates  = get_rates_snapshot()
    crypto = get_crypto_watchlist_snapshot(list(_CRYPTO_DEFAULT_IDS))
    etfs   = _alert_etf_momentum()
    posture  = (al.get("marketPosture", {}) or {}).get("label") or "CAUTIOUS"
    cautious = posture in ("EVENT_WAIT", "RISK_OFF")
    rb = reg.get("ratesBackdrop", {}) if isinstance(reg, dict) else {}
    cards = []

    def add(asset_class, name, action, conf, risk, reason, points, nxt, status):
        cards.append({"assetClass": asset_class, "displayName": name, "action": action,
                      "confidence": conf, "risk": risk, "reasonJa": reason,
                      "dataPoints": points, "nextConditionJa": nxt, "status": status})

    # ── JP / US stock aggregates (from the live label engine) ──
    for mkt, name in (("JP", "Japan Individual Stocks"), ("US", "US Individual Stocks")):
        ls = [l for l in al.get("labels", []) if l["market"] == mkt and l.get("status") == "live"]
        if ls:
            from collections import Counter
            dominant, votes = Counter(l["action"] for l in ls).most_common(1)[0]
            chgs = [l["supportingData"]["changePct"] for l in ls]
            avg = sum(chgs) / len(chgs)
            flows = [l["supportingData"].get("bigFlowRatio") for l in ls
                     if l["supportingData"].get("bigFlowRatio") is not None]
            conf = "high" if votes / len(ls) >= 0.7 else "med"
            risk = "high" if avg <= -2 or cautious else ("low" if abs(avg) < 1 else "med")
            pts = [f"監視{len(ls)}銘柄 平均{avg:+.2f}%", f"多数派ラベル: {dominant} ({votes}/{len(ls)})"]
            if flows:
                pts.append(f"大口フロー平均 {sum(flows)/len(flows):+.1%} ({len(flows)}銘柄)")
            add(f"{mkt}_STOCK", name, dominant, conf, risk,
                f"ウォッチ銘柄の多数派は{dominant}。姿勢は{posture}。",
                pts, "個別はWatchlistの戦略カードで確認。", "live")
        else:
            add(f"{mkt}_STOCK", name, "WAIT", "low", "med",
                "ライブ価格が未取得のため中立。", [], "データ復帰後に再評価。", "partial")

    # ── Gold / Bonds / REIT (dedicated ETF momentum) ──
    for sym, cls, name, extra in (
            ("GLD", "GOLD", "Gold (GLD)", "stress" ),
            ("TLT", "BOND", "Bonds (TLT)", "rates"),
            ("XLRE", "REIT", "REITs (XLRE)", "rates")):
        m = etfs.get(sym)
        if m:
            action, conf, risk, reason, nxt = _alert_action_for_etf(m, cautious)
            if extra == "rates" and rb.get("posture") == "tightening":
                reason += " 金利上昇がデュレーション資産の逆風。"
                if action == "HOLD":
                    action = "WAIT"
            if extra == "stress" and (cautious or rb.get("posture") == "stress"):
                reason += " リスク回避局面ではヘッジ需要が支え。"
            pts = [f"5d {m['momentum5d']}% / 20d {m['momentum20d']}%" if m.get("momentum20d") is not None
                   else f"1d {m['momentum1d']}%"]
            add(cls, name, action, conf, risk, reason, pts, nxt, "live")
        else:
            add(cls, name, "WAIT", "low", "med", "ETFデータ未取得のため中立。", [],
                "データ取得後に再評価。", "partial")

    # ── Crypto (CoinGecko 24h) ──
    q = {x["id"]: x for x in (crypto.get("quotes") or []) if x.get("status") == "live"}
    if q:
        btc, eth = q.get("bitcoin"), q.get("ethereum")
        chg = btc["changePct"] if btc else (eth["changePct"] if eth else 0.0)
        if chg <= -5:   act, cf, rk, rs = "WAIT", "med", "high", f"BTC 24hで{chg:+.1f}%と急落。落ちるナイフは拾わない。"
        elif chg >= 5:  act, cf, rk, rs = "WAIT FOR PULLBACK", "med", "high", f"BTC 24hで{chg:+.1f}%と急伸。追いかけは避ける。"
        elif cautious:  act, cf, rk, rs = "WAIT", "med", "high", f"値動きは限定的({chg:+.1f}%)だが、{posture}局面の高ベータ資産は様子見。"
        else:           act, cf, rk, rs = "HOLD", "low", "high", f"24h {chg:+.1f}%。明確な方向感なし。"
        pts = []
        if btc: pts.append(f"BTC ${btc['priceUsd']:,.0f} ({btc['changePct']:+.1f}%/24h)")
        if eth: pts.append(f"ETH ${eth['priceUsd']:,.0f} ({eth['changePct']:+.1f}%/24h)")
        add("CRYPTO", "Crypto (BTC/ETH)", act, cf, rk, rs, pts,
            "BTCの方向確定とレジームの変化を確認。", "live")
    else:
        add("CRYPTO", "Crypto (BTC/ETH)", "WAIT", "low", "high",
            "ライブ価格未取得のため中立。", [], "データ復帰後に再評価。", "partial")

    # ── USD/JPY (FRED daily) ──
    uj = rates.get("usdJpy") if isinstance(rates, dict) else None
    if uj and uj.get("status") == "live":
        lvl, chg = uj["latestValue"], uj["change"]
        if abs(chg) >= 1.5:
            add("USDJPY", "USD/JPY", "WAIT", "med", "high",
                f"前日比{chg:+.2f}円と値幅が大きい。急変・介入警戒。",
                [f"USD/JPY {lvl} ({chg:+.2f}/日次)"], "値動きの沈静化を確認。", "live")
        else:
            add("USDJPY", "USD/JPY", "HOLD", "low", "med",
                f"USD/JPY {lvl}。日次の値幅は通常圏({chg:+.2f}円)。",
                [f"USD/JPY {lvl} ({chg:+.2f}/日次)"], "急変時(±1.5円/日)に再評価。", "live")
    else:
        add("USDJPY", "USD/JPY", "HOLD", "low", "med", "為替データ未取得。", [], "—", "partial")

    # ── Cash (posture inverse) ──
    if cautious:
        add("CASH", "Cash (待機資金)", "ADD", "med", "low",
            f"{posture}局面では待機資金を厚めに保ち、押し目に備える。",
            [f"姿勢: {posture}"], "イベント通過/レジーム改善で再配分を検討。", "live")
    elif posture == "RISK_ON":
        add("CASH", "Cash (待機資金)", "HOLD", "low", "low",
            "リスク選好局面。過剰な現金は機会損失にも注意(無理な投入はしない)。",
            [f"姿勢: {posture}"], "レジーム悪化で現金比率を引き上げ。", "live")
    else:
        add("CASH", "Cash (待機資金)", "HOLD", "low", "low",
            "中立。現金比率は計画通りを維持。", [f"姿勢: {posture}"],
            "姿勢の変化に応じて調整。", "live")

    live_n = sum(1 for c in cards if c["status"] == "live")
    payload = {
        "status": "live" if live_n == len(cards) else ("partial" if live_n else "mock"),
        "asOf": _ai_now_iso(),
        "engineVersion": "alerts-v1",
        "posture": posture,
        "cards": cards,
    }
    if live_n:
        _ALERTS_CACHE["data"] = payload
        _ALERTS_CACHE["expires"] = now + _ALERTS_TTL
    return payload

@app.route("/api/argus/action-alerts")
def api_argus_action_alerts():
    return jsonify(get_action_alerts())


# ━━━ Backup vault relay (v10.3.4) ━━━
# The browser pushes a CLIENT-SIDE-ENCRYPTED backup envelope here; the daily
# prediction-ledger workflow pulls it (admin token) and commits the ciphertext
# to the public `ledger` branch (vault/<id>/latest.json). The backend never
# sees plaintext, holds blobs only in bounded memory, and the vault id is a
# hash of the user's passphrase — unguessable, and useless without it.
_VAULT_SLOTS     = {}                 # vaultId -> {"blob": str, "ts": epoch}
_VAULT_MAX_SLOTS = 10                 # bounded memory on a public endpoint
_VAULT_MAX_BYTES = 256 * 1024
_VAULT_ID_RE     = re.compile(r"^[0-9a-f]{64}$")

@app.route("/api/argus/vault-push", methods=["POST"])
def api_argus_vault_push():
    body = request.get_json(silent=True) or {}
    vid  = str(body.get("vaultId") or "")
    blob = body.get("blob")
    if not _VAULT_ID_RE.match(vid) or not isinstance(blob, str) or not blob:
        return jsonify({"error": "bad_payload"}), 400
    if len(blob) > _VAULT_MAX_BYTES:
        return jsonify({"error": "too_large"}), 413
    if vid not in _VAULT_SLOTS and len(_VAULT_SLOTS) >= _VAULT_MAX_SLOTS:
        oldest = min(_VAULT_SLOTS, key=lambda k: _VAULT_SLOTS[k]["ts"])
        del _VAULT_SLOTS[oldest]
    _VAULT_SLOTS[vid] = {"blob": blob, "ts": time.time()}
    return jsonify({"ok": True, "queued": len(_VAULT_SLOTS),
                    "noteJa": "受領。次回の台帳ラン(平日16:05)でクラウド(GitHub)に保存されます。"})

@app.route("/api/argus/vault-relay")
def api_argus_vault_relay():
    """Non-destructive read of the latest pushed envelope for a vault id —
    the near-realtime half of cross-device sync (sync-v1, v10.10). The durable
    half remains the daily ledger commit. Ciphertext only; the vault id is
    unguessable (SHA-256 derived from the passphrase on-device)."""
    vid = str(request.args.get("vaultId") or "")
    if not _VAULT_ID_RE.match(vid):
        return jsonify({"error": "bad_vault_id"}), 400
    s = _VAULT_SLOTS.get(vid)
    if not s:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"ts": s["ts"], "blob": s["blob"]})

@app.route("/api/argus/vault-pull", methods=["POST"])
def api_argus_vault_pull():
    # Admin-only drain: the ledger workflow collects pending envelopes and
    # persists them to git. Ciphertext in, ciphertext out. Slots are KEPT
    # (sync-v1: /vault-relay reads them between daily commits) — re-draining
    # the same envelope is a no-op for git, and memory stays bounded at
    # _VAULT_MAX_SLOTS either way.
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    out = {vid: {"blob": s["blob"], "ts": s["ts"]} for vid, s in _VAULT_SLOTS.items()}
    return jsonify({"slots": out, "asOf": _ai_now_iso()})


# ━━━ Integration Health (public, secret-free) ━━━
# Summarizes provider configuration + runtime status for the frontend. Reads
# env presence (booleans only) and existing cached snapshots — NEVER exposes a
# key, NEVER calls OpenAI/Gemini, and avoids forcing expensive refetches.
_INTEGRATIONS_CACHE = {"data": None, "expires": 0.0}
_INTEGRATIONS_TTL   = 120  # 2 min — cheap, but coalesce bursts

_NEXT_RECOMMENDED_APIS = [
    "coingecko-crypto-watchlist",
    "alerts-scanner-live",
    "moomoo-flow-vwap-orderbook",
    "portfolio-exposure-layer",
    "what-if-simulator",
]

def get_integrations_snapshot():
    now = time.time()
    if _INTEGRATIONS_CACHE["data"] is not None and now < _INTEGRATIONS_CACHE["expires"]:
        return _INTEGRATIONS_CACHE["data"]

    # Market-data runtime status comes from the same cached getters the pages use
    # (cheap when warm). AI status comes from the key-aware truth helper (no call).
    rates = get_rates_snapshot()
    jp    = get_japan_watchlist_snapshot()
    us    = get_us_watchlist_snapshot()
    def _st(x):
        return x.get("status", "unknown") if isinstance(x, dict) else "unknown"
    fred_rt = _st(rates)
    jq_rt   = _st(jp)
    td_rt   = _st(us)

    ai = _ai_judgment_truth()
    # OpenAI / Gemini runtime status, key-aware and honest.
    if not ai["enabled"]:
        oai_rt = "disabled" if bool(_OPENAI_API_KEY) else "missing"
        gem_rt = "disabled" if bool(GEMINI_API_KEY) else "missing"
    else:
        oai_rt = ("missing" if not _OPENAI_API_KEY else
                  ("live" if ai["status"] == "live" else
                   ("partial" if ai["status"] == "partial" else "no_cached_result")))
        gem_rt = ("missing" if not GEMINI_API_KEY else
                  ("live" if ai["status"] == "live" else
                   ("partial" if ai["status"] == "partial" else "no_cached_result")))

    providers = [
        {"id": "fred", "label": "FRED", "category": "market_data",
         "configured": bool(_FRED_API_KEY), "runtimeStatus": fred_rt if _FRED_API_KEY else "missing",
         "usedFor": ["rates", "market-regime"], "lastKnownStatus": fred_rt,
         "notesJa": "金利・VIX・HY OASに使用。"},
        {"id": "jquants", "label": "J-Quants", "category": "market_data",
         "configured": bool(_JQUANTS_API_KEY), "runtimeStatus": jq_rt if _JQUANTS_API_KEY else "missing",
         "usedFor": ["japan-watchlist", "catalysts", "market-regime"], "lastKnownStatus": jq_rt,
         "notesJa": "日本株価格・決算/開示メタデータ・日本レジームproxyに使用。"},
        {"id": "twelvedata", "label": "Twelve Data", "category": "market_data",
         "configured": bool(_TWELVEDATA_API_KEY), "runtimeStatus": td_rt if _TWELVEDATA_API_KEY else "missing",
         "usedFor": ["us-watchlist", "market-regime"], "lastKnownStatus": td_rt,
         "notesJa": "米国株価格・ETFレジームproxyに使用。"},
        {"id": "finnhub", "label": "Finnhub", "category": "news_catalyst",
         "configured": bool(FINNHUB_API_KEY), "runtimeStatus": ("live" if FINNHUB_API_KEY else "missing"),
         "usedFor": ["corporate-catalysts"], "lastKnownStatus": ("live" if FINNHUB_API_KEY else "missing"),
         "notesJa": "未設定なら米国ニュース/決算カレンダーはpartial。"},
        {"id": "openai", "label": "OpenAI GPT-5.5", "category": "ai",
         "configured": bool(_OPENAI_API_KEY), "runtimeStatus": oai_rt,
         "usedFor": ["ai-judgment"], "lastKnownStatus": _AI_LAST_RUN.get("oai"),
         "notesJa": "APIキーとAI_JUDGE_ENABLEDが必要。ChatGPT Proとは別請求。"},
        {"id": "gemini", "label": "Gemini", "category": "ai",
         "configured": bool(GEMINI_API_KEY), "runtimeStatus": gem_rt,
         "usedFor": ["ai-judgment-double-check"], "lastKnownStatus": _AI_LAST_RUN.get("gem"),
         "notesJa": "OpenAI判断の二重チェック用。"},
        {"id": "coingecko", "label": "CoinGecko", "category": "market_data",
         "configured": True,  # keyless — no API key required
         "runtimeStatus": _crypto_last_status(),
         "usedFor": ["crypto-watchlist"], "lastKnownStatus": _crypto_last_status(),
         "notesJa": "BTC/ETH等のライブUSD価格(キー不要・無料、10分キャッシュ)。"},
        {"id": "moomoo", "label": "moomoo OpenAPI (bridge)", "category": "flow_orderbook",
         "configured": _push_last_age_sec() is not None,
         "runtimeStatus": ("live" if (_push_last_age_sec() or 1e9) <= 900 else
                           "stale" if _push_last_age_sec() is not None else
                           "pending_local_validation"),
         "usedFor": ["realtime-quotes", "flow", "orderbook", "vwap"],
         "lastKnownStatus": (f"last push {int(_push_last_age_sec())}s ago"
                             if _push_last_age_sec() is not None else None),
         "notesJa": "ローカルOpenD→quote-pushブリッジ経由のリアルタイム価格。push途絶時はJ-Quants/Twelve Dataへ自動フォールバック。"},
    ]

    # Overall: live only if the 3 core market-data providers are live.
    core = [fred_rt, jq_rt, td_rt]
    live_n = sum(1 for s in core if s == "live")
    overall = "live" if live_n == 3 else ("partial" if live_n >= 1 else "degraded")

    payload = {
        "status": overall,
        "asOf": _ai_now_iso(),
        "engineVersion": "integrations-v1",
        "providers": providers,
        "aiJudgment": {
            "enabled": ai["enabled"],
            "openaiConfigured": ai["openaiConfigured"],
            "geminiConfigured": ai["geminiConfigured"],
            "adminTokenConfigured": ai["adminTokenConfigured"],
            "hasCachedResult": ai["hasCachedResult"],
            "cachedStatus": ai["cachedStatus"],
            "lastRunAt": ai["lastRunAt"],
            "publicGetStatus": ai["publicGetStatus"],
            "truthStatus": ai["status"],
        },
        "nextRecommendedApis": list(_NEXT_RECOMMENDED_APIS),
    }
    _INTEGRATIONS_CACHE["data"] = payload
    _INTEGRATIONS_CACHE["expires"] = now + _INTEGRATIONS_TTL
    return payload

@app.route("/api/argus/integrations")
def api_argus_integrations():
    return jsonify(get_integrations_snapshot())


# ━━━ Context-aware VIX signal (v9.12) ━━━
# A fixed "VIX crossed N" alert is a magic number. The essential read is:
#   velocity (how fast fear is rising) × position vs ITS OWN recent regime
#   (60-day percentile) × broad absolute sanity bands.
# Alerts fire on ZONE TRANSITIONS and SPIKES, never on one hardcoded level.
_VIX_HIST_CACHE = {"data": None, "expires": 0.0}
_VIX_HIST_TTL   = 3600  # 1h — daily series, no need to hammer FRED

def _fred_vix_history(n=70):
    """Newest-first VIX closes (~n obs) from FRED. [] on no key / failure."""
    now = time.time()
    if _VIX_HIST_CACHE["data"] is not None and now < _VIX_HIST_CACHE["expires"]:
        return _VIX_HIST_CACHE["data"]
    if not _FRED_API_KEY:
        return []
    try:
        r = requests.get(_FRED_BASE, params={
            "series_id": "VIXCLS", "api_key": _FRED_API_KEY, "file_type": "json",
            "sort_order": "desc", "limit": n + 10,
        }, timeout=8)
        r.raise_for_status()
        closes = [float(o["value"]) for o in r.json().get("observations", [])
                  if o.get("value") not in (None, ".", "")][:n]
        if len(closes) >= 10:
            _VIX_HIST_CACHE["data"] = closes
            _VIX_HIST_CACHE["expires"] = now + _VIX_HIST_TTL
        return closes
    except Exception:
        return _VIX_HIST_CACHE["data"] or []

def _vix_assess(closes):
    """Context-aware VIX read from a newest-first close list (pure, testable).

    zone: calm / normal / elevated / shock —
      - spike   = day-over-day velocity (+15% AND +2pt, or +5pt) — fear is
                  accelerating regardless of the absolute level
      - elevated= top quintile of ITS OWN trailing 60 days (and not trivially
                  low), or an absolute 25+ where index option pricing implies
                  outsized daily swings
      - shock   = 30+, or a spike landing at an already-elevated 24+
    Broad bands are sanity floors, not triggers — alerts react to TRANSITIONS.
    """
    if not closes:
        return None
    level = float(closes[0])
    prev  = float(closes[1]) if len(closes) > 1 else level
    chg     = round(level - prev, 2)
    chg_pct = round((chg / prev) * 100, 1) if prev else 0.0
    window = [float(v) for v in closes[:60]]
    med  = round(statistics.median(window), 1)
    rank = int(round(100.0 * sum(1 for v in window if v <= level) / len(window)))
    spike = (chg_pct >= 15 and chg >= 2) or chg >= 5
    if level >= 30 or (spike and level >= 24):
        zone, zone_ja = "shock", "ショック圏(恐怖の急拡大)"
    elif (rank >= 80 and level >= 18) or level >= 25:
        zone, zone_ja = "elevated", "警戒圏(直近レンジの上限域)"
    elif level < 14 and not spike:
        # A flat low-vol regime is calm by absolute level — every day of a
        # flat series sits at its own 100th percentile, so rank can't be used.
        zone, zone_ja = "calm", "凪(低ボラティリティ)"
    else:
        zone, zone_ja = "normal", "通常圏"
    note = "急騰・" + zone_ja if spike else zone_ja
    return {
        "level": round(level, 1), "changeAbs": chg, "changePct1d": chg_pct,
        "median60d": med, "percentile60d": rank, "spike": spike, "zone": zone,
        "zoneJa": zone_ja, "historyDays": len(window),
        "rationaleJa": (f"VIX {round(level, 1)} — {note}。"
                        f"前日比{chg:+.1f}({chg_pct:+.1f}%)・直近{len(window)}日分布の{rank}パーセンタイル(中央値{med})。"),
    }


# ━━━ Prediction Ledger snapshot (ledger-v1) — the self-scoring loop ━━━
# Composes TODAY's falsifiable per-symbol predictions in a scoreable format.
# A GitHub Actions cron records this daily to the repo's `ledger` branch and
# scores past snapshots against realized moves — accumulating, per context
# (posture / VIX zone / flow), how often the rule engine and the AI were right.
# ARGUS still does not "predict" — it states scenario DISTRIBUTIONS and gets
# graded on them (Brier score + argmax hit), which is the honest way to learn.

# ── ledger-v3: 3-layer learning universe ─────────────────────────────────────
# Finalized 2026-06-11 after the user's ChatGPT/Gemini consultation.
#   Layer 1 — FIXED 16 regime sensors: the calibration backbone, never churned.
#             Idiosyncratic names (9984, 7011) were deliberately moved OUT and
#             USD/JPY + VIX added for macro judgment.
#   Layer 2 — active tactical watchlist (the battlefield names, free to swap).
#   Layer 3 — experimental / high-noise names, aggregated separately so they
#             never pollute Layer-1 statistics.
_L1_SENSORS_JP = [
    ("1306", "TOPIX ETF"), ("1321", "Nikkei 225 ETF"),
    ("8306", "Mitsubishi UFJ"), ("7203", "Toyota Motor"),
    ("8058", "Mitsubishi Corporation"), ("9432", "NTT"),
]
_L1_SENSORS_US = ["SPY", "QQQ", "SMH", "IWM", "TLT", "HYG", "GLD"]
# + BTC (crypto), USDJPY (fx), VIX (vol) = 16 sensors total.
# Scenario band per sensor kind ≈ one rough daily sigma, so "sideways" means
# the same thing for an FX pair (σ≈0.5%) as for an equity ETF (σ≈2%), BTC
# (σ≈3%) or the VIX itself (σ≈8%). Band units, not fixed magic levels.
_SENSOR_BAND_PCT = {"equity_jp": 2.0, "etf_us": 2.0, "crypto": 3.0, "fx": 0.5, "vol": 8.0}
_LAYER3_SYMBOLS = {"6584"}

def _layer_of(symbol):
    """Tactical-prediction layer attribution (pure). 8058 doubles as a Layer-1
    sensor, so its stock row counts toward Layer 1; explicit high-noise names
    go to Layer 3; everything else is the active tactical Layer 2."""
    if symbol in _LAYER3_SYMBOLS:
        return 3
    if symbol == "8058":
        return 1
    return 2

def _scenarios_scaled(chg, band_pct):
    """Scenario distribution in BAND units: the ±2%-tuned thresholds of
    _scenarios_for are reused by rescaling the move into each sensor's own
    daily-sigma band (e.g. a 0.5% USDJPY move ≙ a 2% equity move)."""
    if chg is None:
        return _scenarios_for(None)
    return _scenarios_for(chg * (2.0 / band_pct))

def _sensor_row(sensor_id, name, kind, price, chg):
    band = _SENSOR_BAND_PCT[kind]
    return {"sensor": sensor_id, "name": name, "kind": kind,
            "price": price, "changePct": chg, "bandPct": band,
            "scenarios": [{"label": s, "p": p} for s, p in _scenarios_scaled(chg, band)]}

# Layer-1 sensor ETFs not covered by the regime/alerts Twelve Data universes
# (currently just SMH). 6h cache = 1 extra TD credit per 6 hours.
_SENSOR_ETF_EXTRA = ["SMH"]
_SENSOR_ETF_CACHE = {"expires": 0.0}

def _ensure_sensor_etfs():
    now = time.time()
    if now < _SENSOR_ETF_CACHE["expires"]:
        return
    missing = [s for s in _SENSOR_ETF_EXTRA
               if not (_ETF_LAST_PRICE.get(s) and now - _ETF_LAST_PRICE[s]["ts"] <= 6 * 3600)]
    if missing:
        _td_timeseries(missing)  # stashes into _ETF_LAST_PRICE as a side effect
    _SENSOR_ETF_CACHE["expires"] = now + 6 * 3600

def _scenarios_for(chg):
    """Server-side port of the frontend scenario distribution (same thresholds).
    Returns [(label, probability)] summing to 100, from the daily change %."""
    if chg is None:
        return [("downside_continuation", 33), ("sideways_stabilization", 34), ("rebound_attempt", 33)]
    if chg <= -7: return [("downside_continuation", 45), ("sideways_stabilization", 40), ("rebound_attempt", 15)]
    if chg <= -3: return [("downside_continuation", 40), ("sideways_stabilization", 40), ("rebound_attempt", 20)]
    if chg < 2:   return [("downside_continuation", 30), ("sideways_stabilization", 50), ("rebound_attempt", 20)]
    if chg < 5:   return [("downside_continuation", 25), ("sideways_stabilization", 50), ("rebound_attempt", 25)]
    return [("downside_continuation", 30), ("sideways_stabilization", 45), ("rebound_attempt", 25)]

# ── Entry Scout (entry-scout-v1, v10.15) ─────────────────────────────────────
# 「個別株の買いの入りは瞬間的な情報収集が要る」(ユーザー、2026-06-13 — 9984を
# 6450で取った日の振り返りから)。1銘柄を1タップで診断する: トレンド/過熱
# (J-Quants日次履歴)+大口フロー(moomoo)+イベント接近+地合い+曜日を束ねて
# 「攻め好機/押し目待ち/中立/見送り」+理由+正直な未対応リストを即答する。
# Phase 2 予定: 日証金・信用残、チャートパターン形状、米国株対応。
_JQ_HISTORY_CACHE = {}          # code -> {"data": {...}|None, "expires": epoch}
_JQ_HISTORY_TTL = 6 * 3600
_SCOUT_CACHE = {}               # code -> {"data": ..., "expires": epoch}
_SCOUT_TTL = 1800
# Weekly margin interest (信用取引週末残高) — answers the user's question
# "is the big-money move a short-covering bounce or fresh buying?" (2026-06-13).
# PLAN-DEPENDENT on J-Quants: if the key's plan does not include it, the fetch
# returns None and the scout honestly lists it as unavailable (NEVER guesses).
_JQ_MARGIN_CACHE = {}           # code -> {"data": [...]|None, "expires": epoch}
_JQ_MARGIN_TTL = 12 * 3600      # weekly data — refreshed twice a day is plenty
# 日証金(JSF)貸借取引残高 — the FREE daily alternative when the J-Quants plan
# omits weekly margin (user-approved 2026-06-13). One public CSV holds every
# 貸借銘柄's loan balance (融資残=margin-buy side) and stock-lending balance
# (貸株残=margin-sell/short side); 貸借倍率=融資残/貸株残 is the classic
# short-covering gauge. Column layout VERIFIED against the live file header,
# Shift_JIS. Non-loanable stocks are simply absent (honest gap, never faked).
_JSF_URL = "https://www.taisyaku.jp/data/zandaka.csv"
_JSF_CACHE = {"table": None, "date": None, "expires": 0.0}
_JSF_TTL = 6 * 3600

def _jq_price_history(code):
    """~60-90 trading days of closes/volumes (newest-first) for one TSE code.
    Same daily-bars endpoint the watchlist uses; 6h cache, 10-min fail back-off."""
    now = time.time()
    c = _JQ_HISTORY_CACHE.get(code)
    if c and now < c["expires"]:
        return c["data"]
    data = None
    if _JQUANTS_API_KEY:
        try:
            headers = {"x-api-key": _JQUANTS_API_KEY}
            frm = (datetime.now(TZ_JST) - timedelta(days=130)).strftime("%Y-%m-%d")
            rows, params = [], {"code": code, "from": frm}
            for _ in range(6):
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
            rows.sort(key=lambda q: q.get("Date", ""), reverse=True)   # newest first
            if len(rows) >= 20:
                data = {"closes": [float(_q_close(q)) for q in rows],
                        "volumes": [int(q.get("Vo") or 0) for q in rows],
                        "dates": [q.get("Date") for q in rows]}
        except Exception as e:
            add_log(f"[scout] history fetch failed {code}: {type(e).__name__}")
    _JQ_HISTORY_CACHE[code] = {"data": data, "expires": now + (_JQ_HISTORY_TTL if data else 600)}
    return data

def _jq_weekly_margin(code):
    """Latest two weekly margin-interest rows for one TSE code, newest-first.
    Returns a list of normalized dicts {date, longVol, shortVol} or None if the
    J-Quants plan does not include this endpoint (403/404) or it is empty. The
    documented v2 fields are LongMarginTradeVolume (信用買い残) and
    ShortMarginTradeVolume (信用売り残); missing fields → row skipped, never faked."""
    now = time.time()
    c = _JQ_MARGIN_CACHE.get(code)
    if c and now < c["expires"]:
        return c["data"]
    data = None
    if _JQUANTS_API_KEY:
        try:
            headers = {"x-api-key": _JQUANTS_API_KEY}
            frm = (datetime.now(TZ_JST) - timedelta(days=90)).strftime("%Y-%m-%d")
            r = requests.get(f"{_JQUANTS_BASE}/markets/weekly_margin_interest",
                             headers=headers, params={"code": code, "from": frm}, timeout=10)
            if r.status_code == 200:
                rows = (r.json() or {}).get("data", []) or []
                norm = []
                for q in rows:
                    lv = q.get("LongMarginTradeVolume")
                    sv = q.get("ShortMarginTradeVolume")
                    if lv is None or sv is None:
                        continue
                    norm.append({"date": q.get("Date"), "longVol": float(lv), "shortVol": float(sv)})
                norm.sort(key=lambda x: x["date"] or "", reverse=True)
                if norm:
                    data = norm[:4]
            # 403/404 → plan does not include it → leave data None (honest gap)
        except Exception as e:
            add_log(f"[scout] margin fetch failed {code}: {type(e).__name__}")
    # On failure cache a short empty window so we retry, but a real None (plan
    # gap) is cached for the full TTL — no point hammering an endpoint the plan
    # will keep refusing.
    _JQ_MARGIN_CACHE[code] = {"data": data, "expires": now + (_JQ_MARGIN_TTL if data is not None else 1800)}
    return data

def _margin_signal(rows):
    """Pure (unit-tested): newest-first weekly margin rows → a short-covering /
    fresh-buying read. None when <2 weeks. Credit ratio = long/short (>1 買い長,
    <1 売り長). Week-over-week deltas reveal which side is building."""
    if not rows or len(rows) < 2:
        return None
    cur, prev = rows[0], rows[1]
    long_v, short_v = cur["longVol"], cur["shortVol"]
    ratio = round(long_v / short_v, 2) if short_v else None
    d_long = (long_v - prev["longVol"]) / prev["longVol"] * 100 if prev["longVol"] else 0.0
    d_short = (short_v - prev["shortVol"]) / prev["shortVol"] * 100 if prev["shortVol"] else 0.0
    return {
        "date": cur["date"], "creditRatio": ratio,
        "longVol": long_v, "shortVol": short_v,
        "longWoWPct": round(d_long, 1), "shortWoWPct": round(d_short, 1),
    }

def _margin_assess_lines(sig):
    """Pure: margin signal → (score_delta, reasonsJa[]). Short-covering fuel is
    a tailwind; ballooning long balance is overhang. All contributions visible."""
    if not sig:
        return 0.0, []
    score, reasons = 0.0, []
    r = sig.get("creditRatio")
    if isinstance(r, (int, float)):
        if r < 1.0:
            score += 0.5
            reasons.append(f"信用倍率{r}倍(売り長) — 買い戻し(踏み上げ)の余地")
        elif r >= 5.0:
            score -= 0.5
            reasons.append(f"信用倍率{r}倍(買い長) — 上値に戻り売り圧力")
    if sig.get("shortWoWPct", 0) >= 15:
        score += 0.5
        reasons.append(f"信用売り残が前週比+{sig['shortWoWPct']}% — 将来の買い戻し圧力が蓄積")
    if sig.get("longWoWPct", 0) >= 15:
        score -= 0.5
        reasons.append(f"信用買い残が前週比+{sig['longWoWPct']}% — 新規買いの過熱(戻り売り予備軍)")
    return score, reasons

def _jsf_balance_table():
    """{code: {loan, short, net, loanNew, loanRepay, shortNew, shortRepay}} from
    the JSF daily 貸借取引残高 CSV. 6h cache; never raises. Column indices are
    fixed against the verified Shift_JIS header (申込日,決済日,銘柄コード,…)."""
    now = time.time()
    if _JSF_CACHE["table"] is not None and now < _JSF_CACHE["expires"]:
        return _JSF_CACHE["table"], _JSF_CACHE["date"]
    table, dt = None, None
    try:
        # Browser-ish UA + 30s: the 858KB file is fetched US→JP from Render.
        r = requests.get(_JSF_URL, timeout=30,
                         headers={"User-Agent": "Mozilla/5.0 (ARGUS bridge)"})
        if r.status_code == 200 and r.content:
            text = r.content.decode("cp932", errors="replace")
            import csv as _csv
            import io as _io
            rows = list(_csv.reader(_io.StringIO(text)))
            table = {}
            for row in rows[1:]:
                if len(row) < 14:
                    continue
                code = (row[2] or "").strip()
                if not code:
                    continue
                def _i(idx):
                    v = (row[idx] or "").strip().replace(",", "")
                    try:
                        return int(float(v)) if v else None
                    except Exception:
                        return None
                loan, short = _i(9), _i(12)
                rec = {
                    "loan": loan, "short": short, "net": _i(13),
                    "loanNew": _i(7), "loanRepay": _i(8),
                    "shortNew": _i(10), "shortRepay": _i(11),
                }
                # A code can appear once per exchange (e.g. 7203 東証 + 名証 with
                # the 名証 row all-zero). Keep the row with the most balance so a
                # secondary-venue zero row never clobbers the real 東証 figures.
                prev = table.get(code)
                if prev is None or (loan or 0) + (short or 0) > (prev["loan"] or 0) + (prev["short"] or 0):
                    table[code] = rec
                if dt is None:
                    dt = (row[0] or "").strip()
            if not table:
                table = None
    except Exception as e:
        add_log(f"[scout] JSF fetch failed: {type(e).__name__}")
    _JSF_CACHE.update({"table": table, "date": dt,
                       "expires": now + (_JSF_TTL if table else 1800)})
    return table, dt

def _jsf_for(code):
    """One stock's JSF balance signal, or None if it is not a 貸借銘柄."""
    table, dt = _jsf_balance_table()
    if not table or code not in table:
        return None
    e = table[code]
    loan, short = e.get("loan"), e.get("short")
    if loan is None or short is None:
        return None
    ratio = round(loan / short, 2) if short else None
    return {"date": dt, "loan": loan, "short": short, "net": e.get("net"),
            "ratio": ratio, "loanNew": e.get("loanNew"), "loanRepay": e.get("loanRepay"),
            "shortNew": e.get("shortNew"), "shortRepay": e.get("shortRepay")}

# JPX 空売り残高 (institutional disclosed short positions ≥0.5%) — the
# "are institutions seriously shorting this?" signal the user asked for
# (2026-06-13). The daily .xls URL carries a per-day token, so we scrape the
# index for the latest *_Short_Positions.xls, parse it (legacy OLE2/BIFF via
# xlrd), and aggregate the disclosed short ratio (col10) per stock code
# (col2). Column layout VERIFIED against the live file. Only ~700 heavily
# shorted names appear; absence is itself meaningful (no big institutional
# short on record) and reported honestly — never faked.
_JPX_SHORT_INDEX = "https://www.jpx.co.jp/markets/public/short-selling/index.html"
_JPX_HOST = "https://www.jpx.co.jp"
_JPX_SHORT_CACHE = {"table": None, "date": None, "expires": 0.0}
_JPX_SHORT_TTL = 6 * 3600

def _jpx_short_table():
    """{code: {ratio: summed disclosed short fraction, reporters: int}} from the
    latest JPX short-position .xls. 6h cache; never raises. xlrd imported lazily
    so the test/CI path (which never calls this) needs no extra dependency."""
    now = time.time()
    if _JPX_SHORT_CACHE["table"] is not None and now < _JPX_SHORT_CACHE["expires"]:
        return _JPX_SHORT_CACHE["table"], _JPX_SHORT_CACHE["date"]
    table, dt = None, None
    try:
        import xlrd  # lazy: only the production fetch path needs it
        hdr = {"User-Agent": "Mozilla/5.0 (ARGUS bridge)"}
        idx = requests.get(_JPX_SHORT_INDEX, headers=hdr, timeout=20)
        m = re.search(r'href="(/markets/public/short-selling/[^"]+?_Short_Positions\.xls)"', idx.text)
        if idx.status_code == 200 and m:
            url = _JPX_HOST + m.group(1)
            fn = m.group(1).rsplit("/", 1)[-1]      # 20260611_Short_Positions.xls
            dm = re.match(r"(\d{4})(\d{2})(\d{2})_", fn)
            dt = f"{dm.group(1)}/{dm.group(2)}/{dm.group(3)}" if dm else None
            r = requests.get(url, headers=hdr, timeout=30)
            if r.status_code == 200 and r.content:
                wb = xlrd.open_workbook(file_contents=r.content)
                sh = wb.sheet_by_index(0)
                agg = {}
                for row in range(8, sh.nrows):       # data starts at row 8 (verified)
                    code = str(sh.cell_value(row, 2)).replace(".0", "").strip()
                    try:
                        ratio = float(sh.cell_value(row, 10))
                    except Exception:
                        ratio = None
                    if not code or not ratio:
                        continue
                    e = agg.setdefault(code, {"ratio": 0.0, "reporters": 0})
                    e["ratio"] += ratio
                    e["reporters"] += 1
                if agg:
                    for e in agg.values():
                        e["ratio"] = round(e["ratio"], 4)
                    table = agg
    except Exception as e:
        add_log(f"[scout] JPX short fetch failed: {type(e).__name__}")
    _JPX_SHORT_CACHE.update({"table": table, "date": dt,
                             "expires": now + (_JPX_SHORT_TTL if table else 1800)})
    return table, dt

def _short_disclosed_assess(sd):
    """Pure (unit-tested): disclosed institutional short → (score_delta,
    reasonsJa[]). Heavy disclosed short is squeeze FUEL if price turns — but
    also reflects strong bearish conviction, so the wording says both and the
    score nudge is modest."""
    if not sd or not sd.get("ratio"):
        return 0.0, []
    pct = round(sd["ratio"] * 100, 1)
    n = sd.get("reporters", 0)
    if sd["ratio"] >= 0.05:
        return 0.5, [f"機関の大口空売り残 {pct}%({n}者) — 反転すれば強い踏み上げ燃料(弱気確信の裏返しでもある)"]
    if sd["ratio"] >= 0.02:
        return 0.3, [f"機関の大口空売り残 {pct}%({n}者) — 買い戻し余地あり(両面解釈)"]
    return 0.0, [f"機関の大口空売り残 {pct}%({n}者・小規模)"]

def _catalyst_context(news, regime_label, esc, earnings_days, high_beta):
    """Pure (unit-tested): assemble the MATERIAL/news backdrop a discretionary
    trader actually uses, from free sources already fetched — no AI call (the
    public path must not trigger costly AI). The SoftBank lesson (2026-06-13):
    the trade was driven by the US-tech link + geopolitics news, which the
    chart/flow engine cannot see. This surfaces that context as 参考 (not
    scored — news interpretation is for the human/AI, not a rule)."""
    items = []
    for t in (news.get("themes") or []) if isinstance(news, dict) else []:
        if t.get("level") in ("elevated", "high"):
            head = (t.get("headlines") or [None])[0]
            items.append({"kind": "news", "level": t["level"], "labelJa": t.get("labelJa"),
                          "count": t.get("count"), "headline": head})
    if high_beta:
        items.append({"kind": "link", "labelJa": "米ハイテク連動",
                      "noteJa": "値動きの主因が米NASDAQ/AI株のことが多い銘柄 — 米テックの地合いとレジームを併せて確認"})
    if regime_label in ("RISK_OFF", "EVENT_WAIT"):
        items.append({"kind": "regime", "labelJa": "市場レジーム", "noteJa": f"{regime_label}(地合いが逆風)"})
    if esc in ("D", "D-1"):
        items.append({"kind": "event", "labelJa": "重要イベント接近", "noteJa": f"{esc}(結果待ち)"})
    if isinstance(earnings_days, (int, float)) and 0 <= earnings_days <= 7:
        items.append({"kind": "earnings", "labelJa": "決算接近", "noteJa": f"あと{int(earnings_days)}日"})
    return {"items": items,
            "noteJa": "材料は参考情報(点数化しない)。最終的なニュース解釈はGPT-5.5 Pro相談ボタンやご自身で。"}

def _flow_inference(m, flow_ratio, jsf, short_disclosed):
    """Pure (unit-tested): fuse the in-hand 需給 signals into a PROBABILISTIC
    read of WHO is moving the stock — new buying vs short-covering vs
    distribution vs retail noise. Never a certainty (ChatGPT/Gemini both
    stress this is impossible from external data); confidence drops when data
    is thin, and VWAP/orderbook gaps are stated. Adopted from the 2026-06-13
    Gemini+GPT consult, built only on data ARGUS already fetches."""
    w = {"newLong": 0.0, "shortCovering": 0.0, "distribution": 0.0, "retailNoise": 0.0}
    reasons, have = [], 0
    ret1 = m.get("ret1") or 0.0
    ret5 = m.get("ret5") or 0.0
    ret20 = m.get("ret20") or 0.0
    volr = m.get("volRatio5v20")
    up = ret1 > 0 or ret5 > 0

    if jsf:
        have += 1
        sn, sr = jsf.get("shortNew") or 0, jsf.get("shortRepay") or 0
        ln, lr = jsf.get("loanNew") or 0, jsf.get("loanRepay") or 0
        ratio = jsf.get("ratio")
        if up and (sr - sn) > max(1, sr * 0.1):       # short balance shrinking
            w["shortCovering"] += 2.0
            reasons.append("株価上昇中に貸株残が縮小(返済>新規)= 買い戻しが進行")
        if up and (ln - lr) > max(1, lr * 0.1):       # margin longs building
            w["newLong"] += 1.5
            reasons.append("融資残が増加(新規>返済)= 新規の信用買いが流入")
        if (lr - ln) > max(1, ln * 0.1) and not up:   # longs unwinding, no rise
            w["distribution"] += 1.0
            reasons.append("信用買い方が返済超(利食い/手仕舞い)= 上値が重い")
        if isinstance(ratio, (int, float)) and ratio < 1.0:
            w["shortCovering"] += 1.0
            reasons.append(f"日証金倍率{ratio}(売り長)= 踏み上げ燃料が残存")
    if short_disclosed and short_disclosed.get("ratio"):
        have += 1
        sd = short_disclosed["ratio"]
        if sd >= 0.05:
            w["shortCovering"] += 1.5
            reasons.append(f"機関の大口空売り{round(sd*100,1)}% = 買い戻し燃料が大きい")
    if isinstance(flow_ratio, (int, float)):
        have += 1
        if flow_ratio >= 0.15 and up:
            w["newLong"] += 1.0
            reasons.append(f"大口資金が純流入+{round(flow_ratio*100)}%(当日)")
        elif flow_ratio <= -0.15:
            w["distribution"] += 1.5
            reasons.append(f"大口資金が純流出{round(flow_ratio*100)}%(上で売り抜けの疑い)")
    if isinstance(volr, (int, float)) and volr >= 1.5:
        have += 1
        if not up:
            w["distribution"] += 1.0
            reasons.append(f"出来高{volr}倍だが株価が伴わない(分配の疑い)")
        elif ret20 > 0 and ret5 > 0:
            w["newLong"] += 0.5
            reasons.append("出来高増+中期(20日)上昇が継続")
    # A sharp one-day spike with no credit fuel reads as retail/news noise.
    if ret1 >= 4 and not (jsf and isinstance(jsf.get("ratio"), (int, float)) and jsf["ratio"] < 1):
        w["retailNoise"] += 0.5
        reasons.append("短期急騰だが信用の買い戻し燃料が乏しい(個人・テーマ性ノイズの可能性)")

    LABEL = {"newLong": "NEW_LONG_ACCUMULATION", "shortCovering": "SHORT_COVERING",
             "distribution": "DISTRIBUTION", "retailNoise": "RETAIL_NOISE"}
    total = sum(w.values())
    limits = ["VWAP・板・歩み値が未接続のため日中のリアルタイム・フローは見えない(推定精度は限定的)",
              "制度信用以外(一般信用・海外勢・ヘッジ)のポジションは見えない",
              "注文主の内部IDは取得不可 — 断定ではなく確率推定"]
    nxt = ("翌営業日も上昇が続き出来高を伴えば新規買い寄りに更新。"
           "続かず貸株残が急減し出来高が細れば買い戻し一巡とみなす。")
    if total == 0 or have < 2:
        return {"classification": "UNCONFIRMED",
                "probabilities": {"newLongAccumulation": 0.0, "shortCovering": 0.0,
                                  "distribution": 0.0, "retailNoise": 0.0, "unconfirmed": 1.0},
                "confidence": "low", "reasonsJa": reasons or ["判定に十分な需給データが揃っていません。"],
                "nextConditionJa": nxt, "dataLimitationsJa": limits}
    # More independent sources → less reserved for "unconfirmed".
    unconf = max(0.05, round(0.45 - 0.1 * have, 2))
    scale = (1.0 - unconf) / total
    probs = {
        "newLongAccumulation": round(w["newLong"] * scale, 2),
        "shortCovering": round(w["shortCovering"] * scale, 2),
        "distribution": round(w["distribution"] * scale, 2),
        "retailNoise": round(w["retailNoise"] * scale, 2),
        "unconfirmed": unconf,
    }
    top = max(w, key=w.get)
    # Squeeze-risk nuance: covering is the call AND fuel still remains.
    cls = LABEL[top]
    if cls == "SHORT_COVERING" and ((jsf and (jsf.get("ratio") or 9) < 1)
                                    or (short_disclosed and short_disclosed.get("ratio", 0) >= 0.05)):
        reasons.insert(0, "踏み上げ継続リスク: 買い戻し燃料がまだ残っている")
    return {"classification": cls, "probabilities": probs,
            "confidence": "medium" if have >= 3 else "low",
            "reasonsJa": reasons, "nextConditionJa": nxt, "dataLimitationsJa": limits}

def _jsf_assess_lines(j):
    """Pure (unit-tested): JSF daily balance → (score_delta, reasonsJa[]).
    日証金倍率(融資残/貸株残): <1 売り長=踏み上げ燃料(+), 高倍率=買い長で戻り売り(-).
    Plus today's new-vs-repayment direction. All contributions visible."""
    if not j:
        return 0.0, []
    score, reasons = 0.0, []
    r = j.get("ratio")
    if isinstance(r, (int, float)):
        if r < 1.0:
            score += 0.5
            reasons.append(f"日証金倍率{r}倍(貸株超=売り長) — 買い戻し(踏み上げ)の燃料")
        elif r >= 3.0:
            score -= 0.5
            reasons.append(f"日証金倍率{r}倍(融資超=買い長) — 上値に戻り売り圧力")
    sn, sr = j.get("shortNew"), j.get("shortRepay")
    if isinstance(sn, int) and isinstance(sr, int) and sn > sr * 1.3 and sn > 0:
        score += 0.3
        reasons.append("本日の新規売り>返済 — 売り建てが増加(将来の買い戻し余地)")
    ln, lr = j.get("loanNew"), j.get("loanRepay")
    if isinstance(ln, int) and isinstance(lr, int) and ln > lr * 1.3 and ln > 0:
        score -= 0.3
        reasons.append("本日の新規買い建てが増加 — 短期の買い疲れに注意")
    return score, reasons

def _entry_metrics(closes, volumes=None):
    """Pure (unit-tested): trend/overheat metrics from NEWEST-FIRST closes.
    <20 sessions → None (too little history to say anything honest)."""
    if not closes or len(closes) < 20:
        return None
    c0 = closes[0]
    def ret(n):
        return round((c0 - closes[n]) / closes[n] * 100, 2) if len(closes) > n and closes[n] else None
    def ma(n):
        return sum(closes[:n]) / n if len(closes) >= n else None
    ma5, ma25 = ma(5), ma(25)
    gains = losses = 0.0
    for i in range(min(14, len(closes) - 1)):
        d = closes[i] - closes[i + 1]
        if d >= 0:
            gains += d
        else:
            losses -= d
    rsi = round(100 * gains / (gains + losses), 1) if (gains + losses) > 0 else 50.0
    consec_down = 0
    for i in range(len(closes) - 1):
        if closes[i] < closes[i + 1]:
            consec_down += 1
        else:
            break
    window = closes[:60]
    hi60, lo60 = max(window), min(window)
    vol_ratio = None
    if volumes and len(volumes) >= 25:
        v5 = sum(volumes[:5]) / 5
        v20 = sum(volumes[5:25]) / 20
        vol_ratio = round(v5 / v20, 2) if v20 else None
    # v2.1 (2026-06-13 「RSIやMACDも統合できているのか」): MACD(12,26,9)、
    # 移動平均クロス、ボリンジャー%b — all computed chronologically.
    chron = closes[::-1]                      # oldest-first

    def _ema(vals, n):
        k = 2.0 / (n + 1)
        e = vals[0]
        out = [e]
        for v in vals[1:]:
            e = v * k + e * (1 - k)
            out.append(e)
        return out

    macd_hist, macd_cross = None, None
    if len(chron) >= 35:
        e12, e26 = _ema(chron, 12), _ema(chron, 26)
        macd_line = [a - b for a, b in zip(e12, e26)]
        signal = _ema(macd_line, 9)
        hist = [a - b for a, b in zip(macd_line, signal)]
        macd_hist = round(hist[-1], 3)
        recent, before = hist[-1], hist[-4:-1]
        if recent > 0 and any(h <= 0 for h in before):
            macd_cross = "golden"
        elif recent < 0 and any(h >= 0 for h in before):
            macd_cross = "dead"

    def _sma_at(idx_from_end, n):
        seg = chron[max(0, len(chron) - idx_from_end - n):len(chron) - idx_from_end]
        return sum(seg) / len(seg) if len(seg) == n else None

    ma_cross = None
    ma5_now, ma25_now = _sma_at(0, 5), _sma_at(0, 25)
    ma5_prev, ma25_prev = _sma_at(5, 5), _sma_at(5, 25)
    if None not in (ma5_now, ma25_now, ma5_prev, ma25_prev):
        if ma5_now > ma25_now and ma5_prev <= ma25_prev:
            ma_cross = "golden"
        elif ma5_now < ma25_now and ma5_prev >= ma25_prev:
            ma_cross = "dead"

    boll_pct_b = None
    if len(closes) >= 25:
        seg = closes[:25]
        mean = sum(seg) / 25
        var = sum((x - mean) ** 2 for x in seg) / 25
        sd = var ** 0.5
        if sd > 0:
            boll_pct_b = round((c0 - (mean - 2 * sd)) / (4 * sd), 2)

    return {
        "ret1": ret(1), "ret5": ret(5), "ret20": ret(20),
        "ret60": ret(60) if len(closes) > 60 else None,
        "ma5DiffPct": round((c0 - ma5) / ma5 * 100, 2) if ma5 else None,
        "ma25DiffPct": round((c0 - ma25) / ma25 * 100, 2) if ma25 else None,
        "rsi14": rsi, "consecDown": consec_down,
        "offHigh60Pct": round((c0 - hi60) / hi60 * 100, 2) if hi60 else None,
        "offLow60Pct": round((c0 - lo60) / lo60 * 100, 2) if lo60 else None,
        "volRatio5v20": vol_ratio, "sessions": len(closes),
        "macdHist": macd_hist, "macdCross": macd_cross,
        "maCross": ma_cross, "bollPctB": boll_pct_b,
    }

def _entry_scout_assess(m, flow_ratio, esc, posture, vix_zone, weekday,
                        regime_label=None, vix_spike=False, rel_strength=None,
                        earnings_days=None, ai_view=None, margin_sig=None, jsf_sig=None,
                        short_disclosed=None):
    """Pure (unit-tested): metrics + context → stance/score/reasons. Every
    contribution is ±0.5〜1 AND stated in reasonsJa — no hidden weights. The
    Friday-bounce anomaly is NOTED but not scored (経験則 — the ledger will
    verify it with data before it earns score weight).
    v2 (2026-06-13 user: 「全能力をここに集約しろ」): regime, VIX spike,
    index-relative strength, earnings proximity, AI double-check view."""
    reasons, score = [], 0.0
    if m["ma25DiffPct"] is not None:
        if m["ma25DiffPct"] <= -8:
            score += 1; reasons.append(f"25日線から{m['ma25DiffPct']}%の下方乖離(売られすぎ圏)")
        elif m["ma25DiffPct"] >= 8:
            score -= 1; reasons.append(f"25日線から+{m['ma25DiffPct']}%の上方乖離(過熱圏)")
    if m["rsi14"] <= 30:
        score += 1; reasons.append(f"RSI14={m['rsi14']}(売られすぎ)")
    elif m["rsi14"] >= 70:
        score -= 1; reasons.append(f"RSI14={m['rsi14']}(買われすぎ)")
    if m["consecDown"] >= 3:
        score += 0.5; reasons.append(f"{m['consecDown']}日続落(自律反発の余地)")
    if (m["ret20"] or 0) > 0 and (m["ret5"] or 0) < 0:
        score += 0.5; reasons.append("中期(20日)上昇トレンド+短期(5日)押し目の形")
    if (m["volRatio5v20"] or 0) >= 1.5:
        reasons.append(f"出来高が平常の{m['volRatio5v20']}倍(注目度上昇 — 方向はフローで判断)")
    # v2.1: classic technicals — each ±0.5, all visible.
    if m.get("macdCross") == "golden":
        score += 0.5; reasons.append("MACDが直近で好転(シグナル線を上抜け)")
    elif m.get("macdCross") == "dead":
        score -= 0.5; reasons.append("MACDが直近で悪化(シグナル線を下抜け)")
    if m.get("maCross") == "golden":
        score += 0.5; reasons.append("5日線が25日線を上抜け(ゴールデンクロス)")
    elif m.get("maCross") == "dead":
        score -= 0.5; reasons.append("5日線が25日線を下抜け(デッドクロス)")
    b = m.get("bollPctB")
    if isinstance(b, (int, float)):
        if b <= 0:
            score += 0.5; reasons.append(f"ボリンジャー-2σ圏(%b={b}) — 統計的売られすぎ")
        elif b >= 1:
            score -= 0.5; reasons.append(f"ボリンジャー+2σ圏(%b={b}) — 統計的過熱")
    if isinstance(flow_ratio, (int, float)):
        if flow_ratio >= 0.15:
            score += 1; reasons.append(f"大口資金が純流入+{round(flow_ratio * 100)}%(確証シグナル)")
        elif flow_ratio <= -0.15:
            score -= 1; reasons.append(f"大口資金が純流出{round(flow_ratio * 100)}%")
    if esc in ("D", "D-1"):
        score -= 1; reasons.append(f"重要イベント接近({esc}) — 結果待ちが原則")
    if posture == "elevated":
        score -= 0.5; reasons.append("金利地合いが逆風(elevated)")
    if vix_zone in ("elevated", "shock"):
        score -= 1; reasons.append(f"ボラティリティ圏域が{vix_zone}")
    # ── v2 factors ──
    if regime_label in ("RISK_OFF", "EVENT_WAIT"):
        score -= 1; reasons.append(f"市場レジームが{regime_label}(逆風の地合い)")
    elif regime_label == "RISK_ON":
        score += 0.5; reasons.append("市場レジームがRISK_ON(追い風)")
    if vix_spike:
        score -= 1; reasons.append("VIXが急騰中(パニック局面 — 入るならサイズを落とす)")
    if isinstance(rel_strength, (int, float)):
        if rel_strength >= 1.0:
            score += 0.5; reasons.append(f"指数(TOPIX)より{rel_strength:+.1f}pt強い(相対力あり)")
        elif rel_strength <= -1.0:
            score -= 0.5; reasons.append(f"指数(TOPIX)より{rel_strength:+.1f}pt弱い(相対的に売られている)")
    if isinstance(earnings_days, (int, float)):
        if 0 <= earnings_days <= 3:
            score -= 1; reasons.append(f"決算が{int(earnings_days)}日以内 — 結果は読めない(ギャンブル領域)")
        elif earnings_days <= 7:
            reasons.append(f"決算まで{int(earnings_days)}日(イベント前の建玉は軽めが原則)")
    if ai_view == "confirm":
        score += 0.5; reasons.append("AI二重チェック(GPT-5.5+Gemini)がルール判定に同意")
    elif ai_view == "disagree":
        score -= 1; reasons.append("AI二重チェックがルール判定に不同意(慎重化)")
    elif ai_view == "caution":
        score -= 0.5; reasons.append("AI二重チェックが注意を表明")
    # ── v2.2: weekly margin (信用残) — short-covering vs fresh-buying read ──
    ms_score, ms_reasons = _margin_assess_lines(margin_sig)
    score += ms_score; reasons.extend(ms_reasons)
    # ── v2.3: 日証金(JSF)daily 貸借残 — free alternative, works without plan ──
    js_score, js_reasons = _jsf_assess_lines(jsf_sig)
    score += js_score; reasons.extend(js_reasons)
    # ── v2.4: JPX disclosed institutional short (≥0.5%) — squeeze intel ──
    sd_score, sd_reasons = _short_disclosed_assess(short_disclosed)
    score += sd_score; reasons.extend(sd_reasons)
    if weekday == 4:
        reasons.append("金曜: 週末リスクで売られやすい日(翌営業日反発は経験則 — 台帳で検証中のため点数化はしない)")
    if score >= 1.5:
        stance = "攻め好機(候補)"
    elif score >= 0.5:
        stance = "押し目買い検討圏"
    elif score > -1:
        stance = "中立(急がない)"
    else:
        stance = "見送り"
    return {"stance": stance, "score": round(score, 2), "reasonsJa": reasons}

def get_entry_scout(sym):
    now = time.time()
    c = _SCOUT_CACHE.get(sym)
    if c and now < c["expires"]:
        return c["data"]
    hist = _jq_price_history(sym)
    if not hist:
        return {"engineVersion": "entry-scout-v1", "symbol": sym, "status": "unavailable",
                "noteJa": "価格履歴を取得できませんでした(コード違いか一時的な障害)。"}
    m = _entry_metrics(hist["closes"], hist["volumes"])
    if not m:
        return {"engineVersion": "entry-scout-v1", "symbol": sym, "status": "unavailable",
                "noteJa": "履歴が20営業日未満のため診断できません(上場直後など)。"}
    # Realtime flow from the bridge (last push regardless of freshness — the
    # asOf below tells the user how stale it is, e.g. on a weekend).
    pushed = (_PUSHED_QUOTES.get("JP") or {}).get(sym)
    flow_ratio, flow_age_min = None, None
    if pushed:
        fl = (pushed.get("row") or {}).get("flow") or {}
        if isinstance(fl.get("bigNetRatio"), (int, float)):
            flow_ratio = float(fl["bigNetRatio"])
            flow_age_min = int((now - pushed["ts"]) / 60)
    ev = get_events_snapshot()
    esc = _region_event_escalation(ev.get("events", []) if isinstance(ev, dict) else [], "JP")
    posture = _rates_posture(get_rates_snapshot())
    vol = _vix_assess(_fred_vix_history())
    vix_zone = vol.get("zone") if isinstance(vol, dict) else None
    vix_spike = bool(vol.get("spike")) if isinstance(vol, dict) else False
    weekday = datetime.now(TZ_JST).weekday()
    # v2: market regime (6h-cached — no extra cost when warm).
    reg = get_market_regime_snapshot()
    reg_label = (reg.get("regime", {}) or {}).get("label") if isinstance(reg, dict) else None
    reg_ok = isinstance(reg, dict) and reg.get("status") in ("live", "partial")
    # v2: index-relative strength — the stock's day move vs TOPIX ETF (1306),
    # both from the bridge so the comparison is same-timestamp realtime.
    rel_strength = None
    idx_pushed = (_PUSHED_QUOTES.get("JP") or {}).get("1306")
    if pushed and idx_pushed:
        s_chg = (pushed.get("row") or {}).get("changePct")
        i_chg = (idx_pushed.get("row") or {}).get("changePct")
        if isinstance(s_chg, (int, float)) and isinstance(i_chg, (int, float)):
            rel_strength = round(s_chg - i_chg, 2)
    # v2: earnings proximity from the catalysts metadata (best effort — the
    # date must be present because daysUntil defaults to 0 when unknown).
    earnings_days = None
    try:
        cat = get_catalysts_snapshot()
        for it in (cat.get("items", []) if isinstance(cat, dict) else []):
            if it.get("symbol") == sym:
                e = it.get("earnings") or {}
                if e.get("date") and isinstance(e.get("daysUntil"), (int, float)):
                    earnings_days = e["daysUntil"]
                break
    except Exception:
        pass
    # v2: cached AI double-check view for this symbol (if the daily run saw it).
    ai_view = None
    cached_ai = _ai_cached_result()
    if isinstance(cached_ai, dict):
        for l in cached_ai.get("labels", []):
            if l.get("symbol") == sym:
                ai_view = l.get("aiView")
                break
    # v2.2: weekly margin (信用残) — plan-dependent, None when unavailable.
    margin_sig = _margin_signal(_jq_weekly_margin(sym))
    # v2.3: 日証金(JSF) daily 貸借残 — free, no plan needed (the primary 信用
    # signal for this user's plan). Distinguish "source down" from "not a
    # 貸借銘柄" so null is never ambiguous (使い物になる検証, 2026-06-13).
    jsf_table, jsf_date = _jsf_balance_table()
    if jsf_table is None:
        jsf_sig, jsf_status = None, "source_unavailable"
    elif sym in jsf_table and jsf_table[sym].get("loan") is not None and jsf_table[sym].get("short") is not None:
        jsf_sig, jsf_status = _jsf_for(sym), "ok"
    else:
        jsf_sig, jsf_status = None, "not_loanable"
    # v2.4: JPX disclosed institutional short (≥0.5%). Distinguish source-down
    # from genuinely-no-disclosed-short (most stocks → none, which is meaningful).
    jpx_short_table, jpx_short_date = _jpx_short_table()
    if jpx_short_table is None:
        short_disclosed, short_status = None, "source_unavailable"
    elif sym in jpx_short_table:
        short_disclosed, short_status = jpx_short_table[sym], "ok"
    else:
        short_disclosed, short_status = None, "none_disclosed"
    assess = _entry_scout_assess(m, flow_ratio, esc, posture, vix_zone, weekday,
                                 regime_label=reg_label if reg_ok else None,
                                 vix_spike=vix_spike, rel_strength=rel_strength,
                                 earnings_days=earnings_days, ai_view=ai_view,
                                 margin_sig=margin_sig, jsf_sig=jsf_sig,
                                 short_disclosed=short_disclosed)
    out = {
        "engineVersion": "entry-scout-v1", "symbol": sym,
        "name": _jq_name_for(sym) or sym,
        "asOf": _ai_now_iso(), "status": "live",
        "lastClose": hist["closes"][0], "lastDate": hist["dates"][0],
        "metrics": m,
        "flow": {"bigNetRatio": flow_ratio, "ageMin": flow_age_min},
        "margin": margin_sig,    # None when the J-Quants plan omits weekly margin
        "nisshokin": jsf_sig,    # 日証金(JSF) daily 貸借残; None if not a 貸借銘柄
        "nisshokinStatus": jsf_status,   # ok / not_loanable / source_unavailable
        "shortDisclosed": (short_disclosed and {"ratioPct": round(short_disclosed["ratio"] * 100, 1),
                                                "reporters": short_disclosed["reporters"], "date": jpx_short_date}),
        "shortDisclosedStatus": short_status,   # ok / none_disclosed / source_unavailable
        # Flow Intelligence (v10.21): probabilistic 新規買い/買い戻し/分配/ノイズ.
        "flowInference": _flow_inference(m, flow_ratio, jsf_sig, short_disclosed),
        # Material/news backdrop (v10.22) — free sources, 参考 (not scored).
        "catalystContext": _catalyst_context(
            get_news_radar(), reg_label if reg_ok else None, esc, earnings_days,
            high_beta=sym in _US_TECH_LINKED_JP),
        "context": {"posture": posture, "vixZone": vix_zone, "vixSpike": vix_spike,
                    "regime": reg_label if reg_ok else None,
                    "relStrengthVsTopix": rel_strength, "earningsDays": earnings_days,
                    "aiView": ai_view, "eventEscalation": esc or "normal",
                    "weekdayJa": "月火水木金土日"[weekday]},
        "assessment": assess,
        "dataGapsJa": [
            {"ok": "信用残: 日証金(JSF)貸借残で取得済み(日証金倍率 = 融資残/貸株残)",
             "not_loanable": "信用残: この銘柄は貸借銘柄ではないため日証金データに非掲載 — 取得不可(正常)",
             "source_unavailable": "信用残: 日証金データ源を一時取得できません(自動リトライ。数分後に再診断で復帰)",
             }[jsf_status],
            {"ok": "機関の大口空売り: JPX開示データで取得済み",
             "none_disclosed": "機関の大口空売り: 0.5%超の開示報告なし(=機関の大口空売りは記録上なし)",
             "source_unavailable": "機関の大口空売り: JPXデータ源を一時取得できません(自動リトライ)",
             }[short_status],
            "本格的なパターン形状(ダブルボトム等)の認識は未対応 — RSI/MACD/ボリンジャー/移動平均クロスで近似(v2.1)",
            "国策・テーマ性の自動判定は未対応 — ニュース/開示で各自確認",
        ],
        "noteJa": "売買指示ではなく、入る前の論点整理。最終判断と数量はあなたのルールで。",
    }
    # If a credit/short source was momentarily down, cache only briefly so the
    # next diagnosis self-heals instead of showing a 30-min gap (検証で確認).
    src_down = jsf_status == "source_unavailable" or short_status == "source_unavailable"
    _SCOUT_CACHE[sym] = {"data": out, "expires": now + (180 if src_down else _SCOUT_TTL)}
    return out

@app.route("/api/argus/entry-scout")
def api_argus_entry_scout():
    sym = (request.args.get("symbol") or "").strip().upper()
    if not _JP_SYM_RE.match(sym):
        return jsonify({"error": "bad_symbol",
                        "noteJa": "現在は日本株の4桁コードのみ対応(米国株はPhase 2)。"}), 400
    return jsonify(get_entry_scout(sym))

# ── Close Pin Intraday Ledger (closepin-v1, v10.11) ──────────────────────────
# The second ledger system of the user-approved architecture: at ~14:30 JST a
# REALTIME price pin + a scenario distribution for "where does today's 15:30
# close land vs this pin" is recorded; the 16:05 daily run scores it the SAME
# day. Same-day feedback = the fastest calibration loop in the system.
# Realtime-only by honesty: a T-1 J-Quants close cannot pin an intraday
# prediction, so rows without a fresh moomoo push are excluded.
_CLOSEPIN_BANDS = (0.25, 0.8)   # % vs pin: |x|<0.25 flat / 0.25–0.8 up·down / >0.8 strong.
                                # ≈ a one-hour sigma for JP large caps: the daily ±2% band
                                # scaled by √(1h/6.5h) ≈ 0.39 → ~0.8%, half of it = 0.25%.
_CLOSEPIN_ACTIVES_JP = ["8058", "9984", "5801", "5803", "6584", "285A", "9501"]
# JP names whose price is dominated by US-tech/AI beta (NASDAQ/SMH link) — for
# these, the US-tech backdrop matters more than the stock's own chart. SBG
# (9984, Arm + AI holdings), Kioxia (285A, NAND/AI memory), Advantest/SoftBank
# adjacents. Used only to surface a 参考 'US-tech link' material note.
_US_TECH_LINKED_JP = {"9984", "285A", "6857", "8035"}

def _closepin_scenarios(chg_so_far, flow_ratio, posture):
    """Pure (unit-tested): scenario distribution for the close-vs-pin move.
    Calm baseline 10/20/40/20/10 with two small, capped tilts:
      - momentum continuation (intraday trends mildly persist into the close;
        ±0.04 per 1% of day change, capped ±0.12 so it never dominates)
      - big-money flow confirmation (same signal family as _flow_adjust)
    Elevated-rates posture damps only the strong-up tail. Sums to 1."""
    p = [0.10, 0.20, 0.40, 0.20, 0.10]  # strongDown, down, flat, up, strongUp
    tilt = max(-0.12, min(0.12, (chg_so_far or 0.0) * 0.04))
    if isinstance(flow_ratio, (int, float)):
        tilt += max(-0.06, min(0.06, flow_ratio * 0.15))
    tilt = max(-0.15, min(0.15, tilt))
    if tilt >= 0:
        p = [p[0] - tilt * 0.3, p[1] - tilt * 0.7, p[2], p[3] + tilt * 0.7, p[4] + tilt * 0.3]
    else:
        t = -tilt
        p = [p[0] + t * 0.3, p[1] + t * 0.7, p[2], p[3] - t * 0.7, p[4] - t * 0.3]
    if posture == "elevated":
        d = min(0.03, p[4] * 0.3)
        p[4] -= d
        p[2] += d
    p = [max(0.02, x) for x in p]
    s = sum(p)
    p = [round(x / s, 3) for x in p]
    p[2] = round(p[2] + (1.0 - sum(p)), 3)  # rounding drift lands on flat
    return {"strongDown": p[0], "down": p[1], "flat": p[2], "up": p[3], "strongUp": p[4]}

_CLOSEPIN_CACHE = {"data": None, "expires": 0.0}

def get_closepin_snapshot():
    rates = get_rates_snapshot()
    posture = _rates_posture(rates)
    sensor_syms = [s for s, _ in _L1_SENSORS_JP]
    syms = sensor_syms + [s for s in _CLOSEPIN_ACTIVES_JP if s not in sensor_syms]
    jp = get_japan_watchlist_snapshot(syms)
    rows = []
    for q in (jp.get("stocks", []) if isinstance(jp, dict) else []):
        # Realtime pins only — see module comment above.
        if q.get("status") != "live" or q.get("source") != "moomoo-rt":
            continue
        chg = q.get("changePct")
        fl = q.get("flow") or {}
        flow_ratio = fl.get("bigNetRatio") if isinstance(fl, dict) else None
        sym = q["symbol"]
        rows.append({
            "symbol": sym, "name": q.get("name"),
            "layer": 1 if sym in sensor_syms else _layer_of(sym),
            "pinPrice": q.get("price"), "changePct": chg, "flowRatio": flow_ratio,
            "bandPct": list(_CLOSEPIN_BANDS),
            "scenarios": _closepin_scenarios(chg, flow_ratio, posture),
        })
    return {
        "engineVersion": "closepin-v1",
        "asOf": datetime.now(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dateJst": datetime.now(pytz.timezone("Asia/Tokyo")).strftime("%Y-%m-%d"),
        "status": "live" if rows else "no_realtime",
        "marketPosture": posture,
        "rows": rows,
        "scoringRule": {
            "targetJa": "同日15:30の終値がピン価格に対してどのバケットに着地するか",
            "buckets": {"flatWithinPct": _CLOSEPIN_BANDS[0], "strongBeyondPct": _CLOSEPIN_BANDS[1]},
            "noteJa": "リアルタイム価格(moomooブリッジ)が取れた銘柄のみピン。T-1価格では当日予測にならないため除外。",
        },
    }

@app.route("/api/argus/closepin-snapshot")
def api_argus_closepin_snapshot():
    # Public read for the pin workflow; 2-min cache coalesces bursts.
    now = time.time()
    if _CLOSEPIN_CACHE["data"] and now < _CLOSEPIN_CACHE["expires"]:
        return jsonify(_CLOSEPIN_CACHE["data"])
    snap = get_closepin_snapshot()
    _CLOSEPIN_CACHE["data"] = snap
    _CLOSEPIN_CACHE["expires"] = now + 120
    return jsonify(snap)

def get_prediction_snapshot():
    al  = get_action_labels()
    jp  = get_japan_watchlist_snapshot()
    us  = get_us_watchlist_snapshot()
    reg = get_market_regime_snapshot()
    vol = _vix_assess(_fred_vix_history())
    rg  = reg.get("regime", {}) if isinstance(reg, dict) else {}
    rb  = reg.get("ratesBackdrop", {}) if isinstance(reg, dict) else {}

    prices = {}
    for snap in (jp, us):
        for s in (snap.get("stocks", []) if isinstance(snap, dict) else []):
            if s.get("status") == "live":
                prices[s["symbol"]] = s

    # Cached AI views (if an admin/cron run happened recently) — recorded so the
    # ledger can grade RULE vs AI over time.
    ai_by_sym, ai_status = {}, "none"
    cached = _AI_RESULT_CACHE["data"]
    if cached and time.time() < _AI_RESULT_CACHE["expires"]:
        ai_status = cached.get("status", "none")
        for l in cached.get("labels", []):
            ai_by_sym[l.get("symbol")] = {
                "view": l.get("aiView"), "action": l.get("aiFinalAction"),
                "confidence": l.get("confidence"),
            }

    predictions = []
    for l in al.get("labels", []):
        q = prices.get(l["symbol"])
        if not q:
            continue  # no live price = nothing falsifiable to record
        sd = l.get("supportingData", {}) or {}
        predictions.append({
            "symbol": l["symbol"], "market": l["market"], "name": l["name"],
            "layer": _layer_of(l["symbol"]),
            "price": q["price"], "changePct": sd.get("changePct"),
            "action": l["action"], "confidence": l["confidence"],
            "scenarios": [{"label": s, "p": p} for s, p in _scenarios_for(sd.get("changePct"))],
            "flowRatio": sd.get("bigFlowRatio"),
            "ai": ai_by_sym.get(l["symbol"]),
        })

    # ── Asset-class predictions (ledger-v2, v10.5) ──
    # The agreed learning axis: not individual-stock memorization but the
    # calibration of CONTEXT × ASSET CLASS. Proxies: the regime/alerts ETF
    # universe + BTC/ETH. _alert_etf_momentum() ensures GLD/TLT/XLRE are
    # stashed; the regime call above covers SPY/QQQ/IWM/XLK/XLU/GLD/TLT/HYG.
    _alert_etf_momentum()
    CLASS_PROXIES = [
        ("US_BROAD", "SPY"), ("US_GROWTH", "QQQ"), ("SMALL_CAPS", "IWM"),
        ("TECH", "XLK"), ("DEFENSIVE", "XLU"), ("GOLD", "GLD"),
        ("BOND", "TLT"), ("CREDIT", "HYG"), ("REIT", "XLRE"),
    ]
    class_predictions = []
    now_ts = time.time()
    for cls, sym in CLASS_PROXIES:
        st = _ETF_LAST_PRICE.get(sym)
        if not st or now_ts - st["ts"] > 12 * 3600:
            continue
        class_predictions.append({
            "assetClass": cls, "symbol": sym, "price": st["price"],
            "changePct": st["m1d"],
            "scenarios": [{"label": s, "p": p} for s, p in _scenarios_for(st["m1d"])],
        })
    cw = get_crypto_watchlist_snapshot(list(_CRYPTO_DEFAULT_IDS))
    for q in (cw.get("quotes") or []):
        if q.get("status") == "live":
            ccls = ("CRYPTO_BTC" if q["id"] == "bitcoin" else
                    "CRYPTO_ETH" if q["id"] == "ethereum" else None)
            if ccls:
                class_predictions.append({
                    "assetClass": ccls, "symbol": q["id"], "price": q["priceUsd"],
                    "changePct": q["changePct"],
                    "scenarios": [{"label": s, "p": p} for s, p in _scenarios_for(q["changePct"])],
                })

    # ── Layer-1 sensors (ledger-v3): the FIXED 16-asset regime universe ──
    sensors = []
    jp_sens = get_japan_watchlist_snapshot([s for s, _ in _L1_SENSORS_JP])
    jp_sens_live = {s["symbol"]: s for s in (jp_sens.get("stocks") or [])
                    if s.get("status") == "live"}
    for sym, name in _L1_SENSORS_JP:
        q = jp_sens_live.get(sym)
        if q:
            sensors.append(_sensor_row(sym, name, "equity_jp", q["price"], q.get("changePct")))
    _ensure_sensor_etfs()
    for sym in _L1_SENSORS_US:
        st = _ETF_LAST_PRICE.get(sym)
        if st and now_ts - st["ts"] <= 12 * 3600:
            sensors.append(_sensor_row(sym, sym, "etf_us", st["price"], st["m1d"]))
    for q in (cw.get("quotes") or []):
        if q.get("id") == "bitcoin" and q.get("status") == "live":
            sensors.append(_sensor_row("BTC", "Bitcoin", "crypto", q["priceUsd"], q.get("changePct")))
    rates = get_rates_snapshot()
    for key, sid, sname, kind in (("usdJpy", "USDJPY", "USD/JPY", "fx"),
                                  ("vix", "VIX", "VIX", "vol")):
        s = rates.get(key) if isinstance(rates, dict) else None
        if s and s.get("status") == "live" and s.get("latestValue") is not None:
            lvl = float(s["latestValue"])
            ch = s.get("change")
            chg_pct = (round(ch / (lvl - ch) * 100, 2)
                       if isinstance(ch, (int, float)) and (lvl - ch) else None)
            sensors.append(_sensor_row(sid, sname, kind, lvl, chg_pct))

    # ── Posture prediction (the call that everything depends on) ──
    # Self-describing scoring rule so the scorer never hardcodes thresholds:
    #   RISK_ON → SPY next move > 0; RISK_OFF → < 0;
    #   EVENT_WAIT → |SPY move| >= 1.0% (the elevated-risk claim validated by
    #   an actual move). CAUTIOUS/MIXED make no strong claim → recorded, not scored.
    posture_label = (al.get("marketPosture", {}) or {}).get("label")
    spy = _ETF_LAST_PRICE.get("SPY")
    posture_prediction = None
    if posture_label and spy and now_ts - spy["ts"] <= 12 * 3600:
        rule = ({"type": "direction", "sign": 1} if posture_label == "RISK_ON" else
                {"type": "direction", "sign": -1} if posture_label == "RISK_OFF" else
                {"type": "absmove", "minPct": 1.0} if posture_label == "EVENT_WAIT" else
                None)
        posture_prediction = {"posture": posture_label, "proxy": "SPY",
                              "price": spy["price"], "rule": rule}

    return {
        "dateJst": datetime.now(TZ_JST).strftime("%Y-%m-%d"),
        "asOf": _ai_now_iso(),
        "engineVersion": "ledger-v3",
        "context": {
            "posture": posture_label,
            "regimeConfidence": rg.get("confidence"),
            "vixZone": (vol or {}).get("zone"),
            "vixLevel": (vol or {}).get("level"),
            "backdrop": rb.get("posture"),
            "aiStatus": ai_status,
        },
        "sensors": sensors,                    # Layer 1 — fixed 16 regime sensors
        "predictions": predictions,            # Layers 1-3 stock rows (see .layer)
        "classPredictions": class_predictions, # legacy continuity (v10.5 axis)
        "posturePrediction": posture_prediction,
        "scoringRule": {
            "horizonsTradingDays": [1, 3, 5],
            "bucketsNote": "per-row bandPct (≈daily sigma): downside < -band, sideways within ±band, rebound > +band; legacy rows band=2%",
            "metrics": ["argmaxHit", "brier"],
        },
    }

@app.route("/api/argus/prediction-snapshot")
def api_argus_prediction_snapshot():
    return jsonify(get_prediction_snapshot())

@app.route("/api/argus/sensor-quotes")
def api_argus_sensor_quotes():
    """Latest values for the 16 Layer-1 sensors — the ledger-v3 scorer's price
    source (JP via J-Quants/moomoo overlay, US ETFs via the Twelve Data stash,
    BTC via CoinGecko, USDJPY/VIX via FRED)."""
    out = {}
    jp = get_japan_watchlist_snapshot([s for s, _ in _L1_SENSORS_JP])
    for s in (jp.get("stocks") or []):
        if s.get("status") == "live":
            out[s["symbol"]] = float(s["price"])
    get_market_regime_snapshot()
    _alert_etf_momentum()
    _ensure_sensor_etfs()
    now_ts = time.time()
    for sym in _L1_SENSORS_US:
        st = _ETF_LAST_PRICE.get(sym)
        if st and now_ts - st["ts"] <= 24 * 3600:
            out[sym] = st["price"]
    cw = get_crypto_watchlist_snapshot(["bitcoin"])
    for q in (cw.get("quotes") or []):
        if q.get("id") == "bitcoin" and q.get("status") == "live":
            out["BTC"] = float(q["priceUsd"])
    rates = get_rates_snapshot()
    for key, sid in (("usdJpy", "USDJPY"), ("vix", "VIX")):
        s = rates.get(key) if isinstance(rates, dict) else None
        if s and s.get("status") == "live" and s.get("latestValue") is not None:
            out[sid] = float(s["latestValue"])
    return jsonify({"asOf": _ai_now_iso(), "engineVersion": "ledger-v3", "quotes": out})

@app.route("/api/argus/class-quotes")
def api_argus_class_quotes():
    """Latest asset-class proxy prices for the ledger scorer. Warms the
    regime/alerts caches first so the stash is fresh; crypto is scored via
    /crypto-watchlist directly."""
    get_market_regime_snapshot()
    _alert_etf_momentum()
    now_ts = time.time()
    out = {sym: {"price": st["price"], "ageSec": int(now_ts - st["ts"])}
           for sym, st in _ETF_LAST_PRICE.items() if now_ts - st["ts"] <= 24 * 3600}
    return jsonify({"asOf": _ai_now_iso(), "quotes": out})


# ━━━ Daily Digest (digest-v1) — the agent's morning brief ━━━
# Rule-based composition of the existing snapshots into a notification-ready
# Japanese brief. NO LLM. Consumed by the morning GitHub Actions cron (→ ntfy
# push) and available to anyone via GET. ARGUS classifies, it does not predict.
_DIGEST_CACHE = {"data": None, "expires": 0.0}
_DIGEST_TTL   = 900  # 15 min
# Best-effort previous-digest memory for the "changes" line. In-memory only —
# resets on dyno restart/sleep, so day-over-day diffs are the FRONTEND log's
# job (localStorage); this is just a bonus when the dyno stays warm.
_DIGEST_PREV  = {"dateJst": None, "posture": None}

_POSTURE_CALL_JA = {
    "EVENT_WAIT": ("WAIT", "イベント通過待ち"),
    "RISK_OFF":   ("WAIT", "リスク回避"),
    "CAUTIOUS":   ("HOLD", "慎重維持"),
    "MIXED":      ("HOLD", "方向感なし"),
    "RISK_ON":    ("HOLD", "リスク選好(追いかけ買いはしない)"),
}

def get_daily_digest():
    now = time.time()
    if _DIGEST_CACHE["data"] is not None and now < _DIGEST_CACHE["expires"]:
        return _DIGEST_CACHE["data"]

    al    = get_action_labels()
    reg   = get_market_regime_snapshot()
    ev    = get_events_snapshot()
    vol   = _vix_assess(_fred_vix_history())  # context-aware VIX (None if no data)
    news  = get_news_radar()                   # cause-side radar (30-min cached)
    posture = (al.get("marketPosture", {}) or {}).get("label") or "CAUTIOUS"
    posture_ja = (al.get("marketPosture", {}) or {}).get("rationaleJa", "")
    rg = reg.get("regime", {}) if isinstance(reg, dict) else {}
    rb = reg.get("ratesBackdrop", {}) if isinstance(reg, dict) else {}
    call, call_ja = _POSTURE_CALL_JA.get(posture, ("WAIT", "中立"))
    date_jst = datetime.now(TZ_JST).strftime("%Y-%m-%d")
    dow = "月火水木金土日"[datetime.now(TZ_JST).weekday()]

    order = {"D": 0, "D-1": 1, "D-3": 2, "D-7": 3, "D+1": 4, "normal": 5}
    events = sorted([e for e in (ev.get("events", []) if isinstance(ev, dict) else [])
                     if e.get("impact") == "high" and (e.get("daysUntil") or 0) >= 0],
                    key=lambda e: ((e.get("daysUntil") or 0), order.get(e.get("escalation"), 9)))[:5]
    top_events = [{"title": e.get("title"), "escalation": e.get("escalation"),
                   "daysUntil": e.get("daysUntil"), "localTimeJst": e.get("localTimeJst")}
                  for e in events]

    # Notable labels: anything that is not a plain HOLD, or carries high risk.
    highlights = [{"symbol": l["symbol"], "name": l["name"], "action": l["action"],
                   "changePct": (l.get("supportingData", {}) or {}).get("changePct"),
                   "reasonJa": l.get("reasonJa", "")[:80]}
                  for l in al.get("labels", [])
                  if l.get("action") != "HOLD" or l.get("risk") == "high"][:5]

    rotations = (reg.get("topRotations", []) if isinstance(reg, dict) else [])[:3]

    changes = []
    if _DIGEST_PREV["dateJst"] and _DIGEST_PREV["dateJst"] != date_jst and _DIGEST_PREV["posture"]:
        if _DIGEST_PREV["posture"] != posture:
            changes.append(f"姿勢が {_DIGEST_PREV['posture']} → {posture} に変化。")
        else:
            changes.append(f"姿勢は {posture} を継続。")

    # ── Notification-ready text (calm, scannable on a phone) ──
    # Short lines, emoji section markers, blank lines between blocks — designed
    # for the ntfy notification view (no markdown dependence).
    conf_pct = int(round((rg.get("confidence") or 0) * 100))
    L = [f"今日の姿勢: {call}", f"{posture}・{call_ja}・確信度{conf_pct}%"]
    if posture_ja:
        L += ["", posture_ja[:100]]
    # AI second opinion (when a fresh admin/cron run is cached — never run here).
    ai_cached = _AI_RESULT_CACHE["data"]
    ai_summary = None
    if ai_cached and time.time() < _AI_RESULT_CACHE["expires"] and ai_cached.get("summaryJa"):
        ai_summary = ai_cached["summaryJa"]
        L += ["", f"🤖 AI見解: {ai_summary[:100]}"]
    if rb:
        L += ["", "📊 金利・ボラティリティ",
              f"US10Y {rb.get('us10y')}% ｜ HY OAS {rb.get('hyOas')}%（{rb.get('posture')}）"]
        if vol:
            L.append(f"VIX {vol['level']} — {vol['zoneJa']}（前日比{vol['changeAbs']:+.1f}・60日分布{vol['percentile60d']}%）")
        else:
            L.append(f"VIX {rb.get('vix')}")
    if top_events:
        L += ["", "📅 イベント"]
        for e in top_events[:3]:
            when = "本日" if e["daysUntil"] == 0 else f"あと{e['daysUntil']}日"
            L.append(f"・{e['title']} — {when}")
    if highlights:
        L += ["", "👀 注目銘柄"]
        L.append(" ／ ".join(f"{h['symbol']} {h['action']}" for h in highlights[:4]))
    if rotations:
        L += ["", "🔄 資金の流れ", " ／ ".join(r.get("label", "") for r in rotations)]
    if news.get("status") == "live" and news.get("level") in ("elevated", "high"):
        hot = [t for t in news["themes"] if t["level"] != "calm"]
        if hot:
            t0 = max(hot, key=lambda t: t["count"])
            L += ["", f"⚡ ニュース検知({'重大' if news['level'] == 'high' else '増加'})",
                  f"{t0['labelJa']}: {t0['count']}件/6h"]
            if t0["headlines"]:
                L.append(f"「{t0['headlines'][0]['title'][:60]}」")
    if changes:
        L += ["", "🔁 " + " ".join(changes)]
    L += ["", "— ルールベースの状況整理。売買指示・予測ではありません —",
          f"({date_jst} {dow}曜)"]
    text_ja = "\n".join(L)

    status = al.get("status", "mock")
    payload = {
        "status": status,
        "asOf": _ai_now_iso(),
        "dateJst": date_jst,
        "engineVersion": "digest-v1",
        "posture": {"label": posture, "call": call, "rationaleJa": posture_ja,
                    "confidence": rg.get("confidence")},
        "ratesBackdrop": {k: rb.get(k) for k in ("us10y", "vix", "hyOas", "posture")} if rb else {},
        "volatility": vol,
        "topEvents": top_events,
        "topRotations": rotations,
        "labelHighlights": highlights,
        "changesSinceLastJa": changes,
        "aiSummaryJa": ai_summary,
        "news": {"level": news.get("level"), "status": news.get("status"),
                 "themes": [{"key": t["key"], "labelJa": t["labelJa"], "count": t["count"],
                             "level": t["level"],
                             "headline": (t["headlines"][0]["title"] if t["headlines"] else None)}
                            for t in news.get("themes", [])]},
        "textJa": text_ja,
        "dataLimitations": [
            "ルールベース合成(LLM不使用)。day-over-dayの厳密な差分は端末側ログが担当。",
            "サーバ側の前日比較はin-memoryのベストエフォート(再起動で消える)。",
        ],
    }
    _DIGEST_PREV["dateJst"] = date_jst
    _DIGEST_PREV["posture"] = posture
    if status != "mock":
        _DIGEST_CACHE["data"] = payload
        _DIGEST_CACHE["expires"] = now + _DIGEST_TTL
    return payload

@app.route("/api/argus/daily-digest")
def api_argus_daily_digest():
    return jsonify(get_daily_digest())


# ━━━ GPT-5.5 Pro Handoff Export (manual review — NO API call, NO cost) ━━━
_PRO_HANDOFF_CACHE = {"data": None, "expires": 0.0}
_PRO_HANDOFF_TTL   = 180  # 3 min

def _compose_pro_prompt(rates, jp, us, ev, al, cat=None, aij_status="disabled", reg=None):
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
             f"marketRegime={_st(reg) if isinstance(reg, dict) else 'unavailable'}, "
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
    if isinstance(reg, dict):
        rg = reg.get("regime", {}) or {}
        rb = reg.get("ratesBackdrop", {}) or {}
        L.append(f"### Market Regime ({reg.get('engineVersion', 'regime-v1')}, status={reg.get('status')})")
        L.append(f"- regime={rg.get('label')} conf={rg.get('confidence')} | "
                 f"growthValueAxis={rg.get('growthValueAxis')} riskDurationAxis={rg.get('riskDurationAxis')} | {rg.get('summaryJa', '')}")
        L.append(f"- ratesBackdrop: posture={rb.get('posture')} | US10Y={rb.get('us10y')} US2Y={rb.get('us2y')} "
                 f"real10Y={rb.get('real10y')} VIX={rb.get('vix')} HY_OAS={rb.get('hyOas')}% | {rb.get('rationaleJa', '')}")
        mx = reg.get("matrix", {}) or {}
        L.append(f"- matrix: x({mx.get('xLabel')})={mx.get('x')} y({mx.get('yLabel')})={mx.get('y')}")
        for g in reg.get("rotationGroups", []):
            L.append(f"    rotation {g.get('label')} [{g.get('role')}]: score={g.get('score')} status={g.get('status')} "
                     f"(1d={g.get('momentum1d')} 5d={g.get('momentum5d')} 20d={g.get('momentum20d')}) {g.get('rationaleJa', '')}")
        for t in reg.get("topRotations", []):
            L.append(f"    topRotation {t.get('label')} [{t.get('direction')}] spread={t.get('score')} | {t.get('evidenceJa', '')}")
        for s in reg.get("supportingEvidence", []):
            L.append(f"    evidence: {s}")
        L.append("- Source statuses: " + ", ".join(f"{k}={v}" for k, v in (reg.get("sourceStatuses", {}) or {}).items()))
        L.append("- NOTE: ETF rotation is a PROXY for capital flow, not direct flow; regime is rule-based (no LLM).")
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
    _aij_human = {
        "live": "LIVE (cached admin-run result)",
        "partial": "PARTIAL (only one provider succeeded / configured)",
        "no_cached_result": "NOT RUN YET (keys present, no cached result — needs an admin run)",
        "missing_keys": "DISABLED (enabled but OpenAI/Gemini API keys are NOT configured on the server)",
        "disabled": "DISABLED (AI_JUDGE_ENABLED is off)",
        "mock": "MOCK",
    }.get(aij_status, aij_status.upper())
    L.append(f"- Automated OpenAI/Gemini judgment status: {_aij_human} (/api/argus/ai-judgment status={aij_status}). "
             "Note: this is NOT marked live merely because a feature flag is on — it reflects real key/cache state.")
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
    if isinstance(reg, dict) and reg.get("status") in ("live", "partial"):
        L.append(f"- Market Regime is rule-based live-scored (regime-v1, status={reg.get('status')}): ETF/index/HY-OAS proxies, NOT direct capital flow. Alerts scanner is not live yet (mock).")
    else:
        L.append("- Market Regime scoring is unavailable this refresh (mock). Alerts scanner is not live yet (mock).")
    L.append("- No historical judgment log and no user-specific exposure weighting yet.")
    L.append("- Today/CommandCenter hero + previews are live-composed (action-labels + market-regime + events). The Action Alerts page still uses seed data.")
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
    cat = get_catalysts_snapshot(); reg = get_market_regime_snapshot()
    def _st(x): return x.get("status", "mock") if isinstance(x, dict) else "mock"
    # Truthful automated-AI-judgment status (key-aware): disabled / missing_keys /
    # partial / no_cached_result / live — NEVER 'live' merely because the feature
    # flag is on. Single source of truth shared with /integrations.
    aij_status = _ai_judgment_truth()["status"]
    src = {"rates": _st(rates), "japanWatchlist": _st(jp), "usWatchlist": _st(us),
           "events": _st(ev), "actionLabels": _st(al), "catalysts": _st(cat),
           "marketRegime": _st(reg)}
    warnings = [f"{k} is {v}" for k, v in src.items() if v != "live"]
    prompt = _compose_pro_prompt(rates, jp, us, ev, al, cat, aij_status, reg)
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


# ━━━ Symbol search (Add Asset candidates) ━━━
# Backend proxy so the Add-Asset UI can search by name/code instead of requiring
# an exact symbol. Keys stay server-side. JP = J-Quants listed-issue master
# (cached 24h), US = Twelve Data symbol_search, Crypto = CoinGecko search (no
# key). Read-only, frontend-safe; degrades to empty results on failure.
_JQ_MASTER_CACHE = {"data": None, "expires": 0.0}   # full JP master, 24h
_SEARCH_Q_CACHE = {}                                # (market,q) -> {data, expires}, 10m
_SEARCH_MAX = 12

def _jq_master():
    """All listed JP issues (cached 24h): list of {code4, ja, en, mkt}."""
    if _JQ_MASTER_CACHE["data"] is not None and time.time() < _JQ_MASTER_CACHE["expires"]:
        return _JQ_MASTER_CACHE["data"]
    if not _JQUANTS_API_KEY:
        return []
    rows, headers, params = [], {"x-api-key": _JQUANTS_API_KEY}, {}
    try:
        for _ in range(40):  # paginate the full master
            r = requests.get(f"{_JQUANTS_BASE}/equities/master", headers=headers, params=params, timeout=12)
            r.raise_for_status()
            body = r.json()
            for x in body.get("data", []):
                code = str(x.get("Code", ""))
                if not code:
                    continue
                rows.append({"code4": code[:4], "ja": x.get("CoName", "") or "",
                             "en": x.get("CoNameEn", "") or "", "mkt": x.get("MktNm", "") or ""})
            pk = body.get("pagination_key")
            if not pk:
                break
            params["pagination_key"] = pk
        _JQ_MASTER_CACHE["data"] = rows
        _JQ_MASTER_CACHE["expires"] = time.time() + 24 * 3600
        return rows
    except Exception:
        return _JQ_MASTER_CACHE["data"] or []

def _jp_query_is_code(q):
    """True when the query looks like a TSE code prefix. TSE codes are 4 chars,
    DIGIT-LED and may END IN A LETTER (285A, 314A, 133A) — `isdigit()` missed
    those, which silently broke code search for every alphanumeric ETF/stock."""
    return bool(re.match(r"^[0-9][0-9A-Za-z]{0,3}$", q))

def _search_jp(q):
    ql = q.lower()
    qu = q.upper()
    code_like = _jp_query_is_code(q)
    out = []
    for r in _jq_master():
        hit = (code_like and r["code4"].upper().startswith(qu)) \
            or (ql in r["ja"].lower() or ql in r["en"].lower())
        if hit:
            out.append({"symbol": r["code4"], "name": r["en"] or r["ja"], "nameJa": r["ja"],
                        "exchange": r["mkt"], "type": "jp_equity"})
        if len(out) >= _SEARCH_MAX:
            break
    return out, ("live" if _jq_master() else "unavailable")

def _search_us(q):
    if not _TWELVEDATA_API_KEY:
        return [], "unavailable"
    try:
        r = requests.get("https://api.twelvedata.com/symbol_search",
                         params={"symbol": q, "outputsize": 20, "apikey": _TWELVEDATA_API_KEY}, timeout=10)
        r.raise_for_status()
        data = r.json().get("data", []) if isinstance(r.json(), dict) else []
        out = []
        for x in data:
            t = (x.get("instrument_type") or "").lower()
            if "stock" not in t and "etf" not in t and t:   # prefer equities/ETFs
                continue
            out.append({"symbol": x.get("symbol", ""), "name": x.get("instrument_name", ""),
                        "nameJa": "", "exchange": x.get("exchange", ""), "type": "us_equity"})
            if len(out) >= _SEARCH_MAX:
                break
        return out, "live"
    except Exception:
        return [], "error"

def _search_crypto(q):
    try:
        r = requests.get("https://api.coingecko.com/api/v3/search", params={"query": q}, timeout=10)
        r.raise_for_status()
        coins = r.json().get("coins", []) if isinstance(r.json(), dict) else []
        out = []
        for c in coins[:_SEARCH_MAX]:
            out.append({"symbol": (c.get("symbol", "") or "").upper(), "name": c.get("name", ""),
                        "nameJa": "", "exchange": "", "type": "crypto", "coingeckoId": c.get("id", "")})
        return out, "live"
    except Exception:
        return [], "error"

@app.route("/api/argus/symbol-search")
def api_argus_symbol_search():
    q = (request.args.get("q", "") or "").strip()[:40]
    market = (request.args.get("market", "") or "").strip().upper()
    if len(q) < 1 or market not in ("JP", "US", "CRYPTO"):
        return jsonify({"status": "mock", "query": q, "market": market, "results": []})
    ck = (market, q.lower())
    cached = _SEARCH_Q_CACHE.get(ck)
    if cached and time.time() < cached["expires"]:
        return jsonify(cached["data"])
    if market == "JP":
        results, st = _search_jp(q)
    elif market == "US":
        results, st = _search_us(q)
    else:
        results, st = _search_crypto(q)
    payload = {"status": st, "query": q, "market": market, "results": results}
    _SEARCH_Q_CACHE[ck] = {"data": payload, "expires": time.time() + 600}
    return jsonify(payload)


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
