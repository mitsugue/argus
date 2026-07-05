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
from argus_rules import (  # pure scoring layer extracted v10.37 (#9)
    _scout_score_bucket, _margin_signal, _margin_assess_lines,
    _jsf_assess_lines, _short_disclosed_assess, _detect_gap,
    _entry_metrics, _flow_inference, _entry_scout_assess, _scout_narrative)
import argus_events  # 24/7 gear-shift event backbone (pure foundation, v10.39)
import argus_research  # evidence-first deterministic research dossier (v10.41)
import argus_event_store  # Lean durable event store: branch snapshot/restore (v10.42)
import argus_ai_cost  # AI cost ledger + hard budget stops (pure math, v10.50)
import argus_calibration  # Calibration Ledger v4 foundation: cohorts/epochs/scoring (pure, v10.68)
import argus_market_clock  # Calibration Ledger v4 Phase 2: market-specific forecast clocks (pure, v10.69)
import argus_posture  # Calibration Ledger v4: multidimensional posture scoring (pure, v10.74)
import argus_decision_value  # Decision Value Ledger v1: net expectancy / risk (pure, research-only, v10.75)
import argus_watchlist_sync  # Calibration Ledger v4 Layer 2B: owner watchlist sync validation (pure, v10.74)
import argus_downside  # Downside Incident Response + cause attribution (pure, decision-support only, v10.98)
import argus_tdnet  # TDnet (適時開示) disclosure title classifier (pure, v10.101)
import argus_jquants_tdnet  # official J-Quants TDnet Add-on classify/map/status (pure, v11.1)
import argus_evidence_pack  # canonical Evidence Pack — the decision spine's input (pure, v11.2)
import argus_official_event_lifecycle  # official disclosures as lifecycle-tracked events (pure, v11.3)
import argus_official_event_store  # durable official-event serialize/merge/restore (pure, v11.3.1)
import argus_macro_event_analysis  # C.A.O.S. macro pre/post: phase resolver + prompts (pure, v11.3.2)
import argus_macro_event_store  # durable macro-analysis merge/serialize (pure, v11.3.2)
import argus_dashboard_event_summary  # unified top-card event model + de-dup (pure, v11.4.1)
import argus_macro_results  # official macro-result parsers (CPI/PPI/FOMC/PCE/GDP/JOLTS, pure, v11.5)
import argus_macro_market_reaction  # macro market-reaction windows + impact fallbacks (pure, v11.5)
import argus_news_i18n  # news headline JP-translation cache helpers (pure, v11.5)
import argus_news_freshness  # news freshness gate — old news never a current lead (pure, v11.5.3)
import argus_investment_universe  # Core Portfolio asset-class universe (pure, v11.5.3)
import argus_caos_source_universe  # per-asset-class source registry + discovery resolution (pure, v11.5.3)
import argus_caos_watchtower_plan  # C.A.O.S. watchtower target plan (pure, v11.5.3)
import argus_caos_patrol  # always-on patrol schedule (pure, v11.5.4)
import argus_caos_source_sweep  # maximum-available source sweep helpers (pure, v11.5.4)
import argus_caos_patrol_store  # 24h patrol ledger — soak proof (pure, v11.5.5)
import argus_institutional_intel  # formal institutional signal layer (pure, v11.6.0)
import argus_flow_attribution  # Big Money / Flow Attribution engine (pure, v11.7.0)
import argus_position_exposure  # Position/Exposure engine (pure, v11.8.0 — backend sees NO holdings)
import argus_portfolio_sync  # Portfolio Sync/Snapshot foundation (pure, v11.9.0 — models + redaction; server plaintext sync disabled)
import argus_supply_demand  # Supply/Demand Intelligence for JP stocks (pure, v11.10.0 — 需給ランク; never fabricates JSF/margin)
import argus_decision_quality  # Decision Quality/Backtest foundation (pure, v11.11.0 — records live device-local only)
import argus_action_priority  # Action Priority engine (pure, v11.12.0 — attention routing, never trade orders)
import argus_session_brief  # Morning/Session Brief engine (pure, v11.13.0 — 今日の作戦, never trade orders)
import argus_notifications  # Notification engine (pure, v11.14.0 — device-local delivery; server stores none)
import argus_learning_review  # Learning/Decision Review (pure, v11.15.0 — device-local aggregation; sample discipline)
import argus_backup_safety  # Backup Safety/Vault Guard (pure, v11.16.0 — device-side; server knows nothing)
import argus_scenario  # Scenario Engine (pure, v11.17.0 — 条件付き分岐; 確率は帯のみ・%断定禁止)
import argus_trade_plan  # Entry/Exit Planning (pure, v11.18.0 — 計画のみ; 執行語・注文なし)
import argus_portfolio_strategy  # Portfolio Strategy/FIRE (pure, v11.19.0 — 戦略は端末内; 公開はredacted)
import argus_fire_core  # FIRE Core/投信追跡 (pure, v11.19.1 — 全データ端末内; 公開はredacted)
import argus_review_pack  # AI Review Pack (pure, v11.20.0 — 端末内合成; サーバー保存/自動送信なし)
import argus_data_quality  # Data Quality Console (pure, v11.22.0 — 鮮度捏造なし; 意図的無効≠障害)
import argus_mover_cause  # Mover Cause Engine: confirmed/probable/candidate/no_lead ladder (pure, v11.3.3)
import argus_mover_cause_store  # durable mover-cause merge/serialize (pure, v11.3.3)
import argus_mover_cause_refresh  # refresh queue + quality/SLA diagnostics (pure, v11.3.4)
import argus_market_confirmation  # Market Confirmation v1.5 from existing data (pure, v11.3.4)
import argus_learning_memory  # Learning Memory: public-safe history → cohort lessons (pure, v11.4.0)
import argus_learning_memory_store  # durable learning-memory merge/serialize (pure, v11.4.0)
import argus_attribution  # Cause Attribution Integrity: trigger/vulnerability/amplifier/unknown (pure, v10.116)
import argus_signal  # Action Level signal resolver (structured signal for APIs/ledgers, pure, v10.124)
import argus_important_events  # Novice event explanations + owner-relevance priority (pure, v10.138)
import argus_research_mesh     # Institutional Intelligence + research mesh core (pure, v1, v10.147)
import argus_licensed_feeds     # LAYER 1 licensed feed adapters (disabled until contracted, v10.147)
import argus_relationship_graph  # §15 cross-market relationship graph (pure, v10.150)
import argus_research_swarm      # §12 deterministic research-mission orchestrator (pure, NO LLM, v10.150)
import argus_positioning         # §14 institutional positioning aggregator (pure, v10.150)
import argus_daily_brief         # §21 owner daily institutional brief (pure, v10.150)
import argus_visibility          # Visibility Risk Guard (aggregates data-visibility signals, pure, v10.195)
import argus_market_depth         # Market Depth capability report (feeds the guard, pure, v10.196)
import argus_mission_trigger       # §12 research-mission trigger gating (pure, v10.198)
import argus_event_card            # EventCard v2 canonical research object (pure, ARGUS Pro v11)
import argus_caos_audit            # CAOS association audit trail (pure, ARGUS Pro v11)
from flask import Flask, jsonify, request
from collections import deque
import hashlib
import hmac
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
_RL_MAX     = 300         # default requests / IP / minute — v11.13.1: Today now
                          # mounts ~20 cached-read endpoints and polls them across
                          # the owner's Mac+iPhone+iPad on ONE home IP; 120 made the
                          # app 429 ITSELF (需給/フロー消失・crypto BTC/ETHのみ残留,
                          # observed 2026-07-04). All these are cheap cache reads.
# Heavy (cache-busting) budget: was 30/min pre-15s-polling. Legit usage is now
# ~10-12/min PER DEVICE (jp+us watchlist every 15s + action-labels) and one
# home IP often runs phone+Mac+preview simultaneously — 30 made the app
# rate-limit ITSELF (observed 2026-06-13). 90 keeps 3 devices + scout taps
# comfortable while still bounding abuse (all heavy endpoints are cached).
_RL_MAX_HEAVY = 200       # 90→140 (v11.8.1) → 200 (v11.13.1): every release
                          # added polling; 3 devices + preview share one IP and all
                          # heavy endpoints are cached reads on Render Standard.
# Interactive symbol-search gets its OWN bucket (v11.8.1) so background quote
# polling can never starve a human typing in the search box into 「混雑」.
_RL_MAX_SEARCH = 30
_RL_MAX_IPS = 5000        # memory bound on a public endpoint

def _rl_client_ip():
    fwd = (request.headers.get("X-Forwarded-For", "").split(",")[0] or "").strip()
    return request.headers.get("CF-Connecting-IP") or fwd or (request.remote_addr or "?")

@app.before_request
def _rate_limit():
    p = request.path
    if not p.startswith("/api/argus/") or request.method == "OPTIONS":
        return None
    # v11.8.1 (owner report 「検索すると混雑してるとよく言われる」): symbol-search
    # used to share the heavy bucket with the app's own quote polling (Mac+
    # iPhone+iPad on one home IP), so background polling starved interactive
    # search into 429s. Search now has its OWN per-IP bucket — polling can no
    # longer eat the search budget — and the heavy budget is raised for the
    # v11.7/11.8 polling growth (all cached reads on Render Standard 2GB).
    search = "symbol-search" in p
    heavy = (not search) and any(k in request.args
                                 for k in ("symbols", "jp", "us", "ids", "q", "symbol"))
    limit = _RL_MAX_SEARCH if search else (_RL_MAX_HEAVY if heavy else _RL_MAX)
    now = time.time()
    ip = _rl_client_ip() + (":search" if search else "")
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

@app.route("/healthz")
def healthz():
    """Liveness + build metadata (v10.38). Public, secret-free. buildSha lets
    the smoke-test workflow confirm WHICH commit is live before asserting, and
    gives the backend the build identity GPT's version-sync review asked for."""
    return jsonify({
        "status": "ok",
        "engineVersion": "argus-backend-v1",
        "buildSha": (os.environ.get("RENDER_GIT_COMMIT", "")[:7] or None),
        "asOf": _ai_now_iso(),
    })

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
    """DEPRECATED (v10.35): this used to read a Render-EPHEMERAL local jsonl
    (argus_ledger.aggregate_stats) that is always empty in production, so it
    reported all-zero hit rates — a footgun for any external caller. It now
    returns the REAL scored calibration from the `ledger` branch summary (the
    same source the Today screen uses). Read the ledger branch directly going
    forward; this shim stays only so old links don't silently lie."""
    real = _ledger_summary() or {}
    return jsonify({
        "deprecated": True,
        "noteJa": "旧実装はRender揮発ファイルを読み常時ゼロでした。現在は台帳ブランチの実集計"
                  "(_ledger_summary)に接続。今後はledgerブランチを直接参照してください。",
        "source": "ledger-branch-summary",
        "updated": real.get("updated"),
        "overall": real.get("overall"),
        "byPosture": real.get("byPosture"),
        "layers": real.get("layers"),
        "aiDirectional": real.get("aiDirectional"),
    })


@app.route("/api/argus/calibration/cohorts")
def api_argus_calibration_cohorts():
    """Calibration Ledger v4 (Phase 1) — the cohort MODEL (read-only).

    Exposes only the fixed server-side structure (regime sensors / tactical
    benchmark / experimental flags / factor groups). The owner's dynamic
    watchlist (Layer 2B) is NOT here — it lives in a private store and is never
    served to anonymous callers. Also applies the new factor-group-weighted
    aggregation to the LIVE Layer-1 byMember stats, non-destructively, so you can
    see how equal-group-weighting differs from the flat 16-symbol average."""
    C = argus_calibration
    # Demonstrate the section-14 fix on real data (horizon 1d byMember hitRates).
    fg_demo = None
    try:
        summ = _ledger_summary() or {}
        bm = (((summ.get("layers") or {}).get("layer1") or {}).get("byHorizon") or {}) \
            .get("1", {}).get("byMember") or {}
        per_sym = {s: float(v.get("hitRate")) for s, v in bm.items()
                   if isinstance(v, dict) and v.get("hitRate") is not None}
        if per_sym:
            flat = round(sum(per_sym.values()) / len(per_sym), 4)
            agg = C.factor_group_aggregate(per_sym)
            fg_demo = {
                "flatEqualSymbolWeighted": flat,
                "equalGroupWeighted": agg["overallEqualGroupWeighted"],
                "factorGroupScores": agg["factorGroupScores"],
                "noteJa": "従来の16銘柄フラット平均と、相関を抑えたファクターグループ等加重の比較"
                          "(米株3銘柄が過大に効かないようにする・section 14)",
            }
    except Exception:
        fg_demo = None
    def _named(syms):
        return [{"symbol": s, "name": C.display_name(s) or s,
                 "factorGroup": C.factor_group_of(s)} for s in syms]
    return jsonify({
        "schemaVersion": C.SCHEMA_VERSION,
        "regimeSensorUniverseVersion": C.UNIVERSE_VERSION,
        "tacticalBenchmarkVersion": C.TACTICAL_BENCHMARK_VERSION,
        "factorGroupVersion": C.FACTOR_GROUP_VERSION,
        "cohortVersion": C.COHORT_VERSION,
        "phase": "v4-universe-v2 (regime_sensor_v2 / tactical_benchmark_v2)",
        "cohorts": {
            C.COHORT_REGIME_SENSOR: {
                "labelJa": "固定レジームセンサー(校正の背骨・16銘柄・不変)",
                "count": len(C.REGIME_SENSORS),
                "members": _named(C.REGIME_SENSORS),
            },
            C.COHORT_TACTICAL_FIXED: {
                "labelJa": "固定タクティカルベンチ(縦断比較用・14銘柄・分散)",
                "count": len(C.TACTICAL_BENCHMARK),
                "jp": _named([s for s in C.TACTICAL_BENCHMARK if s[0].isdigit()]),
                "us": _named([s for s in C.TACTICAL_BENCHMARK if not s[0].isdigit()]),
                "noteJa": "5803 フジクラは意図的に固定ベンチに保持。5801/METAは所有者ウォッチリストで利用可。",
            },
            C.COHORT_OWNER_WATCHLIST: {
                "labelJa": "所有者ウォッチリスト(動的・private保存・採点はPhase4で有効化)",
                "symbols": [], "status": "pending_private_store",
                "noteJa": "5801/META/285A/9501/6584/ETH 等が想定。2Aと重複しても予測は1件・コホートは別集計。",
            },
            C.COHORT_EXPERIMENTAL: {
                "labelJa": "実験コホート(旧「Layer3=6584固定」を廃止しフラグ制に置換)",
                "examples": list(C._MANUAL_EXPERIMENTAL.keys()),
                "flags": list(C.EXPERIMENTAL_FLAGS),
            },
        },
        "contextVariables": {
            "noteJa": "回帰・地合い説明用の文脈変数。等加重のリターン採点センサーには混ぜない"
                      "(VIXは逆相関リスク、USDJPYは文脈依存、金利/HY OASは水準でリターンでない)。",
            "variables": C.context_variables(),
        },
        "factorGroups": {g: list(s) for g, s in C.FACTOR_GROUPS.items()},
        "tacticalFactorRoles": C.TACTICAL_FACTOR_GROUPS,
        "layer1FactorGroupDemo": fg_demo,
    })


@app.route("/api/argus/decision-value/summary")
def api_argus_decision_value_summary():
    """Decision Value Ledger v1 (Phase 1: engine ready, no shadow records yet).

    RESEARCH SIMULATION ONLY — no order routes, no broker, no execution. Measures
    "would a defined policy have positive value AFTER costs/risk?" — SEPARATE from
    the calibration (Brier/RPS) question. Shadow recording + per-policy expectancy
    arrive in Phase 2; this exposes engine readiness + versions only."""
    DV = argus_decision_value
    # v10.195: report the REAL phase. Public payload carries per-policy n + sample
    # stage ONLY — never netR (real outcomes stay owner-gated in the private store).
    pub = _dv_shadow_public_summary()
    return jsonify({
        "schemaVersion": DV.DECISION_VALUE_SCHEMA,
        "costModelVersion": DV.COST_MODEL_VERSION,
        "riskModelVersion": DV.RISK_MODEL_VERSION,
        "phase": pub["phase"],
        "status": pub["status"],
        "shadow": pub["shadow"],
        "blockersJa": pub.get("blockersJa"),
        "noteJa": "「校正(Brier/RPS)が良い ≠ 儲かる」を測る別台帳。明示的な不変ポリシーで shadow "
                  "(仮想)シミュレーションし、現実的コスト後の純期待値・リスクオブルインを評価。"
                  "Phase1は純エンジン+テスト(21件)のみ。shadow記録/ポリシー別集計はPhase2。",
        "engine": {
            "metrics": ["netExpectancyR", "payoffRatio", "profitFactor",
                        "riskOfRuin(blockBootstrapMonteCarlo)", "noTradeValue",
                        "kelly(disabled_by_default)"],
            "sampleStages": ["burn_in(<30)", "exploratory(30-59)",
                             "provisional(60-119)", "validation(120+) — never 'proven'"],
        },
        "safety": DV.DISCLAIMER + " No broker, no order routes, no auto-trading.",
    })


@app.route("/api/argus/decision-value/policies")
def api_argus_decision_value_policies():
    """Decision Value — the immutable Policy Registry + comparison baselines
    (read-only). Policies define eligibility/entry/exit so shadow results are
    reproducible + hindsight-free. RESEARCH ONLY — no order routes."""
    return jsonify(argus_decision_value.list_policies())


# ── Decision Value shadow operations (Phase 1 START, v10.195) ────────────────
# Records eligible decisions as IMMUTABLE shadow candidates in the OWNER-PRIVATE
# store, and scores due horizons. RESEARCH SIMULATION ONLY — no order/broker/execute
# route is created; real entry/exit prices + netR live ONLY in the private repo and
# never appear in any public payload or the ledger branch.
def _dv_shadow_pick_policy(action):
    a = str(action or "").upper()
    if a in ("BUY DIP", "ADD", "ENTER"):
        return "daily_next_session_long_v1"
    return "no_trade_control_v1"   # WAIT/HOLD/EXIT/etc → the no-trade control arm

def _dv_shadow_record():
    """Write today's shadow candidates (one per prediction) to the private store,
    immutable. Reuses the ledger prediction snapshot (has symbol/market/price/action)."""
    if not _layer2b_store_configured():
        return {"ok": False, "reason": "private_store_not_configured"}
    import json as _json
    snap = get_prediction_snapshot()
    date = snap.get("dateJst")
    as_of = snap.get("asOf")
    # Capture the visibility state ONCE at decision time so each record is auditable.
    try:
        _vg = _visibility_guard()
    except Exception:
        _vg = {}
    _cap = _vg.get("confidenceCap")
    _blocked = list(_vg.get("blockedActions") or [])
    cands = []
    for p in (snap.get("predictions") or []):
        price = p.get("price")
        if not isinstance(price, (int, float)):
            continue
        action = p.get("action")
        pid = _dv_shadow_pick_policy(action)
        conf_b = p.get("confidence")
        conf_a = (round(min(conf_b, _cap), 3) if isinstance(conf_b, (int, float)) and _cap is not None else conf_b)
        # aggressive long entry that the guard situationally blocks = a downgraded decision
        downgraded = ("ENTER" in _blocked) and (pid == "daily_next_session_long_v1")
        # v11.3: what the desk KNEW about this symbol's official-disclosure lifecycle at
        # decision time (latest MATERIAL event; in-memory store, no fetch).
        try:
            _oe = _official_events_by_symbol(p.get("symbol"), material_only=True)
            _oe_ctx = argus_official_event_lifecycle.evidence_ref(_oe[0]) if _oe else None
            if _oe_ctx:
                _oe_ctx["missingConfirmations"] = (_oe[0].get("missingConfirmations") or [])
        except Exception:
            _oe_ctx = None
        rec = argus_decision_value.build_shadow_decision(
            policy_id=pid, symbol=p.get("symbol"), market=p.get("market"),
            decision_price=price, decision_ts=as_of,
            eligible=(pid != "no_trade_control_v1"),
            posture_before=action, posture_after=action,
            confidence_before=conf_b, confidence_after=conf_a,
            blocked_actions=_blocked, visibility_downgraded=downgraded,
            official_event=_oe_ctx)
        rec["actionAtDecision"] = action
        cands.append(rec)
    if not cands:
        return {"ok": False, "reason": "no_predictions"}
    ok = _gh_private_put(f"decision_value/candidates/{date}.json",
                         _json.dumps({"date": date, "asOf": as_of, "candidates": cands},
                                     ensure_ascii=False, indent=1),
                         f"dv shadow candidates {date}", overwrite=False)  # immutable
    return {"ok": bool(ok), "date": date, "recorded": len(cands)}

def _dv_shadow_score():
    """Score candidates whose 1-day horizon has elapsed, using the latest price as
    exit and the decision-close as the entry proxy (Phase-1; intraday entry arrives
    in Phase 2). Writes scores + rebuilds the private summary. Best-effort."""
    if not _layer2b_store_configured():
        return {"ok": False, "reason": "private_store_not_configured"}
    import json as _json, glob as _glob  # noqa: F401 (glob unused; listing via API)
    # List candidate files via the GitHub contents API (private).
    repo = os.environ.get("ARGUS_LAYER2B_PRIVATE_REPO", "")
    scored_records, files = [], []
    try:
        r = requests.get(f"https://api.github.com/repos/{repo}/contents/decision_value/candidates",
                         headers=_gh_private_headers(), timeout=15)
        if r.status_code == 200:
            files = [f["name"] for f in r.json() if str(f.get("name", "")).endswith(".json")]
    except Exception:
        pass
    today = datetime.now(TZ_JST).strftime("%Y-%m-%d")
    for fn in sorted(files)[-12:]:
        d = fn[:-5]
        if d >= today:
            continue                                   # not yet elapsed
        content, _ = _gh_private_get(f"decision_value/candidates/{fn}")
        if not content:
            continue
        try:
            day = _json.loads(content)
        except Exception:
            continue
        # realized prices now (proxy exit at horizon)
        members = [{"symbol": c.get("symbol"), "market": c.get("market")} for c in day.get("candidates", [])]
        prices = {}
        try:
            prices = _layer2b_live_prices(members)
        except Exception:
            prices = {}
        for c in day.get("candidates", []):
            sym = c.get("symbol")
            live = prices.get(sym)
            exit_px = live[0] if live else None
            dp = c.get("decisionPrice")
            sc = argus_decision_value.score_shadow_record(
                record=c, entry_price=dp, entry_ts=(str(c.get("decisionTs")) + "~next"),
                exit_price=exit_px,
                invalidation=(dp * 0.97 if isinstance(dp, (int, float)) else None))
            sc["horizonDate"] = d
            scored_records.append(sc)
    agg = argus_decision_value.aggregate_by_policy(scored_records)
    agg["asOf"] = _ai_now_iso()
    agg["scoredCount"] = len([s for s in scored_records if s.get("outcomeStatus") == "scored"])
    agg["note"] = ("Phase-1 shadow: entry uses the decision-close proxy pending intraday "
                   "history (Phase 2). Research simulation only — no orders.")
    _gh_private_put("decision_value/summary.json",
                    _json.dumps(agg, ensure_ascii=False, indent=1),
                    f"dv shadow summary {today}", overwrite=True)
    return {"ok": True, "scored": agg["scoredCount"], "policies": list(agg.get("policies", {}).keys())}

def _dv_shadow_has_records():
    if not _layer2b_store_configured():
        return False
    content, _ = _gh_private_get("decision_value/summary.json")
    return bool(content)

def _dv_shadow_phase():
    return "phase1_shadow_recording_active" if _dv_shadow_has_records() else "v1-phase1-engine-only"

def _dv_shadow_public_summary():
    """PUBLIC-SAFE Decision Value status: phase + per-policy n + sampleStage ONLY.
    Never exposes netR / real prices (owner-gated). Reports exact blockers."""
    if not _layer2b_store_configured():
        return {"phase": "v1-phase1-engine-only", "status": "blocked_pending_private_store",
                "shadow": None,
                "blockersJa": "Decision Valueシャドー記録には、Layer 2B用のprivate GitHubリポ"
                              "(ARGUS_LAYER2B_PRIVATE_REPO / _TOKEN)が必要です。設定済みなら"
                              "毎営業日16:05にshadow-runで自動記録・採点します。"}
    import json as _json
    content, _ = _gh_private_get("decision_value/summary.json")
    if not content:
        return {"phase": "v1-phase1-engine-only", "status": "engine_ready_no_records_yet",
                "shadow": None,
                "blockersJa": "private storeは設定済み。次回のshadow-run(毎営業日16:05)で記録が始まります。"}
    try:
        s = _json.loads(content)
    except Exception:
        return {"phase": "phase1_shadow_recording_active", "status": "parse_error", "shadow": None}
    safe_pol = {pid: {"n": v.get("n"), "sampleStage": v.get("sampleStage")}
                for pid, v in (s.get("policies") or {}).items()}
    safe_nt = {pid: {"n": v.get("n"), "sampleStage": v.get("sampleStage")}
               for pid, v in (s.get("noTrade") or {}).items()}
    return {"phase": "phase1_shadow_recording_active", "status": "phase1_shadow_recording_active",
            "shadow": {"policies": safe_pol, "noTrade": safe_nt, "scoredCount": s.get("scoredCount"),
                       "asOf": s.get("asOf"), "note": s.get("note")},
            "blockersJa": None}

@app.route("/api/argus/decision-value/shadow-run", methods=["POST"])
def api_argus_decision_value_shadow_run():
    """Admin: record today's shadow candidates + score due horizons in the PRIVATE
    store. Append-only, immutable candidates. NO order/broker/execute — research only."""
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    if not _layer2b_store_configured():
        return jsonify({"ok": False, "reason": "private_store_not_configured"}), 200
    try:
        rec = _dv_shadow_record()
        sco = _dv_shadow_score()
        return jsonify({"ok": True, "record": rec, "score": sco})
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {str(e)[:160]}"}), 500

@app.route("/api/argus/decision-value/shadow-summary", methods=["GET", "POST"])
def api_argus_decision_value_shadow_summary():
    """Owner-gated FULL shadow summary from the private store (includes netR). The
    public /decision-value/summary carries only n + sampleStage."""
    body = request.get_json(silent=True) or {}
    token = body.get("ownerToken") if isinstance(body, dict) else None
    ok, err, code = _require_owner_sync(body_token=token)
    if not ok:
        return jsonify(err), code
    if not _layer2b_store_configured():
        return jsonify({"status": "disabled_pending_private_store"})
    import json as _json
    content, _ = _gh_private_get("decision_value/summary.json")
    if not content:
        return jsonify({"status": "no_data_yet"})
    try:
        return jsonify({"status": "ok", "summary": _json.loads(content)})
    except Exception:
        return jsonify({"status": "parse_error"})


def _dv_status_public_dict():
    """PUBLIC-SAFE Decision Value status dict (route + Evidence Pack both read this)."""
    pub = _dv_shadow_public_summary()
    shadow = pub.get("shadow") or {}
    pol = shadow.get("policies") or {}
    nt = shadow.get("noTrade") or {}
    total = sum((v or {}).get("n", 0) for v in list(pol.values()) + list(nt.values()))
    scored = shadow.get("scoredCount") or 0
    configured = _layer2b_store_configured()
    # phase is derived from what actually exists, never asserted.
    if not configured:
        phase = "not_configured"
    elif total <= 0:
        phase = "engine_ready_no_records_yet"
    elif scored <= 0:
        phase = "shadow_recording_active"
    else:
        phase = "scoring_active"
    stages = [v.get("sampleStage") for v in list(pol.values()) + list(nt.values()) if v.get("sampleStage")]
    sample_stage = "usable" if any(s in ("validation", "provisional") for s in stages) else (
        "early_signal" if any(s == "exploratory" for s in stages) else ("burn_in" if stages else "none"))
    return {
        "schemaVersion": argus_decision_value.DECISION_VALUE_SCHEMA,
        "phase": phase,
        "privateStoreConfigured": configured,
        "lastShadowRunAt": shadow.get("asOf"),
        "totalRecords": total,
        "scoredCount": scored,
        "pendingOutcomeCount": max(0, total - scored),
        "policyCounts": {pid: (v or {}).get("n", 0) for pid, v in pol.items()},
        "noTradeCounts": {pid: (v or {}).get("n", 0) for pid, v in nt.items()},
        "sampleStage": sample_stage,
        "reasonJa": pub.get("blockersJa") or "",
        "disclaimer": "Research simulation only. No order was or will be submitted.",
    }


@app.route("/api/argus/decision-value/status")
def api_argus_decision_value_status():
    """PUBLIC-SAFE Decision Value status (ARGUS Pro v11). Auditable phase + per-policy
    counts + sampleStage ONLY — never netR / prices / holdings (those stay owner-private).
    phase can never claim recording/scoring unless records/scores actually exist."""
    return jsonify(_dv_status_public_dict())


# ── Calibration Operations (v10.195) — is v4 capture actually happening? ─────
_CALIB_V4_CACHE = {"data": None, "expires": 0.0}

def _calibration_v4_summary():
    """Read the parallel v4 dry-run summary (calibration_v1/summary.json) off the
    ledger branch. None until the GitHub Action has written it (fresh env → 404)."""
    now = time.time()
    if _CALIB_V4_CACHE["data"] is not None and now < _CALIB_V4_CACHE["expires"]:
        return _CALIB_V4_CACHE["data"]
    out = None
    try:
        import json as _json
        r = requests.get(f"{_LEDGER_RAW_BASE}/calibration_v1/summary.json", timeout=12)
        if r.status_code == 200 and r.text.strip().startswith("{"):
            out = _json.loads(r.text)
    except Exception:
        out = None
    _CALIB_V4_CACHE["data"] = out
    _CALIB_V4_CACHE["expires"] = now + 30 * 60
    return out

def _calibration_coverage():
    """Layer-1 session coverage from the live snapshot: how many of the fixed 16
    regime sensors recorded today. Expected count comes from the CONSTANTS (not the
    recorded rows) so a dropped sensor reads as missing, never as 100%."""
    try:
        snap = get_prediction_snapshot()
    except Exception:
        return {"expected": 16, "recorded": 0, "missing": None, "layer1SessionCoverage": 0.0,
                "contextVarsPresent": 0, "note": "snapshot unavailable"}
    expected = [t[0] for t in _L1_SENSORS_JP] + list(_L1_SENSORS_US) + ["BTC"]
    # v10.203 fix: the snapshot's sensor rows key the ticker as "sensor" (not
    # "symbol") — reading the wrong key made every row None → a false 0/16 coverage.
    recorded = {(r.get("sensor") or r.get("symbol")) for r in (snap.get("sensors") or []) if isinstance(r, dict)}
    missing = sorted(set(expected) - recorded)
    return {"expected": len(expected), "recorded": len(recorded & set(expected)),
            "missing": missing, "layer1SessionCoverage": round((len(expected) - len(missing)) / len(expected), 4),
            "contextVarsPresent": len(snap.get("contextVariables") or []),
            "rollingPerSensorCoverage": None}   # needs day-history (Phase later)

@app.route("/api/argus/calibration/ops")
def api_argus_calibration_ops():
    """Calibration Operations — is usable v4 capture happening, and can the clean
    epoch be activated? Read-only; NO owner/Layer-2B data. Honest inputs to
    readiness_check (no fabricated coverage)."""
    C = argus_calibration
    led = _ledger_summary() or {}
    overall = led.get("overall") or {}
    v3days = int(overall.get("days") or 0)
    v4 = _calibration_v4_summary()
    cov = _calibration_coverage()
    l1 = cov.get("layer1SessionCoverage") or 0.0
    rolling = cov.get("rollingPerSensorCoverage")
    readiness = C.readiness_check(
        required_sensor_coverage=l1,
        layer1_session_coverage=l1,
        rolling_per_sensor_coverage=(rolling if isinstance(rolling, (int, float)) else 0.0),
        unresolved_write_failures=0,
        stale_price_forecasts=len(cov.get("missing") or []),
        cohorts_finalized=True,
        scoring_tests_pass=True,
    )
    try:
        health = _ledger_health()
    except Exception:
        health = {}
    return jsonify({
        "asOf": _ai_now_iso(), "schemaVersion": C.SCHEMA_VERSION,
        "currentEpoch": {"active": C.ACTIVE_EPOCH,
                         "reliabilityStage": C.reliability_stage(v3days)},
        "v3Headline": overall,
        "v4DryRun": v4 or {"status": "no_v4_summary_yet",
                           "noteJa": "v4ドライランのsummaryは平日のワークフロー実行後に生成されます。"},
        "activeUniverse": {"regimeSensors": len(C.REGIME_SENSORS), "tactical": len(C.TACTICAL_BENCHMARK),
                           "versions": {"universe": C.UNIVERSE_VERSION, "tactical": C.TACTICAL_BENCHMARK_VERSION,
                                        "factorGroup": C.FACTOR_GROUP_VERSION, "cohort": C.COHORT_VERSION,
                                        "schema": C.SCHEMA_VERSION}},
        "coverage": cov,
        "marketClocks": {"clockVersion": argus_market_clock.CLOCK_VERSION,
                         "calendarVersion": argus_market_clock.CALENDAR_VERSION,
                         "jp": argus_market_clock.forecast_clock("7203"),
                         "us": argus_market_clock.forecast_clock("SPY")},
        "expectedVsActual": {"v3Days": v3days, "lastScoringRun": led.get("updated"),
                             "predictionLedgerHealth": health.get("predictionLedger") if isinstance(health, dict) else None},
        "readiness": readiness,
        "activationAllowed": readiness["ready"],
        "pendingJa": ("baseline/skillスコアの永続化はまだ(v4はBrier/RPSのみ保存) / "
                      "per-sensorのローリング被覆率は履歴が必要 / 較正はburn-in中=精度は未証明。"),
        "noteJa": "校正は「ただ待てば良くなる」ものではありません。市場別クロックで正しい日付に、"
                  "被覆率と欠測を記録し、不変の予測を追記できている時だけ改善します。上記が現状の記録健全性です。",
    })


@app.route("/api/argus/calibration/v4/status")
def api_argus_calibration_v4_status():
    """PUBLIC-SAFE Calibration v4 status (ARGUS Pro v11) — auditable and HONESTLY
    INACTIVE. isActive is true ONLY when the v4 artifact exists AND has records; it
    never claims "proven". Reads the public ledger-branch v4 dry-run summary (no
    owner data). reliabilityStage comes from the real trading-day count."""
    C = argus_calibration
    v4 = _calibration_v4_summary()   # ledger-branch calibration_v1/summary.json, or None
    led = _ledger_summary() or {}
    overall = led.get("overall") or {}
    days = int(overall.get("days") or 0)
    artifact = isinstance(v4, dict) and bool(v4)
    # v4 summary field names vary; read defensively and never fabricate.
    def _num(*keys):
        for k in keys:
            v = (v4 or {}).get(k)
            if isinstance(v, (int, float)):
                return int(v)
        return 0
    n_pred = _num("nPredictions", "n", "count", "records")
    n_scored = _num("nScored", "scored", "scoredCount")
    stage = C.reliability_stage(days)
    is_active = bool(artifact and (n_pred > 0 or n_scored > 0))
    if not artifact:
        reason = ("v4ドライランのsummaryはまだ生成されていません（平日のワークフロー実行後に台帳ブランチへ書き込まれます）。"
                  "現時点でクリーンなv4採点はinactiveです。")
    elif n_pred <= 0:
        reason = "v4アーティファクトはありますが記録がまだ0件です。inactive（精度は未実証）。"
    elif stage == "burn_in":
        reason = "記録は開始していますがburn-in段階です（精度は未実証・『実証済み』とは表示しません）。"
    else:
        reason = "v4記録が蓄積中です（それでも分類であり利益保証ではありません）。"
    return jsonify({
        "schemaVersion": C.SCHEMA_VERSION,          # "calibration-v4"
        "engineVersion": C.SCHEMA_VERSION,
        "asOf": _ai_now_iso(),
        "artifactFound": artifact,
        "lastRecordAt": (v4 or {}).get("updated") or (v4 or {}).get("asOf"),
        "lastScoreAt": (v4 or {}).get("lastScoreAt") or (v4 or {}).get("updated"),
        "nPredictions": n_pred,
        "nScored": n_scored,
        "cohortCounts": (v4 or {}).get("cohortCounts") or {},
        "epoch": C.ACTIVE_EPOCH,
        "reliabilityStage": stage,       # burn_in | early_signal | provisional | regime_level
        "isActive": is_active,
        "v3HeadlineDays": days,          # legacy v3 remains as burn-in history, not v4
        "reasonJa": reason,
        "noteJa": "v4はv3ヘッドラインと分離したクリーンepoch。『実証済み』表記はしません。",
    })


@app.route("/api/argus/calibration/posture")
def api_argus_calibration_posture():
    """Calibration Ledger v4 — multidimensional posture (read-only).

    Replaces SPY-only posture grading: computes today's risk-appetite across
    equity/growth/small-cap/credit/duration/volatility/safe-haven/Japan/FX/
    liquidity dimensions from live data. Marked PARTIAL (never SPY-only) when too
    few dimensions are available."""
    P = argus_posture
    rets = {}
    try:
        _alert_etf_momentum()
        _ensure_sensor_etfs()
        for sym in ("SPY", "QQQ", "IWM", "SMH", "XLU", "GLD", "TLT", "HYG", "LQD"):
            st = _ETF_LAST_PRICE.get(sym)
            if st and st.get("m1d") is not None:
                rets[sym] = st["m1d"]
        cw = get_crypto_watchlist_snapshot(["bitcoin"])
        for q in (cw.get("quotes") or []):
            if q.get("id") == "bitcoin" and q.get("changePct") is not None:
                rets["BTC"] = q["changePct"]
        jp = get_japan_watchlist_snapshot(["1306", "1321"])
        for s in (jp.get("stocks") or []):
            if s.get("status") == "live" and s.get("changePct") is not None:
                rets[s["symbol"]] = s["changePct"]
        rates = get_rates_snapshot()
        for key, sym in (("usdJpy", "USDJPY"), ("vix", "VIX")):
            s = rates.get(key) if isinstance(rates, dict) else None
            if s and s.get("status") == "live":
                ch = s.get("change")
                lvl = s.get("latestValue")
                if isinstance(ch, (int, float)) and lvl and (lvl - ch):
                    rets[sym] = round(ch / (lvl - ch) * 100, 2)
    except Exception:
        pass
    outcome = P.posture_outcome(rets)
    return jsonify({
        "postureVersion": P.POSTURE_VERSION,
        "noteJa": "地合いをSPY単独でなく多次元(株式/グロース/小型/クレジット/デュレーション/"
                  "ボラ/安全資産/日本/FX/流動性)で評価。次元が足りなければpartial(SPY単独に落とさない)。",
        "inputsUsed": sorted(rets.keys()),
        "outcome": outcome,
        "dimensionDefinitions": {d: [s for s, _ in b] for d, b in P.DIMENSIONS.items()},
    })


_LAYER2B_STATE = {"lastSyncAt": None, "lastStatus": "never_synced",
                  "lastHash": None, "symbolCount": 0}

def _layer2b_store_configured():
    """Layer 2B persists owner watchlist membership to a PRIVATE GitHub repo (the
    public repo must never see owner symbols). Configured via env; until set,
    scoring stays disabled and nothing is stored."""
    return bool(os.environ.get("ARGUS_LAYER2B_PRIVATE_REPO")
                and os.environ.get("ARGUS_LAYER2B_PRIVATE_TOKEN"))

def _require_owner_sync(body_token=None):
    """(authorized, error, code) — accepts the dedicated OWNER-SYNC token OR the
    admin token, from a header OR the request body (body lets a non-ASCII
    passphrase work — header values must be ASCII). Scoped ONLY to watchlist-sync
    (membership metadata; no portfolio, no other admin action). Never logs it."""
    owner = os.environ.get("ARGUS_OWNER_SYNC_TOKEN", "")
    admin = _ARGUS_ADMIN_TOKEN
    if not owner and not admin:
        return False, {"error": "owner_sync_unconfigured",
                       "message": "ARGUS_OWNER_SYNC_TOKEN is not configured."}, 503
    tok = (request.headers.get("X-ARGUS-OWNER-TOKEN", "")
           or request.headers.get("X-ARGUS-ADMIN-TOKEN", "")
           or (body_token or ""))
    if tok and ((owner and tok == owner) or (admin and tok == admin)):
        return True, None, 200
    return False, {"error": "unauthorized"}, 401

def _gh_private_headers():
    return {"Authorization": f"Bearer {os.environ.get('ARGUS_LAYER2B_PRIVATE_TOKEN','')}",
            "Accept": "application/vnd.github+json", "User-Agent": "argus-layer2b",
            "X-GitHub-Api-Version": "2022-11-28"}

def _gh_private_get(path):
    """GET a file from the private repo. Returns (content_str, sha) or (None, None)."""
    repo = os.environ.get("ARGUS_LAYER2B_PRIVATE_REPO", "")
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    try:
        r = requests.get(url, headers=_gh_private_headers(), timeout=15)
        if r.status_code == 200:
            import base64
            j = r.json()
            return base64.b64decode(j.get("content", "")).decode("utf-8"), j.get("sha")
    except Exception:
        pass
    return None, None

def _gh_private_put(path, content_str, message, overwrite=True):
    """PUT a file to the private repo. If overwrite=False and it exists, skip
    (immutable daily snapshots). Returns True on success."""
    import base64
    repo = os.environ.get("ARGUS_LAYER2B_PRIVATE_REPO", "")
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    _, sha = _gh_private_get(path)
    if sha and not overwrite:
        return True  # immutable: already written, never rewrite
    body = {"message": message,
            "content": base64.b64encode(content_str.encode("utf-8")).decode("ascii")}
    if sha:
        body["sha"] = sha
    try:
        r = requests.put(url, headers=_gh_private_headers(), json=body, timeout=20)
        return r.status_code in (200, 201)
    except Exception:
        return False

def _layer2b_persist_private(snapshot):
    """Write an IMMUTABLE daily membership snapshot to the private repo, plus a
    mutable latest pointer. Raises with the GitHub HTTP status on failure so the
    owner can see WHY (e.g. 404 wrong repo path, 403 token scope)."""
    import json as _json, base64
    repo = os.environ.get("ARGUS_LAYER2B_PRIVATE_REPO", "")
    blob = _json.dumps(snapshot, ensure_ascii=False, indent=2)
    eff = snapshot.get("effectiveFrom", "unknown")
    for path, overwrite in ((f"membership/{eff}.json", False), ("membership/latest.json", True)):
        url = f"https://api.github.com/repos/{repo}/contents/{path}"
        sha = None
        rg = requests.get(url, headers=_gh_private_headers(), timeout=15)
        if rg.status_code == 200:
            sha = rg.json().get("sha")
        elif rg.status_code != 404:
            raise RuntimeError(f"GitHub GET {rg.status_code} ({repo}/{path}): "
                               f"{(rg.json().get('message') if rg.headers.get('content-type','').startswith('application/json') else rg.text)[:90]}")
        if sha and not overwrite:
            continue  # immutable daily snapshot already exists
        b = {"message": f"layer2b {path} {eff}",
             "content": base64.b64encode(blob.encode("utf-8")).decode("ascii")}
        if sha:
            b["sha"] = sha
        rp = requests.put(url, headers=_gh_private_headers(), json=b, timeout=20)
        if rp.status_code not in (200, 201):
            msg = rp.json().get("message", "") if rp.headers.get("content-type", "").startswith("application/json") else rp.text
            raise RuntimeError(f"GitHub PUT {rp.status_code} ({repo}/{path}): {str(msg)[:90]}")

def _layer2b_read_latest():
    """Read the latest membership snapshot from the private repo (owner-gated)."""
    if not _layer2b_store_configured():
        return None
    import json as _json
    content, _ = _gh_private_get("membership/latest.json")
    if not content:
        return None
    try:
        return _json.loads(content)
    except Exception:
        return None


# ── Layer 2B daily record + score (v10.85) ──────────────────────────────────
# Scores the OWNER's watchlist privately, append-only + swap-safe: each day's
# membership is frozen, predictions/scores are never deleted, and changing the
# watchlist only affects FUTURE days. All owner data stays in the private repo.
_L2B_BANDS = {"JP": 2.0, "US": 2.0, "CRYPTO": 3.0}   # ±1σ-ish bands per market
_L2B_CRYPTO_IDS = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana"}


def _layer2b_live_prices(members):
    """Current prices for owner symbols → {symbol: (price, changePct, market)}.

    v10.205 FIX (JP only): the Layer-2B run fires at 16:05 JST (post-TSE-close),
    when JP quotes are the day's CLOSE with status 'delayed' — not 'live'. The old
    'status==live' filter therefore dropped every JP name at run time, so JP was
    never recorded or scored (perpetual 採点待ち). The post-close CLOSE is the correct
    daily anchor, so accept any REAL JP price (live/delayed/close), excluding only
    mock/absent.
    US and crypto stay live-only ON PURPOSE: at 16:05 JST the US market is CLOSED, so
    a 'delayed' US quote is the PRIOR close — a wrong anchor for a prediction stamped
    'today' (and US scoring is held for invalid-clock anyway). Crypto is 24/7, so it
    is genuinely 'live' at this hour. Relaxing them would only record stale anchors."""
    def _real_jp(st):
        return str(st or "") not in ("", "mock", "unavailable")
    out = {}
    jp = [m["symbol"] for m in members if m.get("market") == "JP"]
    us = [m["symbol"] for m in members if m.get("market") == "US"]
    cr = [m["symbol"] for m in members if m.get("market") == "CRYPTO"]
    try:
        if jp:
            for s in (get_japan_watchlist_snapshot(jp).get("stocks") or []):
                if _real_jp(s.get("status")) and s.get("price"):
                    out[s["symbol"]] = (s["price"], s.get("changePct"), "JP")
        if us:
            for s in (get_us_watchlist_snapshot(us).get("stocks") or []):
                if s.get("status") == "live" and s.get("price"):
                    out[s["symbol"]] = (s["price"], s.get("changePct"), "US")
        if cr:
            ids = [_L2B_CRYPTO_IDS[s] for s in cr if s in _L2B_CRYPTO_IDS]
            idmap = {v: k for k, v in _L2B_CRYPTO_IDS.items()}
            if ids:
                for q in (get_crypto_watchlist_snapshot(ids).get("quotes") or []):
                    if q.get("status") == "live" and q.get("priceUsd"):
                        out[idmap.get(q["id"], q["id"])] = (q["priceUsd"], q.get("changePct"), "CRYPTO")
    except Exception:
        pass
    return out


def _layer2b_compute_summary(rows):
    by_h = {"1d": [], "3d": [], "5d": []}
    held = 0  # US/crypto horizons held for invalid clock (not counted in metrics)
    for r in rows:
        sc = r.get("scored") or {}
        for h in by_h:
            x = sc.get(h)
            if isinstance(x, dict) and x.get("argmaxHit") is not None:
                by_h[h].append(x)             # a real numeric score
            elif isinstance(x, dict) and x.get("status") == "experimental_invalid_clock":
                held += 1
    out = {"updated": _ai_now_iso(), "cohortId": "owner_watchlist_dynamic",
           "nPredictions": len(rows),
           "tradingDays": len({r.get("date") for r in rows}),
           "uniqueSymbols": len({r.get("symbol") for r in rows}),
           "heldInvalidClock": held,
           "scoringNoteJa": "現状JP銘柄のみ採点。US/暗号資産は市場別クロック実装まで採点保留。",
           "byHorizon": {}}
    for h, lst in by_h.items():
        if lst:
            hits = sum(1 for x in lst if x.get("argmaxHit"))
            brier = sum(x.get("brierNormalizedMean", 0) for x in lst) / len(lst)
            out["byHorizon"][h] = {"n": len(lst), "hitRate": round(hits / len(lst), 4),
                                   "brierMean": round(brier, 4)}
        else:
            out["byHorizon"][h] = {"n": 0}
    out["sampleStage"] = ("burn_in" if out["tradingDays"] < 30 else
                          "exploratory" if out["tradingDays"] < 60 else
                          "provisional" if out["tradingDays"] < 120 else "validation")
    out["noteJa"] = "所有者ウォッチリストの自己採点(選択バイアスあり・利益保証ではない)。proven表記はしない。"
    return out


def _layer2b_run():
    """Daily: record today's owner predictions + score any due horizons, in the
    PRIVATE repo. Append-only, immutable per date, swap-safe."""
    import json as _json
    if not _layer2b_store_configured():
        return {"ok": False, "error": "private_store_not_configured"}
    mem = _layer2b_read_latest()
    if not mem or not mem.get("members"):
        return {"ok": False, "error": "no_membership_synced"}
    members = [{"symbol": m.get("symbol"), "market": m.get("market")} for m in mem["members"]]
    prices = _layer2b_live_prices(members)
    today = datetime.now(TZ_JST).strftime("%Y-%m-%d")

    content, _ = _gh_private_get("predictions.jsonl")
    rows = []
    if content:
        for ln in content.splitlines():
            ln = ln.strip()
            if ln:
                try:
                    rows.append(_json.loads(ln))
                except Exception:
                    pass

    new_count = 0
    if not any(r.get("date") == today for r in rows):  # immutable: record once/day
        for m in members:
            sym, mkt = m["symbol"], m["market"]
            pc = prices.get(sym)
            if not pc:
                continue
            price, chg, _mk = pc
            clk = argus_market_clock.forecast_clock(sym)
            targets = {t["horizon"]: (t.get("targetTradingDate") or t.get("targetTimestamp"))
                       for t in clk.get("targets", [])}
            rows.append({
                "id": "l2b-" + hashlib.sha256((today + sym).encode("utf-8")).hexdigest()[:10],
                "date": today, "symbol": sym, "market": mkt,
                "cohortId": "owner_watchlist_dynamic",
                "priceAtPrediction": price, "changePct": chg,
                "scenarios": {lab: p for lab, p in _scenarios_for(chg)},
                "bandPct": _L2B_BANDS.get(mkt, 2.0),
                "targets": targets, "calendar": clk.get("marketCalendar"),
                # JP records/scores correctly at the 16:05 JST run (post-close).
                # US/crypto would be scored at the WRONG time here, so they are
                # held until market-specific clocks exist (GPT P0 #4).
                "clockValid": (mkt == "JP"),
                "scored": {"1d": None, "3d": None, "5d": None},
            })
            new_count += 1

    scored_count = 0
    held_count = 0
    for r in rows:
        sc = r.get("scored") or {}
        jp = r.get("market") == "JP"
        for h in ("1d", "3d", "5d"):
            if sc.get(h) is not None:
                continue
            tgt = (r.get("targets") or {}).get(h)
            if not tgt or str(tgt)[:10] > today:
                continue  # not due yet
            if not jp:
                # Scoring US/crypto at 16:05 JST uses a wrong-time price (US is
                # closed, crypto anchor is hour-based). Hold, don't fake a score.
                sc[h] = {"status": "experimental_invalid_clock",
                         "noteJa": "市場別クロック未実装のため採点保留(誤時刻採点の防止)"}
                held_count += 1
                continue
            pc = prices.get(r.get("symbol"))
            if not pc:
                continue
            res = argus_calibration.score_prediction(
                r.get("scenarios") or {}, r.get("priceAtPrediction"), pc[0], r.get("bandPct", 2.0))
            if res:
                res["priceAsOf"] = today
                sc[h] = res
                scored_count += 1
        r["scored"] = sc

    newcontent = "\n".join(_json.dumps(r, ensure_ascii=False) for r in rows) + "\n"
    ok_w = _gh_private_put("predictions.jsonl", newcontent, f"layer2b run {today}", overwrite=True)
    summ = _layer2b_compute_summary(rows)
    _gh_private_put("summary.json", _json.dumps(summ, ensure_ascii=False, indent=2),
                    f"layer2b summary {today}", overwrite=True)
    return {"ok": bool(ok_w), "recorded": new_count, "scored": scored_count,
            "heldInvalidClock": held_count, "totalRows": len(rows),
            "date": today, "summary": summ}


@app.route("/api/argus/calibration/watchlist-sync", methods=["POST"])
def api_argus_watchlist_sync():
    """Layer 2B — sync the OWNER's watchlist MEMBERSHIP for calibration (owner/
    admin only). Accepts metadata only (symbol/market/enabled/timestamps); ANY
    portfolio field is hard-rejected. The repo is public, so nothing is persisted
    unless a PRIVATE store is configured — otherwise scoring stays disabled and no
    symbols are stored anywhere. No orders, ever."""
    body = request.get_json(silent=True) or {}
    token = body.pop("ownerToken", None) if isinstance(body, dict) else None  # strip before validate/store
    ok, err, code = _require_owner_sync(body_token=token)
    if not ok:
        return jsonify(err), code
    # Post-auth work is wrapped so a bug surfaces as a readable error to the
    # AUTHENTICATED owner (safe) instead of a blank HTTP 500. persist_detail
    # captures WHY a private-store write failed (the common real cause).
    persist_detail = None
    try:
        W = argus_watchlist_sync
        valid, cleaned, errs = W.validate_sync_payload(body)
        if not valid:
            return jsonify({"ok": False, "errors": errs,
                            "note": "Research simulation only. Metadata only — no portfolio data accepted."}), 400
        eff = datetime.now(TZ_JST).strftime("%Y-%m-%d")
        gen = _ai_now_iso()
        sid = "wl-" + hashlib.sha256((eff + W.content_hash(cleaned["items"])).encode("utf-8")).hexdigest()[:10]
        snap = W.build_membership_snapshot(cleaned["items"], effective_date=eff,
                                           generated_at=gen, snapshot_id=sid)
        configured = _layer2b_store_configured()
        status = "synced"
        if configured:
            try:
                _layer2b_persist_private(snap)
            except Exception as pe:
                status = "failed"
                persist_detail = f"{type(pe).__name__}: {str(pe)[:140]}"
        else:
            status = "disabled_pending_private_store"
        _LAYER2B_STATE.update({"lastSyncAt": gen, "lastStatus": status,
                               "lastHash": snap["contentHash"], "symbolCount": snap["symbolCount"]})
        return jsonify({
            "ok": True, "status": status, "snapshotId": sid,
            "symbolCount": snap["symbolCount"], "contentHash": snap["contentHash"],
            "effectiveFrom": eff, "privateStoreConfigured": configured,
            "persistDetail": persist_detail,
            "note": ("Stored privately. Research/calibration metadata only — no order, no portfolio data."
                     if status == "synced" else
                     "Private-store write did not complete — see persistDetail."
                     if status == "failed" else
                     "Layer 2B scoring disabled until a private store is configured."),
        })
    except Exception as e:
        return jsonify({"ok": False,
                        "error": f"server_error: {type(e).__name__}: {str(e)[:160]}"}), 500

@app.route("/api/argus/calibration/watchlist-sync-status")
def api_argus_watchlist_sync_status():
    """Non-sensitive sync status (count/hash/status only — no symbols)."""
    return jsonify({**_LAYER2B_STATE,
                    "privateStoreConfigured": _layer2b_store_configured(),
                    "noteJa": "所有者ウォッチリスト(Layer 2B)同期状態。保有情報は一切送受信しない。"
                              "公開リポ対策でprivateストア設定前は採点無効(銘柄は保存しない)。"})

@app.route("/api/argus/calibration/watchlist-membership", methods=["GET", "POST"])
def api_argus_watchlist_membership():
    """Owner-gated read of the latest synced membership from the PRIVATE store
    (reveals symbols → requires the owner-sync token via header or JSON body).
    Used to restore the device watchlist if localStorage was cleared."""
    body = request.get_json(silent=True) or {}
    token = body.get("ownerToken") if isinstance(body, dict) else None
    ok, err, code = _require_owner_sync(body_token=token)
    if not ok:
        return jsonify(err), code
    snap = _layer2b_read_latest()
    if not snap:
        return jsonify({"status": "empty", "privateStoreConfigured": _layer2b_store_configured()})
    # v10.204: enrich each member with a resolved company name so a restore shows
    # 会社名, not just the 4-digit code (old syncs stored symbol-only). JP → J-Quants
    # master; never invent — fall back to the symbol if unresolved.
    try:
        name_map = _symbol_name_map()   # SYMBOL→name from the JP/US watchlists (reliable)
        for m in (snap.get("members") or []):
            if m.get("name") and m["name"] != m.get("symbol"):
                continue
            sym = str(m.get("symbol") or "").upper()
            nm = name_map.get(sym)
            if not nm and str(m.get("market")) == "JP":
                nm = _jq_name_for(sym)   # fall back to the J-Quants master for other JP codes
            if nm and nm != sym:
                m["name"] = nm
    except Exception:
        pass
    return jsonify({"status": "ok", "membership": snap})

@app.route("/api/argus/calibration/layer2b-run", methods=["POST"])
def api_argus_layer2b_run():
    """Admin-triggered daily run: record today's owner predictions + score due
    horizons in the PRIVATE store. Append-only, swap-safe. No orders."""
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    try:
        return jsonify(_layer2b_run())
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {str(e)[:160]}"}), 500

@app.route("/api/argus/calibration/layer2b-summary", methods=["GET", "POST"])
def api_argus_layer2b_summary():
    """Owner-gated read of the Layer 2B self-scoring summary from the PRIVATE
    store (per-horizon hit rate + Brier; sample stage). Reveals nothing public.
    Accepts the owner token via header (GET) or JSON body (POST, any passphrase)."""
    body = request.get_json(silent=True) or {}
    token = body.get("ownerToken") if isinstance(body, dict) else None
    ok, err, code = _require_owner_sync(body_token=token)
    if not ok:
        return jsonify(err), code
    if not _layer2b_store_configured():
        return jsonify({"status": "disabled_pending_private_store"})
    import json as _json
    content, _ = _gh_private_get("summary.json")
    if not content:
        return jsonify({"status": "no_data_yet",
                        "noteJa": "まだ採点データがありません(同期後、毎営業日の記録+1/3/5営業日後の採点で蓄積)。"})
    try:
        return jsonify({"status": "ok", "summary": _json.loads(content)})
    except Exception:
        return jsonify({"status": "parse_error"})


@app.route("/api/argus/calibration/epochs")
def api_argus_calibration_epochs():
    """Calibration epochs — the legacy n≈133 is PRESERVED as an archived burn-in
    epoch (excluded from headline metrics); the clean epoch is pending an
    admin-gated readiness/activation step (Phase 2). Read-only, no owner data."""
    C = argus_calibration
    summ = _ledger_summary() or {}
    ov = summ.get("overall") or {}
    n = ov.get("n")
    updated = summ.get("updated")
    burn_in = C.burn_in_epoch_record((None, updated), n if isinstance(n, int) else 0)
    return jsonify({
        "schemaVersion": C.SCHEMA_VERSION,
        "epochs": [
            burn_in,
            {
                "epochId": C.ACTIVE_EPOCH,
                "status": "pending_readiness",
                "includeInHeadlineMetrics": False,
                "noteJa": "コホート定義の確定+センサー完全記録+採点スキーマ確定の後に、"
                          "管理者が明示的に有効化(自動では始めない)。",
            },
        ],
        "legacyPreserved": True,
        "noteJa": "現n≈133は削除せず burn_in_legacy_v3 として保存。不安定期データなので"
                  "ヘッドライン指標からは除外。",
    })


@app.route("/api/argus/calibration/clock")
def api_argus_calibration_clock():
    """Calibration Ledger v4 (Phase 2) — market-specific forecast clock preview.

    Read-only. Shows, for a symbol (or a representative set across markets), the
    correct origin session + 1D/3D/5D targets on THAT market's calendar (JP/US
    trading-session closes, crypto 24/72/120h, FX NY-close). Demonstrates that
    the legacy 'everything at 16:05 JST' assumption is gone. Wiring into the
    recording workflow is Phase 3 (this endpoint does not record anything)."""
    MC = argus_market_clock
    sym = request.args.get("symbol")
    if sym:
        return jsonify(MC.forecast_clock(sym))
    sample = ["7203", "NVDA", "BTC", "USDJPY", "VIX"]
    return jsonify({
        "clockVersion": MC.CLOCK_VERSION,
        "calendarVersion": MC.CALENDAR_VERSION,
        "noteJa": "各銘柄を「その市場の正しい引け/セッション」で採点する。"
                  "全部16:05 JST固定をやめた(JP=TSE引け / US=NYSE引け[EDT/EST自動] / "
                  "crypto=24/72/120h / FX=NY引け)。記録への接続はPhase 3。",
        "samples": [MC.forecast_clock(s) for s in sample],
    })


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

def _rates_snapshot_base():
    """Combined snapshot of the four watched series + derived signals (FRED daily)."""
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


_YF_RT_CACHE = {"data": None, "expires": 0.0}
_YF_RT_TTL = 90    # ~realtime FX/rates — realtime enough without hammering Yahoo
# snapshot key -> (Yahoo symbol, label). ^TNX = 10Y yield in %, ^VIX = VIX level.
_YF_RT_MAP = {"usdJpy": ("JPY=X", "USD/JPY"),
              "us10y":  ("%5ETNX", "US 10Y Treasury yield"),
              "vix":    ("%5EVIX", "VIX")}


def _yf_quote(sym):
    """One realtime quote from Yahoo Finance chart API (keyless). None on failure."""
    try:
        r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=2d",
                         headers={"User-Agent": "Mozilla/5.0 (compatible; argus-research/1.0)"}, timeout=8)
        if r.status_code != 200:
            return None
        res = (r.json().get("chart") or {}).get("result") or []
        m = (res[0].get("meta") if res else None) or {}
        px = m.get("regularMarketPrice")
        prev = m.get("chartPreviousClose") or m.get("previousClose")
        if px is None:
            return None
        return (float(px), float(prev) if prev is not None else float(px))
    except Exception:
        return None


def _yahoo_rates_rt():
    """Realtime USD/JPY, US 10Y yield and VIX via Yahoo Finance (keyless). 5-min
    cache, best-effort per metric — FRED daily stays the fallback. Fixes the multi-
    day FRED lag (USD/JPY was ~7 days stale) that didn't match a broker's live rate."""
    now = time.time()
    if _YF_RT_CACHE["data"] is not None and now < _YF_RT_CACHE["expires"]:
        return _YF_RT_CACHE["data"]
    today = _ai_now_iso()[:10]
    out = {}
    for key, (sym, label) in _YF_RT_MAP.items():
        q = _yf_quote(sym)
        if not q:
            continue
        px, prev = round(q[0], 2), round(q[1], 2)
        chg = round(px - prev, 2)
        out[key] = {"label": label, "latestValue": px, "previousValue": prev,
                    "change": chg, "changeBp": round(chg * 100, 1),
                    "latestDate": today, "source": "yahoo-rt", "status": "live"}
    if out:
        _YF_RT_CACHE["data"] = out
        _YF_RT_CACHE["expires"] = now + _YF_RT_TTL
    return out


def get_rates_snapshot():
    """Rates snapshot with a REALTIME overlay (Yahoo Finance: USD/JPY, US10Y, VIX) on
    top of the FRED-daily base. Applied on every call (not frozen into the rates cache)
    so the figures track live quotes; any metric Yahoo misses stays FRED-daily and is
    labelled with its real as-of date in the UI."""
    snap = _rates_snapshot_base()
    rt = _yahoo_rates_rt()
    if rt:
        snap = {**snap, **rt}
        u10, vx = snap.get("us10y") or {}, snap.get("vix") or {}
        if u10 and vx:
            snap["summary"] = (f"10Y {u10['latestValue']:.2f}% ({u10['changeBp']:+.0f}bp), "
                               f"VIX {vx['latestValue']:.1f}. Pressure: {snap.get('ratesPressure')}, "
                               f"Vol: {snap.get('riskVolatility')}.")
    return snap


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


_YF_JP_CACHE = {}        # code -> {"row": .., "ts": ..}
_YF_JP_TTL = 600


def _yahoo_jp_row(code, name):
    """Previous-close fallback for a JP name via Yahoo Finance (<code>.T), keyless.
    Used ONLY when J-Quants + the moomoo bridge both lack the symbol, so the card
    shows a REAL (delayed) price instead of MOCK. status='delayed' (never 'live').
    10-min cache; None on failure."""
    now = time.time()
    hit = _YF_JP_CACHE.get(code)
    if hit and now - hit["ts"] <= _YF_JP_TTL:
        return hit["row"]
    row = None
    q = _yf_quote(f"{code}.T")
    if q:
        px, prev = round(q[0], 2), round(q[1], 2)
        chg = round(px - prev, 2)
        pct = round((chg / prev) * 100, 2) if prev else 0.0
        row = {"symbol": code, "name": name, "nameJa": name, "price": px,
               "changeAbs": chg, "changePct": pct, "volume": 0, "date": None,
               "source": "yahoo-delayed", "status": "delayed"}
    _YF_JP_CACHE[code] = {"row": row, "ts": now}
    return row

# JP sector rotation (v10.189): TOPIX-17 NEXT FUNDS sector ETFs, fetched keyless via Yahoo
# (10-min per-code cache), shaped like the US rotationGroups so the UI renders the SAME
# horizontal flow board for Japan instead of a bare text line.
_JP_SECTORS = [
    ("1622", "自動車・輸送機", "リスク"),
    ("1625", "電機・精密",     "グロース"),
    ("1631", "銀行",           "金利敏感"),
    ("1629", "商社・卸売",     "バリュー"),
    ("1626", "情報通信・サービス", "グロース"),
    ("1621", "医薬品",         "ディフェンシブ"),
    ("1627", "電力・ガス",     "ディフェンシブ"),
    ("1633", "不動産",         "金利敏感"),
]

def _jp_sector_rotation():
    """JP sector money-flow per TOPIX-17 ETF (1-day move → score -1..1), same shape as the
    US rotationGroups. Best-effort/keyless; missing sectors come back available=False."""
    flow_ja = {"inflow": "資金流入", "outflow": "資金流出", "neutral": "中立"}
    groups = []
    for code, label, role in _JP_SECTORS:
        try:
            row = _yahoo_jp_row(code, label)
        except Exception:
            row = None
        pct = row.get("changePct") if isinstance(row, dict) else None
        if not isinstance(pct, (int, float)):
            groups.append({"id": f"jp-{code}", "label": label, "role": role, "assets": [f"{code}.T"],
                           "score": 0.0, "status": "neutral", "momentum1d": None, "momentum5d": None,
                           "momentum20d": None, "available": False, "rationaleJa": f"{label}: データ取得待ち。"})
            continue
        score = max(-1.0, min(1.0, pct / 3.0))   # ±3% ≈ full deflection (matches the US meter scale)
        status = "inflow" if score >= 0.2 else ("outflow" if score <= -0.2 else "neutral")
        groups.append({"id": f"jp-{code}", "label": label, "role": role, "assets": [f"{code}.T"],
                       "score": round(score, 3), "status": status, "momentum1d": round(pct, 2),
                       "momentum5d": None, "momentum20d": None, "available": True,
                       "rationaleJa": f"{label}: 本日{pct:+.2f}%（{flow_ja[status]}）。"})
    return groups

# JP-specific role → matrix-coordinate maps (v10.192). Mirrors the US _ROLE_GROWTH/
# _ROLE_RISK but for the TOPIX sector roles, so the JP Matrix uses the SAME geometry
# as the US one (growth↔defensive × risk↔duration).
_JP_ROLE_GROWTH = {"グロース": 0.6, "リスク": 0.4, "金利敏感": 0.0, "バリュー": -0.2, "ディフェンシブ": -0.55}
_JP_ROLE_RISK   = {"リスク": 0.55, "グロース": 0.5, "金利敏感": 0.15, "バリュー": 0.05, "ディフェンシブ": -0.45}

def _jp_regime_matrix(jp_groups):
    """JP Regime Matrix from the TOPIX sector flows — same 2 axes/geometry as the US
    matrix. Current location (blue) = the aggregate of the sector scores by role;
    context dots = each available sector. ETF-flow proxy, not direct capital flow."""
    def _c(v):
        return max(-1.0, min(1.0, v))
    avail = [g for g in (jp_groups or []) if g.get("available")]
    def role_avg(roles):
        vs = [g["score"] for g in avail if g.get("role") in roles]
        return sum(vs) / len(vs) if vs else 0.0
    growth_lead    = role_avg({"グロース", "リスク"})
    defensive_lead = role_avg({"ディフェンシブ"})
    risk_lead      = role_avg({"リスク", "グロース", "金利敏感", "バリュー"})
    duration_lead  = role_avg({"ディフェンシブ", "金利敏感"})
    x = _c(growth_lead - defensive_lead)
    y = _c(risk_lead - duration_lead)
    points = []
    for g in avail:
        px = _c(_JP_ROLE_GROWTH.get(g.get("role"), 0.0) * 0.6 + g["score"] * 0.5)
        py = _c(_JP_ROLE_RISK.get(g.get("role"), 0.0) * 0.6 + g["score"] * 0.5)
        points.append({"label": g["label"], "x": round(px, 2), "y": round(py, 2)})
    n = len(avail)
    ja = (f"日本株{n}セクターの資金フロー(TOPIX-17 ETF)から合成した現在地。"
          f"グロース優位={x:+.2f} / リスク寄り={y:+.2f}。ETFフローのプロキシで直接の資金フローではない。"
          if n else "日本株セクターのデータ取得待ち。")
    return {"x": round(x, 3), "y": round(y, 3),
            "xLabel": "Growth vs Defensive", "yLabel": "Risk vs Duration",
            "points": points, "rationaleJa": ja, "available": n > 0}

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
            # Honesty (v10.156): J-Quants free is lagged. Only call it "live" when
            # the bar is actually today's; otherwise it is delayed (T-1+), so the UI
            # shows 遅延 instead of pretending a yesterday close is a live quote.
            "status": "live" if latest.get("Date") == datetime.now(TZ_JST).strftime("%Y-%m-%d") else "delayed",
            "source": "jquants",
        }
    except Exception:
        return None

def _jquants_fetch_quote(s, headers):
    """Curated-list fetch (moomoo overlays on top later): Yahoo (fresher) → J-Quants
    (T-1) → mock. Order matches the owner spec (v10.157)."""
    return (_yahoo_jp_row(s["symbol"], s["name"])
            or _jq_fetch_bar_row(s["symbol"], s["name"], headers)
            or _jp_mock_quote(s))

def _jp_mock_snapshot():
    return {"status": "mock", "asOf": None,
            "stocks": [_jp_mock_quote(s) for s in _JP_WATCHLIST]}

# Dynamic (user-watchlist) symbol support. The engine list is no longer fixed:
# the frontend passes its actual assets via ?symbols=. Public endpoint →
# sanitize hard, cap the count, and bound the per-set cache.
_JP_SYM_RE      = re.compile(r"^[0-9A-Z]{4}$")   # TSE 4-char codes incl. 285A
_US_SYM_RE      = re.compile(r"^[A-Z][A-Z.\-]{0,9}$")
_JP_DYN_MAX     = 20
# Twelve Data plan-aware caps (v11.1). Basic = free-tier conservatism; Grow raises the
# quota so coverage can widen — but a quota bump NEVER proves L2/tape/options/borrow or
# extended-hours live (those need real feeds + proof). Unknown plan → keep the old caps.
_TWELVEDATA_PLAN = (os.environ.get("TWELVEDATA_PLAN", "") or "").strip().lower()
def _td_int_env(name, default):
    try:
        return max(1, int(os.environ.get(name, "") or default))
    except Exception:
        return default
_TD_GROW = _TWELVEDATA_PLAN in ("grow", "pro", "enterprise", "custom")
_US_DYN_MAX     = _td_int_env("TWELVEDATA_DYNAMIC_MAX", 24 if _TD_GROW else 8)
_TD_VWAP_MAX    = _td_int_env("TWELVEDATA_VWAP_SYMBOL_MAX", 12 if _TD_GROW else 6)
_TD_REGIME_ETF_MAX = _td_int_env("TWELVEDATA_REGIME_ETF_MAX", 16 if _TD_GROW else 8)
_TD_CREDIT_BUDGET_PER_MIN = _td_int_env("TWELVEDATA_CREDIT_BUDGET_PER_MIN", 55 if _TD_GROW else 8)
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
        # J-Quants when configured; otherwise (or per-symbol miss) a keyless Yahoo
        # previous-close fallback so a watched name shows a REAL delayed price, never
        # MOCK. The moomoo bridge overlay (applied after) still overrides with realtime.
        headers = {"x-api-key": _JQUANTS_API_KEY} if _JQUANTS_API_KEY else None
        def fetch(code):
            # Order (owner spec v10.157): moomoo realtime overlays on top later; for a
            # non-moomoo symbol use the FRESHER source first — Yahoo (intraday ~20min /
            # today's close) BEFORE J-Quants (free = T-1 yesterday). J-Quants is the
            # last resort for names Yahoo lacks.
            nm = _jq_name_for(code) or code
            row = _yahoo_jp_row(code, nm)
            if row is None and headers:
                row = _jq_fetch_bar_row(code, nm, headers)
            return row
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(syms))) as ex:
            stocks = [q for q in ex.map(fetch, syms) if q is not None]
        # v10.191: coverage-based status instead of all-or-nothing. A few names on
        # delayed/close data (e.g. 6146/6758 not in the moomoo bridge push set) no
        # longer drag the WHOLE watchlist to a scary "partial" — that state is now
        # reserved for genuinely INCOMPLETE data (mock/missing mixed in). "mixed" =
        # mostly-live + a few delayed (fine); "delayed" = all real but off-hours/T-1.
        live_n    = sum(1 for q in stocks if q.get("status") == "live")
        delayed_n = sum(1 for q in stocks if q.get("status") == "delayed")
        mock_n    = sum(1 for q in stocks if q.get("status") == "mock")
        total     = len(syms)
        if not stocks:
            overall = "mock"
        elif live_n == total:
            overall = "live"
        elif mock_n == 0 and live_n == 0:
            overall = "delayed"      # every name real, just delayed/close (not broken)
        elif mock_n == 0:
            overall = "mixed"        # mostly live + a few delayed (not broken)
        else:
            overall = "partial"      # genuinely incomplete — mock/missing present
        as_of   = max((q["date"] for q in stocks if q.get("date")), default=None)
        snapshot = {"status": overall, "asOf": as_of, "stocks": stocks,
                    "coverage": {"live": live_n, "delayed": delayed_n, "mock": mock_n, "total": total},
                    "liveSymbols": [q.get("symbol") for q in stocks if q.get("status") == "live"],
                    "delayedSymbols": [q.get("symbol") for q in stocks if q.get("status") == "delayed"]}
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
    # Remember the requested symbols HERE (not just in the HTTP route) so BOTH the
    # watchlist page AND the Today page (which reaches this via get_action_labels)
    # teach the bridge the owner's watchlist → /jp-watchlist-codes → realtime push.
    if symbols and requested:
        _remember_jp_symbols(requested)
    return _overlay_pushed(snap, "JP", requested)

@app.route("/api/argus/japan-watchlist")
def api_argus_japan_watchlist():
    raw = (request.args.get("symbols") or "")
    symbols = [s for s in raw.split(",") if s.strip()] or None
    return jsonify(get_japan_watchlist_snapshot(symbols))


# Watchlist symbols the frontend has actually requested — so the moomoo bridge can
# push REALTIME for them (not just the hardcoded CODES). The frontend's watchlist is
# client-side; this is how the server-side bridge learns about a newly-added name.
_JP_SEEN_SYMBOLS = {}      # symbol(upper) -> last_seen_epoch
_JP_SEEN_MAX = 200
_JP_SEEN_TTL = 7 * 24 * 3600   # forget a symbol unseen for a week


def _remember_jp_symbols(symbols):
    now = time.time()
    for s in symbols:
        c = str(s).strip().upper()
        if c:
            _JP_SEEN_SYMBOLS[c] = now
    # prune stale + cap
    for k in [k for k, ts in _JP_SEEN_SYMBOLS.items() if now - ts > _JP_SEEN_TTL]:
        _JP_SEEN_SYMBOLS.pop(k, None)
    if len(_JP_SEEN_SYMBOLS) > _JP_SEEN_MAX:
        for k in sorted(_JP_SEEN_SYMBOLS, key=_JP_SEEN_SYMBOLS.get)[:-_JP_SEEN_MAX]:
            _JP_SEEN_SYMBOLS.pop(k, None)


def _recent_jp_watchlist_codes():
    """Recently-requested JP watchlist symbols as moomoo codes (for the bridge)."""
    return ["JP." + s for s in sorted(_JP_SEEN_SYMBOLS)]


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
    requested = (_sanitize_symbols(symbols, _US_SYM_RE, _US_DYN_MAX) if symbols
                 else [s["symbol"] for s in _US_WATCHLIST])
    # Bridge-first (v10.61): the /us-watchlist poll runs every ~15s. Calling Twelve
    # Data on EVERY poll burned 28× the free daily quota (22k/800). When the moomoo
    # bridge has FRESH quotes for every requested symbol, serve those and SKIP the
    # Twelve Data fetch entirely — Twelve Data is only needed as the off-bridge
    # fallback + for the regime ETFs.
    now = time.time()
    bridge = {sym for sym, p in (_PUSHED_QUOTES.get("US") or {}).items()
              if now - p.get("ts", 0) <= _PUSH_TTL}
    if requested and all(s in bridge for s in requested):
        base = {"status": "live", "asOf": _ai_now_iso(), "provider": "moomoo-bridge", "stocks": []}
        return _overlay_pushed(base, "US", requested)
    snap = _get_us_watchlist_core(symbols)
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

# Rolling short-window history per symbol (v10.49) — feeds detect_acceleration,
# the EARLY-warning layer that catches a move BEFORE the day-change thresholds.
# ~40 samples × 15s ≈ 10 min of memory; per-process (rebuilds after a restart).
_PUSH_HISTORY = {"JP": {}, "US": {}}    # market -> {symbol: deque[{ts,price,flowRatio,volRatio}]}
_PUSH_HIST_MAX = 40

# ── EC2→Render ingress HMAC anti-replay (v10.44) ─────────────────────────────
# Additive defence on top of the admin token: the bridge signs each push with
# HMAC-SHA256 over "<ts>.<nonce>.<rawbody>" using a shared secret, so a captured
# admin token alone can't replay or forge a push. BACKWARD-COMPATIBLE: with no
# secret set it's a no-op (current behaviour). With a secret set but
# ARGUS_BRIDGE_HMAC_REQUIRED unset, signed requests are verified and unsigned
# ones are still allowed (migration window). Flip REQUIRED once the bridge signs.
_BRIDGE_HMAC_SECRET   = os.environ.get("ARGUS_BRIDGE_HMAC_SECRET", "")
_BRIDGE_HMAC_REQUIRED = os.environ.get("ARGUS_BRIDGE_HMAC_REQUIRED", "0") not in ("0", "false", "")
_BRIDGE_HMAC_WINDOW   = 300             # seconds: reject stale/future timestamps
_BRIDGE_NONCES        = deque()         # (nonce, epoch) within the window
_BRIDGE_NONCE_SET     = set()

def _hmac_ok(secret, ts, nonce, sig, raw_body, now, window=300):
    """Pure (unit-tested): verify timestamp freshness + HMAC signature. Nonce
    replay is checked statefully by the caller. Returns (ok, reason)."""
    if not (ts and nonce and sig):
        return False, "missing_signature"
    try:
        tsf = float(ts)
    except (TypeError, ValueError):
        return False, "bad_timestamp"
    if abs(now - tsf) > window:
        return False, "stale_timestamp"
    expected = hmac.new(secret.encode("utf-8"),
                        f"{ts}.{nonce}.".encode("utf-8") + raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, str(sig)):
        return False, "bad_signature"
    return True, "ok"

def _verify_bridge_signature(raw_body):
    """(ok, reason) for the current request's bridge signature. No-op when no
    secret is configured; replay-checks the nonce when verifying."""
    if not _BRIDGE_HMAC_SECRET:
        return True, "hmac_disabled"
    ts = request.headers.get("X-ARGUS-TIMESTAMP", "")
    nonce = request.headers.get("X-ARGUS-NONCE", "")
    sig = request.headers.get("X-ARGUS-SIGNATURE", "")
    if not (ts and nonce and sig):
        return (False, "missing_signature") if _BRIDGE_HMAC_REQUIRED else (True, "unsigned_allowed")
    ok, reason = _hmac_ok(_BRIDGE_HMAC_SECRET, ts, nonce, sig, raw_body, time.time(), _BRIDGE_HMAC_WINDOW)
    if not ok:
        return False, reason
    now = time.time()
    while _BRIDGE_NONCES and _BRIDGE_NONCES[0][1] < now - _BRIDGE_HMAC_WINDOW:
        old, _ = _BRIDGE_NONCES.popleft()
        _BRIDGE_NONCE_SET.discard(old)
    if nonce in _BRIDGE_NONCE_SET:
        return False, "replay"
    _BRIDGE_NONCES.append((nonce, now))
    _BRIDGE_NONCE_SET.add(nonce)
    return True, "verified"

def _jp_market_open(now_jst=None):
    """Pure (unit-tested): is the TSE cash session open right now? Weekday and
    09:00–11:30 or 12:30–15:30 JST. Used to stop labelling weekend/after-hours
    bridge pushes as 'live' — the bridge pushes 24/7 but a Saturday price is the
    Friday close, not a real-time quote (user caught this 2026-06-20)."""
    n = now_jst or datetime.now(TZ_JST)
    if n.weekday() >= 5:           # Sat/Sun
        return False
    hm = n.hour * 60 + n.minute
    return (9 * 60 <= hm <= 11 * 60 + 30) or (12 * 60 + 30 <= hm <= 15 * 60 + 30)

def _overlay_pushed(snapshot, market, requested):
    """Copy of a watchlist snapshot with fresh pushed quotes overlaid (and
    holes filled for requested symbols the provider missed). Cache-safe —
    never mutates the cached object. No fresh pushes → snapshot unchanged."""
    try:
        if not isinstance(snapshot, dict):
            return snapshot
        now = time.time()
        fresh = {sym: p for sym, p in (_PUSHED_QUOTES.get(market) or {}).items()
                 if now - p["ts"] <= _PUSH_TTL}
        if not fresh:
            return snapshot
        # Honesty: outside the JP cash session a pushed quote is the last close,
        # NOT a live price — label it 'delayed' so the UI never claims "live"
        # on a Saturday (user caught this 2026-06-20). US session check is
        # left to the provider for now.
        jp_closed = (market == "JP" and not _jp_market_open())
        session = "closed" if jp_closed else ("open" if market == "JP" else "unknown")
        def _stamp(p):
            # v10.36 (#3): per-quote freshness so the UI/inference can be honest.
            # ageSec = how long since the bridge pushed; entitlement carried from
            # the bridge (default unknown). A quote can be pushed every 15s yet
            # still be 15-min DELAYED at source — these are different facts.
            row = p["row"]
            age = int(now - p["ts"])
            stamped = {**row, "ageSec": age, "session": session,
                       "entitlement": row.get("entitlement", "unknown")}
            if jp_closed:
                stamped["status"] = "delayed"
            return stamped
        stocks, seen, overlaid = [], set(), 0
        for q in snapshot.get("stocks", []):
            sym = q.get("symbol")
            seen.add(sym)
            if sym in fresh:
                stocks.append({**q, **_stamp(fresh[sym])})
                overlaid += 1
            else:
                stocks.append(q)
        for sym in requested or []:
            if sym in fresh and sym not in seen:
                name = (_jq_name_for(sym) or sym) if market == "JP" else sym
                stocks.append({**_stamp(fresh[sym]), "name": name, "nameJa": name})
                overlaid += 1
        if overlaid == 0:
            return snapshot
        ages = [now - p["ts"] for p in fresh.values()]
        ents = {p["row"].get("entitlement", "unknown") for p in fresh.values()}
        ent = (ents.pop() if len(ents) == 1 else "mixed")
        note = ("moomooブリッジは約15秒毎に更新。entitlement=unknownの間は、配信が速くても"
                "元データがリアルタイムか15分遅延か未確認のため『リアルタイム』と断定しません。")
        # v10.114: the daily all-market cap-test PROVED realtime (traded-control
        # set) — upgrade 'unknown' to 'realtime' for JP while that proof is fresh
        # (<20h, i.e. today's run). Never override a bridge-reported 'delayed'.
        if market == "JP" and ent == "unknown":
            _proof = _MOOMOO_ALLMARKET_REPORT.get("realtimeProof") or {}
            if _proof.get("at") and (now - _proof["at"]) < 20 * 3600:
                ent = "realtime"
                note = (f"全市場cap-testで売買銘柄の鮮度 p95={_proof.get('p95', '?')}s "
                        f"(traded={_proof.get('traded', '?')}銘柄)→リアルタイムと実証(realtime_evidence)。"
                        "約定の薄い銘柄や昼休み前後は更新が遅く出ることがあります。")
        out = {**snapshot, "stocks": stocks, "realtimeCount": overlaid,
               "marketOpen": (None if market != "JP" else _jp_market_open()),
               "quoteFreshness": {
                   "session": session,
                   "newestAgeSec": int(min(ages)) if ages else None,
                   "oldestAgeSec": int(max(ages)) if ages else None,
                   "entitlement": ent,
                   "noteJa": note}}
        if out.get("status") == "mock":
            out["status"] = "partial"   # real pushed data beats an all-mock claim
        if jp_closed and out.get("status") == "live":
            out["status"] = "partial"   # session closed → not a fully-live snapshot
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
    raw = request.get_data() or b""               # raw bytes for signature verify
    sig_ok, sig_reason = _verify_bridge_signature(raw)
    if not sig_ok:
        send_security_alert({"type": "bridge_signature_rejected", "reason": sig_reason,
                             "meta": _client_meta()})
        return jsonify({"error": "signature_invalid", "reason": sig_reason}), 401
    body = request.get_json(silent=True) or {}
    stocks = body.get("stocks")
    if not isinstance(stocks, list):
        return jsonify({"error": "bad_payload", "message": "expected {stocks: [...]}"}), 400
    now, accepted = time.time(), 0
    _pushed_now = {}   # market -> [rows pushed this request] (for event detection)
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
            # entitlement (v10.36, #3): the bridge MAY report whether the moomoo
            # account data is realtime or 15-min delayed. Until it does, we say
            # "unknown" and the UI must NOT claim realtime. exchangeTs (epoch s
            # or ISO) is the venue's own timestamp when the bridge can supply it.
            ent = str(s.get("entitlement") or "unknown").lower()
            if ent not in ("realtime", "delayed", "unknown"):
                ent = "unknown"
            row = {"symbol": sym,
                   "price": round(price, 4),
                   "changeAbs": round(float(s.get("changeAbs") or 0.0), 4),
                   "changePct": round(float(s.get("changePct") or 0.0), 4),
                   "volume": int(float(s.get("volume") or 0)),
                   "date": datetime.now(TZ_JST).strftime("%Y-%m-%d"),
                   "status": "live", "source": "moomoo-rt",
                   "entitlement": ent, "exchangeTs": s.get("exchangeTs")}
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
            hist = _PUSH_HISTORY[market].get(sym)
            if hist is None:
                hist = _PUSH_HISTORY[market][sym] = deque(maxlen=_PUSH_HIST_MAX)
            hist.append({"ts": now, "price": row["price"],
                         "volume": row.get("volume"),   # cumulative — VWAP needs Δvolume (v11.3.4)
                         "flowRatio": (row.get("flow") or {}).get("bigNetRatio")})
            _pushed_now.setdefault(market, []).append(row)
            accepted += 1
        except Exception:
            continue
    # 24/7 event backbone (v10.39): run deterministic Gear-0/1 anomaly detection
    # on the just-pushed quotes (S高/急変/フロー異常). Cheap, no LLM, gated to
    # real sessions — the existing bridge feeds this, so it works without any
    # EC2 change. Never raises into the push response.
    try:
        for mkt, rows in _pushed_now.items():
            _process_events_from_push(mkt, rows)
    except Exception:
        pass
    return jsonify({"accepted": accepted, "asOf": _ai_now_iso(),
                    "held": {m: len(v) for m, v in _PUSHED_QUOTES.items()}})


# ━━━ 24/7 Gear-Shift Event Backbone (event-v1, v10.39) — Lean ━━━━━━━━━━━━━━━
# Phase 2: deterministic Gear-0/1 detection on the bridge's existing 24/7 quote
# pushes → in-memory event store with dedup + lifecycle → ntfy on meaningful new
# events. NO LLM, NO new AWS infra. Gear 2/3 (AI deep scan) are feature-flagged
# OFF until explicitly enabled. The whole subsystem is flag-guarded and wrapped
# so a failure never touches the existing live endpoints.
def _ev_int(name, default):
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default
_EVENT_BACKBONE_ENABLED = os.environ.get("EVENT_BACKBONE_ENABLED", "1") not in ("0", "false", "")
_EVENT_GEAR2_ENABLED    = os.environ.get("EVENT_GEAR2_ENABLED", "0") not in ("0", "false", "")
# v10.42: restore active events from the ledger branch on boot (raw read — no
# secret). The snapshot is written by the event-ledger workflow. Best-effort
# durability (snapshot granularity); the event HISTORY on the branch is durable.
_EVENT_PERSISTENCE_ENABLED = os.environ.get("EVENT_PERSISTENCE_ENABLED", "1") not in ("0", "false", "")
_EVENTS_RESTORED = {"done": False}
_EVENT_NTFY_MIN_SEV     = _ev_int("EVENT_NTFY_MIN_SEVERITY", 4)   # push only sev>=4
_EVENT_TTL_SEC          = _ev_int("EVENT_TTL_HOURS", 8) * 3600
_EVENTS_ACTIVE = {}                 # dedupKey -> latest envelope revision
_EVENTS_LOG    = deque(maxlen=200)  # recent events (history)
_EVENT_LOCK    = threading.Lock()
_EVENT_STATE   = {"lastDetectionAt": None, "lastEventAt": None, "detections": 0}

# ── TDnet decision metrics (v10.50, GPT item G) ──────────────────────────────
# Objective evidence for/against buying the J-Quants TDnet add-on, measured WITHOUT
# any TDnet data: for each JP high/critical event, was the official catalyst known
# (via EDINET) at/after detection, or did we fall back to secondary news / nothing?
# Upserted by the dossier builder; a protected weekly summary aggregates it.
_TDNET_METRICS = {}                 # eventId -> metric row (upsert)
_TDNET_METRICS_LOCK = threading.Lock()
_TDNET_METRIC_TTL_DAYS = 14

def _parse_iso_z(s):
    try:
        return datetime.strptime(str(s), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.utc)
    except Exception:
        return None

def _record_tdnet_metric(env, official_known, news_used):
    """Upsert a TDnet decision-metric row for a JP high/critical (sev≥4) event.
    Pure bookkeeping — never fabricates TDnet data, never raises into the caller."""
    try:
        if env.get("market") != "JP" or (env.get("severity") or 0) < 4:
            return
        eid = env.get("eventId")
        if not eid:
            return
        now = datetime.now(pytz.utc)
        now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        with _TDNET_METRICS_LOCK:
            row = _TDNET_METRICS.get(eid)
            if row is None:
                row = {"eventId": eid, "symbol": env.get("symbol"), "severity": env.get("severity"),
                       "eventType": env.get("eventType"), "firstSeenAt": now_iso,
                       "officialCatalystKnown": False, "causeSource": "unknown",
                       "secondaryNewsUsedBeforeOfficialSource": False,
                       "timeToOfficialCauseMinutes": None, "resolvedAt": None}
                _TDNET_METRICS[eid] = row
            if official_known and not row["officialCatalystKnown"]:
                row["officialCatalystKnown"] = True
                row["causeSource"] = "edinet_official"
                row["resolvedAt"] = now_iso
                fs = _parse_iso_z(row["firstSeenAt"])
                row["timeToOfficialCauseMinutes"] = max(0, int((now - fs).total_seconds() // 60)) if fs else None
            elif not row["officialCatalystKnown"] and news_used:
                row["secondaryNewsUsedBeforeOfficialSource"] = True
                row["causeSource"] = "secondary_news"
            # age-out old rows
            cutoff = now - timedelta(days=_TDNET_METRIC_TTL_DAYS)
            for k in [k for k, v in _TDNET_METRICS.items()
                      if (_parse_iso_z(v.get("firstSeenAt")) or now) < cutoff]:
                _TDNET_METRICS.pop(k, None)
    except Exception:
        pass

def _tdnet_metrics_summary(days=7):
    """Protected weekly summary: how often the official catalyst was unknown for
    JP high/critical events (the TDnet purchase case). No TDnet data involved."""
    now = datetime.now(pytz.utc)
    cutoff = now - timedelta(days=days)
    with _TDNET_METRICS_LOCK:
        rows = [dict(v) for v in _TDNET_METRICS.values()
                if (_parse_iso_z(v.get("firstSeenAt")) or cutoff) >= cutoff]
    n = len(rows)
    known = [r for r in rows if r["officialCatalystKnown"]]
    unknown = [r for r in rows if not r["officialCatalystKnown"]]
    times = sorted(r["timeToOfficialCauseMinutes"] for r in known
                   if isinstance(r["timeToOfficialCauseMinutes"], int))
    def _median(xs):
        if not xs:
            return None
        m = len(xs) // 2
        return xs[m] if len(xs) % 2 else round((xs[m - 1] + xs[m]) / 2.0, 1)
    unresolved15 = sum(1 for r in unknown
                       if (_parse_iso_z(r.get("firstSeenAt")) and
                           (now - _parse_iso_z(r["firstSeenAt"])).total_seconds() > 15 * 60))
    return {
        "asOf": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "windowDays": days,
        "jpHighCriticalEvents": n,
        "officialCatalystKnown": len(known), "officialCatalystUnknown": len(unknown),
        "pctUnknownOfficialCatalyst": round(100.0 * len(unknown) / n, 1) if n else None,
        "meanTimeToOfficialMinutes": round(sum(times) / len(times), 1) if times else None,
        "medianTimeToOfficialMinutes": _median(times),
        "unresolvedAfter15Minutes": unresolved15,
        "tdnetWouldLikelyHelp": len(unknown),
        "rows": rows[:50],
        "noteJa": "JPの高/重大イベントで公式原因(EDINET)が当日判明したかの実測。TDnet未契約・TDnetデータ不使用。"
                  "unknownや未解決が多いほどTDnet適時開示の価値が高い(購入判断は実測の蓄積後に)。",
    }
_EVENT_POSTURE = {
    "LIMIT_UP": "LIMIT_UP_RISK", "LIMIT_DOWN": "LIMIT_DOWN_RISK",
    "LIMIT_UP_PROXIMITY": "LIMIT_UP_RISK", "LIMIT_DOWN_PROXIMITY": "LIMIT_DOWN_RISK",
    "CRYPTO_SHOCK": "INVESTIGATE", "PRICE_SPIKE": "AVOID_CHASING",
    "PRICE_CRASH": "INVESTIGATE", "VOLUME_ANOMALY": "WATCH", "FLOW_ANOMALY": "WATCH",
    "MOMENTUM_ACCELERATION": "AVOID_CHASING", "FLOW_REVERSAL": "INVESTIGATE",
    "VOLUME_ACCELERATION": "WATCH", "MARKET_MOVER": "INVESTIGATE",
}

def _us_market_open(now_et=None):
    n = now_et or datetime.now(TZ_ET)
    if n.weekday() >= 5:
        return False
    hm = n.hour * 60 + n.minute
    return 9 * 60 + 30 <= hm <= 16 * 60

def _mover_push_allowed(market):
    """Whether a whole-market MARKET_MOVER for `market` is worth pushing right now.
    Only while that market is actually trading — the JP full-market feed is EOD-only,
    so a post-close push is stale noise (v10.133). Crypto/unknown = 24h → always."""
    if market == "JP":
        return _jp_market_open()
    if market == "US":
        return _us_market_open()
    return True

def _event_ntfy(env):
    """Push an event to the user's phone (ntfy). Topic from env only — never in
    code/logs. Title ASCII (header limit); Japanese reason in the UTF-8 body."""
    topic = os.environ.get("NTFY_TOPIC", "")
    if not topic:
        return
    sev = env.get("severity", 1)
    # Downside incidents get the upgraded, actionable message (cause + override +
    # next condition) instead of a bare "急落しています" (v10.98).
    inc = env.get("downsideIncident")
    if inc:
        pct = inc.get("changePct")
        pct_s = f"{pct:+.1f}%" if isinstance(pct, (int, float)) else ""
        title = f"ARGUS: {inc.get('symbol')} {inc.get('actionOverride')} {pct_s}".strip()
        note = argus_downside.build_notification(inc)
        body = (f"{note['title']}\n{note['message']}\n"
                f"{env.get('market')} / sev{sev} / {inc.get('incidentType')}")
        try:
            requests.post(f"https://ntfy.sh/{topic}", data=body.encode("utf-8"),
                          headers={"Title": title,
                                   "Tags": "rotating_light" if sev >= 5 else "warning",
                                   "Priority": "urgent" if sev >= 5 else "high"}, timeout=10)
        except Exception:
            pass
        return
    title = f"ARGUS: {env.get('symbol')} {env.get('eventType')}"
    # Company name goes in the UTF-8 body (the Title header must stay ASCII).
    nm = env.get("nameJa")
    head = f"{nm}({env.get('symbol')})" if nm else f"{env.get('symbol')}"
    # Show the DATA's own time when the source provides it (v10.143), so a mover
    # alert states WHEN the move was — never implying the push time is the move time.
    _asof = f"\nデータ時刻 {env.get('dataAsOf')}" if env.get("dataAsOf") else ""
    body = (f"{head}\n{env.get('reasonJa') or ''}\n"
            f"{env.get('market')} / {env.get('session')} / sev{sev} / {env.get('recommendedPosture')}{_asof}")
    try:
        requests.post(f"https://ntfy.sh/{topic}", data=body.encode("utf-8"),
                      headers={"Title": title, "Tags": "rotating_light" if sev >= 5 else "warning",
                               "Priority": "urgent" if sev >= 5 else "high"}, timeout=10)
    except Exception:
        pass

_DOWNSIDE_EVENT_TYPES = {"PRICE_CRASH", "LIMIT_DOWN_PROXIMITY", "MOMENTUM_ACCELERATION", "FLOW_REVERSAL"}


def _record_event(market, symbol, trig, now, session, bucket_minutes=30,
                  source="moomoo-bridge", session_override=None, quote=None,
                  suppress_notify=False):
    """Dedup + lifecycle + notify for one deterministic trigger. Lean: Gear 0/1
    only, so severity decides the state directly (no AI queue unless enabled).
    bucket_minutes widens the dedup window (crypto uses 360 so a sustained 24h
    shock doesn't re-alert every poll)."""
    key = argus_events.dedup_key(market, symbol, trig["type"], bucket_minutes=bucket_minutes,
                                 now=now.astimezone(TZ_JST))
    notify = False
    with _EVENT_LOCK:
        prev = _EVENTS_ACTIVE.get(key)
        if prev and prev.get("severity", 0) >= trig["severity"]:
            return                              # already have it at >= severity
        env = argus_events.make_envelope(
            event_type=trig["type"], symbol=symbol, market=market,
            source=source, trigger=trig, now=now,
            recommended_posture=_EVENT_POSTURE.get(trig["type"], "WATCH"), gear=1)
        if session_override:
            env["session"] = session_override
        # Always carry the JP company name (never a guessed mapping — resolved from
        # the J-Quants master) so no screen/notification shows a bare 4-digit code.
        if market == "JP":
            nm = _jq_name_for(symbol)
            if nm:
                env["nameJa"] = nm
        env["ingestAt"] = now.astimezone(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        env["lifecycleState"] = ("HIGH_ALERT" if trig["severity"] >= 5
                                 else "VERIFIED" if trig["severity"] >= 4 else "OBSERVING")
        env["expiresAt"] = (now + timedelta(seconds=_EVENT_TTL_SEC)).astimezone(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        # Downside enrichment (v10.98): for a downward move, classify the incident
        # so the notification carries cause + action override + next condition
        # instead of a generic "急落". Pure + cheap; owner/regime read from caches.
        if quote and trig.get("type") in _DOWNSIDE_EVENT_TYPES:
            _chg = quote.get("changePct")
            if isinstance(_chg, (int, float)) and _chg < 0:
                try:
                    _owner = _owner_symbols_cached()
                    _of = _owner.get(str(symbol).upper()) or {}
                    _reg = _REGIME_CACHE.get("data") or {}
                    _nm = env.get("nameJa") or symbol
                    _inc = argus_downside.classify_incident(
                        {"symbol": symbol, "market": market, "name": _nm, "assetName": _nm,
                         "changePct": _chg, "flowRatio": quote.get("flowRatio"),
                         "beta": "high" if str(symbol) in _DOWNSIDE_HIGH_BETA else None,
                         "isHeld": _of.get("ownerState") in ("held", "protected"),
                         "ownerState": _of.get("ownerState"),
                         "downsideStrictness": _of.get("downsideStrictness", "normal"),
                         "priority": _of.get("priority", "normal"),
                         "newsChecked": False, "tdnetConnected": False, "currentAction": "HOLD"},
                        {"globalRegime": (_reg.get("regime") or {}).get("label") or "UNKNOWN"},
                        now_iso=env.get("ingestAt"))
                    if _inc:
                        env["downsideIncident"] = _inc
                except Exception:
                    pass
        _EVENTS_ACTIVE[key] = env
        _EVENTS_LOG.appendleft(env)
        _EVENT_STATE["lastEventAt"] = env["ingestAt"]
        do_notify, _why = argus_events.should_notify(prev, env)
        notify = do_notify and env["severity"] >= _EVENT_NTFY_MIN_SEV
        # v10.133: a whole-market MARKET_MOVER is only actionable while that market
        # is trading. The JP full-market feed is EOD-only, so a post-close scan was
        # pushing the day's moves hours late (e.g. 19:30 JST = useless). Record it
        # (API/ledger still get it) but suppress the push outside the market session.
        if notify and env.get("eventType") == "MARKET_MOVER" and not _mover_push_allowed(env.get("market")):
            notify = False
        if suppress_notify:
            notify = False                       # caller knows the data is stale/non-actionable
        out = env
    if notify:
        _event_ntfy(out)
    return out                                   # newly-stored env (for dossier build)

def _process_events_from_push(market, rows):
    """Run Gear-0 detection on the just-pushed quotes. Gated to real sessions so
    a 24/7 bridge push of a stale weekend/after-hours price never fires."""
    if not _EVENT_BACKBONE_ENABLED or not rows:
        return
    if market == "JP" and not _jp_market_open():
        return
    if market == "US" and not _us_market_open():
        return
    now = datetime.now(pytz.utc)
    session = argus_events.session_label(now.astimezone(TZ_JST))
    _EVENT_STATE["lastDetectionAt"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    _EVENT_STATE["detections"] += 1
    for r in rows:
        try:
            price = r.get("price")
            chg_abs = r.get("changeAbs")
            prev_close = (price - chg_abs) if (price and isinstance(chg_abs, (int, float))) else None
            flow = (r.get("flow") or {}).get("bigNetRatio")
            quote = {"market": market, "symbol": r.get("symbol"), "price": price,
                     "changePct": r.get("changePct"), "flowRatio": flow}
            triggers = list(argus_events.detect_anomalies(quote, session, prev_close=prev_close))
            # Rolling short-window EARLY-warning layer (v10.49): momentum/flow
            # acceleration from the per-symbol history. Tighter dedup bucket so a
            # building move can re-warn without spamming. Reuses the same record/
            # notify/dossier path. Suppressed if the full anomaly already fired this
            # symbol (no point double-alerting once the day-change threshold is hit).
            accel = argus_events.detect_acceleration(
                list(_PUSH_HISTORY[market].get(r["symbol"]) or []), session, now=now)
            for trig in triggers:
                env = _record_event(market, r["symbol"], trig, now, session, quote=quote)
                # Build the EVENT-TIME dossier snapshot for significant events, off
                # the hot path / outside the lock — so the public GET only reads it.
                if env and env.get("severity", 0) >= 4 and "dossier" not in env:
                    try:
                        env["dossier"] = _build_event_dossier(env, r)
                    except Exception:
                        pass
            if not triggers:
                for trig in accel:
                    env = _record_event(market, r["symbol"], trig, now, session, bucket_minutes=15, quote=quote)
                    if env and env.get("severity", 0) >= 4 and "dossier" not in env:
                        try:
                            env["dossier"] = _build_event_dossier(env, r)
                        except Exception:
                            pass
        except Exception:
            continue

def _events_active_list():
    now = time.time()
    with _EVENT_LOCK:
        out = []
        for e in _EVENTS_ACTIVE.values():
            exp = e.get("expiresAt")
            try:
                if exp and datetime.strptime(exp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.utc).timestamp() < now:
                    continue
            except Exception:
                pass
            out.append(e)
    return sorted(out, key=lambda e: (-(e.get("severity") or 0), -argus_events.priority_score(e)))

def _parse_iso_epoch(iso):
    try:
        return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.utc).timestamp()
    except Exception:
        return None

def _events_restore_once():
    """Restore active events + history from the ledger branch snapshot on first
    access after a (re)start. Raw read, no secret; never raises. v10.42."""
    if _EVENTS_RESTORED["done"] or not _EVENT_PERSISTENCE_ENABLED:
        return
    _EVENTS_RESTORED["done"] = True
    try:
        r = requests.get(f"{_LEDGER_RAW_BASE}/events/snapshot.json?cb={int(time.time())}", timeout=6)
        if r.status_code != 200:
            return
        active, log = argus_event_store.restore_state(
            r.json(), time.time(), _parse_iso_epoch, lambda e: e.get("deduplicationKey"))
        with _EVENT_LOCK:
            for k, v in active.items():
                if k and k not in _EVENTS_ACTIVE:
                    _EVENTS_ACTIVE[k] = v
            for e in reversed(log):
                _EVENTS_LOG.appendleft(e)
        if active:
            add_log(f"[event] restored {len(active)} active events from ledger branch")
    except Exception:
        pass

@app.route("/api/argus/events-active")
def api_argus_events_active():
    """Public read: current active 24/7 events for the frontend. Secret-free."""
    _events_restore_once()
    active = _events_active_list()
    return jsonify({"enabled": _EVENT_BACKBONE_ENABLED, "asOf": _ai_now_iso(),
                    "schemaVersion": argus_events.SCHEMA_VERSION,
                    "count": len(active), "events": active[:30]})

_CTX_FETCH = object()   # sentinel: fetch-allowed default for _event_card_context

def _event_card_context_cached(active):
    """CACHED-ONLY variant for the public evidence-pack GET (v11.2.1)."""
    return _event_card_context(active, tdnet_snapshot=_tdnet_recent_cached_only())


def _event_card_context(active, tdnet_snapshot=_CTX_FETCH):
    """Per-event corroboration context for EventCard v2 — reuses the mesh's own
    corroboration_level over the event source + any IntelligenceItems linked to the
    event's symbol. Two syndicated copies of one wire stay ONE family (mesh handles it).
    `tdnet_snapshot`: pass a cached snapshot (or None) to forbid fetching (v11.2.1)."""
    ctx = {}
    intel = list(_INTEL_STORE)
    _PRICE_TYPES = {"PRICE_MOVE", "PRICE_SPIKE", "PRICE_CRASH", "LIMIT_UP", "LIMIT_DOWN",
                    "GAP", "VOLUME_ANOMALY", "FLOW_ANOMALY"}
    # Official TDnet disclosures by symbol (v11.1) → an OFFICIAL confirmation on the
    # EventCard. Prefers the official J-Quants Add-on; yanoshin fallback is non-official
    # so it does NOT set has_official.
    try:
        _td = get_tdnet_recent(150) if tdnet_snapshot is _CTX_FETCH else (tdnet_snapshot or {})
        _td_official = bool(_td.get("official"))
        _td_by_sym = _td.get("bySymbol") or {}
    except Exception:
        _td_official, _td_by_sym = False, {}
    for e in active:
        sym = e.get("symbol")
        src_ids = [e.get("source")] if e.get("source") else []
        tiers = []
        for it in intel:
            if sym and sym in (it.get("linkedAssets") or []):
                if it.get("sourceId"):
                    src_ids.append(it["sourceId"])
                if it.get("sourceTier"):
                    tiers.append(it["sourceTier"])
        src_ids = [s for s in src_ids if s]
        try:
            corr = argus_research_mesh.corroboration_level(src_ids) if src_ids else "single"
        except Exception:
            corr = "single"
        etype = str(e.get("eventType") or "").upper()
        # Official TDnet disclosure for this symbol → official confirmation. A MATERIAL
        # disclosure adds an official source id (so corroboration can reach 'official').
        td_rows = _td_by_sym.get(str(sym)) if sym else None
        td_material = bool(td_rows and any(r.get("material") for r in td_rows))
        has_official = (corr == "official") or (_td_official and bool(td_rows))
        if _td_official and td_rows:
            src_ids = list(src_ids) + ["official:tdnet"]
            tiers.append("exchange_or_listing_venue")
        ctx[e.get("eventId")] = {
            "source_ids": src_ids or None,
            "independent_family_count": (2 if corr == "corroborated" else (1 if src_ids else 0)),
            "has_official": has_official,
            "theme_only": etype in ("THEME", "CAOS_CANDIDATE", "INSTITUTIONAL_VIEW") and not td_material,
            "market_confirmed": etype in _PRICE_TYPES,   # the observed move confirms itself
            "source_tiers": sorted(set(tiers)),
        }
    return ctx


@app.route("/api/argus/events/cards")
@app.route("/api/argus/events/cards/<card_id>")
def api_argus_event_cards(card_id=None):
    """EventCard v2 — the canonical research object (ARGUS Pro v11). Folds active
    events + corroboration context + the Visibility Guard into disciplined cards:
    a single-source association is never a confirmed_cause, a theme-only link cannot
    move the Today call, confidenceFinal = min(raw, cap), and every card states what
    is missing. Public, secret-free."""
    _events_restore_once()
    try:
        guard = _visibility_guard()
    except Exception:
        guard = {}
    active = _events_active_list()
    cards = argus_event_card.build_cards(active, guard=guard,
                                         context_by_event=_event_card_context(active),
                                         now_iso=_ai_now_iso())
    if card_id:
        card = next((c for c in cards if c.get("cardId") == card_id), None)
        return (jsonify(card), 200) if card else (jsonify({"error": "not_found", "cardId": card_id}), 404)
    symbol = (request.args.get("symbol") or "").strip().upper()
    etype = (request.args.get("type") or "").strip()
    if symbol:
        cards = [c for c in cards if symbol in (c.get("directAssets") or [])
                 or symbol in (c.get("associatedAssets") or [])]
    if etype:
        cards = [c for c in cards if c.get("eventType") == etype]
    try:
        limit = max(1, min(60, int(request.args.get("limit", "30"))))
    except Exception:
        limit = 30
    return jsonify({"asOf": _ai_now_iso(), "schemaVersion": argus_event_card.SCHEMA_VERSION,
                    "count": len(cards), "items": cards[:limit]})


@app.route("/api/argus/caos/audit")
def api_argus_caos_audit():
    """C.A.O.S. association audit trail (ARGUS Pro v11) — WHY each symbol↔event link
    exists (matched terms, source family/tier, corroboration) with a permanent
    non-causality caveat. Metadata only; never full text. Public, secret-free."""
    symbol = (request.args.get("symbol") or "").strip().upper() or None
    try:
        limit = max(1, min(200, int(request.args.get("limit", "100"))))
    except Exception:
        limit = 100
    return jsonify({"asOf": _ai_now_iso(), **argus_caos_audit.snapshot(symbol=symbol, limit=limit)})


# ── Evidence Pack — the decision spine's canonical input (v11.2) ─────────────
# CACHED-ONLY accessors (v11.2.1): the PUBLIC evidence-pack GET must never trigger a
# paid provider fetch, an LLM call, or a public-text fetch — not even on a cold cache.
# These read the in-process caches AS-IS (stale is fine, honest) and return None/{} on
# a miss; the scheduled/cron/other endpoints keep refreshing those caches.
def _tdnet_recent_cached_only():
    d = _TDNET_OFFICIAL_CACHE.get("data")
    if d and d.get("items"):
        return d
    return _TDNET_FEED_CACHE.get("data")            # yanoshin cache, may be None

def _quote_cached_only(sym, market):
    """Cached quote for one symbol: bridge push → dynamic snapshot caches → curated
    cache. NEVER fetches."""
    q = (_PUSHED_QUOTES.get(market) or {}).get(sym)
    if q and isinstance(q.get("row"), dict):
        return dict(q["row"], status="live")
    dyn = _JP_DYN_CACHE if market == "JP" else _US_DYN_CACHE
    try:
        for ent in list(dyn.values()):
            for s in ((ent.get("data") or {}).get("stocks") or []):
                if str(s.get("symbol")).upper() == sym:
                    return s
    except Exception:
        pass
    cur = (_JP_CACHE if market == "JP" else _US_CACHE).get("data") or {}
    for s in (cur.get("stocks") or []):
        if str(s.get("symbol")).upper() == sym:
            return s
    return None

def _visibility_guard_cached_only():
    return _VISIBILITY_CACHE.get("data") or {}

def _market_depth_proof_cached_only():
    """Depth-proof summary from the CACHED depth report only (a cold _market_depth_report
    can reach the paid TDnet probe via _source_registry — so never trigger it here)."""
    rep = _MARKET_DEPTH_CACHE.get("data")
    if not rep:
        return None
    items = _market_depth_proof_items(rep.get("capabilities") or {})
    return {"summary": {
        "trueDepthLiveCount": sum(1 for i in items if i["status"] == "live" and i["isTrueDepth"]),
        "computedIndicatorsLiveCount": sum(1 for i in items if i["status"] == "live" and not i["isTrueDepth"]),
        "requiresContractCount": sum(1 for i in items if i["status"] == "requires_contract"),
    }}

def _source_coverage_cached_only():
    """In-memory tally of the intel store (no network by construction)."""
    try:
        return {"summary": {
            "totalItems": len(_INTEL_STORE),
            "canGroundJudgmentItems": sum(1 for it in _INTEL_STORE if it.get("canGroundJudgment")),
            "weakSignalItems": sum(1 for it in _INTEL_STORE if it.get("weakSignal")),
        }}
    except Exception:
        return None

# Build stats for /decision-spine/status (secret-free; symbol is public-watchlist scope).
_EVIDENCE_PACK_STATE = {"lastBuildAt": None, "lastSymbol": None,
                        "cacheMissCountToday": 0, "day": None}


def _build_evidence_pack(symbol, market=None):
    """Assemble the canonical Evidence Pack for ONE symbol from ALREADY-CACHED data
    ONLY (v11.2.1). A cache miss yields empty fields + an explicit cache:* marker in
    missingConfirmations — never a live fetch. The fold itself is pure."""
    sym = str(symbol).strip().upper()
    as_of = _ai_now_iso()
    mkt = argus_evidence_pack.infer_market(sym, market)
    cache_missing = set()
    quote = _quote_cached_only(sym, mkt) if mkt in ("JP", "US") else None
    if mkt in ("JP", "US") and quote is None:
        cache_missing.add("cache:quote")
    guard = _visibility_guard_cached_only()
    if not guard:
        cache_missing.add("cache:visibility_guard")
    try:
        active = [e for e in _events_active_list() if str(e.get("symbol") or "").upper() == sym]
        cards = argus_event_card.build_cards(active, guard=guard,
                                             context_by_event=_event_card_context_cached(active),
                                             now_iso=as_of)
    except Exception:
        cards = []
    td = _tdnet_recent_cached_only()
    if td is None:
        discs = []
        cache_missing.add("cache:tdnet")
    else:
        discs = (td.get("bySymbol") or {}).get(sym[:4], [])
    try:
        caos = argus_caos_audit.snapshot(symbol=sym, limit=6).get("items") or []
    except Exception:
        caos = []
    try:
        views = [it for it in list(_INTEL_STORE) if sym in (it.get("linkedAssets") or [])][:6]
    except Exception:
        views = []
    cov = _source_coverage_cached_only()
    if cov is None:
        cache_missing.add("cache:source_coverage")
    dp = _market_depth_proof_cached_only()
    if dp is None:
        cache_missing.add("cache:market_depth")
    # Calibration/DV: read ARGUS's OWN cached summaries (the ledger is ARGUS's own free
    # public artifact — no paid provider, no LLM, no article text). Cold cache → honest
    # cache marker instead of a fetch.
    try:
        _v4 = _CALIB_V4_CACHE.get("data")
        _days = int((((_ledger_summary() or {}).get("overall")) or {}).get("days") or 0)
        cal = {"isActive": bool(_v4) and any(isinstance((_v4 or {}).get(k), (int, float)) and (_v4 or {}).get(k) > 0
                                             for k in ("nPredictions", "n", "count", "records")),
               "reliabilityStage": argus_calibration.reliability_stage(_days)}
    except Exception:
        cal = None
    try:
        _dv = _dv_status_public_dict()
        dvd = {"phase": _dv.get("phase"), "sampleStage": _dv.get("sampleStage")}
    except Exception:
        dvd = None
    # v11.3: lifecycle-tracked official events for this symbol (in-memory store =
    # cached-only compliant).
    try:
        oe_refs = [argus_official_event_lifecycle.evidence_ref(r)
                   for r in _official_events_by_symbol(sym)[:5]]
    except Exception:
        oe_refs = []
    pack = argus_evidence_pack.build_pack(
        symbol=sym, as_of=as_of, market=mkt, quote=quote, event_cards=cards,
        official_disclosures=discs, filings=[], caos_links=caos, institutional_views=views,
        source_coverage=cov, market_depth_proof=dp, visibility_guard=guard,
        calibration_status=cal, decision_value_status=dvd, past_failure_patterns=[],
        official_event_refs=oe_refs)
    if cache_missing:
        pack["missingConfirmations"] = sorted(set(pack["missingConfirmations"]) | cache_missing)
    # v11.4: Learning Memory (compact, symbol-relevant, CAUTION-ONLY). Cache-only
    # read of ARGUS's own aggregated history — never grounds/confirms/forces a
    # decision, only caps confidence / adds caution.
    try:
        lm = _learning_memory_compact_for_symbol(sym, mkt)
        if lm:
            pack["learningMemory"] = lm
    except Exception:
        pass
    # build stats for /decision-spine/status (public-watchlist-scope symbol only)
    _today = datetime.now(TZ_JST).strftime("%Y-%m-%d")
    if _EVIDENCE_PACK_STATE.get("day") != _today:
        _EVIDENCE_PACK_STATE.update(day=_today, cacheMissCountToday=0)
    _EVIDENCE_PACK_STATE.update(lastBuildAt=as_of, lastSymbol=sym)
    if cache_missing:
        _EVIDENCE_PACK_STATE["cacheMissCountToday"] += 1
    return pack


@app.route("/api/argus/evidence-pack")
def api_argus_evidence_pack():
    """The canonical Evidence Pack for one symbol (ARGUS Pro v11.2) — what every judge
    (rules / GPT / Gemini / TodayCall) reads. Public GET: cached data only, no LLM calls,
    no public-text fetches, no private holdings/P&L. Empty arrays when nothing collected."""
    sym = (request.args.get("symbol") or "").strip()
    if not sym:
        return jsonify({"error": "symbol_required",
                        "messageJa": "銘柄コードを指定してください（例 ?symbol=8058&market=JP）。"}), 400
    market = (request.args.get("market") or "").strip().upper() or None
    return jsonify(_build_evidence_pack(sym, market))


@app.route("/api/argus/decision-spine/status")
def api_argus_decision_spine_status():
    """Decision Spine status (v11.2.1) — is the spine actually wired end-to-end?
    Public-safe: no keys/headers/provider URLs, no private holdings/P&L; the last-built
    symbol is public-watchlist scope by construction."""
    limitations = []
    # action labels: same cached composition the public /action-labels endpoint serves
    try:
        al = get_action_labels()
        labs = al.get("labels") or []
        with_refs = sum(1 for l in labs
                        if str(((l.get("decisionRefs") or {}).get("evidencePackId")) or "").startswith("ep-"))
        al_stats = {"decisionRefsAttached": bool(labs) and with_refs == sum(
                        1 for l in labs if l.get("status") != "mock"),
                    "labelsWithEvidenceRefs": with_refs, "totalLabels": len(labs)}
    except Exception:
        al_stats = {"decisionRefsAttached": False, "labelsWithEvidenceRefs": 0, "totalLabels": 0}
        limitations.append("action-labelsの取得に失敗（一時的）。")
    # AI judgment: cached payload only (never triggers a run)
    ai_payload = _AI_RESULT_CACHE.get("data")
    if not ai_payload:
        try:
            with open(_AI_LATEST_FILE, "r") as f:
                ai_payload = json.load(f)
        except Exception:
            ai_payload = None
    gem_included = bool((ai_payload or {}).get("geminiChallenge"))
    ai_refs = any((l.get("decisionRefs") or {}).get("evidencePackId")
                  for l in ((ai_payload or {}).get("labels") or []))
    if ai_payload and not gem_included:
        limitations.append("AI判定キャッシュがv11.2以前の実行分のため、geminiChallenge/evidence refsは次回実行から付きます。")
    if not ai_payload:
        limitations.append("AI判定はまだ実行されていません（キャッシュなし）。")
    return jsonify({
        "schemaVersion": "decision-spine-v1",
        "asOf": _ai_now_iso(),
        "evidencePack": {
            "endpointAvailable": True,
            "publicReadCachedOnly": True,          # enforced by cached-only accessors + tests
            "lastBuildAt": _EVIDENCE_PACK_STATE.get("lastBuildAt"),
            "lastSymbol": _EVIDENCE_PACK_STATE.get("lastSymbol"),
            "cacheMissCountToday": _EVIDENCE_PACK_STATE.get("cacheMissCountToday", 0),
        },
        "actionLabels": al_stats,
        "aiJudgment": {
            "evidenceContextIncluded": True,       # _build_ai_snapshot attaches evidenceContext (v11.2)
            "geminiChallengeIncluded": gem_included,
            "aiLabelsCarryEvidenceRefs": ai_refs,
            "lastRunAt": (ai_payload or {}).get("asOf"),
        },
        "safety": {
            "publicFetchBlocked": True,
            "llmOnPublicGetBlocked": True,
            "paidFetchOnPublicGetBlocked": True,
        },
        "limitationsJa": limitations,
    })


@app.route("/api/argus/event-log")
def api_argus_event_log():
    """Public read: recent event history (for the durable-snapshot workflow)."""
    _events_restore_once()
    with _EVENT_LOCK:
        log = list(_EVENTS_LOG)[:60]
    return jsonify({"asOf": _ai_now_iso(), "count": len(log), "events": log})

@app.route("/api/argus/event-snapshot")
def api_argus_event_snapshot():
    """Public read: the full durable snapshot (active + log) the event-ledger
    workflow commits to the branch. No secrets (events are watchlist anomalies)."""
    _events_restore_once()
    active = _events_active_list()
    with _EVENT_LOCK:
        log = list(_EVENTS_LOG)
    return jsonify(argus_event_store.serialize_state(active, log, now_iso=_ai_now_iso()))

@app.route("/api/argus/crypto-scan", methods=["POST"])
def api_argus_crypto_scan():
    """ADMIN-ONLY 24/7 crypto shock scan — invoked by the crypto-watch workflow
    (not the public frontend). Crypto trades around the clock, so this is what
    makes the 24h promise honest off-session. Deterministic, no LLM."""
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    if not _EVENT_BACKBONE_ENABLED:
        return jsonify({"scanned": 0, "recorded": 0, "reason": "backbone_disabled"})
    snap = get_crypto_watchlist_snapshot(_CRYPTO_DEFAULT_IDS)
    now = datetime.now(pytz.utc)
    _events_restore_once()
    scanned = recorded = 0
    for q in (snap.get("quotes") if isinstance(snap, dict) else None) or []:
        if q.get("status") != "live":
            continue
        scanned += 1
        sym = str(q.get("id") or "").upper()[:12] or "CRYPTO"
        for trig in argus_events.detect_crypto_anomaly(sym, q.get("changePct")):
            env = _record_event("CRYPTO", sym, trig, now, "CRYPTO_24H",
                                bucket_minutes=360, source="coingecko",
                                session_override="CRYPTO_24H")
            if env:
                recorded += 1
    return jsonify({"scanned": scanned, "recorded": recorded, "asOf": _ai_now_iso()})

# ── Evidence-First Research Dossier (dossier-v1, v10.41) — deterministic ──────
# Built on-demand from signals ARGUS ALREADY has (cached entry-scout flow/credit,
# news context, broad-index move). NO LLM (AI Gear 2/3 is a future opt-in), so a
# public GET never triggers a model call — only cheap, cached, deterministic
# assembly. Cached per event so repeated reads are free.
_DOSSIER_CACHE = {}   # (eventId, eventVersion, evidenceHash) -> dossier

# ── EDINET official-filing source (edinet-v1, v10.48) ────────────────────────
# 金融庁 EDINET API v2 — official corporate disclosures (有報・大量保有報告 等).
# Requires a free Subscription-Key (user registers + sets EDINET_API_KEY in
# Render). When a recent EDINET filing matches an event's symbol, the dossier
# gains a REAL official_fact (claimType=official_fact, tier=official_filing) so
# official_catalyst becomes reachable. No key → source missing (honest).
_EDINET_API_KEY = os.environ.get("EDINET_API_KEY", "")
_EDINET_BASE    = "https://api.edinet-fsa.go.jp/api/v2/documents.json"
_EDINET_CACHE   = {}    # date -> (results|None, expires)
_EDINET_STATE   = {"lastFetchOk": False, "lastAt": None}

def edinet_match_symbol(results, symbol):
    """Pure (unit-tested): EDINET filings whose secCode (5-digit, ticker+0) maps
    to the 4-digit symbol. Compact metadata only — never the filing body."""
    out = []
    for r in results or []:
        if str(r.get("secCode") or "")[:4] == str(symbol):
            out.append({"docID": r.get("docID"), "filerName": r.get("filerName"),
                        "docTypeCode": r.get("docTypeCode"),
                        "docDescription": r.get("docDescription"),
                        "submitDateTime": r.get("submitDateTime")})
    return out

def _edinet_filings(date_str):
    """EDINET documents.json for a date (metadata, type=2). Cached. None without
    a key or on failure. The key is sent server-side over HTTPS, never logged."""
    if not _EDINET_API_KEY:
        return None
    now = time.time()
    c = _EDINET_CACHE.get(date_str)
    if c and now < c[1]:
        return c[0]
    data = None
    try:
        r = requests.get(_EDINET_BASE, params={"date": date_str, "type": "2",
                                               "Subscription-Key": _EDINET_API_KEY}, timeout=10)
        if r.status_code == 200:
            j = r.json()
            if isinstance(j, dict) and isinstance(j.get("results"), list):
                data = j["results"]
                _EDINET_STATE["lastFetchOk"] = True
                _EDINET_STATE["lastAt"] = _ai_now_iso()
    except Exception:
        data = None
    today = datetime.now(TZ_JST).strftime("%Y-%m-%d")
    ttl = 1800 if date_str == today else 6 * 3600
    _EDINET_CACHE[date_str] = (data, now + (ttl if data is not None else 600))
    return data

def _edinet_recent_for(symbol, now=None):
    """Recent EDINET filings (today + yesterday) for a JP symbol. [] without key."""
    if not _EDINET_API_KEY:
        return []
    n = now or datetime.now(TZ_JST)
    found = []
    for back in (0, 1):
        res = _edinet_filings((n - timedelta(days=back)).strftime("%Y-%m-%d"))
        if res:
            found += edinet_match_symbol(res, symbol)
    return found[:3]

def _ev_item(n, eid, source, stype, claim_type, claim, reliability, *,
             observed_at=None, published_at=None, fetched_at=None, now_iso=None,
             source_event_id=None, url=None, meta=None):
    """One evidence item with TRUE source/event times preserved (null when
    unavailable — never fabricated to the GET clock). contentHash is stable."""
    fetched = fetched_at or now_iso
    fresh = None
    if observed_at and now_iso:
        try:
            o = datetime.strptime(observed_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.utc)
            fresh = max(0, int((datetime.now(pytz.utc) - o).total_seconds()))
        except Exception:
            fresh = None
    return {"evidenceId": f"{eid}#ev{n}", "eventId": eid, "source": source,
            "sourceType": stype, "sourceURL": url, "sourceEventId": source_event_id,
            "publishedAt": published_at, "observedAt": observed_at, "fetchedAt": fetched,
            "freshnessSeconds": fresh, "reliability": reliability, "claimType": claim_type,
            "normalizedClaim": claim, "compactRawMetadata": meta,
            "contentHash": hashlib.sha256(f"{eid}|{claim_type}|{claim}".encode("utf-8")).hexdigest()[:16],
            "status": "active", "schemaVersion": "evidence-v1"}

def _event_by_id(eid):
    with _EVENT_LOCK:
        for e in _EVENTS_ACTIVE.values():
            if e.get("eventId") == eid:
                return e
        for e in _EVENTS_LOG:
            if e.get("eventId") == eid:
                return e
    return None

# News-Radar / Catalyst feeds are secondary media (GDELT/Finnhub aggregation),
# NOT a verified official filing — so the highest tier they can earn is
# reputable_secondary_media. official_catalyst stays unreachable until a real
# TDnet/EDINET/IR feed is wired (honest; no over-claiming).
_NEWS_SOURCE_TIER = "reputable_secondary_media"

def _build_event_dossier(env, push_row=None):
    """Deterministic EVENT-TIME dossier. push_row is the quote that triggered the
    event (preferred over the latest quote). Never raises a fabricated timestamp."""
    sym, mkt = env.get("symbol"), env.get("market")
    eid, now_iso = env.get("eventId"), _ai_now_iso()
    scout = None
    try:
        if mkt in ("JP", "US"):
            scout = get_entry_scout(sym, mkt)        # 6h-cached — usually free
    except Exception:
        scout = None
    flow_inf = (scout or {}).get("flowInference") or {}
    rsi = ((scout or {}).get("metrics") or {}).get("rsi14")
    name = (scout or {}).get("name")
    scout_asof = (scout or {}).get("asOf")
    # symbol move at EVENT TIME (the triggering push), else the held quote
    pq = (_PUSHED_QUOTES.get(mkt) or {}).get(sym)
    row = push_row or (pq or {}).get("row") or {}
    sym_chg = row.get("changePct")
    obs_at = env.get("observedAt") or env.get("detectedAt")
    # broad-market baseline: US from the Market-Regime SPY stash (SPY is NOT a
    # bridge symbol); JP from a pushed 1306 (TOPIX ETF) if present, else None.
    index_chg, index_fresh = None, True
    if mkt == "US":
        spy = _ETF_LAST_PRICE.get("SPY")
        if spy:
            index_chg = spy.get("m1d")
            index_fresh = (time.time() - (spy.get("ts") or 0)) < 6 * 3600
    else:
        iq = (_PUSHED_QUOTES.get("JP") or {}).get("1306")
        if iq:
            index_chg = (iq.get("row") or {}).get("changePct")
            index_fresh = (time.time() - (iq.get("ts") or 0)) < 1800
    cat = (scout or {}).get("catalystContext") or {}
    news_items = [it.get("headline") or it.get("labelJa") for it in (cat.get("items") or [])
                  if it.get("kind") == "news" and (it.get("headline") or it.get("labelJa"))][:3]
    # EDINET official filings (JP, when EDINET_API_KEY is set) — a REAL official
    # fact, so the catalyst becomes official-tier (not just reported media).
    edinet = []
    try:
        if mkt == "JP":
            edinet = _edinet_recent_for(sym)
    except Exception:
        edinet = []
    # EDINET semantics (v10.50): an EDINET filing is ALWAYS an official_fact, but
    # only a MATERIALLY-RELEVANT filing (臨時報告/大量保有) whose submission
    # plausibly coincides with the move becomes an official_CATALYST. Periodic/
    # amendment filings are recorded as fact but DON'T attribute the move to them.
    event_date = (str(obs_at)[:10] if obs_at else datetime.now(TZ_JST).strftime("%Y-%m-%d"))
    for f in edinet:
        f["docClass"] = argus_research.classify_edinet_doc(f.get("docTypeCode"), f.get("docDescription"))
        f["eventRelationship"] = argus_research.edinet_event_relationship(f.get("submitDateTime"), event_date)
    edinet_is_catalyst, _edinet_cat = argus_research.edinet_catalyst_decision(edinet, event_date)
    catalyst_tier = ("official_filing" if edinet_is_catalyst
                     else _NEWS_SOURCE_TIER if news_items else "unknown")
    # TDnet decision metric (item G): record whether the official catalyst was
    # known for this JP high/critical event (no TDnet data used).
    _record_tdnet_metric(env, edinet_is_catalyst, bool(news_items))
    evidence, n = [], 1
    if isinstance(sym_chg, (int, float)):
        evidence.append(_ev_item(n, eid, "moomoo-bridge", "primary_market_data", "market_observation",
                                  f"{sym} {sym_chg:+.2f}%", 0.9, observed_at=obs_at, now_iso=now_iso)); n += 1
    for f in edinet[:2]:
        desc = f.get("docDescription") or f.get("docTypeCode") or "EDINET開示"
        dcl, rel = f.get("docClass") or "other", f.get("eventRelationship") or "unknown"
        is_cause = (dcl in argus_research.EDINET_CATALYST_CLASSES and rel == "precedes_or_same_day")
        # official_fact ALWAYS; the claim notes whether it qualifies as the cause.
        evidence.append(_ev_item(n, eid, "EDINET", "official_filing", "official_fact",
                                  f"{f.get('filerName') or sym}: {desc} [{dcl}/{rel}"
                                  f"{'・catalyst候補' if is_cause else '・cause扱いせず'}]", 0.92,
                                  published_at=f.get("submitDateTime"), now_iso=now_iso,
                                  source_event_id=f.get("docID"),
                                  url=(f"https://disclosure2.edinet-fsa.go.jp/WEEK0010.aspx" if f.get("docID") else None),
                                  meta={"docClass": dcl, "docTypeCode": f.get("docTypeCode"),
                                        "issuer": f.get("filerName"), "eventRelationship": rel,
                                        "qualifiesAsCatalyst": is_cause})); n += 1
    if argus_research.has_confirmed_flow_signal(flow_inf.get("classification")):
        evidence.append(_ev_item(n, eid, "argus-flow-intelligence", "derived", "derived_metric",
                                  f"flow={flow_inf['classification']}", 0.6,
                                  observed_at=scout_asof, now_iso=now_iso)); n += 1
    for nm in news_items:
        evidence.append(_ev_item(n, eid, "news-radar", "secondary_media", "news_report", nm,
                                  argus_research.tier_reliability(_NEWS_SOURCE_TIER),
                                  observed_at=None, now_iso=now_iso)); n += 1   # true pub time unknown → null
    ev_hash = hashlib.sha256("|".join(e["contentHash"] for e in evidence).encode("utf-8")).hexdigest()[:16]
    times = {"asOf": now_iso, "dossierGeneratedAt": now_iso,
             "eventObservedAt": env.get("observedAt"), "eventDetectedAt": env.get("detectedAt"),
             "evidenceAsOf": obs_at, "nextReviewAt": env.get("nextReviewAt"),
             "mode": "event_time_snapshot",
             "sourceFreshness": {"quote": "event-time", "news": "publication-time-unknown",
                                 "indexBaseline": ("fresh" if index_fresh else "stale_or_missing")}}
    return argus_research.build_dossier(
        event=env, flow_inf=flow_inf, rsi=rsi, sym_chg=sym_chg, index_chg=index_chg,
        index_fresh=index_fresh, catalyst_tier=catalyst_tier, evidence=evidence,
        times=times, evidence_hash=ev_hash, asset_name=name)

@app.route("/api/argus/event-dossier")
def api_argus_event_dossier():
    """Public read of the deterministic Research Dossier. Reads the stored
    event-time snapshot; rebuilds only if the event revision changed. No model
    call. Proper HTTP semantics (400/404/500/503)."""
    eid = (request.args.get("eventId") or "").strip()
    if not eid:
        return jsonify({"error": "missing_eventId"}), 400
    env = _event_by_id(eid)
    if not env:
        return jsonify({"error": "event_not_found"}), 404
    stored = env.get("dossier")
    ver = env.get("eventVersion", 1)
    if stored and stored.get("eventVersion") == ver:
        return jsonify(stored)                    # event-time snapshot, no rebuild
    ck = (eid, ver, env.get("dossier", {}).get("evidenceHash") if stored else None)
    if ck not in _DOSSIER_CACHE:
        try:
            _DOSSIER_CACHE[ck] = _build_event_dossier(env)
            _DOSSIER_CACHE[ck]["dossierMode"] = "latest_revision"   # built post-hoc, disclosed
        except Exception as e:
            add_log(f"[dossier] build failed {eid}: {type(e).__name__}")
            return jsonify({"error": "dossier_build_failed", "detail": type(e).__name__}), 500
    return jsonify(_DOSSIER_CACHE[ck])

_EVENT_TEST_STATE = {"lastTs": 0.0, "day": "", "count": 0}
_EVENT_TEST_DAILY_CAP = 6   # bound abuse: at most 6 owner-phone test pushes/day

@app.route("/api/argus/event-test-notify", methods=["POST"])
def api_argus_event_test_notify():
    """ADMIN-ONLY test push (GPT review #9): a public surface that can buzz the
    owner's phone is removed. Auth via the standard admin gate (401/503); the
    cooldown + daily cap + audit log remain as defence in depth. Never echoes
    the topic."""
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    now = time.time()
    if not os.environ.get("NTFY_TOPIC"):
        return jsonify({"sent": False, "reason": "ntfy_not_configured",
                        "noteJa": "RenderにNTFY_TOPICが未設定です。"}), 200
    today = datetime.now(TZ_JST).strftime("%Y-%m-%d")
    if _EVENT_TEST_STATE["day"] != today:
        _EVENT_TEST_STATE["day"], _EVENT_TEST_STATE["count"] = today, 0
    if _EVENT_TEST_STATE["count"] >= _EVENT_TEST_DAILY_CAP:
        return jsonify({"sent": False, "reason": "daily_cap",
                        "noteJa": f"本日のテスト送信は上限({_EVENT_TEST_DAILY_CAP}回)に達しました。"}), 200
    if now - _EVENT_TEST_STATE["lastTs"] < 180:
        wait = int(180 - (now - _EVENT_TEST_STATE["lastTs"]))
        return jsonify({"sent": False, "reason": "rate_limited",
                        "noteJa": f"連投防止のため約{wait}秒後に再試行してください。"}), 200
    _EVENT_TEST_STATE["lastTs"] = now
    _EVENT_TEST_STATE["count"] += 1
    add_log(f"[event] test-notify fired ({_EVENT_TEST_STATE['count']}/{_EVENT_TEST_DAILY_CAP} today)")
    _event_ntfy({"symbol": "TEST", "eventType": "TEST_NOTIFICATION", "market": "—",
                 "session": "test", "severity": 4, "recommendedPosture": "WATCH",
                 "reasonJa": "ARGUS 24/7監視の通知テストです。これが届けば設定完了。"})
    return jsonify({"sent": True, "noteJa": "テスト通知を送信しました。スマホを確認してください。"})

_EVENT_SNAP_META = {"data": None, "expires": 0.0}

def _event_snapshot_meta():
    """Last durable snapshot's metadata from the ledger branch (10-min cache)."""
    now = time.time()
    if now < _EVENT_SNAP_META["expires"]:
        return _EVENT_SNAP_META["data"]
    data = None
    try:
        r = requests.get(f"{_LEDGER_RAW_BASE}/events/snapshot.json?cb={int(now)}", timeout=6)
        if r.status_code == 200:
            d = r.json()
            data = {"snapshotAt": d.get("snapshotAt"), "activeCount": d.get("activeCount")}
    except Exception:
        data = None
    _EVENT_SNAP_META["data"] = data
    _EVENT_SNAP_META["expires"] = now + (600 if data else 300)
    return data

@app.route("/api/argus/event-backbone-status")
def api_argus_event_backbone_status():
    """Public ops summary (no secrets) — for the Ledger Health / Ops view."""
    _events_restore_once()
    with _EVENT_LOCK:
        active = len(_EVENTS_ACTIVE)
    snap = _event_snapshot_meta()
    return jsonify({
        "enabled": _EVENT_BACKBONE_ENABLED, "gear2Enabled": _EVENT_GEAR2_ENABLED,
        "activeCount": active, "schemaVersion": argus_events.SCHEMA_VERSION,
        "lastDetectionAt": _EVENT_STATE["lastDetectionAt"], "lastEventAt": _EVENT_STATE["lastEventAt"],
        "detectionsThisProcess": _EVENT_STATE["detections"],
        "ntfyConfigured": bool(os.environ.get("NTFY_TOPIC")), "ntfyMinSeverity": _EVENT_NTFY_MIN_SEV,
        "sessionJp": _jp_market_open(), "sessionUs": _us_market_open(),
        # v10.42 durable store status
        "persistenceEnabled": _EVENT_PERSISTENCE_ENABLED, "restoredOnBoot": _EVENTS_RESTORED["done"],
        "lastSnapshotAt": (snap or {}).get("snapshotAt"), "storeMode": "ledger-branch (Lean)",
        "noteJa": "決定論的Gear0/1のみ稼働(LLMなし)。ブリッジの既存pushを解析しS高/急変/フロー異常を検知。"
                  "イベントはledgerブランチにスナップショット永続(再起動時に復元)。PTS/L2/VWAPは未対応(capability-gated)。",
    })

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
_CRYPTO_CACHE_TTL  = 90          # ~realtime (coingecko simple/price)
# Plausible fallback values (NOT real quotes) so the UI renders in mock state.
_CRYPTO_MOCK = {
    "bitcoin":  {"price": 68_200.0, "changePct": 1.2, "volume": 28_000_000_000},
    "ethereum": {"price": 3_820.0,  "changePct": 0.8, "volume": 14_000_000_000},
}

# CoinGecko's keyless public API is rate-limited/blocked from datacenter IPs
# (Render), so in production it silently fell to mock (v10.208 bug report). Two
# fixes: (1) a free Demo API key (env COINGECKO_API_KEY, sent as the
# x-cg-demo-api-key header) restores reliable cloud access; (2) if there's no key
# OR CoinGecko still fails, fall back to Coinbase's keyless public stats endpoint
# — datacenter-friendly — so crypto shows REAL prices, not mock, with zero setup.
_COINGECKO_KEY = os.environ.get("COINGECKO_API_KEY") or os.environ.get("COINGECKO_DEMO_API_KEY")
# coingecko id -> Coinbase product base (keyless fallback; major coins only).
_CG_TO_COINBASE = {
    "bitcoin": "BTC", "ethereum": "ETH", "solana": "SOL", "ripple": "XRP",
    "cardano": "ADA", "dogecoin": "DOGE", "litecoin": "LTC", "polkadot": "DOT",
    "avalanche-2": "AVAX", "chainlink": "LINK", "polygon": "MATIC", "matic-network": "MATIC",
    "tron": "TRX", "stellar": "XLM", "bitcoin-cash": "BCH", "uniswap": "UNI",
    "cosmos": "ATOM", "aptos": "APT", "arbitrum": "ARB", "optimism": "OP",
    "shiba-inu": "SHIB", "near": "NEAR",
}
_COINBASE_STATS = "https://api.exchange.coinbase.com/products/{}-USD/stats"

def _crypto_coinbase_fallback(ids):
    """Keyless Coinbase stats (datacenter-friendly) for the major coins — used
    ONLY when CoinGecko is unavailable. 24h change = (last-open)/open. status is a
    real-time last-trade price, so 'live' is honest. Coins outside the map are
    skipped (no fabricated numbers)."""
    rows = []
    for i in ids:
        sym = _CG_TO_COINBASE.get(i)
        if not sym:
            continue
        try:
            r = requests.get(_COINBASE_STATS.format(sym), timeout=8,
                             headers={"User-Agent": "argus-research/1.0"})
            r.raise_for_status()
            s = r.json()
            last = float(s.get("last"))
            openp = float(s.get("open") or last)
            chg = ((last - openp) / openp * 100.0) if openp else 0.0
            rows.append({"id": i, "priceUsd": round(last, 2),
                         "changePct": round(chg, 2),
                         "volume": int(float(s.get("volume") or 0)),  # base-ccy 24h vol
                         "date": None, "status": "live"})
        except Exception:
            continue
    return rows

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

    def _fallback_or_mock():
        """CoinGecko unavailable → try keyless Coinbase (real), else mock."""
        fb = _crypto_coinbase_fallback(ids)
        if fb:
            snap = {"status": ("live" if len(fb) == len(ids) else "partial"),
                    "asOf": None, "provider": "coinbase", "quotes": fb}
            if len(_CRYPTO_CACHE) >= _CRYPTO_CACHE_MAX:
                _CRYPTO_CACHE.clear()
            _CRYPTO_CACHE[ids] = {"data": snap, "expires": now + _CRYPTO_CACHE_TTL}
            return snap
        return {"status": "mock", "asOf": None, "provider": "coingecko", "quotes": _mock_rows()}

    try:
        headers = {"User-Agent": "argus-research/1.0", "Accept": "application/json"}
        if _COINGECKO_KEY:
            headers["x-cg-demo-api-key"] = _COINGECKO_KEY   # free Demo plan: reliable from cloud
        r = requests.get(_COINGECKO_PRICE, params={
            "ids": ",".join(ids), "vs_currencies": "usd",
            "include_24hr_change": "true", "include_24hr_vol": "true",
            "include_last_updated_at": "true",
        }, headers=headers, timeout=10)
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
            return _fallback_or_mock()
        status = "live" if len(rows) == len(ids) else "partial"
        as_of  = max((x["date"] for x in rows if x["date"]), default=None)
        snapshot = {"status": status, "asOf": as_of, "provider": "coingecko", "quotes": rows}
        if len(_CRYPTO_CACHE) >= _CRYPTO_CACHE_MAX:
            _CRYPTO_CACHE.clear()
        _CRYPTO_CACHE[ids] = {"data": snapshot, "expires": now + _CRYPTO_CACHE_TTL}
        return snapshot
    except Exception:
        return _fallback_or_mock()

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


# ━━━ Japanese mutual-fund NAV (基準価額) follow (v10.60) ━━━
# FINALLY a real source for 投信 NAV: the 投信総合ライブラリー (資産運用業協会) daily
# CSV by ISIN + 協会コード (SHIFT-JIS). Free, no key. So 投資信託 can be FOLLOWED
# (latest 基準価額 + 前日比), which Twelve Data does NOT provide for JP open-end funds.
_FUND_NAV_CATALOG = {
    "03311182": {"isin": "JP90C000FXV1", "name": "eMAXIS Slim 国内株式(日経平均)"},
    "03311187": {"isin": "JP90C000GKC6", "name": "eMAXIS Slim 米国株式(S&P500)"},
    "0331418A": {"isin": "JP90C000H1T1", "name": "eMAXIS Slim 全世界株式(オール・カントリー)"},
}
_FUND_NAV_BASE  = "https://toushin-lib.fwg.ne.jp/FdsWeb/FDST030000/csv-file-download"
_FUND_NAV_CACHE = {}          # code -> {"data": dict|None, "expires": epoch}
_FUND_NAV_TTL   = 6 * 3600    # NAV is daily — 6h cache is plenty (and source-friendly)

def _toushin_nav(code):
    """Latest 基準価額(NAV) + 前日比 for a JP 投信 by 協会コード, parsed from the
    投信総合ライブラリー CSV (SHIFT-JIS). Cached. None on unknown code / error."""
    meta = _FUND_NAV_CATALOG.get(code)
    if not meta:
        return None
    now = time.time()
    c = _FUND_NAV_CACHE.get(code)
    if c and now < c["expires"]:
        return c["data"]
    out = None
    try:
        r = requests.get(_FUND_NAV_BASE,
                         params={"isinCd": meta["isin"], "associFundCd": code}, timeout=15)
        if r.status_code == 200 and r.content:
            text = r.content.decode("shift_jis", errors="ignore")
            data_rows = [ln.split(",") for ln in text.splitlines()
                         if ln[:1].isdigit() and len(ln.split(",")) >= 2]
            if data_rows:
                last = data_rows[-1]
                prev = data_rows[-2] if len(data_rows) >= 2 else None
                nav = float(last[1])
                prev_nav = float(prev[1]) if prev and prev[1] else None
                chg = round((nav / prev_nav - 1) * 100, 2) if prev_nav else None
                m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", last[0])
                date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else last[0]
                out = {"code": code, "name": meta["name"], "navYen": round(nav, 0),
                       "changePct": chg, "date": date, "status": "live"}
    except Exception:
        out = None
    _FUND_NAV_CACHE[code] = {"data": out, "expires": now + (_FUND_NAV_TTL if out else 1800)}
    return out

@app.route("/api/argus/fund-nav")
def api_argus_fund_nav():
    """Public: latest NAV + 前日比 for JP 投信 by 協会コード (default = catalog)."""
    raw = (request.args.get("codes") or "").strip()
    codes = [c.strip() for c in raw.split(",") if c.strip()] or list(_FUND_NAV_CATALOG.keys())
    funds = [x for x in (_toushin_nav(c) for c in codes[:10]) if x]
    return jsonify({"status": "live" if funds else "unavailable",
                    "asOf": _ai_now_iso(), "provider": "投信総合ライブラリー", "funds": funds})


# ━━━ US whole-market mover scanner (v10.62) ━━━
# ARGUS = the all-seeing, so detection must reach BEYOND the watchlist. Alpha
# Vantage's free TOP_GAINERS_LOSERS gives the day's biggest US gainers/losers
# (incl. ETFs); a price floor drops penny-stock pumps. Only the most extreme are
# turned into events/notifications (no spam). Needs a free ALPHAVANTAGE_API_KEY.
_ALPHAVANTAGE_KEY  = os.environ.get("ALPHAVANTAGE_API_KEY", "")
_AV_MOVERS_URL     = "https://www.alphavantage.co/query"
_AV_MOVERS_CACHE   = {"data": None, "expires": 0.0}
_AV_MOVERS_TTL     = 14 * 60  # scan refreshes every ~15 min during the US session;
                              # only the scan fetches, sized to ~24/25 free calls/day.
_MARKET_MOVER_MIN_PRICE = float(os.environ.get("MARKET_MOVER_MIN_PRICE") or 10.0)  # $1→$10 (v10.145): drop micro-cap penny pumps the owner doesn't trade
_MARKET_MOVER_PCT       = float(os.environ.get("MARKET_MOVER_PCT") or 12.0)
_MARKET_MOVER_MAX_PCT   = float(os.environ.get("MARKET_MOVER_MAX_PCT") or 60.0)  # > this = almost certainly a pump/halt artifact, not a tradable signal
_MARKET_MOVER_NOTIFY_MAX = int(os.environ.get("MARKET_MOVER_NOTIFY_MAX") or 5)
# Freshness gate (v10.143): the AV free TOP_GAINERS_LOSERS can return a PRIOR
# session's snapshot. If its own last_updated is older than this, we record it but
# do NOT push a "fresh" alert about an hours-old move (the owner saw stale spikes
# arrive at 1am JST). Env-tunable; 2h covers normal intraday refresh lag.
_MOVER_FRESH_SEC = float(os.environ.get("MOVER_FRESH_SEC") or 7200)

def _av_lastupdated_epoch(s):
    """Parse Alpha Vantage's 'YYYY-MM-DD HH:MM:SS US/Eastern' → UTC epoch, or None."""
    if not s:
        return None
    try:
        base = str(s).replace("US/Eastern", "").replace("US/E-DST", "").strip()
        dt = datetime.strptime(base, "%Y-%m-%d %H:%M:%S")
        return pytz.timezone("America/New_York").localize(dt).timestamp()
    except Exception:
        return None

def _av_market_movers(force=False):
    """US top gainers/losers from Alpha Vantage (price-filtered). status: live |
    missing_key | unavailable | warming. ONLY the scheduled scan (force=True) hits
    the API — the public endpoint serves the cache (force=False) so the frontend can
    never burn the tiny 25/day free quota. The scan cadence is sized to the US
    session so we use ~24/25 calls/day (see the market-watch workflow)."""
    if not _ALPHAVANTAGE_KEY:
        return {"status": "missing_key", "gainers": [], "losers": [], "asOf": None}
    now = time.time()
    cached = _AV_MOVERS_CACHE["data"]
    if not force:
        # public read: serve whatever the last scan cached (never fetch).
        return cached or {"status": "warming", "gainers": [], "losers": [], "asOf": None}
    if cached is not None and now < _AV_MOVERS_CACHE["expires"]:
        return cached
    out = {"status": "unavailable", "gainers": [], "losers": [], "asOf": None, "note": None}
    try:
        r = requests.get(_AV_MOVERS_URL, params={"function": "TOP_GAINERS_LOSERS",
                                                 "apikey": _ALPHAVANTAGE_KEY}, timeout=15)
        j = r.json() if r.status_code == 200 else {}
        # Surface Alpha Vantage's own message (premium gate / rate limit / bad key)
        # so the failure is debuggable instead of a silent "unavailable".
        if isinstance(j, dict):
            note = j.get("Information") or j.get("Note") or j.get("Error Message")
            if note:
                note = str(note)
                # SECURITY: Alpha Vantage echoes the API key in its rate-limit note
                # — never leak it through this public endpoint.
                if _ALPHAVANTAGE_KEY:
                    note = note.replace(_ALPHAVANTAGE_KEY, "***")
                out["note"] = note[:200]
        def _rows(key):
            rows = []
            for x in (j.get(key) or []):
                try:
                    price = float(x.get("price"))
                    chg = float(str(x.get("change_percentage", "")).replace("%", ""))
                except (TypeError, ValueError):
                    continue
                if price < _MARKET_MOVER_MIN_PRICE:
                    continue
                if abs(chg) > _MARKET_MOVER_MAX_PCT:   # drop pump/halt artifacts (e.g. +247%) — not a 1-day signal
                    continue
                rows.append({"symbol": x.get("ticker"), "price": round(price, 2),
                             "changePct": round(chg, 2)})
            return rows
        if isinstance(j, dict) and (j.get("top_gainers") or j.get("top_losers")):
            _lu = j.get("last_updated")
            out = {"status": "live", "asOf": _lu, "asOfEpoch": _av_lastupdated_epoch(_lu),
                   "gainers": _rows("top_gainers"), "losers": _rows("top_losers")}
    except Exception:
        pass
    _AV_MOVERS_CACHE["data"] = out
    # On failure/rate-limit, back off ~30 min (don't retry-burn the 25/day quota).
    _AV_MOVERS_CACHE["expires"] = now + (_AV_MOVERS_TTL if out["status"] == "live" else 1800)
    return out

@app.route("/api/argus/market-movers")
def api_argus_market_movers():
    """Public: US top gainers/losers (cache only). Prefer the CURATED liquid moomoo feed
    (real 1-day quotes from the large-cap universe) when the bridge has pushed it; else fall
    back to the (now MAX_PCT-filtered) Alpha Vantage feed. Both drop pump/halt artifacts."""
    try:
        rows = [r for r in (_moomoo_us_movers() or [])
                if isinstance(r.get("changePct"), (int, float))
                and abs(r["changePct"]) <= _MARKET_MOVER_MAX_PCT
                and (r.get("price") or 0) >= _MARKET_MOVER_MIN_PRICE]
    except Exception:
        rows = []
    if rows:
        rows.sort(key=lambda r: r["changePct"], reverse=True)
        gainers = [r for r in rows if r["changePct"] > 0][:8]
        losers = sorted([r for r in rows if r["changePct"] < 0], key=lambda r: r["changePct"])[:8]
        _decorate_mover_rows(gainers + losers, "US")
        return jsonify({"status": "live", "source": "moomoo", "asOf": _MOOMOO_US_MOVERS.get("asOf"),
                        "gainers": gainers, "losers": losers})
    out = _av_market_movers(force=False)
    try:
        _decorate_mover_rows((out.get("gainers") or []) + (out.get("losers") or []), "US")
    except Exception:
        pass
    return jsonify(out)


def _decorate_mover_rows(rows, market):
    """Attach the mover-cause ladder chip to public mover rows — STORE LOOKUP
    ONLY (the refresh cron builds the records; this route never fetches)."""
    try:
        _mover_causes_restore_once()
        today = _ai_now_iso()[:10].replace("-", "")
        for r in rows:
            rec = _MOVER_CAUSES.get(f"mc-{market}-{str(r.get('symbol') or '').upper()}-{today}")
            if rec:
                r["cause"] = {"causeStatus": rec.get("causeStatus"),
                              "causeStatusJa": rec.get("causeStatusJa"),
                              "bestLeadJa": (rec.get("bestLeadJa") or "")[:90]}
    except Exception:
        pass

# ━━━ moomoo realtime US movers (v10.146) ━━━
# Curated liquid US universe; the bridge sweeps (this ∪ live watchlist ∪ regime
# ETFs) realtime via get_market_snapshot — replacing Alpha Vantage's stale/penny
# whole-market feed for the US EMERGING movers. Env-overridable.
_US_MOVER_UNIVERSE = (os.environ.get("US_MOVER_UNIVERSE") or
    "AAPL,MSFT,NVDA,AMZN,GOOGL,GOOG,META,TSLA,AVGO,BRK.B,LLY,JPM,V,XOM,UNH,MA,COST,HD,"
    "PG,JNJ,WMT,ABBV,NFLX,CRM,BAC,ORCL,KO,MRK,CVX,AMD,PEP,ADBE,TMO,LIN,ACN,MCD,CSCO,"
    "WFC,ABT,GE,DHR,IBM,NOW,TXN,QCOM,INTU,AMAT,ISRG,CAT,VZ,PFE,DIS,CMCSA,GS,SPGI,RTX,"
    "AMGN,UBER,PM,T,LOW,UNP,HON,ELV,BKNG,NKE,COP,MU,LRCX,ADI,PLD,SYK,VRTX,REGN,PANW,"
    "KLAC,SNPS,CDNS,MDLZ,GILD,C,SBUX,BSX,ADP,MMC,CB,TJX,SCHW,MO,DE,BMY,SO,FI,DUK,"
    "INTC,PYPL,SHOP,SMCI,COIN,PLTR,MRVL,CRWD,ARM,DELL,WDAY,SNOW,ABNB,MSTR").split(",")

_MOOMOO_US_MOVERS  = {"rows": [], "ts": 0.0, "asOf": None}

@app.route("/api/argus/us-universe")
def api_argus_us_universe():
    """Bridge helper: the US sweep universe = curated liquid names ∪ the owner's
    live US watchlist ∪ the regime ETFs, as moomoo codes (auto-updates when the
    watchlist changes, no env edit needed). Admin-gated like jp-universe."""
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    syms = {s.strip().upper() for s in _US_MOVER_UNIVERSE if s.strip()}
    syms |= {s["symbol"].upper() for s in _US_WATCHLIST}
    syms |= {e.upper() for e in _REGIME_ETFS}
    return jsonify({"codes": sorted(f"US.{s}" for s in syms), "count": len(syms),
                    "asOf": _ai_now_iso()})

@app.route("/api/argus/us-movers-push", methods=["POST"])
def api_argus_us_movers_push():
    """Bridge → backend: realtime US movers from the moomoo sweep (admin+HMAC)."""
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    raw = request.get_data() or b""
    sig_ok, sig_reason = _verify_bridge_signature(raw)
    if not sig_ok:
        send_security_alert({"type": "bridge_signature_rejected", "reason": sig_reason, "meta": _client_meta()})
        return jsonify({"error": "signature_invalid", "reason": sig_reason}), 401
    body = request.get_json(silent=True) or {}
    rows = []
    for m in (body.get("movers") or [])[:200]:
        try:
            sym = str(m.get("symbol", "")).strip().upper()
            if not _US_SYM_RE.match(sym):
                continue
            price, chg = float(m.get("price") or 0), float(m.get("changePct") or 0)
            if not (price > 0 and math.isfinite(price) and math.isfinite(chg)):
                continue
            rows.append({"symbol": sym, "price": price, "changePct": round(chg, 4),
                         "volume": int(m.get("volume") or 0), "name": m.get("name")})
        except (TypeError, ValueError):
            continue
    _MOOMOO_US_MOVERS.update({"rows": rows, "ts": time.time(), "asOf": body.get("asOf")})
    return jsonify({"ok": True, "accepted": len(rows)})

def _moomoo_us_movers():
    """Fresh moomoo-swept US movers (realtime, curated ∪ watchlist) or []."""
    if time.time() - (_MOOMOO_US_MOVERS["ts"] or 0) > _MOOMOO_MOVERS_TTL:
        return []
    return list(_MOOMOO_US_MOVERS["rows"])

def _scan_market_movers():
    """Whole-market US movers, moomoo-first (v10.146): moomoo realtime sweep of the
    curated US universe ∪ watchlist → Alpha Vantage fallback (stale-gated). Gated to
    the US session; price floor + max-% filter drop penny/pump noise; caps spam."""
    if not _EVENT_BACKBONE_ENABLED or not _us_market_open():
        return 0
    now_real = datetime.now(pytz.utc)
    mm = _moomoo_us_movers()
    if mm:
        rows = [r for r in mm if abs(r.get("changePct") or 0) <= _MARKET_MOVER_MAX_PCT
                and (r.get("price") or 0) >= _MARKET_MOVER_MIN_PRICE]
        rows.sort(key=lambda r: abs(r.get("changePct") or 0), reverse=True)
        n = 0
        for row in rows[:_MARKET_MOVER_NOTIFY_MAX]:
            for trig in argus_events.detect_market_mover(row["symbol"], row["changePct"], row["price"],
                                                         min_price=_MARKET_MOVER_MIN_PRICE, gainer_pct=_MARKET_MOVER_PCT):
                env = _record_event("US", row["symbol"], trig, now_real, "US_REGULAR",
                                    bucket_minutes=180, source="moomoo-rt")
                if env:
                    env["nameJa"] = row.get("name") or row["symbol"]
                    n += 1
        return n
    # Fallback: Alpha Vantage (delayed). Data time + staleness gate (v10.143).
    mv = _av_market_movers(force=True)
    if mv.get("status") != "live":
        return 0
    av_epoch = mv.get("asOfEpoch")
    ev_time = datetime.fromtimestamp(av_epoch, pytz.utc) if av_epoch else now_real
    stale = av_epoch is None or (time.time() - av_epoch) > _MOVER_FRESH_SEC
    rows = [r for r in ((mv.get("gainers") or []) + (mv.get("losers") or []))
            if abs(r.get("changePct") or 0) <= _MARKET_MOVER_MAX_PCT]
    rows.sort(key=lambda r: abs(r.get("changePct") or 0), reverse=True)
    n = 0
    for row in rows[:_MARKET_MOVER_NOTIFY_MAX]:
        for trig in argus_events.detect_market_mover(
                row["symbol"], row["changePct"], row["price"],
                min_price=_MARKET_MOVER_MIN_PRICE, gainer_pct=_MARKET_MOVER_PCT):
            env = _record_event("US", row["symbol"], trig, ev_time, "US_REGULAR",
                                bucket_minutes=180, source="alphavantage", suppress_notify=stale)
            if env:
                env["nameJa"] = row["symbol"]
                env["dataAsOf"] = mv.get("asOf")
                env["dataStale"] = stale
                n += 1
    return n

@app.route("/api/argus/market-scan", methods=["POST"])
def api_argus_market_scan():
    """Admin: run the whole-market scans (US live + JP EOD)."""
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    try:
        return jsonify({"recordedUS": _scan_market_movers(), "recordedJP": _scan_jp_market_movers(),
                        "asOf": _ai_now_iso()})
    except Exception as e:
        return jsonify({"error": "scan_failed", "message": str(e)[:120]}), 500


# ━━━ JP whole-market EOD mover scanner (v10.64) ━━━
# J-Quants Standard gives daily bars for ALL listed stocks. No free realtime JP
# full-market feed exists, so this computes the day's biggest movers (vs prev
# close) AFTER the 15:30 close — "今日 全市場で何が動いたか". One paginated fetch
# per date, cached 6h, run post-close by the market-watch workflow.
_JP_MOVERS_CACHE = {"data": None, "expires": 0.0}
_JP_MOVERS_TTL   = 6 * 3600
_JP_MOVER_MIN_PRICE = float(os.environ.get("JP_MOVER_MIN_PRICE") or 300)
_JP_MOVER_PCT       = float(os.environ.get("JP_MOVER_PCT") or 8.0)

def _jq_all_for_date(date_str, headers, max_pages=40):
    """All-stocks daily bars for one date → {code: row}. {} if no data/error."""
    out, params = {}, {"date": date_str}
    try:
        for _ in range(max_pages):
            r = requests.get(f"{_JQUANTS_BASE}/equities/bars/daily",
                             headers=headers, params=params, timeout=20)
            if r.status_code != 200:
                break
            body = r.json()
            for row in body.get("data", []):
                c = row.get("Code") or row.get("code")
                if c:
                    out[c] = row
            pk = body.get("pagination_key")
            if not pk:
                break
            params["pagination_key"] = pk
    except Exception:
        pass
    return out

def _jq_market_movers():
    """JP whole-market EOD movers (all stocks, vs prev close). Cached."""
    if not _JQUANTS_API_KEY:
        return {"status": "missing_key", "gainers": [], "losers": [], "asOf": None}
    now = time.time()
    if _JP_MOVERS_CACHE["data"] is not None and now < _JP_MOVERS_CACHE["expires"]:
        return _JP_MOVERS_CACHE["data"]
    headers = {"x-api-key": _JQUANTS_API_KEY}
    out = {"status": "unavailable", "gainers": [], "losers": [], "asOf": None}
    try:
        base = datetime.now(TZ_JST)
        latest, latest_date = {}, None
        for back in range(0, 8):
            d = (base - timedelta(days=back)).strftime("%Y-%m-%d")
            latest = _jq_all_for_date(d, headers)
            if latest:
                latest_date = d
                break
        prev = {}
        if latest_date:
            ld = datetime.strptime(latest_date, "%Y-%m-%d")
            for back in range(1, 8):
                prev = _jq_all_for_date((ld - timedelta(days=back)).strftime("%Y-%m-%d"), headers)
                if prev:
                    break
        rows = []
        for code, row in latest.items():
            c, pr = _q_close(row), _q_close(prev.get(code, {})) if prev.get(code) else None
            try:
                c, pr = float(c), float(pr)
            except (TypeError, ValueError):
                continue
            if c < _JP_MOVER_MIN_PRICE or pr <= 0:
                continue
            chg = round((c / pr - 1) * 100, 2)
            if abs(chg) > _MARKET_MOVER_MAX_PCT:   # drop limit-up/halt artifacts (not a clean 1-day signal)
                continue
            s4 = str(code)[:4]
            rows.append({"symbol": s4, "name": _jq_name_for(s4) or s4,
                         "price": round(c, 1), "changePct": chg})
        if rows:
            out = {"status": "live", "asOf": latest_date, "universe": len(rows),
                   "gainers": sorted([r for r in rows if r["changePct"] > 0],
                                     key=lambda r: -r["changePct"])[:15],
                   "losers": sorted([r for r in rows if r["changePct"] < 0],
                                    key=lambda r: r["changePct"])[:15]}
    except Exception:
        pass
    _JP_MOVERS_CACHE["data"] = out
    _JP_MOVERS_CACHE["expires"] = now + (_JP_MOVERS_TTL if out["status"] == "live" else 1800)
    return out

# ── Yahoo!ファイナンス all-market intraday ranking (v10.66, ~20min delayed) ──
# The wider net: covers ALL listed stocks DURING the session (J-Quants is EOD only,
# the moomoo bridge is a few-hundred-name subset). Best-effort scrape of the
# server-rendered ranking JSON; clearly labeled delayed/参考.
_YAHOO_RANK_URL     = "https://finance.yahoo.co.jp/stocks/ranking/{d}?market=all&term=daily"
_YAHOO_MOVERS_CACHE = {"data": None, "expires": 0.0}
_YAHOO_MOVERS_TTL   = 20 * 60   # Yahoo ranking is ~20 min delayed

def _yahoo_rank(direction):
    rows = []
    try:
        html = requests.get(_YAHOO_RANK_URL.format(d=direction),
                            headers={"User-Agent": "Mozilla/5.0"}, timeout=15).text
        m = re.search(r'__PRELOADED_STATE__\s*=\s*(\{.*)', html, re.S)
        raw = m.group(1) if m else ""
        for ch in raw.split('"stockCode":"')[1:]:
            code = ch.split('"', 1)[0]
            nm = re.search(r'"stockName":"([^"]+)"', ch[:400])
            pr = re.search(r'"savePrice":"([\d,.]+)"', ch[:700])
            cg = re.search(r'"changePriceRate":"([+\-]?[\d.]+)"', ch[:900])
            if not (nm and pr and cg):
                continue
            try:
                p, c = float(pr.group(1).replace(",", "")), float(cg.group(1))
            except ValueError:
                continue
            rows.append({"symbol": code[:4], "name": nm.group(1), "price": round(p, 1), "changePct": c})
            if len(rows) >= 20:
                break
    except Exception:
        pass
    return rows

def _yahoo_jp_movers():
    now = time.time()
    if _YAHOO_MOVERS_CACHE["data"] is not None and now < _YAHOO_MOVERS_CACHE["expires"]:
        return _YAHOO_MOVERS_CACHE["data"]
    g, l = _yahoo_rank("up"), _yahoo_rank("down")
    # Yahoo's all-market ranking is ~20min delayed. Stamp the effective DATA time
    # (fetch − delay), not just the fetch time, so the UI can't imply realtime
    # (v10.190 honesty fix — the change% itself is a correct 1-day move vs prev
    # close; only the freshness label was misleading).
    delay_min = 20
    data_iso = datetime.fromtimestamp(now - delay_min * 60, pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = {"status": "live" if (g or l) else "unavailable",
           "provider": "Yahoo!ファイナンス(約20分遅延・全市場)", "asOf": _ai_now_iso(),
           "dataAsOf": data_iso, "delayMin": delay_min,
           "gainers": g[:15], "losers": l[:15]}
    _YAHOO_MOVERS_CACHE["data"] = out
    _YAHOO_MOVERS_CACHE["expires"] = now + (_YAHOO_MOVERS_TTL if out["status"] == "live" else 600)
    return out

@app.route("/api/argus/jp-market-movers")
def api_argus_jp_market_movers():
    """Public: JP whole-market movers. Intraday → Yahoo (~20min, all market);
    after close → J-Quants EOD (authoritative, vs prev close)."""
    if _jp_market_open():
        y = _yahoo_jp_movers()
        if y.get("status") == "live":
            try:
                _decorate_mover_rows((y.get("gainers") or []) + (y.get("losers") or []), "JP")
            except Exception:
                pass
            return jsonify(y)
    out = _jq_market_movers()
    try:
        _decorate_mover_rows((out.get("gainers") or []) + (out.get("losers") or []), "JP")
    except Exception:
        pass
    return jsonify(out)

# ━━━ moomoo realtime JP movers (v10.135) ━━━
# The local bridge sweeps (500-sample ∪ your watchlist) via get_market_snapshot and
# POSTs the movers here — realtime (seconds), but only the swept universe. The mover
# scan then layers Yahoo (~20min, broader market) and J-Quants EOD underneath it.
# Fresh window kept short so a stale sweep never reads as live.
_MOOMOO_JP_MOVERS  = {"rows": [], "ts": 0.0, "asOf": None}
_MOOMOO_MOVERS_TTL = float(os.environ.get("MOOMOO_MOVERS_TTL", "720"))   # 12 min

@app.route("/api/argus/jp-movers-push", methods=["POST"])
def api_argus_jp_movers_push():
    """Bridge → backend: realtime JP movers from the moomoo all-market sweep.
    Admin + HMAC gated (same as quote-push). Non-monetary market data only."""
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    raw = request.get_data() or b""
    sig_ok, sig_reason = _verify_bridge_signature(raw)
    if not sig_ok:
        send_security_alert({"type": "bridge_signature_rejected", "reason": sig_reason,
                             "meta": _client_meta()})
        return jsonify({"error": "signature_invalid", "reason": sig_reason}), 401
    body = request.get_json(silent=True) or {}
    movers = body.get("movers")
    if not isinstance(movers, list):
        return jsonify({"error": "bad_payload", "message": "expected {movers: [...]}"}), 400
    rows = []
    for m in movers[:200]:
        try:
            sym = str(m.get("symbol", "")).strip().upper()
            if not _JP_SYM_RE.match(sym):
                continue
            price = float(m.get("price") or 0)
            chg = float(m.get("changePct") or 0)
            if not (price > 0 and math.isfinite(price) and math.isfinite(chg)):
                continue
            rows.append({"symbol": sym, "price": price, "changePct": round(chg, 4),
                         "volume": int(m.get("volume") or 0), "name": m.get("name")})
        except (TypeError, ValueError):
            continue
    _MOOMOO_JP_MOVERS.update({"rows": rows, "ts": time.time(), "asOf": body.get("asOf")})
    return jsonify({"ok": True, "accepted": len(rows)})

def _moomoo_jp_movers():
    """Fresh moomoo-swept JP movers (realtime; 500-sample ∪ watchlist) or []."""
    if time.time() - (_MOOMOO_JP_MOVERS["ts"] or 0) > _MOOMOO_MOVERS_TTL:
        return []
    return list(_MOOMOO_JP_MOVERS["rows"])

def _scan_jp_market_movers():
    """Whole-market JP movers via a 3-tier waterfall (v10.135): moomoo realtime
    (500-sample ∪ watchlist) → Yahoo (~20min, broader market) → J-Quants EOD
    (post-close backstop). Dedup by symbol (higher tier wins), rank by |move|,
    record + (session-gated) push. Daily dedup per symbol."""
    if not _EVENT_BACKBONE_ENABLED:
        return 0
    _open = _jp_market_open()
    tiers = []   # (source, session, rows) — priority order
    mm = _moomoo_jp_movers()
    if mm:
        tiers.append(("moomoo-rt", "JP_RT", mm))             # realtime, swept universe
    if _open:
        y = _yahoo_jp_movers()
        if y.get("status") == "live":
            tiers.append(("yahoo-jp", "JP_INTRADAY",
                          (y.get("gainers") or []) + (y.get("losers") or [])))
    else:
        # J-Quants EOD is yesterday's data intraday — only meaningful after close,
        # where it's the day's final tape (push is suppressed post-close anyway).
        jq = _jq_market_movers()
        if jq.get("status") == "live":
            tiers.append(("jquants-eod", "JP_EOD",
                          (jq.get("gainers") or []) + (jq.get("losers") or [])))
    if not tiers:
        return 0
    seen, merged = set(), []
    for source, session, rows in tiers:
        for r in rows:
            sym = str(r.get("symbol") or "")
            if not sym or sym in seen:
                continue
            seen.add(sym)
            merged.append((source, session, r))
    merged.sort(key=lambda t: abs(t[2].get("changePct") or 0), reverse=True)
    now, n = datetime.now(pytz.utc), 0
    for source, session, row in merged[:_MARKET_MOVER_NOTIFY_MAX]:
        for trig in argus_events.detect_market_mover(
                row["symbol"], row["changePct"], row["price"],
                min_price=_JP_MOVER_MIN_PRICE, gainer_pct=max(_JP_MOVER_PCT, 10.0)):
            env = _record_event("JP", row["symbol"], trig, now, session,
                                bucket_minutes=1440, source=source)
            if env:
                env["nameJa"] = row.get("name")
                n += 1
    return n


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
                "kind": kind,
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
            "kind": "auction",
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

@app.route("/api/argus/important-events")
def api_argus_important_events():
    """Owner-facing IMPORTANT EVENTS for the Today command area: novice explanation +
    owner-relevance priority + action-until/next-review. No forecast/consensus is
    invented; impact = how strongly markets may move, not a direction."""
    snap = get_events_snapshot()
    events = snap.get("events") or []
    try:
        owner_map = _owner_symbols_cached() or {}
    except Exception:
        owner_map = {}
    wl = ({str(s.get("symbol")).upper() for s in _JP_WATCHLIST}
          | {str(s.get("symbol")).upper() for s in _US_WATCHLIST})
    owner_symbols = wl | {str(k).upper() for k in owner_map}
    held = {str(k).upper() for k, v in owner_map.items()
            if (v or {}).get("ownerState") in ("held", "protected")}
    regime = ((_REGIME_CACHE.get("data") or {}).get("regime") or {}).get("label")
    vix_elevated = False
    try:
        vix = ((get_rates_snapshot().get("vix") or {}).get("latestValue"))
        vix_elevated = isinstance(vix, (int, float)) and vix >= 20
    except Exception:
        pass
    items = argus_important_events.build_important_events(
        events, owner_symbols=owner_symbols, held_symbols=held,
        ctx={"regime": regime, "vixElevated": vix_elevated}, limit=8)
    return jsonify({"status": snap.get("status"), "asOf": snap.get("asOf"),
                    "timezone": "Asia/Tokyo", "engineVersion": "important-events-v1",
                    "count": len(items), "events": items})


# ━━━ Institutional Intelligence + Research Mesh v1 (v10.147) ━━━
# Phase-1 LAYER 2 (public web): collect public METADATA (titles/links/timestamps)
# from an ALLOW-LIST of public financial RSS, normalize to IntelligenceItems, dedup
# story clusters, resolve named institutions, and link to owner symbols. All access
# rights enforced by argus_research_mesh. Collection is admin/scheduled only; the
# public GET serves the cache and never fetches or calls a model. SSRF-hardened.
import socket as _socket
import ipaddress as _ipaddress
from urllib.parse import urlparse as _urlparse
import xml.etree.ElementTree as _ET

# Public RSS allow-list — TARGETED, NOT a generic crawler. Every URL here was
# runtime-validated (HTTP 200 + parseable items with the argus-research UA) before
# shipping; unreachable/dead feeds are NEVER left in production. Each entry is
# (sourceId, label, url); the label is what per-feed logging reports. Reuters's old
# public RSS (reutersagency.com) is dead (301→0 items) and was removed — no name-only
# 0-item placeholder. Strong on finance + macro + company/earnings + official.
_INTEL_FEEDS = [
    # Bloomberg 英語版 — public RSS (markets / economics / technology)
    ("bloomberg_public",     "bbg:markets",      "https://feeds.bloomberg.com/markets/news.rss",      "rss"),
    ("bloomberg_public",     "bbg:economics",    "https://feeds.bloomberg.com/economics/news.rss",    "rss"),
    ("bloomberg_public",     "bbg:technology",   "https://feeds.bloomberg.com/technology/news.rss",   "rss"),
    # Bloomberg 日本語版 — official robots-declared news sitemap (no RSS exists)
    ("bloomberg_jp",         "bbg-jp:news",      "https://www.bloomberg.co.jp/feeds/cojp/sitemap_news.xml", "sitemap"),
    # 日経 web headlines (metadata only). Nikkei has no official public RSS, so this
    # uses a public 3rd-party RSS aggregator of Nikkei's free headlines; links resolve
    # to nikkei.com. PUBLIC_METADATA — titles + links only, no full text.
    ("nikkei_web",           "nikkei:markets",   "https://assets.wor.jp/rss/rdf/nikkei/markets.rdf",  "rss"),
    ("nikkei_web",           "nikkei:business",  "https://assets.wor.jp/rss/rdf/nikkei/business.rdf", "rss"),
    # CNBC public RSS — markets / finance / economy / earnings
    ("cnbc_public",          "cnbc:markets",     "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664", "rss"),
    ("cnbc_public",          "cnbc:finance",     "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=15839135", "rss"),
    ("cnbc_public",          "cnbc:economy",     "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258", "rss"),
    ("cnbc_public",          "cnbc:earnings",    "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=15839263", "rss"),
    # MarketWatch public RSS (Dow Jones public endpoint)
    ("marketwatch_public",   "mw:marketpulse",   "https://feeds.content.dowjones.io/public/rss/mw_marketpulse", "rss"),
    ("marketwatch_public",   "mw:topstories",    "https://feeds.content.dowjones.io/public/rss/mw_topstories",  "rss"),
    # Nasdaq markets
    ("nasdaq_public",        "nasdaq:markets",   "https://www.nasdaq.com/feed/rssoutbound?category=Markets", "rss"),
    # Yahoo Finance headlines (company news volume)
    ("yahoo_finance_public", "yahoo:finance",    "https://finance.yahoo.com/news/rssindex", "rss"),
    # Official / macro — central bank + regulator (public domain)
    ("federal_reserve",      "fed:press",        "https://www.federalreserve.gov/feeds/press_all.xml", "rss"),
    ("sec_press",            "sec:press",        "https://www.sec.gov/news/pressreleases.rss", "rss"),
    # JP official + JP-language macro/markets (v10.191). Whale/大量保有 = EDINET (already
    # integrated as official catalyst); TDnet/株探/みんかぶ/FISCO have no free public RSS
    # (HTML/403) so they stay out of the allow-list. These four ARE public feeds (200):
    ("boj_official",         "boj:whatsnew",     "https://www.boj.or.jp/rss/whatsnew.xml", "rss"),           # 日銀 公表資料
    ("meti_official",        "meti:release",     "https://www.meti.go.jp/ml_index_release_atom.xml", "rss"), # 経産省 (Atom — _parse_rss handles <entry>)
    ("reuters_jp",           "reuters:jp-top",   "https://assets.wor.jp/rss/rdf/reuters/top.rdf", "rss"),    # ロイター日本語 トップ
    ("reuters_jp",           "reuters:jp-biz",   "https://assets.wor.jp/rss/rdf/reuters/business.rdf", "rss"),
    # V11.5.3 watchtower coverage: NHK 経済 (JP professional media) + crypto specialist
    # media (Core Portfolio CRYPTO_BTC_ETH had no news source). Public RSS, metadata only.
    ("nhk_business",         "nhk:keizai",       "https://www3.nhk.or.jp/rss/news/cat5.xml", "rss"),
    ("coindesk",             "coindesk:news",    "https://www.coindesk.com/arc/outboundfeeds/rss/", "rss"),
    ("cointelegraph",        "cointelegraph:news", "https://cointelegraph.com/rss", "rss"),
]
_INTEL_STORE = []                  # capped list of recent IntelligenceItems (metadata only)
_INTEL_STORE_MAX = 400
_INTEL_LAST = {"ts": 0.0, "collected": 0, "perSource": {}}
_INTEL_FETCH_MAX_BYTES = 1_500_000
_INTEL_STORE_FILE = "/tmp/argus_intel_store.json"   # §27 persistence (survives restarts)


def _intel_translate_titles(cap=40):
    """Attach a Japanese title (titleJa) to institutional items so the C.A.O.S. UI
    shows translated headlines. Runs ONLY at collection time (admin/cron) so the
    public GET never triggers a model call. JP-language items keep their own title;
    English ones are translated once (cheap Gemini flash) and never re-translated.
    Bounded per run; best-effort (falls back to the English title)."""
    pending_items, pending_titles = [], []
    for it in _INTEL_STORE:
        if not it.get("institutionId") or it.get("titleJa"):
            continue
        if it.get("language") == "ja":
            it["titleJa"] = it.get("title")
            continue
        if len(pending_titles) < cap:
            pending_items.append(it)
            pending_titles.append(it.get("title", ""))
    if pending_titles:
        tr = _translate_headlines_ja(pending_titles)
        for i, it in enumerate(pending_items):
            it["titleJa"] = tr.get(i) or it.get("title")


def _intel_persist():
    """Atomically persist the intel store (metadata only — rights already enforced,
    no full text) so a process restart doesn't drop to WARMING. Best-effort."""
    try:
        tmp = f"{_INTEL_STORE_FILE}.{os.getpid()}.tmp"
        with open(tmp, "w") as f:
            json.dump({"store": _INTEL_STORE, "last": _INTEL_LAST,
                       "missed": _MISSED_INTEL[:200], "aliasOverlay": _INST_ALIAS_OVERLAY[:500]},
                      f, ensure_ascii=False, default=str)
        os.replace(tmp, _INTEL_STORE_FILE)
    except Exception:
        pass


def _intel_restore():
    """Load a previously persisted intel store at startup (best-effort)."""
    try:
        with open(_INTEL_STORE_FILE, "r") as f:
            blob = json.load(f)
        items = blob.get("store") or []
        if isinstance(items, list):
            _INTEL_STORE[:] = items[:_INTEL_STORE_MAX]
            last = blob.get("last")
            if isinstance(last, dict):
                _INTEL_LAST.update(last)
        # v10.198: restore missed-intel log + re-apply the owner alias overlay (guard
        # with .get defaults so older snapshots without these keys still load).
        missed = blob.get("missed")
        if isinstance(missed, list):
            _MISSED_INTEL[:] = missed[:200]
        overlay = blob.get("aliasOverlay")
        if isinstance(overlay, list):
            _INST_ALIAS_OVERLAY[:] = overlay[:500]
            for e in overlay:
                try:
                    argus_research_mesh.register_institution_alias(e.get("institutionId"), e.get("alias"))
                except Exception:
                    pass
    except Exception:
        pass


def _ssrf_safe_url(url):
    """Block non-public targets (SSRF, §23): https only, public host, no private IPs."""
    try:
        u = _urlparse(url)
        if u.scheme != "https" or not u.hostname:
            return False
        for fam, _, _, _, sa in _socket.getaddrinfo(u.hostname, 443, proto=_socket.IPPROTO_TCP):
            ip = _ipaddress.ip_address(sa[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
        return True
    except Exception:
        return False


def _fetch_public_text(url):
    """Size/timeout/redirect-limited fetch of public content (data, never trusted as
    instructions). Returns text or None."""
    if not _ssrf_safe_url(url):
        return None
    try:
        r = requests.get(url, timeout=12, allow_redirects=True,
                         headers={"User-Agent": "argus-research/1.0"}, stream=True)
        if r.status_code != 200:
            return None
        # Validate redirect target too + cap size.
        if not _ssrf_safe_url(r.url):
            return None
        chunks, total = [], 0
        for c in r.iter_content(16384):
            total += len(c)
            if total > _INTEL_FETCH_MAX_BYTES:
                break
            chunks.append(c)
        return b"".join(chunks).decode("utf-8", "replace")
    except Exception:
        return None


def _parse_rss(xml_text, source_id, now_iso):
    """Public RSS/Atom → raw intel records (title/link/pubDate only). Strips any
    embedded markup; content is DATA, not instructions (§23)."""
    out = []
    try:
        root = _ET.fromstring(xml_text)
    except Exception:
        return out
    for item in root.iter():
        tag = item.tag.lower().rsplit("}", 1)[-1]
        if tag not in ("item", "entry"):
            continue
        title = link = pub = ""
        for ch in item:
            ct = ch.tag.lower().rsplit("}", 1)[-1]
            txt = (ch.text or "").strip()
            if ct == "title":
                title = re.sub(r"<[^>]+>", "", txt)[:300]
            elif ct == "link":
                link = (ch.attrib.get("href") or txt)[:600]
            elif ct in ("pubdate", "published", "updated"):
                pub = txt[:40]
        if title:
            out.append({"sourceId": source_id, "title": title, "canonicalUrl": link,
                        "publishedAt": pub or None, "firstDetectedAt": now_iso, "fetchedAt": now_iso})
    return out


def _parse_news_sitemap(xml_text, source_id, now_iso, language="en", limit=60):
    """Google-News sitemap (<url><news:news><news:title>) → raw intel records. This
    is the official, robots.txt-declared public-metadata path for outlets that no
    longer publish RSS (e.g. Bloomberg 日本語版). Titles/links/dates only; markup
    stripped; content is DATA, not instructions (§23)."""
    out = []
    try:
        root = _ET.fromstring(xml_text)
    except Exception:
        return out
    for url in root.iter():
        if url.tag.lower().rsplit("}", 1)[-1] != "url":
            continue
        loc = title = pub = ""
        for el in url.iter():
            lt = el.tag.lower().rsplit("}", 1)[-1]
            txt = (el.text or "").strip()
            if lt == "loc" and not loc:
                loc = txt[:600]
            elif lt == "title" and not title:
                title = re.sub(r"<[^>]+>", "", txt)[:300]
            elif lt == "publication_date" and not pub:
                pub = txt[:40]
        if title:
            out.append({"sourceId": source_id, "title": title, "canonicalUrl": loc,
                        "publishedAt": pub or None, "language": language,
                        "firstDetectedAt": now_iso, "fetchedAt": now_iso})
        if len(out) >= limit:
            break
    return out


# ── §x Entity profiles (v10.173) — the ASSOCIATION engine ────────────────────
# Per-stock business + relationship metadata so a headline that names a RELATED entity
# (an investee / holding / supplier / customer / peer / commodity) — not the stock itself —
# still links to it ("OpenAI IPO delayed" → 9984; a big LNG plant order → 6330). The link
# is a CANDIDATE only: it is handed to the AI WITH the relationship explained, and the AI
# judges materiality — it never auto-fires a signal (same precision model as corroboration).
_ENTITY_PROFILES = {}                 # symbol -> profile
_ENTITY_PROFILES_META = {"asOf": None}
_ENTITY_PROFILES_FILE = "/tmp/argus_entity_profiles.json"          # AI-generated (runtime)
_ENTITY_PROFILE_SEED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "entity_profiles_seed.json")  # committed web-verified seed
_ENTITY_PROFILES_GH_PATH = "entity_profiles.json"  # durable store in the Layer-2B private repo
_ENTITY_PROFILE_TTL = 7 * 24 * 3600   # AI-generated profiles refresh weekly

# Hand-seeded flagship anchors (guaranteed-correct; the AI generator fills/refreshes the
# rest of the watchlist, and never overwrites a seed). 9984 + 6330 are the owner's examples.
_ENTITY_PROFILE_SEED = {
    "9984": {"businessJa": "投資持株会社。Vision Fund等を通じAI/テック企業に大型投資し、半導体IPのArmを連結子会社に持つ。",
             "sector": "tech-investment", "themes": ["ai_compute", "semis", "ipo", "tech-valuations"],
             "relatedEntities": [
                 {"name": "OpenAI", "relationJa": "大型出資先。IPO・評価額の変化がSBGの保有評価損益に直結", "type": "investee"},
                 {"name": "Arm", "relationJa": "連結子会社(半導体IP)。Arm株価・業績がSBGに反映", "type": "subsidiary"},
                 {"name": "Nvidia", "relationJa": "AI半導体の象徴。AI投資テーマの地合いに連動", "type": "theme"},
                 {"name": "TSMC", "relationJa": "Armエコシステム・半導体製造の代理", "type": "theme"},
                 {"name": "Alibaba", "relationJa": "歴史的な大量保有先", "type": "holding"}],
             "peers": [],
             "keywords": ["softbank", "ソフトバンク", "9984", "openai", "オープンai", "chatgpt", "arm",
                          "アーム", "vision fund", "ビジョンファンド", "alibaba", "アリババ", "孫正義", "masayoshi son"]},
    "6330": {"businessJa": "総合エンジニアリング会社。石油・ガス・LNG・アンモニア・肥料などのプラントを設計・建設(EPC)。",
             "sector": "plant-epc", "themes": ["energy-capex", "lng", "ammonia", "oil_gas", "脱炭素"],
             "relatedEntities": [
                 {"name": "LNG", "relationJa": "主要案件領域。LNG設備投資・大型受注が業績に直結", "type": "commodity"},
                 {"name": "アンモニア", "relationJa": "脱炭素燃料プラントの需要テーマ", "type": "theme"},
                 {"name": "日揮", "relationJa": "同業大手(JGC)。プラント受注環境の連想", "type": "peer"},
                 {"name": "千代田化工", "relationJa": "同業。プラントEPC市況の連想", "type": "peer"}],
             "peers": ["1963", "6366"],
             "keywords": ["東洋エンジニアリング", "6330", "toyo engineering", "プラント", "epc", "lng",
                          "アンモニア", "肥料", "脱炭素", "日揮", "jgc", "千代田化工", "プラント受注"]},
}


def _kw_match(k, t):
    """Boundary-aware keyword match. ASCII terms (>=3 chars) need a word boundary so 'arm'
    doesn't hit 'alarm' and 'meta' doesn't hit 'metal'; JP/mixed terms (>=2) use substring."""
    k = (k or "").lower().strip()
    if not k:
        return False
    if re.fullmatch(r"[a-z0-9 .&'-]+", k):
        return len(k) >= 3 and re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", t) is not None
    return len(k) >= 2 and k in t


def _kw_hit(kw, t):
    """Match a keyword that may be MULTI-WORD. Japanese has no spaces, so a space-joined
    term like '南鳥島 レアアース' can never substring-match '南鳥島沖のレアアース' — instead
    require ALL parts to appear (AND), which catches the relationship without the join."""
    parts = (kw or "").split()
    if len(parts) <= 1:
        return _kw_match(kw, t)
    return all(_kw_match(p, t) for p in parts)


def _entity_alias_match(name, t):
    """A relatedEntity name may pack aliases ("Berkshire Hathaway / バークシャー / バフェット") —
    match ANY '/'-separated alias (but not '・', which is part of a single JP name)."""
    return any(_kw_hit(part.strip(), t) for part in re.split(r"[/／]", name or ""))


def _entity_link(title):
    """[{symbol, via, term, relationJa}] for watchlist stocks whose profile keywords appear
    in the title. via='entity' (a related entity → carries relationJa) or 'name' (own name)."""
    t = (title or "").lower()
    out = []
    for sym, prof in _ENTITY_PROFILES.items():
        matched = next((kw for kw in (prof.get("keywords") or []) if _kw_hit(kw, t)), None)
        if not matched:
            continue
        rel = next((e for e in (prof.get("relatedEntities") or []) if _entity_alias_match(e.get("name"), t)), None)
        nm = (prof.get("name") or "").lower()
        own = _kw_hit(sym, t) or sym.lower() in (matched or "").lower() or (matched or "").lower() in nm
        if rel:                                   # a known related entity → carries the why
            out.append({"symbol": sym, "via": "entity", "term": rel.get("name"), "relationJa": rel.get("relationJa")})
        elif own:                                 # the stock's own name / ticker
            out.append({"symbol": sym, "via": "name", "term": sym, "relationJa": None})
        else:                                     # a theme keyword (e.g. 南鳥島 レアアース → 6330)
            out.append({"symbol": sym, "via": "theme", "term": matched, "relationJa": None})
    return out


# CAOS association audit — dedup so the same lead isn't recorded on every refresh.
_CAOS_AUDIT_SEEN = {}          # sym -> (signature, expires)
_CAOS_AUDIT_DEDUP_SEC = 30 * 60

def _caos_audit_maybe_record(sym, best, event_id=None, event_after_move=False):
    """Record WHY this symbol was associated with a lead (metadata only), deduped per
    symbol. A single-source association stays a candidate — argus_caos_audit enforces
    that; here we only supply honest inputs (never fabricate timing)."""
    if not best:
        return
    now = time.time()
    sig = (best.get("via"), best.get("term"), best.get("corroboration"), (best.get("titleJa") or "")[:48])
    hit = _CAOS_AUDIT_SEEN.get(sym)
    if hit and hit[0] == sig and now < hit[1]:
        return
    _CAOS_AUDIT_SEEN[sym] = (sig, now + _CAOS_AUDIT_DEDUP_SEC)
    link_type = {"name": "direct_mention", "entity": "entity_profile"}.get(best.get("via"), "theme")
    sid = best.get("_sid")
    try:
        argus_caos_audit.record_association(
            symbol=sym, event_id=event_id, link_type=link_type,
            matched_terms=[best["term"]] if best.get("term") else [],
            source_family=argus_research_mesh.source_family(sid),
            source_tier=argus_research_mesh.source_tier(sid),
            corroboration_level=best.get("corroboration") or "single",
            why_ja=best.get("relationJa") or best.get("titleJa") or "",
            event_after_move=event_after_move, now_iso=_ai_now_iso())
    except Exception:
        pass   # audit is best-effort; never breaks the association path


def _caos_catalyst_for(sym, news_items, intel_items):
    """Best C.A.O.S./association-linked news for a symbol — the candidate LEAD behind a move,
    derived from news + entity relationships instead of '原因未確認'. Corroborated preferred,
    then an entity-relationship link (the non-obvious association). A candidate, not a cause."""
    sym = str(sym).upper()
    rank = {"official": 0, "corroborated": 1, "single": 2}
    best = None
    for n in list(news_items) + list(intel_items):
        blob = (n.get("headline") or n.get("title") or "") + " " + (n.get("headlineJa") or n.get("titleJa") or "")
        link = next((m for m in _entity_link(blob) if m["symbol"] == sym), None)
        # v10.190: a JP per-symbol headline (fetched by company name) carries a
        # symbolHint — treat it as a direct name link even if the alias table misses.
        if not link and str(n.get("symbolHint") or "").upper() == sym:
            link = {"via": "name", "term": None, "relationJa": None}
        if not link:
            continue
        corr = n.get("corroboration") or "single"
        cand = {"titleJa": (n.get("headlineJa") or n.get("titleJa") or n.get("headline") or n.get("title") or "")[:120],
                "via": link.get("via"), "term": link.get("term"),
                "relationJa": link.get("relationJa"), "corroboration": corr,
                # V11.5.3: carry the timestamp so the freshness gate can demote an
                # association lead built on an OLD story (past ≠ today's lead).
                "publishedAt": n.get("publishedAt") or n.get("datetime") or n.get("firstDetectedAt"),
                "_sid": n.get("sourceId") or n.get("source")}   # kept for the audit trail
        if (best is None or rank.get(corr, 2) < rank.get(best["corroboration"], 2)
                or (rank.get(corr, 2) == rank.get(best["corroboration"], 2)
                    and link.get("via") == "entity" and best.get("via") != "entity")):
            best = cand
    _caos_audit_maybe_record(sym, best)   # populate /caos/audit for real (deduped)
    return best


# ── JP single-stock Japanese-language headlines (v10.190) ─────────────────────
# The intel allow-list is macro/global (Bloomberg/CNBC/Nikkei-markets); it rarely
# NAMES an individual JP company, so the downside association ("なぜ落ちた?") had no
# Japanese headline to match and every drop read as "原因未確認". This targeted fetch
# pulls per-symbol JP headlines from Google News' public RSS search (a company-name
# query), normalized through the same _parse_rss path (titles/links/dates only;
# content is DATA, not instructions §23). Cached per symbol; best-effort; never raises.
_JP_STOCK_NEWS_CACHE = {}          # sym -> {"expires": float}
_JP_STOCK_NEWS_TTL   = 30 * 60

def _google_news_jp_rss(query):
    try:
        from urllib.parse import quote
        url = ("https://news.google.com/rss/search?q=" + quote(query)
               + "&hl=ja&gl=JP&ceid=JP:ja")
        xml = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8).text
        return _parse_rss(xml, "google_news_jp", _ai_now_iso())
    except Exception:
        return []

def _jp_stock_news_intel(pairs):
    """For (symbol, jp_name) pairs, fetch Japanese headlines that NAME the company
    and push them into _INTEL_STORE so the C.A.O.S. association can find a lead.
    Returns count pushed. Cached per symbol (30 min)."""
    now = time.time()
    pushed = 0
    seen = {(it.get("title") or "") for it in _INTEL_STORE}
    for sym, name in pairs:
        sym = str(sym).upper()
        nm = (name or "").strip()
        if not sym or not nm:
            continue
        c = _JP_STOCK_NEWS_CACHE.get(sym)
        if c and now < c["expires"]:
            continue
        _JP_STOCK_NEWS_CACHE[sym] = {"expires": now + _JP_STOCK_NEWS_TTL}
        for r in _google_news_jp_rss(f'"{nm}" (株価 OR 決算 OR 業績 OR 急落 OR 下落 OR 材料)')[:6]:
            t = r.get("title") or ""
            if not t or t in seen:
                continue
            seen.add(t)
            r = dict(r); r["symbolHint"] = sym; r["lang"] = "ja"; r["corroboration"] = "single"
            r.setdefault("intelligenceId", hashlib.md5(
                f"google_news_jp|{r.get('canonicalUrl')}|{t}".encode()).hexdigest()[:16])
            _INTEL_STORE.append(r)
            pushed += 1
    if len(_INTEL_STORE) > _INTEL_STORE_MAX:
        del _INTEL_STORE[:len(_INTEL_STORE) - _INTEL_STORE_MAX]
    return pushed


_ENTITY_PROFILE_SYSTEM = (
    "You build a compact profile for an investing ASSOCIATION engine: given a stock, list the "
    "EXTERNAL entities whose news would plausibly move it. HONESTY: only real, well-established, "
    "MATERIAL relationships — never invent. Return STRICT JSON: {\"businessJa\": str (1-2 JP "
    "sentences), \"sector\": str, \"themes\": [str], \"relatedEntities\": [{\"name\": str, "
    "\"relationJa\": str (why its news moves the stock), \"type\": str}], \"peers\": [str], "
    "\"keywords\": [str] (JP+EN headline-scan terms: name aliases + relatedEntity names + theme "
    "terms; tight, NOT over-broad common words)}."
)


def _entity_profile_make(sym, name="", market=""):
    """Generate ONE profile via GPT and store it (source='ai'). Returns the profile or None.
    `market` (JP|US) sets the prompt context — needed for device-added stocks the backend
    watchlist doesn't know. Never raises."""
    sym = str(sym).strip().upper()
    if not sym:
        return None
    m = str(market or "").upper()
    if m in ("JP", "日本株"):
        mkt = "日本株"
    elif m in ("US", "米国株"):
        mkt = "米国株"
    else:
        mkt = "日本株" if sym in {x["symbol"] for x in _JP_WATCHLIST} else "米国株"
    pr = _openai_prose(f"銘柄: {sym} {name or sym}({mkt})。この銘柄の連想プロフィールをJSONで返せ。",
                       max_out=700, system=_ENTITY_PROFILE_SYSTEM)
    if not pr or not pr.get("businessJa"):
        return None
    prof = {
        "symbol": sym, "name": str(name or sym)[:60],
        "businessJa": str(pr.get("businessJa") or "")[:300], "sector": str(pr.get("sector") or "")[:60],
        "themes": [str(t)[:40] for t in (pr.get("themes") or [])][:8],
        "relatedEntities": [{"name": str(e.get("name") or "")[:60], "relationJa": str(e.get("relationJa") or "")[:140],
                             "type": str(e.get("type") or "")[:30]}
                            for e in (pr.get("relatedEntities") or []) if e.get("name")][:8],
        "peers": [str(p)[:20] for p in (pr.get("peers") or [])][:6],
        "keywords": [str(k)[:40] for k in (pr.get("keywords") or [])][:24],
        "source": "ai", "ts": time.time(), "generatedAt": _ai_now_iso(),
    }
    _ENTITY_PROFILES[sym] = prof
    _ENTITY_PROFILES_META["asOf"] = _ai_now_iso()
    return prof


def _entity_profile_generate(symbols=None):
    """Admin/cron — AI-generate missing/stale watchlist profiles (skips seeds/owner & fresh)."""
    wl = {x["symbol"]: x["name"] for x in (_JP_WATCHLIST + _US_WATCHLIST)}
    syms = symbols or list(wl.keys())
    now = time.time()
    made = 0
    for sym in syms[:12]:
        prev = _ENTITY_PROFILES.get(sym)
        if prev and prev.get("source") in ("seed", "owner"):   # never overwrite hand seeds or owner edits
            continue
        if prev and (now - prev.get("ts", 0) < _ENTITY_PROFILE_TTL):
            continue
        if _entity_profile_make(sym, wl.get(sym, sym)):
            made += 1
    _entity_profile_persist()
    return {"generated": made, "total": len(_ENTITY_PROFILES)}


def _entity_profile_persist():
    # persist AI-generated + OWNER edits (seeds are committed, not persisted here)
    keep = {k: v for k, v in _ENTITY_PROFILES.items() if v.get("source") in ("ai", "owner")}
    blob = {"profiles": keep, "asOf": _ENTITY_PROFILES_META.get("asOf")}
    try:                                             # /tmp = fast cache (survives restart)
        tmp = f"{_ENTITY_PROFILES_FILE}.{os.getpid()}.tmp"
        with open(tmp, "w") as f:
            json.dump(blob, f, ensure_ascii=False, default=str)
        os.replace(tmp, _ENTITY_PROFILES_FILE)
    except Exception:
        pass
    if _layer2b_store_configured():                  # private repo = DURABLE across redeploys
        try:
            _gh_private_put(_ENTITY_PROFILES_GH_PATH, json.dumps(blob, ensure_ascii=False, default=str),
                            "argus: entity profiles (owner/ai overrides)")
        except Exception:
            pass


def _entity_profile_restore():
    for k, v in _ENTITY_PROFILE_SEED.items():        # hand-seed fallback (always)
        _ENTITY_PROFILES[k] = dict(v, symbol=k, source="seed")
    try:                                             # committed web-verified seed (authoritative)
        with open(_ENTITY_PROFILE_SEED_FILE) as f:
            for k, v in (json.load(f).get("profiles") or {}).items():
                _ENTITY_PROFILES[k] = dict(v, symbol=k, source="seed")
    except Exception:
        pass
    def _apply(blob):
        # OWNER edits override anything (incl. seed); AI overrides only non-seed.
        for k, v in (blob.get("profiles") or {}).items():
            if v.get("source") == "owner" or _ENTITY_PROFILES.get(k, {}).get("source") != "seed":
                _ENTITY_PROFILES[k] = v
        if blob.get("asOf"):
            _ENTITY_PROFILES_META["asOf"] = blob["asOf"]
    if _layer2b_store_configured():                  # DURABLE store first (survives redeploys)
        try:
            content, _ = _gh_private_get(_ENTITY_PROFILES_GH_PATH)
            if content:
                _apply(json.loads(content))
        except Exception:
            pass
    try:                                             # /tmp fast cache (empty after a redeploy)
        with open(_ENTITY_PROFILES_FILE) as f:
            _apply(json.load(f))
    except Exception:
        pass


# ── §y Buy candidates (v10.177) — "本日の注目候補" ───────────────────────────
# Elevate the raw surge feed into a HIGH-BAR, AI-screened watch list of non-watchlist
# names with a genuine constructive setup (catalyst/theme-driven via the association
# engine, not pure momentum). Decision-support only — never advice, never auto-trade;
# most days few or zero qualify.
_BUY_CANDIDATES = {"items": [], "asOf": None}
_BUY_CANDIDATES_FILE = "/tmp/argus_buy_candidates.json"

_BUY_CANDIDATE_SYSTEM = (
    "You screen TODAY's market movers for an individual investor and flag ONLY names where NOW looks "
    "like a genuinely GOOD ENTRY to BUY — a constructive, still-actionable setup (not a pure momentum / "
    "blow-off / already-extended spike you'd be chasing). This is DECISION-SUPPORT, NOT investment "
    "advice and NOT a guarantee. Be STRICT: most days only a few or ZERO qualify; omit weak ones "
    "entirely. Prefer names with an identifiable catalyst/theme driver (given as driverJa) and where "
    "the risk/reward of entering today is favorable. conviction = how strong a BUY-NOW this is (0..1). "
    "Return STRICT JSON: {\"candidates\": "
    "[{\"symbol\": str, \"market\": str, \"thesisJa\": str (why constructive — read the driver), "
    "\"entryJa\": str (what to CONFIRM before buying: 押し目/出来高/地合い等), \"riskJa\": str (what "
    "kills the thesis), \"conviction\": number 0..1}]}. Use ONLY the given symbols; never invent one."
)


def _mover_universe(cap=14):
    """Today's gainers beyond the watchlist (JP + US), the candidate pool to screen."""
    wl = {s["symbol"].upper() for s in (_JP_WATCHLIST + _US_WATCHLIST)}
    out = []
    try:
        for m in (_jq_market_movers().get("gainers") or [])[:10]:
            sym = str(m.get("symbol") or "").upper()
            if sym and sym not in wl and (m.get("changePct") or 0) > 0:
                out.append({"symbol": sym, "name": m.get("name") or sym, "market": "JP",
                            "changePct": m.get("changePct")})
    except Exception:
        pass
    try:
        us = sorted([r for r in (_moomoo_us_movers() or []) if (r.get("changePct") or 0) > 0],
                    key=lambda r: -(r.get("changePct") or 0))[:10]
        for m in us:
            sym = str(m.get("symbol") or "").upper()
            if sym and sym not in wl:
                out.append({"symbol": sym, "name": m.get("name") or sym, "market": "US",
                            "changePct": m.get("changePct")})
    except Exception:
        pass
    return out[:cap]


def _buy_candidates_generate(limit=4):
    """Admin/cron — screen today's movers into high-conviction buy candidates (>=0.6)."""
    uni = _mover_universe()
    if not uni:
        return {"generated": 0, "total": len(_BUY_CANDIDATES["items"])}
    try:
        news_rel = [n for n in (get_market_news().get("items") or []) if n.get("relevant")]
    except Exception:
        news_rel = []
    intel = list(_INTEL_STORE)[:60]
    rows = []
    for m in uni:
        lead = _caos_catalyst_for(m["symbol"], news_rel, intel)   # the driver, via association
        rows.append({"symbol": m["symbol"], "name": m.get("name"), "market": m.get("market"),
                     "changePct": m.get("changePct"),
                     "driverJa": (lead.get("titleJa") if lead else None)})
    try:
        posture = (get_action_labels().get("marketPosture") or {}).get("label")
    except Exception:
        posture = None
    pr = _openai_prose(f"地合い: {posture}\n本日の上昇銘柄(候補母集団):\n"
                       + json.dumps(rows, ensure_ascii=False)
                       + "\nこの中から、買い候補として注目に値するものだけを厳選して返せ(無理に出さない)。",
                       max_out=900, system=_BUY_CANDIDATE_SYSTEM)
    by = {r["symbol"]: r for r in rows}
    out = []
    for c in ((pr or {}).get("candidates") or []):
        sym = str(c.get("symbol") or "").upper()
        if sym not in by:                                   # never accept an invented symbol
            continue
        conv = c.get("conviction")
        if not isinstance(conv, (int, float)) or conv < 0.6:
            continue
        src = by[sym]
        out.append({"symbol": sym, "name": src.get("name") or sym,
                    "market": c.get("market") or src.get("market"), "changePct": src.get("changePct"),
                    "thesisJa": str(c.get("thesisJa") or "")[:240], "entryJa": str(c.get("entryJa") or "")[:160],
                    "riskJa": str(c.get("riskJa") or "")[:160], "conviction": round(float(conv), 2),
                    "driverJa": src.get("driverJa")})
    out.sort(key=lambda x: -x["conviction"])
    _BUY_CANDIDATES["items"] = out[:limit]
    _BUY_CANDIDATES["asOf"] = _ai_now_iso()
    _buy_candidates_persist()
    return {"generated": len(out[:limit]), "total": len(out)}


def _buy_candidates_persist():
    try:
        tmp = f"{_BUY_CANDIDATES_FILE}.{os.getpid()}.tmp"
        with open(tmp, "w") as f:
            json.dump(_BUY_CANDIDATES, f, ensure_ascii=False, default=str)
        os.replace(tmp, _BUY_CANDIDATES_FILE)
    except Exception:
        pass


def _buy_candidates_restore():
    try:
        with open(_BUY_CANDIDATES_FILE) as f:
            blob = json.load(f)
        if isinstance(blob, dict) and isinstance(blob.get("items"), list):
            _BUY_CANDIDATES["items"] = blob["items"]
            _BUY_CANDIDATES["asOf"] = blob.get("asOf")
    except Exception:
        pass


def _intel_link_assets(title):
    """Tag an item with watchlist symbols linked to the public title — by direct name/ticker
    AND (v10.173) by entity-profile RELATIONSHIP (a headline naming a related entity)."""
    t = (title or "").lower()
    assets = []
    for s in ({x["symbol"] for x in _JP_WATCHLIST} | {x["symbol"] for x in _US_WATCHLIST}):
        if _kw_match(s, t) and s.upper() not in assets:
            assets.append(s.upper())
    for name, sym in [("nvidia", "NVDA"), ("micron", "MU"), ("apple", "AAPL"), ("tesla", "TSLA"),
                      ("meta", "META"), ("softbank", "9984"), ("mitsubishi", "8058")]:
        if _kw_match(name, t) and sym not in assets:
            assets.append(sym)
    for m in _entity_link(t):
        if m["symbol"] not in assets:
            assets.append(m["symbol"])
    return assets


def collect_institutional_intel():
    """Admin/scheduled: fetch the allow-listed public feeds, normalize + dedup, store
    metadata-only IntelligenceItems. Reports PER-FEED counts (fetched + new) and any
    feed that returned nothing, so the market-watch log proves what was ingested.
    Never called by a public GET."""
    now_iso = _ai_now_iso()
    # raw per-symbol discovery rows (jp/us stock news, article probes) carry no
    # intelligenceId — a hard i["intelligenceId"] here crashed the WHOLE collect
    # whenever one was in the store (silent 24/7-patrol killer). Tolerate them.
    seen = {(i.get("intelligenceId") or f"t:{i.get('title') or ''}") for i in _INTEL_STORE}
    per_feed, per_source, total_new = [], {}, 0
    for sid, label, url, kind in _INTEL_FEEDS:
        txt = _fetch_public_text(url)
        if not txt:
            rows = []
        elif kind == "sitemap":
            rows = _parse_news_sitemap(txt, sid, now_iso, language=("ja" if "co.jp" in url else "en"))
        else:
            rows = _parse_rss(txt, sid, now_iso)
        src_lang = (argus_research_mesh.SOURCE_RIGHTS.get(sid) or {}).get("language", "en")
        new = 0
        for raw in rows:
            raw.setdefault("language", src_lang)           # ja for nikkei/bbg-jp feeds
            raw["linkedAssets"] = _intel_link_assets(raw.get("title", ""))
            item = argus_research_mesh.normalize_item(raw)
            if item["intelligenceId"] in seen:
                continue
            seen.add(item["intelligenceId"])
            _INTEL_STORE.insert(0, item)
            new += 1
        total_new += new
        per_source[sid] = per_source.get(sid, 0) + len(rows)
        per_feed.append({"feed": label, "source": sid, "fetched": len(rows),
                         "new": new, "ok": bool(txt) and len(rows) > 0})
    del _INTEL_STORE[_INTEL_STORE_MAX:]
    _intel_translate_titles()                          # attach titleJa (cron-time only)
    # v10.201: bias toward the owner's held/incident/watchlist names. generate_queries
    # (previously unused) builds the targeted query PLAN, and matching collected intel
    # gets an importance boost so those names surface first in the brief/rankings.
    query_plan = []
    try:
        watch = _intel_watchlist_symbols()
        incident = []
        try:
            incident = [str(i.get("symbol")).upper() for i in (get_downside_incidents().get("incidents") or [])]
        except Exception:
            incident = []
        query_plan = argus_research_mesh.generate_queries(
            {"heldOrIncident": incident + watch, "watchlist": watch, "themes": []}, max_queries=12)
        inc_set, watch_set = set(incident), set(watch)
        for it in _INTEL_STORE:
            la = {str(a).upper() for a in (it.get("linkedAssets") or [])}
            if la & inc_set:
                it["importance"] = max(float(it.get("importance") or 0), 0.9)
            elif la & watch_set:
                it["importance"] = max(float(it.get("importance") or 0), 0.6)
    except Exception:
        pass
    _INTEL_LAST.update({"ts": time.time(), "collected": total_new,
                        "perSource": per_source, "perFeed": per_feed,
                        "queryPlan": query_plan[:12]})
    _intel_persist()                                   # §27 survive restarts
    # one-line, human-readable summary echoed by the cron (どのfeedから何件)
    summary = " | ".join(f"{f['feed']}:{f['fetched']}(+{f['new']})" for f in per_feed)
    failed = [f["feed"] for f in per_feed if not f["ok"]]
    return {"collected": total_new, "stored": len(_INTEL_STORE),
            "feeds": len(_INTEL_FEEDS), "failedFeeds": failed,
            "perFeed": per_feed, "perSource": per_source, "summary": summary}


def _intel_clusters():
    return argus_research_mesh.cluster_items(list(_INTEL_STORE))


# ━━━ V11.6.0 Institutional Intelligence Layer ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Formal InstitutionalSignal records built (cached-only) from the intel mesh:
# stance / claim type / direct-vs-background / owner-readable why (JA) / action
# implication that is NEVER a trade. Public GETs read the in-memory store only.

def _owner_asset_set():
    base = {"GLD", "TLT", "XLRE", "BTC", "ETH", "USDJPY"}
    try:
        return set(_intel_watchlist_symbols()) | base
    except Exception:
        return base


def _institutional_signals(symbol=None, cap=40):
    now_iso = _ai_now_iso()
    sigs = argus_institutional_intel.build_signals(
        list(_INTEL_STORE)[:400], owner_assets=_owner_asset_set(),
        now_iso=now_iso, cap=cap)
    if symbol:
        symu = str(symbol).upper()
        sigs = [s for s in sigs if symu in (s.get("affectedAssets") or [])
                or symu in (s.get("tickers") or [])]
    # v11.7.0 owner rule: news headlines are NEVER shown in raw English — attach
    # the Japanese-first display title (cached JA or JP fallback) and queue the
    # original for the admin translate cron. Cache-read only on this public path.
    _news_ja_restore_once()
    for s in sigs:
        d = _news_decorate(s.get("headline") or "", s.get("sourceName") or "")
        s["displayTitleJa"] = d["displayTitleJa"]
        s["titleOriginal"] = d["titleOriginal"]
        s["translationStatus"] = d["translationStatus"]
    return sigs


@app.route("/api/argus/institutional-intel/signals")
def api_argus_institutional_intel_signals():
    """Public cached-only: ranked institutional signals (+regime themes). No fetch,
    no LLM. ?symbol= narrows to one asset. Context, never trade instructions."""
    try:
        limit = max(1, min(int(request.args.get("limit") or 20), 40))
    except Exception:
        limit = 20
    sigs = _institutional_signals(symbol=request.args.get("symbol"), cap=40)
    return jsonify({
        "schemaVersion": "institutional-intel-signals-v1", "asOf": _ai_now_iso(),
        "count": len(sigs[:limit]), "signals": sigs[:limit],
        "regimeThemes": argus_institutional_intel.regime_themes(sigs),
        "handoffSummary": argus_institutional_intel.handoff_summary(sigs[:20]),
        "disclaimerJa": argus_institutional_intel.DISCLAIMER_JA,
        "disclaimerEn": argus_institutional_intel.DISCLAIMER_EN})


@app.route("/api/argus/institutional-intel/status")
def api_argus_institutional_intel_status():
    """Public observability: registry (enabled/disabled with reasons), fetch stats
    from the existing 24/7 collector, today's signal counts. Not a red alert unless
    ingestion is actually dead."""
    now_iso = _ai_now_iso()
    sigs = _institutional_signals(cap=40)
    today = now_iso[:10]
    per_feed = _INTEL_LAST.get("perFeed") or []
    failed = [f["feed"] for f in per_feed if not f.get("ok")]
    reg = argus_institutional_intel.build_source_registry()
    disabled = [{"sourceName": s["sourceName"], "reasonJa": s["noteJa"]}
                for s in (reg["media"] + reg["official"])
                if s["status"] in ("disabled", "metadata_only")]
    ts = _INTEL_LAST.get("ts") or 0
    return jsonify({
        "schemaVersion": "institutional-intel-status-v1", "asOf": now_iso,
        "sourcesChecked": len(per_feed), "sourcesFailed": failed,
        "latestFetchAt": (datetime.fromtimestamp(ts, pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                          if ts else None),
        "signalsNow": len(sigs),
        "signalsToday": sum(1 for s in sigs if str(s.get("publishedAt") or "")[:10] == today
                            or str(s.get("fetchedAt") or "")[:10] == today),
        "mappedToOwnerAssets": sum(1 for s in sigs if s.get("ownerAssetHit")),
        "headlineOnlyCount": sum(1 for s in sigs if s.get("headlineOnly")),
        "registry": reg, "disabledSources": disabled,
        "ingestionAlive": bool(ts and (time.time() - ts) < 3600),
        "noteJa": "取込は既存のC.A.O.S. 24/7巡回(rate-limit/dedupe/失敗バックオフ実装済み)を共用。"
                  "公開GETは取得を起動しない。"})


# ── V11.7.0 Big Money / Flow Attribution ─────────────────────────────────────
# Answers 「大口の新規買いか、買い戻しか、個人の追随か」 as EVIDENCE, never as a
# trade signal. Evidence collection is CACHED-ONLY (public-path safe): bridge
# quotes (US flow), JQ daily bars, weekly margin, institutional signals, regime,
# macro events. Missing pieces (JP moomoo flow is intentionally off) become
# missingEvidence + a confidence cap — never fabricated numbers.

def _flow_evidence_for(symbol, market):
    """Cached-only evidence dict for argus_flow_attribution.classify. NEVER fetches."""
    symu, mkt = str(symbol).upper(), str(market).upper()
    ev, sources = {}, {}
    q = _quote_cached_only(symu, mkt) or {}
    if isinstance(q.get("changePct"), (int, float)):
        ev["changePct"] = float(q["changePct"])
    if isinstance(q.get("price"), (int, float)):
        ev["price"] = float(q["price"])
    if isinstance(q.get("volume"), (int, float)) and q["volume"] > 0:
        ev["volume"] = q["volume"]
    bnr = (q.get("flow") or {}).get("bigNetRatio")
    if isinstance(bnr, (int, float)):
        ev["flowBigNetRatio"] = float(bnr)
        sources["flow"] = True
    ev["sourceUpdatedAt"] = q.get("exchangeTs") or q.get("date")
    if mkt == "JP":
        code4 = symu[:4]
        h = (_JQ_HISTORY_CACHE.get(code4) or {}).get("data") or {}
        closes, vols = h.get("closes") or [], h.get("volumes") or []
        try:
            if len(closes) >= 7 and closes[6]:
                ev["priorRunupPct"] = round((float(closes[1]) / float(closes[6]) - 1) * 100, 1)
        except Exception:
            pass
        try:
            base = [v for v in vols[1:21] if isinstance(v, (int, float)) and v > 0]
            if len(base) >= 5 and isinstance(ev.get("volume"), (int, float)):
                ev["volumeRatio"] = round(ev["volume"] / (sum(base) / len(base)), 2)
        except Exception:
            pass
        try:
            hist = (_JQ_MARGIN_CACHE.get(code4) or {}).get("data") or []
            if hist:
                latest = hist[0]                    # newest-first
                ev["marginShortHeavy"] = bool((latest.get("shortVol") or 0) >
                                              (latest.get("longVol") or 0))
                sources["margin"] = True
                # v11.10.0 supply/demand structure hints (RAW shape, not the SD
                # narrative — keeps flow←structure one-directional):
                base = [v for v in ((_JQ_HISTORY_CACHE.get(code4) or {}).get("data") or {})
                        .get("volumes", [])[1:21] if isinstance(v, (int, float)) and v > 0]
                avg_v = (sum(base) / len(base)) if len(base) >= 5 else None
                mb, msell = latest.get("longVol"), latest.get("shortVol")
                if avg_v and isinstance(mb, (int, float)):
                    ev["creditOverhang"] = (mb / avg_v) >= 5          # 買い残が平均出来高5日分超
                if avg_v and isinstance(msell, (int, float)):
                    ev["squeezeProne"] = ev.get("marginShortHeavy") or (msell / avg_v) >= 3
        except Exception:
            pass
        try:
            table, _dt = _JSF_CACHE.get("table"), None
            rec = (table or {}).get(code4)
            if rec and isinstance(rec.get("short"), int) and isinstance(rec.get("loan"), int):
                # 貸借残: short > loan は売り長 — margin evidence が無い時の補完
                if "marginShortHeavy" not in ev:
                    ev["marginShortHeavy"] = rec["short"] > rec["loan"]
                if "squeezeProne" not in ev:
                    ev["squeezeProne"] = rec["short"] > rec["loan"]
                sources["shortInterest"] = True
        except Exception:
            pass
    try:                                            # institutional stance (v11.6.0)
        for s in _institutional_signals(symbol=symu, cap=10)[:3]:
            st = s.get("stance")
            if st in ("bullish", "bearish"):
                ev["instStance"] = st
                ev["instDirect"] = s.get("directness") == "direct"
                break
    except Exception:
        pass
    try:                                            # regime + macro events today
        reg = ((_REGIME_CACHE.get("data") or {}).get("regime") or {})
        if reg.get("label"):
            ev["regimeLabel"] = reg["label"]
            ev["regimeRiskOff"] = reg["label"] in ("RISK_OFF", "EVENT_WAIT")
    except Exception:
        pass
    try:
        today = _ai_now_iso()[:10]
        ev["eventToday"] = any(
            rec.get("phase") in ("imminent", "released_pending_result", "post_result")
            and str(rec.get("eventTimeUtc") or rec.get("eventDate") or "")[:10] == today
            for rec in _MOVER_MACRO_VIEW())
    except Exception:
        pass
    try:                                            # theme peers (same direction)
        chg = ev.get("changePct")
        if isinstance(chg, (int, float)) and abs(chg) >= 1.0:
            for members in _DOWNSIDE_THEMES.values():
                if symu not in members:
                    continue
                same = total = 0
                for m in members:
                    if m == symu:
                        continue
                    pq = _quote_cached_only(m, "JP" if m[:1].isdigit() else "US") or {}
                    pc = pq.get("changePct")
                    if isinstance(pc, (int, float)):
                        total += 1
                        if abs(pc) >= 1.0 and ((pc > 0) == (chg > 0)):
                            same += 1
                ev["themePeersSame"], ev["themePeersTotal"] = same, total
                break
    except Exception:
        pass
    ev["sources"] = sources
    return ev


_SD_FLOW_SUPPORT_JA = {
    "squeeze_prone": "需給は買い戻し(踏み上げ)解釈を支持 — 新規大口買いとは未確定",
    "credit_overhang": "需給は買い集め解釈を弱める(信用買い残が重い)",
    "very_good": "需給は買い集め解釈と整合的(上値の玉が軽い)",
    "good": "需給は買い集め解釈と整合的(上値の玉が軽い)",
    "distribution_risk": "需給は売り抜け警戒を支持",
    "unknown": "需給データ不足(解釈の裏付けなし)",
}


def _flow_attribution_for(symbol, market):
    rec = argus_flow_attribution.classify(
        symbol, market, _flow_evidence_for(symbol, market), _ai_now_iso())
    # v11.10.0: JP flow records carry the supply/demand read as SUPPORTING
    # evidence (Flow=誰が動かしたか / SD=土台が軽いか重いか、の分離を保つ).
    if str(market).upper() == "JP":
        try:
            sig = _supply_demand_signal_for(symbol)
            rec["supplyDemand"] = {
                "rank": sig["supplyDemandRank"], "conditionJa": sig["conditionJa"],
                "chips": sig["chips"], "readabilityLabelJa": sig["readabilityLabelJa"],
                "supportNoteJa": _SD_FLOW_SUPPORT_JA.get(sig["condition"], "需給は中立"),
                "confidence": sig["confidence"]}
        except Exception:
            pass
    return rec


def _flow_attribution_list(cap=12):
    """Material movers on the watchlist (|chg|>=2% or vol spike), classified."""
    out = []
    for s in (_JP_WATCHLIST + _US_WATCHLIST):
        sym = str(s.get("symbol") or "").upper()
        mkt = "JP" if sym[:1].isdigit() else "US"
        ev = _flow_evidence_for(sym, mkt)
        chg, vr = ev.get("changePct"), ev.get("volumeRatio")
        if not ((isinstance(chg, (int, float)) and abs(chg) >= 2.0)
                or (isinstance(vr, (int, float)) and vr >= 1.8)):
            continue
        rec = argus_flow_attribution.classify(sym, mkt, ev, _ai_now_iso())
        rec["name"] = s.get("name") or sym
        out.append(rec)
    out.sort(key=lambda r: (-(r["confidence"]),
                            -abs(r["changePct"] or 0.0)))
    return out[:cap]


# ── V11.8.0 Position / Exposure — watchlist-level ONLY on the backend ───────
# PRIVACY: actual holdings (quantity/average cost/valuation) exist ONLY in the
# owner's device localStorage. The server never receives, stores, or serves
# them, so this public endpoint is structurally leak-free: it reports theme
# COUNTS over the public watchlist and the honest "position data not
# configured server-side" state. The real exposure dashboard is computed
# client-side by web/src/domain/positionExposure.ts.

def _watchlist_theme_items():
    items = [{"symbol": s.get("symbol"), "market": "JP", "name": s.get("name")}
             for s in _JP_WATCHLIST]
    items += [{"symbol": s.get("symbol"), "market": "US", "name": s.get("name")}
              for s in _US_WATCHLIST]
    return items


# ── V11.9.0 Portfolio Sync / Snapshot Foundation ─────────────────────────────
# ARCHITECTURE (see argus_portfolio_sync module docstring): the cross-device
# sync path is the EXISTING client-encrypted passphrase vault (ciphertext-only
# in the cloud). A server-side PLAINTEXT portfolio store is modeled but
# DISABLED until real authentication exists: the flag below has no env wire on
# purpose — enabling it is a deliberate future code change, not a config flip.
_PORTFOLIO_SERVER_SYNC_ENABLED = False


@app.route("/api/argus/portfolio-sync/status")
def api_argus_portfolio_sync_status():
    """Public: storage-layer architecture + enabled/disabled state ONLY.
    Structurally leak-free (argus_portfolio_sync.contains_sensitive == [])."""
    return jsonify(argus_portfolio_sync.public_sync_status(
        server_sync_enabled=_PORTFOLIO_SERVER_SYNC_ENABLED, now_iso=_ai_now_iso()))


@app.route("/api/argus/portfolio-sync/pull", methods=["GET"])
@app.route("/api/argus/portfolio-sync/push", methods=["POST"])
@app.route("/api/argus/portfolio-sync/snapshots", methods=["GET", "POST"])
def api_argus_portfolio_sync_disabled():
    """Server-side plaintext sync stubs — admin-gated AND disabled. Even a
    valid admin token gets 'disabled' until an authenticated private store
    exists; the client-encrypted vault remains the sync path."""
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    return jsonify({"status": "disabled",
                    "reasonJa": "サーバー側に平文の保有データを置く同期は、認証基盤が"
                                "整うまで無効です。端末間同期は既存のパスフレーズ暗号化"
                                "バックアップ(vault)をご利用ください。",
                    "syncSchemaVersion": argus_portfolio_sync.SYNC_SCHEMA_VERSION}), 403


@app.route("/api/argus/position-exposure/status")
def api_argus_position_exposure_status():
    """Public: watchlist theme exposure (counts only) + where real position
    data lives. NO quantities/costs/values by construction."""
    wl = argus_position_exposure.watchlist_theme_exposure(_watchlist_theme_items())
    return jsonify({
        "schemaVersion": "position-exposure-status-v1", "asOf": _ai_now_iso(),
        "positionData": "device_local_only",
        "positionDataNoteJa": "保有数量・取得単価は端末内(localStorage)のみで管理され、"
                              "サーバーには送信・保存されません。保有リスク判定は"
                              "アプリ内でローカル計算されます。",
        "watchlistExposure": wl,
        "engineVersion": argus_position_exposure.SCHEMA_VERSION,
        "disclaimerJa": "リスク点検であり売買指示ではない。"})


# ── V11.11.0 US daily-bars cache (Finnhub candles; warmed by the collect cron
# only — public GETs read cache). Feeds US supply/demand volume metrics, flow
# volumeRatio, and the Decision Quality outcome updater. ──────────────────────
_US_HISTORY_CACHE = {}          # SYM -> {"data": {...}|None, "expires": epoch}
_US_HISTORY_TTL = 6 * 3600


def _us_price_history(sym):
    """~60 trading days of closes/volumes/dates (newest-first) for one US symbol.
    FETCHES (Finnhub) — call only from admin/cron paths; readers use the cache."""
    symu = str(sym).upper()
    now = time.time()
    c = _US_HISTORY_CACHE.get(symu)
    if c and now < c["expires"]:
        return c["data"]
    data = None
    try:
        candles = get_stock_candles(symu, days=90)
        if candles and len(candles) >= 20:
            rows = sorted(candles, key=lambda x: x["timestamp"], reverse=True)
            data = {"closes": [float(r["close"]) for r in rows],
                    "volumes": [int(r.get("volume") or 0) for r in rows],
                    "dates": [datetime.utcfromtimestamp(r["timestamp"]).strftime("%Y-%m-%d")
                              for r in rows]}
    except Exception as e:
        add_log(f"[sd] us history fetch failed {symu}: {type(e).__name__}")
    _US_HISTORY_CACHE[symu] = {"data": data, "expires": now + (_US_HISTORY_TTL if data else 600)}
    return data


# ── V11.10.0 Supply / Demand Intelligence (JP) ───────────────────────────────
# 「日証金を見ると需給は良いのか悪いのか」に RANK+状態 で答える層。数値の読み方
# はエンジンが行い、生数値はevidence(UIでは折りたたみ)に置く。cached-only:
# J-Quants週次信用残 + JSF日次貸借残 + 日足 — 公表データでリアルタイムではない。

def _supply_demand_signal_for(symu, market="JP"):
    """One symbol → SupplyDemandSignal. Cached-only, deterministic. JP uses
    margin/JSF structure; US uses the measured bridge flow (簡易判定, honest)."""
    symu = str(symu).upper()
    mkt = str(market).upper()
    code4 = symu[:4]
    fev = _flow_evidence_for(symu, mkt)
    ev = {"changePct": fev.get("changePct"), "volumeRatio": fev.get("volumeRatio"),
          "priorRunupPct": fev.get("priorRunupPct"), "instStance": fev.get("instStance"),
          "eventToday": fev.get("eventToday"), "regimeRiskOff": fev.get("regimeRiskOff"),
          "liquidityLow": fev.get("liquidityLow"),
          "sourceUpdatedAt": fev.get("sourceUpdatedAt")}
    if mkt == "US":
        ev["measuredFlowNetRatio"] = fev.get("flowBigNetRatio")
        try:
            h = (_US_HISTORY_CACHE.get(symu) or {}).get("data") or {}
            vols = [v for v in (h.get("volumes") or [])[1:21]
                    if isinstance(v, (int, float)) and v > 0]
            if len(vols) >= 5:
                ev["avgDailyVolume"] = sum(vols) / len(vols)
                q = _quote_cached_only(symu, "US") or {}
                if isinstance(q.get("volume"), (int, float)) and q["volume"] > 0 \
                        and ev.get("volumeRatio") is None:
                    ev["volumeRatio"] = round(q["volume"] / ev["avgDailyVolume"], 2)
            closes = h.get("closes") or []
            if len(closes) >= 7 and closes[6] and ev.get("priorRunupPct") is None:
                ev["priorRunupPct"] = round((float(closes[1]) / float(closes[6]) - 1) * 100, 1)
        except Exception:
            pass
        try:
            ev["flowClass"] = argus_flow_attribution.classify(
                symu, "US", fev, _ai_now_iso())["flowClass"]
        except Exception:
            pass
        return argus_supply_demand.classify(symu, "US", ev, _ai_now_iso())
    try:
        hist = (_JQ_MARGIN_CACHE.get(code4) or {}).get("data") or []
        if hist:
            ev["marginBuying"] = hist[0].get("longVol")
            ev["marginSelling"] = hist[0].get("shortVol")
            ev["marginDate"] = hist[0].get("date")
            if len(hist) > 1:
                ev["marginBuyingPrev"] = hist[1].get("longVol")
                ev["marginSellingPrev"] = hist[1].get("shortVol")
    except Exception:
        pass
    try:
        rec = (_JSF_CACHE.get("table") or {}).get(code4)
        if rec:
            ev["jsfLoan"], ev["jsfLending"] = rec.get("loan"), rec.get("short")
            ev["jsfDate"] = _JSF_CACHE.get("date")
    except Exception:
        pass
    try:
        h = (_JQ_HISTORY_CACHE.get(code4) or {}).get("data") or {}
        vols = [v for v in (h.get("volumes") or [])[1:21]
                if isinstance(v, (int, float)) and v > 0]
        if len(vols) >= 5:
            ev["avgDailyVolume"] = sum(vols) / len(vols)
    except Exception:
        pass
    try:                                    # flow narrative as context (one-way)
        ev["flowClass"] = argus_flow_attribution.classify(
            symu, "JP", fev, _ai_now_iso())["flowClass"]
    except Exception:
        pass
    return argus_supply_demand.classify(symu, "JP", ev, _ai_now_iso())


def _supply_demand_list(cap=16):
    out = []
    for s, mkt in ([(x, "JP") for x in _JP_WATCHLIST]
                   + [(x, "US") for x in _US_WATCHLIST]):
        sym = str(s.get("symbol") or "").upper()
        if not sym:
            continue
        sig = _supply_demand_signal_for(sym, mkt)
        sig["name"] = s.get("name") or sym
        out.append(sig)
    rank_order = {"S": 0, "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "Unknown": 6}
    out.sort(key=lambda r: (rank_order.get(r["supplyDemandRank"], 9), -r["confidence"]))
    return out[:cap]


def _supply_demand_sources():
    return {"enabled": [s for s, ok in (("jquants-margin-weekly", bool(_JQ_MARGIN_CACHE)),
                                        ("jsf-daily-balance", bool(_JSF_CACHE.get("table"))),
                                        ("jquants-daily-bars", bool(_JQ_HISTORY_CACHE))) if ok],
            "disabled": [
                {"source": "逆日歩(品貸料)", "reasonJa": "未取込(日証金の品貸料CSVは別系統。捏造せず未取得と表示)"},
                {"source": "銘柄別空売り比率", "reasonJa": "J-Quants Standardは業種別のみ(銘柄別は未提供)"},
                {"source": "moomoo JPリアルタイム", "reasonJa": "口座権限により意図的に無効(エラーではない)"}],
            "jsf": bool(_JSF_CACHE.get("table")),
            "jqMargin": bool(_JQ_MARGIN_CACHE),
            "shortRatio": False}


# ── V11.12.0 Action Priority (server side = WATCHLIST-LEVEL only) ────────────
# The server never knows holdings, so its items rank public signals with
# isHeld=unknown (privacy-safe by construction). The device-local TS port
# re-ranks with real held/weight context for the owner's Today list.

def _action_priority_items(cap=12):
    now_iso = _ai_now_iso()
    sd_by = {s["symbol"]: s for s in _supply_demand_list(cap=30)}
    flow_by = {r["symbol"]: r for r in _flow_attribution_list(cap=30)}
    risk_off = False
    try:
        lbl = ((_REGIME_CACHE.get("data") or {}).get("regime") or {}).get("label")
        risk_off = lbl in ("RISK_OFF", "EVENT_WAIT")
    except Exception:
        pass
    items = []
    for s, mkt in ([(x, "JP") for x in _JP_WATCHLIST] + [(x, "US") for x in _US_WATCHLIST]):
        sym = str(s.get("symbol") or "").upper()
        if not sym:
            continue
        sd = sd_by.get(sym) or {}
        fl = flow_by.get(sym) or {}
        ev = (sd.get("evidence") or {})
        inputs = {
            "isHeld": None, "assetName": s.get("name") or sym,
            "sdRank": sd.get("supplyDemandRank"), "sdCondition": sd.get("condition"),
            "flowClass": fl.get("flowClass") or ev.get("flowAttributionContext"),
            "changePct": fl.get("changePct"),
            "priorRunupPct": None,
            "eventPending": bool(ev.get("eventContext")),
            "instStance": ev.get("institutionalContext"),
            "instDirect": False,
            "regimeRiskOff": risk_off,
        }
        items.append(argus_action_priority.build_item(sym, mkt, inputs, now_iso))
    return argus_action_priority.rank_items(items, cap=cap)


@app.route("/api/argus/action-priority")
def api_argus_action_priority():
    """Public cached-only: watchlist-level attention priorities (no holdings —
    the app re-ranks locally with held context). Never a trade instruction."""
    items = _action_priority_items(cap=12)
    return jsonify({"schemaVersion": "action-priority-response-v1",
                    "asOf": _ai_now_iso(), "count": len(items), "items": items,
                    "summary": argus_action_priority.summary(items, _ai_now_iso()),
                    "disclaimerJa": argus_action_priority.COMPLIANCE})


@app.route("/api/argus/action-priority/status")
def api_argus_action_priority_status():
    items = _action_priority_items(cap=30)
    return jsonify(argus_action_priority.status_doc(
        items, now_iso=_ai_now_iso(),
        sources={"positionExposure": False,   # device-local by design
                 "eventRadar": bool(_MACRO_ANALYSIS), "flowAttribution": True,
                 "supplyDemand": True,
                 "institutionalIntelligence": bool(_INTEL_STORE),
                 "marketRegime": bool(_REGIME_CACHE.get("data")),
                 "decisionQuality": False}))  # records device-local by design


# ── V11.13.0 Session Brief (server side = WATCHLIST-LEVEL redacted brief) ────

def _session_brief_public():
    now = datetime.now(TZ_JST)
    jp_open = False
    us_open = False
    try:
        jp_open = now.weekday() < 5 and (9 <= now.hour < 15 or (now.hour == 15 and now.minute <= 30))
        us_h = now.hour
        us_open = now.weekday() < 5 and (us_h >= 22 or us_h < 5) \
            or (now.weekday() == 5 and now.hour < 5)
    except Exception:
        pass
    sess = argus_session_brief.resolve_session(now.hour, now.weekday(), jp_open, us_open)
    items = _action_priority_items(cap=20)
    events = []
    try:
        today = _ai_now_iso()[:10]
        for rec in _MOVER_MACRO_VIEW():
            if rec.get("phase") in ("imminent", "released_pending_result") \
                    and str(rec.get("eventTimeUtc") or rec.get("eventDate") or "")[:10] == today:
                events.append(rec.get("eventCode") or rec.get("title"))
    except Exception:
        pass
    regime = None
    risk_off = False
    try:
        regime = ((_REGIME_CACHE.get("data") or {}).get("regime") or {}).get("label")
        risk_off = regime in ("RISK_OFF", "EVENT_WAIT")
    except Exception:
        pass
    sd_hi = []
    try:
        for s in _supply_demand_list(cap=16):
            if s["supplyDemandRank"] in ("S", "A", "D", "E") \
                    or s["condition"] == "squeeze_prone":
                sd_hi.append({"symbol": s["symbol"], "name": s.get("name"),
                              "rank": s["supplyDemandRank"], "conditionJa": s["conditionJa"]})
    except Exception:
        pass
    return argus_session_brief.build_brief({
        "sessionType": sess["sessionType"], "marketStatus": sess["marketStatus"],
        "priorityItems": items, "eventNames": [e for e in events if e][:4],
        "regimeLabel": regime, "regimeRiskOff": risk_off,
        "sdHighlights": sd_hi, "isPrivate": False,
    }, _ai_now_iso())


# ── V11.17.0 Scenario Engine (server side = WATCHLIST-LEVEL, isHeld unknown) ─
# 「明日どうなる?」に単一予測ではなく条件付き分岐で答える層。サーバーは保有を
# 知らないので isHeld=None(public_safe)で合成し、端末側TSポートが保有文脈で
# 再合成する。確率は帯のみ — %断定は実証モデルなしには絶対にしない。

def _scenario_set_for(sym, mkt, name, sd, fl, risk_off):
    ev = (sd.get("evidence") or {})
    fev = {}
    try:
        fev = _flow_evidence_for(sym, mkt)
    except Exception:
        pass
    missing = list(sd.get("missingEvidence") or [])[:2] \
        + list(fl.get("missingEvidence") or [])[:2]
    inputs = {
        "isHeld": None, "assetName": name,
        "sdRank": sd.get("supplyDemandRank"), "sdCondition": sd.get("condition"),
        "sdLevel": sd.get("supplyDemandLevel"), "sdDirection": sd.get("direction"),
        "flowClass": fl.get("flowClass"),
        "instStance": fev.get("instStance"), "instDirect": False,
        "eventPending": bool(fev.get("eventToday")),
        "eventName": fev.get("eventToday"),
        "regimeRiskOff": risk_off,
        "changePct": fl.get("changePct") if fl.get("changePct") is not None
        else fev.get("changePct"),
        "priorRunupPct": fev.get("priorRunupPct"),
        "missing": missing,
    }
    return argus_scenario.build_scenario_set(sym, mkt, inputs, _ai_now_iso())


def _scenario_list(cap=16):
    sd_by = {s["symbol"]: s for s in _supply_demand_list(cap=30)}
    flow_by = {r["symbol"]: r for r in _flow_attribution_list(cap=30)}
    risk_off = False
    try:
        lbl = ((_REGIME_CACHE.get("data") or {}).get("regime") or {}).get("label")
        risk_off = lbl in ("RISK_OFF", "EVENT_WAIT")
    except Exception:
        pass
    out = []
    for s, mkt in ([(x, "JP") for x in _JP_WATCHLIST] + [(x, "US") for x in _US_WATCHLIST]):
        sym = str(s.get("symbol") or "").upper()
        if not sym:
            continue
        out.append(_scenario_set_for(sym, mkt, s.get("name") or sym,
                                     sd_by.get(sym) or {}, flow_by.get(sym) or {},
                                     risk_off))
    order = {"bearish": 0, "wait_event": 1, "mixed": 2, "bullish": 3,
             "base": 4, "unknown": 5}
    out.sort(key=lambda r: (order.get(r["dominantScenario"], 9), -r["confidence"]))
    return out[:cap]


@app.route("/api/argus/scenarios")
def api_argus_scenarios():
    """Public cached-only: conditional scenario sets at WATCHLIST level (no
    holdings — the app re-composes with held context on device). Probability
    BANDS only; never a prediction or trade instruction."""
    sym = str(request.args.get("symbol") or "").upper().strip()
    now_iso = _ai_now_iso()
    if sym:
        all_wl = [(x, "JP") for x in _JP_WATCHLIST] + [(x, "US") for x in _US_WATCHLIST]
        hit = next(((s, m) for s, m in all_wl
                    if str(s.get("symbol") or "").upper() == sym), None)
        if not hit:
            return jsonify({"schemaVersion": "scenario-response-v1", "asOf": now_iso,
                            "error": "symbol not in watchlist", "symbol": sym}), 404
        s, mkt = hit
        sd_by = {x["symbol"]: x for x in _supply_demand_list(cap=30)}
        flow_by = {r["symbol"]: r for r in _flow_attribution_list(cap=30)}
        risk_off = False
        try:
            lbl = ((_REGIME_CACHE.get("data") or {}).get("regime") or {}).get("label")
            risk_off = lbl in ("RISK_OFF", "EVENT_WAIT")
        except Exception:
            pass
        return jsonify({"schemaVersion": "scenario-response-v1", "asOf": now_iso,
                        "scenarioSet": _scenario_set_for(sym, mkt, s.get("name") or sym,
                                                         sd_by.get(sym) or {},
                                                         flow_by.get(sym) or {}, risk_off),
                        "disclaimerJa": argus_scenario.COMPLIANCE})
    sets = _scenario_list(cap=16)
    return jsonify({"schemaVersion": "scenario-response-v1", "asOf": now_iso,
                    "count": len(sets), "scenarioSets": sets,
                    "marketScenario": _market_scenario_public(),
                    "disclaimerJa": argus_scenario.COMPLIANCE})


def _market_scenario_public():
    regime = None
    risk_off = False
    try:
        regime = ((_REGIME_CACHE.get("data") or {}).get("regime") or {}).get("label")
        risk_off = regime in ("RISK_OFF",)
    except Exception:
        pass
    events = []
    try:
        today = _ai_now_iso()[:10]
        for rec in _MOVER_MACRO_VIEW():
            if rec.get("phase") in ("imminent", "released_pending_result") \
                    and str(rec.get("eventTimeUtc") or rec.get("eventDate") or "")[:10] == today:
                events.append(rec.get("eventCode") or rec.get("title"))
    except Exception:
        pass
    return argus_scenario.market_scenario(regime, risk_off,
                                          [e for e in events if e][:2], _ai_now_iso())


# ── V11.18.0 Entry / Exit Planning (server side = WATCHLIST-LEVEL) ───────────
# 「今から入っていいか/買い増ししていいか」に計画で答える層。サーバーは保有を
# 知らないので isHeld=None(public_safe)で合成し、端末側TSポートが数量・比率・
# 損益を加味して再合成する。執行語(今すぐ買え等)は純モジュールが構造的に禁止。

def _market_open_now(mkt):
    try:
        now = datetime.now(TZ_JST)
        if now.weekday() >= 5:
            return False
        if mkt == "JP":
            return 9 <= now.hour < 15 or (now.hour == 15 and now.minute <= 30)
        return now.hour >= 22 or now.hour < 5
    except Exception:
        return None


def _trade_plan_list(cap=16):
    sd_by = {s["symbol"]: s for s in _supply_demand_list(cap=30)}
    flow_by = {r["symbol"]: r for r in _flow_attribution_list(cap=30)}
    scen_by = {s["symbol"]: s for s in _scenario_list(cap=30)}
    ap_by = {i["symbol"]: i for i in _action_priority_items(cap=30)}
    risk_off = False
    try:
        lbl = ((_REGIME_CACHE.get("data") or {}).get("regime") or {}).get("label")
        risk_off = lbl in ("RISK_OFF", "EVENT_WAIT")
    except Exception:
        pass
    plans = []
    for s, mkt in ([(x, "JP") for x in _JP_WATCHLIST] + [(x, "US") for x in _US_WATCHLIST]):
        sym = str(s.get("symbol") or "").upper()
        if not sym:
            continue
        sd = sd_by.get(sym) or {}
        fl = flow_by.get(sym) or {}
        sc = scen_by.get(sym) or {}
        ap = ap_by.get(sym) or {}
        fev = {}
        try:
            fev = _flow_evidence_for(sym, mkt)
        except Exception:
            pass
        plans.append(argus_trade_plan.build_plan(sym, mkt, {
            "isHeld": None, "assetName": s.get("name") or sym,
            "sdRank": sd.get("supplyDemandRank"), "sdCondition": sd.get("condition"),
            "sdLevel": sd.get("supplyDemandLevel"),
            "flowClass": fl.get("flowClass"),
            "scenarioDominant": sc.get("dominantScenario"),
            "apCategory": ap.get("category"), "apRank": ap.get("priorityRank"),
            "eventPending": bool(fev.get("eventToday")),
            "eventName": fev.get("eventToday"),
            "regimeRiskOff": risk_off,
            "priorRunupPct": fev.get("priorRunupPct"),
            "changePct": fl.get("changePct"),
            "marketOpen": _market_open_now(mkt),
            "missing": list(sd.get("missingEvidence") or [])[:2],
        }, _ai_now_iso()))
    order = {"trim_review": 0, "exit_review": 0, "event_wait": 1, "avoid_chase": 2,
             "add": 3, "entry": 3, "hold": 4, "wait": 5, "no_action": 6, "unknown": 7}
    plans.sort(key=lambda p: (order.get(p["planType"], 9), -p["confidence"]))
    return plans[:cap]


@app.route("/api/argus/position-plans")
def api_argus_position_plans():
    """Public cached-only: WATCHLIST-LEVEL planning views (no holdings — the app
    re-composes with held context on device). Plans, never orders."""
    sym = str(request.args.get("symbol") or "").upper().strip()
    now_iso = _ai_now_iso()
    plans = _trade_plan_list(cap=30 if sym else 16)
    if sym:
        hit = next((p for p in plans if p["symbol"] == sym), None)
        if not hit:
            return jsonify({"schemaVersion": "trade-plan-response-v1", "asOf": now_iso,
                            "error": "symbol not in watchlist", "symbol": sym}), 404
        return jsonify({"schemaVersion": "trade-plan-response-v1", "asOf": now_iso,
                        "plan": hit, "disclaimerJa": argus_trade_plan.COMPLIANCE})
    return jsonify({"schemaVersion": "trade-plan-response-v1", "asOf": now_iso,
                    "count": len(plans), "plans": plans,
                    "portfolioSummary": argus_trade_plan.portfolio_summary(plans),
                    "disclaimerJa": argus_trade_plan.COMPLIANCE})


@app.route("/api/argus/position-plans/status")
def api_argus_position_plans_status():
    plans = _trade_plan_list(cap=30)
    return jsonify(argus_trade_plan.status_doc(
        plans, now_iso=_ai_now_iso(),
        sources={"scenarioEngine": True, "actionPriority": True,
                 "supplyDemand": True, "flowAttribution": True,
                 "positionExposure": False,   # device-local by design
                 "marketRegime": bool(_REGIME_CACHE.get("data")),
                 "institutionalIntelligence": bool(_INTEL_STORE),
                 "eventRadar": bool(_MACRO_ANALYSIS),
                 "decisionQuality": False,    # records device-local by design
                 "learningDashboard": False,  # records device-local by design
                 "notifications": False}))    # stored device-local by design


@app.route("/api/argus/scenarios/status")
def api_argus_scenarios_status():
    sets = _scenario_list(cap=30)
    return jsonify(argus_scenario.status_doc(
        sets, now_iso=_ai_now_iso(),
        sources={"supplyDemand": True, "flowAttribution": True,
                 "eventRadar": bool(_MACRO_ANALYSIS),
                 "marketRegime": bool(_REGIME_CACHE.get("data")),
                 "positionExposure": False,   # device-local by design
                 "decisionQuality": False}))  # records device-local by design


# ── V11.22.0 Data Quality Console (server-side collection — honest only) ────
# 鮮度はサーバーが実測できたタイムスタンプのみから判定。測れないものはunknown。
# 私的レイヤー(保有/投信/記録)は「端末内で判定」として数値を持たない。

def _dq_iso(epoch):
    try:
        return datetime.utcfromtimestamp(epoch).strftime("%Y-%m-%dT%H:%M:%SZ") if epoch else None
    except Exception:
        return None


def _data_quality_console():
    import time as _t
    now = _t.time()
    now_iso = _ai_now_iso()
    bdoc = _bridge_status_doc()

    def cache_success(cache, ttl):
        """expires-TTL≈最終成功時刻(dataがある場合のみ・なければNone=unknown)。"""
        try:
            exps = [v.get("expires", 0) for v in cache.values()
                    if isinstance(v, dict) and v.get("data")]
            return _dq_iso(max(exps) - ttl) if exps else None
        except Exception:
            return None

    jq_margin_last = None
    try:
        dates = [h[0].get("date") for h in
                 ((v.get("data") or None) for v in _JQ_MARGIN_CACHE.values()) if h]
        if dates:
            jq_margin_last = max(d for d in dates if d)
    except Exception:
        pass

    us_last = _dq_iso(now - bdoc["lastUsPushAgeSec"]) if bdoc.get("lastUsPushAgeSec") is not None else None
    rates_last = _dq_iso(_RATES_CACHE["expires"] - _RATES_CACHE_TTL) \
        if _RATES_CACHE.get("data") is not None and _RATES_CACHE.get("expires") else None

    sources = [
        {"sourceName": "us-realtime-bridge", "sourceType": "market_data",
         "cadence": "realtime", "lastSuccessAt": us_last,
         "impactJa": "米国株の現在値・Flow実測", "nextStepJa": "bridge/scripts/check_bridge_status.sh"},
        {"sourceName": "jp-fallback-prices", "sourceType": "market_data",
         "cadence": "intraday", "lastSuccessAt": None,   # 取得毎キャッシュで一括時刻なし
         "fallbackActive": True, "impactJa": "日本株の価格(夜間/引け後はdelayedで正常)"},
        {"sourceName": "jsf-daily-balance", "sourceType": "supply_demand",
         "cadence": "daily", "lastSuccessAt": (str(_JSF_CACHE.get("date")) + "T16:00:00+09:00"
                                               if _JSF_CACHE.get("date") else None),
         "impactJa": "需給ランク(貸借残)の鮮度", "nextStepJa": "collect cron(30分毎)後に再確認"},
        {"sourceName": "jquants-margin-weekly", "sourceType": "supply_demand",
         "cadence": "weekly", "lastSuccessAt": (str(jq_margin_last) + "T16:00:00+09:00"
                                                if jq_margin_last else None),
         "impactJa": "需給ランク(週次信用残)の鮮度"},
        {"sourceName": "fund-nav", "sourceType": "market_data", "cadence": "daily",
         "lastSuccessAt": cache_success(_FUND_NAV_CACHE, _FUND_NAV_TTL),
         "impactJa": "投信(FIRE Core)の評価額"},
        {"sourceName": "crypto-prices", "sourceType": "market_data", "cadence": "realtime",
         "lastSuccessAt": cache_success(_CRYPTO_CACHE, _CRYPTO_CACHE_TTL),
         "impactJa": "暗号資産の現在値"},
        {"sourceName": "fred-rates-vix", "sourceType": "macro", "cadence": "intraday",
         "lastSuccessAt": rates_last, "impactJa": "金利/VIX/ドル円(地合い判定)"},
        {"sourceName": "event-calendar", "sourceType": "event", "cadence": "event_based",
         "lastSuccessAt": None if not _MACRO_ANALYSIS else now_iso,
         "impactJa": "重要イベント(cron生成キャッシュ)"},
        {"sourceName": "institutional-intel", "sourceType": "institutional",
         "cadence": "intraday", "lastSuccessAt": now_iso if _INTEL_STORE else None,
         "impactJa": "機関シグナル/C.A.O.S."},
        # 恒久の意図的無効(criticalにしない)
        {"sourceName": "moomoo JPリアルタイム", "sourceType": "market_data",
         "cadence": "realtime", "expectedDisabled": True,
         "impactJa": "JPはフォールバック(J-Quants/Yahoo)で運用"},
        {"sourceName": "逆日歩(品貸料)", "sourceType": "supply_demand",
         "cadence": "daily", "expectedDisabled": True, "impactJa": "需給evidenceで常に未取得表示"},
        {"sourceName": "銘柄別空売り比率", "sourceType": "supply_demand",
         "cadence": "daily", "expectedDisabled": True, "impactJa": "業種別のみ取得可"},
    ]
    engines = [
        {"engineName": n, "status": "ok", "lastRunAt": now_iso}
        for n in ("session_brief", "action_priority", "scenario",
                  "entry_exit_planning", "supply_demand", "flow_attribution",
                  "institutional_intelligence")
    ] + [
        {"engineName": n, "status": "ok", "lastRunAt": None,
         "impactJa": "端末内で計算(サーバーは内容を知らない)"}
        for n in ("portfolio_strategy", "fire_core", "decision_quality",
                  "learning_dashboard", "notifications", "backup_safety",
                  "ai_review_pack")
    ]
    console = argus_data_quality.build_console({
        "sources": sources, "engines": engines,
        "bridge": {"bridgeProcess": bdoc.get("bridgeProcess"),
                   "openDStatus": bdoc.get("openDStatus"),
                   "bridgeMode": (bdoc.get("heartbeat") or {}).get("bridgeMode") or "us_only",
                   "usRealtimeStatus": bdoc.get("usRealtimeStatus"),
                   "jpRealtimeStatus": bdoc.get("jpRealtimeStatus"),
                   "jpFallbackActive": bdoc.get("jpFallbackActive"),
                   "heartbeatAgeSec": bdoc.get("heartbeatAgeSec"),
                   "acceptedCount": (bdoc.get("heartbeat") or {}).get("acceptedCount"),
                   "diskUsagePct": (bdoc.get("heartbeat") or {}).get("diskUsagePct")},
        "publicLeakSafe": True, "backupUnsafeWithData": None,
        "eventNear": False,
    }, now_iso, app_version="")
    # 自己漏洩検査 — 自分のドキュメントに機微フィールドが乗ったら即critical化
    try:
        if argus_portfolio_sync.contains_sensitive(console):
            console["publicLeakSafe"] = False
            console["overallStatus"] = "critical"
    except Exception:
        pass
    return console


@app.route("/api/argus/data-quality")
def api_argus_data_quality():
    """Public REDACTED console — statuses/buckets/timestamps only. No holdings,
    no fund data, no secrets. Honest: unmeasurable freshness stays unknown."""
    return jsonify(_data_quality_console())


@app.route("/api/argus/data-quality/status")
def api_argus_data_quality_status():
    return jsonify(argus_data_quality.public_status(
        _data_quality_console(), now_iso=_ai_now_iso()))


@app.route("/api/argus/review-pack/status")
def api_argus_review_pack_status():
    """Public REDACTED — flags only. Review packs are generated and copied ON
    DEVICE; the server never sees, stores, or forwards them."""
    return jsonify(argus_review_pack.public_status(now_iso=_ai_now_iso()))


@app.route("/api/argus/fire-core/status")
def api_argus_fire_core_status():
    """Public REDACTED — flags only. Fund data (names/units/NAV/values/
    contributions/accounts) lives on device; the server holds none of it."""
    return jsonify(argus_fire_core.public_status(now_iso=_ai_now_iso()))


@app.route("/api/argus/portfolio-strategy/status")
def api_argus_portfolio_strategy_status():
    """Public REDACTED — feature flags only. Strategy/FIRE/role details are
    composed ON DEVICE from local holdings; the server knows none of it."""
    return jsonify(argus_portfolio_strategy.public_status(
        now_iso=_ai_now_iso(),
        sources={"positionExposure": False,      # device-local by design
                 "entryExitPlanning": True, "scenarioEngine": True,
                 "marketRegime": bool(_REGIME_CACHE.get("data")),
                 "decisionQuality": False, "learningDashboard": False,
                 "portfolioSync": False, "backupSafety": False}))


@app.route("/api/argus/backup-safety/status")
def api_argus_backup_safety_status():
    """Public REDACTED — architecture facts only. Protection state, passphrase
    presence, and payloads live on device; the server cannot and must not know."""
    return jsonify(argus_backup_safety.public_status(now_iso=_ai_now_iso()))


@app.route("/api/argus/learning-review/status")
def api_argus_learning_review_status():
    """Public REDACTED — the learning dashboard aggregates DEVICE-LOCAL records
    on device; the server holds no records and computes nothing over them."""
    return jsonify(argus_learning_review.public_status(
        now_iso=_ai_now_iso(),
        sources={"decisionQuality": False, "snapshots": False, "notifications": False,
                 "supplyDemand": True, "flowAttribution": True,
                 "actionPriority": True, "sessionBrief": True,
                 "ownerAnnotations": False}))


@app.route("/api/argus/notifications/status")
def api_argus_notifications_status():
    """Public REDACTED — feature/architecture flags only. Notifications are
    generated and stored ON DEVICE; the server holds none by construction."""
    return jsonify(argus_notifications.public_status(
        now_iso=_ai_now_iso(),
        sources={"sessionBrief": True, "actionPriority": True,
                 "eventRadar": bool(_MACRO_ANALYSIS),
                 "positionExposure": False, "flowAttribution": True,
                 "supplyDemand": True,
                 "institutionalIntelligence": bool(_INTEL_STORE),
                 "decisionQuality": False, "portfolioSync": False}))


@app.route("/api/argus/session-brief")
def api_argus_session_brief():
    """Public cached-only: watchlist-level 今日の作戦 (no holdings — the app
    composes the held-aware version locally). Never a trade instruction."""
    brief = _session_brief_public()
    return jsonify({"schemaVersion": "session-brief-response-v1",
                    "asOf": _ai_now_iso(), "brief": brief,
                    "disclaimerJa": argus_session_brief.COMPLIANCE})


@app.route("/api/argus/session-brief/status")
def api_argus_session_brief_status():
    brief = _session_brief_public()
    return jsonify(argus_session_brief.status_doc(
        brief, now_iso=_ai_now_iso(),
        sources={"actionPriority": True, "eventRadar": bool(_MACRO_ANALYSIS),
                 "marketRegime": bool(_REGIME_CACHE.get("data")),
                 "institutionalIntelligence": bool(_INTEL_STORE),
                 "flowAttribution": True, "supplyDemand": True,
                 "positionExposure": False, "decisionQuality": False}))


# ── V11.11.0 Decision Quality foundation (server side = status + price history
# only; the RECORDS live device-local, the server never stores them) ─────────

@app.route("/api/argus/price-history")
def api_argus_price_history():
    """Public cached-only daily closes (dates newest-first) — the Decision
    Quality outcome updater runs ON DEVICE and needs forward closes. JP from
    the J-Quants bars cache, US from the Finnhub bars cache (both warmed by the
    collect cron). NEVER fetches here; cold cache → honest empty."""
    sym = (request.args.get("symbol") or "").strip().upper()
    mkt = (request.args.get("market") or ("JP" if sym[:1].isdigit() else "US")).upper()
    if not sym:
        return jsonify({"error": "symbol required"}), 400
    h = None
    if mkt == "JP":
        h = (_JQ_HISTORY_CACHE.get(sym[:4]) or {}).get("data")
    elif mkt == "US":
        h = (_US_HISTORY_CACHE.get(sym) or {}).get("data")
    return jsonify({"schemaVersion": "price-history-v1", "asOf": _ai_now_iso(),
                    "symbol": sym, "market": mkt,
                    "available": bool(h),
                    "dates": (h or {}).get("dates") or [],
                    "closes": (h or {}).get("closes") or [],
                    "noteJa": (None if h else
                               "日足キャッシュ未取得(平日の巡回で自動取得されます)。")})


@app.route("/api/argus/decision-quality/status")
def api_argus_decision_quality_status():
    """Public REDACTED status — architecture facts only. Records/outcomes are
    device-local (+encrypted vault); the server holds none by construction."""
    return jsonify(argus_decision_quality.public_status(
        enabled=True, storage_mode="local_only+encrypted_vault", now_iso=_ai_now_iso()))


@app.route("/api/argus/supply-demand")
def api_argus_supply_demand():
    """Public cached-only: 需給ランク for ?symbol= (single) or the JP watchlist
    (list). No fetch, no LLM, no trade instructions, nothing fabricated."""
    sym = (request.args.get("symbol") or "").strip().upper()
    now_iso = _ai_now_iso()
    if sym:
        mkt = (request.args.get("market")
               or ("JP" if sym[:1].isdigit() else "US")).upper()
        sig = _supply_demand_signal_for(sym, mkt)
        return jsonify({"schemaVersion": "supply-demand-response-v1", "asOf": now_iso,
                        "signal": sig, "disclaimerJa": sig["complianceNote"]})
    signals = _supply_demand_list(cap=12)
    return jsonify({"schemaVersion": "supply-demand-response-v1", "asOf": now_iso,
                    "count": len(signals), "signals": signals,
                    "disclaimerJa": "需給の状態評価であり売買指示ではない。"})


@app.route("/api/argus/supply-demand/status")
def api_argus_supply_demand_status():
    """Public observability: sources enabled/disabled with reasons, rank
    distribution, direct vs inferred counts. Missing JP realtime is intentional."""
    signals = _supply_demand_list(cap=20)
    return jsonify(argus_supply_demand.status_doc(
        signals, now_iso=_ai_now_iso(), sources=_supply_demand_sources()))


@app.route("/api/argus/flow-attribution")
def api_argus_flow_attribution():
    """Public cached-only: flow attribution for ?symbol= (single) or today's
    material watchlist movers (list). No fetch, no LLM, no trade instructions.
    Rate limiting: the global /api/argus/ before_request bucket."""
    sym = (request.args.get("symbol") or "").strip().upper()
    now_iso = _ai_now_iso()
    if sym:
        mkt = (request.args.get("market") or ("JP" if sym[:1].isdigit() else "US")).upper()
        rec = _flow_attribution_for(sym, mkt)
        return jsonify({"schemaVersion": "flow-attribution-response-v1",
                        "asOf": now_iso, "record": rec,
                        "disclaimerJa": rec["complianceNote"]})
    records = _flow_attribution_list(cap=12)
    return jsonify({"schemaVersion": "flow-attribution-response-v1",
                    "asOf": now_iso, "count": len(records), "records": records,
                    "disclaimerJa": "推定であり売買指示ではない。大口の実在は"
                                    "direct evidenceが無い限り断定しない。"})


@app.route("/api/argus/flow-attribution/status")
def api_argus_flow_attribution_status():
    """Public observability: how many assets scanned, evidence availability
    (JP moomoo flow is intentionally off — never a red alert), missing-evidence
    tally. Cached-only."""
    records = _flow_attribution_list(cap=40)
    us_flow = any(isinstance(((_PUSHED_QUOTES.get("US") or {}).get(s, {}).get("row") or {})
                             .get("flow", {}).get("bigNetRatio"), (int, float))
                  for s in list(_PUSHED_QUOTES.get("US") or {})[:20])
    avail = {"flow_us_bridge": us_flow,
             "flow_jp_bridge": False,      # intentionally disabled (Jul-3 incident)
             "jq_margin_weekly": bool(_JQ_MARGIN_CACHE),
             "jsf_daily_balance": bool(_JSF_CACHE.get("table")),
             "jq_daily_bars": bool(_JQ_HISTORY_CACHE),
             "institutional_signals": bool(_INTEL_STORE)}
    doc = argus_flow_attribution.status_doc(records, now_iso=_ai_now_iso(),
                                            source_availability=avail)
    return jsonify(doc)


@app.route("/api/argus/institutional-intelligence")
def api_argus_institutional_intelligence():
    """Public (cheap, cache-only): recent institutional intelligence + clusters.
    Only items with a RESOLVED named institution are surfaced as institutional."""
    inst = [i for i in _INTEL_STORE if i.get("institutionId")]
    return jsonify({"asOf": _ai_now_iso(), "schema": argus_research_mesh.SCHEMA,
                    "system": argus_research_mesh.SYSTEM_NAME,
                    "systemFull": argus_research_mesh.SYSTEM_NAME_FULL,
                    "taglineJa": argus_research_mesh.SYSTEM_TAGLINE_JA,
                    "institutionalCount": len(inst), "totalCollected": len(_INTEL_STORE),
                    "lastCollectedAt": _INTEL_LAST.get("ts"),
                    "items": inst[:30], "clusters": _intel_clusters()[:20]})


@app.route("/api/argus/institutional-intelligence/institutions")
def api_argus_intel_institutions():
    return jsonify({"count": len(argus_research_mesh.INSTITUTIONS),
                    "institutions": list(argus_research_mesh.INSTITUTIONS.values())})


@app.route("/api/argus/institutional-intelligence/source-health")
def api_argus_intel_source_health():
    """Honest source coverage (§24) — access class + last success per source."""
    per_feed = {f["feed"]: f for f in _INTEL_LAST.get("perFeed", [])}
    sources = []
    for sid in argus_research_mesh.SOURCE_RIGHTS:
        r = argus_research_mesh.source_rights(sid)
        r["lastDetected"] = _INTEL_LAST.get("perSource", {}).get(sid)
        sources.append(r)
    # active RSS feeds (validated allow-list) with their last-collection counts
    feeds = [{"feed": label, "source": sid,
              "fetched": per_feed.get(label, {}).get("fetched"),
              "ok": per_feed.get(label, {}).get("ok")}
             for sid, label, _url, _kind in _INTEL_FEEDS]
    rss_live = sum(1 for f in feeds if f.get("ok"))
    return jsonify({"asOf": _ai_now_iso(), "lastCollectedAt": _INTEL_LAST.get("ts"),
                    "coverage": {
                        "LICENSED_FEED": "NOT_CONFIGURED",
                        "PUBLIC_WEB": ("LIVE" if rss_live and rss_live == len(feeds)
                                       else "PARTIAL" if rss_live else "WARMING"),
                        "OFFICIAL_SOURCES": "LIVE",
                        "SUBSCRIBER_CAPTURE": "ENABLED",
                        "INSTITUTION_WATCHLIST": "ACTIVE",
                    },
                    "activeFeeds": feeds, "activeFeedCount": len(feeds), "feedsLive": rss_live,
                    "sources": sources,
                    "licensedFeeds": argus_licensed_feeds.all_health()})


@app.route("/api/argus/events/<symbol>/institutional-intelligence")
def api_argus_event_intel(symbol):
    """Per-asset institutional intelligence (cheap) — items naming the symbol, with
    causal role vs the symbol's recent move. Goes INSIDE the asset card. Public GET:
    reads the already-collected intel store only (no fetch, no LLM)."""
    symu = str(symbol).strip().upper()
    if not symu:
        return jsonify({"error": "symbol_required",
                        "messageJa": "銘柄コードを指定してください。"}), 400
    reg = (_REGIME_CACHE.get("data") or {})
    move = _ai_now_iso()
    out = []
    for it in _INTEL_STORE:
        if symu not in (it.get("linkedAssets") or []):
            continue
        link = argus_research_mesh.link_to_event(it, {"eventId": symu, "linkedAssets": [symu], "moveStartedAt": move})
        out.append({"title": it["title"], "titleJa": it.get("titleJa"),
                    "institutionId": it.get("institutionId"),
                    "category": it.get("category"), "contentType": it.get("contentType"),
                    "publishedAt": it.get("publishedAt"), "accessClass": it["accessClass"],
                    "canonicalUrl": it.get("canonicalUrl"), "stance": it.get("stance"),
                    "relation": link["causalRole"], "relationLabelJa": link["relationLabelJa"],
                    "isNamedView": link["isNamedView"], "notConfirmed": link["notConfirmed"]})
    return jsonify({"symbol": symu, "count": len(out), "items": out[:8]})


@app.route("/api/argus/institutional-intelligence/capture", methods=["POST"])
def api_argus_intel_capture():
    """Owner Share/Capture (§3B) — title/link/excerpt/institution only. NEVER
    credentials/cookies/tokens/authenticated content."""
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    b = request.get_json(silent=True) or {}
    for forbidden in ("credentials", "cookies", "token", "session", "password"):
        if forbidden in b:
            return jsonify({"error": "forbidden_field", "field": forbidden}), 400
    raw = {"sourceId": "owner_capture", "title": (b.get("title") or "")[:300],
           "canonicalUrl": (b.get("url") or "")[:600], "author": b.get("analyst"),
           "publicSnippet": (b.get("excerpt") or "")[:500],
           "linkedAssets": b.get("relatedAssets") or [], "firstDetectedAt": _ai_now_iso(), "fetchedAt": _ai_now_iso()}
    item = argus_research_mesh.normalize_item(raw)
    _INTEL_STORE.insert(0, item)
    del _INTEL_STORE[_INTEL_STORE_MAX:]
    return jsonify({"ok": True, "intelligenceId": item["intelligenceId"], "accessClass": item["accessClass"]})


_MISSED_INTEL = []
_INST_ALIAS_OVERLAY = []   # §22 owner-approved alias additions (persisted; re-applied at load)

def _symbol_name_map():
    """SYMBOL → display name, for the missed-intel replay (does the headline name it?)."""
    out = {}
    for x in (_JP_WATCHLIST + _US_WATCHLIST):
        out[str(x["symbol"]).upper()] = x.get("name") or ""
    return out

@app.route("/api/argus/institutional-intelligence/missed", methods=["POST"])
def api_argus_intel_missed():
    """Owner 'missed important info' feedback (§22) — replays the detection rules to
    report WHY it was missed, links it to the nearest root event, and records it.
    Never auto-retrains (a fix is suggested; applying it is a separate manual step)."""
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    b = request.get_json(silent=True) or {}
    sym = (b.get("symbol") or "").upper()
    diag = argus_research_mesh.diagnose_miss(
        url=b.get("url"), title=b.get("title") or b.get("why"), institution=b.get("institution"),
        symbol=sym, known_symbol_names=_symbol_name_map())
    # nearest root event = an active downside incident on the same symbol, if any
    root = None
    try:
        for inc in (get_downside_incidents().get("incidents") or []):
            if str(inc.get("symbol")).upper() == sym:
                root = {"eventId": sym, "incidentId": inc.get("incidentId"), "severity": inc.get("severity")}
                break
    except Exception:
        pass
    rec = {"url": (b.get("url") or "")[:600], "institution": b.get("institution"),
           "symbol": sym, "title": (b.get("title") or "")[:300], "whyJa": (b.get("why") or "")[:400],
           "at": _ai_now_iso(), "diagnosis": diag, "rootEvent": root, "status": "recorded"}
    _MISSED_INTEL.insert(0, rec)
    del _MISSED_INTEL[200:]
    _intel_persist()
    return jsonify({"ok": True, "recorded": rec})

@app.route("/api/argus/institutional-intelligence/missed", methods=["GET"])
def api_argus_intel_missed_list():
    """Missed-intelligence log + metrics (count by likely cause). Public read-only."""
    by_cause = {}
    for m in _MISSED_INTEL:
        c = ((m.get("diagnosis") or {}).get("likelyCause")) or "unknown"
        by_cause[c] = by_cause.get(c, 0) + 1
    return jsonify({"count": len(_MISSED_INTEL), "byCause": by_cause,
                    "items": _MISSED_INTEL[:30], "aliasOverlaySize": len(_INST_ALIAS_OVERLAY)})

@app.route("/api/argus/institutional-intelligence/missed/apply", methods=["POST"])
def api_argus_intel_missed_apply():
    """Admin: apply a suggested fix from a missed-intel diagnosis (§22 — MANUAL).
    Currently supports adding an institution alias. Persisted as an OVERLAY over the
    seed; re-applied at load. Never edits the seed, never auto-retrains."""
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    b = request.get_json(silent=True) or {}
    iid, alias = b.get("institutionId"), b.get("alias")
    if not argus_research_mesh.register_institution_alias(iid, alias):
        return jsonify({"ok": False, "reason": "invalid_or_too_short_alias"}), 200
    entry = {"institutionId": str(iid).lower(), "alias": str(alias).lower(), "at": _ai_now_iso()}
    if entry not in _INST_ALIAS_OVERLAY:
        _INST_ALIAS_OVERLAY.append(entry)
        _intel_persist()
    return jsonify({"ok": True, "applied": entry, "overlaySize": len(_INST_ALIAS_OVERLAY)})

_intel_restore()        # §27 reload any persisted intel at startup (avoids WARMING)


@app.route("/api/argus/institutional-intelligence/collect", methods=["POST"])
def api_argus_intel_collect():
    """Admin/cron: run the public-feed collection (the ONLY fetch path)."""
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    out = collect_institutional_intel()
    # v11.10.0: warm the supply/demand caches here (admin path — fetching is
    # allowed). Without this, a fresh deploy leaves _JQ_MARGIN_CACHE/_JSF_CACHE
    # cold and every 需給ランク reads Unknown until the owner happens to tap
    # エントリー診断. Both fetchers honor their own TTLs (12h margin / 6h JSF),
    # so this 30-min cron is a cheap no-op most runs.
    warmed = {"jsf": False, "margin": 0}
    try:
        table, _d = _jsf_balance_table()
        warmed["jsf"] = bool(table)
    except Exception:
        pass
    for s in _JP_WATCHLIST:
        try:
            code4 = str(s.get("symbol") or "")[:4]
            if code4.isdigit() or (code4 and code4[0].isdigit()):
                if _jq_weekly_margin(code4):
                    warmed["margin"] += 1
                _jq_price_history(code4)   # daily bars → avgVolume/daysToCover/runup
        except Exception:
            continue
    for s in _US_WATCHLIST:                    # v11.11.0: US bars for 需給/outcome
        try:
            if _us_price_history(str(s.get("symbol") or "")):
                warmed["usBars"] = warmed.get("usBars", 0) + 1
        except Exception:
            continue
    out["supplyDemandWarm"] = warmed
    return jsonify(out)


# ━━━ V11.5.3 C.A.O.S. Watchtower — Core Portfolio source universe + patrol ━━━
# The owner's June-19-news-as-current-lead complaint exposed two gaps: (1) no
# freshness gate (fixed in argus_news_freshness + mover cause), (2) no defined
# "who do we watch, where, how often" registry. This block wires the pure
# universe/source/plan modules to real collection, tracks per-source freshness,
# and exposes it all as public cache-only status. Public GETs never fetch/LLM;
# the admin refresh is the ONLY patrol path (cron: caos-watchtower.yml).

_US_STOCK_NEWS_CACHE = {}          # sym -> {"expires": float}
_US_STOCK_NEWS_TTL = 30 * 60


def _google_news_us_rss(query):
    """Google News US RSS — DISCOVERY LAYER for US names (same parser as JP;
    items resolve to their true publisher via argus_caos_source_universe)."""
    try:
        url = ("https://news.google.com/rss/search?q=" + quote(query)
               + "&hl=en-US&gl=US&ceid=US:en")
        xml = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8).text
        return _parse_rss(xml, "google_news_us", _ai_now_iso())
    except Exception:
        return []


def _us_stock_news_intel(pairs):
    """US counterpart of _jp_stock_news_intel — per-symbol English headlines into
    _INTEL_STORE (metadata only, symbolHint for association). 30-min per-symbol cache."""
    now = time.time()
    pushed = 0
    seen = {(it.get("title") or "") for it in _INTEL_STORE}
    for sym, name in pairs:
        sym = str(sym).upper()
        nm = (name or sym).strip()
        if not sym:
            continue
        c = _US_STOCK_NEWS_CACHE.get(sym)
        if c and now < c["expires"]:
            continue
        _US_STOCK_NEWS_CACHE[sym] = {"expires": now + _US_STOCK_NEWS_TTL}
        for r in _google_news_us_rss(f'"{nm}" stock (earnings OR news OR falls OR surges)')[:6]:
            t = r.get("title") or ""
            if not t or t in seen:
                continue
            seen.add(t)
            r = dict(r)
            r["symbolHint"] = sym
            r["lang"] = "en"
            r["corroboration"] = "single"
            r.setdefault("intelligenceId", hashlib.md5(
                f"google_news_us|{r.get('canonicalUrl')}|{t}".encode()).hexdigest()[:16])
            _INTEL_STORE.append(r)
            pushed += 1
    if len(_INTEL_STORE) > _INTEL_STORE_MAX:
        del _INTEL_STORE[:len(_INTEL_STORE) - _INTEL_STORE_MAX]
    return pushed


_WATCHTOWER_STATE = {"restored": False, "lastRefreshAt": None,
                     "sources": {}, "lastSummary": None}
_WATCHTOWER_FILE = "/tmp/argus_watchtower.json"


def _watchtower_persist():
    try:
        with open(_WATCHTOWER_FILE, "w") as f:
            json.dump({k: _WATCHTOWER_STATE[k] for k in
                       ("lastRefreshAt", "sources", "lastSummary")},
                      f, ensure_ascii=False, default=str)
    except Exception:
        pass


def _watchtower_restore_once():
    if _WATCHTOWER_STATE["restored"]:
        return
    _WATCHTOWER_STATE["restored"] = True
    try:
        with open(_WATCHTOWER_FILE) as f:
            blob = json.load(f)
        for k in ("lastRefreshAt", "sources", "lastSummary"):
            if blob.get(k) is not None:
                _WATCHTOWER_STATE[k] = blob[k]
    except Exception:
        pass


def _watchtower_configured():
    """Which API paths are configured — boolean flags only, never values."""
    return {"JQUANTS_API_KEY": bool(_JQUANTS_API_KEY),
            "FINNHUB_API_KEY": bool(FINNHUB_API_KEY),
            "TWELVEDATA_API_KEY": bool(_TWELVEDATA_API_KEY),
            "FRED_API_KEY": bool(_FRED_API_KEY)}


def _watchtower_plan_build(now_iso, src_uni=None):
    src_uni = src_uni or argus_caos_source_universe.build_universe(_watchtower_configured(), now_iso)
    _mover_causes_restore_once()
    try:
        events = (_build_dashboard_events(limit=8) or {}).get("items") or []
    except Exception:
        events = []
    return argus_caos_watchtower_plan.build_plan(
        watchlist_jp=list(_JP_WATCHLIST), watchlist_us=list(_US_WATCHLIST),
        movers=_mover_causes_today(), macro_events=events,
        universe_sources=src_uni["sources"], now_iso=now_iso)


@app.route("/api/argus/investment-universe")
def api_argus_investment_universe():
    """Public-safe: Core Portfolio asset-class universe. Static — no fetch/LLM,
    no holdings/amounts."""
    return jsonify(argus_investment_universe.build_universe(_ai_now_iso()))


@app.route("/api/argus/caos/source-universe")
def api_argus_caos_source_universe():
    """Public-safe: per-asset-class source registry (tier/rights/status). Env
    presence is reported as booleans via status only — never values."""
    return jsonify(argus_caos_source_universe.build_universe(
        _watchtower_configured(), _ai_now_iso()))


@app.route("/api/argus/caos/watchtower-plan")
def api_argus_caos_watchtower_plan():
    """Public cache-only: what C.A.O.S. will patrol next (movers/watchlist/events/
    Core Portfolio baseline). Built from stored records — never fetches."""
    return jsonify(_watchtower_plan_build(_ai_now_iso()))


@app.route("/api/argus/caos-watchtower/status")
def api_argus_caos_watchtower_status():
    """Public cache-only: per-source freshness (last check / newest item age /
    items today) + per-asset-class coverage + honest alerts."""
    _watchtower_restore_once()
    now_iso = _ai_now_iso()
    src_uni = argus_caos_source_universe.build_universe(_watchtower_configured(), now_iso)
    today = now_iso[:10]
    # newest item + today count per sourceId from the intel store (metadata only).
    # Compare by EPOCH — feeds mix RFC-822 pubDates with ISO stamps, and a string
    # compare across formats picks the wrong "newest" (36h-old NHK bug).
    newest, newest_ep, today_counts = {}, {}, {}
    for it in list(_INTEL_STORE):
        sid = it.get("sourceId")
        if not sid:
            continue
        ts = it.get("publishedAt") or it.get("firstDetectedAt")
        ep = argus_news_freshness._epoch(ts)
        if ep is not None and ep > newest_ep.get(sid, 0.0):
            newest_ep[sid] = ep
            newest[sid] = str(ts)
        if str(it.get("firstDetectedAt") or "")[:10] == today:
            today_counts[sid] = today_counts.get(sid, 0) + 1
    # API-source liveness from their own engine caches (no fetch here)
    api_alive = {"jquants_tdnet": bool(_TDNET_OFFICIAL_CACHE.get("data")),
                 "finnhub_company_news": bool(_FINN_CACHE),
                 "coingecko": True}   # crypto quotes run 24/7 via market loop
    sources_out = []
    stats = _WATCHTOWER_STATE.get("sources") or {}
    for s in src_uni["sources"]:
        sid = s["sourceId"]
        st = stats.get(sid) or {}
        status = s["status"]
        newest_at = newest.get(sid)
        age_h = argus_news_freshness.age_hours(newest_at, now_iso) if newest_at else None
        if status == "live":
            if sid in api_alive and not api_alive[sid]:
                status = "partial"
            # a feed source with no success today cannot claim live
            if s.get("collectionMethod") in ("rss", "sitemap", "search_discovery") \
                    and not today_counts.get(sid) and (age_h is None or age_h > 24):
                status = "stale"
        sources_out.append({
            "sourceId": sid, "name": s["name"], "assetClasses": s["assetClasses"],
            "sourceTier": s["sourceTier"], "rightsClass": s["rightsClass"],
            "isDiscoveryLayer": s.get("isDiscoveryLayer", False),
            "status": status,
            "lastCheckAt": st.get("lastCheckAt") or _WATCHTOWER_STATE.get("lastRefreshAt"),
            "newestPublishedAt": newest_at,
            "newestAgeHours": round(age_h, 1) if isinstance(age_h, (int, float)) else None,
            "itemsToday": today_counts.get(sid, 0),
            "successRate24h": st.get("successRate24h"),
            "limitationsJa": s.get("limitationsJa") or []})
    # per-asset-class coverage
    coverage = {}
    for ac in argus_investment_universe.REQUIRED_CLASSES:
        cls_sources = [x for x in sources_out if ac in x["assetClasses"]]
        live = [x for x in cls_sources if x["status"] == "live"]
        ages = [x["newestAgeHours"] for x in live if isinstance(x["newestAgeHours"], (int, float))]
        coverage[ac] = {"totalSources": len(cls_sources), "liveSources": len(live),
                        "newestItemAgeHours": min(ages) if ages else None,
                        "status": ("live" if live else "partial" if cls_sources else "missing")}
    alerts = []
    jp_live = [x for x in sources_out if "JP_EQUITY" in x["assetClasses"]
               and x["status"] == "live"
               and x["sourceTier"] in ("official_regulatory", "official_corporate",
                                       "central_bank_or_government", "wire_service",
                                       "reputable_financial_media")]
    if not jp_live:
        alerts.append({"severity": "high", "messageJa":
                       "日本株の公式/プロメディアのliveソースがゼロ — ニュース監視が機能していない可能性。"})
    us_live = [x for x in sources_out if "US_EQUITY" in x["assetClasses"]
               and x["status"] == "live"
               and (x["sourceTier"].startswith("official") or
                    x["sourceId"] == "finnhub_company_news" or
                    x["sourceTier"] in ("wire_service", "reputable_financial_media"))]
    if not us_live:
        alerts.append({"severity": "high", "messageJa":
                       "米国株の公式/企業ニュースのliveソースがゼロ — ニュース監視が機能していない可能性。"})
    for ac in ("GOLD_GLD", "FX_USDJPY", "CRYPTO_BTC_ETH"):
        if coverage[ac]["status"] != "live":
            alerts.append({"severity": "info", "messageJa":
                           f"{ac}の監視はpartial(専門ソースの一部が未構成)。"})
    # v11.5.5 patrol references — the compact proof the patrol is alive (full
    # detail lives at /api/argus/caos/patrol-health)
    patrol_ref = None
    try:
        _sweep_state_restore_once()
        _patrol_ledger_restore_once()
        doc = _PATROL_LEDGER["doc"]
        runs = doc.get("runs", [])
        vio, _ = _old_primary_violations(now_iso)
        summ = argus_caos_patrol_store.summarize(doc, now_iso,
                                                 old_primary_violations=len(vio))
        st, _al = argus_caos_patrol_store.derive_status(
            now_iso=now_iso, last_patrol_at=(runs[-1]["at"] if runs else None),
            summary=summ, is_weekday=datetime.now(pytz.utc).weekday() < 5,
            has_runs=bool(runs))
        deep = [s for s in doc.get("sweeps", []) if s.get("kind") in ("deep", "investigate")]
        patrol_ref = {"status": st,
                      "lastPatrolAt": runs[-1]["at"] if runs else None,
                      "lastDeepSweepAt": deep[-1]["at"] if deep else None,
                      "baselineSweeps24h": summ["baselineSweeps24h"],
                      "deepSweeps24h": summ["deepSweeps24h"],
                      "emptyDeepSweepRuns24h": summ["emptyDeepSweepRuns24h"],
                      "oldPrimaryViolations": summ["oldPrimaryViolations"],
                      "baselineOnly": bool(runs and not runs[-1].get("deepSweeps")
                                           and not int(runs[-1].get("activeMovers") or 0))}
    except Exception:
        pass
    return jsonify({
        "schemaVersion": "caos-watchtower-status-v1", "asOf": now_iso,
        "sourceUniverseVersion": src_uni["schemaVersion"],
        "investmentUniverseVersion": argus_investment_universe.SCHEMA_VERSION,
        "lastRefreshAt": _WATCHTOWER_STATE.get("lastRefreshAt"),
        "patrolHealth": patrol_ref,
        "sources": sources_out, "coverageByAssetClass": coverage, "alerts": alerts,
        "noteJa": "near-real-time監視(15分巡回)。Bloomberg/Reuters端末の完全代替ではない。"
                  "公開GETは取得を起動しない。"})


@app.route("/api/argus/admin/caos-watchtower/refresh", methods=["POST"])
def api_argus_admin_caos_watchtower_refresh():
    """Admin/cron: the patrol. Fetch allow-listed feeds + targeted discovery for
    urgent/high targets, classify freshness, queue translations. METADATA ONLY —
    no article bodies, no LLM here, no raw provider blobs stored."""
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    try:
        return jsonify(_watchtower_refresh_run())
    except Exception as e:
        # never a bare HTML 500 — the cron log must show WHAT failed (no secrets)
        add_log(f"[watchtower] refresh failed: {type(e).__name__}: {str(e)[:160]}")
        return jsonify({"ok": False, "schemaVersion": "caos-watchtower-refresh-v1",
                        "error": f"{type(e).__name__}: {str(e)[:200]}"}), 500


def _watchtower_refresh_run():
    _watchtower_restore_once()
    _news_ja_restore_once()
    now_iso = _ai_now_iso()
    src_uni = argus_caos_source_universe.build_universe(_watchtower_configured(), now_iso)
    plan = _watchtower_plan_build(now_iso, src_uni)
    # 1) allow-listed public feeds (Bloomberg/Nikkei/NHK/CNBC/.../CoinDesk/BOJ/Fed/SEC)
    intel = collect_institutional_intel()
    # 2) targeted per-symbol discovery for urgent/high equity targets
    jp_pairs, us_pairs = [], []
    for t in plan["targets"]:
        if t["priority"] not in ("urgent", "high") or not t.get("symbol"):
            continue
        if t["assetClass"] == "JP_EQUITY":
            jp_pairs.append((t["symbol"], t["name"]))
        elif t["assetClass"] == "US_EQUITY":
            us_pairs.append((t["symbol"], t["name"]))
    pushed_jp = _jp_stock_news_intel(jp_pairs[:12])
    pushed_us = _us_stock_news_intel(us_pairs[:8])
    for sym, _nm in us_pairs[:6]:            # Finnhub company news (cached per symbol)
        try:
            _finnhub_catalyst(sym)
        except Exception:
            pass
    try:
        get_market_news()                    # Finnhub general (10-min cache)
    except Exception:
        pass
    # 3) freshness pass over the store: count old items (kept as background/過去材料)
    stale_demoted = 0
    for it in list(_INTEL_STORE):
        fr = argus_news_freshness.classify(
            it.get("publishedAt") or it.get("firstDetectedAt"), now_iso)
        if fr["freshness"] in ("old", "stale"):
            stale_demoted += 1
    # 4) queue NEW English titles for the visible-first translation cron
    queued_tr = 0
    for it in list(_INTEL_STORE)[:80]:
        t = it.get("title") or ""
        if argus_news_i18n.looks_translatable(t) and not argus_news_i18n.is_translated(t, _NEWS_JA_CACHE):
            _NEWS_JA_SEEN.append(t)
            queued_tr += 1
    # 5) per-source stats
    stats = _WATCHTOWER_STATE.setdefault("sources", {})
    for pf in (intel.get("perFeed") or []):
        sid = pf.get("source")
        e = stats.setdefault(sid, {"attempts": 0, "successes": 0})
        e["attempts"] = int(e.get("attempts") or 0) + 1
        e["successes"] = int(e.get("successes") or 0) + (1 if pf.get("ok") else 0)
        e["lastCheckAt"] = now_iso
        e["successRate24h"] = round(e["successes"] / max(1, e["attempts"]), 2)
    for sid, pushed in (("google_news_jp", pushed_jp), ("google_news_us", pushed_us)):
        e = stats.setdefault(sid, {"attempts": 0, "successes": 0})
        e["attempts"] = int(e.get("attempts") or 0) + 1
        e["successes"] = int(e.get("successes") or 0) + 1
        e["lastCheckAt"] = now_iso
        e["successRate24h"] = round(e["successes"] / max(1, e["attempts"]), 2)
    # per-asset-class new-item counts (sourceId → classes via the universe)
    cls_of = {s["sourceId"]: s["assetClasses"] for s in src_uni["sources"]}
    by_class = {}
    for pf in (intel.get("perFeed") or []):
        for ac in cls_of.get(pf.get("source"), []):
            by_class[ac] = by_class.get(ac, 0) + int(pf.get("new") or 0)
    unconfigured = [s["sourceId"] for s in src_uni["sources"]
                    if s["status"] in ("not_configured", "requires_contract", "disabled")]
    _WATCHTOWER_STATE["lastRefreshAt"] = now_iso
    summary = {
        "schemaVersion": "caos-watchtower-refresh-v1", "asOf": now_iso,
        "targetsChecked": len(plan["targets"]),
        "sourcesChecked": len(intel.get("perFeed") or []) + 2,
        "newItems": int(intel.get("collected") or 0) + pushed_jp + pushed_us,
        "freshItems": sum(1 for it in list(_INTEL_STORE)[:120]
                          if argus_news_freshness.classify(
                              it.get("publishedAt") or it.get("firstDetectedAt"),
                              now_iso)["freshness"] in ("fresh", "recent")),
        "staleItemsDemoted": stale_demoted,
        "translationQueued": queued_tr,
        "unconfiguredSources": unconfigured,
        "byAssetClass": by_class,
        "bySource": intel.get("perSource") or {},
        "limitationsJa": ["メタデータのみ取得(本文なし)", "near-real-time(完全リアルタイムではない)"],
    }
    _WATCHTOWER_STATE["lastSummary"] = {k: summary[k] for k in
                                        ("asOf", "targetsChecked", "newItems", "freshItems")}
    # V11.5.4: deep sweeps for due critical/urgent patrol targets (movers first)
    deep_done = []
    active_movers = 0
    try:
        _sweep_state_restore_once()               # v11.5.5: survive dyno restarts
        active_movers = len(_mover_causes_today())
        patrol = argus_caos_patrol.build_patrol_plan(
            plan["targets"], _SWEEP_STATE.get("bySymbol") or {}, now_iso)
        picked = argus_caos_patrol.pick_due_targets(patrol, max_deep=4, max_light=0)
        for t in picked["deep"]:
            if not t.get("symbol") or t["assetClass"] not in ("JP_EQUITY", "US_EQUITY"):
                continue
            try:
                res = _caos_run_sweep(t["symbol"],
                                      "JP" if t["assetClass"] == "JP_EQUITY" else "US",
                                      name=t.get("name"), budget_sec=8, probe_articles=1)
                deep_done.append({"symbol": t["symbol"], "status": res["status"],
                                  "fresh": len(res["freshItems"])})
                argus_caos_patrol_store.record_sweep(
                    _PATROL_LEDGER["doc"], now_iso=now_iso, symbol=t["symbol"],
                    market="JP" if t["assetClass"] == "JP_EQUITY" else "US",
                    kind="deep", status=res["status"], fresh=len(res["freshItems"]))
            except Exception:
                continue
        summary["deepSweeps"] = deep_done
        _SWEEP_STATE["lastPatrolSweep"] = {"asOf": now_iso, "deepSweeps": deep_done}
        _sweep_state_persist()
    except Exception:
        pass
    # V11.5.5 patrol ledger: every run is recorded — the feed collection IS the
    # Core Portfolio baseline check (all 9 classes' sources), so a mover-less run
    # is an honest baseline-only success, never a silent one.
    try:
        _patrol_ledger_restore_once()
        pf = intel.get("perFeed") or []
        note = ("" if deep_done else
                "active mover sweepなし。Core Portfolio baselineのみ確認。" if not active_movers
                else "急変銘柄はcadence内のためdeep sweep省略(直近実施済み)。")
        argus_caos_patrol_store.record_run(
            _PATROL_LEDGER["doc"], now_iso=now_iso, ok=True,
            deep_sweeps=len(deep_done), baseline_checked=bool(pf),
            fresh_items=int(summary.get("freshItems") or 0),
            new_items=int(summary.get("newItems") or 0),
            source_success=sum(1 for x in pf if x.get("ok")),
            source_errors=sum(1 for x in pf if not x.get("ok")),
            active_movers=active_movers, note_ja=note)
        newest_by_src = {}
        for it in list(_INTEL_STORE)[:400]:
            sid = it.get("sourceId")
            ts = it.get("publishedAt") or it.get("firstDetectedAt")
            ep = argus_news_freshness._epoch(ts)
            if sid and ep and ep > (newest_by_src.get(sid, (0, None))[0]):
                newest_by_src[sid] = (ep, str(ts))
        for x in pf:
            sid = x.get("source")
            argus_caos_patrol_store.update_source(
                _PATROL_LEDGER["doc"], sid, now_iso=now_iso, ok=bool(x.get("ok")),
                newest_published_at=(newest_by_src.get(sid) or (0, None))[1])
        _patrol_ledger_persist()
    except Exception:
        pass
    _watchtower_persist()
    return summary


# ━━━ V11.5.4 Always-On Deep Patrol / Investigate Again Now ━━━━━━━━━━━━━━━━━━
# The owner's directive: go as far as the PUBLIC web allows and never decide
# "this is enough". The sweep walks official → professional metadata →
# discovery → public article probe → alternative chasing. A source that blocks
# us (403/login/subscription) is recorded as blocked — we do NOT bypass it —
# and we immediately chase official documents and sibling outlets instead.
# investigate-now is a PUBLIC POST doing a strictly bounded immediate sweep
# (no LLM ever on this path); the patrol runs the same sweep without clicks.

_SWEEP_STATE = {"restored": False, "bySymbol": {}, "lastInvestigateNow": None,
                "lastPatrolSweep": None}
_SWEEP_STATE_FILE = "/tmp/argus_caos_sweeps.json"
_SWEEP_LOCK = threading.Lock()           # one sweep at a time (public POST safety)
_INVESTIGATE_RL = {}                     # "ip|MKT:SYM" -> epoch
_INVESTIGATE_RL_SEC = 60                 # per IP+symbol
_INVESTIGATE_COOLDOWN_SEC = 120          # per symbol, any caller
_PROBE_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")


def _sweep_state_persist():
    try:
        with open(_SWEEP_STATE_FILE, "w") as f:
            json.dump({k: _SWEEP_STATE[k] for k in
                       ("bySymbol", "lastInvestigateNow", "lastPatrolSweep")},
                      f, ensure_ascii=False, default=str)
    except Exception:
        pass


def _sweep_state_restore_once():
    if _SWEEP_STATE["restored"]:
        return
    _SWEEP_STATE["restored"] = True
    try:
        with open(_SWEEP_STATE_FILE) as f:
            blob = json.load(f)
        for k in ("bySymbol", "lastInvestigateNow", "lastPatrolSweep"):
            if blob.get(k) is not None:
                _SWEEP_STATE[k] = blob[k]
    except Exception:
        pass


def _probe_article(url, timeout=6):
    """Stage-4 public article probe: fetch a PUBLICLY served page, detect
    login/paywall blocks, extract metadata + snippet (<=240 chars). Never stores
    the body; never sends credentials; never bypasses a block."""
    try:
        r = requests.get(url, headers={"User-Agent": _PROBE_UA}, timeout=timeout,
                         allow_redirects=True)
        html = r.text[:400_000]
        meta = argus_caos_source_sweep.extract_article_metadata(html, str(r.url))
        verdict = argus_caos_source_sweep.detect_block(
            r.status_code, html, meta.get("isAccessibleForFree"))
        return verdict, meta, str(r.url)
    except Exception:
        return "unreachable", {}, url


def _caos_run_sweep(symbol, market, name=None, budget_sec=12, probe_articles=3,
                    force_discovery=True):
    """The maximum-available source sweep for one symbol. Stages: official →
    professional metadata → discovery → public article probe → alternative
    chasing for blocked items. Time-budgeted; each stage failure moves on.
    NEVER calls an LLM. Updates the intel store + mover cause immediately."""
    t0 = time.time()
    now_iso = _ai_now_iso()
    symu, mkt = str(symbol).upper(), str(market).upper()
    nm = (name or (_ENTITY_PROFILES.get(symu) or {}).get("name") or symu)
    ac = argus_investment_universe.asset_class_of_symbol(symu, mkt)
    searched, found, blocked, alternatives = [], [], [], []
    status = "completed"

    def over_budget():
        return (time.time() - t0) > budget_sec

    # ── Stage 1: official / primary (cached-first; live TDnet deferred so a slow
    # official API can never starve the discovery stage of the whole budget) ──
    tdnet_live_pending = False

    def _tdnet_scan(snap):
        n = 0
        for it in ((snap or {}).get("items") or [])[:150]:
            code = str(it.get("code") or it.get("symbol") or "")
            if symu in code:
                found.append({"title": f"適時開示: {it.get('title') or it.get('subject') or ''}",
                              "publishedAt": it.get("time") or it.get("datetime"),
                              "url": str(it.get("url") or "")[:300], "source": "tdnet"})
                n += 1
        return n

    try:
        if mkt == "JP":
            searched.append("tdnet")
            snap = _tdnet_recent_cached_only()
            if snap:
                _tdnet_scan(snap)
            else:
                tdnet_live_pending = True          # fetch after discovery if budget left
            searched.append("official_events_store")
            for oe in list(_OFFICIAL_EVENTS.values())[:200] if isinstance(_OFFICIAL_EVENTS, dict) else []:
                if str(oe.get("symbol") or "").upper() == symu:
                    found.append({"title": f"公式イベント: {oe.get('titleJa') or oe.get('title') or ''}",
                                  "publishedAt": oe.get("disclosedAt") or oe.get("asOf"),
                                  "url": "", "source": "tdnet"})
        else:
            searched.append("sec_edgar")
            try:
                filings, _st = _sec_filings(symu)
                for f in (filings or [])[:5]:
                    found.append({"title": f"SEC filing: {f.get('form')}",
                                  "publishedAt": f.get("filingDate"),
                                  "url": str(f.get("url") or "")[:300], "source": "sec.gov"})
            except Exception:
                pass
    except Exception:
        pass

    # ── Stage 2: professional metadata already collected by the 24/7 feeds ──
    try:
        searched.append("caos_feeds(nikkei/reuters/nhk/bloomberg/cnbc/coindesk)")
        nml = str(nm)
        for it in list(_INTEL_STORE)[:400]:
            la = {str(a).upper() for a in (it.get("linkedAssets") or [])}
            hint = str(it.get("symbolHint") or "").upper()
            title = str(it.get("title") or "")
            if symu in la or hint == symu or (len(nml) >= 3 and nml in title):
                found.append({"title": title, "publishedAt": it.get("publishedAt") or it.get("firstDetectedAt"),
                              "url": str(it.get("canonicalUrl") or "")[:300],
                              "source": it.get("sourceId") or ""})
    except Exception:
        pass

    # ── Stage 3: discovery search (fresh fetch — bypass the 30-min cache) ──
    if not over_budget():
        try:
            if mkt == "JP":
                searched.append("google_news_jp")
                if force_discovery:
                    _JP_STOCK_NEWS_CACHE.pop(symu, None)
                _jp_stock_news_intel([(symu, nm)])
            else:
                searched.append("google_news_us")
                if force_discovery:
                    _US_STOCK_NEWS_CACHE.pop(symu, None)
                _us_stock_news_intel([(symu, nm)])
            # per-symbol items land anywhere in the store (append vs insert(0)) —
            # scan the WHOLE bounded store, not just the head
            for it in list(_INTEL_STORE):
                if str(it.get("symbolHint") or "").upper() == symu:
                    found.append({"title": it.get("title") or "",
                                  "publishedAt": it.get("publishedAt") or it.get("firstDetectedAt"),
                                  "url": str(it.get("canonicalUrl") or "")[:300],
                                  "source": "google_news_jp" if mkt == "JP" else "google_news_us"})
            # Google News ranks by RELEVANCE, so old high-relevance stories can crowd
            # out this morning's news. A second when:2d query forces the recent window
            # (行けるところまで行く — never settle for the relevance page alone).
            if not over_budget():
                searched.append("google_news_recent(when:2d)")
                recent_rows = (_google_news_jp_rss(f'"{nm}" when:2d') if mkt == "JP"
                               else _google_news_us_rss(f'"{nm}" when:2d'))
                seen_titles = {str(x.get("title") or "") for x in _INTEL_STORE}
                for r in recent_rows[:8]:
                    t = str(r.get("title") or "")
                    if not t:
                        continue
                    found.append({"title": t, "publishedAt": r.get("publishedAt"),
                                  "url": str(r.get("canonicalUrl") or "")[:300],
                                  "source": "google_news_jp" if mkt == "JP" else "google_news_us"})
                    if t not in seen_titles:
                        rr = dict(r)
                        rr["symbolHint"] = symu
                        rr["lang"] = "ja" if mkt == "JP" else "en"
                        rr["corroboration"] = "single"
                        rr.setdefault("intelligenceId", hashlib.md5(
                            f"gnews_recent|{rr.get('canonicalUrl')}|{t}".encode()).hexdigest()[:16])
                        _INTEL_STORE.append(rr)
            if mkt == "US":
                searched.append("finnhub_company_news")
                try:
                    res = _finnhub_catalyst(symu)
                    fin = res[0] if isinstance(res, tuple) else res
                    for n in ((fin or {}).get("news") or [])[:8]:
                        ts = n.get("datetime")
                        iso = (datetime.fromtimestamp(ts, pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                               if isinstance(ts, (int, float)) and ts > 0 else None)
                        found.append({"title": str(n.get("headline") or ""), "publishedAt": iso,
                                      "url": str(n.get("url") or "")[:300],
                                      "source": n.get("source") or "Finnhub"})
                except Exception:
                    pass
        except Exception:
            pass
    else:
        status = "partial"

    # deferred live TDnet (only when the cache was cold and budget remains)
    if tdnet_live_pending and not over_budget():
        try:
            _tdnet_scan(get_tdnet_recent())
        except Exception:
            pass

    # ── Stage 4: public article probe (top fresh items with real URLs) ──
    probed = 0
    if probe_articles > 0:
        candidates = []
        for f in found:
            fr = argus_news_freshness.classify(f.get("publishedAt"), now_iso)
            if fr["freshness"] in ("fresh", "recent") and f.get("url", "").startswith("http"):
                candidates.append(f)
        for f in candidates[:probe_articles]:
            if over_budget():
                status = "partial"
                break
            searched.append(f"article_probe:{f.get('source') or 'web'}")
            verdict, meta, final_url = _probe_article(f["url"])
            probed += 1
            if verdict == "ok" and meta.get("title"):
                f["snippet"] = meta.get("snippet") or ""
                f["publishedAt"] = f.get("publishedAt") or meta.get("publishedAt")
                # store metadata (never the body) so C.A.O.S./cause engines see it
                _INTEL_STORE.insert(0, {
                    "intelligenceId": hashlib.md5(
                        f"public_article|{final_url}|{meta['title']}".encode()).hexdigest()[:16],
                    "sourceId": "public_article", "title": meta["title"],
                    "canonicalUrl": meta.get("canonicalUrl") or final_url,
                    "publishedAt": meta.get("publishedAt") or f.get("publishedAt"),
                    "firstDetectedAt": now_iso, "fetchedAt": now_iso,
                    "author": meta.get("publisher"), "symbolHint": symu, "lang":
                        ("ja" if mkt == "JP" else "en"), "corroboration": "single"})
            elif verdict in ("subscription_required", "login_required", "forbidden",
                             "not_found", "unreachable"):
                pub = argus_caos_source_universe.resolve_publisher(
                    f.get("title") or "", f.get("source") or "", f.get("url") or "")
                blocked.append({"source": pub["sourceFamily"], "reason": verdict,
                                "title": str(f.get("title") or "")[:120]})

    # ── Stage 5: alternative chasing for blocked stories ──
    for b in blocked[:2]:
        if over_budget():
            status = "partial"
            break
        kws = argus_caos_source_sweep.headline_keywords(b.get("title") or "")
        if not kws:
            continue
        q = " ".join(kws)
        alternatives.append(f"google_news_{'jp' if mkt == 'JP' else 'us'}:『{q[:40]}』で代替検索")
        try:
            rows = (_google_news_jp_rss(q) if mkt == "JP" else _google_news_us_rss(q))[:4]
            for r in rows:
                found.append({"title": r.get("title") or "",
                              "publishedAt": r.get("publishedAt"),
                              "url": str(r.get("canonicalUrl") or "")[:300],
                              "source": "google_news_jp" if mkt == "JP" else "google_news_us"})
        except Exception:
            pass
        alternatives.append("tdnet/公式開示を再確認" if mkt == "JP" else "SEC EDGARを再確認")

    if len(_INTEL_STORE) > _INTEL_STORE_MAX:
        del _INTEL_STORE[:len(_INTEL_STORE) - _INTEL_STORE_MAX]

    result = argus_caos_source_sweep.build_sweep_result(
        symbol=symu, market=mkt, asset_class=ac, now_iso=now_iso,
        searched_sources=searched, found_items=found, blocked_sources=blocked,
        alternative_sources_checked=alternatives,
        status=status, elapsed_ms=int((time.time() - t0) * 1000))
    # v11.7.0 owner rule: sweep items shown in the UI must be Japanese-first —
    # attach displayTitleJa (cached JA or JP fallback) and queue originals.
    try:
        _news_ja_restore_once()
        for lst in ("foundItems", "freshItems", "officialItems",
                    "professionalItems", "publicTextItems"):
            for it in result.get(lst) or []:
                d = _news_decorate(it.get("title") or "", it.get("truePublisher") or "")
                it["displayTitleJa"] = d["displayTitleJa"]
                it["translationStatus"] = d["translationStatus"]
    except Exception:
        pass

    # queue English titles for the translation cron (headlines only)
    try:
        _news_ja_restore_once()
        eng = [{"titleOriginal": i["title"], "source": i.get("truePublisher") or ""}
               for i in result["freshItems"]
               if argus_news_i18n.looks_translatable(i["title"])]
        if eng:
            argus_news_i18n.visible_queue_add(_NEWS_JA_VQUEUE, eng, _NEWS_JA_CACHE,
                                              context="investigate-now", symbol=symu,
                                              market=mkt, now_iso=now_iso)
            _news_ja_persist()
    except Exception:
        pass

    # rebuild the mover cause from the (now richer) cached evidence — no LLM
    try:
        _mover_causes_restore_once()
        q = _quote_cached_only(symu, mkt) or {}
        rec = _mover_cause_for(symu, mkt, q.get("changePct"),
                               name=q.get("nameJa") or q.get("name") or nm,
                               cached_only=True)
        mid = rec.get("moverCauseId")
        if mid:
            _MOVER_CAUSES[mid] = argus_mover_cause_store.merge_record(
                _MOVER_CAUSES.get(mid), rec, now_iso=now_iso)
            _mover_causes_persist()
            _MOVER_REFRESH_QUEUE["data"] = None
        result["moverCauseUpdated"] = True
        served = _mover_cause_serve(_MOVER_CAUSES.get(mid) or rec, now_iso)
        # ladder lead first; when the ladder can't score (e.g. cold price cache →
        # not_scoreable) the sweep's own fresh lead still answers "what's new NOW"
        result["bestCurrentLeadJa"] = (served.get("bestLeadJa")
                                       or result.get("latestFreshLeadJa")
                                       or "最新材料は未確認")[:200]
    except Exception:
        result["moverCauseUpdated"] = False
        result["bestCurrentLeadJa"] = result.get("latestFreshLeadJa") or "最新材料は未確認"

    key = f"{mkt}:{symu}"
    _SWEEP_STATE.setdefault("bySymbol", {})[key] = {
        "lastSweepAt": now_iso, "status": result["status"],
        "freshCount": len(result["freshItems"]),
        "blockedCount": len(result["blockedSources"]),
        "latestFreshLeadJa": result["latestFreshLeadJa"]}
    # bound the per-symbol map
    bysym = _SWEEP_STATE["bySymbol"]
    if len(bysym) > 120:
        for k in sorted(bysym, key=lambda k: str(bysym[k].get("lastSweepAt")))[:len(bysym) - 120]:
            bysym.pop(k, None)
    return result


@app.route("/api/argus/caos/patrol-plan")
def api_argus_caos_patrol_plan():
    """Public cache-only: the always-on patrol schedule (what C.A.O.S. sweeps
    without any click, at what cadence, and when each target is next due)."""
    _sweep_state_restore_once()
    now_iso = _ai_now_iso()
    plan = _watchtower_plan_build(now_iso)
    return jsonify(argus_caos_patrol.build_patrol_plan(
        plan["targets"], _SWEEP_STATE.get("bySymbol") or {}, now_iso))


@app.route("/api/argus/caos/investigate-now", methods=["POST"])
def api_argus_caos_investigate_now():
    """PUBLIC 念押しボタン: an immediate, strictly bounded source sweep for one
    symbol — official disclosures, professional metadata, fresh discovery, public
    article probe, alternative chasing. NO LLM on this path; no login/paywall
    bypass; per-IP+symbol and per-symbol rate limits; 12s budget → partial."""
    _sweep_state_restore_once()
    body = request.get_json(silent=True) or {}
    sym = (str(body.get("symbol") or "").strip().upper())[:16]
    mkt = (str(body.get("market") or "JP").strip().upper())[:4]
    now_iso = _ai_now_iso()
    base = {"schemaVersion": "caos-investigate-now-v2", "symbol": sym, "market": mkt}
    if not sym or mkt not in ("JP", "US") or not re.match(r"^[A-Z0-9._-]{1,10}$", sym):
        return jsonify({**base, "ok": False, "status": "error",
                        "messageJa": "銘柄コードまたは市場が不正です。"}), 200
    key = f"{mkt}:{sym}"
    nowt = time.time()
    ip = _client_meta().get("ip") or ""
    if nowt - float(_INVESTIGATE_RL.get(f"{ip}|{key}", 0.0)) < _INVESTIGATE_RL_SEC:
        return jsonify({**base, "ok": True, "status": "rate_limited",
                        "messageJa": "直前に確認済みです。少し待って再度お試しください。"}), 200
    last = ((_SWEEP_STATE.get("bySymbol") or {}).get(key) or {}).get("lastSweepAt")
    last_ep = argus_news_freshness._epoch(last) if last else None
    if last_ep and (nowt - last_ep) < _INVESTIGATE_COOLDOWN_SEC and not body.get("force"):
        nxt = datetime.fromtimestamp(last_ep + _INVESTIGATE_COOLDOWN_SEC, pytz.utc)
        return jsonify({**base, "ok": True, "status": "rate_limited",
                        "nextCheckAt": nxt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "messageJa": f"直前に確認済みです。次回確認: {nxt.strftime('%H:%M')}UTC",
                        "lastSweep": (_SWEEP_STATE.get('bySymbol') or {}).get(key)}), 200
    if not _SWEEP_LOCK.acquire(blocking=False):
        return jsonify({**base, "ok": True, "status": "rate_limited",
                        "messageJa": "調査が混み合っています。数秒後に再度お試しください。"}), 200
    try:
        _INVESTIGATE_RL[f"{ip}|{key}"] = nowt
        if len(_INVESTIGATE_RL) > 2000:
            _INVESTIGATE_RL.clear()
        result = _caos_run_sweep(sym, mkt, budget_sec=12, probe_articles=3)
    finally:
        _SWEEP_LOCK.release()
    # AI explanation stays a SEPARATE queued path (no LLM on public POST)
    _mc_explain_req_restore_once()
    today = now_iso[:10].replace("-", "")
    mc = _MOVER_CAUSES.get(f"mc-{mkt}-{sym}-{today}")
    if mc and mc.get("explanationJa"):
        ai = {"status": "cached", "messageJa": "AI解説を開けます。"}
    else:
        _mc_explain_req_add(sym, mkt, str(body.get("context") or "investigate-now"), now_iso)
        _mc_explain_req_persist()
        ai = {"status": "queued", "messageJa": "AI解説は別途生成待ちです(補足)。"}
    fresh_n = len(result["freshItems"])
    msg = (f"最新材料を確認しました。新規{fresh_n}件を反映しました。" if fresh_n
           else "最新材料を確認しました。新しい材料は見つかりませんでした。")
    if result["status"] == "partial":
        msg = "一部ソースのみ確認できました。" + msg
    _SWEEP_STATE["lastInvestigateNow"] = {
        "asOf": now_iso, "symbol": sym, "market": mkt, "status": result["status"],
        "searchedSources": result["searchedSources"],
        "freshCount": fresh_n, "blockedCount": len(result["blockedSources"])}
    _sweep_state_persist()
    try:                                          # v11.5.5: soak-proof ledger entry
        _patrol_ledger_restore_once()
        argus_caos_patrol_store.record_sweep(
            _PATROL_LEDGER["doc"], now_iso=now_iso, symbol=sym, market=mkt,
            kind="investigate", status=result["status"], fresh=fresh_n)
        _patrol_ledger_persist()
    except Exception:
        pass
    return jsonify({**base, "ok": True, "status": result["status"],
                    "elapsedMs": result["elapsedMs"],
                    "sweep": {k: result[k] for k in (
                        "searchedSources", "freshItems", "officialItems",
                        "professionalItems", "publicTextItems", "blockedSources",
                        "alternativeSourcesChecked", "notFoundJa")},
                    "moverCauseUpdated": result.get("moverCauseUpdated", False),
                    "bestCurrentLeadJa": result.get("bestCurrentLeadJa", ""),
                    "messageJa": msg, "aiExplanation": ai}), 200


def _old_primary_violations(now_iso):
    """(violations, symbols_with_only_old_news) over today's mover records —
    the hard invariant: old/stale news must never be the current lead."""
    violations, only_old = [], []
    for r in _mover_causes_today():
        served = _mover_cause_serve(r, now_iso)
        best = str(served.get("bestLeadJa") or "")
        cands = served.get("causeCandidates") or []
        news_cands = [c for c in cands if c.get("category") in ("direct_news", "analyst_action")]
        if best and best != "最新材料は未確認":
            # the winner is candidates[0] (resolve() moves it there) — matching ANY
            # candidate whose titleJa appears in best mis-fires when untranslated
            # headlines share a generic fallback title (IONQ false-triple, v11.5.5).
            top = cands[0] if cands else None
            nf = (top or {}).get("newsFreshness") or {}
            if (top and top.get("titleJa") and top["titleJa"] in best
                    and nf.get("freshness") in ("old", "stale")):
                violations.append({"symbol": served.get("symbol"),
                                   "type": "old_news_as_primary",
                                   "detailJa": f"{nf.get('freshness')}のニュースがbestLeadに使われている"})
        if news_cands and all((c.get("newsFreshness") or {}).get("freshness")
                              in ("old", "stale") for c in news_cands):
            only_old.append(str(served.get("symbol") or ""))
    return violations, only_old


@app.route("/api/argus/caos/deep-research/status")
def api_argus_caos_deep_research_status():
    """Public cache-only audit: what the last investigate-now / patrol sweep did,
    which symbols have only old news, and any old-news-as-primary VIOLATIONS
    (must stay empty — smoke fails otherwise)."""
    _sweep_state_restore_once()
    _mover_causes_restore_once()
    _patrol_ledger_restore_once()
    now_iso = _ai_now_iso()
    violations, only_old = _old_primary_violations(now_iso)
    summary = argus_caos_patrol_store.summarize(_PATROL_LEDGER["doc"], now_iso,
                                                old_primary_violations=len(violations))
    return jsonify({
        "schemaVersion": "caos-deep-research-status-v1", "asOf": now_iso,
        "lastInvestigateNow": _SWEEP_STATE.get("lastInvestigateNow"),
        "lastPatrolSweep": _SWEEP_STATE.get("lastPatrolSweep"),
        "sweepsBySymbol": {k: v for k, v in
                           list((_SWEEP_STATE.get("bySymbol") or {}).items())[:40]},
        "coverageByAssetClass": {},   # full coverage lives in /caos-watchtower/status
        "sourcesStale": [s["sourceId"] for s in
                         argus_caos_patrol_store.source_health(_PATROL_LEDGER["doc"], now_iso)
                         if s["status"] == "stale"][:20],
        "symbolsWithOnlyOldNews": only_old[:20],
        "violations": violations[:20],
        # v11.5.5 patrol references (full detail: /api/argus/caos/patrol-health)
        "patrolHealth": {"lastPatrolAt": _PATROL_LEDGER["doc"].get("asOf"),
                         "baselineSweeps24h": summary["baselineSweeps24h"],
                         "deepSweeps24h": summary["deepSweeps24h"],
                         "emptyDeepSweepRuns24h": summary["emptyDeepSweepRuns24h"],
                         "oldPrimaryViolations": summary["oldPrimaryViolations"]},
        "noteJa": "violationsが空=古いニュースがcurrent leadに出ていない。"
                  "公開GETは取得を起動しない。"})


# ── V11.5.5 patrol ledger: durable 24h soak proof ────────────────────────────
_PATROL_LEDGER = {"restored": False, "doc": argus_caos_patrol_store.new_ledger("")}
_PATROL_LEDGER_FILE = "/tmp/argus_caos_patrol_ledger.json"


def _patrol_ledger_persist():
    try:
        with open(_PATROL_LEDGER_FILE, "w") as f:
            json.dump(_PATROL_LEDGER["doc"], f, ensure_ascii=False, default=str)
    except Exception:
        pass


def _patrol_ledger_restore_once():
    """tmp → ledger-branch latest patrol snapshot (MERGE — never wipe) → empty.
    A dyno restart must not erase the day's patrol history."""
    if _PATROL_LEDGER["restored"]:
        return
    _PATROL_LEDGER["restored"] = True
    now_iso = _ai_now_iso()
    try:
        with open(_PATROL_LEDGER_FILE) as f:
            blob = json.load(f)
        if isinstance(blob, dict) and blob.get("schemaVersion") == argus_caos_patrol_store.SCHEMA_VERSION:
            _PATROL_LEDGER["doc"] = argus_caos_patrol_store.merge(
                _PATROL_LEDGER["doc"], blob, now_iso)
    except Exception:
        pass
    if _PATROL_LEDGER["doc"].get("runs"):
        return                                     # tmp had history — good enough
    try:
        r = requests.get(f"{_LEDGER_RAW_BASE}/caos-patrol/latest.json?cb={int(time.time())}",
                         timeout=6)
        if r.status_code == 200 and r.text.strip().startswith("{"):
            snap = json.loads(r.text)
            inner = snap.get("ledger") if isinstance(snap.get("ledger"), dict) else snap
            if isinstance(inner, dict):
                _PATROL_LEDGER["doc"] = argus_caos_patrol_store.merge(
                    _PATROL_LEDGER["doc"], inner, now_iso)
    except Exception:
        pass


@app.route("/api/argus/caos/patrol-health")
def api_argus_caos_patrol_health():
    """Public cache-only: PROOF that the patrol keeps running — 24h run/sweep
    counts, per-source success/failure, per-target due state, honest alerts.
    Never fetches, never calls an LLM."""
    _sweep_state_restore_once()
    _patrol_ledger_restore_once()
    _mover_causes_restore_once()
    now_iso = _ai_now_iso()
    doc = _PATROL_LEDGER["doc"]
    violations, _only_old = _old_primary_violations(now_iso)
    summary = argus_caos_patrol_store.summarize(doc, now_iso,
                                                old_primary_violations=len(violations))
    runs = doc.get("runs", [])
    last_patrol = runs[-1]["at"] if runs else None
    deep_sweeps = [s for s in doc.get("sweeps", []) if s.get("kind") in ("deep", "investigate")]
    base_runs = [r for r in runs if r.get("baselineChecked")]
    is_weekday = datetime.now(pytz.utc).weekday() < 5
    status, alerts = argus_caos_patrol_store.derive_status(
        now_iso=now_iso, last_patrol_at=last_patrol, summary=summary,
        is_weekday=is_weekday, has_runs=bool(runs))
    # baseline-only honesty: latest run had no deep sweeps and no active movers
    if runs and not runs[-1].get("deepSweeps") and not int(runs[-1].get("activeMovers") or 0):
        alerts.append({"level": "info",
                       "messageJa": "active mover sweepなし。Core Portfolio baselineのみ確認。"})
    next_at = None
    if last_patrol:
        ep = argus_news_freshness._epoch(last_patrol)
        if ep:
            next_at = datetime.fromtimestamp(
                ep + (15 * 60 if is_weekday else 60 * 60), pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # target health from the live plan (cache-only)
    try:
        plan = argus_caos_patrol.build_patrol_plan(
            _watchtower_plan_build(now_iso)["targets"],
            _SWEEP_STATE.get("bySymbol") or {}, now_iso)
        targets = [{k: t[k] for k in ("targetId", "assetClass", "symbol", "priority",
                                      "lastSweepAt", "nextSweepAt", "stale", "limitationsJa")}
                   for t in plan["targets"][:30]]
    except Exception:
        targets = []
    summary["targetsPlanned"] = len(targets)
    return jsonify({
        "schemaVersion": "caos-patrol-health-v1", "asOf": now_iso,
        "status": status, "window": "24h",
        "lastPatrolAt": last_patrol,
        "lastDeepSweepAt": deep_sweeps[-1]["at"] if deep_sweeps else None,
        "lastBaselineSweepAt": base_runs[-1]["at"] if base_runs else None,
        "nextScheduledPatrolAt": next_at,
        "summary": summary,
        "sourceHealth": argus_caos_patrol_store.source_health(doc, now_iso)[:40],
        "targetHealth": targets,
        "alerts": alerts,
        # the raw 24h ledger rides along so the workflow snapshot IS the restore source
        "ledger": {"runs": doc.get("runs", [])[-100:],
                   "sweeps": doc.get("sweeps", [])[-150:],
                   "sources": doc.get("sources", {}),
                   "schemaVersion": doc.get("schemaVersion")},
        "noteJa": "near-real-time巡回の稼働証明(24時間窓)。true realtime端末ではない。"
                  "公開GETは取得を起動しない。"})


@app.route("/api/argus/admin/caos/patrol-self-check", methods=["POST"])
def api_argus_admin_caos_patrol_self_check():
    """Admin: cheap is-the-patrol-dead diagnostic — runtime state + baseline plan +
    source freshness. No LLM, no heavy provider fetch (plan build is cache-only)."""
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    _sweep_state_restore_once()
    _patrol_ledger_restore_once()
    now_iso = _ai_now_iso()
    checks, repairs = [], []

    def add(name, ok_, msg=""):
        checks.append({"name": name, "ok": bool(ok_), "messageJa": msg})
        return ok_

    doc = _PATROL_LEDGER["doc"]
    runs = doc.get("runs", [])
    try:
        plan = _watchtower_plan_build(now_iso)
        baseline = [t for t in plan["targets"] if t.get("reason") == "core_portfolio"]
        if not add("baseline_targets_exist", len(baseline) >= 5,
                   f"Core Portfolio基線ターゲット{len(baseline)}件"):
            repairs.append("watchtower planの生成を確認(investment universe読込)")
    except Exception as e:
        add("baseline_targets_exist", False, f"plan生成失敗: {type(e).__name__}")
        repairs.append("watchtower plan生成の例外をログで確認")
    add("patrol_ledger_present", bool(runs),
        f"24時間窓のrun記録{len(runs)}件" if runs else "run記録なし(再起動直後/初回)")
    last = runs[-1]["at"] if runs else None
    last_ep = argus_news_freshness._epoch(last) if last else None
    fresh_run = bool(last_ep and (time.time() - last_ep) < 45 * 60)
    if not add("last_run_recent", fresh_run,
               f"最終巡回 {last or 'なし'}"):
        repairs.append("caos-watchtower workflowの稼働(cron/dispatch)を確認")
    src_ok_today = sum(1 for s in argus_caos_patrol_store.source_health(doc, now_iso)
                       if s["status"] in ("live", "partial"))
    if not add("sources_alive", src_ok_today > 0, f"本日成功ソース{src_ok_today}件"):
        repairs.append("admin/caos-watchtower/refreshを手動実行してソース状態を再収集")
    violations, _ = _old_primary_violations(now_iso)
    if not add("no_old_primary_violation", not violations,
               "違反なし" if not violations else f"違反{len(violations)}件"):
        repairs.append("mover causeの鮮度ゲート回帰を確認(直ちに修正対象)")
    all_ok = all(c["ok"] for c in checks)
    status = ("healthy" if all_ok else
              "error" if violations else
              "stale" if not fresh_run else "degraded")
    return jsonify({"schemaVersion": "caos-patrol-self-check-v1", "ok": all_ok,
                    "status": status, "asOf": now_iso,
                    "checks": checks, "repairActionsJa": repairs})


def _intel_watchlist_symbols():
    return sorted({x["symbol"].upper() for x in _JP_WATCHLIST} | {x["symbol"].upper() for x in _US_WATCHLIST})


@app.route("/api/argus/institutional-intelligence/brief")
def api_argus_intel_brief():
    """§21 daily institutional brief — compact, relevance-first, from the cache.
    Public GET: folds already-collected metadata, no fetch / no model call."""
    brief = argus_daily_brief.build_daily_brief(
        list(_INTEL_STORE), _intel_watchlist_symbols(),
        active_events=None, now_iso=_ai_now_iso(),
        rss_item_counts=_INTEL_LAST.get("perSource") or {})
    return jsonify(brief)


@app.route("/api/argus/institutional-intelligence/relationship-graph")
def api_argus_relationship_graph():
    """§15 cross-market relationship graph. ?symbol= returns that node's themes /
    related assets / propagation candidates (each carries the non-causality caveat)."""
    out = {"meta": argus_relationship_graph.graph_meta()}
    sym = request.args.get("symbol")
    if sym:
        out.update({
            "symbol": sym.upper(),
            "themes": argus_relationship_graph.themes_of(sym),
            "relatedAssets": argus_relationship_graph.related_assets(sym),
            "propagationCandidates": argus_relationship_graph.propagation_candidates(sym),
        })
    return jsonify(out)


@app.route("/api/argus/events/<symbol>/research-mission")
def api_argus_research_mission(symbol):
    """§12 deterministic research mission for an asset — runs the analyst-role swarm
    over the collected evidence. NO LLM (cost.llmCalls=0), so it is safe as a public
    GET. Returns rolesRun + evidence + adversarialFlags + the gated ARGUS view."""
    symu = str(symbol).strip().upper()
    if not symu:
        return jsonify({"error": "symbol_required",
                        "messageJa": "銘柄コードを指定してください。"}), 400
    held = symu in _intel_watchlist_symbols()
    event = _real_event_for(symu, held)
    mission = argus_research_swarm.run_mission(
        event, list(_INTEL_STORE), context={"ownerRelevant": held})
    return jsonify({"symbol": symu, **mission})


def _real_event_for(symu, held):
    """Build a REAL event dict for a mission (v10.198 — fixes the latent bug where
    every held symbol got moveStartedAt=now + severity=high, which made link_to_event
    meaningless). Uses the actual downside incident when present; else moveStartedAt is
    None (unknown timing → no fabricated trigger)."""
    move_ts, severity = None, ("high" if held else "normal")
    try:
        for inc in (get_downside_incidents().get("incidents") or []):
            if str(inc.get("symbol")).upper() == symu:
                move_ts = inc.get("detectedAt") or inc.get("firstDetectedAt") or inc.get("asOf")
                severity = str(inc.get("severity") or severity)
                break
    except Exception:
        pass
    return {"eventId": symu, "linkedAssets": [symu], "moveStartedAt": move_ts, "severity": severity}


@app.route("/api/argus/institutional-intelligence/positioning/<symbol>")
def api_argus_positioning(symbol):
    """§14 institutional positioning read for an asset (uncalibrated). Uses the
    best-available FAST signal (realtime pushed quote); slow-positioning feeds
    (13F/FINRA/EDINET) are honestly absent until wired. Never names a trader."""
    symu = str(symbol).strip().upper()
    if not symu:
        return jsonify({"error": "symbol_required",
                        "messageJa": "銘柄コードを指定してください。"}), 400
    sig = None
    for mkt in ("US", "JP"):
        q = (_PUSHED_QUOTES.get(mkt) or {}).get(symu)
        if q and time.time() - q.get("ts", 0) <= _PUSH_TTL:
            row = q.get("row") or {}
            sig = {"changePct": row.get("changePct"), "volRatio": row.get("volRatio")}
            break
    return jsonify({"symbol": symu, "fastSignalAvailable": sig is not None,
                    **argus_positioning.aggregate_positioning(sig)})


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

def _etf_series_with_moomoo(symbols):
    """Daily ETF closes (Twelve Data, cached) with the CURRENT point overlaid from
    the realtime moomoo bridge when fresh (v10.146). Twelve Data still supplies the
    daily HISTORY for momentum (moomoo gives one realtime point, not 20 days), but
    the latest value — what the regime reads as 'now' — is realtime, and the bridge
    being live means less Twelve-Data refetch pressure (the cause of PARTIAL)."""
    series = _td_timeseries(symbols)            # {sym: [latest_close, ...]} cached
    pushed = _PUSHED_QUOTES.get("US") or {}
    now = time.time()
    for sym in symbols:
        p = pushed.get(str(sym).upper())
        if not p or now - p.get("ts", 0) > _PUSH_TTL:
            continue
        row = p.get("row") or {}
        price = row.get("price")
        if not (isinstance(price, (int, float)) and price > 0):
            continue
        if series.get(sym):
            series[sym] = [float(price)] + series[sym][1:]   # realtime current + TD history
        else:
            # Twelve Data is down for this ETF — build a minimal series from moomoo
            # alone (current price + prev close reconstructed from changePct) so the
            # ETF still COUNTS toward etf_full (cures PARTIAL). Real 1d momentum; 5d/
            # 20d stay None (the regime honestly lacks the longer trend until TD
            # returns). This is the cold-start / TD-quota case (v10.146.2).
            chg = row.get("changePct")
            prev = price / (1 + chg / 100.0) if isinstance(chg, (int, float)) and chg > -100 else price
            series[sym] = [float(price), float(prev)]
    return series

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
_REGIME_PARTIAL_TTL = 45 * 60  # partial reading retry — long enough to stay under
                               # Twelve Data's 800/day free credit cap (see below)
# Stability (v10.34): the last FULL+live regime. A PARTIAL ETF load (Twelve Data
# free-tier rate caps) scores from a subset and tilts the axes differently each
# cold computation, so the headline label wobbled across restarts/cache-expiry.
# We hold the last good reading and prefer it over a fresh partial (up to 24h)
# so the call only changes when we actually have full data — not from noise.
_REGIME_LAST_GOOD = {"data": None, "ts": 0.0}
_REGIME_LAST_GOOD_TTL = 24 * 3600

def _clip(v, lo, hi):
    return lo if v < lo else hi if v > hi else v

def _scale_ret(r):
    """Decimal return → [-1, 1] via a ±10% cap (transparent, no z-score)."""
    return _clip(r, -0.10, 0.10) / 0.10

# Latest ETF closes stashed by _td_timeseries — consumed by the prediction
# ledger's class predictions and the /class-quotes scoring endpoint (v10.5).
_ETF_LAST_PRICE = {}   # sym -> {"price": float, "m1d": float, "ts": epoch}

# ETF daily-close cache (v10.134): these are DAILY bars — they don't change
# intraday — but the regime engine used to refetch them on every refresh, so a
# Twelve Data free-tier rate-limit/miss dropped coverage and flipped the whole
# regime to "partial" (capping confidence). Cache for hours, and on a flaky/partial
# fetch MERGE with the last-good values so coverage never silently degrades.
_TD_TS_CACHE = {}   # ",".join(symbols) -> {"data": {sym: closes}, "expires": epoch}
_TD_TS_TTL = float(os.environ.get("TD_TS_TTL", "7200"))   # 2h

def _td_timeseries(symbols):
    """Batched daily closes for the ETF universe.

    Returns {symbol: [latest_close, ..., older]} (newest-first). Cached ~2h and
    merged with the last-good set, so a transient rate-limit/partial fetch keeps
    full coverage instead of downgrading the regime to partial. Never raises.
    ONE request, len(symbols) credits — keep len(symbols) <= 8 for the free cap.
    """
    key = ",".join(symbols)
    now = time.time()
    cached = _TD_TS_CACHE.get(key)
    prev = (cached or {}).get("data") or {}
    # Fresh + full cache → reuse without spending quota (daily data is stable).
    if cached and now < cached["expires"] and len(prev) == len(symbols):
        return dict(prev)
    if not _TWELVEDATA_API_KEY:
        return dict(prev)
    try:
        r = requests.get(_TWELVEDATA_TS, params={
            "symbol": ",".join(symbols), "interval": "1day",
            "outputsize": 22, "apikey": _TWELVEDATA_API_KEY,
        }, timeout=15)
        r.raise_for_status()
        body = r.json()
        # Top-level error (bad key / quota / rate limit) → flat dict status=error.
        if isinstance(body, dict) and str(body.get("status", "")).lower() == "error":
            return dict(prev)   # serve last-good instead of dropping to partial
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
        # Merge: fresh symbols overwrite; any missing this refresh keep last-good,
        # so a partial response doesn't collapse coverage (→ no spurious partial).
        if out:
            merged = {**prev, **out}
            _TD_TS_CACHE[key] = {"data": merged, "expires": now + _TD_TS_TTL}
            return merged
        return dict(prev)   # empty fetch → last-good
    except Exception:
        return dict(prev)   # network error → last-good, never {}

# US entry-scout history (us-scout-v1, v10.27): ~130d daily OHLCV for one US
# symbol from Twelve Data, newest-first. 6h cache; never raises. 1 credit/call.
_TD_HISTORY_CACHE = {}
_TD_HISTORY_TTL = 6 * 3600

def _td_price_history(sym):
    now = time.time()
    c = _TD_HISTORY_CACHE.get(sym)
    if c and now < c["expires"]:
        return c["data"]
    data = None
    if _TWELVEDATA_API_KEY:
        try:
            r = requests.get(_TWELVEDATA_TS, params={
                "symbol": sym, "interval": "1day", "outputsize": 130,
                "apikey": _TWELVEDATA_API_KEY}, timeout=15)
            r.raise_for_status()
            body = r.json()
            vals = body.get("values") if isinstance(body, dict) else None
            if (isinstance(vals, list) and len(vals) >= 20
                    and str(body.get("status", "ok")).lower() != "error"):
                def _f(v, k):
                    x = v.get(k)
                    try:
                        return float(x) if x not in (None, "") else None
                    except Exception:
                        return None
                rows = [v for v in vals if _f(v, "close") is not None]   # newest-first
                data = {"closes": [_f(v, "close") for v in rows],
                        "highs": [_f(v, "high") for v in rows],
                        "lows": [_f(v, "low") for v in rows],
                        "volumes": [int(_f(v, "volume") or 0) for v in rows],
                        "dates": [v.get("datetime") for v in rows]}
        except Exception as e:
            add_log(f"[scout] US history fetch failed {sym}: {type(e).__name__}")
    # Short failure cache (150s) so a transient TD rate-limit (8/min free) on
    # one symbol self-heals fast instead of locking it out for 10 min.
    _TD_HISTORY_CACHE[sym] = {"data": data, "expires": now + (_TD_HISTORY_TTL if data else 150)}
    return data

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

    etf = {sym: _etf_momentum(cl) for sym, cl in _etf_series_with_moomoo(_REGIME_ETFS).items()}
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

    # ── JP intraday overlay (v10.98): never collapse a green global (US-ETF)
    # regime onto a deteriorating Japan tape. Built from JP watchlist breadth as
    # a proxy (same caveat as the breadth evidence above).
    _jp_dec = sum(1 for s in jp_live_stocks if float(s.get("changePct", 0) or 0) < 0)
    _jp_breadth_val = (round(sum(float(s.get("changePct", 0) or 0) for s in jp_live_stocks) / len(jp_live_stocks), 2)
                       if jp_live_stocks else None)
    _hb = {"5803", "285A", "5801", "6920", "6857"}   # high-beta/momentum JP proxy set
    _hb_live = [s for s in jp_live_stocks if str(s.get("symbol")) in _hb]
    _high_beta_down = bool(_hb_live) and all(float(s.get("changePct", 0) or 0) < -1.0 for s in _hb_live)
    jp_overlay = argus_downside.jp_intraday_overlay({
        "globalRegime": label,
        "nikkeiProxyPct": _jp_breadth_val,
        "jpBreadth": _jp_breadth_val,
        "jpDecliners": _jp_dec,
        "jpTotal": len(jp_live_stocks),
        "highBetaDown": _high_beta_down,
        "ownerAffected": False,   # owner-specific overlay is set in the downside endpoint
    }) if jp_live_stocks else None

    _jp_groups = _jp_sector_rotation()   # computed ONCE — feeds both the JP board + JP matrix

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
        "jpRotationGroups": _jp_groups,              # JP sector flow board (v10.189)
        "jpMatrix": _jp_regime_matrix(_jp_groups),   # JP Regime Matrix (v10.192)
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
        "jpIntradayOverlay": jp_overlay,
    }
    # Last-known-good hold by ETF COVERAGE (v10.34): the label only wobbles when
    # a recompute scores from a different ETF subset. So we replace the displayed
    # reading ONLY when the new one is at least as complete (>= ETFs loaded) — or
    # when the held one is stale (>24h). A thinner refresh is held over, marked.
    new_cov = len(etf)
    lg = _REGIME_LAST_GOOD
    held_fresh = lg["data"] is not None and now - lg["ts"] < _REGIME_LAST_GOOD_TTL
    # Adopt the fresh reading when: nothing held yet / it's stale, OR this refresh
    # is FULL (always take fresh full data), OR it strictly improves coverage.
    # An equal-or-thinner partial is held over so the label can't flip on noise.
    if new_cov > 0 and (not held_fresh or etf_full or new_cov > lg.get("cov", 0)):
        lg["data"], lg["ts"], lg["cov"] = payload, now, new_cov
    elif held_fresh:
        held = dict(lg["data"])
        held["heldOverMin"] = int((now - lg["ts"]) / 60)
        held["dataLimitations"] = (lg["data"].get("dataLimitations") or []) + [
            f"ETFデータが一時的に不足したため、直近のより完全な評価({held['heldOverMin']}分前)を保持表示中"
            "（地合い判定がノイズで揺れないための安定化。より完全なデータが揃うと自動更新）。"]
        payload = held
    if payload.get("status") != "mock":
        _REGIME_CACHE["data"]    = payload
        # A full (all-ETF) reading can sit the 6h TTL; a thinner reading retries
        # sooner — but NOT every 5 min: that was 288 retries/day × 8 ETF credits =
        # ~2304/day, blowing Twelve Data's 800/day free limit so the quota burned
        # out and ETF data failed ALL day (empty Capital Rotation Board). 45 min
        # → ~32 retries/day × 8 = ~256 credits, leaving room for the watchlist.
        full = (payload.get("status") == "live") and not payload.get("heldOverMin")
        _REGIME_CACHE["expires"] = now + (_REGIME_CACHE_TTL if full else _REGIME_PARTIAL_TTL)
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

def _apply_visibility_guard(action, conf, reason, nxt, dq, vg_cap, vg_blocked, vg_reason):
    """Apply the Visibility Guard to ONE label (ARGUS Pro v11). Pure given
    argus_signal.resolve_signal — easy to unit-test. It can only make a label MORE
    conservative:
      1. confidenceCap lowers confidence (never raises it).
      2. If ENTER is situationally blocked and the action would permit a new entry
         (signal.permissions.newEntry == 'allowed'), downgrade the action to WAIT and
         record WHY. High-conviction entry is never shown while entry precision is
         untrustworthy.
    Returns (action, conf, reason, nxt, signal, downgraded)."""
    downgraded = False
    if vg_cap is not None and conf > vg_cap:
        conf = round(vg_cap, 2)
    sig = argus_signal.resolve_signal(action, data_quality=dq)
    if "ENTER" in (vg_blocked or set()) and (sig.get("permissions") or {}).get("newEntry") == "allowed":
        action = "WAIT"
        conf = round(min(conf, 0.5), 2)
        reason = (reason + " 可視性ガードが新規エントリーを一時停止しました"
                  + (f"（{vg_reason}）" if vg_reason else "（一時的な可視性の劣化）") + "。")
        nxt = nxt or "リアルタイム配信の復帰・裏取り後に入りを再評価する。"
        sig = argus_signal.resolve_signal(action, data_quality=dq)
        downgraded = True
    return action, conf, reason, nxt, sig, downgraded


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

    # ── Visibility Guard wiring (ARGUS Pro v11) ──────────────────────────────
    # The guard was previously only a warning surface. It now ACTUALLY constrains
    # judgment: (a) confidenceCap lowers every label's confidence (e.g. calibration
    # burn-in caps at 0.60), and (b) a SITUATIONAL blockedActions=["ENTER"] (bridge
    # stale in-session / prices stopped) downgrades any aggressive new-entry label to
    # WAIT. Fail-open: if the guard errors, labels are unchanged. This can only make
    # judgment MORE conservative, never more aggressive. See _apply_visibility_guard.
    # Kill-switch: ARGUS_VISIBILITY_GATE=0 reverts to pre-v11 behaviour (warn-only,
    # no cap/block) with no redeploy — the gate is the only change that alters what
    # the user is told to DO, so it must be instantly reversible.
    try:
        _vg = _visibility_guard() if os.environ.get("ARGUS_VISIBILITY_GATE", "1") != "0" else {}
    except Exception:
        _vg = {}
    _vg_cap = _vg.get("confidenceCap")
    _vg_blocked = set(_vg.get("blockedActions") or [])
    _vg_reason = ""
    for _w in (_vg.get("warnings") or []):
        if _w.get("code") in ("BRIDGE_STALE", "BRIDGE_NEVER", "REALTIME_UNPROVEN", "AI_BUDGET_STOPPED"):
            _vg_reason = _w.get("messageJa") or ""
            break
    # Decision spine (v11.2): per-symbol active-event ids + today's evidence-pack date,
    # so every label can reference its pack deterministically. Cheap in-memory walk.
    _now_utc_date = datetime.now(pytz.utc).strftime("%Y-%m-%d")
    _ev_ids_by_sym = {}
    try:
        for _e in _events_active_list():
            _s = str(_e.get("symbol") or "").upper()
            if _s:
                _ev_ids_by_sym.setdefault(_s, []).append(_e.get("eventId"))
    except Exception:
        pass

    quotes = {}
    for snap in (jp, us):
        for s in (snap.get("stocks", []) if isinstance(snap, dict) else []):
            quotes[s["symbol"]] = s

    labels, changes = [], []
    for meta in _action_metas(jp, us, jp_symbols, us_symbols):
        q   = quotes.get(meta["symbol"])
        esc = esc_by_market[meta["market"]]
        price = (q or {}).get("price")
        qstatus = (q or {}).get("status")
        # Judge on the last KNOWN price (live OR delayed close), not only live — a closed
        # market (JP after 15:30) carries a real close, so it gets a real assessment instead
        # of the "ライブデータ復帰後に…" placeholder. Only a genuinely price-less / mock quote
        # falls through to neutral-hold.
        if not q or qstatus in (None, "", "mock") or not isinstance(price, (int, float)):
            labels.append({
                "symbol": meta["symbol"], "market": meta["market"], "name": meta["name"],
                "action": "HOLD", "confidence": 0.2, "risk": "low",
                "reasonJa": "価格データが未取得のため中立で保留。",
                "supportingData": {"price": price, "changePct": (q or {}).get("changePct", 0), "volume": (q or {}).get("volume", 0),
                                   "eventEscalation": esc or "normal", "ratesPosture": posture},
                "nextConditionJa": "価格データの取得後に再評価する。",
                "status": "mock",
                "signal": argus_signal.resolve_signal("HOLD", data_quality="MOCK"),
                "visibilityDowngraded": False,
            })
            continue
        chg = float(q.get("changePct", 0) or 0)
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
        # ── Learning Memory: caution-only confidence cap (v11.4). A usable/mature
        #    NEGATIVE lesson for this symbol/market/source can only LOWER confidence
        #    — it can never create ADD/BUY DIP or raise confidence. Current official
        #    evidence still governs the ACTION; memory only tempers certainty. ──
        lm_used = False
        try:
            _lm = _learning_memory_compact_for_symbol(meta["symbol"], meta["market"])
            if _lm:
                lm_used = any(L.get("stage") in ("early_signal", "usable", "mature")
                              for L in (_lm.get("lessons") or []))
                _lm_caps = [c.get("cap") for c in (_lm.get("confidenceCaps") or [])
                            if isinstance(c.get("cap"), (int, float))]
                if _lm_caps:
                    conf = round(min(conf, min(_lm_caps)), 2)
        except Exception:
            pass
        # ── Visibility Guard: cap confidence, block aggressive entry (v11) ──
        conf_before = conf                     # decision spine: confidence BEFORE the guard
        dq = ("LIVE" if qstatus == "live" and lag in (0, None) else "DELAYED")
        action, conf, reason, nxt, sig, vg_downgraded = _apply_visibility_guard(
            action, conf, reason, nxt, dq, _vg_cap, _vg_blocked, _vg_reason)
        labels.append({
            "symbol": meta["symbol"], "market": meta["market"], "name": meta["name"],
            "action": action, "confidence": conf, "risk": risk, "reasonJa": reason,
            "supportingData": {"price": q.get("price"), "changePct": chg, "volume": q.get("volume", 0),
                               "eventEscalation": esc or "normal", "ratesPosture": posture,
                               "marketRegime": reg_label or "n/a",
                               "quoteDate": q.get("date"), "quoteLagDays": lag,
                               "bigFlowRatio": flow_ratio},
            "nextConditionJa": nxt, "status": qstatus,
            # Structured Action Level signal per label (v10.136) so API/ledger
            # consumers get {code,level,permissions} without re-deriving from text.
            "signal": sig,
            "visibilityDowngraded": vg_downgraded,
            # Decision spine (v11.2): every label states WHICH evidence pack it belongs
            # to and how the guard/calibration memory shaped it — auditable later.
            "decisionRefs": {
                "evidencePackId": argus_evidence_pack.pack_id(meta["symbol"], _now_utc_date),
                "eventIds": _ev_ids_by_sym.get(str(meta["symbol"]).upper(), []),
                "visibilityDowngraded": vg_downgraded,
                "confidenceBefore": conf_before,
                "confidenceAfter": conf,
                "calibrationMemoryUsed": cal.get("factor", 1.0) != 1.0,
                "decisionValueMemoryUsed": False,   # DV scoring not yet feeding judgment — honest
                "learningMemoryUsed": lm_used,      # v11.4: usable/early lesson included (caution-only)
                "missingData": list(_vg.get("reasonCodes") or []),
            },
        })

    imminent_any = esc_by_market["US"] in ("D", "D-1") or esc_by_market["JP"] in ("D", "D-1")
    avg = sum(changes) / len(changes) if changes else 0.0
    if reg_ready:
        # The Market Regime engine reads the broad cross-asset backdrop (chiefly
        # US ETF momentum), so when it is live/partial it sets the headline
        # posture; the watchlist-average rule below is the fallback.
        mp = reg_label
        mp_ja = reg_block.get("summaryJa", "") + "（地合い判定=米ETF中心のMarket Regimeエンジン）"
        # Honesty (#4): the regime is US-led, so flag when what you actually watch
        # diverges from it — e.g. RISK_ON globally while your watchlist sells off.
        if changes:
            if mp == "RISK_ON" and avg <= -0.5:
                mp_ja += f" ⚠ ただしウォッチリストは本日軟調(平均{avg:+.1f}%)で、米国主導の地合いと乖離。日本株は別の動き。"
            elif mp == "RISK_OFF" and avg >= 0.5:
                mp_ja += f" ⚠ ただしウォッチリストは本日堅調(平均{avg:+.1f}%)で地合いと乖離。"
        mp_ja += " 自己採点はburn-in段階で精度は未証明(分類であって利益保証ではない)。"
    elif imminent_any:
        mp, mp_ja = "EVENT_WAIT", "重要イベントが目前のため、新規ポジションを抑えイベント通過後に判断する。"
    elif avg <= -2.0:
        mp, mp_ja = "RISK_OFF", "ウォッチリスト全体が軟調で、リスク回避寄りの地合い。"
    elif avg >= 1.5:
        mp, mp_ja = "RISK_ON", "ウォッチリスト全体が堅調で、リスク選好寄りの地合い。"
    else:
        mp, mp_ja = "CAUTIOUS", "方向感は限定的で、慎重なスタンスを継続する。"

    # v10.191: "mixed" (mostly live + a few delayed) and "delayed" (all real but
    # off-hours/close) count as live-enough here — a couple of T-1 names no longer
    # force the whole hero into a scary "partial" (which also capped confidence to
    # 60%). "partial"/"mock" is reserved for genuinely incomplete/absent data.
    _LIVE_ENOUGH = ("live", "mixed", "delayed")
    rates_live = isinstance(rates, dict) and rates.get("status") == "live"
    jp_live    = isinstance(jp, dict) and jp.get("status") in _LIVE_ENOUGH
    us_live    = isinstance(us, dict) and us.get("status") in _LIVE_ENOUGH
    ev_ok      = isinstance(ev, dict) and ev.get("status") in ("live", "partial")
    if rates_live and jp_live and us_live and ev_ok:
        status = "live"
    elif jp_live or us_live:
        status = "partial"   # some live prices → conservative labels still produced
    else:
        status = "mock"

    # Visibility summary for the Today hero / TodayCall — so a downgrade is never
    # silent. blockedEntry drives the "high-conviction entry is suspended" line.
    _vg_entry_blocked = "ENTER" in _vg_blocked
    _vg_downgrade_reason = (_vg_reason if (_vg_entry_blocked and _vg_reason) else "") or (
        "自己採点がまだ精度未証明のため信頼度に上限をかけています。" if _vg_cap is not None else "")
    return {
        "status": status,
        "asOf": datetime.now(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "engineVersion": "action-v0",
        "signalSchemaVersion": argus_signal.SIGNAL_SCHEMA_VERSION,
        "marketPosture": {"label": mp, "rationaleJa": mp_ja},
        "visibility": {
            "visibilityLevel": _vg.get("visibilityLevel"),
            "confidenceCap": _vg_cap,
            "blockedActions": sorted(_vg_blocked),
            "entryBlocked": _vg_entry_blocked,
            "downgradeReasonJa": _vg_downgrade_reason,
            "reasonCodes": _vg.get("reasonCodes", []),
            "coverageLineJa": _vg.get("coverageLineJa"),
        },
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


# ━━━ AI Judgment Layer (OpenAI primary + Gemini double-check) — LIVE ━━━
# This path IS live: _execute_ai_judgment runs it, /api/argus/ai-judgment/run triggers it
# (ai-rejudge.yml every 15 min during sessions + prediction-ledger.yml daily scored run),
# gated by the API keys + the AI run gate + the daily/monthly budget hard-stop. The separate
# GPT-5.5 Pro Handoff export further below stays manual (copy-paste, no API call).
_OPENAI_API_KEY        = os.environ.get("OPENAI_API_KEY", "")
_OPENAI_MODEL          = os.environ.get("OPENAI_MODEL", "") or "gpt-5.5"
# Checker tiering: the DAILY SCORED run (checker=pro) uses the Pro model; the frequent 15-min
# re-judges (checker=flash) and the 429-quota fallback use Flash, so the double-check DEGRADES
# instead of disappearing. Both env-overridable.
_GEMINI_JUDGE_MODEL    = os.environ.get("GEMINI_JUDGE_MODEL", "") or "gemini-2.5-pro"
_GEMINI_FALLBACK_MODEL = os.environ.get("GEMINI_FALLBACK_MODEL", "") or "gemini-2.5-flash"
_ARGUS_ADMIN_TOKEN     = os.environ.get("ARGUS_ADMIN_TOKEN", "")

# ── AI safety / Security Gate v1 config ──────────────────────────────
_AI_JUDGE_ENABLED  = os.environ.get("AI_JUDGE_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
def _int_env(name, default):
    try: return int(os.environ.get(name, str(default)) or default)
    except Exception: return default
# Option C (owner, v10.155): 15-min AI re-judgment during market hours. The run-COUNT
# cap was a proxy guard; the real cost protection is the daily/monthly USD budget
# hard-stop below ($5/day, $80/mo) which pauses AI gracefully if spend is exceeded.
# So the count cap is raised to allow the 15-min cadence (~52 runs/day ≈ $2.6/day,
# well under $5). Tune via env if desired.
_AI_JUDGE_MAX_RUNS      = _int_env("AI_JUDGE_MAX_RUNS_PER_DAY", 64)
_AI_JUDGE_MIN_INTERVAL  = _int_env("AI_JUDGE_MIN_INTERVAL_MINUTES", 14)
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
_AI_LATEST_FILE = "/tmp/argus_ai_latest.json"   # persist EVERY successful run (incl. the
# 15-min ai-rejudge) so an in-instance restart restores the LATEST AI view, not just the
# daily ledger one. Deploys (new container) still fall back to the ledger ai/latest.json.

# Last-run per-model diagnostics (admin-only surface). No secrets, no payloads —
# just the status of the most recent admin-triggered run, if any.
_AI_LAST_RUN = {"oai": None, "gem": None, "groundingEnabled": None, "at": None,
                "gemModel": None, "oaiUsage": None, "gemUsage": None, "gemError": None}

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

# ── AI cost ledger + HARD budget stops (v10.50, GPT cost-control patch) ───────
# The OpenAI prepaid balance / provider project budget are NOT our stop — this
# ARGUS-side ceiling is. Token counts come from the providers' usage metadata;
# prices are env-overridable (we never hard-code a list price we can't let the
# owner correct). Cost is always an ESTIMATE. Accumulator is in-memory but the
# month-to-date total is restored from the ledger branch on boot so a dyno
# restart cannot silently reset the monthly hard stop.
def _float_env(name, default):
    try: return float(os.environ.get(name, str(default)) or default)
    except Exception: return default
_AI_DAILY_BUDGET_USD    = _float_env("AI_DAILY_BUDGET_USD", 5.0)
_AI_MONTHLY_BUDGET_USD  = _float_env("AI_MONTHLY_BUDGET_USD", 80.0)
_AI_EMERGENCY_RESERVE_USD = _float_env("AI_EMERGENCY_RESERVE_USD", 2.0)
_AI_PRICING = {
    _OPENAI_MODEL:        {"in": _float_env("OPENAI_PRICE_INPUT_PER_1M", 1.25),
                           "out": _float_env("OPENAI_PRICE_OUTPUT_PER_1M", 10.0)},
    _GEMINI_JUDGE_MODEL:  {"in": _float_env("GEMINI_PRICE_INPUT_PER_1M", 1.25),
                           "out": _float_env("GEMINI_PRICE_OUTPUT_PER_1M", 10.0)},
    _GEMINI_FALLBACK_MODEL: {"in": _float_env("GEMINI_FLASH_PRICE_INPUT_PER_1M", 0.30),
                             "out": _float_env("GEMINI_FLASH_PRICE_OUTPUT_PER_1M", 2.50)},
}
_AI_GROUNDING_USD = _float_env("GEMINI_GROUNDING_USD_PER_CALL", argus_ai_cost.DEFAULT_GROUNDING_USD)
_AI_COST_STATE = {
    "month": None, "monthSpentUsd": 0.0,     # the monthly hard-stop bucket
    "day": None,   "daySpentUsd": 0.0,       # the daily hard-stop bucket
    "lastRun": None,                          # {provider rows, totalUsd, at, eventId, status}
    "runs": deque(maxlen=50),                 # recent run cost records (no prompts/keys)
    "restoredMonth": None,                    # provenance of the restored baseline
}
_AI_COST_RESTORE_STATE = {"lastTry": 0.0}

def _ai_cost_roll(now_jst):
    """Reset the day/month buckets when the calendar advances. Caller holds _AI_LOCK."""
    mk, dk = argus_ai_cost.month_key(now_jst), argus_ai_cost.day_key(now_jst)
    if _AI_COST_STATE["month"] != mk:
        _AI_COST_STATE["month"] = mk
        _AI_COST_STATE["monthSpentUsd"] = 0.0
    if _AI_COST_STATE["day"] != dk:
        _AI_COST_STATE["day"] = dk
        _AI_COST_STATE["daySpentUsd"] = 0.0

def _ai_cost_restore_once():
    """Best-effort: restore THIS month's spent total from the ledger branch so the
    monthly hard stop survives a dyno restart. Never raises; backs off on failure."""
    now = time.time()
    if _AI_COST_STATE["restoredMonth"] == argus_ai_cost.month_key(datetime.now(TZ_JST)):
        return
    if now - _AI_COST_RESTORE_STATE["lastTry"] < _AI_RESTORE_BACKOFF_S:
        return
    _AI_COST_RESTORE_STATE["lastTry"] = now
    mk = argus_ai_cost.month_key(datetime.now(TZ_JST))
    try:
        url = f"{_LEDGER_RAW_BASE}/ai-cost/{mk}.json?cb={int(now)}"
        with urllib.request.urlopen(url, timeout=20) as r:
            d = json.loads(r.read().decode("utf-8"))
        with _AI_LOCK:
            _ai_cost_roll(datetime.now(TZ_JST))
            base = float(d.get("monthSpentUsd") or 0.0)
            # Restore only if the persisted baseline is higher (never lose spend).
            if base > _AI_COST_STATE["monthSpentUsd"]:
                _AI_COST_STATE["monthSpentUsd"] = base
            _AI_COST_STATE["restoredMonth"] = mk
        add_log(f"[AI] cost baseline restored {mk}: ${base:.2f}")
    except Exception:
        pass  # no file yet (first month) or branch unreachable — start from 0

def _ai_record_cost(run_id, oai_status, gem_status, grounding_enabled):
    """Add the just-finished run's ESTIMATED cost to the day/month buckets. Reads
    per-provider token usage captured in _AI_LAST_RUN; uses the ACTUAL Gemini model
    that ran (pro vs flash fallback). Never raises. Returns the run cost record."""
    rows, total = [], 0.0
    oai_u = _AI_LAST_RUN.get("oaiUsage")
    if oai_status == "live" and oai_u:
        c = argus_ai_cost.estimate_cost(_OPENAI_MODEL, oai_u[0], oai_u[1], _AI_PRICING)
        rows.append({"provider": "openai", "model": _OPENAI_MODEL, "fallbackUsed": False,
                     "inputTokens": oai_u[0], "outputTokens": oai_u[1], "grounding": False, "estUsd": c})
        total += c
    gem_u = _AI_LAST_RUN.get("gemUsage")
    gem_model = _AI_LAST_RUN.get("gemModel") or _GEMINI_JUDGE_MODEL
    if gem_status == "live" and gem_u:
        c = argus_ai_cost.estimate_cost(gem_model, gem_u[0], gem_u[1], _AI_PRICING,
                                        grounding=bool(grounding_enabled), grounding_usd=_AI_GROUNDING_USD)
        rows.append({"provider": "gemini", "model": gem_model,
                     "fallbackUsed": (gem_model == _GEMINI_FALLBACK_MODEL and gem_model != _GEMINI_JUDGE_MODEL),
                     "inputTokens": gem_u[0], "outputTokens": gem_u[1],
                     "grounding": bool(grounding_enabled), "estUsd": c})
        total += c
    total = round(total, 6)
    rec = {"at": _ai_now_iso(), "runId": run_id, "rows": rows, "totalUsd": total,
           "oaiStatus": oai_status, "gemStatus": gem_status, "estimated": True}
    with _AI_LOCK:
        _ai_cost_roll(datetime.now(TZ_JST))
        _AI_COST_STATE["daySpentUsd"] = round(_AI_COST_STATE["daySpentUsd"] + total, 6)
        _AI_COST_STATE["monthSpentUsd"] = round(_AI_COST_STATE["monthSpentUsd"] + total, 6)
        _AI_COST_STATE["lastRun"] = rec
        _AI_COST_STATE["runs"].appendleft(rec)
    add_log(f"[AI] cost +${total:.4f} day=${_AI_COST_STATE['daySpentUsd']:.2f} "
            f"month=${_AI_COST_STATE['monthSpentUsd']:.2f}")
    return rec

def _ai_cost_snapshot():
    """Protected Operations view of AI spend (no prompts/keys). Pure read."""
    with _AI_LOCK:
        _ai_cost_roll(datetime.now(TZ_JST))
        day_s, month_s = _AI_COST_STATE["daySpentUsd"], _AI_COST_STATE["monthSpentUsd"]
        last = _AI_COST_STATE["lastRun"]
        runs = list(_AI_COST_STATE["runs"])[:20]
    return {
        "asOf": _ai_now_iso(), "estimated": True,
        "month": _AI_COST_STATE["month"], "day": _AI_COST_STATE["day"],
        "dailyBudgetUsd": _AI_DAILY_BUDGET_USD, "daySpentUsd": round(day_s, 4),
        "dayRemainingUsd": round(max(0.0, _AI_DAILY_BUDGET_USD - day_s), 4),
        "monthlyBudgetUsd": _AI_MONTHLY_BUDGET_USD, "monthSpentUsd": round(month_s, 4),
        "monthRemainingUsd": round(max(0.0, _AI_MONTHLY_BUDGET_USD - month_s), 4),
        "emergencyReserveUsd": _AI_EMERGENCY_RESERVE_USD,
        "lastRunCostUsd": (last or {}).get("totalUsd"),
        "lastRun": last, "recentRuns": runs,
        "pricing": _AI_PRICING, "groundingUsdPerCall": _AI_GROUNDING_USD,
        "noteJa": "コストは推定値(プロバイダのトークン使用量×設定単価)。OpenAIの前払い残高ではなく、このARGUS側上限がハード停止。",
    }

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

def _ai_persist_latest(payload):
    """Persist a successful run to /tmp so an in-instance restart restores the LATEST
    AI view (incl. 15-min ai-rejudge), not just the daily ledger. Best-effort, atomic."""
    try:
        if isinstance(payload, dict) and payload.get("status") in ("live", "partial") and payload.get("labels"):
            tmp = f"{_AI_LATEST_FILE}.{os.getpid()}.tmp"
            with open(tmp, "w") as f:
                json.dump(payload, f, ensure_ascii=False, default=str)
            os.replace(tmp, _AI_LATEST_FILE)
    except Exception:
        pass


def _ai_restore_local():
    """Restore the latest persisted run from /tmp (validated, age-bounded). Fresher
    than the daily ledger; survives in-instance restarts (not deploys). None if absent."""
    try:
        with open(_AI_LATEST_FILE) as f:
            d = _ai_restore_validate(json.load(f))
        if d:
            d.setdefault("runMode", "restored")
            _AI_RESULT_CACHE["data"] = d
            _AI_RESULT_CACHE["expires"] = time.time() + _AI_CACHE_TTL
            return d
    except Exception:
        pass
    return None


def _ai_cached_result():
    """Valid in-memory run → /tmp-restored latest (in-instance restart) → ledger-
    restored daily (deploys) → None."""
    cached = _AI_RESULT_CACHE["data"]
    if cached and time.time() < _AI_RESULT_CACHE["expires"]:
        return cached
    return _ai_restore_local() or _ai_try_restore()

_AI_CONSERVATIVE = {"WAIT", "HOLD", "WAIT FOR PULLBACK"}
_AI_RANK = {"EXIT": 0, "TRIM": 1, "WAIT FOR PULLBACK": 2, "WAIT": 3, "BUY DIP": 4, "ADD": 5, "HOLD": 6}

def _ai_most_conservative(a, b):
    # Smaller rank = more defensive; prefer the more defensive of the two.
    return a if _AI_RANK.get(a, 99) <= _AI_RANK.get(b, 99) else b

_AI_ENRICH_CACHE = {}     # symbol -> {"data": {...}, "expires": epoch}
_AI_ENRICH_TTL = 1800     # 30 min — the 15-min AI runs reuse this, no refetch each time


def _ai_enrich_symbol(sym, market):
    """(b, v10.160) Per-stock CHART (RSI14 + trend from daily candles) + 日証金/信用
    margin signal (JP weekly, J-Quants) for the AI snapshot — so GPT+Gemini judge WITH
    technicals + margin, not just price/%. 30-min cached, best-effort ({} on failure).
    US margin/JSF is unavailable (no J-Quants); JP only."""
    now = time.time()
    c = _AI_ENRICH_CACHE.get(sym)
    if c and now < c["expires"]:
        return c["data"]
    out = {}
    try:
        candles = get_stock_candles(sym, days=30)
        closes = [x["close"] for x in (candles or []) if x.get("close") is not None]
        if len(closes) >= 15:
            m = _entry_metrics(closes)
            if isinstance(m, dict) and m.get("rsi14") is not None:
                out["rsi14"] = round(float(m["rsi14"]), 1)
                sma10 = sum(closes[-10:]) / 10.0
                out["trend"] = "up" if closes[-1] >= sma10 else "down"
    except Exception:
        pass
    if market == "JP":
        try:
            sig = _margin_signal(_jq_weekly_margin(sym))
            lines = _margin_assess_lines(sig) if sig else None
            if lines:
                out["marginJa"] = " / ".join(lines[:2])[:160]
        except Exception:
            pass
    _AI_ENRICH_CACHE[sym] = {"data": out, "expires": now + _AI_ENRICH_TTL}
    return out


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
               "reasonJa": l["reasonJa"], "nextConditionJa": l["nextConditionJa"],
               # decision spine (v11.2): the judges reference the SAME evidence pack
               "evidencePackId": (l.get("decisionRefs") or {}).get("evidencePackId"),
               "visibilityDowngraded": bool(l.get("visibilityDowngraded"))}
              for l in al.get("labels", [])]
    # (b) enrich each stock with CHART (rsi14/trend) + 日証金/信用 margin so the AI
    # judges WITH them. Concurrent + 30-min cached (bounded API load on 15-min runs).
    try:
        pairs = [(x["symbol"], x["market"]) for x in labels]
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(pairs) or 1)) as ex:
            enr = dict(zip([p[0] for p in pairs], ex.map(lambda p: _ai_enrich_symbol(*p), pairs)))
        for x in labels:
            e = enr.get(x["symbol"]) or {}
            for k in ("rsi14", "trend", "marginJa"):
                if e.get(k) is not None:
                    x[k] = e[k]
    except Exception:
        pass
    # (e) ASSOCIATION (v10.173): attach each stock's business profile + any news linked to it
    # via a RELATED entity (not its own name) — candidate associations the AI judges materiality
    # on. This is the "antenna" that lets it reason "OpenAI IPO delay → SoftBank exposure".
    try:
        _mn2 = get_market_news()
        _news2 = _mn2.get("items", []) if isinstance(_mn2, dict) and _mn2.get("status") == "live" else []
        by_sym = {}
        for n in _news2:
            blob = (n.get("headline") or "") + " " + (n.get("headlineJa") or "")
            for m in _entity_link(blob):
                if m["via"] not in ("entity", "theme"):   # non-obvious associations (not own name)
                    continue
                lst = by_sym.setdefault(m["symbol"], [])
                if len(lst) < 3:
                    lst.append({"headlineJa": (n.get("headlineJa") or n.get("headline") or "")[:120],
                                "via": m["term"], "relationJa": m.get("relationJa"),
                                "corroboration": n.get("corroboration") or "single"})
        for x in labels:
            prof = _ENTITY_PROFILES.get(x["symbol"])
            if prof and prof.get("businessJa"):
                x["profileJa"] = prof["businessJa"]
            if by_sym.get(x["symbol"]):
                x["relatedNews"] = by_sym[x["symbol"]]
    except Exception:
        pass
    # CLOSE-THE-LOOP (v10.153): give the AI judges (a) the self-scoring ledger as a
    # "textbook" so they calibrate against ARGUS's own past accuracy, and (b) the
    # C.A.O.S. institutional signals so the decision reflects fresh institutional
    # views — not just the rule labels. Both are compact + secret-free.
    led = _ledger_summary() or {}
    self_scoring = {
        "overall": led.get("overall"),
        "byPosture": {k: {"n": v.get("n"), "hitRate": v.get("hitRate"), "brierMean": v.get("brierMean")}
                      for k, v in (led.get("byPosture") or {}).items()},
        "aiDirectional": led.get("aiDirectional"),
        "noteJa": "これはARGUS自身の過去成績(自己採点)。hitRateが低い局面では確信度を下げ、高い局面のみ強気にする。将来の利益保証ではない。",
    }
    caos = []
    try:
        for it in [x for x in _INTEL_STORE if x.get("institutionId")][:6]:
            caos.append({"institution": it.get("institutionId"), "stance": it.get("stance"),
                         "type": it.get("contentType"), "assets": it.get("linkedAssets") or [],
                         "title": (it.get("titleJa") or it.get("title") or "")[:120]})
    except Exception:
        caos = []
    # (c) general market news — AWARENESS only (uncorroborated). Major-flagged first. The AI
    # must NOT treat a headline as fact/cause or let it drive the call; it cross-checks it
    # against institutionalSignals + price/rates. Folds news into the same C.A.O.S. input.
    news_digest = []
    try:
        mn = get_market_news()
        if isinstance(mn, dict) and mn.get("status") == "live":
            # precision (v10.169 + v10.170): only MARKET-RELEVANT headlines reach the AI,
            # ranked by corroboration (official>corroborated>single) then source tier — so
            # uncorroborated/clickbait headlines sort last and are flagged for near-zero weight.
            _clvl = {"official": 0, "corroborated": 1, "single": 2}
            _tier = {"official": 0, "wire": 1, "aggregator": 2}
            relevant = [n for n in mn.get("items", []) if n.get("relevant")]
            relevant.sort(key=lambda n: (_clvl.get(n.get("corroboration"), 2),
                                         _tier.get(n.get("tier"), 2), 0 if n.get("major") else 1))
            for n in relevant[:6]:
                news_digest.append({"headlineJa": (n.get("headlineJa") or n.get("headline") or "")[:140],
                                    "source": n.get("source"), "tier": n.get("tier"),
                                    "corroboration": n.get("corroboration") or "single",
                                    "major": bool(n.get("major"))})
    except Exception:
        news_digest = []
    # ── DECISION SPINE (v11.2): the judges see the SAME evidence context the rule
    # labels used — visibility guard, market-depth proof, calibration stage, DV phase,
    # missing data + per-symbol official disclosures / CAOS candidates. Compact
    # (token-bounded), never raw article text, never key material.
    try:
        _vg2 = _visibility_guard()
    except Exception:
        _vg2 = {}
    try:
        _dpi2 = _market_depth_proof_items((_market_depth_report() or {}).get("capabilities") or {})
        _depth2 = {"trueDepthLiveCount": sum(1 for i in _dpi2 if i["status"] == "live" and i["isTrueDepth"]),
                   "requiresContractCount": sum(1 for i in _dpi2 if i["status"] == "requires_contract")}
    except Exception:
        _depth2 = {}
    try:
        _cal_stage = argus_calibration.reliability_stage(
            int((((led or {}).get("overall")) or {}).get("days") or 0))
    except Exception:
        _cal_stage = None
    try:
        _dv_phase = _dv_status_public_dict().get("phase")
    except Exception:
        _dv_phase = None
    try:
        _td2 = get_tdnet_recent(150)
        _td_by2 = _td2.get("bySymbol") or {}
        _td_official2 = bool(_td2.get("official"))
    except Exception:
        _td_by2, _td_official2 = {}, False
    for x in labels:
        rows = _td_by2.get(str(x["symbol"])[:4]) or []
        if rows:
            x["officialDisclosures"] = {"count": len(rows),
                                        "material": sum(1 for r in rows if r.get("material")),
                                        "official": _td_official2}
        try:
            _ca2 = argus_caos_audit.snapshot(symbol=x["symbol"], limit=2).get("items") or []
            if _ca2:
                x["caosCandidates"] = [{"linkType": c.get("linkType"),
                                        "triggerRole": c.get("triggerRole"),
                                        "whyJa": (c.get("whyJa") or "")[:60]} for c in _ca2]
        except Exception:
            pass
    # v11.4: Learning Memory as prompt caution/context (NOT a fresh fact). Global
    # top lessons + caps + hints; the AI must treat it as caution, never overriding
    # official disclosure or fresh market confirmation.
    try:
        _lm_doc = _learning_memory_doc()
        _lm_ch = _lm_doc.get("capsAndHints") or {}
        learning_memory_ctx = {
            "sampleStage": _lm_doc.get("sampleStage"),
            "promptHints": list(_lm_ch.get("promptHints") or [])[:6],
            "confidenceCaps": [{"cohortType": c.get("cohortType"), "cohortKey": c.get("cohortKey"),
                                "cap": c.get("cap")} for c in (_lm_ch.get("confidenceCaps") or [])[:8]],
            "limitationsJa": list(_lm_doc.get("limitationsJa") or [])[:4],
            "cautionOnly": True,
        }
    except Exception:
        learning_memory_ctx = {"sampleStage": "none", "cautionOnly": True}
    evidence_context = {
        "visibilityGuard": {"visibilityLevel": _vg2.get("visibilityLevel"),
                            "confidenceCap": _vg2.get("confidenceCap"),
                            "blockedActions": list(_vg2.get("blockedActions") or []),
                            "reasonCodes": list(_vg2.get("reasonCodes") or [])},
        "marketDepthProof": _depth2,
        "calibrationStage": _cal_stage,
        "decisionValuePhase": _dv_phase,
        "learningMemory": learning_memory_ctx,
        "missingData": list(_vg2.get("reasonCodes") or []),
        "disciplineJa": argus_evidence_pack.DISCIPLINE_JA,
    }
    snap = {
        "marketPosture": al.get("marketPosture"),
        "rates": {k: rates.get(k) for k in ("ratesPressure", "riskVolatility", "summary")} if isinstance(rates, dict) else {},
        "urgentEvents": urgent,
        "labels": labels,
        "selfScoring": self_scoring,            # the learning "textbook" (close-the-loop)
        "institutionalSignals": caos,           # C.A.O.S. — reported views, not trades
        "marketNews": news_digest,              # C.A.O.S. — uncorroborated general news (awareness only)
        "evidenceContext": evidence_context,    # decision spine (v11.2) — same evidence as the rules
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
    "limitations honestly. "
    # close-the-loop: the snapshot now carries ARGUS's own learning + institutional intel.
    "You MUST factor `selfScoring` (ARGUS's own past hit-rate/Brier by posture) into your "
    "confidence: where past hitRate is low, LOWER confidence; only raise it where history supports it. "
    "You MAY reference `institutionalSignals` (public, reported institutional VIEWS — a view is NOT a "
    "trade, and published-after-a-move is not the cause); never assert an institution traded. "
    "`marketNews` is a digest of news HEADLINES (NOT article bodies — the headline wording often does "
    "not match the actual content). Treat each as an unconfirmed CLAIM, never an established fact or the "
    "proven cause of a move; do NOT infer specifics beyond the headline text. Each item has "
    "`corroboration`: 'official' (an authoritative source) / 'corroborated' (>=2 independent source "
    "families) / 'single' (one source — UNVERIFIED). A 'single' item is AWARENESS-ONLY with near-zero "
    "weight and MUST NOT move the call. 'corroborated'/'official' items may inform it ONLY if the "
    "price/rates data CONFIRM them; if news and data conflict, trust the data and stay conservative. "
    "News ALONE never triggers ADD/BUY DIP/EXIT/TRIM. "
    "In `summaryJa`, actively READ the day's corroborated `marketNews` + `institutionalSignals` and name the "
    "single most important driver/theme of the session in concrete terms (not a generic platitude); say so "
    "honestly if the read is thin. "
    "Each label may carry `rsi14`/`trend` (chart technicals) and `marginJa` (Japan 信用/JSF margin-balance "
    "signal) — factor them in (e.g. RSI extremes, margin short-cover fuel) but never treat them as certainty. "
    "A label may also carry `profileJa` (what the company does) and `relatedNews` — news linked to it NOT by "
    "its own name but via a known RELATIONSHIP or THEME (`via`=entity|theme, `term`=the related entity/theme, "
    "`relationJa`=why it matters; e.g. an investee/holding/supplier/peer, or a theme like a policy/commodity). "
    "Treat `relatedNews` as CANDIDATE associations: judge whether the "
    "relationship is MATERIAL to this stock today, and if so EXPLAIN it in reasonJa (e.g. 'OpenAIのIPO遅延→保有評価に影響'); "
    "never treat a candidate as confirmed causation, and a relatedNews item alone never fires ADD/BUY DIP/EXIT/TRIM. "
    "`marketPosture` is the rule engine's current regime read — confirm or critique it, don't just echo it. "
    "`urgentEvents` (and each label's `eventEscalation`) are imminent scheduled events at D/D-1/D-3 escalation: "
    "when a material one is imminent, bias `modelPosture` toward EVENT_WAIT and say so in `marketRiskJa` "
    "(avoid new-entry conviction right before the event). "
    # EVIDENCE DISCIPLINE (decision spine, v11.2) — the judges read the same Evidence
    # Pack context as the rule engine, and these gates are NON-NEGOTIABLE.
    "EVIDENCE DISCIPLINE: the snapshot carries `evidenceContext` (visibility guard, market-depth proof, "
    "calibration stage, decision-value phase, missingData, disciplineJa) and per-label `evidencePackId`/"
    "`officialDisclosures`/`caosCandidates`. You MUST obey: "
    "(1) a single-source C.A.O.S. association is a CANDIDATE only — never a confirmed cause; "
    "(2) an official disclosure (TDnet/EDINET) confirms the FACT, not necessarily the PRICE CAUSE — do not "
    "assert causation without market/timing confirmation; "
    "(3) theme-only links can NEVER justify ADD/BUY DIP unless independently corroborated; "
    "(4) if `evidenceContext.visibilityGuard.blockedActions` contains ENTER, do NOT suggest ADD/BUY DIP; "
    "(5) if `evidenceContext.marketDepthProof.trueDepthLiveCount` is 0, LOWER confidence on any intraday/"
    "microstructure claim (no L2/tape proof exists); "
    "(6) while `evidenceContext.calibrationStage` is burn_in, do not overstate confidence. "
    "(7) `evidenceContext.learningMemory` is ARGUS's OWN past-outcome history (cohort lessons + "
    "confidenceCaps + promptHints) — treat it as CAUTION/CONTEXT ONLY, never as a current fact: it can lower "
    "your confidence or flag a repeatedly-wrong pattern, but it must NEVER override a fresh official disclosure "
    "or fresh market confirmation, and it can NEVER by itself create ADD/BUY DIP. If its `sampleStage` is "
    "none/burn_in, do not lean on it (sample too small); if a `confidenceCaps` entry applies to a label, keep "
    "that label's confidence at or below the cap. Model weights are NOT updated — this is aggregated history. "
    "State in dataLimitations which evidence was missing when it constrained you. "
    "All *Ja fields must be concise Japanese. Return STRICT JSON only."
)

def _usage_tokens(resp):
    """Best-effort (input_tokens, output_tokens) from either the OpenAI Responses
    API (input_tokens/output_tokens, reasoning folded into output) or chat
    completions (prompt_tokens/completion_tokens). Returns (0, 0) if absent —
    never raises. output includes reasoning/thinking tokens (they bill as output)."""
    u = getattr(resp, "usage", None)
    if u is None:
        return 0, 0
    def _g(*names):
        for n in names:
            v = getattr(u, n, None)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return int(v)
        return 0
    inp = _g("input_tokens", "prompt_tokens")
    out = _g("output_tokens", "completion_tokens")
    return inp, out

def _openai_judge(snapshot):
    _AI_LAST_RUN["oaiUsage"] = None
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
        _AI_LAST_RUN["oaiUsage"] = _usage_tokens(resp)
        out = safe_json(text or "")
        if not isinstance(out, dict) or not isinstance(out.get("labels"), list):
            return None, "partial"
        return out, "live"
    except Exception as e:
        add_log(f"[AI] openai judge failed: {type(e).__name__}")
        return None, "unavailable"

def _gemini_usage_tokens(resp):
    """Best-effort (input, output) tokens from Gemini's usage_metadata. output
    folds in thoughts/thinking tokens (they bill as output). (0,0) if absent."""
    um = getattr(resp, "usage_metadata", None)
    if um is None:
        return 0, 0
    def _g(*names):
        for n in names:
            v = getattr(um, n, None)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return int(v)
        return 0
    inp = _g("prompt_token_count")
    out = _g("candidates_token_count") + _g("thoughts_token_count")
    return inp, out

def _gemini_prompt(snapshot, openai_out):
    """PURE Gemini challenge prompt (v11.2: evidence-aware). Kept as a separate
    function so tests can assert it carries missingData / visibilityGuard / the
    challenge keys without any API call."""
    return (
        "あなたはARGUSの独立検証役です。以下の市場スナップショット・ルールラベル・GPTの提案を検証し、"
        "(1)裏付けのない主張、(2)直近の重大リスク(web情報があれば反映)、(3)GPT提案が強気/積極的すぎないか、"
        "(4)注意すべき銘柄、(5)最終アクションを引き下げるべきか、を点検してください。捏造は禁止。"
        "SNAPSHOT内の evidenceContext（可視性ガード・市場深さの実証・校正段階・missingData・disciplineJa）を必ず参照: "
        "単一ソース連想は候補止まり・公式開示は事実確認であって価格原因の確定ではない・"
        "可視性がENTERをブロック中の新規提案は不可・欠けている証拠(missingData)は弱点として明示。"
        "STRICT JSONのみを返す。キー: status, model, summaryJa, agreement(confirm|caution|disagree), "
        "mainWeaknessJa, whatWouldChangeJa, unverifiedAssumptions[], disagreements[] "
        "(symbol, issueJa, severity(low|medium|high), recommendedConservativeAction(WAIT|HOLD|WAIT FOR PULLBACK)), "
        "globalRedFlags[], groundingSources[] (title,url)。\n"
        "SNAPSHOT:\n" + json.dumps(snapshot, ensure_ascii=False) +
        "\nGPT:\n" + json.dumps(openai_out or {}, ensure_ascii=False))


def _build_gemini_challenge(openai_out, gemini_out):
    """PURE: fold the GPT view + Gemini checker output into the structured challenge
    record (decision spine v11.2). Defensive: works with partial/missing outputs and
    derives `agreement` from disagreements severity when Gemini didn't state one."""
    o = openai_out if isinstance(openai_out, dict) else {}
    g = gemini_out if isinstance(gemini_out, dict) else {}
    dis = [d for d in (g.get("disagreements") or []) if isinstance(d, dict)]
    agreement = g.get("agreement")
    if agreement not in ("confirm", "caution", "disagree"):
        agreement = ("disagree" if any(d.get("severity") == "high" for d in dis)
                     else "caution" if (dis or g.get("globalRedFlags")) else
                     ("confirm" if g else "unavailable"))
    weakness = (g.get("mainWeaknessJa")
                or (dis[0].get("issueJa") if dis else "")
                or (str((g.get("globalRedFlags") or [""])[0]) if g.get("globalRedFlags") else ""))
    return {
        "gptView": (o.get("summaryJa") or "")[:300],
        "geminiChallenge": (g.get("summaryJa") or "")[:300],
        "agreement": agreement,
        "mainWeaknessJa": (weakness or "")[:200],
        "whatWouldChangeJa": (g.get("whatWouldChangeJa") or "")[:200],
        "unverifiedAssumptions": [str(x)[:120] for x in (g.get("unverifiedAssumptions") or [])][:5],
    }


def _gemini_check(snapshot, openai_out, checker_model=None):
    """Returns (out|None, status, grounding_enabled)."""
    _AI_LAST_RUN["gemUsage"] = None
    if not google_genai or not GEMINI_API_KEY:
        return None, "unavailable", False
    grounding_enabled = False
    try:
        client = google_genai.Client(api_key=GEMINI_API_KEY)
        prompt = _gemini_prompt(snapshot, openai_out)
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

        model_used = checker_model or _GEMINI_JUDGE_MODEL   # per-run tier (flash/pro)
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
        _AI_LAST_RUN["gemUsage"] = _gemini_usage_tokens(resp)
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
            # decision spine (v11.2): the arbitrated view keeps the SAME evidence refs
            # the rule label carried, so ARGUS View is auditable end-to-end.
            "decisionRefs": rl.get("decisionRefs"),
        })
    return labels

def _ai_now_iso():
    return datetime.now(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _age_min_iso(iso):
    """Minutes since an ISO-8601 '…Z' timestamp; None if unparseable."""
    if not iso or not isinstance(iso, str):
        return None
    try:
        t = datetime.strptime(iso.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z")
        return max(0, int((datetime.now(pytz.utc) - t).total_seconds() / 60))
    except Exception:
        return None

def _next_weekday_run_iso(hh_jst, mm_jst):
    """Next weekday occurrence of HH:MM JST as ISO (for ledger-health nextRun)."""
    n = datetime.now(TZ_JST)
    cand = n.replace(hour=hh_jst, minute=mm_jst, second=0, microsecond=0)
    if cand <= n:
        cand += timedelta(days=1)
    while cand.weekday() >= 5:
        cand += timedelta(days=1)
    return cand.astimezone(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _last_weekday_run_dt(hh_jst, mm_jst):
    """Most recent PAST weekday HH:MM JST (the last scheduled run that should
    have fired). Used to tell 'missed a run' (real stale) apart from 'weekend
    gap, up-to-date for the latest session' (fine — not a failure)."""
    n = datetime.now(TZ_JST)
    cand = n.replace(hour=hh_jst, minute=mm_jst, second=0, microsecond=0)
    if cand > n:
        cand -= timedelta(days=1)
    while cand.weekday() >= 5:
        cand -= timedelta(days=1)
    return cand

def _ai_session_freshness(as_of_iso, age_min):
    """fresh / persisted / stale, SESSION-AWARE. A run made at/after the last
    scheduled 16:05 JST slot is 'persisted' (current for the latest session),
    NOT stale — so a Friday run shown on Saturday isn't flagged as a failure.
    'stale' means a scheduled run was actually MISSED."""
    if age_min is None:
        return "persisted"
    if age_min <= _AI_CACHE_TTL / 60 + 5:
        return "fresh"
    try:
        run_dt = datetime.strptime(as_of_iso.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z").astimezone(TZ_JST)
        return "persisted" if run_dt >= _last_weekday_run_dt(16, 5) else "stale"
    except Exception:
        return "persisted" if age_min < 24 * 60 else "stale"

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

def _execute_ai_judgment(run_mode="manual", checker=None):
    """Run a fresh AI judgment (GPT-5.5 primary + Gemini double-check), arbitrate,
    cache, return. Never raises. The security gate / run limits are enforced by
    the caller (POST route) — this function performs the actual model work.

    `checker` picks the Gemini double-check tier per run (cost/quality, v10.159):
      'flash' → cheap fallback model (the frequent 15-min/off-hours refresh)
      'pro' / None → the strong configured model (the daily scored run + on-demand).
    """
    snap, al = _build_ai_snapshot()
    openai_out, oai_status = _openai_judge(snap)
    checker_model = _GEMINI_FALLBACK_MODEL if checker == "flash" else _GEMINI_JUDGE_MODEL
    gemini_out, gem_status, grounding_enabled = _gemini_check(snap, openai_out, checker_model)
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
        # decision spine (v11.2): the structured GPT-vs-Gemini challenge record — what
        # the checker disputed, its main weakness, and unverified assumptions.
        "geminiChallenge": _build_gemini_challenge(openai_out, gemini_out),
    }
    if status != "mock":
        _AI_RESULT_CACHE["data"] = payload
        _AI_RESULT_CACHE["expires"] = time.time() + _AI_CACHE_TTL
        _ai_persist_latest(payload)   # /tmp — survive in-instance restarts (every run)
    _AI_LAST_RUN.update({"oai": oai_status, "gem": gem_status,
                         "groundingEnabled": grounding_enabled, "at": _ai_now_iso()})
    # Cost ledger (v10.50): record this run's estimated spend into the day/month
    # hard-stop buckets, using the ACTUAL Gemini model that ran (pro vs flash).
    try:
        cost = _ai_record_cost(payload.get("asOf"), oai_status, gem_status, grounding_enabled)
        payload["costEstimateUsd"] = cost.get("totalUsd")
        # Surface the real model that ran for calibration (Pro and Flash must not
        # be merged as one model). gemModelActual is null when Gemini didn't run.
        payload["models"]["checkerActual"] = (_AI_LAST_RUN.get("gemModel") if gem_status == "live" else None)
        payload["models"]["groundingUsed"] = bool(grounding_enabled)
    except Exception:
        pass
    add_log(f"[AI] run mode={run_mode} models={_OPENAI_MODEL}/{_AI_LAST_RUN.get('gemModel') or _GEMINI_JUDGE_MODEL} "
            f"symbols={len(labels)} oai={oai_status} gem={gem_status} grounding={grounding_enabled} status={status}")
    return payload

# ━━━ C.A.O.S. event lifecycle — pre-event scenarios + post-event analysis (v10.165) ━━━
# Enriches the C.A.O.S. frame around scheduled macro events. PRE-event: what the market
# has priced in, how big-money is positioned (reported VIEWS, not trades), and staged
# scenarios so ARGUS reacts the instant the number drops. POST-event: the result (only
# if it's in an official C.A.O.S. item — NEVER fabricated), how big-money + the market
# took it (the realized regime/price reaction), and the read-through to the industry.
# AI-generated (cron/admin), cached + /tmp-persisted; the public GET serves the cache.
_EVENT_ANALYSIS = {"items": {}, "asOf": None}     # eventId -> analysis dict
_EVENT_ANALYSIS_FILE = "/tmp/argus_event_analysis.json"
_EVENT_ANALYSIS_TTL = 6 * 3600                    # regenerate at most ~every 6h per event

_CAOS_EVENT_SYSTEM = (
    "You are C.A.O.S. (Corroborated Analyst & Official Signals), ARGUS's research desk. "
    "Give a COMPACT Japanese read of ONE scheduled macro event for an individual investor. "
    "Each field is ONE short sentence (一言), NOT a paragraph. HONESTY IS ABSOLUTE: never "
    "fabricate a result number, a consensus, or that an institution traded — a public VIEW is "
    "not a trade; published-after-a-move is not the cause. If the actual result isn't in the "
    "provided data, say so plainly. No trade instructions (decision-support only). "
    "Return STRICT JSON with exactly these keys: {"
    "\"summaryJa\": str — 概要: what this event is and why it matters to the portfolio (ALWAYS, one sentence); "
    "\"preJa\": str — 事前予想: PRE phase ONLY — what the market has priced in and big-money posture "
    "(a reported view, never a position) plus the asymmetric risk if it surprises; set \"\" when phase is POST; "
    "\"postJa\": str — 事後: POST phase ONLY — the result (state plainly if it is not in the data), how "
    "big-money and the market actually took it (use marketReaction/regime), and the financial-industry "
    "read-through; set \"\" when phase is PRE}."
)


def _openai_prose(user, max_out=600, system=None):
    """Generic GPT STRICT-JSON call. Returns a non-empty dict or None. Used by the C.A.O.S.
    event analyzer (default system) and the entity-profile generator (system= override)."""
    if not _OPENAI_API_KEY:
        return None
    sys_prompt = system or _CAOS_EVENT_SYSTEM
    try:
        import openai
        client = openai.OpenAI(api_key=_OPENAI_API_KEY)
        try:
            resp = client.responses.create(model=_OPENAI_MODEL, instructions=sys_prompt,
                                            input=user, timeout=60)
            text = getattr(resp, "output_text", None)
        except Exception:
            resp = client.chat.completions.create(
                model=_OPENAI_MODEL,
                messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": user}],
                response_format={"type": "json_object"}, timeout=60)
            text = resp.choices[0].message.content
        try:
            _ai_record_cost(_ai_now_iso(), "live", "unavailable", False)  # bill GPT-only usage
        except Exception:
            pass
        out = safe_json(text or "")
        return out if isinstance(out, dict) and out else None
    except Exception as e:
        add_log(f"[caos] event prose failed: {type(e).__name__}")
        return None


def _caos_event_inputs(ev):
    """Assemble the (phase, prompt) for one important-event: linked C.A.O.S. items +
    the current regime/rates reaction + linked-asset moves. phase = pre|post."""
    days = ev.get("daysUntil")
    phase = "post" if (isinstance(days, (int, float)) and days <= 0) else "pre"
    assets = {str(a).upper() for a in (ev.get("linkedAssets") or [])}
    caos = []
    for it in _INTEL_STORE:
        if it.get("institutionId") and (assets & {str(a).upper() for a in (it.get("linkedAssets") or [])}):
            caos.append({"inst": it.get("institutionId"), "stance": it.get("stance"),
                         "title": (it.get("titleJa") or it.get("title") or "")[:120]})
        if len(caos) >= 5:
            break
    rates = get_rates_snapshot()
    reaction = {k: (rates.get(k) or {}).get("latestValue") for k in ("usdJpy", "us10y", "vix")} if isinstance(rates, dict) else {}
    reg = (_REGIME_CACHE.get("data") or {}).get("regime") if isinstance(_REGIME_CACHE.get("data"), dict) else None
    payload = {"event": {k: ev.get(k) for k in ("eventCode", "displayImpact", "daysUntil", "countdown",
                                                 "whyItMattersJa", "linkedAssets")},
               "phase": phase, "institutionalViews": caos,
               "marketReaction": reaction, "regime": (reg or {}).get("label") if isinstance(reg, dict) else reg}
    instr = ("PRE-event: summaryJa=概要(このイベントとポートフォリオへの意味)、preJa=事前予想(市場の織り込み・大口の構え〔見解であり建玉ではない〕・サプライズ時の非対称リスク)。postJaは\"\"。各1文。"
             if phase == "pre" else
             "POST-event: summaryJa=概要、postJa=事後(結果〔公式データに無ければ無いと明記〕・大口/市場の捉え方〔下のmarketReaction/regimeの実反応〕・金融業界への影響)。preJaは\"\"。各1文。")
    return phase, instr + "\nData:\n" + json.dumps(payload, ensure_ascii=False)


def _caos_event_generate(limit=5):
    """Generate pre/post C.A.O.S. analyses for the top material events (admin/cron).
    Cached per eventId for _EVENT_ANALYSIS_TTL; persisted to /tmp. Never raises."""
    out = {}
    try:
        ev_snap = get_events_snapshot()
        items = argus_important_events.build_important_events(
            ev_snap.get("events", []) if isinstance(ev_snap, dict) else [],
            owner_symbols=_owner_symbols_for_events())
    except Exception:
        items = []
    material = [e for e in items if e.get("displayImpact") in ("critical", "high")][:limit]
    now = time.time()
    made = 0
    for ev in material:
        eid = ev.get("eventId") or ev.get("eventCode")
        prev = _EVENT_ANALYSIS["items"].get(eid)
        phase = "post" if (isinstance(ev.get("daysUntil"), (int, float)) and ev["daysUntil"] <= 0) else "pre"
        # reuse cache if same phase + still fresh
        if prev and prev.get("phase") == phase and now - prev.get("ts", 0) < _EVENT_ANALYSIS_TTL:
            out[eid] = prev
            continue
        _, prompt = _caos_event_inputs(ev)
        # v11.2.1 (owner request — 答え合わせ): when the event flips PRE→POST, the
        # pre-event prediction must SURVIVE so the post analysis can be checked
        # against it. Feed the preserved prediction into the post prompt and ask for
        # an explicit 当たり/外れ verdict — a real answer-check, not a fresh take.
        prev_pre = str((prev or {}).get("preJa") or "")[:200]
        if phase == "post" and prev_pre:
            prompt += ("\n発表前のARGUS事前予想: " + prev_pre +
                       "\npostJaでは必ずこの事前予想との答え合わせ（概ね当たり/部分的/外れ＋一言の理由）を含めること。")
        pr = _openai_prose(prompt)
        if not pr:
            if prev:
                out[eid] = prev
            continue
        # Headed one-liners (概要/事前予想/事後). Legacy bodyJa maps to 概要 if a model
        # returns the old shape, so the panel never blanks during a schema transition.
        summary = str(pr.get("summaryJa") or pr.get("headlineJa") or pr.get("bodyJa") or "")[:200]
        # POST phase carries the preserved pre-event prediction (read-only) so the UI
        # can show 事前予想(当時) next to 事後の答え合わせ.
        pre = (str(pr.get("preJa") or "")[:200] if phase == "pre" else prev_pre)
        post = str(pr.get("postJa") or "")[:200] if phase == "post" else ""
        out[eid] = {"eventId": eid, "eventCode": ev.get("eventCode"), "phase": phase,
                    "displayImpact": ev.get("displayImpact"), "daysUntil": ev.get("daysUntil"),
                    "countdown": ev.get("countdown"),
                    "summaryJa": summary, "preJa": pre, "postJa": post,
                    "ts": now, "generatedAt": _ai_now_iso()}
        made += 1
    _EVENT_ANALYSIS["items"] = out
    _EVENT_ANALYSIS["asOf"] = _ai_now_iso()
    _caos_event_persist()
    return {"generated": made, "total": len(out)}


def _caos_event_persist():
    try:
        tmp = f"{_EVENT_ANALYSIS_FILE}.{os.getpid()}.tmp"
        with open(tmp, "w") as f:
            json.dump(_EVENT_ANALYSIS, f, ensure_ascii=False, default=str)
        os.replace(tmp, _EVENT_ANALYSIS_FILE)
    except Exception:
        pass


def _caos_event_restore():
    try:
        with open(_EVENT_ANALYSIS_FILE) as f:
            blob = json.load(f)
        if isinstance(blob, dict) and isinstance(blob.get("items"), dict):
            _EVENT_ANALYSIS["items"] = blob["items"]
            _EVENT_ANALYSIS["asOf"] = blob.get("asOf")
    except Exception:
        pass


def _owner_symbols_for_events():
    try:
        return sorted({x["symbol"].upper() for x in _JP_WATCHLIST} | {x["symbol"].upper() for x in _US_WATCHLIST}
                      | set(_JP_SEEN_SYMBOLS.keys()))
    except Exception:
        return None


# ━━━ C.A.O.S. Macro Event Pre/Post Intelligence (v11.3.2) ━━━━━━━━━━━━━━━━━━━
# Replaces the fragile daysUntil<=0 pre/post split with the canonical eventTimeUtc
# phase resolver (release-day-before-release = still PRE), a DURABLE store (pre views
# survive redeploys so post can answer-check against them), and an official-result
# adapter (BLS NFP first — never fabricated).
_MACRO_ANALYSIS = {}                  # eventId -> analysis record
_MACRO_ANALYSIS_FILE = "/tmp/argus_macro_analysis.json"
_MACRO_ANALYSIS_STATE = {"restored": False, "lastGenerateAt": None, "lastResultsAt": None,
                         "pathType": "ephemeral_tmp"}
# V11.5: per-event-code result adapter state (metricsAvailable filled on success).
_MACRO_RESULT_STATE = {code: {"provider": argus_macro_results.PROVIDER.get(code), "status": "not_run",
                              "lastSuccessAt": None, "sampleEventId": None, "metricsAvailable": []}
                       for code in ("NFP", "CPI", "PPI", "FOMC", "PCE", "GDP", "JOLTS")}
# adapters returning honest partial/not_implemented (no reliable free numeric source)
_MACRO_NOT_IMPLEMENTED = ("BOJ", "TREASURY_AUCTION", "AUCTION")


def _macro_analysis_persist():
    try:
        with open(_MACRO_ANALYSIS_FILE, "w") as f:
            json.dump({"items": _MACRO_ANALYSIS,
                       "state": {k: _MACRO_ANALYSIS_STATE[k]
                                 for k in ("lastGenerateAt", "lastResultsAt")}},
                      f, ensure_ascii=False, default=str)
    except Exception:
        pass


def _macro_analysis_restore_once():
    """tmp → ledger latest (short timeout, merge — an old snapshot can't wipe newer) → empty."""
    if _MACRO_ANALYSIS_STATE["restored"]:
        return
    _MACRO_ANALYSIS_STATE["restored"] = True
    try:
        with open(_MACRO_ANALYSIS_FILE, "r") as f:
            blob = json.load(f)
        if isinstance(blob.get("items"), dict):
            _MACRO_ANALYSIS.update(blob["items"])
            _MACRO_ANALYSIS_STATE["pathType"] = "durable_restored"
        _MACRO_ANALYSIS_STATE.update({k: v for k, v in (blob.get("state") or {}).items()
                                      if k in ("lastGenerateAt", "lastResultsAt")})
    except Exception:
        pass
    try:
        r = requests.get(f"{_LEDGER_RAW_BASE}/macro-events/analysis/latest.json?cb={int(time.time())}",
                         timeout=6)
        if r.status_code == 200 and r.text.strip().startswith("{"):
            merged = argus_macro_event_store.merge_records(
                _MACRO_ANALYSIS,
                list(argus_macro_event_store.restore_from_snapshot(json.loads(r.text)).values()),
                now_iso=_ai_now_iso())
            _MACRO_ANALYSIS.clear()
            _MACRO_ANALYSIS.update(merged)
            _MACRO_ANALYSIS_STATE["pathType"] = "ledger_restored"
    except Exception:
        pass


def _macro_market_context_ja():
    """Short REAL market context for the prompts (measured values only)."""
    bits = []
    try:
        rates = get_rates_snapshot()
        if isinstance(rates, dict):
            for k, lab in (("us10y", "US10Y"), ("usdJpy", "ドル円"), ("vix", "VIX")):
                v = (rates.get(k) or {}).get("latestValue")
                if v is not None:
                    bits.append(f"{lab}={v}")
    except Exception:
        pass
    try:
        reg = (_REGIME_CACHE.get("data") or {}).get("regime") or {}
        if reg.get("label"):
            bits.append(f"regime={reg['label']}")
    except Exception:
        pass
    return " / ".join(bits)


def _bls_nfp_result(event):
    """OFFICIAL NFP result from the BLS public API (no key needed; free). available=True
    ONLY when the latest published month equals the release's reference month — never
    fabricated. Admin/cron path only."""
    now_iso = _ai_now_iso()
    out = {"available": False, "source": "BLS", "releasedAt": None, "headline": None,
           "metrics": {}, "limitationsJa": ["公式結果未取得"]}
    try:
        yr = datetime.now(pytz.utc).year
        r = requests.post("https://api.bls.gov/publicAPI/v2/timeseries/data/",
                          json={"seriesid": ["CES0000000001", "LNS14000000"],
                                "startyear": str(yr - 1), "endyear": str(yr)},
                          headers={"Content-Type": "application/json",
                                   "User-Agent": "argus-research/1.0"}, timeout=15)
        if r.status_code != 200:
            _MACRO_RESULT_STATE["NFP"].update(status=("rate_limited" if r.status_code == 429 else "error"))
            out["limitationsJa"] = [f"BLS HTTP {r.status_code}"]
            return out
        series = {s.get("seriesID"): s.get("data") or []
                  for s in (((r.json() or {}).get("Results") or {}).get("series") or [])}
        ces = sorted(series.get("CES0000000001") or [],
                     key=lambda d: (d.get("year"), d.get("period")), reverse=True)
        lns = sorted(series.get("LNS14000000") or [],
                     key=lambda d: (d.get("year"), d.get("period")), reverse=True)
        if len(ces) < 2:
            out["limitationsJa"] = ["BLS系列が空"]
            _MACRO_RESULT_STATE["NFP"].update(status="partial")
            return out
        latest, prior = ces[0], ces[1]
        latest_month = f"{latest.get('year')}-{str(latest.get('period') or '').replace('M', '')}"
        # reference month of THIS release = the month before the event date
        ev_d = str(event.get("eventDate") or event.get("eventTimeUtc") or "")[:10]
        try:
            evdt = datetime.strptime(ev_d, "%Y-%m-%d")
            ref = (evdt.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        except Exception:
            ref = None
        chg_k = round(float(latest.get("value", 0)) - float(prior.get("value", 0)))
        ur = (lns[0].get("value") if lns else None)
        if ref and latest_month != ref:
            out["limitationsJa"] = [f"公式結果未反映（BLS最新は{latest_month}・今回の対象月は{ref}）"]
            _MACRO_RESULT_STATE["NFP"].update(status="live", lastSuccessAt=now_iso)
            return out
        out.update(available=True, releasedAt=now_iso,
                   headline=f"非農業部門雇用者数 {chg_k:+,}千人 / 失業率 {ur}%",
                   metrics={"nfpChangeK": chg_k, "unemploymentRate": ur,
                            "referenceMonth": latest_month},
                   limitationsJa=[])
        out["sourceUrl"] = "https://www.bls.gov/news.release/empsit.nr0.htm"
        _MACRO_RESULT_STATE["NFP"].update(status="live", lastSuccessAt=now_iso,
                                          sampleEventId=event.get("id") or event.get("eventId"))
    except Exception as e:
        _MACRO_RESULT_STATE["NFP"].update(status="error")
        out["limitationsJa"] = [f"BLS取得エラー({type(e).__name__})"]
    return out


def _bls_fetch(series_ids, years_back=2):
    """POST the BLS public API for the given series (admin/cron path). Returns the
    parsed JSON or None. No key needed (free tier)."""
    yr = datetime.now(pytz.utc).year
    r = requests.post("https://api.bls.gov/publicAPI/v2/timeseries/data/",
                      json={"seriesid": list(series_ids), "startyear": str(yr - years_back),
                            "endyear": str(yr)},
                      headers={"Content-Type": "application/json",
                               "User-Agent": "argus-research/1.0"}, timeout=15)
    if r.status_code != 200:
        return None, r.status_code
    return r.json(), 200


def _fred_raw(series_id, limit=16):
    """Raw FRED observations dict for a series (admin/cron path). None on failure/no-key."""
    if not _FRED_API_KEY:
        return None
    try:
        r = requests.get(_FRED_BASE, params={"series_id": series_id, "api_key": _FRED_API_KEY,
                         "file_type": "json", "sort_order": "desc", "limit": limit}, timeout=8)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def _macro_result_fetch(event):
    """Dispatch official-result fetch by eventCode (admin/cron only). Each adapter
    returns a normalized result via the pure parsers; missing data → partial/
    not_implemented, never fabricated."""
    code = str(event.get("eventCode") or "").upper()
    now_iso = _ai_now_iso()
    MR = argus_macro_results
    try:
        if code == "NFP":
            return _bls_nfp_result(event)
        if code == "CPI":
            raw, st = _bls_fetch(["CUSR0000SA0", "CUSR0000SA0L1E"])
            if raw is None:
                return MR._empty("rate_limited" if st == 429 else "source_unreachable",
                                 [f"BLS HTTP {st}"], "BLS")
            return MR.parse_cpi(raw, event, now_iso)
        if code == "PPI":
            raw, st = _bls_fetch(["WPSFD4", "WPSFD49104"])
            if raw is None:
                return MR._empty("source_unreachable", [f"BLS HTTP {st}"], "BLS")
            return MR.parse_ppi(raw, event, now_iso)
        if code == "JOLTS":
            raw, st = _bls_fetch(["JTS000000000000000JOL"])
            if raw is None:
                return MR._empty("source_unreachable", [f"BLS HTTP {st}"], "BLS")
            return MR.parse_jolts(raw, event, now_iso)
        if code == "PCE":
            h, c = _fred_raw("PCEPI"), _fred_raw("PCEPILFE")
            if h is None and c is None:
                return MR._empty("source_unreachable", ["FRED未取得（キー未設定または通信失敗）"], "FRED/BEA")
            return MR.parse_pce(h or {}, c or {}, event, now_iso)
        if code == "GDP":
            g = _fred_raw("A191RL1Q225SBEA")
            if g is None:
                return MR._empty("source_unreachable", ["FRED未取得"], "FRED/BEA")
            return MR.parse_gdp(g, event, now_iso)
        if code == "FOMC":
            up, lo = _fred_raw("DFEDTARU"), _fred_raw("DFEDTARL")
            if up is None and lo is None:
                return MR._empty("source_unreachable", ["FRED未取得"], "FRED/Fed")
            return MR.parse_fomc(up or {}, lo or {}, event, now_iso)
        if code == "BOJ":
            return MR.boj_partial(event, now_iso)
        return MR.not_implemented(code or "UNKNOWN", now_iso)
    except Exception as e:
        return MR._empty("parse_error", [f"取得エラー({type(e).__name__})"], MR.PROVIDER.get(code))


def _macro_important_events(limit=8):
    try:
        ev_snap = get_events_snapshot()
        items = argus_important_events.build_important_events(
            ev_snap.get("events", []) if isinstance(ev_snap, dict) else [],
            owner_symbols=_owner_symbols_for_events())
    except Exception:
        items = []
    sel = [e for e in items if e.get("displayImpact") in ("critical", "high")
           and isinstance(e.get("daysUntil"), (int, float)) and -2 <= e["daysUntil"] <= 7]
    return sel[:limit]


def _refresh_macro_results():
    """Admin/cron: fetch official results for events past their release time."""
    _macro_analysis_restore_once()
    now_iso = _ai_now_iso()
    checked = updated = 0
    for ev in _macro_important_events(10):
        eid = str(ev.get("eventId") or ev.get("eventCode") or "")
        rec = _MACRO_ANALYSIS.get(eid) or argus_macro_event_analysis.new_record(
            {**ev, "id": eid}, now_iso=now_iso)
        phase = argus_macro_event_analysis.resolve_macro_event_phase(
            rec.get("eventTimeUtc") or ev.get("eventTimeUtc"), now_iso,
            actual_available=bool((rec.get("actual") or {}).get("available")),
            event_date=rec.get("eventDate") or ev.get("eventDate"))
        if phase not in ("released_pending_result", "post_result"):
            continue
        checked += 1
        if (rec.get("actual") or {}).get("available"):
            continue
        actual = _macro_result_fetch(ev)
        # V11.5: record per-code adapter status for the result-status endpoint.
        _code = str(ev.get("eventCode") or "").upper()
        if _code in _MACRO_RESULT_STATE:
            _MACRO_RESULT_STATE[_code].update(
                status=actual.get("status") or ("live" if actual.get("available") else "partial"),
                metricsAvailable=argus_macro_results.metrics_available(actual))
            if actual.get("available"):
                _MACRO_RESULT_STATE[_code].update(lastSuccessAt=now_iso,
                                                  sampleEventId=ev.get("eventId"))
        if actual.get("available"):
            rec["actual"] = actual
            updated += 1
        else:
            rec.setdefault("actual", {}).update(limitationsJa=actual.get("limitationsJa", []),
                                                status=actual.get("status"))
        rec["updatedAt"] = now_iso
        _MACRO_ANALYSIS[eid] = argus_macro_event_store.merge_record(
            _MACRO_ANALYSIS.get(eid), rec, now_iso=now_iso)
    _MACRO_ANALYSIS_STATE["lastResultsAt"] = now_iso
    _macro_analysis_persist()
    return {"checked": checked, "resultsFetched": updated, "asOf": now_iso}


def _market_snapshot_values(cached_only=True):
    """Current market LEVELS for the reaction diff (rates yields, USDJPY, VIX, ETF
    prices, BTC). cached_only=True (public) reads caches; admin refresh may fetch."""
    vals = {}
    try:
        rs = (_RATES_CACHE.get("data") if cached_only else get_rates_snapshot()) or {}
        for k in ("us10y", "usdJpy", "vix"):
            v = ((rs.get(k) or {}).get("latestValue"))
            if isinstance(v, (int, float)):
                vals[k] = v
    except Exception:
        pass
    for k, sym in (("spy", "SPY"), ("qqq", "QQQ"), ("iwm", "IWM"), ("gold", "GLD")):
        try:
            q = _quote_cached_only(sym, "US") or {}
            p = q.get("price")
            if isinstance(p, (int, float)):
                vals[k] = p
        except Exception:
            pass
    try:
        cs = get_crypto_watchlist_snapshot(("bitcoin",)) if not cached_only else \
            (_CRYPTO_CACHE.get(("bitcoin",)) or {}).get("data")
        for q in ((cs or {}).get("quotes") or []):
            if q.get("id") == "bitcoin" and isinstance(q.get("priceUsd"), (int, float)):
                vals["btc"] = q["priceUsd"]
    except Exception:
        pass
    return vals


def _refresh_macro_market_reaction():
    """Admin/cron: for events released in the last 48h, capture a baseline on first
    observation, then compute the reaction (baseline → now) and merge it in. No LLM.
    If post.marketReactionJa is empty, fill a deterministic summary."""
    _macro_analysis_restore_once()
    now_iso = _ai_now_iso()
    now_vals = _market_snapshot_values(cached_only=False)
    checked = updated = 0
    items = []
    for eid, rec in list(_MACRO_ANALYSIS.items()):
        phase = argus_macro_event_analysis.resolve_macro_event_phase(
            rec.get("eventTimeUtc"), now_iso,
            actual_available=bool((rec.get("actual") or {}).get("available")),
            event_date=rec.get("eventDate"))
        if phase not in ("released_pending_result", "post_result"):
            continue
        rel_hrs = None
        try:
            a = argus_macro_event_analysis._parse_utc(rec.get("eventTimeUtc"))
            b = argus_macro_event_analysis._parse_utc(now_iso)
            rel_hrs = (b - a).total_seconds() / 3600.0 if (a and b) else None
        except Exception:
            rel_hrs = None
        if rel_hrs is not None and rel_hrs > 48:
            continue
        checked += 1
        mr = dict(rec.get("marketReaction") or {})
        baseline = mr.get("baseline")
        if not baseline:
            # first observation: capture the baseline (honest "初回観測時点", not 発表直前)
            mr["baseline"] = {**now_vals, "capturedAt": now_iso}
            rec["marketReaction"] = mr
            rec["updatedAt"] = now_iso
            _MACRO_ANALYSIS[eid] = argus_macro_event_store.merge_record(
                _MACRO_ANALYSIS.get(eid), rec, now_iso=now_iso)
            items.append({"eventId": eid, "eventCode": rec.get("eventCode"),
                          "windowsUpdated": [], "summaryJa": "",
                          "limitationsJa": ["初回観測でベースラインを取得（次回以降に反応を算出）"]})
            continue
        reaction = argus_macro_market_reaction.build_reaction(
            event_id=eid, event_code=str(rec.get("eventCode") or ""),
            windows_io=[{"window": "same_day", "before": baseline, "after": now_vals}],
            now_iso=now_iso)
        compact = argus_macro_market_reaction.compact_for_store(reaction)
        compact["baseline"] = baseline
        rec["marketReaction"] = compact
        # fill a deterministic market-reaction summary if the AI post didn't
        post = dict(rec.get("post") or {})
        if not post.get("marketReactionJa") and compact.get("summaryJa"):
            post["marketReactionJa"] = compact["summaryJa"]
            rec["post"] = post
        rec["updatedAt"] = now_iso
        _MACRO_ANALYSIS[eid] = argus_macro_event_store.merge_record(
            _MACRO_ANALYSIS.get(eid), rec, now_iso=now_iso)
        wins = [w["window"] for w in (compact.get("windows") or [])
                if any(w.get(k) is not None for k in argus_macro_market_reaction._ASSET_KEYS)]
        updated += 1
        items.append({"eventId": eid, "eventCode": rec.get("eventCode"),
                      "windowsUpdated": wins, "summaryJa": compact.get("summaryJa", ""),
                      "limitationsJa": compact.get("limitationsJa", [])})
    _MACRO_ANALYSIS_STATE["lastReactionAt"] = now_iso
    _macro_analysis_persist()
    return {"schemaVersion": "macro-reaction-refresh-v1", "asOf": now_iso,
            "checked": checked, "updated": updated, "items": items[:20]}


def _generate_macro_event_analysis(limit=8):
    """Admin/cron: the ONLY model-calling path for macro pre/post analysis.
    PRE is refreshed only on checkpoint/TTL; POST runs only with a real official
    result + the PRESERVED pre; released_pending stays '公式結果待ち'."""
    _macro_analysis_restore_once()
    now_iso = _ai_now_iso()
    ctx = _macro_market_context_ja()
    made_pre = made_post = 0
    for ev in _macro_important_events(limit):
        eid = str(ev.get("eventId") or ev.get("eventCode") or "")
        rec = _MACRO_ANALYSIS.get(eid) or argus_macro_event_analysis.new_record(
            {**ev, "id": eid}, now_iso=now_iso)
        rec["eventTimeUtc"] = rec.get("eventTimeUtc") or ev.get("eventTimeUtc")
        rec["eventDate"] = rec.get("eventDate") or ev.get("eventDate")
        phase = argus_macro_event_analysis.resolve_macro_event_phase(
            rec.get("eventTimeUtc"), now_iso,
            actual_available=bool((rec.get("actual") or {}).get("available")),
            event_date=rec.get("eventDate"))
        rec["phase"] = phase
        rec["daysUntil"] = ev.get("daysUntil")
        rec["displayImpact"] = ev.get("displayImpact")
        if argus_macro_event_analysis.should_refresh_pre(rec, phase, now_iso=now_iso):
            out = _openai_prose(argus_macro_event_analysis.build_pre_prompt(ev, ctx), max_out=700,
                                system=argus_macro_event_analysis.MACRO_EVENT_SYSTEM_JA)
            pre = argus_macro_event_analysis.parse_pre(out, phase=phase, now_iso=now_iso)
            if pre:
                rec["pre"] = pre
                made_pre += 1
        if phase == "post_result":
            post = rec.get("post") or {}
            if post.get("verdict") in (None, "", "not_available", "not_scoreable") or not post.get("generatedAt"):
                pre_exists = bool((rec.get("pre") or {}).get("argusScenarioJa")
                                  or (rec.get("pre") or {}).get("summaryJa"))
                out = _openai_prose(argus_macro_event_analysis.build_post_prompt(
                    ev, rec.get("pre") or {}, rec.get("actual") or {}, ctx), max_out=700,
                    system=argus_macro_event_analysis.MACRO_EVENT_SYSTEM_JA)
                rec["post"] = argus_macro_event_analysis.parse_post(
                    out or {}, now_iso=now_iso, pre_exists=pre_exists,
                    actual_available=bool((rec.get("actual") or {}).get("available")))
                made_post += 1
        rec["updatedAt"] = now_iso
        _MACRO_ANALYSIS[eid] = argus_macro_event_store.merge_record(
            _MACRO_ANALYSIS.get(eid), rec, now_iso=now_iso)
    _MACRO_ANALYSIS_STATE["lastGenerateAt"] = now_iso
    _macro_analysis_persist()
    return {"pre": made_pre, "post": made_post, "total": len(_MACRO_ANALYSIS), "asOf": now_iso}


def _macro_compat_item(rec):
    """Backward-compatible projection (the legacy /event-analysis shape CaosHub reads)."""
    pre, post, actual = rec.get("pre") or {}, rec.get("post") or {}, rec.get("actual") or {}
    phase = rec.get("phase") or ""
    legacy_phase = "post" if phase.startswith(("released", "post")) else "pre"
    post_ja = post.get("answerCheckJa") or ""
    if legacy_phase == "post" and not post_ja:
        post_ja = ("公式結果待ち" if not actual.get("available") else "答え合わせ生成待ち…")
    return {"eventId": rec.get("eventId"), "eventCode": rec.get("eventCode"),
            "phase": legacy_phase, "phaseDetail": phase,
            "displayImpact": rec.get("displayImpact"), "daysUntil": rec.get("daysUntil"),
            "summaryJa": pre.get("summaryJa") or "",
            "preJa": pre.get("argusScenarioJa") or "",
            "postJa": post_ja,
            "generatedAt": pre.get("generatedAt") or post.get("generatedAt"),
            "actualAvailable": bool(actual.get("available")),
            "verdict": post.get("verdict")}


@app.route("/api/argus/macro-event-analysis")
def api_argus_macro_event_analysis():
    """Public cache-only: durable macro-event pre/post analyses. Never calls an LLM,
    never fetches an official result."""
    _macro_analysis_restore_once()
    rows = list(_MACRO_ANALYSIS.values())
    code = (request.args.get("eventCode") or "").strip().upper()
    phase = (request.args.get("phase") or "").strip()
    if code:
        rows = [r for r in rows if str(r.get("eventCode") or "").upper() == code]
    if phase:
        rows = [r for r in rows if r.get("phase") == phase]
    rows.sort(key=lambda r: str(r.get("eventTimeUtc") or r.get("eventDate") or ""))
    try:
        limit = max(1, min(50, int(request.args.get("limit", "20"))))
    except Exception:
        limit = 20
    return jsonify({"asOf": _ai_now_iso(), "schemaVersion": argus_macro_event_store.SCHEMA_VERSION,
                    "count": len(rows), "items": rows[:limit]})


@app.route("/api/argus/macro-event-analysis/status")
def api_argus_macro_event_analysis_status():
    _macro_analysis_restore_once()
    rows = list(_MACRO_ANALYSIS.values())
    by_phase = {}
    for r in rows:
        by_phase[r.get("phase")] = by_phase.get(r.get("phase"), 0) + 1
    return jsonify({"asOf": _ai_now_iso(), "schemaVersion": argus_macro_event_store.SCHEMA_VERSION,
                    "total": len(rows), "byPhase": by_phase,
                    "withPre": sum(1 for r in rows if (r.get("pre") or {}).get("argusScenarioJa")),
                    "withActual": sum(1 for r in rows if (r.get("actual") or {}).get("available")),
                    "lastGenerateAt": _MACRO_ANALYSIS_STATE.get("lastGenerateAt"),
                    "lastResultsAt": _MACRO_ANALYSIS_STATE.get("lastResultsAt"),
                    "pathType": _MACRO_ANALYSIS_STATE.get("pathType"),
                    "noteJa": "発表前の予想を保存し、発表後に公式結果と照合して答え合わせ。結果もコンセンサスも捏造しない。"})


@app.route("/api/argus/macro-event-analysis/<eid>")
def api_argus_macro_event_analysis_one(eid):
    _macro_analysis_restore_once()
    r = _MACRO_ANALYSIS.get(str(eid))
    if not r:
        return jsonify({"error": "not_found", "eventId": eid}), 404
    return jsonify(r)


@app.route("/api/argus/macro-events/result-status")
def api_argus_macro_result_status():
    """Public cache-only: one row per event code with its adapter status. Reports
    cached/probed status only — never fetches a provider on this GET."""
    srcs = []
    for code, st in _MACRO_RESULT_STATE.items():
        srcs.append({"eventCode": code, "provider": st.get("provider"),
                     "status": st.get("status"), "lastSuccessAt": st.get("lastSuccessAt"),
                     "sampleEventId": st.get("sampleEventId"),
                     "metricsAvailable": list(st.get("metricsAvailable") or []),
                     "limitationsJa": []})
    srcs += [{"eventCode": c, "provider": argus_macro_results.PROVIDER.get(c),
              "status": ("partial" if c == "BOJ" else "not_implemented"),
              "lastSuccessAt": None, "sampleEventId": None, "metricsAvailable": [],
              "limitationsJa": ["公式結果アダプタ未実装/部分実装（結果は捏造しない）"]}
             for c in _MACRO_NOT_IMPLEMENTED]
    srcs.sort(key=lambda s: s["eventCode"])
    return jsonify({"schemaVersion": "macro-result-status-v1", "asOf": _ai_now_iso(),
                    "sources": srcs})


@app.route("/api/argus/admin/macro-event-analysis/generate", methods=["POST"])
def api_argus_admin_macro_generate():
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    return jsonify(_generate_macro_event_analysis())


@app.route("/api/argus/admin/macro-event-analysis/refresh-results", methods=["POST"])
def api_argus_admin_macro_refresh_results():
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    return jsonify(_refresh_macro_results())


@app.route("/api/argus/admin/macro-event-analysis/refresh-market-reaction", methods=["POST"])
def api_argus_admin_macro_refresh_market_reaction():
    """Admin/cron: compute market-reaction windows for recently-released events
    (no LLM). Baseline captured on first observation; reaction merged into the store."""
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    try:
        return jsonify(_refresh_macro_market_reaction())
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {str(e)[:160]}"}), 500


@app.route("/api/argus/admin/news/translate", methods=["POST"])
def api_argus_admin_news_translate():
    """Admin/cron: translate queued English news headlines to Japanese, VISIBLE-FIRST,
    and cache them (the LLM call lives here, never on a public GET). Owner rule: news is
    always shown translated. Never returns prompts or article bodies."""
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    body = request.get_json(silent=True) or {}
    try:
        cap = max(1, min(120, int(body.get("max") or 60)))
    except Exception:
        cap = 60
    try:
        return jsonify(_translate_pending_headlines(cap=cap))
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {str(e)[:160]}"}), 500


@app.route("/api/argus/news/translation-request", methods=["POST"])
def api_argus_news_translation_request():
    """PUBLIC, enqueue-only. The UI posts on-screen English news titles so they are
    guaranteed to enter the visible-first translation queue. NEVER calls an LLM or a
    provider. Ignores Japanese titles + already-translated titles; dedupes by title
    hash; throttled per IP+context. Stores only titleOriginal/source/publishedAt."""
    _news_ja_restore_once()
    body = request.get_json(silent=True) or {}
    ctx = str(body.get("context") or "")[:40]
    sym = str(body.get("symbol") or "")[:16]
    mkt = str(body.get("market") or "")[:4]
    items = body.get("items") if isinstance(body.get("items"), list) else []
    now_iso = _ai_now_iso()
    base = {"schemaVersion": "news-translation-request-v1"}
    # per-IP+context throttle (the global before_request limiter also applies)
    ip = _client_meta().get("ip") or ""
    rlk = f"{ip}|{ctx}"
    nowt = time.time()
    if nowt - float(_NEWS_JA_VQUEUE_RL.get(rlk, 0.0)) < _NEWS_JA_VQUEUE_RL_SEC:
        st = argus_news_i18n.translation_queue_status(_NEWS_JA_VQUEUE)
        return jsonify({**base, "ok": True, "queued": 0, "alreadyTranslated": 0,
                        "alreadyQueued": 0, "rateLimited": True,
                        "queueRemaining": st["queuedCount"],
                        "nextRunHintJa": "次回の翻訳処理で反映されます。"}), 200
    _NEWS_JA_VQUEUE_RL[rlk] = nowt
    if len(_NEWS_JA_VQUEUE_RL) > 2000:
        _NEWS_JA_VQUEUE_RL.clear()
    stats = argus_news_i18n.visible_queue_add(
        _NEWS_JA_VQUEUE, items[:40], _NEWS_JA_CACHE, context=ctx, symbol=sym,
        market=mkt, now_iso=now_iso)
    if stats["queued"]:
        _news_ja_persist()
    st = argus_news_i18n.translation_queue_status(_NEWS_JA_VQUEUE)
    return jsonify({**base, "ok": True, "queued": stats["queued"],
                    "alreadyTranslated": stats["alreadyTranslated"],
                    "alreadyQueued": stats["alreadyQueued"], "ignored": stats["ignored"],
                    "rateLimited": False, "queueRemaining": st["queuedCount"],
                    "nextRunHintJa": "次回の翻訳処理で反映されます。"}), 200


@app.route("/api/argus/admin/news/translate-visible", methods=["POST"])
def api_argus_admin_news_translate_visible():
    """Admin/cron: translate the VISIBLE queue first, then the inferred visible pool.
    The LLM call lives here — never on a public GET/POST. No prompts/bodies stored."""
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    body = request.get_json(silent=True) or {}
    try:
        cap = max(1, min(120, int(body.get("max") or 60)))
    except Exception:
        cap = 60
    try:
        return jsonify(_translate_pending_headlines(cap=cap, queue_first=True))
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {str(e)[:160]}"}), 500


@app.route("/api/argus/news/ja-cache-snapshot")
def api_argus_news_ja_cache_snapshot():
    """Public cache-only artifact for the ledger workflow (v11.9.1): the JA
    translation cache, bounded to the newest ~1200 entries. Contains ONLY
    hash→{ja,at} + public timestamps — no originals, no secrets, no owner data.
    The 24/7 caos-scan workflow commits this to ledger/news-ja/latest.json so a
    redeploy no longer wipes every translation back to 翻訳待ち."""
    _news_ja_restore_once()
    items = sorted(_NEWS_JA_CACHE.items(),
                   key=lambda kv: str((kv[1] or {}).get("at") or ""), reverse=True)[:1200]
    return jsonify({"schemaVersion": "news-ja-cache-v1", "asOf": _ai_now_iso(),
                    "cache": dict(items),
                    "state": {"lastTranslateAt": _NEWS_JA_STATE.get("lastTranslateAt")},
                    "count": len(items)})


@app.route("/api/argus/news/translation-status")
def api_argus_news_translation_status():
    """Public cache-only: translation coverage for the VISIBLE news + overall. Reads
    caches only — never triggers a translation, never calls an LLM/provider."""
    _news_ja_restore_once()
    now_iso = _ai_now_iso()
    try:
        visible = _news_visible_pool()
    except Exception:
        visible = []
    vis_titles = [str(t) for t in visible if t]
    vis_translatable = [t for t in vis_titles if argus_news_i18n.looks_translatable(t)]
    vis_pending = [t for t in vis_translatable if not argus_news_i18n.is_translated(t, _NEWS_JA_CACHE)]
    vis_pct = round(1.0 - (len(vis_pending) / len(vis_translatable)), 3) if vis_translatable else 1.0
    # how many of the still-pending visible titles are already in the explicit queue
    vis_queued = [t for t in vis_pending
                  if argus_news_i18n.text_hash(t) in _NEWS_JA_VQUEUE]
    vis_queued_pct = round(len(vis_queued) / len(vis_translatable), 3) if vis_translatable else 0.0
    all_translatable = len(vis_translatable) or 0
    translated_today = int(_NEWS_JA_STATE.get("translatedToday") or 0) \
        if _NEWS_JA_STATE.get("translatedDay") == now_iso[:10] else 0
    qstat = argus_news_i18n.translation_queue_status(_NEWS_JA_VQUEUE)
    # translatedRecent samples: most-recent cache entries (JA is a public headline; no body)
    recent = sorted(_NEWS_JA_CACHE.values(), key=lambda e: str(e.get("at")), reverse=True)[:5]
    return jsonify({
        "schemaVersion": "news-translation-status-v1", "asOf": now_iso,
        "cachedCount": len(_NEWS_JA_CACHE),
        "pendingQueue": len(_NEWS_JA_SEEN),
        "visiblePendingCount": len(vis_pending),
        "translatedToday": translated_today,
        "lastTranslateAt": _NEWS_JA_STATE.get("lastTranslateAt"),
        "nextTranslateHintJa": "重要度の高い値動きから約15分ごとに翻訳します。",
        "visibleQueue": {
            "queuedCount": qstat["queuedCount"],
            "oldestQueuedAt": qstat["oldestQueuedAt"],
            "lastQueuedAt": qstat["lastQueuedAt"],
            "lastDrainAt": _NEWS_JA_VQUEUE_STATE.get("lastDrainAt"),
            "lastDrainCount": _NEWS_JA_VQUEUE_STATE.get("lastDrainCount"),
            "durable": _NEWS_JA_QUEUE_DURABLE},
        "coverage": {"visibleTranslatedPct": vis_pct,
                     "visibleQueuedPct": vis_queued_pct,
                     "allTranslatedPct": round(1.0 - (len(vis_pending) / all_translatable), 3)
                     if all_translatable else 1.0},
        "samples": {
            "pendingVisible": argus_news_i18n.queue_samples(_NEWS_JA_VQUEUE, cap=5),
            "translatedRecent": [{"titlePreview": str(e.get("ja") or "")[:60],
                                  "at": e.get("at")} for e in recent]},
        "noteJa": "英語ニュースは管理側で翻訳してキャッシュ表示。公開GETは翻訳を起動しません。"})


# ── V11.4.1 Unified dashboard event summary ──────────────────────────────────
def _build_dashboard_events(limit=8, importance=None):
    """Merge cached important events + macro analysis records into the unified
    display model. Cache-only: reads the in-memory macro store + the (public-safe)
    important-events snapshot; never calls an LLM, never fetches an official result."""
    _macro_analysis_restore_once()
    now_iso = _ai_now_iso()
    try:
        ie = _macro_important_events(12)
    except Exception:
        ie = []
    recs = list(_MACRO_ANALYSIS.values())
    summ = argus_dashboard_event_summary.build_summary(
        important_events=ie, macro_records=recs, now_iso=now_iso, limit=20)
    items = summ["items"]
    if importance in ("critical", "high"):
        items = [it for it in items if it.get("importance") == importance]
    items = items[:max(1, min(20, int(limit or 8)))]
    return summ, items, now_iso


@app.route("/api/argus/dashboard-events")
def api_argus_dashboard_events():
    """Public cache-only: the single unified event surface for the top dashboard
    card. Merges ImportantEvents + macro pre/actual/post, RE-RESOLVES the display
    state from the real release clock (so a record generated pre-release flips to
    post/pending after release), and de-duplicates. No LLM, no provider fetch."""
    try:
        limit = int(request.args.get("limit", "8"))
    except Exception:
        limit = 8
    importance = (request.args.get("importance") or "").strip().lower()
    include_details = (request.args.get("includeDetails") or "").lower() in ("1", "true", "yes")
    summ, items, now_iso = _build_dashboard_events(limit, importance)
    st = argus_dashboard_event_summary.status_counts({"items": items})
    dedupe = dict(summ["dedupe"])
    dedupe["mergedCount"] = len(items)
    if not include_details:
        dedupe["detailsJa"] = []
    return jsonify({
        "schemaVersion": argus_dashboard_event_summary.SCHEMA_VERSION,
        "asOf": now_iso, "items": items, "dedupe": dedupe,
        "status": {**st,
                   "lastMacroAnalysisAt": _MACRO_ANALYSIS_STATE.get("lastGenerateAt"),
                   "lastHotRefreshAt": _MACRO_ANALYSIS_STATE.get("lastResultsAt")},
    })


def _repair_post_release():
    """Admin/cron: repair stuck displays after a major release — fetch official
    results, recompute phase, generate/repair the post answer-check where the
    result is available and the pre was preserved. Uses the existing budgeted
    refresh+generate; never fabricates a result, never touches future pre records."""
    _macro_analysis_restore_once()
    before_actual = {eid: bool((r.get("actual") or {}).get("available"))
                     for eid, r in _MACRO_ANALYSIS.items()}
    before_post = {eid: bool((r.get("post") or {}).get("generatedAt"))
                   for eid, r in _MACRO_ANALYSIS.items()}
    _refresh_macro_results()                 # official results for released events
    _generate_macro_event_analysis()         # post answer-check where actual + pre exist
    now_iso = _ai_now_iso()
    checked = actual_updated = post_generated = 0
    items = []
    for eid, r in _MACRO_ANALYSIS.items():
        aa = bool((r.get("actual") or {}).get("available"))
        pg = bool((r.get("post") or {}).get("generatedAt"))
        phase = argus_macro_event_analysis.resolve_macro_event_phase(
            r.get("eventTimeUtc"), now_iso, actual_available=aa, event_date=r.get("eventDate"))
        if phase in ("released_pending_result", "post_result"):
            checked += 1
        if aa and not before_actual.get(eid):
            actual_updated += 1
        if pg and not before_post.get(eid):
            post_generated += 1
        items.append({"eventCode": r.get("eventCode"), "phase": phase,
                      "actualAvailable": aa, "postGenerated": pg})
    _macro_analysis_persist()
    return {"ok": True, "checked": checked, "actualUpdated": actual_updated,
            "postGenerated": post_generated, "displayUpdated": len(items),
            "items": items[:20], "asOf": now_iso}


@app.route("/api/argus/admin/macro-event-analysis/repair-post-release", methods=["POST"])
def api_argus_admin_macro_repair_post_release():
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    try:
        return jsonify(_repair_post_release())
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {str(e)[:160]}"}), 500


@app.route("/api/argus/event-analysis")
def api_argus_event_analysis():
    """Public GET — backward-compatible projection of the NEW durable macro analysis
    (v11.3.2). Falls back to the legacy /tmp store until the first generation runs."""
    _macro_analysis_restore_once()
    if _MACRO_ANALYSIS:
        its = [_macro_compat_item(r) for r in _MACRO_ANALYSIS.values()]
        its.sort(key=lambda x: (0 if x.get("phase") == "post" else 1,
                                x.get("daysUntil") if x.get("daysUntil") is not None else 99))
        return jsonify({"asOf": _MACRO_ANALYSIS_STATE.get("lastGenerateAt") or _ai_now_iso(),
                        "system": argus_research_mesh.SYSTEM_NAME, "items": its})
    its = sorted(_EVENT_ANALYSIS["items"].values(),
                 key=lambda x: (0 if x.get("phase") == "post" else 1, x.get("daysUntil") if x.get("daysUntil") is not None else 99))
    return jsonify({"asOf": _EVENT_ANALYSIS.get("asOf"), "system": argus_research_mesh.SYSTEM_NAME,
                    "items": its})


@app.route("/api/argus/event-analysis/generate", methods=["POST"])
def api_argus_event_analysis_generate():
    """Admin/cron — repointed to the NEW macro analysis (v11.3.2): refresh official
    results first, then generate pre/post. Keeps the existing ai-rejudge cron working."""
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    res = _refresh_macro_results()
    gen = _generate_macro_event_analysis()
    return jsonify({"results": res, "generated": gen})


@app.route("/api/argus/entity-profiles")
def api_argus_entity_profiles():
    """Public (cache-only): the association-engine profiles (business + relationships)."""
    return jsonify({"asOf": _ENTITY_PROFILES_META.get("asOf"), "count": len(_ENTITY_PROFILES),
                    "profiles": _ENTITY_PROFILES})


@app.route("/api/argus/entity-profiles/generate", methods=["POST"])
def api_argus_entity_profiles_generate():
    """Owner/admin — generate profiles. With `symbol` (+name/market) force-generates THAT one
    on demand (for device-added stocks the cron doesn't know); otherwise bulk-generates the
    backend watchlist (the cron path). Owner-sync token (header or body) accepted."""
    body = request.get_json(silent=True) or {}
    ok, err, code = _require_owner_sync(body_token=body.get("ownerToken"))
    if not ok:
        return jsonify(err), code
    sym = str(body.get("symbol") or "").strip().upper()
    if sym:
        prev = _ENTITY_PROFILES.get(sym)
        if prev and prev.get("source") == "owner" and not body.get("force"):
            return jsonify({"ok": True, "skipped": "owner-edited", "symbol": sym, "profile": prev})
        prof = _entity_profile_make(sym, str(body.get("name") or "")[:60], str(body.get("market") or ""))
        _entity_profile_persist()
        return jsonify({"ok": bool(prof), "symbol": sym, "profile": prof})
    return jsonify(_entity_profile_generate())


@app.route("/api/argus/entity-profiles/edit", methods=["POST"])
def api_argus_entity_profiles_edit():
    """Owner-edited profile override (source='owner') — persists, TAKES PRECEDENCE over the
    seed/AI, and is never overwritten by the AI generator. Gated by the owner-sync (or admin)
    token (header or body). Lets the owner customize the association metadata from the UI."""
    body = request.get_json(silent=True) or {}
    ok, err, code = _require_owner_sync(body_token=body.get("ownerToken"))
    if not ok:
        return jsonify(err), code
    sym = str(body.get("symbol") or "").strip().upper()
    if not sym:
        return jsonify({"error": "symbol_required"}), 400
    prev = _ENTITY_PROFILES.get(sym, {})

    def clip(v, n):
        return str(v if v is not None else "")[:n]

    prof = {
        "symbol": sym, "name": clip(body.get("name") or prev.get("name") or sym, 60),
        "businessJa": clip(body.get("businessJa"), 400), "sector": clip(body.get("sector"), 80),
        "themes": [clip(t, 40) for t in (body.get("themes") or []) if str(t).strip()][:12],
        "relatedEntities": [{"name": clip(e.get("name"), 80), "relationJa": clip(e.get("relationJa"), 160),
                             "type": clip(e.get("type"), 30)}
                            for e in (body.get("relatedEntities") or [])
                            if isinstance(e, dict) and str(e.get("name") or "").strip()][:14],
        "peers": [clip(p, 30) for p in (body.get("peers") or []) if str(p).strip()][:10],
        "keywords": [clip(k, 40) for k in (body.get("keywords") or []) if str(k).strip()][:30],
        "source": "owner", "ts": time.time(), "editedAt": _ai_now_iso(),
    }
    _ENTITY_PROFILES[sym] = prof
    _ENTITY_PROFILES_META["asOf"] = _ai_now_iso()
    _entity_profile_persist()
    return jsonify({"ok": True, "symbol": sym, "profile": prof})


@app.route("/api/argus/buy-candidates")
def api_argus_buy_candidates():
    """Public (cache-only): high-bar screened buy candidates (本日の注目候補)."""
    return jsonify({"asOf": _BUY_CANDIDATES.get("asOf"), "items": _BUY_CANDIDATES.get("items", [])})


@app.route("/api/argus/buy-candidates/generate", methods=["POST"])
def api_argus_buy_candidates_generate():
    """Admin/cron — screen today's movers into high-conviction buy candidates."""
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    return jsonify(_buy_candidates_generate())


_caos_event_restore()       # reload persisted analyses at startup
_entity_profile_restore()   # load entity profiles (seed + persisted) at startup
_buy_candidates_restore()   # load persisted buy candidates at startup


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

# ── Legacy /api/* lockdown (v10.88, GPT P0 #1) ──────────────────────────────
# The pre-ARGUS scanner left these UNAUTHENTICATED: /api/run starts a background
# scan, /api/reset wipes state, plus /api/logs|chart|price_*|order_book|margin
# expose data. The ARGUS frontend uses /api/argus/* only, so admin-gate the bare
# legacy routes (CORS is a browser rule, not auth — curl bypasses it).
_LEGACY_API_PREFIXES = ("/api/run", "/api/reset", "/api/logs", "/api/chart",
                        "/api/price_history", "/api/price_now", "/api/order_book",
                        "/api/margin")

@app.before_request
def _gate_legacy_api():
    if request.method == "OPTIONS":
        return None  # let CORS preflight through
    p = request.path or ""
    if any(p.startswith(x) for x in _LEGACY_API_PREFIXES):
        ok, err, code = _require_admin()
        if not ok:
            return jsonify(err), code
    return None

def _ai_run_gate(force=False):
    """(allowed, payload, http_code). Validates enabled/locked/country/interval/
    daily-count AND the ARGUS-side USD hard budget. Records the run when allowed.
    force=True (admin) may dip into the small monthly emergency reserve only."""
    now = time.time()
    meta = _client_meta()
    if not _AI_JUDGE_ENABLED:
        return False, {"status": "disabled", "reason": "AI judgment is not enabled yet.",
                       "asOf": _ai_now_iso(), "locked": _is_locked()}, 200
    # HARD budget stop (v10.50): the OpenAI prepaid balance is NOT our stop — this
    # is. Restore the month baseline first so a dyno restart can't reset it.
    _ai_cost_restore_once()
    with _AI_LOCK:
        _ai_cost_roll(datetime.now(TZ_JST))
        day_s, month_s = _AI_COST_STATE["daySpentUsd"], _AI_COST_STATE["monthSpentUsd"]
    ok_budget, why, used_reserve = argus_ai_cost.budget_check(
        day_s, month_s, _AI_DAILY_BUDGET_USD, _AI_MONTHLY_BUDGET_USD,
        reserve_usd=_AI_EMERGENCY_RESERVE_USD, force=force)
    if not ok_budget:
        send_security_alert({"type": "run_blocked_budget", "meta": meta})
        return False, {"status": "budget_exceeded", "reason": why,
                       "daySpentUsd": round(day_s, 4), "monthSpentUsd": round(month_s, 4),
                       "dailyBudgetUsd": _AI_DAILY_BUDGET_USD, "monthlyBudgetUsd": _AI_MONTHLY_BUDGET_USD,
                       "asOf": _ai_now_iso()}, 429
    if used_reserve:
        send_security_alert({"type": "run_used_emergency_reserve", "meta": meta})
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
    # Freshness truth (v10.36, #4): distinguish a FRESH in-cache run from a
    # PERSISTED one restored from the ledger branch (last good run, maybe from a
    # prior day). A 30-min TTL lapsing does NOT mean yesterday's judgment ceased
    # to exist — show it as persisted/stale with its age, not "no result".
    now = time.time()
    cache_valid = bool(_AI_RESULT_CACHE["data"]) and now < _AI_RESULT_CACHE["expires"]
    cached = _ai_cached_result()
    if cached:
        as_of = cached.get("asOf")
        age_min = _age_min_iso(as_of)
        restored = cached.get("runMode") == "restored"
        # Session-aware freshness: a Friday run on Saturday is 'persisted'
        # (current for the latest session), only a genuinely MISSED run is stale.
        freshness = _ai_session_freshness(as_of, age_min)
        if freshness == "fresh" and restored:
            freshness = "persisted"          # restored ≠ a fresh live run
        run_mode = "cached" if (freshness == "fresh" and not restored) else "restored" if restored else "cached"
        expires_in = (max(0, int((_AI_RESULT_CACHE["expires"] - now) / 60))
                      if (freshness == "fresh" and cache_valid) else None)
        return jsonify({**cached, "runMode": run_mode,
                        "freshness": freshness, "ageMin": age_min,
                        "cacheExpiresInMin": expires_in,
                        "models": cached.get("models") or {"primary": _OPENAI_MODEL,
                                                            "checker": _GEMINI_JUDGE_MODEL},
                        "nextScheduledRun": _next_weekday_run_iso(16, 5),
                        "nextScheduledRunJa": "平日16:05 JST(予測台帳cron)",
                        "fallbackJa": "Action Labelは常にルールベースが主。AIは時刻付きの第二意見で、"
                                      "未実行/失効でも判定の土台は変わりません。"})
    return jsonify({**_ai_disabled_payload(
        "not_run_yet", "まだ自動AI判定が実行されていません(次回 平日16:05 JST)。"),
        "freshness": "not_run_yet", "nextScheduledRunJa": "平日16:05 JST(予測台帳cron)",
        "fallbackJa": "Action Labelはルールベースで稼働中。AIは未実行(第二意見待ち)。"})

@app.route("/api/argus/ai-judgment/run", methods=["POST"])
def api_argus_ai_judgment_run():
    # Admin-gated fresh run: GPT-5.5 primary + Gemini double-check. NEVER reachable
    # from the public frontend (admin token required).
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    # ?force=1 (admin) may dip into the small monthly emergency reserve only.
    force = str(request.args.get("force", "")).strip().lower() in ("1", "true", "yes", "on")
    allowed, info, code = _ai_run_gate(force=force)
    if not allowed:
        return jsonify(info), code
    # ?checker=flash|pro picks the Gemini double-check tier (default pro). The 15-min
    # ai-rejudge cron passes flash (cheap, frequent); the daily scored run passes pro.
    checker = (request.args.get("checker") or "").strip().lower()
    checker = checker if checker in ("flash", "pro") else None
    return jsonify(_execute_ai_judgment(run_mode="manual", checker=checker))

@app.route("/api/argus/ai-cost")
def api_argus_ai_cost():
    # Protected Operations: AI spend vs budget + last-run cost. No prompts/keys.
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    return jsonify(_ai_cost_snapshot())

def _system_health():
    """PUBLIC-safe at-a-glance health lamps for the metered/important systems
    (green=ok, amber=warning, red=stopped). Colors + coarse JA only — NO dollar
    amounts or secrets (those stay in the admin-only Operations endpoints). The
    point: a silent budget stop / bridge outage becomes VISIBLE at a glance."""
    now = time.time()
    lamps = []
    def L(key, label, status, detail):
        lamps.append({"key": key, "labelJa": label, "status": status, "detailJa": detail})

    # ── AI budget (the 'overheat' lamp) — color only, never the $ amount. ──
    with _AI_LOCK:
        _ai_cost_roll(datetime.now(TZ_JST))
        day_s, mon_s = _AI_COST_STATE["daySpentUsd"], _AI_COST_STATE["monthSpentUsd"]
    def _frac(s, b): return (s / b) if (isinstance(b, (int, float)) and b > 0) else 0.0
    worst = max(_frac(day_s, _AI_DAILY_BUDGET_USD), _frac(mon_s, _AI_MONTHLY_BUDGET_USD))
    if worst >= 1.0:
        L("ai_budget", "AI予算", "stopped", "上限到達 — 新規AI実行を停止中")
    elif worst >= 0.8:
        L("ai_budget", "AI予算", "warning", "残りわずか(上限の80%超)")
    else:
        L("ai_budget", "AI予算", "ok", "余裕あり")

    integ = get_integrations_snapshot()
    prov = {p["id"]: p for p in integ.get("providers", [])}
    def conf(pid): return bool((prov.get(pid) or {}).get("configured"))

    # AI judge availability (stable: based on enabled + key present, not per-worker probe)
    if not _AI_JUDGE_ENABLED:
        L("ai_judge", "AI判断", "off", "未有効")
    elif _OPENAI_API_KEY or GEMINI_API_KEY:
        L("ai_judge", "AI判断", "ok", "稼働可")
    else:
        L("ai_judge", "AI判断", "warning", "キー未設定")

    # v11.5.7 SEGMENTED bridge lamps (Jul-3 incident): "all green" must never
    # imply JP realtime works when the account has no JP quote entitlement.
    # Bridge process / OpenD / US realtime / JP realtime are evaluated apart.
    hb = _BRIDGE_HB.get("data")
    hb_age = (now - _BRIDGE_HB["receivedAt"]) if hb else None
    ages = [now - rec["ts"] for mkt in ("JP", "US")
            for rec in (_PUSHED_QUOTES.get(mkt) or {}).values() if rec.get("ts")]
    us_ages = [now - rec["ts"] for rec in (_PUSHED_QUOTES.get("US") or {}).values() if rec.get("ts")]
    jp_ages = [now - rec["ts"] for rec in (_PUSHED_QUOTES.get("JP") or {}).values() if rec.get("ts")]
    jp_open, us_open = _jp_market_open(), _us_market_open()
    mkt_open = jp_open or us_open
    if hb is not None:
        # bridge process: heartbeat keeps flowing even while markets are closed
        opend = str(hb.get("openDStatus") or "unknown")
        disk = hb.get("diskUsagePct")
        disk_txt = f" · disk {disk}%" if isinstance(disk, (int, float)) else ""
        if opend == "sms_required":
            L("bridge", "moomooブリッジ", "stopped",
              "OpenDがSMS認証待ち — 再ログインまでrealtime push不可" + disk_txt)
        elif hb_age is not None and hb_age <= 180:
            mode = str(hb.get("bridgeMode") or "")
            L("bridge", "moomooブリッジ", "ok",
              f"heartbeat {int(hb_age)}秒前 · mode={mode or '不明'}"
              + (" · OpenD不調" if opend == "api_unhealthy" else "") + disk_txt)
        else:
            L("bridge", "moomooブリッジ", "warning" if mkt_open else "off",
              f"heartbeat {int((hb_age or 0)//60)}分前(途絶?)" if mkt_open
              else f"heartbeat {int((hb_age or 0)//60)}分前 · 市場時間外")
        if isinstance(disk, (int, float)) and disk >= 90:
            L("bridge_disk", "EC2ディスク", "stopped" if disk >= 97 else "warning",
              f"使用率 {disk}% — 拡張/掃除が必要")
        # US realtime — session-aware
        uss = str(hb.get("usRealtimeStatus") or "unknown")
        if us_ages and min(us_ages) <= 120:
            L("us_realtime", "US realtime", "ok", "LIVE — moomooから更新中")
        elif not us_open:
            L("us_realtime", "US realtime", "off", "市場時間外(待機)")
        elif uss in ("ok", "unknown"):
            L("us_realtime", "US realtime", "warning", "市場時間中なのにUS push無し")
        else:
            L("us_realtime", "US realtime", "warning", f"状態: {uss}")
        # JP realtime — entitlement-aware. disabled=gray(意図的), 権限なし=yellow.
        jps = str(hb.get("jpRealtimeStatus") or "unknown")
        if jps == "disabled":
            L("jp_realtime", "JP realtime", "off",
              "無効化中(US-onlyモード) — 日本株は代替データ(J-Quants/Yahoo)で判定")
        elif jps == "entitlement_unavailable":
            L("jp_realtime", "JP realtime", "warning",
              "unavailable — moomoo日本株クォート権限なし。日本株は代替データで判定")
        elif jp_ages and min(jp_ages) <= 120:
            L("jp_realtime", "JP realtime", "ok", "LIVE — moomooから更新中")
        elif not jp_open:
            L("jp_realtime", "JP realtime", "off", "市場時間外(待機)")
        elif jps == "degraded":
            L("jp_realtime", "JP realtime", "warning", "一時的な取得エラー(バックオフ中)")
        else:
            L("jp_realtime", "JP realtime", "warning", "市場時間中なのにJP push無し")
    else:
        # legacy bridge (no heartbeat yet) — the pre-v11.5.7 push-derived lamp
        if not ages:
            L("bridge", "moomooブリッジ", "warning" if mkt_open else "off",
              ("市場時間中なのにpush無し" if mkt_open else "市場時間外(待機)")
              + " · 旧ブリッジ(heartbeat未対応)")
        elif min(ages) <= 120:
            L("bridge", "moomooブリッジ", "ok",
              f"最終push {int(min(ages))}秒前 · 旧ブリッジ(heartbeat未対応)")
        else:
            L("bridge", "moomooブリッジ", "warning" if mkt_open else "off",
              f"最終push {int(min(ages)//60)}分前" + ("(途絶?)" if mkt_open else ""))

    L("prices_jp", "日本株価格", "ok" if conf("jquants") else "warning",
      "J-Quants 設定済" if conf("jquants") else "要設定")
    L("prices_us", "米国株価格", "ok" if conf("twelvedata") else "warning",
      "Twelve Data 設定済" if conf("twelvedata") else "要設定")
    L("crypto", "暗号資産", "ok", "CoinGecko" + ("(Demo鍵)" if _COINGECKO_KEY else "(鍵なし)") + " + Coinbaseフォールバック")
    L("macro", "金利/VIX", "ok" if conf("fred") else "warning",
      "FRED 設定済" if conf("fred") else "要設定")
    # Key configured = green (the deep verified/last-fetch nuance lives in the
    # source-registry; per-worker probe lag must not falsely amber the strip).
    if not _EDINET_API_KEY:
        L("edinet", "EDINET", "off", "未設定")
    else:
        L("edinet", "EDINET", "ok", "公式開示 設定済")
    L("notify", "通知(ntfy)", "ok" if os.environ.get("NTFY_TOPIC") else "off",
      "設定済" if os.environ.get("NTFY_TOPIC") else "未設定")

    overall = ("stopped" if any(l["status"] == "stopped" for l in lamps)
               else "warning" if any(l["status"] == "warning" for l in lamps) else "ok")
    return {"asOf": _ai_now_iso(), "overall": overall, "lamps": lamps,
            "noteJa": "課金/重要システムの健全性ランプ。緑=正常・橙=注意・赤=停止。"
                      "金額など詳細は管理者画面のみ。"}

@app.route("/api/argus/system-health")
def api_argus_system_health():
    return jsonify(_system_health())


# ── V11.5.7 bridge heartbeat + segmented status (Jul-3 OpenD incident) ────────
# "All green" must never imply JP realtime works when the moomoo account has no
# JP quote entitlement. The bridge posts a heartbeat (even while markets are
# closed); the backend derives SEGMENTED lamps: bridge process / OpenD / US
# realtime / JP realtime (+fallback). Old bridges without heartbeat keep the
# legacy push-derived lamp with an honest note.
_BRIDGE_HB = {"data": None, "receivedAt": 0.0}
_HB_ALLOWED_KEYS = ("at", "bridgeVersion", "bridgeMode", "openDStatus",
                    "lastQuotePushAt", "lastUSQuotePushAt", "lastJPQuotePushAt",
                    "acceptedCountLastPush", "usRealtimeStatus", "jpRealtimeStatus",
                    "jpFallbackActive", "jpLastErrorClass", "diskUsagePct", "intervalSec")


@app.route("/api/argus/bridge/heartbeat", methods=["POST"])
def api_argus_bridge_heartbeat():
    """Bridge-side heartbeat (admin + HMAC gated, same as quote-push). Stores a
    SANITIZED whitelist of status fields — never secrets/accounts/raw bodies."""
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    raw = request.get_data() or b""
    sig_ok, sig_reason = _verify_bridge_signature(raw)
    if not sig_ok:
        send_security_alert({"type": "bridge_signature_rejected", "reason": sig_reason,
                             "meta": _client_meta()})
        return jsonify({"error": "signature_invalid", "reason": sig_reason}), 401
    hb = (request.get_json(silent=True) or {}).get("heartbeat")
    if not isinstance(hb, dict):
        return jsonify({"error": "bad_payload", "message": "expected {heartbeat: {...}}"}), 400
    clean = {}
    for k in _HB_ALLOWED_KEYS:
        v = hb.get(k)
        if isinstance(v, bool) or v is None:
            clean[k] = v
        elif isinstance(v, (int, float)):
            clean[k] = v
        else:
            clean[k] = str(v)[:60]
    _BRIDGE_HB["data"] = clean
    _BRIDGE_HB["receivedAt"] = time.time()
    return jsonify({"ok": True, "receivedAt": _ai_now_iso()})


def _bridge_status_doc():
    """Segmented bridge status (public-safe). Heartbeat-first; falls back to the
    legacy push-derived view for old bridges."""
    now = time.time()
    now_iso = _ai_now_iso()
    hb = _BRIDGE_HB.get("data")
    hb_age = (now - _BRIDGE_HB["receivedAt"]) if hb else None
    ages = [now - rec["ts"] for mkt in ("JP", "US")
            for rec in (_PUSHED_QUOTES.get(mkt) or {}).values() if rec.get("ts")]
    us_ages = [now - rec["ts"] for rec in (_PUSHED_QUOTES.get("US") or {}).values() if rec.get("ts")]
    jp_ages = [now - rec["ts"] for rec in (_PUSHED_QUOTES.get("JP") or {}).values() if rec.get("ts")]
    doc = {"schemaVersion": "bridge-status-v1", "asOf": now_iso,
           "heartbeat": hb, "heartbeatAgeSec": int(hb_age) if hb_age is not None else None,
           "legacy": hb is None,
           "lastPushAgeSec": int(min(ages)) if ages else None,
           "lastUsPushAgeSec": int(min(us_ages)) if us_ages else None,
           "lastJpPushAgeSec": int(min(jp_ages)) if jp_ages else None}
    # segmented derivation
    if hb and hb_age is not None and hb_age <= 180:
        bridge_seg = "ok"
    elif hb:
        bridge_seg = "stale"
    elif ages and min(ages) <= 120:
        bridge_seg = "ok_legacy"
    else:
        bridge_seg = "unknown"
    doc["bridgeProcess"] = bridge_seg
    doc["openDStatus"] = (hb or {}).get("openDStatus") or "unknown"
    doc["usRealtimeStatus"] = ((hb or {}).get("usRealtimeStatus")
                               or ("ok" if us_ages and min(us_ages) <= 120 else "unknown"))
    doc["jpRealtimeStatus"] = ((hb or {}).get("jpRealtimeStatus")
                               or ("ok" if jp_ages and min(jp_ages) <= 120 else "unknown"))
    doc["jpFallbackActive"] = bool((hb or {}).get("jpFallbackActive")
                                   if hb else not (jp_ages and min(jp_ages) <= 600))
    doc["bridgeMode"] = (hb or {}).get("bridgeMode") or "unknown"
    doc["diskUsagePct"] = (hb or {}).get("diskUsagePct")
    doc["noteJa"] = ("ブリッジは正常ですが、moomooの日本株リアルタイムは利用できません"
                     "(日本株は代替データで判定)。" if doc["jpFallbackActive"]
                     and doc["bridgeProcess"] in ("ok", "ok_legacy") else
                     "セグメント別状態: ブリッジ/OpenD/USリアルタイム/JPリアルタイムは独立に評価されます。")
    return doc


@app.route("/api/argus/bridge/status")
def api_argus_bridge_status():
    """Public cache-only segmented bridge status — statuses/ages only, no secrets."""
    return jsonify(_bridge_status_doc())


@app.route("/api/argus/admin/bridge/diagnostic")
def api_argus_admin_bridge_diagnostic():
    """Admin: diagnostic summary + recommended action (Jul-3 runbook companion)."""
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    doc = _bridge_status_doc()
    hb = doc.get("heartbeat") or {}
    rec = []
    if doc["bridgeProcess"] in ("stale", "unknown"):
        rec.append("EC2で systemctl status argus-bridge / journalctl -u argus-bridge -n 120 を確認。")
    if doc["openDStatus"] == "sms_required":
        rec.append("OpenDがSMS認証待ち。EC2のOpenDで再ログイン(SMSコードをチャットに貼らないこと)。")
    elif doc["openDStatus"] == "api_unhealthy":
        rec.append("OpenD APIが不調。OpenD再起動(重複プロセスにも注意)→ argus-bridge再起動。")
    if doc["jpRealtimeStatus"] == "entitlement_unavailable":
        rec.append("USブリッジは正常。moomooの日本株クォート権限が無いため、JPはフォールバック"
                   "継続 or moomoo側でJP権限を有効化。")
    if doc["jpRealtimeStatus"] == "disabled":
        rec.append("US-onlyモード(ARGUS_DISABLE_JP_QUOTES=1)。JP権限取得後は環境変数を外して"
                   "argus-bridge再起動でfullモードに復帰。")
    if isinstance(doc.get("diskUsagePct"), (int, float)) and doc["diskUsagePct"] >= 90:
        rec.append("EC2ディスク使用率が高い。bridge/README.mdのディスク拡張チェックリストを実施。")
    if not rec:
        rec.append("正常。対応不要。")
    return jsonify({"schemaVersion": "bridge-diagnostic-v1", "asOf": doc["asOf"],
                    "status": doc, "lastJpErrorClass": hb.get("jpLastErrorClass"),
                    "recommendedActionsJa": rec})

_MOOMOO_ALLMARKET_REPORT = {"data": None}  # latest JP all-market sweep from the bridge

@app.route("/api/argus/moomoo-capability")
def api_argus_moomoo_capability():
    # Protected capability-test report (item E): per-symbol freshness truth +
    # the latest JP ALL-MARKET sweep report posted by the EC2 bridge.
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    out = _moomoo_capability_report()
    out["jpAllMarketTest"] = _MOOMOO_ALLMARKET_REPORT["data"]
    return jsonify(out)

@app.route("/api/argus/jp-universe")
def api_argus_jp_universe():
    """JP universe (moomoo codes) for the bridge's all-market capability sweep.
    Admin-gated. Prime/Standard/Growth common stocks by default (ETF/REIT/PRO
    excluded for the initial test, per the capability-test spec)."""
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    want = {s.strip() for s in request.args.get("segments", "prime,standard,growth").lower().split(",")}
    codes, seg_counts = [], {"prime": 0, "standard": 0, "growth": 0, "other": 0}
    for r in _jq_master():
        mkt = r.get("mkt") or ""
        seg = ("prime" if ("プライム" in mkt or "Prime" in mkt) else
               "standard" if ("スタンダード" in mkt or "Standard" in mkt) else
               "growth" if ("グロース" in mkt or "Growth" in mkt) else "other")
        seg_counts[seg] = seg_counts.get(seg, 0) + 1
        if seg in want:
            codes.append("JP." + r["code4"])
    # PRIORITY first (flexible scaling): the owner's watchlist (Layer 2B), the
    # fixed tactical benchmark and the regime sensors are ALWAYS swept, even if
    # they fall outside a capped sample — the bridge takes codes[:N] from the
    # front, so prioritised names are never dropped. Broad universe fills the rest.
    priority = []
    try:
        mem = _layer2b_read_latest()
        for m in (mem.get("members") if isinstance(mem, dict) else []) or []:
            if str(m.get("market")) == "JP" and m.get("symbol"):
                priority.append("JP." + str(m["symbol"]))
    except Exception:
        pass
    # Also include symbols the frontend recently requested (covers watchlist adds
    # that aren't in the synced Layer-2B set yet, e.g. a just-added 6965).
    priority += _recent_jp_watchlist_codes()
    for s in list(argus_calibration.TACTICAL_BENCHMARK) + list(argus_calibration.REGIME_SENSORS):
        if s and s[0].isdigit():          # JP listing code (e.g. 7203 / 285A)
            priority.append("JP." + s)
    priority = list(dict.fromkeys(priority))          # dedup, keep order
    pset = set(priority)
    broad = sorted(c for c in set(codes) if c not in pset)
    ordered = priority + broad
    return jsonify({"codes": ordered, "count": len(ordered), "priorityCount": len(priority),
                    "segments": sorted(want), "segmentCounts": seg_counts,
                    "noteJa": "先頭は優先銘柄(所有者watchlist+固定ベンチ+センサー)で必ずスイープ対象。"
                              "残りは全市場。ブリッジが先頭からCAP_UNIVERSE_MAX件を取るので優先銘柄は外れない。",
                    "note": "priority-first JP codes for the capability sweep"})

@app.route("/api/argus/jp-watchlist-codes")
def api_argus_jp_watchlist_codes():
    """Lightweight list of JP names the bridge should PUSH REALTIME (not just sweep
    for movers): Layer-2B synced watchlist ∪ recently-requested frontend symbols, as
    moomoo codes. Admin-gated. The bridge merges these into its 15s quote push so any
    watchlist add (e.g. 6965) goes realtime without editing the bridge's CODES env."""
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    syms = set(_JP_SEEN_SYMBOLS.keys())
    try:
        mem = _layer2b_read_latest()
        for m in (mem.get("members") if isinstance(mem, dict) else []) or []:
            if str(m.get("market")) == "JP" and m.get("symbol"):
                syms.add(str(m["symbol"]).upper())
    except Exception:
        pass
    return jsonify({"codes": sorted("JP." + s for s in syms), "count": len(syms),
                    "asOf": _ai_now_iso()})


@app.route("/api/argus/moomoo-capability-report", methods=["POST"])
def api_argus_moomoo_capability_report():
    """Receive the EC2 bridge's JP all-market capability report (admin + HMAC,
    same gate as quote-push). Stored in memory + shown via /moomoo-capability."""
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    raw = request.get_data() or b""
    sig_ok, sig_reason = _verify_bridge_signature(raw)
    if not sig_ok:
        return jsonify({"error": "signature_invalid", "reason": sig_reason}), 401
    body = request.get_json(silent=True) or {}
    rep = body.get("report")
    if not isinstance(rep, dict):
        return jsonify({"error": "bad_payload", "message": "expected {report: {...}}"}), 400
    rep["receivedAt"] = _ai_now_iso()
    _MOOMOO_ALLMARKET_REPORT["data"] = rep
    # Best-of-day proof (v10.114): realtime is hard to fake (low p95 across many
    # traded names). A later edge/lunch/cold-reconnect reading can falsely read
    # 'delayed' — so a realtime_evidence STAMP stands on its own and is not cleared
    # by a subsequent delayed report.
    if rep.get("entitlementVerdict") == "realtime_evidence":
        _MOOMOO_ALLMARKET_REPORT["realtimeProof"] = {
            "at": time.time(), "p95": rep.get("quoteAgeP95TradedS"),
            "traded": rep.get("tradedCount")}
    return jsonify({"ok": True, "stored": True})

@app.route("/api/argus/tdnet-metrics")
def api_argus_tdnet_metrics():
    # Protected: objective TDnet purchase metrics (no TDnet data used).
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    try:
        days = max(1, min(30, int(request.args.get("days", 7))))
    except Exception:
        days = 7
    return jsonify(_tdnet_metrics_summary(days))

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
            "bridgeHmacConfigured": bool(_BRIDGE_HMAC_SECRET), "bridgeHmacRequired": _BRIDGE_HMAC_REQUIRED,
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
     "phrases": ["invasion", "military strike", "missile attack", "declares war"],
     "phrasesJa": ["侵攻", "軍事攻撃", "ミサイル", "宣戦", "空爆"]},
    {"key": "fx_policy", "labelJa": "為替・金融政策の急変",
     "phrases": ["currency intervention", "yen intervention", "emergency rate cut"],
     "phrasesJa": ["為替介入", "円買い介入", "緊急利下げ", "緊急利上げ"]},
    {"key": "financial_stress", "labelJa": "金融システム不安",
     "phrases": ["bank collapse", "bank failure", "trading halted", "circuit breaker", "debt default"],
     "phrasesJa": ["銀行破綻", "取引停止", "サーキットブレーカー", "デフォルト", "債務不履行"]},
    {"key": "policy_shock", "labelJa": "緊急会見・政変",
     "phrases": ["emergency press conference", "emergency meeting", "prime minister resigns"],
     "phrasesJa": ["緊急会見", "緊急会合", "首相辞任", "内閣総辞職"]},
    {"key": "disaster", "labelJa": "災害・非常事態",
     "phrases": ["state of emergency", "major earthquake"],
     "phrasesJa": ["非常事態", "大地震", "大規模停電"]},
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

# Market-RELEVANCE gate (v10.169): the `major` regex over-flags raw geopolitics (a
# headline like "Iran fires on cargo ship" or "FIFA rainbow flag" has no investing
# relevance). A headline reaches the AI only if it is market/finance-relevant — this
# is the precision lever: a misleading or irrelevant headline never enters judgment.
_NEWS_RELEVANCE_RE = re.compile(
    r"(stock|share|equit|market|index|nasdaq|s&p|dow jones|bond|yield|treasur|"
    r"\brate(s)?\b|fed|fomc|ecb|boj|central bank|inflation|cpi|pce|gdp|jobs|payroll|"
    r"unemploy|earning|revenue|profit|guidance|ipo|merger|acquisition|buyback|dividend|"
    r"tariff|trade war|sanction|oil|crude|opec|energy|natural gas|dollar|\byen\b|euro|"
    r"currency|forex|\bfx\b|gold|commodit|semiconductor|\bchip(s)?\b|nvidia|tsmc|"
    r"\bbank(s|ing)?\b|lending|credit|\bdebt\b|default|downgrade|upgrade|recession|"
    r"housing|retail sales|consumer|manufacturing|\bpmi\b|valuation|hedge fund|\betf\b|"
    r"\bsec\b|regulat|antitrust|stimulus|\bboe\b|intervention|bankruptc|crash|"
    # JA (headlineJa may carry these even when the EN is terse)
    r"株|相場|市場|指数|金利|国債|利回り|日銀|インフレ|物価|雇用|決算|業績|増益|減益|"
    r"関税|原油|ドル|為替|半導体|景気|銀行|融資|信用|格付|利下げ|利上げ|配当|自社株|"
    r"買収|合併|上場|債務|不況|消費|製造|金融|証券|投資)", re.I)

# Source-trust tier — news agencies/wires are weighted above aggregators by the AI.
_NEWS_WIRE_SRC = ("reuters", "bloomberg", "associated press", "dow jones", "nikkei",
                  "financial times", "wall street journal", "cnbc", "marketwatch", "barron")

def _news_source_tier(src):
    s = (src or "").lower()
    return "wire" if any(k in s for k in _NEWS_WIRE_SRC) else "aggregator"

def _news_relevant(headline, headline_ja=None):
    # Relevance requires a genuine market/finance term — NOT the broad `major` geopolitics
    # vocab (iran/israel/strikes…), which alone (e.g. "FIFA … Iran World Cup") is noise.
    # Market-moving geopolitics still passes via its market term (oil/sanction/tariff/yen…).
    txt = f"{headline or ''} {headline_ja or ''}"
    return bool(_NEWS_RELEVANCE_RE.search(txt))

def _annotate_news_corroboration(news_items):
    """Tag each headline with a corroborationLevel by clustering it against the C.A.O.S.
    mesh store via argus_research_mesh.cluster_items (independent SOURCE FAMILIES = real
    corroboration; wire re-syndication is not). A lone unverified headline gets 'single'
    so it carries near-zero weight in the AI's call and can't rattle the judgment. This is
    the robust foundation: news reaches the AI corroboration-rated, not as a raw headline."""
    try:
        norm = []
        for n in news_items:
            d = {"sourceId": n.get("source"), "title": n.get("headline") or "",
                 "linkedAssets": _intel_link_assets(n.get("headline") or ""),
                 "contentType": None, "institutionId": None, "_n": n}
            norm.append(d)
        mesh = [{"sourceId": it.get("sourceId"), "title": it.get("title") or "",
                 "linkedAssets": it.get("linkedAssets") or [],
                 "contentType": it.get("contentType"), "institutionId": it.get("institutionId")}
                for it in list(_INTEL_STORE)[:200]]
        clusters = {c["storyClusterId"]: c for c in argus_research_mesh.cluster_items(norm + mesh)}
        for d in norm:
            c = clusters.get(d.get("storyClusterId")) or {}
            d["_n"]["corroboration"] = c.get("corroborationLevel") or "single"
    except Exception as e:
        add_log(f"[news] corroboration tag failed: {type(e).__name__}")
        for n in news_items:
            n.setdefault("corroboration", "single")
    return news_items

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


# ── V11.5 news headline translation cache (owner: always show JP, never raw English) ──
# Public GETs can't call an LLM, so translation happens on the admin/cron path and is
# cached by content hash. Any English headline shown anywhere is queued into _SEEN;
# the admin translate run drains it via the Gemini helper and fills _NEWS_JA_CACHE.
_NEWS_JA_CACHE = {}                       # hash -> {"ja": str, "at": iso}
_NEWS_JA_SEEN = deque(maxlen=300)         # recent English headlines pending translation
_NEWS_JA_FILE = "/tmp/argus_news_ja.json"
_NEWS_JA_STATE = {"restored": False, "lastTranslateAt": None,
                  "translatedToday": 0, "translatedDay": None}
# V11.5.2: explicit visible-translation request queue (hash -> minimal entry). The public
# translation-request POST enqueues on-screen English titles here; translate-visible drains
# it FIRST. Only titleOriginal/source/publishedAt/hash/context/symbol stored — no bodies.
# Persisted alongside the cache in /tmp (ephemeral on Render → status reports durable:false).
_NEWS_JA_VQUEUE = {}                       # hash -> {titleOriginal, source, publishedAt, ...}
_NEWS_JA_VQUEUE_RL = {}                    # "ip|context" -> last epoch (per-IP+context throttle)
_NEWS_JA_VQUEUE_RL_SEC = 5
_NEWS_JA_VQUEUE_STATE = {"lastDrainAt": None, "lastDrainCount": 0}
_NEWS_JA_QUEUE_DURABLE = False             # /tmp only → non-durable (survives within a dyno)


def _news_ja_persist():
    try:
        with open(_NEWS_JA_FILE, "w") as f:
            json.dump({"cache": _NEWS_JA_CACHE,
                       "vqueue": _NEWS_JA_VQUEUE,
                       "vqueueState": _NEWS_JA_VQUEUE_STATE,
                       "state": {k: _NEWS_JA_STATE.get(k) for k in
                                 ("lastTranslateAt", "translatedToday", "translatedDay")}},
                      f, ensure_ascii=False, default=str)
    except Exception:
        pass


def _news_ja_restore_once():
    """3-stage restore (v11.9.1 — owner report 「ニュースが全部翻訳待ち」):
    /tmp runtime file → ledger-branch news-ja/latest.json → empty. The /tmp
    file dies on every Render deploy, and 4 same-day deploys used to wipe ALL
    past translations back to 翻訳待ち. The ledger stage (committed by the
    24/7 caos-scan workflow) makes translations deploy-proof. /tmp entries win
    over ledger (they are never older). Short timeout; never blocks startup."""
    if _NEWS_JA_STATE["restored"]:
        return
    _NEWS_JA_STATE["restored"] = True
    restored_from = []
    try:
        with open(_NEWS_JA_FILE) as f:
            blob = json.load(f)
        if isinstance(blob.get("cache"), dict):
            _NEWS_JA_CACHE.update(blob["cache"])
            restored_from.append("tmp")
        if isinstance(blob.get("vqueue"), dict):
            _NEWS_JA_VQUEUE.update(blob["vqueue"])
        for k in ("lastDrainAt", "lastDrainCount"):
            if (blob.get("vqueueState") or {}).get(k) is not None:
                _NEWS_JA_VQUEUE_STATE[k] = blob["vqueueState"][k]
        for k in ("lastTranslateAt", "translatedToday", "translatedDay"):
            if (blob.get("state") or {}).get(k) is not None:
                _NEWS_JA_STATE[k] = blob["state"][k]
    except Exception:
        pass
    try:
        r = requests.get(f"{_LEDGER_RAW_BASE}/news-ja/latest.json?cb={int(time.time())}",
                         timeout=6)
        if r.status_code == 200 and r.text.strip().startswith("{"):
            snap = json.loads(r.text)
            cache = snap.get("cache")
            if isinstance(cache, dict):
                for h, ent in cache.items():
                    if h not in _NEWS_JA_CACHE and isinstance(ent, dict) and ent.get("ja"):
                        _NEWS_JA_CACHE[h] = ent
                restored_from.append("ledger")
            st = snap.get("state") or {}
            if not _NEWS_JA_STATE.get("lastTranslateAt") and st.get("lastTranslateAt"):
                _NEWS_JA_STATE["lastTranslateAt"] = st["lastTranslateAt"]
    except Exception:
        pass
    _NEWS_JA_STATE["restoredFrom"] = restored_from or ["empty"]


def _headline_ja(text):
    """Japanese headline for display (cached-only, safe on public GET). Japanese text
    passes through; English returns its cached translation, else the original English
    (queued for the next admin translate run)."""
    _news_ja_restore_once()
    s = (text or "").strip()
    if argus_news_i18n.looks_translatable(s) and not argus_news_i18n.is_translated(s, _NEWS_JA_CACHE):
        _NEWS_JA_SEEN.append(s)
    return argus_news_i18n.pick_ja(s, _NEWS_JA_CACHE)


def _news_decorate(text, source=""):
    """V11.5.1: display fields for a news title (queues English for the cron, then
    returns titleOriginal/titleJa/displayTitleJa/translationStatus). displayTitleJa is
    ALWAYS Japanese or a Japanese fallback — never raw English as the primary text."""
    _news_ja_restore_once()
    s = (text or "").strip()
    if argus_news_i18n.looks_translatable(s) and not argus_news_i18n.is_translated(s, _NEWS_JA_CACHE):
        _NEWS_JA_SEEN.append(s)
    return argus_news_i18n.decorate(s, _NEWS_JA_CACHE, source)


def _news_visible_pool():
    """Ordered (priority-first) English titles currently visible in the UI, so the
    admin translate run drains what the owner actually sees first. Cached-only."""
    pool = []
    # 1) mover-cause bestLead / top candidates (top card + downside/mover cards)
    try:
        for r in list(_MOVER_CAUSES.values()):
            for cnd in (r.get("causeCandidates") or [])[:3]:
                if cnd.get("titleJa"):
                    pool.append(str(cnd["titleJa"]))
    except Exception:
        pass
    # 2) the recently-queued headlines seen by _news_decorate on public reads
    pool += list(_NEWS_JA_SEEN)
    # 3) market news + Finnhub company news caches
    try:
        for it in ((_MARKET_NEWS_CACHE.get("data") or {}).get("items") or []):
            if it.get("headline"):
                pool.append(it["headline"])
    except Exception:
        pass
    try:
        for ent in list(_FINN_CACHE.values()):
            for n in ((ent.get("data") or {}).get("news") or []):
                if n.get("headline"):
                    pool.append(n["headline"])
    except Exception:
        pass
    return pool


def _translate_pending_headlines(cap=60, queue_first=False):
    """Admin/cron: translate queued/visible English headlines to JP, VISIBLE-FIRST.
    Uses the existing Gemini helper (LLM allowed on admin path). No article bodies.
    queue_first=True drains the explicit visible-translation request queue before the
    inferred visible pool, then prunes any queue entries that got translated."""
    _news_ja_restore_once()
    now_iso = _ai_now_iso()
    ordered = []
    queued_n = 0
    if queue_first:
        q_titles = argus_news_i18n.visible_queue_drain(_NEWS_JA_VQUEUE, _NEWS_JA_CACHE, max_items=cap)
        ordered.extend(q_titles)
        queued_n = len(q_titles)
    ordered.extend(_news_visible_pool())          # inferred on-screen titles (priority-first)
    pending = argus_news_i18n.collect_visible_pending(ordered, _NEWS_JA_CACHE, cap=cap)
    if not pending:
        drained = argus_news_i18n.visible_queue_prune(_NEWS_JA_VQUEUE, _NEWS_JA_CACHE) if queue_first else 0
        if queue_first:
            _NEWS_JA_VQUEUE_STATE["lastDrainAt"] = now_iso
            _NEWS_JA_VQUEUE_STATE["lastDrainCount"] = drained
            _news_ja_persist()
        return {"translated": 0, "pending": 0, "fromQueue": queued_n,
                "cacheSize": len(_NEWS_JA_CACHE), "queueRemaining": len(_NEWS_JA_VQUEUE),
                "asOf": now_iso}
    tr = _translate_headlines_ja(pending)     # {index -> ja}; {} on failure
    merged = argus_news_i18n.merge_translations(_NEWS_JA_CACHE, pending, tr, now_iso)
    _NEWS_JA_CACHE.clear()
    _NEWS_JA_CACHE.update(merged)
    # drop queue entries now covered by the cache
    pruned = argus_news_i18n.visible_queue_prune(_NEWS_JA_VQUEUE, _NEWS_JA_CACHE)
    _NEWS_JA_STATE["lastTranslateAt"] = now_iso
    _NEWS_JA_STATE["translatedToday"] = int(_NEWS_JA_STATE.get("translatedToday") or 0) + len(tr)
    _NEWS_JA_STATE["translatedDay"] = now_iso[:10]
    if queue_first:
        _NEWS_JA_VQUEUE_STATE["lastDrainAt"] = now_iso
        _NEWS_JA_VQUEUE_STATE["lastDrainCount"] = pruned
    _news_ja_persist()
    return {"translated": len(tr), "pending": len(pending), "fromQueue": queued_n,
            "cacheSize": len(_NEWS_JA_CACHE), "queuePruned": pruned,
            "queueRemaining": len(_NEWS_JA_VQUEUE), "asOf": now_iso}


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
            src = str(n.get("source") or "")[:40]
            items.append({
                "headline": h,
                "source": src,
                "url": str(n.get("url") or "")[:300],
                "datetime": n.get("datetime"),   # unix seconds
                "major": bool(_NEWS_MAJOR_RE.search(h)),
                "tier": _news_source_tier(src),   # wire | aggregator (source-trust)
            })
            if len(items) >= 14:
                break
        # Japanese headlines (news-v2.1): one flash call per 10-min refill.
        tr = _translate_headlines_ja([i["headline"] for i in items])
        for idx, item in enumerate(items):
            if idx in tr:
                item["headlineJa"] = tr[idx]
        # Market-relevance gate (v10.169): flag headlines that are actually about
        # markets/finance (incl. the JA translation) so the UI + AI can drop noise.
        for item in items:
            item["relevant"] = _news_relevant(item["headline"], item.get("headlineJa"))
        # Corroboration rating (v10.170): cluster against the C.A.O.S. mesh so each
        # headline carries official/corroborated/single — single can't drive the AI.
        _annotate_news_corroboration(items)
        # v10.191: fold in JP-language headlines from the intel mesh (Reuters JP /
        # 日銀 / 経産省 / Bloomberg JP / 日経 / per-symbol Google News) so the JP owner
        # actually SEES Japan news on the card, not just US wire. Newest first, capped.
        try:
            _JP_NEWS_SRC = {"reuters_jp", "boj_official", "meti_official", "nikkei_web", "bloomberg_jp", "google_news_jp"}
            _seen_h = {i["headline"] for i in items}
            jp_items = []
            for it in reversed(list(_INTEL_STORE)):
                sid = it.get("sourceId")
                if it.get("lang") != "ja" and sid not in _JP_NEWS_SRC:
                    continue
                h = str(it.get("title") or it.get("headline") or "")[:200]
                if not h or h in _seen_h:
                    continue
                _seen_h.add(h)
                # v11.5.6: carry a real epoch so the newest-first sort below works —
                # datetime:None made every JP item unsortable (and stuck at the top
                # regardless of age, violating 最新が上 on the hub).
                _ep = argus_news_freshness._epoch(
                    it.get("publishedAt") or it.get("firstDetectedAt"))
                jp_items.append({
                    "headline": h, "headlineJa": h,
                    "source": str(sid or "JP")[:40],
                    "url": str(it.get("canonicalUrl") or it.get("url") or "")[:300],
                    "datetime": int(_ep) if _ep else None,
                    "major": bool(_NEWS_MAJOR_RE.search(h)),
                    "tier": "wire" if sid in ("reuters_jp", "boj_official", "meti_official") else "aggregator",
                    "relevant": _news_relevant(h, h),
                    "corroboration": it.get("corroboration") or "single",
                })
                if len(jp_items) >= 6:
                    break
            if jp_items:
                items = (jp_items + items)[:16]
        except Exception:
            pass
        # v11.5.6 owner rule: EVERY news list renders newest-first — sort by epoch,
        # undated items sink to the bottom (never fake-fresh at the top).
        items.sort(key=lambda i: (i.get("datetime") is None, -(i.get("datetime") or 0)))
        # v11.5.1: Japanese-first display field (headlineJa is filled above; English
        # without a translation gets a JP fallback, never raw English as primary).
        for _it in items:
            _it.update(argus_news_i18n.decorate_from_ja(
                _it.get("headline"), _it.get("headlineJa"), _it.get("source") or ""))
        out = {"status": "live", "asOf": _ai_now_iso(), "items": items,
               "noteJa": "Finnhub市場ニュース(見出しは自動翻訳・参考情報)。⚡=重要キーワード。AIには「未検証の見出し(本文と異なりうる)」として、相場関連のみ・裏取り(公式>複数系統>単一)で重み付けして参考投入。単一ソースは判断を動かさない。"}
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
        themes_out = []

    # v10.192: if GDELT is unreachable (or found nothing), fall back to the C.A.O.S.
    # intel store — the public RSS mesh (Reuters JP / 日銀 / 経産省 / Bloomberg / CNBC)
    # now feeds crisis-theme detection too, so the radar (now surfaced inside the
    # C.A.O.S. hub) still works when GDELT is down. Phrase-match EN + JA titles.
    if status != "live" or not any(t.get("count") for t in themes_out):
        try:
            titles = [str(it.get("title") or it.get("headline") or "").lower()
                      for it in _INTEL_STORE]
            titles = [x for x in titles if x]
            fb = []
            for t in _NEWS_THEMES:
                pats = [p.lower() for p in (t["phrases"] + t.get("phrasesJa", []))]
                cnt = sum(1 for x in titles if any(p in x for p in pats))
                fb.append({"key": t["key"], "labelJa": t["labelJa"],
                           "count": cnt, "level": _news_theme_level(cnt), "headlines": []})
            if titles:
                themes_out, status = fb, "live"   # intel-based read (headlines omitted)
        except Exception:
            pass
    if not themes_out:
        themes_out = [{"key": t["key"], "labelJa": t["labelJa"],
                       "count": 0, "level": "calm", "headlines": []} for t in _NEWS_THEMES]

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
    # Cache EITHER way (v10.63): caching only on success meant every GOLD/BOND/REIT
    # poll re-hit Twelve Data while the quota was exhausted, re-burning credits and
    # never recovering. On empty, back off 45 min (stay in budget); on success, 6h.
    _ALERT_ETF_CACHE["data"] = out
    _ALERT_ETF_CACHE["expires"] = now + (_ALERT_ETF_TTL if out else 45 * 60)
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
        # Neutral band. v10.190: under a cautious posture (EVENT_WAIT/RISK_OFF) we
        # no longer collapse this to a flat WAIT — that made the whole page read as
        # "do nothing". Existing positions can be HELD; only NEW entries wait for the
        # event to pass. HOLD(保有継続) ≠ WAIT(新規待ち) — the distinction is the point.
        if cautious:
            return ("HOLD", "low", "med",
                    f"方向感は限定的(スコア{s:+.2f})。重要イベント接近のため新規は様子見だが、既存の保有は継続でよい。",
                    "イベント通過と明確なトレンドの発生を待って新規を検討する。")
        return ("HOLD", "low", "low",
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
    # Rotation signal per ETF symbol — keeps an asset-class call DIFFERENTIATED (inflow/
    # outflow/neutral) even when the raw ETF momentum is stale, instead of a flat WAIT.
    rot_by_asset = {}
    for g in (reg.get("rotationGroups", []) if isinstance(reg, dict) else []):
        for a in (g.get("assets") or []):
            rot_by_asset[str(a).upper()] = g
    cards = []

    def add(asset_class, name, action, conf, risk, reason, points, nxt, status):
        cards.append({"assetClass": asset_class, "displayName": name, "action": action,
                      "confidence": conf, "risk": risk, "reasonJa": reason,
                      "dataPoints": points, "nextConditionJa": nxt, "status": status})

    # ── JP / US stock aggregates (from the live label engine) ──
    for mkt, name in (("JP", "Japan Individual Stocks"), ("US", "US Individual Stocks")):
        ls = [l for l in al.get("labels", []) if l["market"] == mkt
              and l.get("status") in ("live", "delayed", "partial")]
        if ls:
            from collections import Counter
            sstatus = "live" if all(l.get("status") == "live" for l in ls) else "partial"
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
                pts, "個別はWatchlistの戦略カードで確認。", sstatus)
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
            g = rot_by_asset.get(sym.upper())
            st = g.get("status") if g else None
            if st == "inflow":
                add(cls, name, "HOLD", "low", "med",
                    g.get("rationaleJa") or f"{name}: 資金流入の傾向。{posture}局面では選好(新規は押し目で)。",
                    ["資金フロー: 流入"], "流れの転換を確認。", "partial")
            elif st == "outflow":
                add(cls, name, "WAIT", "low", "med",
                    g.get("rationaleJa") or f"{name}: 資金流出の傾向。新規は見送り・様子見。",
                    ["資金フロー: 流出"], "下げ止まり/流入転換を確認。", "partial")
            elif st == "neutral":
                add(cls, name, "HOLD", "low", "med",
                    g.get("rationaleJa") or f"{name}: 資金フローは中立。計画通り。",
                    ["資金フロー: 中立"], "明確な方向感を確認。", "partial")
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


# ━━━ Downside Incident Response + cause attribution (v10.98) ━━━
# When a held/watched name drops materially (or the JP tape deteriorates), turn
# the old generic "急落" into an explained incident: classification, likely-cause
# buckets, holder-specific action OVERRIDE, missing-data, next-review. Pure logic
# lives in argus_downside; this layer just builds the context from live snapshots.
# Decision-support only — no orders, ever.
_DOWNSIDE_THEMES = {
    # AI / semis / electric-cable complex that moves together on theme unwinds.
    "ai_semis_cable": {"5801", "5803", "285A", "6920", "6857", "NVDA", "SMH", "AVGO", "TSM"},
}
_DOWNSIDE_HIGH_BETA = {"5803", "285A", "5801", "6920", "6857"}
_OWNER_SYMS_CACHE = {"syms": None, "ts": 0.0}
_OWNER_SYMS_TTL = 600
_DOWNSIDE_CACHE = {"data": None, "expires": 0.0}
_DOWNSIDE_TTL = 60    # restored 180→60 (v10.126): Render upgraded to Standard 2GB
# (2026-06-24), so the memory/CPU headroom is there to recompute the downside layer
# every 60s again — faster drop detection is the whole point of this safety layer.
# (v10.110 had stretched it to 180 only to survive the 512MB ceiling.)


def _owner_symbols_cached():
    """Owner (Layer 2B) watchlist as a MAP {SYMBOL(upper): {ownerState,
    downsideStrictness, priority}}, cached ~10m. Carries only the non-monetary
    flags — never quantity/cost/P/L. Owner-gated read; degrades to {} if absent.
    NOTE: returns a dict, so `sym in owner` still works (checks keys)."""
    now = time.time()
    if _OWNER_SYMS_CACHE["syms"] is not None and now - _OWNER_SYMS_CACHE["ts"] < _OWNER_SYMS_TTL:
        return _OWNER_SYMS_CACHE["syms"]
    flags = {}
    try:
        for mrow in (_layer2b_read_latest() or []):
            s = str(mrow.get("symbol") or "").upper()
            if s:
                flags[s] = {
                    "ownerState": mrow.get("ownerState") or "watch",
                    "downsideStrictness": mrow.get("downsideStrictness") or "normal",
                    "priority": mrow.get("priority") or "normal",
                }
    except Exception:
        flags = _OWNER_SYMS_CACHE["syms"] or {}
    _OWNER_SYMS_CACHE["syms"] = flags
    _OWNER_SYMS_CACHE["ts"] = now
    return flags


def _theme_peers_down(sym, by_sym):
    """True if >=2 same-theme peers are also down materially (theme unwind)."""
    u = sym.upper()
    for members in _DOWNSIDE_THEMES.values():
        if u in members:
            downs = 0
            for m in members:
                if m == u:
                    continue
                row = by_sym.get(m)
                if row and isinstance(row.get("changePct"), (int, float)) and row["changePct"] < -1.5:
                    downs += 1
            if downs >= 2:
                return True
    return False


_JP_INDEX_CACHE = {"val": None, "ts": 0.0}
_JP_INDEX_TTL = 300

_TDNET_FEED_CACHE = {"data": None, "expires": 0.0}
_TDNET_FEED_TTL = 600


# ── Official J-Quants TDnet Document Add-on (v11.1) ──────────────────────────
# Reuses the SAME J-Quants v2 auth (x-api-key). The exact add-on path can differ per
# plan/release, so it is env-overridable and the fetch reports HTTP status HONESTLY
# (entitlement_missing / endpoint_not_found / rate_limited) instead of guessing. A key
# being present is NOT 'live' — only a 200 with rows is.
# OFFICIAL spec (jpx-jquants.com/ja/spec/td-list, add-on launched 2026-05-18):
#   GET https://api.jquants.com/v2/td/list — SAME x-api-key, no key regeneration needed.
#   `date` or `code` is MANDATORY (date accepts YYYY-MM-DD); optional from/to/cursor.
#   Error semantics (spec/response-status): 403 covers plan-missing AND wrong key AND
#   wrong path — so only the BODY message distinguishes them; a no-param call returns
#   400 ("This API requires at least 1 parameter as follows; date, code") IFF the route
#   resolves and the account is entitled. Add-on has its own 100 req/min pool.
_JQUANTS_TDNET_PATH = os.environ.get("JQUANTS_TDNET_PATH", "/td/list")
_TDNET_OFFICIAL_CACHE = {"data": None, "expires": 0.0}

def _jquants_tdnet_fetch(limit=150):
    """Official J-Quants TDnet Add-on snapshot + a bool 'usable'. Never exposes the key."""
    if not _JQUANTS_API_KEY:
        return argus_jquants_tdnet.build_snapshot(
            [], status="not_configured", official=True, provider="jquants-tdnet",
            entitlement="missing", as_of=_ai_now_iso(), note_ja="JQUANTS_API_KEY未設定。"), False
    now = time.time()
    c = _TDNET_OFFICIAL_CACHE
    if c["data"] is not None and now < c["expires"]:
        d = c["data"]
        return d, (d.get("status") == "official_tdnet_live" and bool(d.get("items")))
    # Probe the OFFICIAL path with a mandatory `date` param, walking back a few days so a
    # weekend/holiday (0 disclosures) isn't misread as a failure. Interpretation per the
    # official spec: 200+rows=live · 200+empty=entitled-but-empty-window · 400=route AND
    # entitlement OK (param rejected) · 403 body decides plan-refusal vs gateway noise
    # ("Missing Authentication Token" = unknown path, NOT entitlement) · 429=rate-limited.
    # Per-date results kept as (date, http, short message hint) — never key material.
    r = None
    probes = []          # [{date, http, hint}]
    ent_hit = None       # a REAL plan/subscription refusal
    entitled_400 = False  # a 400 proves route + entitlement are fine
    gateway_403 = False
    for _back in range(4):
        _d = (datetime.now(TZ_JST) - timedelta(days=_back)).strftime("%Y-%m-%d")
        try:
            rr = requests.get(f"{_JQUANTS_BASE}{_JQUANTS_TDNET_PATH}",
                              headers={"x-api-key": _JQUANTS_API_KEY},
                              params={"date": _d}, timeout=10)
        except Exception as e:
            probes.append({"date": _d, "http": None, "hint": type(e).__name__})
            continue
        if rr.status_code == 200:
            body = rr.json() if isinstance(rr.json(), dict) else {}
            rows = body.get("td_list") or body.get("data") or body.get("tdnet") or body.get("items") or []
            probes.append({"date": _d, "http": 200, "hint": f"{len(rows)} rows"})
            if rows:
                r = rr
                break
            continue                                   # entitled, empty day → try prior day
        try:
            b = rr.json() if isinstance(rr.json(), dict) else {}
            hint = str(b.get("message") or b.get("Message") or "")[:80]
        except Exception:
            hint = (rr.text or "")[:80]
        probes.append({"date": _d, "http": rr.status_code, "hint": hint[:60]})
        if rr.status_code == 400:
            entitled_400 = True                        # spec: 400 ⇒ route+entitlement OK
            break
        if rr.status_code in (401, 403):
            if "missing authentication token" in hint.lower() or hint.strip().lower() in ("forbidden", "not found"):
                gateway_403 = True                     # unknown path, NOT an entitlement signal
            else:
                ent_hit = (_d, rr.status_code, hint)
            break
        if rr.status_code == 429:
            break
    http = None
    try:
        if r is None:
            had_200 = any(p.get("http") == 200 for p in probes)
            last = probes[-1] if probes else {}
            if had_200 or entitled_400:
                # Entitlement PROVEN (route resolved) — just no rows / a param quirk.
                st, ent, code = "live", "tdnet_addon", 200 if had_200 else 400
                note = ("公式TDnet Add-onは疎通OK（権限あり）。直近数日の開示0件"
                        + ("" if had_200 else "・パラメータが拒否されたため要確認(400)") + "。")
            elif ent_hit:
                st, code, ent = "entitlement_missing", ent_hit[1], "missing"
                note = (f"公式TDnet {_JQUANTS_TDNET_PATH} → HTTP {code}（{ent_hit[2][:60]}）。"
                        "TDnet Add-onはStandardとは別の追加購入(月額)です。J-Quantsダッシュボード → "
                        "Subscription → アドオンプラン → 「TDnet/Company Disclosure」カードに"
                        "[ご利用中]バッジがあるか確認してください（キー再発行は不要）。")
            elif gateway_403:
                st, code, ent = "endpoint_not_found", (last.get("http")), "unknown"
                note = ("公式TDnetのパスがゲートウェイで解決されません（unknown path応答）。"
                        "env JQUANTS_TDNET_PATH を確認してください。")
            elif last.get("http") == 429:
                st, code, ent = "rate_limited", 429, "unknown"
                note = "公式TDnetがレート制限中（アドオンは100req/分の専用枠）。"
            else:
                st, code, ent = "unavailable", last.get("http"), "unknown"
                note = "公式TDnet取得エラー（ネットワーク/一時障害の可能性）。"
            snap = argus_jquants_tdnet.build_snapshot(
                [], status=st, official=True, provider="jquants-tdnet", entitlement=ent,
                as_of=_ai_now_iso(), note_ja=note)
            snap["httpStatus"] = code
            snap["probes"] = probes          # date+code+hint only — never key material
            c["data"] = snap
            c["expires"] = now + (900 if st != "live" else _TDNET_FEED_TTL)
            return snap, False
        http = r.status_code
        if r.status_code == 200:
            body = r.json() if isinstance(r.json(), dict) else {}
            rows = body.get("data") or body.get("td_list") or body.get("tdnet") or body.get("items") or []
            items, by_sym = [], {}
            for raw in (rows or [])[:200]:
                n = argus_jquants_tdnet.normalize_row(raw, argus_tdnet.classify_disclosure)
                if not n.get("symbol") or not n.get("title"):
                    continue
                it = {"code": n["symbol"], "name": n["company"], "title": n["title"],
                      "time": n["disclosedAt"], "url": None, "documentId": n["documentId"],
                      "category": n["category"], "categoryJa": n["categoryJa"],
                      "sentiment": n["sentiment"], "material": n["material"],
                      "provider": "jquants-tdnet", "official": True}
                items.append(it)
                by_sym.setdefault(n["symbol"], []).append(it)
            snap = argus_jquants_tdnet.build_snapshot(
                items, status=("official_tdnet_live" if items else "live"), official=True,
                provider="jquants-tdnet", entitlement="tdnet_addon", as_of=_ai_now_iso(),
                note_ja="公式 J-Quants TDnet Add-on から取得。")
            snap["bySymbol"] = by_sym
            snap["httpStatus"] = 200
            c["data"] = snap
            c["expires"] = now + _TDNET_FEED_TTL
            return snap, bool(items)
        st = argus_jquants_tdnet.status_from_http(r.status_code)
        ent = "missing" if r.status_code in (401, 403) else "unknown"
        snap = argus_jquants_tdnet.build_snapshot(
            [], status=st, official=True, provider="jquants-tdnet", entitlement=ent,
            as_of=_ai_now_iso(), note_ja=f"official TDnet HTTP {r.status_code}（キー値は出しません）。")
        snap["httpStatus"] = r.status_code
        # cache a non-200 briefly so a plan-gap/wrong-path isn't hammered
        c["data"] = snap
        c["expires"] = now + 900
        return snap, False
    except Exception:
        snap = argus_jquants_tdnet.build_snapshot(
            [], status="unavailable", official=True, provider="jquants-tdnet",
            entitlement="unknown", as_of=_ai_now_iso(), note_ja="official TDnet 取得エラー。")
        snap["httpStatus"] = http
        return snap, False


def _get_tdnet_yanoshin(limit=150):
    """FALLBACK: recent TDnet via the free yanoshin third-party wrapper. official=False,
    a LOWER-tier source than the official J-Quants Add-on. Cached 10m."""
    now = time.time()
    if _TDNET_FEED_CACHE["data"] is not None and now < _TDNET_FEED_CACHE["expires"]:
        return _TDNET_FEED_CACHE["data"]
    out = {"status": "unavailable", "asOf": _ai_now_iso(), "items": [], "bySymbol": {},
           "provider": "yanoshin-tdnet", "official": False, "entitlement": "fallback"}
    try:
        r = requests.get(f"https://webapi.yanoshin.jp/webapi/tdnet/list/recent.json?limit={limit}",
                         timeout=12, headers={"User-Agent": "argus/1.0"})
        if r.ok:
            data = r.json()
            items, by_sym = [], {}
            for row in (data.get("items") or []):
                td = row.get("Tdnet") or row.get("tdnet") or {}
                code5 = str(td.get("company_code") or "")
                code = code5[:4] if len(code5) >= 4 else code5
                title = td.get("title") or ""
                if not code or not title:
                    continue
                cls = argus_tdnet.classify_disclosure(title)
                it = {"code": code, "name": td.get("company_name"), "title": title,
                      "time": td.get("pubdate"), "url": td.get("document_url"),
                      "category": cls["category"], "categoryJa": cls["categoryJa"],
                      "sentiment": cls["sentiment"], "provider": "yanoshin-tdnet", "official": False}
                items.append(it)
                by_sym.setdefault(code, []).append(it)
            if items:
                out = {"status": "live", "asOf": _ai_now_iso(), "items": items[:200],
                       "bySymbol": by_sym, "provider": "yanoshin-tdnet", "official": False,
                       "entitlement": "fallback"}
    except Exception:
        pass
    if out["status"] == "live":
        _TDNET_FEED_CACHE["data"] = out
        _TDNET_FEED_CACHE["expires"] = now + _TDNET_FEED_TTL
    return out


def get_tdnet_recent(limit=150):
    """TDnet 適時開示. Prefers the OFFICIAL J-Quants TDnet Add-on (provider=jquants-tdnet,
    official=true); falls back to the yanoshin third-party wrapper (official=false) ONLY
    when the official feed is unavailable. The two are always distinguishable via
    provider/official, and the official status (why it didn't win) is surfaced."""
    official, usable = _jquants_tdnet_fetch(limit)
    if usable and official.get("items"):
        _official_lifecycle_ingest(official)          # v11.3: lifecycle-track official items
        return official
    fb = _get_tdnet_yanoshin(limit)
    fb["officialStatus"] = official.get("status")     # e.g. entitlement_missing / endpoint_not_found
    fb["officialHttpStatus"] = official.get("httpStatus")
    return fb


# ── Official Event Lifecycle store (v11.3) ───────────────────────────────────
# Official disclosures become lifecycle-tracked research events (discovered→…→scored).
# In-memory + /tmp persisted (public-safe metadata only, no PDFs/full text). Ingest is
# pure in-memory processing of an ALREADY-FETCHED snapshot — no extra provider calls.
_OFFICIAL_EVENTS = {}                 # officialEventId -> lifecycle record
_OFFICIAL_EVENTS_MAX = 600
_OFFICIAL_EVENTS_FILE = "/tmp/argus_official_events.json"
_OFFICIAL_EVENTS_STATE = {"lastIngestAt": None, "lastTrackAt": None, "restored": False,
                          "pathType": "ephemeral_tmp", "restoreStatus": "not_attempted"}
_OFFICIAL_LEDGER_CACHE = {"data": None, "expires": 0.0}   # ledger latest.json meta (10-min)


def _official_events_persist():
    try:
        with open(_OFFICIAL_EVENTS_FILE, "w") as f:
            json.dump({"items": _OFFICIAL_EVENTS, "state": {k: _OFFICIAL_EVENTS_STATE[k]
                                                            for k in ("lastIngestAt", "lastTrackAt")}},
                      f, ensure_ascii=False, default=str)
    except Exception:
        pass


def _official_events_restore_once():
    """Restore order (v11.3.1): /tmp runtime cache → ledger-branch latest.json (ARGUS's
    own public artifact; short timeout, never blocks on failure) → empty. MERGES via the
    pure store module so an older snapshot can never wipe newer runtime progress.
    Never fetches a provider, never calls an LLM."""
    if _OFFICIAL_EVENTS_STATE["restored"]:
        return
    _OFFICIAL_EVENTS_STATE["restored"] = True
    restored_from = []
    try:
        with open(_OFFICIAL_EVENTS_FILE, "r") as f:
            blob = json.load(f)
        if isinstance(blob.get("items"), dict):
            _OFFICIAL_EVENTS.update(blob["items"])
            restored_from.append("tmp")
        _OFFICIAL_EVENTS_STATE.update({k: v for k, v in (blob.get("state") or {}).items()
                                       if k in ("lastIngestAt", "lastTrackAt")})
    except Exception:
        pass
    try:
        r = requests.get(f"{_LEDGER_RAW_BASE}/official-events/latest.json?cb={int(time.time())}",
                         timeout=6)
        if r.status_code == 200 and r.text.strip().startswith("{"):
            snap = json.loads(r.text)
            merged = argus_official_event_store.merge_records(
                _OFFICIAL_EVENTS, list(argus_official_event_store.restore_from_snapshot(snap).values()),
                now_iso=_ai_now_iso())
            _OFFICIAL_EVENTS.clear()
            _OFFICIAL_EVENTS.update(merged)
            restored_from.append("ledger")
    except Exception:
        pass
    if "ledger" in restored_from:
        _OFFICIAL_EVENTS_STATE["pathType"] = "ledger_restored"
        _OFFICIAL_EVENTS_STATE["restoreStatus"] = "ok"
    elif "tmp" in restored_from:
        _OFFICIAL_EVENTS_STATE["pathType"] = "durable_restored"
        _OFFICIAL_EVENTS_STATE["restoreStatus"] = "tmp_only"
    else:
        _OFFICIAL_EVENTS_STATE["pathType"] = "ephemeral_tmp"
        _OFFICIAL_EVENTS_STATE["restoreStatus"] = "restore_failed_or_empty"


def _official_lifecycle_ingest(td_snapshot):
    """Upsert OFFICIAL disclosures into the lifecycle store (dedup by id; append-only —
    existing records keep their reaction/lifecycle progress)."""
    try:
        _official_events_restore_once()
        now_iso = _ai_now_iso()
        added = 0
        for it in (td_snapshot.get("items") or []):
            if not it.get("official"):
                continue
            rec = argus_official_event_lifecycle.from_disclosure(
                it, source="tdnet", provider="jquants-tdnet", market="JP",
                first_seen_at=now_iso,
                evidence_pack_id=argus_evidence_pack.pack_id(
                    it.get("code") or "", now_iso))
            oid = rec["officialEventId"]
            if oid not in _OFFICIAL_EVENTS:
                _OFFICIAL_EVENTS[oid] = rec
                added += 1
        if len(_OFFICIAL_EVENTS) > _OFFICIAL_EVENTS_MAX:
            # keep the newest by firstSeenAt
            keep = sorted(_OFFICIAL_EVENTS.values(),
                          key=lambda r: str(r.get("firstSeenAt") or ""), reverse=True)[:_OFFICIAL_EVENTS_MAX]
            _OFFICIAL_EVENTS.clear()
            _OFFICIAL_EVENTS.update({r["officialEventId"]: r for r in keep})
        if added:
            _OFFICIAL_EVENTS_STATE["lastIngestAt"] = now_iso
            _official_events_persist()
    except Exception:
        pass                                        # ingest is best-effort, never breaks the feed


def _official_events_by_symbol(sym, material_only=False):
    _official_events_restore_once()
    sym = str(sym or "").upper()
    out = [r for r in _OFFICIAL_EVENTS.values()
           if r.get("symbol") == sym and (r.get("material") or not material_only)]
    return sorted(out, key=lambda r: str(r.get("disclosedAt") or ""), reverse=True)


def _official_events_track():
    """Scheduled/admin refresh: fill pending market-reaction windows from CACHED/cheap
    daily bars (_jq_price_history — 6h cached). No L2/tape required; missing stays
    missing. Never called from a public GET."""
    _official_events_restore_once()
    now_iso = _ai_now_iso()
    updated = 0
    for oid, rec in list(_OFFICIAL_EVENTS.items()):
        try:
            d0 = str(rec.get("disclosedAt") or "")[:10]
            if not d0 or not rec.get("symbol"):
                continue
            mr = rec.get("marketReaction") or {}
            pending = [w for w, k in (("same_day", "sameDay"), ("next_session", "nextSession"),
                                      ("day3", "day3"), ("day5", "day5")) if not mr.get(k)]
            if not pending:
                continue
            hist = _jq_price_history(rec["symbol"])
            if not hist:
                continue
            dates, closes, vols = hist.get("dates") or [], hist.get("closes") or [], hist.get("volumes") or []
            if d0 not in dates:
                continue
            i0 = dates.index(d0)                       # newest-first
            def _pct(i_new, i_old):
                try:
                    return round((closes[i_new] - closes[i_old]) / closes[i_old] * 100.0, 2)
                except Exception:
                    return None
            def _volr():
                try:
                    base = vols[i0 + 1: i0 + 21]
                    avg = (sum(base) / len(base)) if base else None
                    return round(vols[i0] / avg, 2) if avg else None
                except Exception:
                    return None
            offsets = {"same_day": (i0, i0 + 1), "next_session": (i0 - 1, i0),
                       "day3": (i0 - 3, i0), "day5": (i0 - 5, i0)}
            new_rec = rec
            for w in pending:
                i_new, i_old = offsets[w]
                if i_new < 0 or i_old >= len(closes):
                    continue                            # window not elapsed / out of history
                reaction = argus_official_event_lifecycle.build_market_reaction(
                    window=w, observed_at=now_iso, price_move_pct=_pct(i_new, i_old),
                    volume_ratio=(_volr() if w == "same_day" else None))
                new_rec = argus_official_event_lifecycle.apply_market_reaction(new_rec, reaction)
            if new_rec is not rec:
                _OFFICIAL_EVENTS[oid] = new_rec
                updated += 1
        except Exception:
            continue
    if updated:
        _OFFICIAL_EVENTS_STATE["lastTrackAt"] = now_iso
        _official_events_persist()
    return {"updated": updated, "total": len(_OFFICIAL_EVENTS), "asOf": now_iso}


@app.route("/api/argus/official-events")
def api_argus_official_events():
    """Lifecycle-tracked official disclosures (v11.3). Store-only read — never fetches."""
    _official_events_restore_once()
    rows = list(_OFFICIAL_EVENTS.values())
    sym = (request.args.get("symbol") or "").strip().upper()
    src = (request.args.get("source") or "").strip().lower()
    cat = (request.args.get("category") or "").strip().lower()
    mat = (request.args.get("material") or "").strip().lower()
    if sym:
        rows = [r for r in rows if r.get("symbol") == sym]
    if src:
        rows = [r for r in rows if r.get("source") == src]
    if cat:
        rows = [r for r in rows if r.get("category") == cat]
    if mat in ("1", "true", "yes"):
        rows = [r for r in rows if r.get("material")]
    rows.sort(key=lambda r: str(r.get("disclosedAt") or ""), reverse=True)
    try:
        limit = max(1, min(100, int(request.args.get("limit", "50"))))
    except Exception:
        limit = 50
    return jsonify({"asOf": _ai_now_iso(), "schemaVersion": argus_official_event_lifecycle.SCHEMA_VERSION,
                    "count": len(rows), "items": rows[:limit]})


@app.route("/api/argus/official-events/status")
def api_argus_official_events_status():
    _official_events_restore_once()
    rows = list(_OFFICIAL_EVENTS.values())
    by_stage, by_cat = {}, {}
    for r in rows:
        by_stage[r.get("lifecycleStage")] = by_stage.get(r.get("lifecycleStage"), 0) + 1
        by_cat[r.get("category")] = by_cat.get(r.get("category"), 0) + 1
    return jsonify({"asOf": _ai_now_iso(), "schemaVersion": argus_official_event_lifecycle.SCHEMA_VERSION,
                    "total": len(rows), "material": sum(1 for r in rows if r.get("material")),
                    "byStage": by_stage, "byCategory": by_cat,
                    "lastIngestAt": _OFFICIAL_EVENTS_STATE.get("lastIngestAt"),
                    "lastTrackAt": _OFFICIAL_EVENTS_STATE.get("lastTrackAt"),
                    "noteJa": "公式開示のライフサイクル追跡。開示=事実確認であり、価格原因の確定には市場反応と時刻整合が必要。"})


@app.route("/api/argus/official-events/<oid>")
def api_argus_official_event_one(oid):
    _official_events_restore_once()
    r = _OFFICIAL_EVENTS.get(str(oid))
    if not r:
        return jsonify({"error": "not_found", "officialEventId": oid}), 404
    return jsonify(r)


@app.route("/api/argus/official-events/<oid>/lifecycle")
def api_argus_official_event_lifecycle_view(oid):
    _official_events_restore_once()
    r = _OFFICIAL_EVENTS.get(str(oid))
    if not r:
        return jsonify({"error": "not_found", "officialEventId": oid}), 404
    return jsonify({"officialEventId": oid, "lifecycleStage": r.get("lifecycleStage"),
                    "causeStatus": r.get("causeStatus"), "marketReaction": r.get("marketReaction"),
                    "missingConfirmations": r.get("missingConfirmations"),
                    "evidenceRef": argus_official_event_lifecycle.evidence_ref(r)})


@app.route("/api/argus/official-events/track", methods=["POST"])
def api_argus_official_events_track():
    """ADMIN/cron: fill pending market-reaction windows from cached daily bars."""
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    return jsonify(_official_events_track())


@app.route("/api/argus/official-events/snapshot")
def api_argus_official_events_snapshot():
    """PUBLIC-SAFE durable snapshot (v11.3.1) — what the ledger workflow commits to
    ledger/official-events/. Sanitized metadata only (no PDFs/full text/portfolio),
    deterministic ordering, store-only read (no provider fetch)."""
    _official_events_restore_once()
    return jsonify(argus_official_event_store.serialize_snapshot(
        list(_OFFICIAL_EVENTS.values()), as_of=_ai_now_iso(),
        date_jst=datetime.now(TZ_JST).strftime("%Y-%m-%d"), source="tdnet"))


def _official_ledger_latest_cached():
    """Meta of ledger/official-events/latest.json (ARGUS's own public artifact),
    10-min cached so the durability endpoint stays cheap. Never raises."""
    now = time.time()
    c = _OFFICIAL_LEDGER_CACHE
    if c["data"] is not None and now < c["expires"]:
        return c["data"]
    out = {"configured": True, "reachable": False, "latestLedgerDate": None,
           "latestCount": 0, "lastPersistAt": None}
    try:
        r = requests.get(f"{_LEDGER_RAW_BASE}/official-events/latest.json?cb={int(now)}",
                         timeout=6)
        if r.status_code == 200 and r.text.strip().startswith("{"):
            snap = json.loads(r.text)
            out.update(reachable=True, latestLedgerDate=snap.get("dateJst"),
                       latestCount=(snap.get("summary") or {}).get("total", 0),
                       lastPersistAt=snap.get("asOf"))
    except Exception:
        pass
    c["data"] = out
    c["expires"] = now + 600
    return out


@app.route("/api/argus/official-events/durability")
def api_argus_official_events_durability():
    """Durability status (v11.3.1): is the official-event research history surviving
    restarts? Public-safe; reads the runtime store + ARGUS's own ledger artifact only."""
    _official_events_restore_once()
    led = _official_ledger_latest_cached()
    lims = []
    if not led.get("reachable"):
        lims.append("ledgerブランチのofficial-events/latest.jsonがまだ存在しないか到達不可（初回は16:05のワークフロー後に生成）。")
    if _OFFICIAL_EVENTS_STATE.get("pathType") == "ephemeral_tmp":
        lims.append("現在の実行はledger/tmpどちらからも復元していません（新規デプロイ直後の空ストアの可能性）。")
    return jsonify({
        "schemaVersion": "official-event-durability-v1",
        "asOf": _ai_now_iso(),
        "runtimeStore": {
            "count": len(_OFFICIAL_EVENTS),
            "max": _OFFICIAL_EVENTS_MAX,
            "pathType": _OFFICIAL_EVENTS_STATE.get("pathType"),
            "restoreStatus": _OFFICIAL_EVENTS_STATE.get("restoreStatus"),
            "lastIngestAt": _OFFICIAL_EVENTS_STATE.get("lastIngestAt"),
            "lastTrackAt": _OFFICIAL_EVENTS_STATE.get("lastTrackAt"),
        },
        "durableStore": {
            "configured": True,
            "lastPersistAt": led.get("lastPersistAt"),
            "latestLedgerDate": led.get("latestLedgerDate"),
            "latestCount": led.get("latestCount"),
            "restoreAvailable": bool(led.get("reachable")),
        },
        "safety": {
            "publicGetFetchesProvider": False,
            "storesFullText": False,
            "storesPrivatePortfolio": False,
        },
        "limitationsJa": lims,
    })


@app.route("/api/argus/admin/official-events/snapshot", methods=["POST"])
def api_argus_admin_official_events_snapshot():
    """ADMIN: force-persist the runtime store to /tmp and return the durable snapshot
    summary (the ledger commit itself is the workflow's job)."""
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    _official_events_restore_once()
    _official_events_persist()
    snap = argus_official_event_store.serialize_snapshot(
        list(_OFFICIAL_EVENTS.values()), as_of=_ai_now_iso(),
        date_jst=datetime.now(TZ_JST).strftime("%Y-%m-%d"))
    return jsonify({"ok": True, "summary": snap["summary"], "asOf": snap["asOf"]})


@app.route("/api/argus/admin/official-events/restore", methods=["POST"])
def api_argus_admin_official_events_restore():
    """ADMIN: restore from the ledger-branch snapshot, MERGING (an older snapshot can
    never wipe newer runtime records — store-module merge policy)."""
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    _official_events_restore_once()
    try:
        r = requests.get(f"{_LEDGER_RAW_BASE}/official-events/latest.json?cb={int(time.time())}",
                         timeout=10)
        if r.status_code != 200:
            return jsonify({"ok": False, "reason": f"ledger_http_{r.status_code}"})
        snap = json.loads(r.text)
    except Exception as e:
        return jsonify({"ok": False, "reason": f"fetch_{type(e).__name__}"})
    before = len(_OFFICIAL_EVENTS)
    merged = argus_official_event_store.merge_records(
        _OFFICIAL_EVENTS, list(argus_official_event_store.restore_from_snapshot(snap).values()),
        now_iso=_ai_now_iso())
    _OFFICIAL_EVENTS.clear()
    _OFFICIAL_EVENTS.update(merged)
    _official_events_persist()
    return jsonify({"ok": True, "before": before, "after": len(_OFFICIAL_EVENTS),
                    "ledgerDate": snap.get("dateJst")})


@app.route("/api/argus/tdnet-recent")
def api_argus_tdnet_recent():
    d = get_tdnet_recent()
    # public, read-only: trim the heavy bySymbol map for the wire. EXPLICITLY expose whether
    # this is the OFFICIAL J-Quants Add-on or the yanoshin fallback (v11.1 merge condition),
    # and — when it's the fallback — WHY official didn't win (officialStatus).
    return jsonify({"status": d["status"], "asOf": d["asOf"], "provider": d.get("provider"),
                    "official": bool(d.get("official")), "entitlement": d.get("entitlement"),
                    "officialStatus": d.get("officialStatus"),
                    "count": len(d.get("items") or []), "items": (d.get("items") or [])[:80]})


def _jp_index_proxy():
    """Real JP index move (TOPIX ETF 1306 + Nikkei ETF 1321 average), cached 5m.
    A direct index read beats watchlist-average breadth for market-wide detection.
    Returns None if unavailable (caller falls back to watchlist breadth)."""
    now = time.time()
    if _JP_INDEX_CACHE["val"] is not None and now - _JP_INDEX_CACHE["ts"] < _JP_INDEX_TTL:
        return _JP_INDEX_CACHE["val"]
    val = None
    try:
        snap = get_japan_watchlist_snapshot(["1306", "1321"])
        chs = [float(s["changePct"]) for s in (snap.get("stocks") or [])
               if s.get("status") == "live" and isinstance(s.get("changePct"), (int, float))]
        if chs:
            val = round(sum(chs) / len(chs), 2)
    except Exception:
        val = _JP_INDEX_CACHE["val"]
    _JP_INDEX_CACHE["val"] = val
    _JP_INDEX_CACHE["ts"] = now
    return val


def _downside_catalyst_for(item):
    """From a catalysts-snapshot item, return a catalyst dict iff there is a
    RECENT, concrete catalyst (fresh filing/disclosure, earnings just passed, or
    recent news) that could explain a same-day drop. We do NOT assert it is 'bad'
    (no reliable sentiment) — confirmedNegative stays False; the UI says 要確認."""
    if not isinstance(item, dict):
        return None
    signals = []

    def _recent(date_str, days):
        try:
            d = datetime.strptime(str(date_str)[:10], "%Y-%m-%d").date()
            return (datetime.now(pytz.utc).date() - d).days <= days
        except Exception:
            return False

    earn = item.get("earnings") or {}
    du = earn.get("daysUntil")
    if isinstance(du, (int, float)) and -2 <= du <= 0:
        signals.append("決算発表直後")
    for f in (item.get("filings") or []):
        if _recent(f.get("filingDate"), 3):
            signals.append(f"開示({f.get('form', 'filing')})")
            break
    for d in (item.get("disclosures") or []):
        if d.get("status") == "live" and _recent(d.get("date"), 3):
            signals.append(f"開示({d.get('type', '')})")
            break
    for n in (item.get("news") or []):
        if _recent(n.get("publishedAt") or n.get("datetime"), 2):
            signals.append("関連ニュース")
            break
    if not signals:
        return None
    return {"recent": True, "detail": "・".join(signals[:3]),
            "confirmedNegative": False, "source": item.get("status")}


def get_downside_incidents():
    now = time.time()
    if _DOWNSIDE_CACHE["data"] is not None and now < _DOWNSIDE_CACHE["expires"]:
        return _DOWNSIDE_CACHE["data"]

    jp = get_japan_watchlist_snapshot()
    us = get_us_watchlist_snapshot()
    owner = _owner_symbols_cached()
    jp_stocks = [s for s in (jp.get("stocks") or []) if isinstance(s, dict)]
    us_stocks = [s for s in (us.get("stocks") or []) if isinstance(s, dict)]
    live_jp = [s for s in jp_stocks if s.get("status") == "live"]

    jp_breadth = (round(sum(float(s.get("changePct", 0) or 0) for s in live_jp) / len(live_jp), 2)
                  if live_jp else None)
    jp_dec = sum(1 for s in live_jp if float(s.get("changePct", 0) or 0) < 0)
    hb_live = [s for s in live_jp if str(s.get("symbol")) in _DOWNSIDE_HIGH_BETA]
    high_beta_down = bool(hb_live) and all(float(s.get("changePct", 0) or 0) < -1.0 for s in hb_live)
    reg = _REGIME_CACHE.get("data") or {}
    global_regime = (reg.get("regime") or {}).get("label") or "UNKNOWN"
    index_proxy = _jp_index_proxy()                     # real 1306/1321 move (v10.99)
    nikkei_proxy = index_proxy if index_proxy is not None else jp_breadth

    market_ctx = {
        "globalRegime": global_regime,
        "nikkeiProxyPct": nikkei_proxy, "jpBreadth": jp_breadth,
        "jpDecliners": jp_dec, "jpTotal": len(live_jp),
        "highBetaDown": high_beta_down,
        "themeUnwind": high_beta_down,
        "dataPartial": (jp.get("status") != "live") and (us.get("status") != "live"),
    }

    by_sym = {str(s.get("symbol", "")).upper(): s for s in (jp_stocks + us_stocks)}
    try:
        news_ok = get_market_news().get("status") == "live"
    except Exception:
        news_ok = False
    # Per-symbol catalyst map (recent filing/earnings/news) — lets a real cause
    # surface instead of defaulting to "unknown" (v10.99).
    cat_map = {}
    try:
        cat_snap = get_catalysts_snapshot()
        if cat_snap.get("status") in ("live", "partial"):
            for it in (cat_snap.get("items") or []):
                sym_c = str(it.get("symbol", "")).upper()
                c = _downside_catalyst_for(it)
                if sym_c and c:
                    cat_map[sym_c] = c
    except Exception:
        cat_map = {}
    # TDnet (適時開示) feed — the authoritative JP disclosure source (v10.101).
    tdnet = get_tdnet_recent()
    tdnet_ok = tdnet.get("status") == "live"
    tdnet_by_sym = tdnet.get("bySymbol") or {}

    assets = []
    for s, market in ([(x, "JP") for x in jp_stocks] + [(x, "US") for x in us_stocks]):
        sym = str(s.get("symbol") or "")
        if not sym:
            continue
        chg = s.get("changePct")
        flow = (s.get("flow") or {}).get("bigNetRatio")
        name = s.get("nameJa") or s.get("name") or sym
        ref_index = nikkei_proxy if market == "JP" else None
        vs_index = (round(float(chg) - ref_index, 2)
                    if isinstance(chg, (int, float)) and ref_index is not None else None)
        of = owner.get(sym.upper()) or {}
        owner_state = of.get("ownerState", "watch") if sym.upper() in owner else None
        # TDnet disclosure is the authoritative JP catalyst; fall back to the
        # SEC/Finnhub/J-Quants catalyst map otherwise.
        td_cat = argus_tdnet.summarize_for_symbol(tdnet_by_sym.get(sym)) if market == "JP" else None
        assets.append({
            "symbol": sym, "market": market, "name": name, "assetName": name,
            "changePct": chg, "price": s.get("price"),
            "flowRatio": flow,
            "beta": "high" if sym in _DOWNSIDE_HIGH_BETA else None,
            "vsIndexPct": vs_index,
            "themePeersDown": _theme_peers_down(sym, by_sym),
            "catalyst": td_cat or cat_map.get(sym.upper()),   # TDnet first, else filing/earnings/news (要確認)
            "newsChecked": news_ok or tdnet_ok,
            "tdnetConnected": tdnet_ok if market == "JP" else True,
            "isHeld": owner_state in ("held", "protected"),
            "ownerState": owner_state,
            "downsideStrictness": of.get("downsideStrictness", "normal"),
            "priority": of.get("priority", "normal"),
            "dataFreshnessOk": s.get("status") == "live",
            "currentAction": "HOLD",
        })

    now_iso = datetime.now(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    incidents = argus_downside.classify_incidents(assets, market_ctx, now_iso=now_iso)
    # C.A.O.S. reason lead (v10.174): the downside cause was rule-only, so a drop with no
    # filing read as "原因未確認" for EVERY name (identical rows). Attach the actual linked
    # news — by name OR entity RELATIONSHIP (OpenAI→9984) — as a corroboration-labeled
    # CANDIDATE lead, so each row names its likely driver without asserting causation.
    try:
        _news_rel = [n for n in (get_market_news().get("items") or []) if n.get("relevant")]
        # v10.190: the macro intel feeds rarely name an individual JP stock, so a
        # JP single-name drop had nothing to associate with. Pull per-symbol JP
        # headlines (by company name) for the actual incident symbols before matching.
        try:
            _name_by_sym = {str(a.get("symbol")).upper(): a.get("name") for a in assets}
            _pairs = [(str(inc.get("symbol")).upper(),
                       _name_by_sym.get(str(inc.get("symbol")).upper())
                       or (_ENTITY_PROFILES.get(str(inc.get("symbol")).upper()) or {}).get("name"))
                      for inc in incidents if str(inc.get("market") or "JP").upper() == "JP"]
            _jp_stock_news_intel(_pairs)
        except Exception:
            pass
        _intel = list(_INTEL_STORE)[:80]
        _mover_causes_restore_once()
        for inc in incidents:
            lead = _caos_catalyst_for(inc.get("symbol"), _news_rel, _intel)
            if lead:
                inc["caosLead"] = lead     # UI badge; the text goes through the ladder below
            # V11.3.3 Mover Cause ladder — a bare 原因未確認 is banned. Every incident
            # carries a structured cause status (確認/有力材料/候補/有力候補なし) with the
            # top candidates, why-not-confirmed, and next checks. Cached evidence only
            # (this is a public lazy route); the deep refresh runs on the admin cron.
            try:
                rec = _MOVER_CAUSES.get(
                    f"mc-{str(inc.get('market') or 'JP').upper()}-"
                    f"{str(inc.get('symbol') or '').upper()}-{now_iso[:10].replace('-', '')}")
                if not rec:
                    rec = _mover_cause_for(inc.get("symbol"), inc.get("market", "JP"),
                                           inc.get("changePct"), name=inc.get("assetName"),
                                           direction="down", cached_only=True, caos_lead=lead)
                inc["moverCause"] = argus_mover_cause.compact(_mover_cause_serve(rec, now_iso))
                inc["causeStatus"] = rec.get("causeStatus")
                suffix = argus_mover_cause.reason_suffix_ja(rec)
                if suffix:
                    inc["reasonJa"] = f"{inc.get('reasonJa', '')} ／ {suffix}".strip(" ／")
            except Exception:
                continue
    except Exception:
        pass
    # Structured Action Level signal per incident (v10.124) — APIs/ledgers carry
    # {code, level, permissions, schemaVersion} instead of inferring from text.
    for _inc in incidents:
        _inc["signal"] = argus_signal.resolve_signal(
            _inc.get("currentAction", "HOLD"),
            downside_override=_inc.get("actionOverride"),
            data_quality="PARTIAL" if _inc.get("status") == "partial" else "LIVE",
            material_downside=True,
            exit_confirmed=(_inc.get("incidentType") == "STOCK_SPECIFIC_BAD_NEWS" and _inc.get("severity") == "critical"))
    owner_affected = any(i.get("isHeld") for i in incidents)
    # Escalate the JP overlay on actual severe incidents (not just average breadth)
    # so a few crashing names can't hide behind green peers.
    jp_incs = [i for i in incidents if i.get("market") == "JP"]
    jp_severe = sum(1 for i in jp_incs if i.get("severity") in ("high", "critical"))
    jp_critical = sum(1 for i in jp_incs if i.get("severity") == "critical")
    owner_severe = any(i.get("isHeld") and i.get("severity") in ("high", "critical") for i in jp_incs)
    overlay = argus_downside.jp_intraday_overlay(dict(
        market_ctx, ownerAffected=owner_affected, ownerSevereAffected=owner_severe,
        jpSevereIncidents=jp_severe, jpCriticalIncidents=jp_critical))

    payload = {
        "status": "live" if (jp.get("status") == "live" or us.get("status") == "live") else "partial",
        "asOf": now_iso,
        "engineVersion": "downside-v1",
        "signalSchemaVersion": argus_signal.SIGNAL_SCHEMA_VERSION,
        "incidents": incidents,
        "activeCount": len(incidents),
        "ownerAffected": owner_affected,
        "globalRegime": overlay["globalRegime"],
        "jpIntradayOverlay": overlay["jpIntradayOverlay"],
        "holderRiskOverlay": overlay["holderRiskOverlay"],
        "overlay": overlay,
        "dataLimitations": [
            ("原因のニュース/開示は自動取得(SEC/Finnhub/J-Quants + TDnet適時開示[yanoshin経由])。"
             if tdnet_ok else
             "原因のニュース/開示は自動取得(SEC/Finnhub/J-Quants)。TDnet適時開示は現在取得不可(即時確認に限界)。"),
            "個別材料を検知しても『悪材料』とは自動断定しない(内容は要確認・無材料=安全ではない)。",
            "地合いはTOPIX/日経ETF(1306/1321)の前日比を指数プロキシに使用(取得不可時はwatchlist平均にフォールバック)。",
            "前日比はJ-Quantsでは前営業日終値ベース。moomooブリッジ稼働時のみ当日リアルタイム。",
            "テーマ判定は固定グループ(AI/半導体/電線)による簡易版。",
        ],
        "noteJa": "急落を分類し原因を推定、保有向けにアクションを上書き提示(決定支援のみ・自動売買なし)。",
    }
    _DOWNSIDE_CACHE["data"] = payload
    _DOWNSIDE_CACHE["expires"] = now + _DOWNSIDE_TTL
    return payload


@app.route("/api/argus/downside-incidents")
def api_argus_downside_incidents():
    return jsonify(get_downside_incidents())


# ━━━ Cause Attribution Integrity (v10.116) ━━━
# Distinguish immediate trigger / background vulnerability / amplifier /
# propagation / unknown for a material move — with timestamp + source-semantics
# integrity (no future-earnings-as-cause, no stale-report-as-trigger, no named
# whale without a filing, short-volume ≠ short-interest). Reuses watchlists,
# catalysts, TDnet, flow, and the contagion theme groups. Decision-support only.
def _openai_research(user):
    """GPT with LIVE web search (Responses API web_search tool) → plain-text answer. This is
    what makes the なぜ動いた? button research today's cause (no new key — uses OPENAI_API_KEY).
    Falls back through tool-name variants, then a no-tool call, then None. Bills usage."""
    if not _OPENAI_API_KEY:
        return None
    try:
        import openai
    except Exception:
        return None
    client = openai.OpenAI(api_key=_OPENAI_API_KEY)
    sysmsg = ("あなたはARGUSのリサーチデスク。最新のニュース・事実を調べ、値動きの理由を簡潔に説明する。"
              "出所のない断定はせず、不明なら正直に不明と言う。投資助言・利益保証はしない。")
    for tools in ([{"type": "web_search"}], [{"type": "web_search_preview"}], None):
        try:
            kw = {"model": _OPENAI_MODEL, "instructions": sysmsg, "input": user, "timeout": 90}
            if tools:
                kw["tools"] = tools
            resp = client.responses.create(**kw)
            txt = getattr(resp, "output_text", None)
            if txt:
                try:
                    _ai_record_cost(_ai_now_iso(), "live", "unavailable", False)
                except Exception:
                    pass
                return txt
        except Exception:
            continue
    return None


def _cause_explain(sym, name, market, chg):
    """Live 'why did it move' — uses the entity profile to connect INDIRECT causes
    (OpenAI→9984, 南鳥島レアアース→6330) and web-searches today's news. Returns text or None."""
    prof = _ENTITY_PROFILES.get(str(sym).upper(), {})
    rels = "; ".join(f"{e.get('name')}({e.get('relationJa')})"
                     for e in (prof.get("relatedEntities") or [])[:6] if e.get("name"))
    pct = f"{chg:+.1f}%" if isinstance(chg, (int, float)) else "大きく"
    user = (f"{name or sym}({sym}・{'日本株' if str(market).upper() == 'JP' else '米国株'})が本日{pct}動いた理由を、"
            "最新ニュースを調べて日本語3〜4文で簡潔に説明して。\n"
            f"この銘柄の事業: {prof.get('businessJa') or '(不明)'}\n"
            f"間接的に効く関係先(ニュースが連想で効く): {rels or '(未登録)'}\n"
            "社名が直接出ないニュースでも、上の関係性から連想して原因を推定してよい"
            "(例: OpenAIのIPO遅延→ソフトバンク、南鳥島レアアース政策→東洋エンジニアリング)。"
            "確かな出所があれば示し、推測は『可能性』と明示。憶測の断定・投資助言はしない。")
    txt = _openai_research(user)
    return (txt or "").strip()[:700] or None


def get_cause_attribution(symbol, market="JP", explain=False):
    symu = str(symbol).upper()
    jp = get_japan_watchlist_snapshot()
    us = get_us_watchlist_snapshot()
    by = {str(s.get("symbol", "")).upper(): s for s in
          ((jp.get("stocks") or []) + (us.get("stocks") or [])) if isinstance(s, dict)}
    row = by.get(symu) or {}
    name = row.get("nameJa") or row.get("name") or symu
    chg = row.get("changePct")
    flow = (row.get("flow") or {}).get("bigNetRatio")

    # move reference: the JP session open today (so yesterday's filings read stale)
    now_utc = datetime.now(pytz.utc)
    move_started = now_utc.replace(hour=0, minute=5, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")

    # evidence from catalysts (earnings + filings) and TDnet (JP disclosures)
    evidence = []
    news = []   # classified, displayable news/disclosures for the stock card (v10.142)
    days_to_earn = None
    try:
        for it in (get_catalysts_snapshot().get("items") or []):
            if str(it.get("symbol", "")).upper() != symu:
                continue
            earn = it.get("earnings") or {}
            du = earn.get("daysUntil")
            if isinstance(du, (int, float)):
                days_to_earn = du
                if du > 0:
                    evidence.append({"id": f"earn:{symu}", "kind": "earnings",
                                     "isFutureEvent": True, "sourceReliability": 0.7, "supports": []})
            for f in (it.get("filings") or [])[:3]:
                evidence.append({"id": f"filing:{f.get('form')}", "kind": "filing",
                                 "publishedAt": f.get("filingDate"), "sourceReliability": 0.6,
                                 "supports": ["COMPANY_SPECIFIC_CATALYST"]})
                news.append({"time": f.get("filingDate"), "titleJa": f"開示: {f.get('form')}",
                             "source": "SEC/EDGAR",
                             "cls": argus_attribution.classify_news(
                                 {"publishedAt": f.get("filingDate"), "sourceReliability": 0.6, "official": True}, move_started)})
    except Exception:
        pass
    if market == "JP":
        try:
            for d in (get_tdnet_recent().get("bySymbol") or {}).get(symu[:4], [])[:3]:
                neg = d.get("sentiment") == "negative"
                evidence.append({"id": f"tdnet:{d.get('category')}", "kind": "report",
                                 "publishedAt": d.get("time"), "sourceReliability": 0.7,
                                 "sameDayRecirculation": True,
                                 "supports": ["COMPANY_SPECIFIC_CATALYST"] if neg else []})
                news.append({"time": d.get("time"), "titleJa": d.get("title") or d.get("category") or "適時開示",
                             "source": "TDnet", "sentiment": d.get("sentiment"),
                             "cls": argus_attribution.classify_news(
                                 {"publishedAt": d.get("time"), "sourceReliability": 0.7,
                                  "sameDayRecirculation": True, "official": True}, move_started)})
        except Exception:
            pass
    else:
        # US: per-company media headlines (Finnhub). Media ≠ official disclosure, so
        # these classify as UNCONFIRMED (related to the company, causal link to the
        # move not asserted). Headlines stay in their source language (v10.144).
        try:
            for cn in (get_company_news(symu) or [])[:4]:
                ts = cn.get("datetime")
                iso = (datetime.fromtimestamp(ts, pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                       if isinstance(ts, (int, float)) and ts > 0 else None)
                hl = (cn.get("headline") or "").strip()
                if not hl:
                    continue
                # v11.5.1: US Finnhub headlines are English — decorate so the UI shows a
                # JP title (or JP fallback), never raw English as the primary text.
                _d = _news_decorate(hl[:120], cn.get("source") or "Finnhub")
                news.append({"time": iso, **_d, "titleEn": hl[:120],
                             "source": cn.get("source") or "Finnhub",
                             "cls": argus_attribution.classify_news({"publishedAt": iso, "official": False}, move_started)})
        except Exception:
            pass

    # contagion peers from the theme groups (reuse _DOWNSIDE_THEMES)
    peers = []
    for members in _DOWNSIDE_THEMES.values():
        if symu in members:
            for m in members:
                if m == symu:
                    continue
                r = by.get(m)
                if r and isinstance(r.get("changePct"), (int, float)):
                    peers.append({"changePct": r["changePct"], "theme": "ai_semis", "market": r.get("market", market)})
    contagion = argus_attribution.classify_contagion(symu, peers)

    positioning = argus_attribution.positioning_probabilities({
        "flowRatio": flow, "changePct": chg, "volRatio": None,
        "priorFlowRatio": None, "relativeWeakness": bool(peers and chg is not None and chg < 0)})

    ctx = {
        "moveStartedAt": move_started, "daysToEarnings": days_to_earn,
        "earningsResultReleased": False, "priorRunupPct": None,
        "peersDown": contagion.get("downFraction", 0) >= 0.5,
        "shortWindowDownAccel": bool(chg is not None and chg <= -4),
        "flowReversal": False, "contagion": contagion, "positioning": positioning,
        "aiCapexConcern": symu in {"NVDA", "SMH", "285A", "5801", "5803", "MU"},
        "isHeld": False,
    }
    stack = argus_attribution.attribute_cause(ctx, evidence, now_iso=move_started)
    stack["symbol"] = symu
    stack["market"] = market
    stack["changePct"] = chg
    stack["asOf"] = _ai_now_iso()
    stack["positioningSources"] = argus_attribution.POSITIONING_SOURCES
    # association-engine links (v10.183): news naming a RELATED entity/theme, not the stock's
    # own name (OpenAI→9984, 南鳥島レアアース→6330) — surfaced in the cause stack when present.
    try:
        pool = []
        _mn = get_market_news()
        if isinstance(_mn, dict) and _mn.get("status") == "live":
            for n in _mn.get("items", []):
                if n.get("relevant"):
                    pool.append((n.get("headline"), n.get("headlineJa"), n.get("source"), n.get("corroboration")))
        for it in list(_INTEL_STORE)[:80]:
            pool.append((it.get("title"), it.get("titleJa"), it.get("sourceId"), None))
        seen_a = set()
        for hl, hlja, src, corr in pool:
            m = next((x for x in _entity_link((hl or "") + " " + (hlja or ""))
                      if x["symbol"] == symu and x["via"] in ("entity", "theme")), None)
            title = (hlja or _headline_ja(hl or "") or "")[:120]     # prefer JP; translate English
            if not m or not title or title in seen_a:
                continue
            seen_a.add(title)
            news.append({"time": None, "titleJa": title, "source": src or "C.A.O.S.", "cls": "LIKELY_RELATED",
                         "assoc": {"via": m["via"], "term": m.get("term"),
                                   "relationJa": m.get("relationJa") or f"関連: {m.get('term')}",
                                   "corroboration": corr or "single"}})
            if len(seen_a) >= 4:
                break
    except Exception:
        pass
    # v11.5.1: every news item gets Japanese-first display fields (displayTitleJa is
    # never raw English). English titles are queued for the admin translate cron.
    _news_ja_restore_once()
    news = [argus_news_freshness.decorate_news_item(
                argus_news_i18n.decorate_news_item(n, _NEWS_JA_CACHE), _ai_now_iso(),
                time_keys=("time", "publishedAt", "datetime"))
            for n in news]
    for n in news:
        if n.get("translationStatus") == "pending":
            _NEWS_JA_SEEN.append(n.get("titleOriginal") or "")
    # v11.5.6 owner rule: newest first on every screen — sort by the decorated age
    # (undated items sink to the bottom, never fake-fresh at the top).
    news.sort(key=lambda n: ((n.get("newsFreshness") or {}).get("ageHours") is None,
                             (n.get("newsFreshness") or {}).get("ageHours") or 0.0))
    stack["news"] = news
    # v11.6.0: compact institutional notes for this symbol (cached-only; context,
    # never a trade instruction — the FE renders stance/directness/whyJa).
    try:
        stack["institutionalSignals"] = _institutional_signals(symbol=symu, cap=40)[:2]
    except Exception:
        stack["institutionalSignals"] = []
    # v11.7.0: flow attribution — 大口/買い戻し/追随の型を証拠ベースで添付
    # (cached-only; 可能性/推定の語彙のみ、断定・売買指示なし)。
    try:
        stack["flowAttribution"] = _flow_attribution_for(symu, market)
    except Exception:
        stack["flowAttribution"] = None
    # V11.3.3: attach the mover-cause ladder (cached evidence only — no fetch/LLM)
    try:
        _mover_causes_restore_once()
        today = _ai_now_iso()[:10].replace("-", "")
        mc = _MOVER_CAUSES.get(f"mc-{str(market).upper()}-{symu}-{today}")
        if mc is None:
            mc = _mover_cause_for(symu, market, chg, name=name, cached_only=True)
        stack["moverCause"] = argus_mover_cause.compact(_mover_cause_serve(mc, _ai_now_iso()))
        # explain=true is now CACHED-ONLY (the old path fired a billed OpenAI
        # web_search from an unauthenticated public GET). Generation moved to
        # POST /api/argus/admin/mover-causes/explain.
        if explain:
            if mc.get("explanationJa"):
                stack["explanationJa"] = mc["explanationJa"]
                stack["explanationStatus"] = "cached"
                stack["explanationGeneratedAt"] = mc.get("explanationGeneratedAt")
            else:
                # V11.5.2: a pending owner request reads as "queued" (the 「理由を詳しく調べる」
                # button was pressed); otherwise not_generated. Public GET never starts AI.
                _mc_explain_req_restore_once()
                queued = _mc_has_explain_request(symu, market)
                stack["explanationStatus"] = "queued" if queued else "not_generated"
                stack["explanationNoteJa"] = (
                    "調査リクエスト受付済み。次回の管理側定期生成で反映されます。" if queued else
                    "AI解説は未生成です。「理由を詳しく調べる」で調査キューに追加できます"
                    "(公開画面からAIは起動しません)。")
    except Exception:
        if explain:
            stack["explanationStatus"] = "not_generated"
    return stack


@app.route("/api/argus/cause-attribution")
def api_argus_cause_attribution():
    sym = (request.args.get("symbol") or "").strip()
    if not sym:
        return jsonify({"error": "symbol required"}), 400
    mkt = (request.args.get("market") or "JP").upper()
    explain = (request.args.get("explain") or "").lower() in ("1", "true", "yes")
    try:
        return jsonify(get_cause_attribution(sym, mkt, explain=explain))
    except Exception as e:
        return jsonify({"error": "attribution_failed", "message": str(e)[:120]}), 200


# ⑧ Cause Attribution Ledger (v10.117): the cause stack for every active incident,
# in one call, so the daily workflow can persist it (and later compare to outcome).
def get_cause_attribution_batch():
    try:
        ds = get_downside_incidents()
    except Exception:
        ds = {}
    incs = ds.get("incidents") or []
    out = []
    for i in incs[:8]:
        try:
            st = get_cause_attribution(i.get("symbol"), i.get("market", "JP"))
            out.append({"symbol": st.get("symbol"), "market": st.get("market"),
                        "changePct": st.get("changePct"),
                        "immediateTrigger": st.get("immediateTrigger"),
                        "causeProbabilities": st.get("causeProbabilities"),
                        "unknownShare": st.get("unknownShare"),
                        "contagionScope": (st.get("contagion") or {}).get("scope"),
                        "preEventDeRisking": (st.get("preEvent") or {}).get("preEventDeRiskingProbability")})
        except Exception:
            continue
    return {"status": "live" if out else "empty", "asOf": _ai_now_iso(),
            "engineVersion": "cause-attribution-v1", "attributions": out, "count": len(out)}


@app.route("/api/argus/cause-attribution-batch")
def api_argus_cause_attribution_batch():
    return jsonify(get_cause_attribution_batch())


# ━━━ V11.3.3 Mover Cause Engine ━━━
# Unified attribution ladder for sharp movers BOTH directions. The owner's finding:
# every mover showed a bare 原因未確認, making the layer useless. The ladder separates
# 原因確認/有力材料/候補/有力候補なし and always says what was checked + what to check
# next. Public GET = cached/in-memory evidence only (no provider fetch, no LLM);
# admin/cron refresh may fetch providers; AI explanation is admin-generated only.
_MOVER_CAUSES = {}                      # moverCauseId -> record
_MOVER_CAUSES_FILE = "/tmp/argus_mover_causes.json"
_MOVER_CAUSES_STATE = {"restored": False, "lastRefreshAt": None,
                       "lastExplainAt": None, "pathType": "ephemeral_tmp"}
# v11.3.4 AI-explain budget knobs (env-tunable; admin/cron paths only)
_MC_AI_MAX_PER_RUN = int(os.environ.get("MOVER_CAUSE_AI_EXPLAIN_MAX_PER_RUN", "5"))
_MC_AI_COOLDOWN_MIN = int(os.environ.get("MOVER_CAUSE_AI_EXPLAIN_COOLDOWN_MIN", "30"))
_MC_AI_MIN_ABS_MOVE = float(os.environ.get("MOVER_CAUSE_AI_EXPLAIN_MIN_ABS_MOVE", "3.0"))
_MC_AI_ENABLED = (os.environ.get("MOVER_CAUSE_AI_EXPLAIN_ENABLED",
                                 os.environ.get("AI_JUDGE_ENABLED", "1")).lower()
                  not in ("0", "false", "no"))
_MOVER_REFRESH_QUEUE = {"data": None, "expires": 0.0}   # cached queue (5-min TTL)

# ── V11.5.2 explanation request queue ────────────────────────────────────────
# The owner clicks 「理由を詳しく調べる」. That PUBLIC POST enqueues a request here —
# it NEVER calls an LLM or a provider. The admin/cron explain run drains this queue
# FIRST (still cooldown/budget-guarded). Only symbol/market/context/timestamps are
# stored — never prompts, holdings, P&L, or provider bodies. Bounded + deduped.
_MC_EXPLAIN_REQUESTS = {}               # "MKT:SYM" -> {symbol, market, context, count, firstAt, lastAt}
_MC_EXPLAIN_REQ_FILE = "/tmp/argus_mc_explain_requests.json"
_MC_EXPLAIN_REQ_STATE = {"restored": False, "lastDrainAt": None, "lastDrainCount": 0}
_MC_EXPLAIN_REQ_MAX = 100               # bounded (oldest dropped)
_MC_EXPLAIN_REQ_RL = {}                 # "ip|MKT:SYM" -> last epoch (per-IP+symbol throttle)
_MC_EXPLAIN_REQ_RL_SEC = 30


def _mc_explain_key(symbol, market):
    return f"{str(market).upper()}:{str(symbol).upper()}"


def _mc_explain_req_persist():
    try:
        with open(_MC_EXPLAIN_REQ_FILE, "w") as f:
            json.dump({"requests": _MC_EXPLAIN_REQUESTS,
                       "state": {k: _MC_EXPLAIN_REQ_STATE[k]
                                 for k in ("lastDrainAt", "lastDrainCount")}},
                      f, ensure_ascii=False, default=str)
    except Exception:
        pass


def _mc_explain_req_restore_once():
    if _MC_EXPLAIN_REQ_STATE["restored"]:
        return
    _MC_EXPLAIN_REQ_STATE["restored"] = True
    try:
        with open(_MC_EXPLAIN_REQ_FILE) as f:
            blob = json.load(f)
        if isinstance(blob.get("requests"), dict):
            _MC_EXPLAIN_REQUESTS.update(blob["requests"])
        for k in ("lastDrainAt", "lastDrainCount"):
            if (blob.get("state") or {}).get(k) is not None:
                _MC_EXPLAIN_REQ_STATE[k] = blob["state"][k]
    except Exception:
        pass


def _mc_explain_req_add(symbol, market, context, now_iso):
    """Enqueue/refresh a request. Bounded + deduped by symbol+market. No LLM/provider."""
    key = _mc_explain_key(symbol, market)
    e = _MC_EXPLAIN_REQUESTS.get(key)
    if e:
        e["count"] = int(e.get("count") or 1) + 1
        e["lastAt"] = now_iso
        if context:
            e["context"] = str(context)[:40]
        status = "already_queued"
    else:
        _MC_EXPLAIN_REQUESTS[key] = {
            "symbol": str(symbol).upper()[:16], "market": str(market).upper()[:4],
            "context": str(context or "")[:40], "count": 1,
            "firstAt": now_iso, "lastAt": now_iso}
        status = "queued"
    if len(_MC_EXPLAIN_REQUESTS) > _MC_EXPLAIN_REQ_MAX:
        for k in sorted(_MC_EXPLAIN_REQUESTS,
                        key=lambda k: str(_MC_EXPLAIN_REQUESTS[k].get("firstAt"))
                        )[:len(_MC_EXPLAIN_REQUESTS) - _MC_EXPLAIN_REQ_MAX]:
            _MC_EXPLAIN_REQUESTS.pop(k, None)
    return status


def _mc_has_explain_request(symbol, market):
    return _mc_explain_key(symbol, market) in _MC_EXPLAIN_REQUESTS


def _mover_causes_persist():
    try:
        with open(_MOVER_CAUSES_FILE, "w") as f:
            json.dump({"items": _MOVER_CAUSES,
                       "state": {k: _MOVER_CAUSES_STATE[k]
                                 for k in ("lastRefreshAt", "lastExplainAt")}},
                      f, ensure_ascii=False, default=str)
    except Exception:
        pass


def _mover_causes_restore_once():
    """tmp → ledger latest (merge; old snapshots never wipe newer) → empty."""
    if _MOVER_CAUSES_STATE["restored"]:
        return
    _MOVER_CAUSES_STATE["restored"] = True
    try:
        with open(_MOVER_CAUSES_FILE) as f:
            blob = json.load(f)
        items = blob.get("items") or {}
        _MOVER_CAUSES_STATE.update({k: v for k, v in (blob.get("state") or {}).items()
                                    if k in ("lastRefreshAt", "lastExplainAt")})
        if items:
            _MOVER_CAUSES.update(items)
            _MOVER_CAUSES_STATE["pathType"] = "durable_restored"
            return
        # an empty tmp file (calm-moment persist) must NOT block the ledger tier
    except Exception:
        pass
    try:
        r = requests.get(f"{_LEDGER_RAW_BASE}/mover-causes/latest.json?cb={int(time.time())}",
                         timeout=6)
        if r.status_code == 200 and r.text.strip().startswith("{"):
            restored = argus_mover_cause_store.restore_from_snapshot(json.loads(r.text))
            merged = argus_mover_cause_store.merge_records(
                _MOVER_CAUSES, list(restored.values()), now_iso=_ai_now_iso())
            _MOVER_CAUSES.clear()
            _MOVER_CAUSES.update(merged)
            if merged:
                _MOVER_CAUSES_STATE["pathType"] = "ledger_restored"
    except Exception:
        pass


def _mover_move_started_iso(market):
    """Per-market session-open proxy for timing checks (JP 09:05 JST / US 09:35 ET,
    DST-aware). Before the open, TODAY's open still stands — the move hasn't
    started yet, so all overnight/pre-market news honestly reads before_move."""
    now_utc = datetime.now(pytz.utc)
    if str(market).upper() == "JP":
        open_utc = now_utc.replace(hour=0, minute=5, second=0, microsecond=0)
    else:
        et = now_utc.astimezone(pytz.timezone("US/Eastern"))
        open_et = et.replace(hour=9, minute=35, second=0, microsecond=0)
        open_utc = open_et.astimezone(pytz.utc)
    return open_utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_mover_cause_inputs(symbol, market, change_pct=None, name=None,
                              cached_only=True, caos_lead=None):
    """Collect evidence for the pure ladder. cached_only=True reads ONLY in-memory
    caches/stores (public-path safe); cached_only=False (admin refresh) may fetch
    free/contracted providers — never LLM."""
    symu, mkt = str(symbol).upper(), str(market).upper()
    code4 = symu[:4]
    cover = {k: False for k in ("tdnetChecked", "officialEventsChecked", "edinetSecChecked",
                                "companyNewsChecked", "jpNewsChecked", "caosChecked",
                                "sectorPeerChecked", "macroChecked", "flowChecked",
                                "technicalChecked")}
    ev = {"coverage": cover}
    direction = "down" if (isinstance(change_pct, (int, float)) and change_pct < 0) else "up"

    # official: TDnet (JP)
    if mkt == "JP":
        try:
            snap = _tdnet_recent_cached_only() if cached_only else get_tdnet_recent()
            if snap:
                # checked = the feed was actually usable, not merely a failure snapshot
                cover["tdnetChecked"] = str(snap.get("status") or "").endswith("live") \
                    or bool(snap.get("items"))
                ev["tdnetItems"] = (snap.get("bySymbol") or {}).get(code4, [])[:8]
        except Exception:
            pass
        try:
            _official_events_restore_once()
            evs = _official_events_by_symbol(symu)
            cover["officialEventsChecked"] = True
            ev["officialEvents"] = evs[:6]
        except Exception:
            pass

    # filings / earnings from the catalysts snapshot
    try:
        cat = None
        if cached_only:
            if _CAT_CACHE.get("data") is not None and time.time() < _CAT_CACHE.get("expires", 0):
                cat = _CAT_CACHE["data"]
        else:
            cat = get_catalysts_snapshot()
        if isinstance(cat, dict):
            cover["edinetSecChecked"] = True
            for it in (cat.get("items") or []):
                if str(it.get("symbol", "")).upper() != symu:
                    continue
                ev["filings"] = (it.get("filings") or [])[:5]
                earn = it.get("earnings") or {}
                # daysUntil=0 with date=None is the "no earnings known" sentinel —
                # passing it through would fabricate a 決算前 vulnerability candidate
                if isinstance(earn.get("daysUntil"), (int, float)) and earn.get("date"):
                    ev["earnings"] = {"daysToEarnings": earn.get("daysUntil"),
                                      "resultReleased": False}
                break
    except Exception:
        pass

    # direct news: Finnhub (US) / Google News JP intel items (JP)
    if mkt == "US":
        try:
            if cached_only:
                fin = (_FINN_CACHE.get(symu) or {}).get("data")
            else:
                res = _finnhub_catalyst(symu)      # returns (data, status)
                fin = res[0] if isinstance(res, tuple) else res
            if isinstance(fin, dict):
                cover["companyNewsChecked"] = True
                # v11.5.5: candidates are built from the ORIGINAL headline — the ladder's
                # identity/corroboration logic needs distinct titles. (The v11.5.1 pre-
                # replacement with displayTitleJa collapsed every untranslated headline
                # into the same 「翻訳待ち…」 string, faking multi_source corroboration and
                # producing meaningless bestLeads — caught by the violations detector.)
                # Japanese-first DISPLAY happens at serve time via
                # _mover_cause_decorate_candidates; _news_decorate here only QUEUES the
                # headline for the translate cron.
                _cn = []
                for n in (fin.get("news") or [])[:8]:
                    if isinstance(n, dict) and n.get("headline"):
                        _news_decorate(str(n["headline"]), n.get("source") or "Finnhub")
                        n = {**n, "headlineEn": str(n["headline"])}
                    _cn.append(n)
                ev["companyNews"] = _cn
        except Exception:
            pass
    else:
        try:
            if not cached_only:
                _jp_stock_news_intel([(symu, name or (_ENTITY_PROFILES.get(symu) or {}).get("name"))])
            # V11.5.3 evidence hygiene: the intel store keeps items for days — never
            # feed >7-day-old articles into TODAY's cause evidence (the freshness
            # gate in argus_mover_cause demotes 72h+ anyway; this trims the pool).
            _now_iso7 = _ai_now_iso()
            # v11.5.4: per-symbol discovery items carry symbolHint (not linkedAssets) —
            # match BOTH so investigate-now's fresh finds actually reach the ladder.
            jp_news = [{"titleJa": it.get("titleJa") or it.get("title"),
                        "publishedAt": it.get("publishedAt") or it.get("firstDetectedAt"),
                        "publisher": it.get("author") or "GoogleNewsJP", "source": "google_news_jp",
                        "sentiment": None}
                       for it in list(_INTEL_STORE)
                       if it.get("sourceId") in ("google_news_jp", "public_article")
                       and (symu in {str(a).upper() for a in (it.get("linkedAssets") or [])}
                            or str(it.get("symbolHint") or "").upper() == symu)
                       and (argus_news_freshness.age_hours(
                           it.get("publishedAt") or it.get("firstDetectedAt"), _now_iso7) or 0) <= 168]
            cover["jpNewsChecked"] = True
            # newest first — the cap must never crowd fresh items out with old ones
            jp_news.sort(key=lambda n: argus_news_freshness._epoch(n.get("publishedAt")) or 0.0,
                         reverse=True)
            ev["jpNews"] = jp_news[:8]
        except Exception:
            pass

    # C.A.O.S. association lead (pure in-memory matching)
    try:
        if caos_lead is None:
            mn = _MARKET_NEWS_CACHE.get("data") or {}
            rel = [n for n in (mn.get("items") or []) if n.get("relevant")]
            caos_lead = _caos_catalyst_for(symu, rel, list(_INTEL_STORE)[:80])
        cover["caosChecked"] = True
        if caos_lead:
            ev["caosLead"] = caos_lead
    except Exception:
        pass

    # sector/theme peers (cached quotes only)
    try:
        for theme, members in _DOWNSIDE_THEMES.items():
            if symu not in members:
                continue
            same = total = 0
            for m in members:
                if m == symu:
                    continue
                q = _quote_cached_only(m, "JP" if m[:1].isdigit() else "US") or {}
                pc = q.get("changePct")
                if isinstance(pc, (int, float)):
                    total += 1
                    if abs(pc) >= 1.0 and ((pc < 0) == (direction == "down")):
                        same += 1
            ev["peers"] = {"theme": theme, "peersTotal": total, "peersSameDirection": same}
            cover["sectorPeerChecked"] = total > 0
            break
    except Exception:
        pass

    # macro events released/imminent today (in-memory macro store + regime cache)
    try:
        _macro_analysis_restore_once()
        regime = ((_REGIME_CACHE.get("data") or {}).get("regime") or {}).get("label") or ""
        consistent = (regime == "RISK_OFF" and direction == "down") or \
                     (regime == "RISK_ON" and direction == "up")
        today = _ai_now_iso()[:10]
        macros = []
        for rec in _MOVER_MACRO_VIEW():
            if rec.get("phase") in ("imminent", "released_pending_result", "post_result") \
                    and str(rec.get("eventTimeUtc") or rec.get("eventDate") or "")[:10] == today:
                macros.append({"eventCode": rec.get("eventCode"), "title": rec.get("title"),
                               "source": rec.get("source"), "marketConsistent": consistent,
                               "whyJa": f"本日の{rec.get('eventCode')}前後の地合い変化の可能性(regime={regime or '不明'})。"})
        cover["macroChecked"] = True
        ev["macroEvents"] = macros[:3]
    except Exception:
        pass

    # flow / technical (cached quote + cached daily bars)
    try:
        q = _quote_cached_only(symu, mkt) or {}
        bnr = ((q.get("flow") or {}).get("bigNetRatio"))
        if isinstance(bnr, (int, float)):
            cover["flowChecked"] = True
            ev["flow"] = {"bigNetRatio": bnr}
    except Exception:
        pass
    if mkt == "JP":
        try:
            hist = (_JQ_MARGIN_CACHE.get(code4) or {}).get("data") or []
            if hist and isinstance(hist, list):
                latest = hist[0]                    # _jq_weekly_margin rows are newest-first
                ev["margin"] = {"shortHeavy": bool((latest.get("shortVol") or 0) >
                                                   (latest.get("longVol") or 0))}
        except Exception:
            pass
        try:
            h = (_JQ_HISTORY_CACHE.get(code4) or {}).get("data") or {}
            closes = h.get("closes") or []
            if len(closes) >= 7 and closes[6]:
                runup = round((float(closes[1]) / float(closes[6]) - 1) * 100, 1)
                ev["technical"] = {"priorRunupPct": runup}
                cover["technicalChecked"] = True
        except Exception:
            pass
    return ev


def _MOVER_MACRO_VIEW():
    return list(_MACRO_ANALYSIS.values())


def _market_confirmation_inputs(symbol, market, change_pct):
    """Cached-only inputs for Market Confirmation v1.5 — quote caches, push
    history, JQ daily bars, theme peers. Never fetches (public-path safe)."""
    symu, mkt = str(symbol).upper(), str(market).upper()
    inputs = {"changePct": change_pct}
    try:                                        # index proxy (relative move)
        idx_sym, idx_name = ("1306", "TOPIX ETF(1306)") if mkt == "JP" else ("SPY", "SPY")
        q = _quote_cached_only(idx_sym, mkt) or {}
        if isinstance(q.get("changePct"), (int, float)):
            inputs["indexMovePct"] = q["changePct"]
            inputs["indexName"] = idx_name
    except Exception:
        pass
    try:                                        # theme-peer basket
        for members in _DOWNSIDE_THEMES.values():
            if symu not in members:
                continue
            moves = []
            for m in members:
                if m == symu:
                    continue
                pq = _quote_cached_only(m, "JP" if m[:1].isdigit() else "US") or {}
                if isinstance(pq.get("changePct"), (int, float)):
                    moves.append(pq["changePct"])
            inputs["peerMoves"] = moves
            break
    except Exception:
        pass
    try:                                        # volume ratio (JP daily bars)
        q = _quote_cached_only(symu, mkt) or {}
        tv = q.get("volume")
        if isinstance(tv, (int, float)) and tv > 0:
            inputs["todayVolume"] = tv
        if mkt == "JP":
            h = (_JQ_HISTORY_CACHE.get(symu[:4]) or {}).get("data") or {}
            vols = [v for v in (h.get("volumes") or [])[1:21] if isinstance(v, (int, float)) and v > 0]
            if len(vols) >= 5:
                inputs["avgVolume"] = sum(vols) / len(vols)
    except Exception:
        pass
    try:                                        # intraday push points (15m/1h moves)
        hist = (_PUSH_HISTORY.get(mkt) or {}).get(symu)
        if hist:
            inputs["pushPoints"] = [{"ts": p.get("ts"), "price": p.get("price"),
                                     "volume": p.get("volume")} for p in list(hist)]
    except Exception:
        pass
    return inputs


def _mover_cause_for(symbol, market, change_pct, name=None, direction=None,
                     cached_only=True, caos_lead=None):
    ev = _build_mover_cause_inputs(symbol, market, change_pct, name=name,
                                   cached_only=cached_only, caos_lead=caos_lead)
    now_iso = _ai_now_iso()
    try:
        ev["marketConfirmation"] = argus_market_confirmation.compute(
            {"symbol": symbol, "market": market, "changePct": change_pct},
            _market_confirmation_inputs(symbol, market, change_pct), now_iso)
    except Exception:
        pass
    # PRIVACY: no owner data goes into the record — records reach public GETs
    # and the public ledger. Owner priority boost is transient (admin queue only).
    mover = {"symbol": symbol, "market": market, "changePct": change_pct,
             "direction": direction, "name": name, "asOf": now_iso,
             "moveStartedAt": _mover_move_started_iso(market)}
    return argus_mover_cause.resolve(mover, ev, now_iso,
                                     ai_min_abs_move=_MC_AI_MIN_ABS_MOVE)


def _collect_active_movers():
    """The refresh target set: downside incidents + watchlist big up-moves +
    whole-market mover rows (cached tiers only — the scans own the fetching)."""
    movers, seen = [], set()

    def _add(sym, mkt, chg, name=None):
        key = (str(mkt).upper(), str(sym).upper())
        if not sym or key in seen or not isinstance(chg, (int, float)):
            return
        seen.add(key)
        movers.append({"symbol": str(sym).upper(), "market": str(mkt).upper(),
                       "changePct": chg, "name": name,
                       "direction": "down" if chg < 0 else "up"})
    try:
        for inc in (get_downside_incidents().get("incidents") or []):
            _add(inc.get("symbol"), inc.get("market", "JP"), inc.get("changePct"),
                 inc.get("assetName"))
    except Exception:
        pass
    try:
        for snap, mkt in ((get_japan_watchlist_snapshot(), "JP"),
                          (get_us_watchlist_snapshot(), "US")):
            for s in (snap.get("stocks") or []):
                chg = s.get("changePct")
                if isinstance(chg, (int, float)) and chg >= 3.0:
                    _add(s.get("symbol"), mkt, chg, s.get("nameJa") or s.get("name"))
    except Exception:
        pass
    try:
        for r in (_moomoo_us_movers() or []):
            _add(r.get("symbol"), "US", r.get("changePct"), r.get("name"))
    except Exception:
        pass
    try:
        y = _YAHOO_MOVERS_CACHE.get("data") or {}
        for r in (y.get("gainers") or [])[:8] + (y.get("losers") or [])[:8]:
            _add(r.get("symbol"), "JP", r.get("changePct"), r.get("name"))
    except Exception:
        pass
    movers.sort(key=lambda m: -abs(m["changePct"]))
    return movers


def _refresh_mover_causes(limit=14):
    """Admin/cron: rebuild ladders for the active mover set. Providers allowed
    (cached_only=False), LLM never (explanations are a separate admin route)."""
    _mover_causes_restore_once()
    now_iso = _ai_now_iso()
    built = 0
    for mv in _collect_active_movers()[:limit]:
        try:
            rec = _mover_cause_for(mv["symbol"], mv["market"], mv["changePct"],
                                   name=mv.get("name"), direction=mv.get("direction"),
                                   cached_only=False)
            merged = argus_mover_cause_store.merge_record(
                _MOVER_CAUSES.get(rec["moverCauseId"]), rec, now_iso=now_iso)
            if merged:
                _MOVER_CAUSES[merged["moverCauseId"]] = merged
                built += 1
        except Exception:
            continue
    # bound the store (keep the newest ~200 records)
    if len(_MOVER_CAUSES) > 200:
        for mid in sorted(_MOVER_CAUSES, key=lambda k: str(_MOVER_CAUSES[k].get("asOf")))[:len(_MOVER_CAUSES) - 200]:
            _MOVER_CAUSES.pop(mid, None)
    _MOVER_CAUSES_STATE["lastRefreshAt"] = now_iso
    _mover_causes_persist()
    return {"refreshed": built, "total": len(_MOVER_CAUSES), "asOf": now_iso}


def _mover_cause_decorate_candidates(out):
    """V11.5.2: a candidate's titleJa can be a raw ENGLISH news headline (US Finnhub).
    Rewrite it to Japanese-first for display — cached JA if we have it, else a JP
    fallback — keeping the English original in titleOriginal and queuing it for the
    next translate run. Mutates the (already-copied) served record only."""
    changed_lead = None
    for c in (out.get("causeCandidates") or []):
        t = str(c.get("titleJa") or "")
        if not argus_news_i18n.looks_translatable(t):
            continue
        src = str(c.get("source") or "")
        d = _news_decorate(t, src)                       # queues + cached-only decorate
        c["titleOriginal"] = d["titleOriginal"]
        c["translationStatus"] = d["translationStatus"]
        c["titleJa"] = d["displayTitleJa"]               # JA (cached) or JP fallback
        if changed_lead is None:
            changed_lead = d["displayTitleJa"]
    # keep bestLeadJa consistent if it echoed a now-rewritten English lead
    bl = str(out.get("bestLeadJa") or "")
    if bl and argus_news_i18n.looks_translatable(bl):
        out["bestLeadJa"] = _news_decorate(bl, "")["displayTitleJa"]
    return out


def _mover_cause_serve(rec, now_iso):
    """Read-time annotation on a COPY: freshness/staleness recomputed, market
    confirmation stale-stamped, explanation state resolved (cached/pending/
    not_generated). The store itself is never mutated by serving."""
    out = argus_mover_cause.annotate_freshness(json.loads(json.dumps(rec)), now_iso)
    try:
        if isinstance(out.get("marketConfirmation"), dict):
            out["marketConfirmation"] = argus_market_confirmation.annotate(
                out["marketConfirmation"], now_iso)
    except Exception:
        pass
    try:
        _mover_cause_decorate_candidates(out)            # Japanese-first candidate titles
    except Exception:
        pass
    if out.get("explanationJa"):
        out["explanationStatus"] = "cached"
    elif _mc_has_explain_request(out.get("symbol"), out.get("market")):
        out["explanationStatus"] = "queued"          # V11.5.2: owner requested, awaiting cron
    else:
        out["explanationStatus"] = ("pending" if (out.get("refreshPolicy") or {}).get("eligibleForAiExplain")
                                    and _MC_AI_ENABLED else "not_generated")
    return out


def _mover_cause_items(direction="both", market="ALL", limit=30):
    _mover_causes_restore_once()
    now_iso = _ai_now_iso()
    # list() first: the cron refresh mutates the dict from another thread
    items = sorted(list(_MOVER_CAUSES.values()), key=lambda r: str(r.get("asOf")), reverse=True)
    if direction in ("up", "down"):
        items = [r for r in items if r.get("direction") == direction]
    if market in ("JP", "US"):
        items = [r for r in items if r.get("market") == market]
    return [_mover_cause_serve(r, now_iso) for r in items[:max(1, min(int(limit or 30), 100))]]


def _mover_causes_today():
    today = _ai_now_iso()[:10].replace("-", "")
    return [r for r in list(_MOVER_CAUSES.values())
            if str(r.get("moverCauseId", "")).endswith(today)]


@app.route("/api/argus/mover-causes")
def api_argus_mover_causes():
    """Public cache-only: the mover-cause ladder for recent sharp movers (both
    directions). Never calls LLM or providers; empty store = not_ready."""
    direction = (request.args.get("direction") or "both").lower()
    market = (request.args.get("market") or "ALL").upper()
    try:
        limit = int(request.args.get("limit") or 30)
    except Exception:
        limit = 30
    items = _mover_cause_items(direction, market, limit)
    return jsonify({"schemaVersion": argus_mover_cause.SCHEMA_VERSION,
                    "status": "live" if items else "not_ready",
                    "asOf": _ai_now_iso(), "count": len(items), "items": items,
                    "noteJa": "原因確定と有力候補を分離。連想・単一ソースは候補どまり。"
                              "急騰の追随買い推奨はしない。"})


@app.route("/api/argus/mover-causes/status")
def api_argus_mover_causes_status():
    _mover_causes_restore_once()
    todays = _mover_causes_today()
    counts = {"totalMovers": len(todays), "confirmedCause": 0, "probableCatalyst": 0,
              "candidateCatalyst": 0, "noLeadYet": 0}
    keymap = {"confirmed_cause": "confirmedCause", "probable_catalyst": "probableCatalyst",
              "candidate_catalyst": "candidateCatalyst", "no_lead_yet": "noLeadYet"}
    for r in todays:
        k = keymap.get(str(r.get("causeStatus")))
        if k:
            counts[k] += 1

    def _cov(ok, empty_ok=False):
        return "live" if ok else ("empty" if empty_ok else "missing")
    tdnet_ok = bool((_TDNET_OFFICIAL_CACHE.get("data") or _TDNET_FEED_CACHE.get("data")))
    jp_news_ok = any(it.get("sourceId") == "google_news_jp" for it in list(_INTEL_STORE)[:200])
    coverage = {
        "tdnet": _cov(tdnet_ok),
        "officialEvents": _cov(bool(_OFFICIAL_EVENTS), empty_ok=True),
        "jpNews": _cov(jp_news_ok),
        "companyNews": _cov(bool(_FINN_CACHE)),
        "caos": _cov(bool(_INTEL_STORE), empty_ok=True),
        "flow": _cov(any((_PUSHED_QUOTES.get(m) or {}) for m in ("JP", "US"))),
        "sectorPeer": "live",
    }
    all_unknown = counts["totalMovers"] > 0 and counts["noLeadYet"] == counts["totalMovers"]
    degraded = all_unknown and (tdnet_ok or jp_news_ok or bool(_FINN_CACHE))
    # v11.3.4 stricter diagnostics: staleness / market-confirmation gaps / SLA
    now_iso = _ai_now_iso()
    qs = argus_mover_cause_refresh.quality_and_sla(todays, now_iso)
    sla_breached = any(b.get("priority") == "urgent" for b in qs["sla"]["breaches"])
    diag = None
    if degraded:
        diag = ("cause attribution coverage failure suspected — "
                "情報源はliveなのに全件no_lead。取得/照合の不具合を疑う。")
    elif sla_breached:
        diag = "urgent moverの証拠が15分SLAを超過。refreshワークフローの稼働を確認。"
    elif counts["totalMovers"] > 0 and qs["quality"]["missingMarketConfirmationCount"] == counts["totalMovers"]:
        diag = "全moverで市場確認が未計算(致命的ではないが確定判定は保守化)。"
    return jsonify({"schemaVersion": "mover-cause-status-v1", "asOf": now_iso,
                    "counts": counts, "coverage": coverage,
                    "quality": qs["quality"], "sla": qs["sla"],
                    "degradedIfAllUnknown": bool(degraded),
                    "degraded": bool(degraded or sla_breached),
                    "diagnosticJa": diag,
                    "storeTotal": len(_MOVER_CAUSES),
                    "lastRefreshAt": _MOVER_CAUSES_STATE.get("lastRefreshAt"),
                    "pathType": _MOVER_CAUSES_STATE.get("pathType"),
                    "noteJa": "原因確定と有力候補を分離します。全件no_leadなら取得/接続不良として扱います。"})


@app.route("/api/argus/mover-causes/refresh-queue")
def api_argus_mover_causes_refresh_queue():
    """Public cache-only: which movers ARGUS will re-check next, in what order,
    within what budget. Built purely from stored records — never fetches."""
    now = time.time()
    if _MOVER_REFRESH_QUEUE["data"] is not None and now < _MOVER_REFRESH_QUEUE["expires"]:
        return jsonify(_MOVER_REFRESH_QUEUE["data"])
    _mover_causes_restore_once()
    out = argus_mover_cause_refresh.build_queue(
        _mover_causes_today(), _ai_now_iso(),
        max_ai_explain=_MC_AI_MAX_PER_RUN, ai_cooldown_min=_MC_AI_COOLDOWN_MIN,
        ai_min_abs_move=_MC_AI_MIN_ABS_MOVE, ai_enabled=_MC_AI_ENABLED)
    _MOVER_REFRESH_QUEUE["data"] = out
    _MOVER_REFRESH_QUEUE["expires"] = now + 300
    return jsonify(out)


@app.route("/api/argus/admin/mover-causes/refresh-queue/run", methods=["POST"])
def api_argus_admin_mover_causes_queue_run():
    """Admin/cron: execute the queue — evidence refresh for queued movers
    (providers allowed) + cached AI explanations for the budgeted top unresolved.
    Prompts/search traces are never stored or returned."""
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    _mover_causes_restore_once()
    ref = _refresh_mover_causes()                      # discover NEW movers from live feeds
    now_iso = _ai_now_iso()
    # transient owner boost — admin path only, never stored/served (privacy)
    owner_map = {}
    try:
        owner_map = {s: (v.get("ownerState") in ("held", "protected") or v.get("priority") == "high")
                     for s, v in _owner_symbols_cached().items()}
    except Exception:
        pass
    queue = argus_mover_cause_refresh.build_queue(
        _mover_causes_today(), now_iso,
        max_ai_explain=_MC_AI_MAX_PER_RUN, ai_cooldown_min=_MC_AI_COOLDOWN_MIN,
        ai_min_abs_move=_MC_AI_MIN_ABS_MOVE, ai_enabled=_MC_AI_ENABLED,
        owner_map=owner_map)
    # execute the REFRESH half of the queue: stored movers that faded out of the
    # live feeds (e.g. a morning -8% spike) would otherwise never clear their
    # SLA breach — _refresh_mover_causes only sweeps currently-visible movers.
    swept = {(m["market"], m["symbol"]) for m in _collect_active_movers()}
    requeued = 0
    for q in queue["queue"]:
        if not q.get("refreshNeeded") or (q["market"], q["symbol"]) in swept:
            continue
        if requeued >= queue["budget"]["maxProviderRefreshPerRun"]:
            break
        try:
            quote = _quote_cached_only(q["symbol"], q["market"]) or {}
            chg = quote.get("changePct", q.get("changePct"))
            rec = _mover_cause_for(q["symbol"], q["market"], chg,
                                   name=quote.get("nameJa") or quote.get("name"),
                                   direction=q.get("direction"), cached_only=False)
            merged = argus_mover_cause_store.merge_record(
                _MOVER_CAUSES.get(rec["moverCauseId"]), rec, now_iso=now_iso)
            if merged:
                _MOVER_CAUSES[merged["moverCauseId"]] = merged
                requeued += 1
        except Exception:
            continue
    explained, skipped = [], []
    for q in queue["queue"]:
        if not q.get("aiExplainNeeded"):
            continue
        try:
            done = _mover_ai_explain(q["symbol"], q["market"], now_iso)
            (explained if done else skipped).append(q["symbol"])
        except Exception:
            skipped.append(q["symbol"])
    _mover_causes_persist()
    _MOVER_REFRESH_QUEUE["data"] = None                # queue changed — recompute
    return jsonify({"ok": True, "refreshed": ref.get("refreshed"),
                    "requeuedRefreshed": requeued,
                    "aiExplained": explained, "aiSkipped": skipped,
                    "budget": queue["budget"], "asOf": now_iso})


@app.route("/api/argus/market-confirmation")
def api_argus_market_confirmation():
    """Public cache-only: Market Confirmation v1.5 for one symbol — computed
    purely from in-memory caches (quotes/push history/daily bars/peers)."""
    sym = (request.args.get("symbol") or "").strip().upper()
    if not sym:
        return jsonify({"error": "symbol required"}), 400
    mkt = (request.args.get("market") or "JP").upper()
    q = _quote_cached_only(sym, mkt) or {}
    chg = q.get("changePct")
    now_iso = _ai_now_iso()
    mc = argus_market_confirmation.compute(
        {"symbol": sym, "market": mkt, "changePct": chg},
        _market_confirmation_inputs(sym, mkt, chg), now_iso)
    mc.update({"symbol": sym, "market": mkt, "asOf": now_iso,
               "noteJa": "既存データによる市場確認v1.5。板/歩み値/borrowではない。"
                         "市場確認単独では原因を確定しない。"})
    return jsonify(mc)


@app.route("/api/argus/admin/market-confirmation/refresh", methods=["POST"])
def api_argus_admin_market_confirmation_refresh():
    """Admin: warm the JP daily-bar cache for requested symbols then recompute
    (the only fetching step in the market-confirmation layer)."""
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    body = request.get_json(silent=True) or {}
    syms = [str(s).upper() for s in (body.get("symbols") or [])][:10]
    warmed = []
    for s in syms:
        try:
            if s[:1].isdigit():
                _jq_price_history(s[:4])       # cached fetch (6h TTL)
            warmed.append(s)
        except Exception:
            continue
    return jsonify({"ok": True, "warmed": warmed, "asOf": _ai_now_iso()})


@app.route("/api/argus/mover-causes/snapshot")
def api_argus_mover_causes_snapshot():
    """Public-safe snapshot for the ledger workflow (metadata only)."""
    _mover_causes_restore_once()
    return jsonify(argus_mover_cause_store.serialize_snapshot(
        list(_MOVER_CAUSES.values()), as_of=_ai_now_iso()))


@app.route("/api/argus/mover-causes/<market>/<symbol>")
def api_argus_mover_cause_detail(market, symbol):
    """Public cache-only detail. Store hit → stored record; miss → an in-memory
    cached-evidence build (still no provider fetch / no LLM)."""
    _mover_causes_restore_once()
    symu, mkt = str(symbol).upper(), str(market).upper()
    now_iso = _ai_now_iso()
    rec = _MOVER_CAUSES.get(f"mc-{mkt}-{symu}-{now_iso[:10].replace('-', '')}")
    if rec is None:
        q = _quote_cached_only(symu, mkt) or {}
        rec = _mover_cause_for(symu, mkt, q.get("changePct"),
                               name=q.get("nameJa") or q.get("name"), cached_only=True)
        rec["computed"] = "cached_evidence_live"
    return jsonify(_mover_cause_serve(rec, now_iso))


@app.route("/api/argus/admin/mover-causes/refresh", methods=["POST"])
def api_argus_admin_mover_causes_refresh():
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    try:
        out = _refresh_mover_causes()
        _MOVER_REFRESH_QUEUE["data"] = None      # store changed — queue must recompute
        return jsonify(out)
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {str(e)[:160]}"}), 500


def _mover_ai_explain(symbol, market, now_iso, force=False):
    """One budgeted AI explanation for a mover-cause record (ADMIN PATHS ONLY —
    the single LLM call in the mover-cause layer). Prompt is built from the
    ladder's own candidates + missing confirmations; the prompt itself is never
    stored. Cooldown-guarded. Returns True when a cached explanation was stored."""
    if not _MC_AI_ENABLED:
        return False
    symu, mkt = str(symbol).upper(), str(market).upper()
    today = now_iso[:10].replace("-", "")
    mid = f"mc-{mkt}-{symu}-{today}"
    rec = _MOVER_CAUSES.get(mid)
    if rec is None:
        q = _quote_cached_only(symu, mkt) or {}
        rec = _mover_cause_for(symu, mkt, q.get("changePct"),
                               name=q.get("nameJa") or q.get("name"), cached_only=False)
    if not force and argus_mover_cause_refresh._cooldown_active(rec, now_iso, _MC_AI_COOLDOWN_MIN):
        return False
    cands = "\n".join(
        f"- {c.get('titleJa')} [{c.get('category')}/{c.get('timingRelation')}/{c.get('corroborationLevel')}]"
        for c in (rec.get("causeCandidates") or [])[:5]) or "(候補なし)"
    missing = "・".join(rec.get("missingConfirmations") or []) or "(なし)"
    prof = _ENTITY_PROFILES.get(symu, {})
    pct = rec.get("changePct")
    pcts = f"{pct:+.1f}%" if isinstance(pct, (int, float)) else "大きく"
    user = (f"{rec.get('name') or symu}({symu}・{'日本株' if mkt == 'JP' else '米国株'})が本日{pcts}動いた。"
            "最新ニュースを調べ、以下のARGUS側の候補と突き合わせて原因を日本語で説明して。\n"
            f"ARGUSの現在の判定: {rec.get('causeStatusJa')}\n候補:\n{cands}\n"
            f"不足している確認: {missing}\n"
            f"事業: {prof.get('businessJa') or '(不明)'}\n"
            "新しい情報が見つからなければ「新規情報なし」と正直に言う。推測は『可能性』と明示。"
            "投資助言はしない。\n"
            "出力はSTRICT JSONのみ: {\"explanationJa\": \"3〜4文の説明\", "
            "\"unverifiedAssumptions\": [\"未検証の仮定(0〜3件)\"]}")
    txt = _openai_research(user)
    if not txt:
        return False
    parsed = safe_json(txt)
    expl = (str(parsed.get("explanationJa"))[:700] if isinstance(parsed, dict)
            and parsed.get("explanationJa") else txt.strip()[:700])
    ua = ([str(x)[:120] for x in parsed.get("unverifiedAssumptions") or []][:3]
          if isinstance(parsed, dict) else [])
    rec["explanationJa"] = expl
    rec["explanationGeneratedAt"] = now_iso
    rec["explanationStatus"] = "cached"
    rec["unverifiedAssumptions"] = ua
    # deterministic confirm/refute conditions from the ladder itself (no AI needed)
    rec["whatWouldConfirmJa"] = ("・".join(rec.get("missingConfirmations") or [])[:200]
                                 or "公式開示/複数ソースと市場反応の一致")
    rec["whatWouldRefuteJa"] = "同業・指数全体の動きで説明できる場合、または候補材料の否定・訂正報道。"
    fr = rec.get("freshness") or {}
    fr["lastAiExplainAt"] = now_iso
    rec["freshness"] = fr
    rp = rec.get("refreshPolicy") or {}
    rp["aiExplainCooldownUntil"] = datetime.fromtimestamp(
        time.time() + _MC_AI_COOLDOWN_MIN * 60, pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rec["refreshPolicy"] = rp
    _MOVER_CAUSES[mid] = argus_mover_cause_store.merge_record(
        _MOVER_CAUSES.get(mid), rec, now_iso=now_iso)
    _MOVER_CAUSES_STATE["lastExplainAt"] = now_iso
    return True


@app.route("/api/argus/admin/mover-causes/explain", methods=["POST"])
def api_argus_admin_mover_causes_explain():
    """Admin-only AI explanation for top unresolved movers (budgeted). Results
    are cached into the store and served by public GETs. Cooldown-guarded;
    prompts/search traces are never stored or exposed."""
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    body = request.get_json(silent=True) or {}
    syms = [str(s).upper() for s in (body.get("symbols") or [])][:_MC_AI_MAX_PER_RUN]
    market = str(body.get("market") or "JP").upper()
    mx = min(int(body.get("max") or _MC_AI_MAX_PER_RUN), _MC_AI_MAX_PER_RUN)
    _mover_causes_restore_once()
    now_iso = _ai_now_iso()
    if not syms:
        queue = argus_mover_cause_refresh.build_queue(
            _mover_causes_today(), now_iso, max_ai_explain=mx,
            ai_cooldown_min=_MC_AI_COOLDOWN_MIN, ai_min_abs_move=_MC_AI_MIN_ABS_MOVE,
            ai_enabled=_MC_AI_ENABLED)
        pairs = [(q["symbol"], q["market"]) for q in queue["queue"] if q.get("aiExplainNeeded")][:mx]
        force = False
    else:
        pairs = [(s, market) for s in syms[:mx]]
        force = True                            # explicit owner request bypasses cooldown
    generated, skipped = [], []
    for sym, mkt in pairs:
        try:
            (generated if _mover_ai_explain(sym, mkt, now_iso, force=force)
             else skipped).append(sym)
        except Exception:
            skipped.append(sym)
    _mover_causes_persist()
    _MOVER_REFRESH_QUEUE["data"] = None
    return jsonify({"ok": True, "generated": generated, "skipped": skipped,
                    "budgetMax": mx, "asOf": now_iso})


@app.route("/api/argus/mover-causes/explain-request", methods=["POST"])
def api_argus_mover_causes_explain_request():
    """PUBLIC, enqueue-only. The owner clicks 「理由を詳しく調べる」 → this records a
    request the admin/cron explain run drains. It NEVER calls an LLM or a provider.
    Deduped by symbol+market; throttled per IP+symbol. Returns cached_available when a
    cached explanation already exists (nothing to queue)."""
    _mover_causes_restore_once()
    _mc_explain_req_restore_once()
    body = request.get_json(silent=True) or {}
    sym = (str(body.get("symbol") or "").strip().upper())[:16]
    mkt = (str(body.get("market") or "JP").strip().upper())[:4]
    ctx = str(body.get("context") or "")[:40]
    now_iso = _ai_now_iso()
    base = {"schemaVersion": "mover-explain-request-v1", "symbol": sym, "market": mkt}
    if not sym or mkt not in ("JP", "US") or not re.match(r"^[A-Z0-9._-]{1,10}$", sym):
        return jsonify({**base, "ok": False, "status": "invalid", "queuedAt": None,
                        "nextRunHintJa": "", "messageJa": "銘柄コードまたは市場が不正です。"}), 200
    # already cached → no need to queue
    today = now_iso[:10].replace("-", "")
    mc = _MOVER_CAUSES.get(f"mc-{mkt}-{sym}-{today}")
    if mc and mc.get("explanationJa"):
        return jsonify({**base, "ok": True, "status": "cached_available", "queuedAt": None,
                        "nextRunHintJa": "既にAI解説があります。",
                        "messageJa": "この銘柄のAI解説は生成済みです。カードで開けます。"}), 200
    # dedupe first (idempotent — cheap, no LLM), so a re-click reads already_queued
    if _mc_has_explain_request(sym, mkt):
        _mc_explain_req_add(sym, mkt, ctx, now_iso)     # bump count/lastAt
        _mc_explain_req_persist()
        return jsonify({**base, "ok": True, "status": "already_queued", "queuedAt": now_iso,
                        "nextRunHintJa": "次回の自動生成(約15分間隔)で反映されます。",
                        "messageJa": "既に調査リクエスト済みです。"}), 200
    # per-IP+symbol throttle for genuinely new requests (global limiter also applies)
    ip = _client_meta().get("ip") or ""
    rlk = f"{ip}|{mkt}:{sym}"
    nowt = time.time()
    if nowt - float(_MC_EXPLAIN_REQ_RL.get(rlk, 0.0)) < _MC_EXPLAIN_REQ_RL_SEC:
        return jsonify({**base, "ok": True, "status": "rate_limited", "queuedAt": None,
                        "nextRunHintJa": "少し待って再度お試しください。",
                        "messageJa": "リクエストが多すぎます。少し待ってから再度お試しください。"}), 200
    _MC_EXPLAIN_REQ_RL[rlk] = nowt
    if len(_MC_EXPLAIN_REQ_RL) > 2000:
        _MC_EXPLAIN_REQ_RL.clear()
    status = _mc_explain_req_add(sym, mkt, ctx, now_iso)
    _mc_explain_req_persist()
    return jsonify({**base, "ok": True, "status": status, "queuedAt": now_iso,
                    "nextRunHintJa": "次回の自動生成(約15分間隔)で反映されます。",
                    "messageJa": "調査リクエストを受け付けました。公開画面からAIは起動せず、"
                                 "管理側の定期生成で処理します。"}), 200


@app.route("/api/argus/admin/mover-causes/explain/run", methods=["POST"])
def api_argus_admin_mover_causes_explain_run():
    """Admin/cron: drain owner explanation requests FIRST, then the priority queue's
    budgeted top-unresolved movers. Respects the existing max-per-run + cooldown.
    May call AI. Stores explanationJa safely — no prompts/search traces persisted."""
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    _mover_causes_restore_once()
    _mc_explain_req_restore_once()
    now_iso = _ai_now_iso()
    body = request.get_json(silent=True) or {}
    mx = min(int(body.get("max") or _MC_AI_MAX_PER_RUN), _MC_AI_MAX_PER_RUN)
    force_req = bool(body.get("force"))            # owner-requested items may bypass cooldown
    generated, skipped, drained_reqs = [], [], []
    # 1) owner requests first (oldest first), within budget
    req_keys = sorted(_MC_EXPLAIN_REQUESTS,
                      key=lambda k: str(_MC_EXPLAIN_REQUESTS[k].get("firstAt")))
    for key in req_keys:
        if len(generated) >= mx:
            break
        e = _MC_EXPLAIN_REQUESTS.get(key) or {}
        sym, mkt = e.get("symbol"), e.get("market")
        if not sym or not mkt:
            _MC_EXPLAIN_REQUESTS.pop(key, None)
            continue
        try:
            done = _mover_ai_explain(sym, mkt, now_iso, force=force_req)
        except Exception:
            done = False
        (generated if done else skipped).append(sym)
        # drain the request once it's generated (or already cached); leave it queued only
        # if it was skipped purely by cooldown so the next run retries it.
        mc = _MOVER_CAUSES.get(f"mc-{mkt}-{sym}-{now_iso[:10].replace('-', '')}")
        if done or (mc and mc.get("explanationJa")):
            _MC_EXPLAIN_REQUESTS.pop(key, None)
            drained_reqs.append(sym)
    # 2) then the standard priority queue for remaining budget
    if len(generated) < mx:
        queue = argus_mover_cause_refresh.build_queue(
            _mover_causes_today(), now_iso, max_ai_explain=mx,
            ai_cooldown_min=_MC_AI_COOLDOWN_MIN, ai_min_abs_move=_MC_AI_MIN_ABS_MOVE,
            ai_enabled=_MC_AI_ENABLED)
        for q in queue["queue"]:
            if len(generated) >= mx:
                break
            if not q.get("aiExplainNeeded"):
                continue
            s, m = q["symbol"], q["market"]
            if s in generated or s in skipped:
                continue
            try:
                (generated if _mover_ai_explain(s, m, now_iso) else skipped).append(s)
            except Exception:
                skipped.append(s)
    _MC_EXPLAIN_REQ_STATE["lastDrainAt"] = now_iso
    _MC_EXPLAIN_REQ_STATE["lastDrainCount"] = len(drained_reqs)
    _mover_causes_persist()
    _mc_explain_req_persist()
    _MOVER_REFRESH_QUEUE["data"] = None
    return jsonify({"ok": True, "schemaVersion": "mover-explain-run-v1",
                    "generated": generated, "skipped": skipped,
                    "drainedRequests": drained_reqs, "budgetMax": mx,
                    "requestsRemaining": len(_MC_EXPLAIN_REQUESTS), "asOf": now_iso})


# ━━━ V11.4.0 Learning Memory ━━━
# ARGUS's own public-safe history → small auditable cohort lessons that flow back
# into the Evidence Pack / AI prompt as CAUTION/CONTEXT. Not fine-tuning, not
# auto-trading. Public GET reads only cached/ledger-derived memory (no LLM, no
# provider fetch). Admin build reads public-safe ledger snapshots (no LLM in v1).
_LEARNING_MEMORY = {"doc": None}                # single aggregate document
_LEARNING_MEMORY_FILE = "/tmp/argus_learning_memory.json"
_LEARNING_MEMORY_STATE = {"restored": False, "lastBuildAt": None, "lastRestoreAt": None,
                          "status": "not_ready", "pathType": "ephemeral_tmp"}


def _learning_memory_persist():
    try:
        with open(_LEARNING_MEMORY_FILE, "w") as f:
            json.dump({"doc": _LEARNING_MEMORY["doc"],
                       "state": {k: _LEARNING_MEMORY_STATE[k]
                                 for k in ("lastBuildAt", "lastRestoreAt", "status")}},
                      f, ensure_ascii=False, default=str)
    except Exception:
        pass


def _learning_memory_restore_once():
    """tmp → ledger latest (merge; counts never shrink) → empty."""
    if _LEARNING_MEMORY_STATE["restored"]:
        return
    _LEARNING_MEMORY_STATE["restored"] = True
    try:
        with open(_LEARNING_MEMORY_FILE) as f:
            blob = json.load(f)
        _LEARNING_MEMORY_STATE.update({k: v for k, v in (blob.get("state") or {}).items()
                                       if k in ("lastBuildAt", "lastRestoreAt", "status")})
        if isinstance(blob.get("doc"), dict):
            _LEARNING_MEMORY["doc"] = blob["doc"]
            _LEARNING_MEMORY_STATE["pathType"] = "durable_restored"
            return
    except Exception:
        pass
    try:
        r = requests.get(f"{_LEDGER_RAW_BASE}/learning-memory/latest.json?cb={int(time.time())}",
                         timeout=6)
        if r.status_code == 200 and r.text.strip().startswith("{"):
            restored = argus_learning_memory_store.restore_from_snapshot(json.loads(r.text))
            if restored:
                _LEARNING_MEMORY["doc"] = argus_learning_memory_store.merge_memory(
                    _LEARNING_MEMORY["doc"], restored, now_iso=_ai_now_iso())
                _LEARNING_MEMORY_STATE["pathType"] = "ledger_restored"
                _LEARNING_MEMORY_STATE["lastRestoreAt"] = _ai_now_iso()
    except Exception:
        pass


def _lm_official_event_observations():
    """Official events → outcome observations. Resolution is decided ONLY by the
    lifecycle's TERMINAL causeStatus (argus_official_event_lifecycle):
      confirmed_cause = hit; not_cause = miss (reaction observed but causation
      disproved); everything else — including probable_catalyst — is STILL PENDING
      (the lifecycle's own 'unknown is acceptable' state) and must never be scored.
    Non-material (fact_only) disclosures are context, not scored."""
    obs = []
    try:
        _official_events_restore_once()
        for r in list(_OFFICIAL_EVENTS.values()):
            if not r.get("material"):
                continue
            mkt = str(r.get("market") or "").upper() or None
            cat = r.get("category") or "other"
            cause = str(r.get("causeStatus") or "")
            if cause == "confirmed_cause":
                outcome, pending = "hit", False
            elif cause == "not_cause":
                outcome, pending = "miss", False
            else:
                outcome, pending = None, True     # probable_catalyst / classified = pending
            for ct, ck in (("eventType", cat), ("market", mkt)):
                if ck:
                    obs.append({"cohortType": ct, "cohortKey": ck,
                                "outcome": outcome, "pending": pending})
    except Exception:
        pass
    return obs


def _lm_macro_observations():
    """Macro pre/post → macroEventCode outcome. Scored only when post.verdict is
    hit/partial/miss; not_scoreable / no post = pending."""
    obs = []
    try:
        for r in list(_MACRO_ANALYSIS.values()):
            code = r.get("eventCode")
            if not code:
                continue
            verdict = str((r.get("post") or {}).get("verdict") or "")
            if verdict in ("hit", "partial", "miss"):
                obs.append({"cohortType": "macroEventCode", "cohortKey": code,
                            "outcome": verdict, "pending": False})
            else:
                obs.append({"cohortType": "macroEventCode", "cohortKey": code,
                            "outcome": None, "pending": True})
    except Exception:
        pass
    return obs


def _lm_mover_cause_observations():
    """Mover causes → sourceFamily / sourceTier / causeCategory outcomes for the TOP
    candidate. A resolved mover (confirmed_cause + market-confirmed) = hit for its top
    candidate's family; a stale unresolved candidate/no_lead = miss; still fresh = pending.
    Conservative: only the top candidate contributes (no per-candidate double counting)."""
    obs = []
    try:
        _mover_causes_restore_once()
        for r in list(_MOVER_CAUSES.values()):
            cands = r.get("causeCandidates") or []
            if not cands:
                continue
            top = cands[0]
            status = str(r.get("causeStatus") or "")
            mc = (r.get("marketConfirmation") or {}).get("status")
            stale = bool((r.get("freshness") or {}).get("isStale"))
            if status == "confirmed_cause" and mc == "confirmed":
                outcome, pending = "hit", False
            elif status in ("candidate_catalyst", "no_lead_yet") and stale:
                outcome, pending = "miss", False
            else:
                outcome, pending = None, True
            keys = [("causeCategory", top.get("category")),
                    ("sourceFamily", top.get("sourceFamily")),
                    ("sourceTier", top.get("sourceTier"))]
            for ct, ck in keys:
                if ck:
                    obs.append({"cohortType": ct, "cohortKey": str(ck),
                                "outcome": outcome, "pending": pending})
    except Exception:
        pass
    return obs


def _lm_visibility_observations():
    """Visibility downgrade reason codes → visibilityReason cohort. Without Decision
    Value outcome linkage these stay pending (recorded, not scored) — honest: we
    don't yet know if a downgrade was 'useful'."""
    obs = []
    try:
        vg = _visibility_guard_cached_only() or {}
        for code in (vg.get("reasonCodes") or []):
            obs.append({"cohortType": "visibilityReason", "cohortKey": str(code),
                        "outcome": None, "pending": True})
    except Exception:
        pass
    return obs


def _build_learning_memory_inputs(cached_only=True):
    """Assemble public-safe observations + context from cached/ledger data ONLY.
    Reads only public stores/ledger artifacts — never private Layer2B raw records,
    never a paid provider, never an LLM."""
    official = _lm_official_event_observations()
    macro = _lm_macro_observations()
    mover = _lm_mover_cause_observations()
    visibility = _lm_visibility_observations()
    observations = official + macro + mover + visibility

    def _scored(lst):
        return sum(1 for o in lst if not o.get("pending")
                   and o.get("outcome") in ("hit", "partial", "miss"))

    # context (calibration / decision-value stages — hints only, never outcome cohorts)
    try:
        dv = _dv_status_public_dict()
    except Exception:
        dv = {}
    try:
        v4 = _calibration_v4_summary() or {}
        cal = {"nScored": v4.get("nScored") or v4.get("scored") or 0,
               "nPredictions": v4.get("nPredictions") or v4.get("n") or 0}
    except Exception:
        cal = {}
    counts = {
        "officialEvents": _scored(official),
        "macroEvents": _scored(macro),
        "moverCauses": _scored(mover),
        "decisionValue": int(dv.get("scoredCount") or 0),
        "calibration": int(cal.get("nScored") or 0),
    }
    context = {"decisionValue": {"phase": dv.get("phase"), "sampleStage": dv.get("sampleStage"),
                                 "totalRecords": dv.get("totalRecords")},
               "calibration": cal, "sampleCounts": counts}
    return observations, context


def _learning_memory_build(persist=True):
    """Admin/cron: rebuild the aggregate from public-safe snapshots. No LLM."""
    _learning_memory_restore_once()
    now_iso = _ai_now_iso()
    observations, context = _build_learning_memory_inputs(cached_only=True)
    doc = argus_learning_memory.build_memory(observations, context=context, now_iso=now_iso)
    # merge so a sparse rebuild never shrinks accumulated counts
    _LEARNING_MEMORY["doc"] = argus_learning_memory_store.merge_memory(
        _LEARNING_MEMORY["doc"], doc, now_iso=now_iso)
    _LEARNING_MEMORY_STATE.update(lastBuildAt=now_iso, status="ready")
    if persist:
        _learning_memory_persist()
    return _LEARNING_MEMORY["doc"]


def _learning_memory_doc():
    """The current memory doc (restore-once; empty-none if never built)."""
    _learning_memory_restore_once()
    return _LEARNING_MEMORY["doc"] or argus_learning_memory.build_memory([], now_iso=_ai_now_iso())


def _learning_memory_compact_for_symbol(symbol, market):
    """Compact, symbol/context-relevant memory slice for the Evidence Pack. Pure
    read of the in-memory doc — cached-only, never triggers a build."""
    try:
        doc = _learning_memory_doc()
        cause_cats, src_families = set(), set()
        today = _ai_now_iso()[:10].replace("-", "")
        rec = _MOVER_CAUSES.get(f"mc-{str(market).upper()}-{str(symbol).upper()}-{today}")
        for c in ((rec or {}).get("causeCandidates") or [])[:3]:
            if c.get("category"):
                cause_cats.add(str(c["category"]))
            if c.get("sourceFamily"):
                src_families.add(str(c["sourceFamily"]))
        macro_codes = {r.get("eventCode") for r in list(_MACRO_ANALYSIS.values())
                       if r.get("eventCode")}
        return argus_learning_memory.compact_for_evidence(
            doc, symbol=str(symbol).upper(), market=str(market).upper(),
            cause_categories=cause_cats, macro_codes=macro_codes,
            source_families=src_families)
    except Exception:
        return None


@app.route("/api/argus/learning-memory")
def api_argus_learning_memory():
    """Public cache-only: ARGUS's auditable Learning Memory. Never calls LLM,
    never fetches a provider — reads the in-memory / ledger-restored doc only."""
    doc = _learning_memory_doc()
    cohort_type = (request.args.get("cohortType") or "").strip()
    market = (request.args.get("market") or "").strip().upper()
    symbol = (request.args.get("symbol") or "").strip().upper()
    try:
        limit = int(request.args.get("limit") or 60)
    except Exception:
        limit = 60
    lessons = list(doc.get("lessons") or [])
    if cohort_type:
        lessons = [L for L in lessons if L.get("cohortType") == cohort_type]
    if market:
        lessons = [L for L in lessons if not (L.get("cohortType") == "market")
                   or L.get("cohortKey") == market]
    if symbol:
        lessons = [L for L in lessons if not (L.get("cohortType") == "symbol")
                   or str(L.get("cohortKey")).upper() == symbol]
    out = dict(doc)
    out["lessons"] = lessons[:max(1, min(limit, 120))]
    out["status"] = _LEARNING_MEMORY_STATE.get("status", "ready" if doc.get("lessons") else "not_ready")
    return jsonify(out)


@app.route("/api/argus/learning-memory/status")
def api_argus_learning_memory_status():
    doc = _learning_memory_doc()
    counts = doc.get("counts") or {}
    stage = doc.get("sampleStage") or "none"
    status = _LEARNING_MEMORY_STATE.get("status")
    if not status or status == "not_ready":
        status = "ready" if doc.get("lessons") else "not_ready"
    # ledger meta (restore availability) — cached-only read of ARGUS's own artifact
    ledger = {"restoreAvailable": False, "latestDate": None, "latestCount": 0}
    try:
        r = requests.get(f"{_LEDGER_RAW_BASE}/learning-memory/latest.json?cb={int(time.time())}",
                         timeout=6)
        if r.status_code == 200 and r.text.strip().startswith("{"):
            snap = json.loads(r.text)
            ledger = {"restoreAvailable": True, "latestDate": str(snap.get("asOf") or "")[:10],
                      "latestCount": int((snap.get("summary") or {}).get("lessons", 0))}
    except Exception:
        pass
    return jsonify({
        "schemaVersion": "learning-memory-status-v1",
        "asOf": _ai_now_iso(),
        "status": status,
        "sampleStage": stage,
        "counts": {
            "lessons": int(counts.get("lessons", 0)),
            "usableLessons": int(counts.get("usableLessons", 0)),
            "burnInLessons": int(counts.get("burnInLessons", 0)),
            "officialEventSamples": int(counts.get("officialEventSamples", 0)),
            "macroEventSamples": int(counts.get("macroEventSamples", 0)),
            "moverCauseSamples": int(counts.get("moverCauseSamples", 0)),
            "decisionValueSamples": int(counts.get("decisionValueSamples", 0)),
            "calibrationSamples": int(counts.get("calibrationSamples", 0)),
        },
        "lastBuildAt": _LEARNING_MEMORY_STATE.get("lastBuildAt"),
        "lastRestoreAt": _LEARNING_MEMORY_STATE.get("lastRestoreAt"),
        "ledger": ledger,
        "pathType": _LEARNING_MEMORY_STATE.get("pathType"),
        "limitationsJa": doc.get("limitationsJa") or [],
    })


@app.route("/api/argus/learning-memory/lesson/<lesson_id>")
def api_argus_learning_memory_lesson(lesson_id):
    doc = _learning_memory_doc()
    for L in (doc.get("lessons") or []):
        if str(L.get("lessonId")) == str(lesson_id):
            return jsonify(L)
    return jsonify({"error": "not_found", "lessonId": lesson_id}), 404


@app.route("/api/argus/learning-memory/snapshot")
def api_argus_learning_memory_snapshot():
    """Public-safe snapshot for the ledger workflow (metadata only, no secrets)."""
    return jsonify(argus_learning_memory_store.serialize_snapshot(
        _learning_memory_doc(), as_of=_ai_now_iso()))


@app.route("/api/argus/admin/learning-memory/build", methods=["POST"])
def api_argus_admin_learning_memory_build():
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    try:
        doc = _learning_memory_build()
        return jsonify({"ok": True, "sampleStage": doc.get("sampleStage"),
                        "counts": doc.get("counts"), "asOf": _ai_now_iso()})
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {str(e)[:160]}"}), 500


@app.route("/api/argus/admin/learning-memory/restore", methods=["POST"])
def api_argus_admin_learning_memory_restore():
    """Admin: force a merge-restore from the ledger snapshot (never wipes)."""
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    try:
        r = requests.get(f"{_LEDGER_RAW_BASE}/learning-memory/latest.json?cb={int(time.time())}",
                         timeout=8)
        restored = None
        if r.status_code == 200 and r.text.strip().startswith("{"):
            restored = argus_learning_memory_store.restore_from_snapshot(json.loads(r.text))
        if restored:
            _LEARNING_MEMORY["doc"] = argus_learning_memory_store.merge_memory(
                _LEARNING_MEMORY["doc"], restored, now_iso=_ai_now_iso())
            _LEARNING_MEMORY_STATE.update(lastRestoreAt=_ai_now_iso(), status="ready")
            _learning_memory_persist()
            return jsonify({"ok": True, "restored": True,
                            "sampleStage": _LEARNING_MEMORY["doc"].get("sampleStage")})
        return jsonify({"ok": True, "restored": False, "reason": "no_ledger_snapshot"})
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {str(e)[:160]}"}), 500


_ATTRIB_HIST_CACHE = {"data": None, "expires": 0.0}


@app.route("/api/argus/attribution-history")
def api_argus_attribution_history():
    now = time.time()
    if _ATTRIB_HIST_CACHE["data"] and now < _ATTRIB_HIST_CACHE["expires"]:
        return jsonify(_ATTRIB_HIST_CACHE["data"])
    out = {"status": "empty", "asOf": _ai_now_iso(), "days": [], "count": 0,
           "noteJa": "原因アトリビューションの記録(毎営業日16:05・後日結果と照合)。"}
    try:
        r = requests.get("https://api.github.com/repos/mitsugue/argus/contents/ledger/attribution?ref=ledger",
                         timeout=12, headers={"User-Agent": "argus/1.0", "Accept": "application/vnd.github+json"})
        if r.ok:
            files = [f for f in r.json() if isinstance(f, dict)
                     and str(f.get("name", "")).endswith(".json") and f.get("name") != "latest.json"]
            days = sorted((f["name"][:-5] for f in files), reverse=True)[:30]
            out["days"] = days
            out["count"] = len(days)
            out["status"] = "live" if days else "empty"
        latest = _gh_ledger_json("attribution/latest.json")
        if latest:
            out["latest"] = latest
    except Exception:
        pass
    if out["status"] == "live":
        _ATTRIB_HIST_CACHE["data"] = out
        _ATTRIB_HIST_CACHE["expires"] = now + 1800
    return jsonify(out)


# Incident Replay (v10.108): list the dates with a recorded downside snapshot
# (written daily to the public ledger branch) + the latest. Public, read-only.
_DOWNSIDE_HIST_CACHE = {"data": None, "expires": 0.0}


@app.route("/api/argus/downside-history")
def api_argus_downside_history():
    now = time.time()
    if _DOWNSIDE_HIST_CACHE["data"] and now < _DOWNSIDE_HIST_CACHE["expires"]:
        return jsonify(_DOWNSIDE_HIST_CACHE["data"])
    out = {"status": "empty", "asOf": _ai_now_iso(), "days": [], "count": 0,
           "noteJa": "急落インシデントの記録(replay用・毎営業日16:05にledgerへ追記)。"}
    try:
        r = requests.get("https://api.github.com/repos/mitsugue/argus/contents/ledger/downside?ref=ledger",
                         timeout=12, headers={"User-Agent": "argus/1.0", "Accept": "application/vnd.github+json"})
        if r.ok:
            files = [f for f in r.json() if isinstance(f, dict)
                     and str(f.get("name", "")).endswith(".json") and f.get("name") != "latest.json"]
            days = sorted((f["name"][:-5] for f in files), reverse=True)[:30]
            out["days"] = days
            out["count"] = len(days)
            out["status"] = "live" if days else "empty"
        latest = requests.get("https://raw.githubusercontent.com/mitsugue/argus/ledger/ledger/downside/latest.json",
                              timeout=10, headers={"User-Agent": "argus/1.0"})
        if latest.ok:
            out["latest"] = latest.json()
    except Exception:
        pass
    if out["status"] == "live":
        _DOWNSIDE_HIST_CACHE["data"] = out
        _DOWNSIDE_HIST_CACHE["expires"] = now + 1800
    return jsonify(out)


# Capital-rotation history + Δ (v10.109): recorded daily readings let us answer
# "where did money leave since the last reading?". Public, read-only.
_ROTATION_HIST_CACHE = {"data": None, "expires": 0.0}


def _gh_ledger_json(path):
    r = requests.get(f"https://raw.githubusercontent.com/mitsugue/argus/ledger/ledger/{path}",
                     timeout=10, headers={"User-Agent": "argus/1.0"})
    return r.json() if r.ok else None


@app.route("/api/argus/rotation-history")
def api_argus_rotation_history():
    now = time.time()
    if _ROTATION_HIST_CACHE["data"] and now < _ROTATION_HIST_CACHE["expires"]:
        return jsonify(_ROTATION_HIST_CACHE["data"])
    out = {"status": "empty", "asOf": _ai_now_iso(), "days": [], "count": 0, "delta": [],
           "noteJa": "資金ローテーションの記録(毎営業日16:05にledgerへ追記)。Δ=前回記録比のスコア変化。"}
    try:
        r = requests.get("https://api.github.com/repos/mitsugue/argus/contents/ledger/rotations?ref=ledger",
                         timeout=12, headers={"User-Agent": "argus/1.0", "Accept": "application/vnd.github+json"})
        if r.ok:
            files = [f for f in r.json() if isinstance(f, dict)
                     and str(f.get("name", "")).endswith(".json") and f.get("name") != "latest.json"]
            days = sorted((f["name"][:-5] for f in files), reverse=True)[:30]
            out["days"] = days
            out["count"] = len(days)
            out["status"] = "live" if days else "empty"
            # Δ between the two most recent recorded readings (where money left).
            if len(days) >= 2:
                cur = _gh_ledger_json(f"rotations/{days[0]}.json") or {}
                prev = _gh_ledger_json(f"rotations/{days[1]}.json") or {}
                prev_scores = {g.get("id"): g.get("score") for g in (prev.get("groups") or [])}
                delta = []
                for g in (cur.get("groups") or []):
                    ps = prev_scores.get(g.get("id"))
                    if isinstance(g.get("score"), (int, float)) and isinstance(ps, (int, float)):
                        delta.append({"id": g.get("id"), "label": g.get("label"),
                                      "score": round(g["score"], 3), "delta": round(g["score"] - ps, 3),
                                      "status": g.get("status")})
                delta.sort(key=lambda x: x["delta"])   # most outflow first
                out["delta"] = delta
                out["deltaFrom"] = days[1]
                out["latest"] = {"date": days[0], "regime": cur.get("regime")}
    except Exception:
        pass
    if out["status"] == "live":
        _ROTATION_HIST_CACHE["data"] = out
        _ROTATION_HIST_CACHE["expires"] = now + 1800
    return jsonify(out)


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
    # v10.202 durability fix: persist the ciphertext IMMEDIATELY to the owner-private
    # repo. The old design only held it in memory until a daily workflow drained it —
    # but a deploy/restart wiped the slot first, so backups often never reached git
    # (root cause of "no cloud backup found"). Ciphertext + passphrase-derived id →
    # safe to store; the daily ledger commit still runs as a second copy.
    durable = False
    try:
        if _layer2b_store_configured():
            import json as _json
            durable = bool(_gh_private_put(f"vault/{vid}.json",
                                           _json.dumps({"blob": blob, "ts": time.time()}),
                                           "vault backup (client-encrypted)", overwrite=True))
    except Exception:
        durable = False
    return jsonify({"ok": True, "queued": len(_VAULT_SLOTS), "durable": durable,
                    "noteJa": ("暗号化バックアップを保存しました(即時・端末退避でも復元可)。"
                               if durable else "受領。次回の台帳ラン(平日16:05)でクラウドに保存されます。")})

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
    if s:
        return jsonify({"ts": s["ts"], "blob": s["blob"]})
    # v10.202: fall back to the durable private-repo copy when the in-memory slot was
    # lost to a restart. This is what makes "restore after the device was evicted"
    # actually work. The vault id is passphrase-derived + unguessable; ciphertext only.
    try:
        if _layer2b_store_configured():
            import json as _json
            content, _sha = _gh_private_get(f"vault/{vid}.json")
            if content:
                d = _json.loads(content)
                if d.get("blob"):
                    return jsonify({"ts": d.get("ts"), "blob": d["blob"], "source": "durable"})
    except Exception:
        pass
    return jsonify({"error": "not_found"}), 404

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
         "usedFor": ["realtime-quotes", "flow"],   # L2/VWAP NOT live — see source-registry
         "lastKnownStatus": (f"last push {int(_push_last_age_sec())}s ago"
                             if _push_last_age_sec() is not None else None),
         "notesJa": "ローカルOpenD→quote-pushブリッジ経由のリアルタイム価格+大口フロー。"
                    "板(L2)/VWAPは未対応(source-registry参照)。push途絶時はJ-Quants/Twelve Dataへ自動フォールバック。"},
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

# ── Source Capability Registry (source-registry-v1, v10.47) ──────────────────
# One honest, capability-LEVEL view of every data source: a provider being
# configured does NOT mean a capability is live. Statuses: confirmed_live /
# confirmed_delayed / partial / requires_test / paid_not_enabled / licence_unclear
# / unavailable / missing. Capabilities ARGUS does not actually have (PTS, L2,
# tape, VWAP, TDnet/EDINET, FX/futures/commodities) are listed unavailable so the
# UI / LLM can never over-claim them.
def _coerce_epoch(ex):
    """exchangeTs may be epoch seconds or an ISO/space string → epoch float|None."""
    if isinstance(ex, (int, float)) and not isinstance(ex, bool):
        return float(ex)
    if isinstance(ex, str) and ex:
        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(ex, fmt).replace(tzinfo=pytz.utc).timestamp()
            except Exception:
                continue
    return None

def _moomoo_capability_report():
    """Protected capability-test (item E): per-symbol exchangeTimestamp /
    receivedAt / quoteAgeSeconds / entitlement / session for the bridge quotes.
    The verdict stays 'unknown' unless a venue timestamp PROVES real-time — we
    never upgrade on push cadence alone. '15-second push' = delivery frequency,
    NOT data freshness; closepin/early-warning never assume confirmed_realtime."""
    now = time.time()
    rows, have_exchange_ts = [], 0
    for mkt in ("JP", "US"):
        sess_open = _jp_market_open() if mkt == "JP" else _us_market_open()
        session = "open" if sess_open else "closed"
        for sym, rec in (_PUSHED_QUOTES.get(mkt) or {}).items():
            row = rec.get("row") or {}
            recv = rec.get("ts")
            ex_epoch = _coerce_epoch(row.get("exchangeTs"))
            if ex_epoch:
                have_exchange_ts += 1
            quote_age = round(now - recv, 1) if recv else None       # age of OUR copy
            venue_age = round(now - ex_epoch, 1) if ex_epoch else None  # true age at venue
            if ex_epoch is None:
                verdict = "unknown"                                   # unprovable without venue ts
            elif sess_open and venue_age is not None and venue_age <= 60:
                verdict = "realtime_evidence"
            elif sess_open and venue_age is not None and venue_age >= 600:
                verdict = "delayed_evidence"
            else:
                verdict = "unknown"
            rows.append({
                "market": mkt, "symbol": sym, "session": session,
                "exchangeTimestamp": row.get("exchangeTs"),
                "receivedAt": (datetime.utcfromtimestamp(recv).strftime("%Y-%m-%dT%H:%M:%SZ") if recv else None),
                "quoteAgeSeconds": quote_age, "venueAgeSeconds": venue_age,
                "entitlementReported": row.get("entitlement", "unknown"),
                "entitlementVerdict": verdict})
    verdicts = {r["entitlementVerdict"] for r in rows}
    overall = ("realtime_proven" if rows and verdicts == {"realtime_evidence"}
               else "delayed_evidence" if "delayed_evidence" in verdicts else "unknown")
    return {"asOf": _ai_now_iso(), "symbols": len(rows), "withExchangeTs": have_exchange_ts,
            "overallEntitlement": overall, "rows": rows,
            "noteJa": "『15秒push』は配信頻度でありデータ鮮度ではない。venueのexchangeTsが無い限りリアルタイムは"
                      "証明不可(entitlement=unknownを維持)。closepin・早期警戒はconfirmed_realtimeを前提にしない。"}

def _source_registry():
    # Self-verify EDINET once when a key is configured (cached) so the registry
    # flips missing→confirmed_live/requires_test without waiting for a JP event.
    if _EDINET_API_KEY and not _EDINET_STATE["lastFetchOk"]:
        try:
            _edinet_filings(datetime.now(TZ_JST).strftime("%Y-%m-%d"))
        except Exception:
            pass
    integ = get_integrations_snapshot()
    prov = {p["id"]: p for p in integ.get("providers", [])}
    def rt(pid):
        return (prov.get(pid) or {}).get("runtimeStatus", "missing")
    bridge_live = rt("moomoo") == "live"
    jq, td, fred, cg = rt("jquants"), rt("twelvedata"), rt("fred"), rt("coingecko")
    # Official J-Quants TDnet Add-on status (v11.1) — the registry must reflect the REAL
    # probe, never stay 'paid_not_enabled' once contracted. Cheap (cached in the fetch).
    try:
        _td_off, _td_usable = _jquants_tdnet_fetch(20)
    except Exception:
        _td_off, _td_usable = {"status": "unavailable", "entitlement": "unknown"}, False
    _td_off_status = _td_off.get("status")
    if not _JQUANTS_API_KEY:
        _td_reg_status, _td_ent, _td_note = "missing", "APIキー未設定", "JQUANTS_API_KEY未設定。"
    elif _td_off_status == "official_tdnet_live":
        _td_reg_status, _td_ent, _td_note = "confirmed_live", "tdnet_addon", "公式J-Quants TDnet Add-onがライブ(official confirmation)。"
    elif _td_off_status == "live":
        # route + entitlement proven; the probed window just had no disclosures (weekend等)
        _td_reg_status, _td_ent, _td_note = "confirmed_live", "tdnet_addon", "公式TDnet Add-on疎通OK(権限あり)。直近ウィンドウの開示0件。"
    elif _td_off_status in ("entitlement_missing",):
        _td_reg_status, _td_ent, _td_note = ("entitlement_missing", "addon未購入/未反映",
            "公式TDnetが403(プラン拒否)。Add-onは別途購入(月額)— ダッシュボードのSubscription→アドオンプランで"
            "[ご利用中]バッジを確認。yanoshinフォールバックで暫定運用。")
    elif _td_off_status in ("endpoint_not_found",):
        _td_reg_status, _td_ent, _td_note = "fallback_partial", "endpoint未解決", "公式TDnetのパスが未解決。env JQUANTS_TDNET_PATHを確認。yanoshinフォールバックで暫定運用。"
    else:
        _td_reg_status, _td_ent, _td_note = "requires_test", "未実証", "キーはあるが公式TDnetの成功プローブがまだ無い。"
    # J-Quants STANDARD datasets summary (v11.1.1) — reads the diagnostics CACHE only
    # (a public GET must never fire provider probes). Unknown until an admin diag ran.
    _dc = _PROVIDER_DIAG_CACHE.get("data") if time.time() < _PROVIDER_DIAG_CACHE.get("expires", 0.0) else None
    def _dc_rt(pid):
        for i in ((_dc or {}).get("items") or []):
            if i.get("provider") == pid:
                return i.get("runtimeStatus")
        return None
    _jq_ds = {p: _dc_rt(p) for p in ("jquants-trading-calendar", "jquants-earnings-calendar",
                                     "jquants-margin-interest", "jquants-short-ratio",
                                     "jquants-investor-types")}
    _jq_live_n = sum(1 for v in _jq_ds.values() if v == "live")
    _jq_known = any(v for v in _jq_ds.values())
    def S(cap, provider, market, status, entitlement, paid, licence, note):
        return {"capability": cap, "provider": provider, "market": market, "status": status,
                "entitlement": entitlement, "paid": paid, "licence": licence, "notesJa": note}
    sources = [
        S("日本株 価格", "moomoo / J-Quants", "JP",
          "confirmed_live" if bridge_live else ("confirmed_delayed" if jq == "live" else "missing"),
          "realtime(bridge) / T-1(J-Quants)", "free", "ok",
          "ブリッジ稼働中はリアルタイム、途絶時はJ-Quants前日終値へ自動フォールバック。"),
        S("米国株 価格", "moomoo / Twelve Data", "US",
          "confirmed_live" if bridge_live else ("confirmed_live" if td == "live" else "missing"),
          "realtime(bridge) / Twelve Data Basic=レギュラー時間RT(鮮度未計測)", "free", "ok",
          "ブリッジ稼働中はリアルタイム、途絶時はTwelve Dataへフォールバック。Twelve Data Basicは"
          "レギュラー時間の米国株/ETFがリアルタイム(時間外RTは上位プラン要)。無料枠の実鮮度は"
          "ランタイム未計測のため『遅延』とも『RT』とも断定しない。アップグレード不要。"),
        S("大口フロー(資金分布)", "moomoo", "JP/US",
          "confirmed_live" if bridge_live else "requires_test",
          "口座のデータ権限依存", "free", "entitlement-dependent",
          "新規買い/買い戻し/分配の推定に使用。"),
        S("暗号資産 価格/ショック", "CoinGecko", "CRYPTO",
          "confirmed_live" if cg == "live" else "partial", "数分遅延", "free", "ok",
          "24時間ショック検知に使用(キー不要)。"),
        S("金利・VIX・HY OAS", "FRED", "US", "confirmed_live" if fred == "live" else "missing",
          "日次", "free", "ok", "地合い/レジーム判定に使用。"),
        S("ニュース/材料", "Finnhub / GDELT / SEC EDGAR", "US/JP",
          "partial", "公開フィード", "free/optional", "ok",
          "二次媒体中心。一次の公式開示としては扱わない。"),
        S("企業開示(TDnet 公式)", "J-Quants TDnet Add-on" + ("" if _td_reg_status == "confirmed_live" else " / yanoshinフォールバック"),
          "JP", _td_reg_status, _td_ent, "paid", "ok",
          _td_note + " 公式=official confirmation。materialな開示のみofficial_catalyst候補、"
          "曖昧な題目はofficial_fact(価格原因の確定にはmarket/timing確認が必要)。yanoshinは非公式の下位ティア。"),
        S("J-Quants Standardデータ(カレンダー/決算予定/信用残/空売り/投資部門)", "J-Quants", "JP",
          ("confirmed_live" if _jq_live_n >= 3 else "partial" if _jq_live_n >= 1 else
           ("requires_test" if _JQUANTS_API_KEY else "missing")),
          (f"実測 live {_jq_live_n}/5" if _jq_known else "未プローブ"), "paid", "ok",
          "文脈/確認データ（生の信用残・空売り比率から単独で売買シグナルは作らない）。"
          "実測はadmin provider-diagnostics(5分キャッシュ)を参照。"
          + ("" if _jq_known else "admin診断が未実行のため requires_test 表示。")),
        S("企業開示(EDINET)", "EDINET API v2", "JP",
          ("missing" if not _EDINET_API_KEY else
           "confirmed_live" if _EDINET_STATE["lastFetchOk"] else "requires_test"),
          ("APIキー未設定" if not _EDINET_API_KEY else "Subscription-Key設定済"),
          "free", "ok",
          "公式開示=official_fact。official_catalystは臨時報告/大量保有など材料性のある開示が"
          "イベント当日に提出された場合のみ(定期/訂正は事実として記録するが当日の原因とは扱わない)。"),
        S("日本PTS", "—", "JP", "unavailable", "プロバイダ未確認", "—", "—",
          "確認済みプロバイダなし。通常のTSE気配からPTSやS高確率を推定しない。"),
        S("米国 時間外(pre/after)", "—", "US", "requires_test", "プロバイダ機能依存", "—", "—",
          "明示的な時間外データを返すプロバイダが未確認。"),
        S("板(L2)", "moomoo", "JP/US", "requires_test", "未検証", "—", "entitlement-dependent",
          "ブリッジ/権限が未検証のためliveにしない。"),
        S("テープ(歩み値)", "moomoo", "JP/US", "requires_test", "未検証", "—", "entitlement-dependent", "同上。"),
        S("VWAP", "—", "JP/US", "unavailable", "入力未接続", "—", "—", "VWAP入力は未接続。"),
        S("FX / 先物 / 商品", "—", "GLOBAL", "unavailable", "プロバイダ未確認", "—", "—",
          "確認済みプロバイダが無いためliveにしない(枠だけ確保)。"),
        S("AI判定(GPT-5.5)", "OpenAI", "—", {"live": "confirmed_live", "partial": "partial"}.get(rt("openai"), "missing"),
          "管理者実行のみ", "paid", "ok", "ルール判定の第二意見。"),
        S("AIチェック(Gemini)", "Gemini", "—", {"live": "confirmed_live", "partial": "partial"}.get(rt("gemini"), "missing"),
          "管理者実行のみ", "paid/free", "ok", "OpenAI判断の二重チェック。"),
    ]
    return {"asOf": _ai_now_iso(), "engineVersion": "source-registry-v1",
            "confirmedLive": sum(1 for s in sources if s["status"] == "confirmed_live"),
            "total": len(sources), "sources": sources,
            "noteJa": "『設定済み』≠『その機能がライブ』。各capabilityの真の状態を表示。"}

@app.route("/api/argus/source-registry")
def api_argus_source_registry():
    return jsonify(_source_registry())


@app.route("/api/argus/source-coverage")
def api_argus_source_coverage():
    """Source coverage by QUALITY TIER (ARGUS Pro v11). Honest: a source being listed
    is not enough — zero items / no successful fetch ≠ live. Weak tiers (aggregator/
    unknown/social) cannot ground judgment or confirm cause. Reuses the source registry
    (configured≠live) + a tally of the live IntelligenceItem store by tier."""
    reg = _source_registry() or {}
    # Tally the actual collected items by tier (what's really flowing in).
    tier_counts = {}
    fam_seen = set()
    for it in list(_INTEL_STORE):
        tier = it.get("sourceTier") or argus_research_mesh.source_tier(it.get("sourceId"))
        b = tier_counts.setdefault(tier, {"tier": tier, "itemCount": 0,
                                          **argus_research_mesh.tier_grounding(tier)})
        b["itemCount"] += 1
        fam_seen.add(argus_research_mesh.source_family(it.get("sourceId")))
    tiers = sorted(tier_counts.values(), key=lambda x: -x["itemCount"])
    grounding_items = sum(b["itemCount"] for b in tiers if b["canGroundJudgment"])
    weak_items = sum(b["itemCount"] for b in tiers if b["weakSignal"])
    return jsonify({
        "asOf": _ai_now_iso(),
        "schemaVersion": "source-coverage-v1",
        "tiers": tiers,
        "independentFamiliesSeen": sorted(f for f in fam_seen if f and f != "unknown"),
        "registry": {"confirmedLive": reg.get("confirmedLive"), "total": reg.get("total"),
                     "note": "configured ≠ live: 実データが流れて初めてliveと数える。"},
        "summary": {
            "totalItems": sum(b["itemCount"] for b in tiers),
            "canGroundJudgmentItems": grounding_items,
            "weakSignalItems": weak_items,
            "distinctTiers": len(tiers),
        },
        "noteJa": "弱いソース(アグリゲータ/不明/SNS)は単独で判断根拠にも原因確定にもできません。"
                  "同一ワイヤの転載は1ファミリー=1確認です。",
    })


# ── Provider diagnostics (v11.1) ─────────────────────────────────────────────
# Safe, cached probes proving which CONTRACTED providers are actually returning data.
# HARD rules: never return a key value / a URL containing a key / request headers / a raw
# provider body. A key being present is NOT 'live' — only a 200 with sampleCount>0 is.
_PROVIDER_DIAG_CACHE = {"data": None, "expires": 0.0}
_PROVIDER_DIAG_TTL = 300          # 5 min — avoid quota drain on repeated admin calls
_DIAG_TIMEOUT = 12   # J-Quants cold endpoints can take >8s; the real fetchers use 10-12s

def _diag_runtime(http, n):
    if http == 200:
        return ("live" if n > 0 else "partial")
    if http == 401:
        return "unauthorized"
    if http == 403:
        return "entitlement_missing"
    if http == 404:
        return "endpoint_not_found"
    if http == 429:
        return "rate_limited"
    return "error"

def _diag_probe(provider, configured, do_request, *, caps=None, limitations=""):
    """do_request() → (http_status:int, sample_count:int). Returns the secret-safe row."""
    now_iso = _ai_now_iso()
    row = {"provider": provider, "configured": bool(configured), "ok": False,
           "runtimeStatus": "missing", "httpStatus": None, "sampleCount": 0,
           "lastSuccessAt": None, "capabilities": caps or [], "limitationsJa": limitations,
           "errorType": None}
    if not configured:
        row.update(runtimeStatus="missing", errorType="not_configured",
                   limitationsJa=(limitations or "APIキー未設定。"))
        return row
    try:
        http, n = do_request()
        rs = _diag_runtime(http, n)
        ok = (http == 200 and n > 0)
        row.update(ok=ok, runtimeStatus=rs, httpStatus=http, sampleCount=int(n),
                   lastSuccessAt=(now_iso if ok else None), errorType=(None if ok else rs))
    except requests.exceptions.HTTPError as e:
        code = getattr(getattr(e, "response", None), "status_code", None)
        row.update(runtimeStatus=_diag_runtime(code or 0, 0), httpStatus=code, errorType="http_error")
    except Exception as e:
        row.update(runtimeStatus="error", errorType=type(e).__name__)   # type name only, never the message
    return row

def _provider_diagnostics():
    """Full admin diagnostics (cached). Secret-safe by construction."""
    now = time.time()
    c = _PROVIDER_DIAG_CACHE
    if c["data"] is not None and now < c["expires"]:
        return c["data"]

    def _jq_core():
        frm = (datetime.now(TZ_JST) - timedelta(days=150)).strftime("%Y-%m-%d")
        r = requests.get(f"{_JQUANTS_BASE}/equities/bars/daily",
                         headers={"x-api-key": _JQUANTS_API_KEY},
                         params={"code": "7203", "from": frm}, timeout=_DIAG_TIMEOUT)
        return r.status_code, len((r.json() or {}).get("data", []) if r.status_code == 200 else [])

    def _jq_tdnet():
        snap, _ = _jquants_tdnet_fetch(20)
        http = snap.get("httpStatus") or (200 if snap.get("status") == "official_tdnet_live" else 0)
        return (http or 0), len(snap.get("items") or [])

    # J-Quants STANDARD dataset probes (v11.1.1) — per-capability status visibility.
    # Rows-key varies per dataset; 200+rows=live, 200+0=partial (empty window ≠ broken),
    # 403 = plan gap / gateway (per J-Quants semantics), honest either way.
    def _jq_probe(path, params, rows_keys=("data",)):
        def fn():
            r = requests.get(f"{_JQUANTS_BASE}{path}", headers={"x-api-key": _JQUANTS_API_KEY},
                             params=params, timeout=_DIAG_TIMEOUT)
            n = 0
            if r.status_code == 200:
                j = r.json() if isinstance(r.json(), dict) else {}
                for k in tuple(rows_keys) + ("data",):
                    v = j.get(k)
                    if isinstance(v, list):
                        n = len(v)
                        break
            return r.status_code, n
        return fn
    _jq_today = datetime.now(TZ_JST).strftime("%Y-%m-%d")
    _jq_7d = (datetime.now(TZ_JST) - timedelta(days=7)).strftime("%Y-%m-%d")
    _jq_90d = (datetime.now(TZ_JST) - timedelta(days=90)).strftime("%Y-%m-%d")

    def _edinet():
        r = requests.get("https://api.edinet-fsa.go.jp/api/v2/documents.json",
                         params={"date": datetime.now(TZ_JST).strftime("%Y-%m-%d"), "type": 2,
                                 "Subscription-Key": _EDINET_API_KEY}, timeout=_DIAG_TIMEOUT)
        return r.status_code, len((r.json() or {}).get("results", []) if r.status_code == 200 else [])

    def _td_quote():
        r = requests.get(_TWELVEDATA_QUOTE, params={"symbol": "AAPL", "apikey": _TWELVEDATA_API_KEY},
                         timeout=_DIAG_TIMEOUT)
        j = r.json() if r.status_code == 200 else {}
        return r.status_code, (1 if isinstance(j, dict) and j.get("symbol") else 0)

    def _td_ts():
        r = requests.get("https://api.twelvedata.com/time_series",
                         params={"symbol": "SPY", "interval": "5min", "outputsize": 1,
                                 "apikey": _TWELVEDATA_API_KEY}, timeout=_DIAG_TIMEOUT)
        j = r.json() if r.status_code == 200 else {}
        return r.status_code, len((j or {}).get("values", []) if isinstance(j, dict) else [])

    def _fred():
        r = requests.get("https://api.stlouisfed.org/fred/series/observations",
                         params={"series_id": "DGS10", "api_key": _FRED_API_KEY, "file_type": "json",
                                 "limit": 1, "sort_order": "desc"}, timeout=_DIAG_TIMEOUT)
        return r.status_code, len((r.json() or {}).get("observations", []) if r.status_code == 200 else [])

    def _finnhub():
        r = requests.get("https://finnhub.io/api/v1/quote", params={"symbol": "AAPL", "token": FINNHUB_API_KEY},
                         timeout=_DIAG_TIMEOUT)
        j = r.json() if r.status_code == 200 else {}
        return r.status_code, (1 if isinstance(j, dict) and j.get("c") else 0)

    def _av():
        r = requests.get("https://www.alphavantage.co/query",
                         params={"function": "TOP_GAINERS_LOSERS", "apikey": _ALPHAVANTAGE_KEY},
                         timeout=_DIAG_TIMEOUT)
        j = r.json() if r.status_code == 200 else {}
        n = len((j or {}).get("top_gainers", []) if isinstance(j, dict) else [])
        # AlphaVantage rate-limits with HTTP 200 + an Information/Note body and NO data
        # (free tier = 25 req/day). Report that honestly as rate_limited, not 'partial'.
        if r.status_code == 200 and n == 0 and isinstance(j, dict) and (j.get("Information") or j.get("Note")):
            return 429, 0
        return r.status_code, n

    def _coingecko():
        headers = {"User-Agent": "argus-research/1.0"}
        if _COINGECKO_KEY:
            headers["x-cg-demo-api-key"] = _COINGECKO_KEY
        r = requests.get("https://api.coingecko.com/api/v3/simple/price",
                         params={"ids": "bitcoin", "vs_currencies": "usd"}, headers=headers,
                         timeout=_DIAG_TIMEOUT)
        return r.status_code, (1 if r.status_code == 200 and (r.json() or {}).get("bitcoin") else 0)

    items = [
        _diag_probe("jquants-core", bool(_JQUANTS_API_KEY), _jq_core,
                    caps=["equities_daily", "markets"], limitations="J-Quants Standard コア。"),
        _diag_probe("jquants-tdnet", bool(_JQUANTS_API_KEY), _jq_tdnet,
                    caps=["official_disclosure"],
                    limitations="公式TDnet Add-on。404ならJQUANTS_TDNET_PATH要調整。official=confirmation。"),
        # v2 paths per the official migration table (jpx-jquants.com/ja/spec/migration-v1-v2):
        # trading_calendar→/markets/calendar, weekly_margin_interest→/markets/margin-interest,
        # short_selling→/markets/short-ratio, trades_spec→/equities/investor-types. All rows
        # live under the top-level "data" key in v2.
        _diag_probe("jquants-trading-calendar", bool(_JQUANTS_API_KEY),
                    _jq_probe("/markets/calendar", {"from": _jq_7d, "to": _jq_today}),
                    caps=["trading_calendar"],
                    limitations="Freeプラン以上。市場クロック照合用（現在は静的カレンダー併用）。"),
        _diag_probe("jquants-earnings-calendar", bool(_JQUANTS_API_KEY),
                    _jq_probe("/equities/earnings-calendar", {}),
                    caps=["earnings_calendar"], limitations="決算発表予定。catalystで使用中。"),
        _diag_probe("jquants-margin-interest", bool(_JQUANTS_API_KEY),
                    _jq_probe("/markets/margin-interest", {"code": "7203", "from": _jq_90d}),
                    caps=["margin_interest"], limitations="信用残(週次)。entry-scoutで使用中。Standard。"),
        _diag_probe("jquants-short-ratio", bool(_JQUANTS_API_KEY),
                    _jq_probe("/markets/short-ratio", {"s33": "0050", "from": _jq_7d, "to": _jq_today}),
                    caps=["short_ratio"],
                    limitations="業種別空売り比率。判断には未接続（状態可視化のみ・文脈データ）。Standard。"),
        _diag_probe("jquants-investor-types", bool(_JQUANTS_API_KEY),
                    _jq_probe("/equities/investor-types",
                              {"from": (datetime.now(TZ_JST) - timedelta(days=30)).strftime("%Y-%m-%d"),
                               "to": _jq_today}),
                    caps=["investor_types"],
                    limitations="投資部門別売買。判断には未接続（状態可視化のみ・文脈データ）。Light以上。"),
        _diag_probe("edinet", bool(_EDINET_API_KEY), _edinet, caps=["official_filings"],
                    limitations="EDINET v2 公式開示。"),
        _diag_probe("twelvedata-quote", bool(_TWELVEDATA_API_KEY), _td_quote, caps=["quote"],
                    limitations="Twelve Data。Growはquota拡張であってL2/tape/options/borrowの代替ではない。"),
        _diag_probe("twelvedata-timeseries", bool(_TWELVEDATA_API_KEY), _td_ts, caps=["time_series", "vwap_bars"],
                    limitations="時間外liveは実証時のみ。"),
        _diag_probe("fred", bool(_FRED_API_KEY), _fred, caps=["macro"], limitations="金利/VIX/HY OAS。"),
        _diag_probe("finnhub", bool(FINNHUB_API_KEY), _finnhub, caps=["quote", "news"], limitations="二次媒体/相場。"),
        _diag_probe("alphavantage", bool(_ALPHAVANTAGE_KEY), _av, caps=["us_movers"], limitations="米国ムーバー。"),
        _diag_probe("coingecko", True, _coingecko, caps=["crypto_price"],
                    limitations="キー任意。DC IPブロック時はCoinbaseフォールバック(価格側)。"),
    ]
    # AI providers: report configured only — do NOT ping (billable). Layer2B: config only.
    items.append({"provider": "openai", "configured": bool(_OPENAI_API_KEY),
                  "ok": bool(_OPENAI_API_KEY), "runtimeStatus": ("configured" if _OPENAI_API_KEY else "missing"),
                  "httpStatus": None, "sampleCount": 0, "lastSuccessAt": None,
                  "capabilities": ["ai_judge"], "limitationsJa": "課金回避のためここでは疎通しない。/ai-provider-status(admin)参照。",
                  "errorType": None})
    items.append({"provider": "gemini", "configured": bool(GEMINI_API_KEY),
                  "ok": bool(GEMINI_API_KEY), "runtimeStatus": ("configured" if GEMINI_API_KEY else "missing"),
                  "httpStatus": None, "sampleCount": 0, "lastSuccessAt": None,
                  "capabilities": ["ai_check"], "limitationsJa": "同上(billable)。", "errorType": None})
    items.append({"provider": "layer2b-private-store", "configured": _layer2b_store_configured(),
                  "ok": _layer2b_store_configured(), "runtimeStatus": ("configured" if _layer2b_store_configured() else "missing"),
                  "httpStatus": None, "sampleCount": 0, "lastSuccessAt": None,
                  "capabilities": ["owner_private_records"], "limitationsJa": "private repo設定の有無のみ(内容は出さない)。",
                  "errorType": None})

    out = {"asOf": _ai_now_iso(), "schemaVersion": "provider-diagnostics-v1", "items": items,
           "summary": {"live": sum(1 for i in items if i["runtimeStatus"] == "live"),
                       "configured": sum(1 for i in items if i["configured"]),
                       "total": len(items)},
           "noteJa": "『設定済み』≠『ライブ』。liveはprovider 200応答+sampleCount>0+lastSuccessAtがある時のみ。"}
    c["data"] = out
    c["expires"] = now + _PROVIDER_DIAG_TTL
    return out

@app.route("/api/argus/admin/provider-diagnostics")
def api_argus_admin_provider_diagnostics():
    """ADMIN-ONLY full provider diagnostics (real probes). Secret-safe: no keys, no
    URLs-with-keys, no request headers, no raw provider bodies. Cached 5m."""
    ok, err, code = _require_admin()
    if not ok:
        return jsonify(err), code
    return jsonify(_provider_diagnostics())

@app.route("/api/argus/provider-diagnostics/public")
def api_argus_provider_diagnostics_public():
    """PUBLIC-safe provider status: configured booleans + live/partial/missing ONLY.
    No admin detail, no httpStatus, no sample counts, no messages."""
    full = _provider_diagnostics()
    pub = [{"provider": i["provider"], "configured": i["configured"],
            "status": ("live" if i["runtimeStatus"] == "live" else
                       "partial" if i["runtimeStatus"] == "partial" else
                       "configured" if i["runtimeStatus"] == "configured" else
                       ("missing" if not i["configured"] else "not_live"))}
           for i in full["items"]]
    return jsonify({"asOf": full["asOf"], "schemaVersion": "provider-diagnostics-public-v1",
                    "providers": pub,
                    "summary": {"live": sum(1 for p in pub if p["status"] == "live"),
                                "configured": sum(1 for p in pub if p["configured"]), "total": len(pub)},
                    "noteJa": "設定済み≠ライブ。詳細はadmin専用エンドポイントで。"})


# ── Market Depth capability report (v10.196) ─────────────────────────────────
# Honest per-capability depth status (bridge/JP cash/US regular/PTS/extended/VWAP/
# tape/L2/options/borrow/FX/TDnet). Feeds the Visibility Guard REAL values instead of
# hardcoded defaults. Pure logic in argus_market_depth; a capability is 'live' only on
# venue-timestamp proof, never on push cadence.
_MARKET_DEPTH_CACHE = {"data": None, "expires": 0.0}
_VWAP_CACHE = {"data": None, "expires": 0.0}

def _vwap_probe():
    """Real capability test (v10.200): compute session VWAP from Twelve Data 5-min
    intraday bars for the US watchlist. US-session-gated, cached, quota-safe, guarded.
    Returns {computed, values, asOf, note, probed:True}. VWAP becomes a LIVE capability
    only when the bars actually compute — never assumed."""
    now = time.time()
    if _VWAP_CACHE["data"] is not None and now < _VWAP_CACHE["expires"]:
        return _VWAP_CACHE["data"]
    probe = {"computed": False, "values": {}, "probed": True, "asOf": _ai_now_iso(),
             "note": "intraday barsから算出"}
    try:
        if not _TWELVEDATA_API_KEY:
            probe["note"] = "TWELVEDATA_API_KEY未設定のため算出不可"
        elif not _us_market_open():
            probe["note"] = "米レギュラー時間外のためintraday VWAPは算出しない"
        else:
            syms = sorted({str(x["symbol"]).upper() for x in _US_WATCHLIST})[:_TD_VWAP_MAX]
            if syms:
                r = requests.get(_TWELVEDATA_TS, params={
                    "symbol": ",".join(syms), "interval": "5min", "outputsize": 96,
                    "apikey": _TWELVEDATA_API_KEY}, timeout=15)
                body = r.json() if r.ok else {}
                if isinstance(body, dict) and str(body.get("status", "")).lower() != "error":
                    vals = {}
                    for sym in syms:
                        node = body.get(sym) if len(syms) > 1 else body
                        if not isinstance(node, dict):
                            continue
                        vw = argus_market_depth.compute_vwap(node.get("values") or [])
                        if vw is not None:
                            vals[sym] = vw
                    if vals:
                        probe.update({"computed": True, "values": vals,
                                      "note": f"{len(vals)}銘柄のセッションVWAPを5分足から算出(算出値)"})
    except Exception:
        probe["note"] = "VWAPプローブ失敗(次回再試行)"
    _VWAP_CACHE["data"] = probe
    _VWAP_CACHE["expires"] = now + (1800 if probe["computed"] else 900)
    return probe

def _market_depth_report():
    now = time.time()
    if _MARKET_DEPTH_CACHE["data"] is not None and now < _MARKET_DEPTH_CACHE["expires"]:
        return _MARKET_DEPTH_CACHE["data"]
    try: mc = _moomoo_capability_report()
    except Exception: mc = {}
    try: rp = _MOOMOO_ALLMARKET_REPORT.get("realtimeProof") or {}
    except Exception: rp = {}
    try: reg = _source_registry()
    except Exception: reg = {}
    try: vwap = _vwap_probe()
    except Exception: vwap = None
    try:
        rep = argus_market_depth.build_market_depth_report(
            now_iso=_ai_now_iso(), bridge_age_sec=_push_last_age_sec(),
            moomoo_capability=mc, realtime_proof=rp, source_registry=reg,
            jp_open=_jp_market_open(), us_open=_us_market_open(),
            vwap_probe=vwap)
    except Exception:
        rep = None
    _MARKET_DEPTH_CACHE["data"] = rep
    _MARKET_DEPTH_CACHE["expires"] = now + 60
    return rep

@app.route("/api/argus/market-depth")
def api_argus_market_depth():
    rep = _market_depth_report()
    return jsonify(rep or {"status": "unavailable", "engineVersion": "market-depth-v1",
                           "capabilities": {}, "note": "depth report temporarily unavailable"})


# Pure projection so the "proof" contract is unit-testable without Flask/network.
def _market_depth_proof_items(capabilities):
    """Project the depth report into per-capability PROOF rows. A capability marked
    'live' but NOT probed (no exchange/venue timestamp) is honestly downgraded to
    'unverified_live' — cadence is never proof. requires_contract/unavailable are
    surfaced (not hidden) so the UI can't imply more coverage than exists."""
    _PROOF_TYPE = {
        "BRIDGE": "provider_timestamp", "JP_CASH": "exchange_timestamp",
        "US_REGULAR": "provider_timestamp", "US_EXTENDED": "provider_timestamp",
        "VWAP": "computed_from_bars", "PTS": "official_api", "TDNET": "official_api",
    }
    # True market DEPTH (order-book/tape) vs computed indicators — for the summary tally.
    _TRUE_DEPTH = {"L2", "TAPE", "OPTIONS_IV", "BORROW_FEE"}
    items = []
    for cap, r in (capabilities or {}).items():
        st = r.get("status")
        probed = bool(r.get("probed"))
        eff = st
        if st == "live" and not probed:
            eff = "unverified_live"       # live claim without a real measurement → honest downgrade
        items.append({
            "capability": cap,
            "status": eff,
            "rawStatus": st,
            "probed": probed,
            "proofType": (_PROOF_TYPE.get(cap, "provider_timestamp") if eff == "live" else
                          ("none" if eff in ("unavailable", "requires_contract", "unverified_live", "testing") else "manual_config")),
            "lastProofAt": r.get("lastSuccess") if eff == "live" else None,
            "sampleCountToday": r.get("sample") if isinstance(r.get("sample"), (int, float)) else None,
            "canAffectDecision": bool(r.get("affectsActionLevel")),
            "isTrueDepth": cap in _TRUE_DEPTH,
            "limitationsJa": r.get("limitations", ""),
        })
    return items


@app.route("/api/argus/market-depth/proof")
def api_argus_market_depth_proof():
    """PROOF-level Market Depth (ARGUS Pro v11): 'live' only where a real measurement
    (probed=true) backs it; otherwise 'unverified_live'. L2/TAPE/OPTIONS_IV/BORROW_FEE
    remain unavailable/requires_contract until a real feed exists — cadence ≠ proof."""
    rep = _market_depth_report() or {}
    items = _market_depth_proof_items(rep.get("capabilities") or {})
    true_live = sum(1 for i in items if i["status"] == "live" and i["isTrueDepth"])
    computed_live = sum(1 for i in items if i["status"] == "live" and not i["isTrueDepth"])
    return jsonify({
        "asOf": rep.get("asOf") or _ai_now_iso(),
        "schemaVersion": "market-depth-proof-v1",
        "items": items,
        "summary": {
            "trueDepthLiveCount": true_live,
            "computedIndicatorsLiveCount": computed_live,
            "unverifiedLiveCount": sum(1 for i in items if i["status"] == "unverified_live"),
            "requiresContractCount": sum(1 for i in items if i["status"] == "requires_contract"),
            "unavailableCount": sum(1 for i in items if i["status"] == "unavailable"),
        },
        "proofNoteJa": "「LIVE」は取引所/提供元タイムスタンプ等の実測(probed=true)がある能力のみ。"
                       "配信頻度は鮮度の証明ではありません。板/歩み値/オプションIV/貸株料は実データが無い限りunavailable/要契約。",
    })


# ── Visibility Risk Guard (v10.195) ──────────────────────────────────────────
# Aggregates every data-visibility signal ARGUS already exposes into one honest
# verdict: what it can't see, whether to cap confidence / block ENTER, and a calm
# "検知≠安全" coverage line. Structural gaps (PTS/L2/tape/VWAP/…) are context-only;
# only SITUATIONAL degradation (bridge stale in session, held-stale regime, budget
# stopped) drops the level / blocks / warns. Pure logic lives in argus_visibility.
# v10.196: capabilities now come from the live Market Depth report (data-driven).
_VISIBILITY_CACHE = {"data": None, "expires": 0.0}

def _visibility_guard():
    now = time.time()
    if _VISIBILITY_CACHE["data"] is not None and now < _VISIBILITY_CACHE["expires"]:
        return _VISIBILITY_CACHE["data"]
    try: sh = _system_health()
    except Exception: sh = None
    try: moomoo_ent = (_moomoo_capability_report() or {}).get("overallEntitlement")
    except Exception: moomoo_ent = None
    try:
        _reg = get_market_regime_snapshot()
        held = _reg.get("heldOverMin") if isinstance(_reg, dict) else None
    except Exception: held = None
    try:
        _n = int(((_ledger_summary() or {}).get("overall") or {}).get("n") or 0)
        cal_stage = argus_calibration.reliability_stage(_n)
    except Exception: cal_stage = None
    try: dv_phase = _dv_shadow_phase()
    except Exception: dv_phase = "v1-phase1-engine-only"
    try: caps = (_market_depth_report() or {}).get("capabilitiesForGuard")
    except Exception: caps = None
    g = argus_visibility.build_visibility_guard(
        now_iso=_ai_now_iso(),
        system_health=sh,
        capabilities=caps,   # data-driven from the Market Depth report (v10.196; None → defaults)
        bridge_age_sec=_push_last_age_sec(),
        jp_open=_jp_market_open(),
        us_open=_us_market_open(),
        moomoo_overall_entitlement=moomoo_ent,
        regime_held_over_min=held,
        calibration_stage=cal_stage,
        decision_value_phase=dv_phase,
    )
    _VISIBILITY_CACHE["data"] = g
    _VISIBILITY_CACHE["expires"] = now + 60
    return g

@app.route("/api/argus/visibility-guard")
def api_argus_visibility_guard():
    return jsonify(_visibility_guard())


# ── Runtime manifest (v10.107) ───────────────────────────────────────────────
# Live "current understanding" base for the AI Review Sheet + external-AI handoff,
# so GPT/Claude never reason from a STALE static doc. Public, secret-free — only
# booleans for config presence, never any key/value.
def get_runtime_manifest():
    reg = _source_registry()
    try:
        ds = get_downside_incidents()
    except Exception:
        ds = {}
    try:
        td = get_tdnet_recent()
    except Exception:
        td = {}
    aij = _ai_judgment_truth()
    try:
        vg = _visibility_guard()
    except Exception:
        vg = {}
    layer2b_configured = bool(os.environ.get("ARGUS_LAYER2B_PRIVATE_REPO")
                              and os.environ.get("ARGUS_LAYER2B_PRIVATE_TOKEN"))
    degraded = [f"{s.get('capability')}:{s.get('status')}" for s in (reg.get("sources") or [])
                if s.get("status") != "confirmed_live"]
    return {
        "asOf": _ai_now_iso(), "engineVersion": "runtime-manifest-v1",
        "buildSha": (os.environ.get("RENDER_GIT_COMMIT", "")[:7] or None),
        "activeRoutes": ["Today", "Watchlist", "Market Context", "Core Portfolio", "Glossary / Guide"],
        "providers": {"confirmedLive": reg.get("confirmedLive"), "total": reg.get("total"),
                      "degraded": degraded[:14]},
        "calibration": {
            "schema": argus_calibration.SCHEMA_VERSION, "universe": argus_calibration.UNIVERSE_VERSION,
            "tacticalBenchmark": argus_calibration.TACTICAL_BENCHMARK_VERSION, "cohort": argus_calibration.COHORT_VERSION,
            "phase": "v4 dry-run (parallel epoch calibration_v1) alongside v3 headline; burn-in — accuracy NOT proven",
        },
        "downside": {
            "engine": "downside-v1", "activeIncidents": ds.get("activeCount", 0),
            "jpIntradayOverlay": ds.get("jpIntradayOverlay"), "holderRiskOverlay": ds.get("holderRiskOverlay"),
            "rule": "serious/unexplained drop is never plain HOLD; held/protected stricter; no-news = caution (not safe)",
        },
        "tdnet": {"status": td.get("status", "unavailable"), "provider": td.get("provider"),
                  "count": len(td.get("items") or [])},
        "ownerWatchlist": {"layer2bConfigured": layer2b_configured,
                           "note": "non-monetary flags only (ownerState/strictness/priority); amounts NEVER sent"},
        "decisionValue": {"phase": (_dv_shadow_public_summary().get("status") or "v1-phase1-engine-only"),
                           "note": "shadow simulation only; NO order/broker/execute routes — ever; real netR owner-private"},
        "visibility": {"visibilityLevel": vg.get("visibilityLevel"), "confidenceCap": vg.get("confidenceCap"),
                       "reasonCodes": vg.get("reasonCodes", []), "coverageLineJa": vg.get("coverageLineJa"),
                       "note": "structural gaps (PTS/L2/tape/VWAP/extended) are context-only; situational degradation caps/blocks"},
        "ai": {"status": aij["status"], "note": "GPT-5.5 + Gemini 2.5 Pro; admin-run + cached view only"},
        "safetyBoundaries": ["no auto-trading", "no order/execute/broker routes",
                             "holdings/cost basis never leave the device in plaintext"],
        "currentLimitations": [
            "calibration is burn-in — accuracy not proven (ARGUS classifies the present; it is not a profit guarantee)",
            "JP prices are J-Quants T-1 unless the moomoo bridge is live (then realtime)",
            # v11.1: drop the third-party-wrapper caveat once the OFFICIAL J-Quants TDnet
            # Add-on is live; keep it (fallback) otherwise.
            ("TDnet: official J-Quants Add-on live (official confirmation; material titles → official_catalyst, ambiguous → official_fact)"
             if td.get("official") else
             "TDnet via a third-party (yanoshin) wrapper; bad-news sentiment is title-only (要確認, not asserted)"),
            "regime label may be held from the last full ETF coverage (shown as held/stale)",
        ],
    }


@app.route("/api/argus/runtime-manifest")
def api_argus_runtime_manifest():
    return jsonify(get_runtime_manifest())


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
# Regime Sensor Universe v2 (v10.72): 4 JP ETFs + 11 US ETFs + BTC = 16. The old
# JP single-names (8306/7203/8058/9432) moved to the Tactical Benchmark; USDJPY/
# VIX moved to Context Variables (recorded but NOT scored as equal return assets).
_L1_SENSORS_JP = [
    ("1306", "TOPIX ETF"), ("1321", "日経225 ETF"),
    ("1615", "東証銀行業ETF"), ("1343", "東証REIT ETF"),
]
_L1_SENSORS_US = ["SPY", "QQQ", "IWM", "SMH", "XLF", "XLE", "XLU", "TLT", "LQD", "HYG", "GLD"]
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
_SENSOR_ETF_EXTRA = ["SMH", "XLF", "XLE", "LQD"]  # v2 sensors not in _REGIME_ETFS
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
                # High/Low for gap (窓) detection — defensive: J-Quants v2
                # abbreviates fields (C=close); try the likely H/L keys and
                # fall back to None so a wrong field name yields NO gap rather
                # than a fake one (Fable 5 rule).
                def _g(q, keys):
                    for k in keys:
                        v = q.get(k)
                        if v is not None:
                            try:
                                return float(v)
                            except Exception:
                                pass
                    return None
                data = {"closes": [float(_q_close(q)) for q in rows],
                        "volumes": [int(q.get("Vo") or 0) for q in rows],
                        "highs": [_g(q, ("H", "Hi", "AdjH")) for q in rows],
                        "lows": [_g(q, ("L", "Lo", "AdjL")) for q in rows],
                        "dates": [q.get("Date") for q in rows]}
        except Exception as e:
            add_log(f"[scout] history fetch failed {code}: {type(e).__name__}")
    _JQ_HISTORY_CACHE[code] = {"data": data, "expires": now + (_JQ_HISTORY_TTL if data else 600)}
    return data

def _jq_weekly_margin(code):
    """Latest two weekly margin-interest rows for one TSE code, newest-first.
    Returns a list of normalized dicts {date, longVol, shortVol} or None if the
    J-Quants plan does not include this endpoint (403/404) or it is empty.
    v11.1.2 FIX: the endpoint was RENAMED in v2 (migration table): the old
    /markets/weekly_margin_interest with LongMarginTradeVolume/ShortMarginTradeVolume
    fields is DEAD — v2 is /markets/margin-interest with ShrtVol/LongVol. The old
    path had silently broken this feature since the v2 migration (the provider
    diagnostics probe surfaced it). Old field names kept as a defensive fallback."""
    now = time.time()
    c = _JQ_MARGIN_CACHE.get(code)
    if c and now < c["expires"]:
        return c["data"]
    data = None
    if _JQUANTS_API_KEY:
        try:
            headers = {"x-api-key": _JQUANTS_API_KEY}
            frm = (datetime.now(TZ_JST) - timedelta(days=90)).strftime("%Y-%m-%d")
            r = requests.get(f"{_JQUANTS_BASE}/markets/margin-interest",
                             headers=headers, params={"code": code, "from": frm}, timeout=10)
            if r.status_code == 200:
                rows = (r.json() or {}).get("data", []) or []
                norm = []
                for q in rows:
                    lv = q.get("LongVol", q.get("LongMarginTradeVolume"))
                    sv = q.get("ShrtVol", q.get("ShortMarginTradeVolume"))
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






# v3 (2026-06-20, user: 「もっとARGUS中心に」): turn the score/flow/credit/
# calibration into a one-line CALL + a 2-3 sentence STORY grounded in the data
# Gemini/GPT can't fetch (flow/credit/our own track record). This is the
# narrative the user otherwise leaves ARGUS to get from an LLM — brought
# in-house. Not a buy/sell order: a framing of the decision.


def get_entry_scout(sym, market="JP"):
    now = time.time()
    ck = f"{market}:{sym}"
    c = _SCOUT_CACHE.get(ck)
    if c and now < c["expires"]:
        return c["data"]
    is_us = (market == "US")
    hist = _td_price_history(sym) if is_us else _jq_price_history(sym)
    if not hist:
        return {"engineVersion": "entry-scout-v1", "symbol": sym, "market": market,
                "status": "unavailable",
                "noteJa": "価格履歴を取得できませんでした(コード違いか一時的な障害)。"}
    m = _entry_metrics(hist["closes"], hist["volumes"], hist.get("highs"), hist.get("lows"))
    if not m:
        return {"engineVersion": "entry-scout-v1", "symbol": sym, "market": market,
                "status": "unavailable",
                "noteJa": "履歴が20営業日未満のため診断できません(上場直後など)。"}
    # Realtime flow from the bridge (last push regardless of freshness — the
    # asOf below tells the user how stale it is, e.g. on a weekend).
    pushed = (_PUSHED_QUOTES.get(market) or {}).get(sym)
    flow_ratio, flow_age_min = None, None
    if pushed:
        fl = (pushed.get("row") or {}).get("flow") or {}
        if isinstance(fl.get("bigNetRatio"), (int, float)):
            flow_ratio = float(fl["bigNetRatio"])
            flow_age_min = int((now - pushed["ts"]) / 60)
    ev = get_events_snapshot()
    esc = _region_event_escalation(ev.get("events", []) if isinstance(ev, dict) else [], market)
    posture = _rates_posture(get_rates_snapshot())
    vol = _vix_assess(_fred_vix_history())
    vix_zone = vol.get("zone") if isinstance(vol, dict) else None
    vix_spike = bool(vol.get("spike")) if isinstance(vol, dict) else False
    weekday = datetime.now(TZ_JST).weekday()
    # v2: market regime (6h-cached — no extra cost when warm).
    reg = get_market_regime_snapshot()
    reg_label = (reg.get("regime", {}) or {}).get("label") if isinstance(reg, dict) else None
    reg_ok = isinstance(reg, dict) and reg.get("status") in ("live", "partial")
    # v2: index-relative strength — JP: vs TOPIX ETF 1306; US: vs SPY, both from
    # the bridge so the comparison is same-timestamp realtime.
    rel_strength = None
    idx_pushed = (_PUSHED_QUOTES.get(market) or {}).get("1306" if not is_us else "SPY")
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
    # v2.2-2.4: JP-only credit/short data (日証金・JPX空売り are Japan-only).
    # For US these are absent — honestly None; US short-interest is a future add.
    margin_sig = jsf_sig = short_disclosed = None
    jsf_status = jpx_short_date = jsf_date = None
    short_status = "us_market" if is_us else None
    if not is_us:
        margin_sig = _margin_signal(_jq_weekly_margin(sym))
        jsf_table, jsf_date = _jsf_balance_table()
        if jsf_table is None:
            jsf_sig, jsf_status = None, "source_unavailable"
        elif sym in jsf_table and jsf_table[sym].get("loan") is not None and jsf_table[sym].get("short") is not None:
            jsf_sig, jsf_status = _jsf_for(sym), "ok"
        else:
            jsf_sig, jsf_status = None, "not_loanable"
        jpx_short_table, jpx_short_date = _jpx_short_table()
        if jpx_short_table is None:
            short_disclosed, short_status = None, "source_unavailable"
        elif sym in jpx_short_table:
            short_disclosed, short_status = jpx_short_table[sym], "ok"
        else:
            short_disclosed, short_status = None, "none_disclosed"
    else:
        jsf_status = "us_market"
    assess = _entry_scout_assess(m, flow_ratio, esc, posture, vix_zone, weekday,
                                 regime_label=reg_label if reg_ok else None,
                                 vix_spike=vix_spike, rel_strength=rel_strength,
                                 earnings_days=earnings_days, ai_view=ai_view,
                                 margin_sig=margin_sig, jsf_sig=jsf_sig,
                                 short_disclosed=short_disclosed)
    out = {
        "engineVersion": "entry-scout-v1", "symbol": sym, "market": market,
        "name": (sym if is_us else (_jq_name_for(sym) or sym)),
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
        # Calibration track record for THIS score bucket (scout-ledger-v1, Phase 3).
        "scoreTrackRecord": ((_scout_summary() or {}).get("byBucket") or {}
                             ).get(_scout_score_bucket((assess or {}).get("score"))),
        "context": {"posture": posture, "vixZone": vix_zone, "vixSpike": vix_spike,
                    "regime": reg_label if reg_ok else None,
                    "relStrengthVsTopix": rel_strength, "earningsDays": earnings_days,
                    "aiView": ai_view, "eventEscalation": esc or "normal",
                    "weekdayJa": "月火水木金土日"[weekday]},
        "assessment": assess,
        "dataGapsJa": ([
            "信用需給: 日証金・JPX空売りは日本株専用のため米国株では未取得(米国の空売り残はFINRA等で将来対応)",
        ] if is_us else [
            {"ok": "信用残: 日証金(JSF)貸借残で取得済み(日証金倍率 = 融資残/貸株残)",
             "not_loanable": "信用残: この銘柄は貸借銘柄ではないため日証金データに非掲載 — 取得不可(正常)",
             "source_unavailable": "信用残: 日証金データ源を一時取得できません(自動リトライ。数分後に再診断で復帰)",
             }[jsf_status],
            {"ok": "機関の大口空売り: JPX開示データで取得済み",
             "none_disclosed": "機関の大口空売り: 0.5%超の開示報告なし(=機関の大口空売りは記録上なし)",
             "source_unavailable": "機関の大口空売り: JPXデータ源を一時取得できません(自動リトライ)",
             }[short_status],
        ]) + [
            "チャート: 窓(ギャップ)は検知済み(v2.5)。ダブルボトム等の視覚的パターン形状は未対応 — RSI/MACD/ボリンジャー/クロスで近似",
            "国策・テーマ性の自動判定は未対応 — ニュース/開示で各自確認",
        ],
        "noteJa": "売買指示ではなく、入る前の論点整理。最終判断と数量はあなたのルールで。",
    }
    # v3 (2026-06-20): engine track record + this-regime calibration (the moat
    # no LLM has), and the one-line CALL + STORY composed from all of the above.
    _led = _ledger_summary() or {}
    out["engineCalibration"] = _led.get("overall")          # {days,n,hitRate,brierMean} | None
    _pl = reg_label if reg_ok else None                     # when regime live, == marketPosture key
    _pc = (_led.get("byPosture") or {}).get(_pl) if _pl else None
    out["postureCalibration"] = ({"posture": _pl, **_pc} if isinstance(_pc, dict) else None)
    out["callJa"], out["narrativeJa"] = _scout_narrative(
        assess, out["flowInference"], out["context"], jsf_sig, short_disclosed,
        m, out["scoreTrackRecord"], out["engineCalibration"], out["postureCalibration"], is_us)
    # If a credit/short source was momentarily down, cache only briefly so the
    # next diagnosis self-heals instead of showing a 30-min gap (検証で確認).
    src_down = jsf_status == "source_unavailable" or short_status == "source_unavailable"
    _SCOUT_CACHE[ck] = {"data": out, "expires": now + (180 if src_down else _SCOUT_TTL)}
    return out

@app.route("/api/argus/entry-scout")
def api_argus_entry_scout():
    sym = (request.args.get("symbol") or "").strip().upper()
    mkt = (request.args.get("market") or "").strip().upper()
    if _JP_SYM_RE.match(sym) and mkt != "US":
        return jsonify(get_entry_scout(sym, "JP"))
    if _US_SYM_RE.match(sym) and (mkt == "US" or not _JP_SYM_RE.match(sym)):
        return jsonify(get_entry_scout(sym, "US"))
    return jsonify({"error": "bad_symbol",
                    "noteJa": "日本株4桁コード、または米国ティッカー(?market=US)に対応。"}), 400

# ── Scout calibration (scout-ledger-v1, v10.24) — Phase 3 ────────────────────
# The learning loop's final piece: record each day's entry-scout score +
# flow-classification for the JP active names, then score them against the
# realized move so a raw "score +1.5" becomes a CALIBRATED "score≥1.5 was up
# 5d X% of the time". Turns every estimate into a track record (the user's
# "全情報を一つの答え%に"). Recording here; scoring in the daily ledger workflow.


_SCOUT_SUMMARY_CACHE = {"data": None, "expires": 0.0}

def _scout_summary():
    """The accumulated scout calibration (ledger/scout/summary.json) — 30-min
    cache, 404 until the workflow has scored ≥1 past day. Never raises."""
    now = time.time()
    if now < _SCOUT_SUMMARY_CACHE["expires"]:
        return _SCOUT_SUMMARY_CACHE["data"]
    data = None
    try:
        r = requests.get(f"{_LEDGER_RAW_BASE}/scout/summary.json", timeout=6)
        if r.status_code == 200:
            d = r.json()
            data = d if isinstance(d, dict) else None
    except Exception:
        data = None
    _SCOUT_SUMMARY_CACHE["data"] = data
    _SCOUT_SUMMARY_CACHE["expires"] = now + (1800 if data else 600)
    return data

_CLOSEPIN_SUMMARY_CACHE = {"data": None, "expires": 0.0}

def _closepin_summary():
    """The accumulated close-pin scoring (ledger/closepin/summary.json) — 30-min
    cache, None until the 14:30 pin has been recorded+scored. Never raises."""
    now = time.time()
    if now < _CLOSEPIN_SUMMARY_CACHE["expires"]:
        return _CLOSEPIN_SUMMARY_CACHE["data"]
    data = None
    try:
        r = requests.get(f"{_LEDGER_RAW_BASE}/closepin/summary.json", timeout=6)
        if r.status_code == 200:
            d = r.json()
            data = d if isinstance(d, dict) else None
    except Exception:
        data = None
    _CLOSEPIN_SUMMARY_CACHE["data"] = data
    _CLOSEPIN_SUMMARY_CACHE["expires"] = now + (1800 if data else 600)
    return data

# ── Ledger Health (v10.36, #5) — one view of every self-scoring loop ─────────
def _days_since_date(date_str):
    """Calendar days since a 'YYYY-MM-DD' string; None if unparseable."""
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        return (datetime.now(TZ_JST).date() - d).days
    except Exception:
        return None

def _ledger_health():
    """Unified operational status of every ledger + the AI loop. Honest about
    empty / stale / healthy — reads the branch summaries + AI truth only."""
    today = datetime.now(TZ_JST).date()
    # how many weekdays since a date (the real expected cadence)
    def weekday_gap(date_str):
        try:
            d = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        except Exception:
            return None
        n, c = 0, d
        while c < today:
            c += timedelta(days=1)
            if c.weekday() < 5:
                n += 1
        return n

    def state(updated, empty_ok=False):
        if not updated:
            return "empty"
        gap = weekday_gap(updated)
        if gap is None:
            return "unknown"
        return "healthy" if gap <= 1 else "stale"

    pred = _ledger_summary() or {}
    scout = _scout_summary() or {}
    cpin = _closepin_summary() or {}
    ai_truth = _ai_judgment_truth()
    ai_cached = _ai_cached_result()                 # the real last run (cache or restored)
    ai_asof = (ai_cached or {}).get("asOf")          # actual run time, not call time
    ai_age = _age_min_iso(ai_asof)
    out = []
    po = pred.get("overall") or {}
    out.append({
        "id": "prediction", "labelJa": "予測台帳(本丸)",
        "status": state(pred.get("updated")), "lastUpdated": pred.get("updated"),
        "sampleCount": po.get("n"), "tradingDays": po.get("days"),
        "hitRate": po.get("hitRate"),
        "nextRunJa": "平日16:05 JST", "trigger": "EC2 cron + GH fallback",
        "staleWeekdays": weekday_gap(pred.get("updated")),
        "noteJa": "毎営業日16:05に当日記録+過去分採点。相関銘柄を含むためnは独立試行ではない。"})
    out.append({
        "id": "scout", "labelJa": "Scout校正(エントリー診断)",
        "status": state(scout.get("updated")), "lastUpdated": scout.get("updated"),
        "sampleCount": scout.get("n"), "tradingDays": None, "hitRate": None,
        "nextRunJa": "平日16:05 JST(予測台帳と同時)", "trigger": "EC2 cron + GH fallback",
        "staleWeekdays": weekday_gap(scout.get("updated")),
        "noteJa": "scoreバケット/フロー分類を実現リターンで採点。最低20件まで参考値。"})
    co = cpin.get("overall") or {}
    out.append({
        "id": "closepin", "labelJa": "引けピン(14:30→同日終値)",
        "status": state(cpin.get("updated")), "lastUpdated": cpin.get("updated"),
        "sampleCount": co.get("n"), "tradingDays": co.get("days"), "hitRate": co.get("hitRate"),
        "nextRunJa": "平日14:30 JST(ピン)+16:05採点", "trigger": "EC2 cron(GHは時刻窓で大抵拒否)",
        "staleWeekdays": weekday_gap(cpin.get("updated")),
        "noteJa": "リアルタイム価格が取れた行のみ採点。bridgeのライブ配信が前提。"})
    # Session-aware: a run at/after the last scheduled 16:05 slot is healthy
    # (current for the latest session); only a genuinely MISSED run is stale.
    ai_fresh = _ai_session_freshness(ai_asof, ai_age) if ai_cached else None
    ai_status = ("empty" if not ai_cached
                 else "stale" if ai_fresh == "stale"
                 else "healthy")
    out.append({
        "id": "ai", "labelJa": "AI判定(GPT-5.5 + Gemini)",
        "status": ai_status,
        "lastUpdated": (ai_asof[:10] if isinstance(ai_asof, str) else None),
        "lastSuccessAt": ai_asof, "ageMin": ai_age,
        "truthStatus": ai_truth.get("status"),
        "models": {"primary": _OPENAI_MODEL, "checker": _GEMINI_JUDGE_MODEL},
        "sampleCount": None, "tradingDays": None, "hitRate": None,
        "nextRunJa": "平日16:05 JST(トークン設定時)", "trigger": "予測台帳cron",
        "noteJa": "ルールベースが主、AIは時刻付き第二意見。失効してもルール判定は不変。"})
    return {"asOf": _ai_now_iso(), "engineVersion": "ledger-health-v1", "ledgers": out}

@app.route("/api/argus/ledger-health")
def api_argus_ledger_health():
    return jsonify(_ledger_health())

_SCOUT_BATCH_CACHE = {"data": None, "expires": 0.0}

def get_scout_batch():
    """Compact, scoreable entry-scout records for the JP active names — the
    daily ledger snapshot for scout calibration. 30-min cache."""
    now = time.time()
    if _SCOUT_BATCH_CACHE["data"] and now < _SCOUT_BATCH_CACHE["expires"]:
        return _SCOUT_BATCH_CACHE["data"]
    recs = []
    for sym in _CLOSEPIN_ACTIVES_JP:
        s = get_entry_scout(sym)
        if not isinstance(s, dict) or s.get("status") != "live":
            continue
        a = s.get("assessment") or {}
        fi = s.get("flowInference") or {}
        recs.append({
            "symbol": sym, "lastClose": s.get("lastClose"), "lastDate": s.get("lastDate"),
            "score": a.get("score"), "bucket": _scout_score_bucket(a.get("score")),
            "stance": a.get("stance"), "flowClass": fi.get("classification"),
        })
    out = {"engineVersion": "scout-ledger-v1",
           "dateJst": datetime.now(TZ_JST).strftime("%Y-%m-%d"),
           "asOf": _ai_now_iso(), "records": recs}
    _SCOUT_BATCH_CACHE["data"] = out
    _SCOUT_BATCH_CACHE["expires"] = now + 1800
    return out

@app.route("/api/argus/scout-batch")
def api_argus_scout_batch():
    return jsonify(get_scout_batch())

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
    # ⑩ Intraday phase (v10.118): the pin is a LATE-day read (full-day context),
    # and 15:25–15:30 is the closing auction — NOT continuous trading. Be explicit
    # so nothing claims continuous quotes or block-trade certainty in that window.
    _jn = datetime.now(pytz.timezone("Asia/Tokyo"))
    _hm = _jn.hour * 60 + _jn.minute
    if _jn.weekday() >= 5:
        phase = "closed_weekend"
    elif _hm < 9 * 60:
        phase = "pre_market"
    elif _hm < 14 * 60 + 30:
        phase = "intraday_pre_pin"
    elif _hm < 15 * 60 + 25:
        phase = "decision_window"      # 14:30–15:25 — heaviest weight, final decision
    elif _hm < 15 * 60 + 30:
        phase = "closing_auction"      # 15:25–15:30 — auction, not continuous trading
    else:
        phase = "closed"
    return {
        "engineVersion": "closepin-v1",
        "asOf": datetime.now(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dateJst": _jn.strftime("%Y-%m-%d"),
        "status": "live" if rows else "no_realtime",
        "marketPosture": posture,
        "intradayPhase": phase,
        "rows": rows,
        "scoringRule": {
            "targetJa": "同日15:30の終値がピン価格に対してどのバケットに着地するか",
            "buckets": {"flatWithinPct": _CLOSEPIN_BANDS[0], "strongBeyondPct": _CLOSEPIN_BANDS[1]},
            "noteJa": "リアルタイム価格(moomooブリッジ)が取れた銘柄のみピン。T-1価格では当日予測にならないため除外。",
        },
        "dataLimitations": [
            "ピンは大引け前(全日の値動きを織り込んだ後半の読み)。14:30→15:25が最終判断窓。",
            "15:25–15:30は引け条件(クロージング・オークション)で連続売買ではない。連続的な気配は前提にしない。",
            "板(L2)/VWAP/ティック未取得のため、ブロック取引・新規ロングの断定はしない。",
        ],
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


def _v4_record_meta(symbol):
    """Calibration Ledger v4 per-record metadata (Phase 3, v10.71).

    Additive enrichment for each recorded prediction/sensor: the v4 cohort, its
    factor group, any experimental flags, and the market-specific forecast clock
    (correct origin session + 1/3/5 trading-day target dates per market). Recorded
    ALONGSIDE the legacy `layer`/`scenarios` fields — nothing existing changes, so
    the current scorer keeps working while the workflow can adopt the per-market
    target dates next. Best-effort: never raises into the recording path."""
    try:
        clk = argus_market_clock.forecast_clock(symbol)
        compact = {
            "market": clk.get("market"),
            "marketCalendar": clk.get("marketCalendar"),
            "timezone": clk.get("timezone"),
            "originTradingDate": clk.get("originTradingDate"),
            "targets": clk.get("targets"),
            "calendarVersion": clk.get("calendarVersion"),
        }
        return {
            "cohortId": argus_calibration.classify_cohort(symbol),
            "factorGroup": argus_calibration.factor_group_of(symbol),
            "experimentalFlags": [f["flag"] for f in argus_calibration.experimental_flags(symbol)],
            "marketClock": compact,
            "calibrationSchema": argus_calibration.SCHEMA_VERSION,
        }
    except Exception:
        return {"calibrationSchema": argus_calibration.SCHEMA_VERSION}


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
        rec = {
            "symbol": l["symbol"], "market": l["market"], "name": l["name"],
            "layer": _layer_of(l["symbol"]),
            "price": q["price"], "changePct": sd.get("changePct"),
            "action": l["action"], "confidence": l["confidence"],
            "scenarios": [{"label": s, "p": p} for s, p in _scenarios_for(sd.get("changePct"))],
            "flowRatio": sd.get("bigFlowRatio"),
            "ai": ai_by_sym.get(l["symbol"]),
        }
        rec.update(_v4_record_meta(l["symbol"]))  # cohort + market-clock (v10.71)
        predictions.append(rec)

    # ── Fixed Tactical Benchmark v2 (v10.72) ──
    # Record the 14-name fixed benchmark INDEPENDENT of the owner/display
    # watchlist, so longitudinal comparison survives watchlist churn. De-duped
    # against the action-label predictions above. Defensive: a failure here must
    # never break the daily recording.
    try:
        recorded = {p["symbol"] for p in predictions}
        bench = [s for s in argus_calibration.TACTICAL_BENCHMARK if s not in recorded]
        bjp = [s for s in bench if s[0].isdigit()]
        bus = [s for s in bench if not s[0].isdigit()]
        bprice = {}
        if bjp:
            for s in (get_japan_watchlist_snapshot(bjp).get("stocks") or []):
                if s.get("status") == "live":
                    bprice[s["symbol"]] = s
        if bus:
            for s in (get_us_watchlist_snapshot(bus).get("stocks") or []):
                if s.get("status") == "live":
                    bprice[s["symbol"]] = s
        for sym in bench:
            q = bprice.get(sym)
            if not q:
                continue
            chg = q.get("changePct")
            brec = {
                "symbol": sym, "market": ("JP" if sym[0].isdigit() else "US"),
                "name": argus_calibration.display_name(sym) or sym,
                "price": q.get("price"), "changePct": chg,
                "scenarios": [{"label": s, "p": p} for s, p in _scenarios_for(chg)],
                "benchmarkOnly": True,  # not owner-watched; fixed-benchmark record
            }
            brec.update(_v4_record_meta(sym))
            predictions.append(brec)
    except Exception:
        pass  # benchmark enrichment is best-effort

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
            _sr = _sensor_row(sym, name, "equity_jp", q["price"], q.get("changePct"))
            _sr.update(_v4_record_meta(sym))
            sensors.append(_sr)
    _ensure_sensor_etfs()
    for sym in _L1_SENSORS_US:
        st = _ETF_LAST_PRICE.get(sym)
        if st and now_ts - st["ts"] <= 12 * 3600:
            _sr = _sensor_row(sym, sym, "etf_us", st["price"], st["m1d"])
            _sr.update(_v4_record_meta(sym))
            sensors.append(_sr)
    for q in (cw.get("quotes") or []):
        if q.get("id") == "bitcoin" and q.get("status") == "live":
            _sr = _sensor_row("BTC", "Bitcoin", "crypto", q["priceUsd"], q.get("changePct"))
            _sr.update(_v4_record_meta("BTC"))
            sensors.append(_sr)
    # Context Variables (v2): USDJPY/VIX (+ yields/HY OAS when available) are
    # RECORDED for regime context but NOT scored as equal return-sensors — VIX is
    # inverse-risk, USDJPY is context-dependent, yields/OAS are levels not returns.
    rates = get_rates_snapshot()
    context_vars = []
    for ctxId, key, sid, sname in (("fx_usdjpy", "usdJpy", "USDJPY", "USD/JPY"),
                                   ("volatility_vix", "vix", "VIX", "VIX")):
        s = rates.get(key) if isinstance(rates, dict) else None
        if s and s.get("status") == "live" and s.get("latestValue") is not None:
            lvl = float(s["latestValue"])
            ch = s.get("change")
            chg_pct = (round(ch / (lvl - ch) * 100, 2)
                       if isinstance(ch, (int, float)) and (lvl - ch) else None)
            context_vars.append({
                "contextId": ctxId, "symbol": sid, "name": sname,
                "value": lvl, "changePct": chg_pct, "asOf": s.get("asOf"),
                "role": "context_variable",  # explanatory, not return-scored
            })

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
        "universeVersion": argus_calibration.UNIVERSE_VERSION,
        "tacticalBenchmarkVersion": argus_calibration.TACTICAL_BENCHMARK_VERSION,
        "factorGroupVersion": argus_calibration.FACTOR_GROUP_VERSION,
        "context": {
            "posture": posture_label,
            "regimeConfidence": rg.get("confidence"),
            "vixZone": (vol or {}).get("zone"),
            "vixLevel": (vol or {}).get("level"),
            "backdrop": rb.get("posture"),
            "aiStatus": ai_status,
        },
        "sensors": sensors,                    # Layer 1 — fixed 16 regime sensors (v2)
        "contextVariables": context_vars,      # recorded but NOT return-scored (v2)
        "predictions": predictions,            # cohort rows (see .cohortId / .layer)
        "classPredictions": class_predictions, # legacy continuity (v10.5 axis)
        "posturePrediction": posture_prediction,
        "scoringRule": {
            "horizonsTradingDays": [1, 3, 5],
            "bucketsNote": "per-row bandPct (≈daily sigma): downside < -band, sideways within ±band, rebound > +band; legacy rows band=2%",
            "metrics": ["argmaxHit", "brier"],
        },
    }

_PREDICTION_SNAPSHOT_CACHE = {"data": None, "expires": 0.0}

@app.route("/api/argus/prediction-snapshot")
def api_argus_prediction_snapshot():
    # Cache 90s: the v2 snapshot fetches ~11 JP names (4 sensors + 7 benchmark) +
    # US/ETF, so an uncached public endpoint would hammer J-Quants (429s). The
    # daily recording reads at most once per cache window, so freshness is fine.
    now = time.time()
    if _PREDICTION_SNAPSHOT_CACHE["data"] and now < _PREDICTION_SNAPSHOT_CACHE["expires"]:
        return jsonify(_PREDICTION_SNAPSHOT_CACHE["data"])
    snap = get_prediction_snapshot()
    _PREDICTION_SNAPSHOT_CACHE["data"] = snap
    _PREDICTION_SNAPSHOT_CACHE["expires"] = now + 90
    return jsonify(snap)

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
    L.append("- Action Level (the canonical signal, schema " + argus_signal.SIGNAL_SCHEMA_VERSION + "): a 7-level"
             " CAPITAL-DEPLOYMENT PERMISSION scale, NOT model confidence and NOT market regime. Higher = freer to deploy:")
    L.append("  7 ENTER (new-entry allowed) / 6 PREPARE / 5 HOLD_ONLY (hold existing only, no new entry) /"
             " 4 PAUSE (no new entry) / 3 REVIEW (reassess now) / 2 DEFEND (protect capital) / 1 EXIT (exit position).")
    L.append("  Legacy labels map onto it (HOLD→HOLD_ONLY, WAIT→PAUSE, TRIM→DEFEND, ADD→ENTER, …); each action-label"
             " row in section 3 carries a structured `signal{code,level,permissions}`. A material/unexplained drop can"
             " never stay a plain HOLD. Decision-support only — ARGUS never places an order.")
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

    # ── Institutional Intelligence (research mesh — public metadata only) ──
    inst_items = [i for i in _INTEL_STORE if i.get("institutionId")]
    rss_n = sum(1 for s in argus_research_mesh.SOURCE_RIGHTS.values() if s.get("collection") == "rss")
    L.append("## Institutional Intelligence (research mesh — public metadata)")
    L.append(f"- Public sources monitored: {rss_n} RSS/sitemap feeds "
             "(Bloomberg EN+JP, CNBC, MarketWatch, Nasdaq, Yahoo Finance, Federal Reserve, SEC). "
             "Licensed feeds (Bloomberg EDF / LSEG / Factiva / RavenPack) NOT configured.")
    if inst_items:
        L.append(f"- Named institutional VIEWS detected: {len(inst_items)} "
                 "(a NAMED VIEW is reported context — NOT a trading position; confirmed vs reported vs inferred kept separate).")
        for it in inst_items[:8]:
            nm = (argus_research_mesh.INSTITUTIONS.get(it.get("institutionId"), {}).get("canonicalName")
                  or it.get("institutionId"))
            assets = ",".join(it.get("linkedAssets") or []) or "—"
            L.append(f"  - {nm} [{it.get('contentType')}] {it.get('publishedAt') or ''} "
                     f"assets={assets} stance={it.get('stance')} :: {(it.get('title') or '')[:100]} "
                     f"({it.get('sourceId')}, accessClass={it.get('accessClass')})")
    else:
        L.append("- No named institutional views in the current window (store warming or no material institutional news).")
    L.append("- CHALLENGE THESE (please push back): (a) any DIRECT-CAUSE claim — is an institutional comment really the "
             "trigger, or did it post-date the move (amplifier)? (b) any NAMED-INSTITUTION TRADING claim — a view is not "
             "a trade; reject 'X sold' from 'X is cautious'. (c) report TIMING vs the price-move start. (d) DUPLICATE-SOURCE "
             "false confirmation (one wire across outlets = one origin, not N). (e) is the interpretation BALANCED (both "
             "bull and bear preserved)? (f) does any new intelligence actually change the Action Level / permission?")
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

_PRO_TYPE_JA = {"LIMIT_UP": "S高", "LIMIT_DOWN": "S安", "LIMIT_UP_PROXIMITY": "S高接近",
                "LIMIT_DOWN_PROXIMITY": "S安接近", "PRICE_SPIKE": "急騰", "PRICE_CRASH": "急落",
                "VOLUME_ANOMALY": "出来高急増", "FLOW_ANOMALY": "大口フロー異常",
                "CRYPTO_SHOCK": "暗号資産ショック", "MOMENTUM_ACCELERATION": "急加速",
                "FLOW_REVERSAL": "フロー反転", "VOLUME_ACCELERATION": "出来高加速",
                "MARKET_MOVER": "全市場ムーバー"}

def _pro_events_section():
    """The active 24/7 events + their deterministic dossiers, as a compact prompt
    block for the GPT-5.5 Pro Handoff (GPT #12). Separates confirmed facts from
    inference; carries the no-auto-trading disclaimer. No model call, no secrets."""
    try:
        _events_restore_once()
        active = _events_active_list()
    except Exception:
        active = []
    if not active:
        return ""
    out = ["## 8. 24/7 検知中イベント + 調査ドシエ(決定論・LLM未使用 / 売買指示ではない)"]
    for e in active[:5]:
        d = e.get("dossier")
        if not d:
            try:
                d = _build_event_dossier(e)
            except Exception:
                d = None
        nm = e.get("nameJa")
        sym = f"{nm}({e.get('symbol')})" if nm else e.get("symbol")
        t = _PRO_TYPE_JA.get(e.get("eventType"), e.get("eventType"))
        if not d:
            out.append(f"■ {sym} {t}(sev{e.get('severity')}) — {e.get('reasonJa')}")
            continue
        cause = "、".join(f"{c['label']}{int(c['probability']*100)}%" for c in (d.get("probableCause") or [])[:3])
        scen = "、".join(f"{s['label']}{int(s['probability']*100)}%" for s in (d.get("nextSessionScenarios") or [])[:3])
        facts = d.get("confirmedFacts") or []
        facts_txt = "; ".join(f.get("claimJa") or "" for f in facts) if facts else "公式の確認済み事実なし(報道/観測のみ)"
        out += [
            f"■ {sym} {t}(sev{e.get('severity')} / posture {d.get('researchPosture')} / 証拠カバレッジ{int((d.get('researchConfidence') or 0)*100)}%・未較正)",
            f"  起きたこと: {d.get('whatHappenedJa')}",
            f"  市場範囲: {d.get('marketScope')} / 推定原因: {cause}",
            f"  次セッション: {scen}",
            f"  罠リスク: {'、'.join(d.get('trapRisks') or []) or 'なし'}",
            f"  反証(レビュー {d.get('reviewVerdict')}): {'; '.join(d.get('reviewObjectionsJa') or []) or 'なし'}",
            f"  無効化条件: {'; '.join(d.get('invalidationConditions') or []) or '—'}",
            f"  欠損データ: {'; '.join(d.get('missingData') or []) or 'なし'}",
            f"  確認済み事実: {facts_txt}",
        ]
    out.append("(上記は決定論的に組み立てた論点整理です。事実・推論・欠損を区別し、確率は較正されていません。)")
    return "\n".join(out)

def _pro_downside_section():
    """Pro Handoff #9: active downside incidents + cause matrix. Explicitly asks
    GPT-5.5 Pro to challenge whether HOLD is still valid (v10.98)."""
    try:
        d = get_downside_incidents()
    except Exception:
        return ""
    incs = d.get("incidents") or []
    ov = d.get("overlay") or {}
    if not incs and ov.get("jpIntradayOverlay", "NORMAL") == "NORMAL":
        return ""
    out = ["## 9. ダウンサイド・インシデント + 原因アトリビューション(決定論 / 売買指示ではない)"]
    out.append(f"地合いオーバーレイ: {ov.get('displayJa', '')} / 保有リスク: {ov.get('holderRiskOverlay', 'NONE')}")
    for i in incs[:8]:
        held = "【保有】" if i.get("isHeld") else "【監視】"
        causes = "・".join(f"{c['cause']} {int(round(c['probability']*100))}%" for c in i.get("causeBuckets", [])[:3])
        out.append(
            f"■ {held}{i.get('symbol')}({i.get('assetName')}) {i.get('changePct')}% "
            f"sev{i.get('severity')} / 現ラベル {i.get('currentAction')} → 上書き {i.get('actionOverride')}\n"
            f"  推定原因: {causes}\n"
            f"  理由: {i.get('reasonJa')}\n"
            f"  やってはいけない: {i.get('doNotDoJa')}\n"
            f"  次の確認条件: {i.get('nextConditionJa')}\n"
            f"  欠損データ: {'/ '.join(i.get('missingData') or []) or 'なし'}")
    out.append("\n■ GPT-5.5 Proへの依頼: 上記の各銘柄について、現行のHOLD(または上書き後のアクション)が"
               "保有者にとって本当に妥当かを批判的に検証してほしい。特に『原因未確認の急落』を安全と誤認していないか、"
               "買い増し回避・縮小・撤退検討のいずれが妥当か、反証(なぜHOLDでよいか)も併せて示してほしい。"
               "※ARGUSは自動売買を行わない。最終判断は本人。")
    return "\n".join(out)


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
    ev_section = _pro_events_section()           # active 24/7 events + dossiers (#12)
    if ev_section:
        prompt = prompt + "\n\n" + ev_section
    ds_section = _pro_downside_section()         # active downside incidents + cause matrix (#9, v10.98)
    if ds_section:
        prompt = prompt + "\n\n" + ds_section
    # v11.6.0: Institutional Intelligence Summary — supportive vs opposing vs
    # conditional public signals, missing evidence, direct/background split.
    try:
        ho = argus_institutional_intel.handoff_summary(_institutional_signals(cap=40)[:20])
        lines = [f"## {ho['title']}",
                 f"(direct={ho['directCount']} related={ho['relatedCount']} "
                 f"background={ho['backgroundCount']})"]
        for label, key in (("Supportive", "supportive"), ("Opposing", "opposing"),
                           ("Conditional/Mixed", "conditional")):
            if ho.get(key):
                lines.append(f"### {label}")
                lines += [f"- {x}" for x in ho[key]]
        if ho.get("missingEvidence"):
            lines.append("### Missing evidence")
            lines += [f"- {x}" for x in ho["missingEvidence"]]
        lines.append(f"注意: {ho['disclaimerJa']}")
        prompt = prompt + "\n\n" + "\n".join(lines)
    except Exception:
        pass
    # v11.7.0: Big Money / Flow Attribution — likely accumulation vs covering vs
    # distribution candidates + strongest opposing interpretation + missing evidence.
    try:
        fh = argus_flow_attribution.handoff_section(_flow_attribution_list(cap=20))
        flines = [f"## {fh['title']}"]
        for label, key in (("Likely accumulation (可能性)", "likelyAccumulation"),
                           ("Likely short covering (可能性)", "likelyShortCovering"),
                           ("Distribution / profit-taking risk", "distributionRisks"),
                           ("Avoid chase (追いかけ買い注意)", "avoidChase")):
            if fh.get(key):
                flines.append(f"### {label}")
                flines += [f"- {x}" for x in fh[key]]
        if fh.get("missingEvidence"):
            flines.append("### Missing evidence (top)")
            flines += [f"- {m} ×{c}" for m, c in fh["missingEvidence"]]
        flines.append(fh["opposingViewJa"])
        flines.append(f"注意: {fh['disclaimerJa']}")
        if len(flines) > 3:                      # only when there is real content
            prompt = prompt + "\n\n" + "\n".join(flines)
    except Exception:
        pass
    # v11.10.0: Supply / Demand Summary (JP) — best/worst/squeeze/overhang with
    # direct-vs-inferred separation and the covering-≠-accumulation discipline.
    try:
        sh = argus_supply_demand.handoff_section(_supply_demand_list(cap=12))
        slines = [f"## {sh['title']}",
                  f"(direct={sh['directCount']} inferred={sh['inferredCount']})"]
        for label, key in (("Best (S/A)", "best"), ("Watch-positive (B)", "watchPositive"),
                           ("Squeeze-prone (踏み上げ候補)", "squeezeProne"),
                           ("Credit overhang (信用買い残重い)", "creditOverhang"),
                           ("Worst (D/E)", "worst")):
            if sh.get(key):
                slines.append(f"### {label}")
                slines += [f"- {x}" for x in sh[key]]
        if sh.get("missingEvidence"):
            slines.append("### Missing evidence")
            slines += [f"- {x}" for x in sh["missingEvidence"]]
        slines.append(sh["sourceLimitJa"])
        slines.append(f"注意: {sh['disclaimerJa']}")
        if len(slines) > 3:
            prompt = prompt + "\n\n" + "\n".join(slines)
    except Exception:
        pass
    # v11.17.0: Scenario Set — 条件付き分岐(watchlist-level)。単一予測ではなく
    # 支配シナリオ+反対シナリオ+無効化条件をProに渡す。確率は帯のみ。
    try:
        sch = argus_scenario.handoff_section(_scenario_list(cap=8))
        sclines = [f"## {sch['title']} (watchlist-level, 条件付き分岐)"]
        sclines += [f"- {x}" for x in sch.get("top") or []]
        sclines.append(sch["opposingJa"])
        sclines.append(f"注意: {sch['disclaimerJa']}")
        if len(sclines) > 3:
            prompt = prompt + "\n\n" + "\n".join(sclines)
    except Exception:
        pass
    # v11.18.0: Entry / Exit Planning — 計画(watchlist-level)。執行語なし。
    try:
        ph = argus_trade_plan.handoff_section(_trade_plan_list(cap=12))
        plines = [f"## {ph['title']} (watchlist-level, 計画であり指示ではない)"]
        for label, key in (("小さく試し玉候補(注意付き)", "entryCandidates"),
                           ("押し目限定", "pullbackOnly"),
                           ("追いかけ買い注意", "avoidChase"),
                           ("利確検討/リスク確認", "trimRiskReview"),
                           ("イベント待ちでブロック中", "eventWaitBlocked")):
            if ph.get(key):
                plines.append(f"### {label}")
                plines += [f"- {x}" for x in ph[key]]
        if ph.get("missingEvidence"):
            plines.append("### 証拠不足(計画保留)")
            plines += [f"- {x}" for x in ph["missingEvidence"]]
        plines.append(ph["invalidationJa"])
        plines.append(f"注意: {ph['disclaimerJa']}")
        if len(plines) > 3:
            prompt = prompt + "\n\n" + "\n".join(plines)
    except Exception:
        pass
    # v11.13.0: Session Brief — 今日の作戦 (watchlist-level; held-aware version
    # is appended by the app at copy time).
    try:
        shh = argus_session_brief.handoff_section(_session_brief_public())
        blines = [f"## {shh['title']} (watchlist-level)",
                  f"モード: {shh['modeJa']} — {shh['headlineJa']}", shh["summaryJa"] or ""]
        if shh.get("whatNotToDo"):
            blines.append("やらないこと: " + " / ".join(shh["whatNotToDo"]))
        if shh.get("nextChecks"):
            blines.append("次の確認: " + " / ".join(shh["nextChecks"]))
        blines.append(f"注意: {shh['disclaimerJa']} {shh['caveatJa']}")
        prompt = prompt + "\n\n" + "\n".join(x for x in blines if x)
    except Exception:
        pass
    # v11.12.0: Action Priority Summary — watchlist-level attention routing.
    try:
        ah = argus_action_priority.handoff_section(_action_priority_items(cap=15))
        alines = [f"## {ah['title']} (watchlist-level)"]
        for label, key in (("Top (P0/P1)", "top"), ("Blocked by event", "blocked"),
                           ("押し目限定候補", "pullbackAdds"), ("追いかけ買い注意", "avoidChase"),
                           ("今日は重要度低", "ignored")):
            if ah.get(key):
                alines.append(f"### {label}")
                alines += [f"- {x}" for x in ah[key]]
        if ah.get("missingEvidence"):
            alines.append("### Missing evidence")
            alines += [f"- {x}" for x in ah["missingEvidence"]]
        alines.append(f"注意: {ah['disclaimerJa']} 実保有を加味した優先度はアプリ側で付加。")
        if len(alines) > 2:
            prompt = prompt + "\n\n" + "\n".join(alines)
    except Exception:
        pass
    # v11.8.0: Position / Exposure Summary — WATCHLIST-LEVEL only. The server
    # never knows real holdings; the app appends the device-local summary when
    # the owner copies the prompt.
    try:
        ph = argus_position_exposure.handoff_section(
            argus_position_exposure.watchlist_theme_exposure(_watchlist_theme_items()))
        plines = [f"## {ph['title']}"]
        plines += [f"- {k}: {v}銘柄" for k, v in list(ph["byThemeJa"].items())[:8]]
        if ph.get("heavyThemes"):
            plines.append(f"偏りが強いテーマ: {' / '.join(ph['heavyThemes'])}")
        plines.append(ph["privacyNoteJa"])
        plines.append(ph["opposingViewJa"])
        plines.append(f"注意: {ph['disclaimerJa']}")
        prompt = prompt + "\n\n" + "\n".join(plines)
    except Exception:
        pass
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
    """Relevance-ranked JP search. Previously it returned matches in raw master order,
    so a name query like "三菱" surfaced MAXIS ETFs before 三菱商事. Now results are
    ranked: exact code → code prefix → name STARTS-WITH → name substring, so the obvious
    stock comes first (v11.1)."""
    ql = q.lower()
    qu = q.upper()
    code_like = _jp_query_is_code(q)
    scored = []
    for r in _jq_master():
        code = r["code4"].upper()
        ja, en = (r["ja"] or ""), (r["en"] or "")
        jal, enl = ja.lower(), en.lower()
        rank = None
        if code_like and code == qu:
            rank = 0                                   # exact code
        elif code_like and code.startswith(qu):
            rank = 1                                   # code prefix
        elif jal.startswith(ql) or enl.startswith(ql):
            rank = 2                                   # name starts with the query
        elif ql in jal or ql in enl:
            rank = 3                                   # name contains the query
        if rank is not None:
            # Deprioritise ETFs/funds: a name query like "三菱" should surface 三菱商事,
            # not the "三菱UFJ-MAXIS…" ETF family that also starts with 三菱. Exact/prefix
            # CODE hits are unaffected (is_etf only breaks ties within a text rank).
            is_etf = ("etf" in enl or "上場投信" in ja or "投信" in ja
                      or "リート" in ja or "reit" in enl
                      or str(r.get("mkt", "")).upper() in ("ETF", "REIT", "ETN"))
            scored.append((rank, 1 if is_etf else 0, code,
                           {"symbol": r["code4"], "name": en or ja, "nameJa": ja,
                            "exchange": r["mkt"], "type": "jp_equity"}))
    scored.sort(key=lambda x: (x[0], x[1], x[2]))
    out = [x[3] for x in scored[:_SEARCH_MAX]]
    return out, ("live" if _jq_master() else "unavailable")

def _search_us(q):
    if not _TWELVEDATA_API_KEY:
        return [], "unavailable"
    try:
        r = requests.get("https://api.twelvedata.com/symbol_search",
                         params={"symbol": q, "outputsize": 20, "apikey": _TWELVEDATA_API_KEY}, timeout=10)
        r.raise_for_status()
        data = r.json().get("data", []) if isinstance(r.json(), dict) else []
        out, seen = [], set()
        for x in data:
            t = (x.get("instrument_type") or "").lower()
            if "stock" not in t and "etf" not in t and t:   # prefer equities/ETFs
                continue
            sym = x.get("symbol", "")
            if not sym or sym in seen:                       # dedupe cross-exchange listings
                continue
            seen.add(sym)
            out.append({"symbol": sym, "name": x.get("instrument_name", ""),
                        "nameJa": "", "exchange": x.get("exchange", ""), "type": "us_equity"})
            if len(out) >= _SEARCH_MAX:
                break
        return out, "live"
    except Exception:
        return [], "error"

def _search_crypto(q):
    try:
        # CoinGecko blocks/limits datacenter IPs (Render) unless a real User-Agent +
        # (optional) demo key are sent — the same fix as the price fetch. Without these
        # the search silently 403/429'd and returned "error" from production. (v11.1)
        headers = {"User-Agent": "argus-research/1.0", "Accept": "application/json"}
        if _COINGECKO_KEY:
            headers["x-cg-demo-api-key"] = _COINGECKO_KEY
        r = requests.get("https://api.coingecko.com/api/v3/search",
                         params={"query": q}, headers=headers, timeout=10)
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

_LAST_INTEL_REFRESH = [0.0]
_MISSION_STORE = {}        # eventId -> latest deterministic mission result
_MISSION_DEBOUNCE = {}     # eventId -> last-run epoch (re-mission at most every TTL)
_MISSION_TTL = 1800        # 30 min per event
_MISSION_MAX_PER_TICK = 3

def _dispatch_research_missions(nowt):
    """Evaluate mission triggers and run the DETERMINISTIC swarm (LLM calls = 0, so no
    budget) for the top few, debounced per event. Stores the gated ARGUS view. No LLM
    escalation here (kept manual/gated) — this is the free, safe auto-dispatch."""
    try:
        held = list(_intel_watchlist_symbols())
        ds = (get_downside_incidents().get("incidents") or [])
        try: evs = get_events_snapshot().get("events") or []
        except Exception: evs = []
        intel = list(_INTEL_STORE)[:80]
    except Exception:
        return
    triggers = argus_mission_trigger.plan_triggers(
        downside_incidents=ds, important_events=evs, new_intel=intel,
        held_symbols=held, watch_symbols=held)
    ran = 0
    for tr in triggers:
        if ran >= _MISSION_MAX_PER_TICK:
            break
        eid = tr["eventId"]
        if nowt - _MISSION_DEBOUNCE.get(eid, 0) < _MISSION_TTL:
            continue                                   # debounce: don't re-mission each tick
        _MISSION_DEBOUNCE[eid] = nowt
        try:
            ev = argus_mission_trigger.to_event(tr)
            m = argus_research_swarm.run_mission(ev, intel, context={"ownerRelevant": tr["ownerRelevant"]})
            _MISSION_STORE[eid] = {"trigger": tr, "argusView": m.get("argusView"),
                                   "adversarialFlags": m.get("adversarialFlags"),
                                   "confidence": m.get("confidence"), "at": _ai_now_iso()}
            ran += 1
        except Exception:
            pass
    # cap store size
    if len(_MISSION_STORE) > 40:
        for k in sorted(_MISSION_STORE, key=lambda x: _MISSION_STORE[x].get("at") or "")[:len(_MISSION_STORE) - 40]:
            _MISSION_STORE.pop(k, None)

@app.route("/api/argus/research-missions")
def api_argus_research_missions():
    """Recent deterministic research missions (auto-dispatched on triggers). Read-only."""
    items = sorted(_MISSION_STORE.values(), key=lambda x: x.get("at") or "", reverse=True)[:20]
    return jsonify({"count": len(_MISSION_STORE), "missions": items})

def _residency_ai_tick():
    """Resident replacement for the flaky GitHub */15 cron (v10.191). Keeps the
    public-feed intel mesh warm and, during market hours, re-runs the AI judgment +
    RECOMMEND — self-gated by the SAME budget / 14-min interval / daily cap as the
    /ai-judgment/run route, so it's idempotent with any cron still firing (double
    fire → the gate blocks the second). Never raises (that would kill the scheduler
    thread). Decision-support only — no order/broker path is created here."""
    try:
        nowt = time.time()
        if nowt - _LAST_INTEL_REFRESH[0] > 600:      # free public RSS; ≤ every 10 min
            _LAST_INTEL_REFRESH[0] = nowt
            try:
                collect_institutional_intel()
            except Exception:
                pass
            try:
                _dispatch_research_missions(nowt)     # deterministic (free) — runs off-hours too
            except Exception:
                pass
        if not (_jp_market_open() or _us_market_open()):
            return                                    # only spend AI budget in-session
        allowed, _info, _code = _ai_run_gate(force=False)   # budget + interval + daily cap
        if not allowed:
            return
        _execute_ai_judgment(run_mode="scheduled", checker="flash")
        try:
            _buy_candidates_generate()
        except Exception:
            pass
    except Exception as e:
        add_log(f"[residency] AI tick failed: {type(e).__name__}")

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
        # Resident AI + intel tick (v10.191) — replaces the unreliable GitHub */15
        # cron. Spawn on 5-min boundaries; the tick self-throttles (intel ≤10min,
        # AI via the run gate's 14-min interval), so a double spawn is harmless.
        if now.minute % 5 == 0:
            threading.Thread(target=_residency_ai_tick, daemon=True).start()
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
