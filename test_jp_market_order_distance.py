"""Exact distance and downstream forecast parity for the cold research path."""
import copy
import itertools
import random
from unittest.mock import patch

import jp_market_analog_backtest as backtest
import jp_market_analogs as analogs
from test_jp_market_analogs import DAYS, POLICY, episode


def matrix_distance(left, right, *, left_pattern=None, right_pattern=None):
    """Independent unit-cost dynamic-programming reference."""
    matrix = [[0] * (len(right) + 1) for _ in range(len(left) + 1)]
    for i in range(len(left) + 1):
        matrix[i][0] = i
    for j in range(len(right) + 1):
        matrix[0][j] = j
    for i, item in enumerate(left, 1):
        for j, other in enumerate(right, 1):
            matrix[i][j] = min(matrix[i - 1][j] + 1, matrix[i][j - 1] + 1,
                               matrix[i - 1][j - 1] + (item != other))
    return matrix[-1][-1] / max(len(left), len(right), 1)


def test_all_short_sequences_match_the_independent_matrix():
    sequences = [list(items) for n in range(6) for items in itertools.product("ab", repeat=n)]
    for left in sequences:
        for right in sequences:
            assert analogs._edit_distance(left, right) == matrix_distance(left, right)


def test_simultaneous_day_tokens_long_patterns_and_unhashable_compatibility():
    randomizer = random.Random(232)
    tokens = [("vix:1",), ("price:-1",), ("price:1", "vix:1"), ()]
    pairs = [([randomizer.choice(tokens) for _ in range(randomizer.randrange(140))],
              [randomizer.choice(tokens) for _ in range(randomizer.randrange(140))])
             for _ in range(180)]
    pairs += [([["a"], ["b"]], [["b"], ["a"], ["b"]]),
              ([{"a": 1}], [{"a": 2}]), ([], [["a"]])]
    for left, right in pairs:
        original = copy.deepcopy((left, right))
        assert analogs._edit_distance(left, right) == matrix_distance(left, right)
        assert analogs._edit_distance(right, left) == matrix_distance(right, left)
        assert (left, right) == original


def test_full_selection_validation_and_weight_search_outputs_are_unchanged():
    candidates = [episode(i, full=True, changes={"condition_rows": [
        {"instrumentId": analogs.INSTRUMENT, "field": "vix_cross", "value": (i + j) % 3 - 1,
         "date": DAYS[i - 5 + j], "availableFrom": DAYS[i - 5 + j] + "T08:00:00Z",
         "unit": "DIRECTION", "revision": 0} for j in range(1, 6) if (i + j) % 4]})
                  for i in range(10, 86)]
    current = episode(110, full=True)
    closes = {day: 100 + i % 6 for i, day in enumerate(DAYS)}

    def evaluate():
        return {
            "selection": analogs.select_episodes(current, candidates, session_dates=DAYS, policy=POLICY),
            "validation": backtest.walk_forward(candidates, closes, DAYS, policy=POLICY,
                                                  minimum_prior=6, step=2),
            "weightSearch": backtest.weight_search(candidates, closes, DAYS, policy=POLICY,
                                                    minimum_prior=6, step=2),
        }

    actual = evaluate()
    with patch.object(analogs, "_edit_distance", side_effect=matrix_distance):
        expected = evaluate()
    assert actual == expected
    assert actual["validation"]["records"]
    assert actual["weightSearch"]["status"] == "AVAILABLE"
