// v13.5.36 — canonical plain-Japanese glossary (owner directive: one source,
// no scattered duplicate strings). DISPLAY ONLY: this module must never
// import from or influence SHO / news direction / SDA / riskKernel — it maps
// already-rendered vocabulary to one- or two-sentence explanations a
// non-specialist can understand.

export interface GlossaryEntry {
  term: string;          // the label as rendered in the UI
  explanationJa: string; // 1–2 short plain sentences, no internal jargon
}

export const GLOSSARY: Record<string, GlossaryEntry> = {
  // ── 市場観: 反転軸の状態 ──
  recovery_test: {
    term: '回復試験',
    explanationJa: '下落後に価格が戻り始めていますが、この反転が本物として続くかはまだ確認中です。',
  },
  confirmed_advance: {
    term: '上昇確認',
    explanationJa: '戻りが続き、上昇の動きがデータで裏付けられた状態です。',
  },
  false_rally: {
    term: 'だまし上げ警戒',
    explanationJa: '価格は上がっていますが、続かずに反落する兆候が混ざっている状態です。',
  },
  technical_rebound: {
    term: 'テクニカル反発',
    explanationJa: '売られすぎの反動による一時的な戻りで、本格反転の裏付けはまだありません。',
  },
  reversal_early: {
    term: '反転初動',
    explanationJa: '下落から上昇へ転じる最初の兆しが出た段階です。まだ確定ではありません。',
  },
  sell_off_active: {
    term: '売り圧継続',
    explanationJa: '売りの勢いがまだ続いている状態です。',
  },
  downside_triggered: {
    term: '下方シグナル点灯',
    explanationJa: 'さらに下落する可能性を示すシグナルが点灯しています。',
  },
  mixed: {
    term: '混在',
    explanationJa: '悪化を示す材料と落ち着きを示す材料が混ざっていて、方向を断定できない状態です。',
  },
  fragile: {
    term: '脆弱',
    explanationJa: '相場の支えが弱く、悪材料に反応しやすい状態です。',
  },
  recovery_pending: {
    term: 'データ待ち',
    explanationJa: 'この判定に必要なデータがまだ揃っていません。',
  },

  // ── 市場観: 証拠ファミリーの状態 ──
  family_met: {
    term: '成立',
    explanationJa: '底入れ局面などで典型的に見られる条件を、実データが満たしています。',
  },
  family_not_met: {
    term: '不成立',
    explanationJa: 'データは取得できていますが、条件は満たしていません。',
  },
  family_unknown: {
    term: '判定不能',
    explanationJa: '必要な材料が十分でないため、ARGUSは方向を決めていません。分からないものを分からないと表示しています。',
  },
  family_missing: {
    term: '欠測',
    explanationJa: '判定に必要なデータを現在取得できていません。',
  },
  family_license: {
    term: '要ライセンス',
    explanationJa: 'この判定には現在契約していない有料データが必要です。',
  },

  // ── ニュース/イベント ──
  news_mixed: {
    term: 'ニュース: 混在',
    explanationJa: 'このニュースの影響は対象によって強気と弱気が分かれています（例: 輸出には逆風、他は不明）。',
  },
  market_confirmation_pending: {
    term: '市場確認待ち',
    explanationJa: 'ニュース自体は重要ですが、株価・金利などの市場の反応ではまだ裏付けられていません。',
  },
  market_confirmed: {
    term: '市場確認済み',
    explanationJa: 'ニュースの想定方向に市場（金利・株価など）が実際に動き、裏付けが取れた状態です。',
  },
  market_contradicted: {
    term: '市場と矛盾',
    explanationJa: 'ニュースの想定方向と反対に市場が大きく動いており、想定を確認とは扱っていません。',
  },

  // ── 夜間・日次基準 ──
  close_basis: {
    term: '終値基準',
    explanationJa: '市場が閉まっている間は、最後に確定した公式の終値を基準に日次判断を行います。エラーではありません。',
  },
  latest_completed_session: {
    term: '最新完了セッション',
    explanationJa: '取引カレンダー上で最後に終了した営業日のことです。祝日や連休があっても正しく前の営業日を指します。',
  },
  daily_decision_available: {
    term: '日次判断: 利用可能',
    explanationJa: '最新の公式終値が確認できているため、日足ベースの判断は市場が閉まっていても実行できます。',
  },
  daily_decision_held: {
    term: '日次判断を保留',
    explanationJa: '本来届いているはずの最新の日足がまだ確認できないため、判断を安全側で止めています。',
  },

  // ── データ品質 ──
  data_partial: {
    term: '一部不足',
    explanationJa: '一部のデータが取得できていないため、確度を控えめにしています。',
  },
  pre_verification: {
    term: '検証前',
    explanationJa: 'この情報は参考表示です。予測力がまだ統計的に証明されていないため、売買判断の根拠にはしていません。',
  },
  // v13.5.38 MARKET SIGNALS (SIG-01..07) states
  signal_active: {
    term: '点灯',
    explanationJa: 'このシグナルの条件が現在のデータで成立しています。7つのうち点灯している数だけを「x / 7」に数えます。',
  },
  signal_clear: {
    term: '消灯',
    explanationJa: 'データはそろっていますが、このシグナルの条件は成立していません。数には入りません。',
  },
  signal_data_gated: {
    term: '判定不能',
    explanationJa: 'データはあるものの、条件を判定できる状態ではありません（検証前・不足など）。数には入りません。',
  },
  signal_stale: {
    term: '古い',
    explanationJa: 'このシグナルのデータが古く、現在の判定には使えません。数には入りません。',
  },
  signal_license: {
    term: '要ライセンス',
    explanationJa: 'このシグナルの正式データはライセンス上まだ取り込めません。代替データがない間は数に入りません。',
  },
  signal_unavailable: {
    term: '欠測',
    explanationJa: 'このシグナルのデータ提供元から現在データが得られていません。ゼロ扱いではなく「欠測」として表示します。',
  },
  // v13.5.38 TACHIBANA LIVE statuses
  tachibana_live: {
    term: 'ライブ',
    explanationJa: '立花証券の現在値が受理済みの鮮度で届いています。参考証拠であり、売買判断を上書きしません。',
  },
  tachibana_degraded: {
    term: '一部',
    explanationJa: '一部の銘柄だけ現在値が届いています。届いていない銘柄は欠測のまま表示します。',
  },
  tachibana_stale: {
    term: '古い',
    explanationJa: '受信した値の鮮度期限が切れています。現在値としては扱いません。',
  },
  tachibana_closed: {
    term: '市場クローズ',
    explanationJa: '立花証券への認証・日付・価格の読取は本番で確認済みで、いまは市場が閉まっているため更新がない状態。提供元の可用性と市場の開閉を分けて表示します。',
  },
  tachibana_unavailable: {
    term: '欠測',
    explanationJa: '現在、立花証券からライブ値を受け取れていません（セッション外・未接続・取得失敗）。値を推定しません。',
  },
  tachibana_auth_failed: {
    term: '認証失敗',
    explanationJa: '立花証券への認証が失敗しました。自動で再試行の嵐は起こさず、上限つきで再接続します。',
  },
  tachibana_maintenance: {
    term: 'メンテナンス',
    explanationJa: '立花証券側がメンテナンス中です。復旧まで値は届きません。',
  },
  tachibana_disabled: {
    term: '無効',
    explanationJa: '立花証券の取り込みは現在オフです（設定で有効化されるまで通信しません）。',
  },
};

// Rendered-state → glossary key maps (kept beside the glossary so the pin
// test can prove every rendered label resolves).
export const REVERSAL_STATE_GLOSSARY: Record<string, string> = {
  MIXED: 'mixed', FRAGILE: 'fragile', DOWNSIDE_TRIGGERED: 'downside_triggered',
  SELL_OFF_ACTIVE: 'sell_off_active', REVERSAL_EARLY: 'reversal_early',
  TECHNICAL_REBOUND: 'technical_rebound', RECOVERY_TEST: 'recovery_test',
  CONFIRMED_ADVANCE: 'confirmed_advance', FALSE_RALLY: 'false_rally',
};

export const FAMILY_STATE_GLOSSARY: Record<string, string> = {
  '成立': 'family_met', '不成立': 'family_not_met',
  '判定不能': 'family_unknown', '欠測': 'family_missing',
  '要ライセンス': 'family_license',
};

export const TACHIBANA_STATUS_GLOSSARY: Record<string, string> = {
  LIVE: 'tachibana_live', DEGRADED: 'tachibana_degraded', STALE: 'tachibana_stale', CLOSED: 'tachibana_closed',
  UNAVAILABLE: 'tachibana_unavailable', AUTH_FAILED: 'tachibana_auth_failed',
  MAINTENANCE: 'tachibana_maintenance', DISABLED: 'tachibana_disabled',
};

export const MARKET_SIGNAL_STATE_GLOSSARY: Record<string, string> = {
  ACTIVE: 'signal_active', CLEAR: 'signal_clear', DATA_GATED: 'signal_data_gated',
  STALE: 'signal_stale', LICENSE_BLOCKED: 'signal_license',
  UNAVAILABLE: 'signal_unavailable',
};

export function glossaryEntry(key: string): GlossaryEntry | null {
  return GLOSSARY[key] ?? null;
}
