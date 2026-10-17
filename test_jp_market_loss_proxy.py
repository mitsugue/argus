"""ARGUS valuation-loss proxy (2026-09-30): distinct from the official figure."""
from datetime import date, timedelta
import unittest

import jp_market_features as features
import jp_market_price_paths as price_paths


def credit_rows(start, balances):
    rows = []
    day = date.fromisoformat(start)
    for value in balances:
        published = (day + timedelta(days=7)).isoformat() + "T15:00:00+09:00"
        rows.append({"instrumentId": "MARKET", "seriesId": "credit.long_balance", "periodEnd": day.isoformat(),
                     "value": value, "unit": "JPY", "publishedAt": published, "availableFrom": published})
        day += timedelta(days=7)
    return rows


def bars(start, closes):
    rows, day = [], date.fromisoformat(start)
    for close in closes:
        if day.weekday() < 5:
            rows.append({"instrumentId": "NIKKEI_225_INDEX", "date": day.isoformat(), "open": close, "high": close,
                         "low": close, "close": close, "volume": 1, "availableFrom": day.isoformat() + "T07:00:00Z"})
        day += timedelta(days=1)
    return rows


class LossProxyTest(unittest.TestCase):
    def setUp(self):
        # 30 weekly balances from Friday 2026-01-02; buying grows 100bn a week
        # while the index rises 100 points a day, so the cost basis sits below
        # the latest close: a valuation gain (negative loss).
        self.credit = credit_rows("2026-01-02", [10_000e9 + 100e9 * n for n in range(30)])
        self.prices = bars("2025-12-15", [30000 + 100 * n for n in range(300)])
        self.cutoff = "2026-07-31T23:59:59Z"

    def test_proxy_is_emitted_labelled_and_positive_means_loss(self):
        snapshot = features.build_market_features(cutoff=self.cutoff, price_series={"nikkei": self.prices},
                                                  two_market_credit=self.credit)
        row = next(r for r in snapshot["features"] if r["seriesId"] == "credit.loss_pct")
        self.assertEqual(row["derivationBasis"], features.LOSS_PROXY_BASIS)
        self.assertLess(row["value"], 0)  # index above the buyers' basis: a gain
        self.assertEqual(row["unit"], "PERCENT")
        # Falling prices after the buying turn the same basis into a loss.
        falling = bars("2025-12-15", [60000 - 100 * n for n in range(300)])
        snapshot = features.build_market_features(cutoff=self.cutoff, price_series={"nikkei": falling},
                                                  two_market_credit=self.credit)
        row = next(r for r in snapshot["features"] if r["seriesId"] == "credit.loss_pct")
        self.assertGreater(row["value"], 0)
        # The proxy uses only what was visible: rows after the cutoff change nothing.
        later = self.credit + credit_rows("2026-08-07", [50_000e9])
        again = features.build_market_features(cutoff=self.cutoff, price_series={"nikkei": self.prices},
                                               two_market_credit=later)
        self.assertEqual(next(r for r in again["features"] if r["seriesId"] == "credit.loss_pct")["value"], 
                         next(r for r in features.build_market_features(cutoff=self.cutoff, price_series={"nikkei": self.prices}, two_market_credit=self.credit)["features"] if r["seriesId"] == "credit.loss_pct")["value"])

    def test_official_series_wins_and_thin_history_or_no_buying_yields_nothing(self):
        official = [{"instrumentId": "MARKET", "seriesId": "credit.valuation_loss_pct", "periodEnd": "2026-07-24",
                     "value": 7.5, "unit": "PERCENT", "signConvention": "positive_is_loss",
                     "availableFrom": "2026-07-28T09:00:00+09:00"}]
        snapshot = features.build_market_features(cutoff=self.cutoff, price_series={"nikkei": self.prices},
                                                  two_market_credit=self.credit, valuation_loss=official)
        row = next(r for r in snapshot["features"] if r["seriesId"] == "credit.loss_pct")
        self.assertEqual(row["value"], 7.5)
        self.assertNotIn("derivationBasis", row)
        thin = features.build_market_features(cutoff=self.cutoff, price_series={"nikkei": self.prices},
                                              two_market_credit=self.credit[-6:])
        self.assertIn("credit.loss_pct", thin["missingFeatures"])
        flat = features.build_market_features(cutoff=self.cutoff, price_series={"nikkei": self.prices},
                                              two_market_credit=credit_rows("2026-01-02", [10_000e9] * 30))
        self.assertIn("credit.loss_pct", flat["missingFeatures"])
        self.assertIsNone(features.margin_cost_basis_loss_proxy(self.credit, [], cutoff=self.cutoff))

    def test_chart_labels_name_the_proxy(self):
        from test_jp_market_analogs import DAYS, POLICY, bars as episode_bars, episode, fact
        from jp_market_analogs import FEATURE_DEFINITIONS, select_episodes, reference_path
        def states(index):
            return [fact(key, 1, index, definition[0], **({"derivationBasis": features.LOSS_PROXY_BASIS}
                                                           if key == "credit.loss_pct" else {}))
                    for key, definition in FEATURE_DEFINITIONS.items()]
        current = episode(83, full=True, changes={"state_rows": states(83)})
        past = [episode(11, full=True, changes={"state_rows": states(11)}), episode(23, full=True)]
        self.assertEqual(current["states"]["credit.loss_pct"]["derivationBasis"], features.LOSS_PROXY_BASIS)
        selected = select_episodes(current, past, session_dates=DAYS, policy=POLICY)
        paths = [reference_path(item, later_bars=episode_bars(0, 84), display_cutoff=current["cutoff"],
                                session_dates=DAYS, policy=POLICY) for item in past]
        document = price_paths.comparison_document(current, selected, paths, price_paths.reference_ensemble(selected, paths))
        labels = [label for candidate in document["candidates"] for label in candidate["comparedFeatures"]]
        self.assertIn("信用評価損失率（ARGUS代理計算）", labels)
        self.assertNotIn("信用評価損失率", labels)
        text = " ".join(d for candidate in document["candidates"] for d in candidate["differences"])
        self.assertNotIn("信用評価損失率：", text)  # never the bare official name

if __name__ == "__main__":
    unittest.main()
