import React from 'react';
import { PageShell } from './PageShell';
import { IntegrationsPanel } from '../components/guide/IntegrationsPanel';
import '../components/dashboard/Dashboard.css';

// ── できること / 最近のアップデート ──────────────────────────────
// RULE (v9.10.1+): バージョンアップのたびに、この2つのリストも必ず更新する。
// アプリ内の説明書は常に「現在の実力」を正確に語ること（HANDOFF.md にも明記）。
const CAPABILITIES: { area: string; descJa: string }[] = [
  { area: '今日の判断 (Today)',
    descJa: '市場全体の姿勢(WAIT/HOLD等)・リスク・理由・触るもの/避けるもの・次に待つ条件を、金利/レジーム/イベント/価格からライブ合成。開いて10秒で今日の構えが分かる。' },
  { area: 'Watchlist',
    descJa: '銘柄を検索して追加(日本株/米国株/投信/暗号資産)・ドラッグ並べ替え。追加した銘柄には自動でライブ価格+ルールベースの行動ラベル+戦略カード(理由/次の条件/シナリオ確率)が付く。' },
  { area: '価格データ',
    descJa: '日本株=J-Quants(前日終値)、米国株=Twelve Data、暗号資産=CoinGecko。moomooブリッジ稼働中は日米株がリアルタイムに自動アップグレード(途絶時は自動フォールバック)。古いデータは「delayed」表示+確信度を自動で下げる。' },
  { area: 'Market Regime',
    descJa: '資金がどこへ回転しているか(ETF proxy)とレジーム(RISK_ON〜EVENT_WAIT)をルールベースで判定。行動ラベルにも反映。' },
  { area: 'Event Radar',
    descJa: 'FOMC/CPI/雇用/日銀/国債入札などの公式カレンダーをD-7→D+1でエスカレーション表示。' },
  { area: 'Corporate Catalysts',
    descJa: '決算日・開示・ニュースのメタデータ(SEC EDGAR/Finnhub/J-Quants)。' },
  { area: '判断ログ (記憶)',
    descJa: '毎日の判断を端末内に記録し「昨日からの変化」と直近7日の判断を表示(この端末のみ)。' },
  { area: '通知 (エージェント)',
    descJa: '日本株の寄り前8:30と米国株の寄り前22:00にダイジェスト、市場時間中(7〜24時)は「姿勢の変化・イベント接近・市場ストレス急変(VIX/信用スプレッド)」の時だけアラートをスマホへpush(ntfy設定時)。通知タップでアプリが開く。' },
  { area: 'AI',
    descJa: 'GPT-5.5 Pro Handoff=手動コピペで無料の深掘り相談。自動AI判断(GPT-5.5+Gemini二重チェック)=管理者実行・キャッシュ閲覧のみ公開。下のAPI statusに現在の状態が常に出る。' },
  { area: '正直さの原則',
    descJa: '全データに live/partial/mock/delayed を明示。ARGUSは予測ではなく「現在の分類」。シナリオ確率は予言ではなく状況整理。' },
];

const RECENT_UPDATES: [string, string][] = [
  ['v9.11.0', 'moomooブリッジ=日米株リアルタイム価格(quote-push)・通知をJP寄り前8:30/US寄り前22:00の2本に・市場ストレス急変アラート・通知文面の読みやすさ改善'],
  ['v9.10.0', '変化検知アラート(変化時のみ通知)・判断コアのユニットテスト+CI・APIレート制限・AIキー疎通ping'],
  ['v9.9.0',  '判断ログ(昨日からの変化+7日履歴)・朝ダイジェスト通知(ntfy)'],
  ['v9.8.0',  '追加した銘柄に自動でライブ価格+行動ラベル(エンジン接続)・データ鮮度の正直表示'],
  ['v9.7.0',  'Todayの判断をライブ合成化(モック廃止)・暗号資産ライブ価格(CoinGecko)'],
  ['v9.6.0',  'API接続状況パネル(この下)・AIステータスの真実化(キー未設定をliveと言わない)'],
];

// 用語一覧 — English chrome term → Japanese meaning.
const GLOSSARY: [string, string][] = [
  ['Today', '今日の判断'],
  ['Action Alerts', '行動アラート'],
  ['Market Regime', '市場レジーム'],
  ['Event Radar', 'イベント監視'],
  ['Watchlist', '監視リスト'],
  ['Core Portfolio', '長期コア資産'],
  ['Capital Rotation', '資金回転'],
  ['Regime Matrix', 'レジーム行列'],
  ['Top Rotations', '注目資金移動'],
  ['Action Label', '行動ラベル'],
  ['Risk', 'リスク'],
  ['Confidence', '確信度'],
  ['Catalyst', '材料・きっかけ'],
  ['Scenario Probabilities', 'シナリオ確率'],
  ['Rescan', '再スキャン'],
  ['Pro Handoff', 'Pro確認用コピー'],
  ['AI Review', 'AIレビュー'],
  ['WAIT', '待機'],
  ['HOLD', '保有継続'],
  ['WAIT FOR PULLBACK', '押し目待ち'],
  ['BUY DIP', '下落時の買い候補'],
  ['ADD', '追加'],
  ['TRIM', '一部利確 / 縮小'],
  ['EXIT', '撤退'],
  ['CONTINUE', '継続'],
  ['GRADUAL ADD', '段階的追加'],
  ['DEFER LUMP SUM', '一括投入見送り'],
  ['NO SELL ACTION', '売却不要'],
];

const HOWTO: string[] = [
  'まず Today で今日の姿勢(市場全体のスタンス)を確認します。',
  'Watchlist で個別銘柄の行動ラベルを見ます。行をタップすると戦略・理由・次に待つ条件が開きます。',
  'Event Radar で重要イベント(FOMC・CPI・決算・国債入札など)の接近を確認します。',
  'Action label は売買の指示ではなく、判断の整理です。迷うときは WAIT / HOLD 寄りに考えます。',
  'Pro Handoff は GPT-5.5 Pro に手動で深く相談したいときにプロンプトをコピーします(自動課金なし)。',
  'Scenario probabilities は予言ではなく、現在のデータに基づく短期のリスク配分です。',
  'データが partial / mock のときは、その銘柄の判断は弱めに受け取ってください。',
  '長期コア資産(Core)は短期の値動きで売買せず、積立方針の維持が基本です。',
];

export const Guide: React.FC = () => {
  return (
    <PageShell title="Glossary / Guide" subtitle="ARGUS でできること・用語一覧・使い方(日本語ガイド)。">
      <section>
        <div className="section-head">
          <span className="section-head__title">ARGUS でできること</span>
          <span className="section-head__count">v{__APP_VERSION__} 時点</span>
        </div>
        <div className="card guide-card">
          <div className="guide-caps">
            {CAPABILITIES.map((c) => (
              <div className="guide-cap" key={c.area}>
                <span className="guide-cap__area">{c.area}</span>
                <span className="guide-cap__desc">{c.descJa}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section>
        <div className="section-head">
          <span className="section-head__title">最近のアップデート</span>
          <span className="section-head__count">{RECENT_UPDATES.length} releases</span>
        </div>
        <div className="card guide-card">
          <div className="guide-caps">
            {RECENT_UPDATES.map(([v, d]) => (
              <div className="guide-cap" key={v}>
                <span className="guide-cap__area guide-cap__area--mono">{v}</span>
                <span className="guide-cap__desc">{d}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section>
        <div className="section-head"><span className="section-head__title">用語一覧</span></div>
        <div className="card guide-card">
          <div className="guide-glossary">
            {GLOSSARY.map(([en, ja]) => (
              <div className="guide-term" key={en}>
                <span className="guide-term__en">{en}</span>
                <span className="guide-term__ja">{ja}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section>
        <div className="section-head">
          <span className="section-head__title">API / Integration status</span>
          <span className="section-head__count">設定・稼働状況</span>
        </div>
        <IntegrationsPanel />
      </section>

      <section>
        <div className="section-head"><span className="section-head__title">ARGUS の使い方</span></div>
        <div className="card guide-card">
          <ol className="guide-howto">
            {HOWTO.map((s, i) => <li key={i}>{s}</li>)}
          </ol>
          <p className="guide-note">
            ARGUS は予測エンジンではありません。現在の市場・銘柄の状況を「行動カテゴリ」に整理して、
            今日の判断・リスク・理由・触るもの・避けるもの・待つものを示す投資コマンドセンターです。
          </p>
        </div>
      </section>
    </PageShell>
  );
};
