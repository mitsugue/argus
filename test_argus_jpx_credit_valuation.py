import math
from decimal import Decimal

import pytest

import argus_jpx_credit_valuation as valuation
from test_jpx_credit_weekly import GRID, current_grid


def inputs(**changed):
    out = dict(zip(valuation.INPUTS, (1000, 100, 200, 100, 300, 100), strict=True))
    out.update(changed)
    return out


def old_grid():
    out = [row[:] for row in GRID] + [[''] * 15 for _ in range(10)]
    out[3][14] = '(単位：千株、百万円）'
    out[7][13] = 1000
    out[14][3], out[14][5], out[14][11] = '社内対当 Matched Internally', '貸借取引残高 Outstanding loans by JSF', '自己融資 Non-JSF funds'
    out[15][5], out[15][7] = '貸株高 Shares', '融資 Funds'
    out[16][1], out[16][2], out[17][2] = '二市場計 Total', '株数Shs.', '金額Val.'
    out[16][3], out[16][7], out[16][11] = 100, 200, 100
    out[17][7], out[17][11] = 300, 100
    out[16][5], out[17][5] = 99999, 88888  # Lending side must never enter the equation.
    return out


def new_grid():
    out = current_grid()
    out[14][6] = 1000
    out[15][1], out[16][1], out[18][1] = '社内対当 Matched Internally', '貸借取引残高 Outstanding loans by JSF', '自己貸株・自己融資 Non-JSF shares,Non-JSF funds'
    out[15][3], out[16][3], out[18][3] = '株数Shs.', '株数Shs.', '株数Shs.'
    out[17][3], out[19][3] = '金額Val.', '金額Val.'
    out[15][4], out[16][6], out[18][6] = 100, 200, 100
    out[17][6], out[19][6] = 300, 100
    out[16][4], out[17][4], out[18][4], out[19][4] = 99999, 88888, 77777, 66666
    out[16][10], out[17][10] = 999, 999  # Tokyo is not the two-market total.
    return out


def test_official_equation_preserves_six_inputs_and_loss_negative_sign():
    result = valuation.calculate(inputs())
    expected = ((Decimal(400) / 300 * 100 + 400) - 1000) / 1000 * 100
    assert math.isclose(result['value'], float(expected), rel_tol=1e-12)
    assert result['inputs'] == inputs()
    assert result['signConvention'] == 'loss_negative_profit_positive'
    assert result['classification'] == 'derived_from_official_workbook'
    assert result['methodVersion'] == valuation.METHOD_VERSION
    assert valuation.calculate(inputs(buyAmountMillionJpy=500))['value'] > 0


@pytest.mark.parametrize('value', [float('nan'), float('inf'), 1e300, -1, True, None, 'missing'])
def test_invalid_values_never_produce_a_rate(value):
    with pytest.raises(ValueError):
        valuation.calculate(inputs(jsfFinanceMillionJpy=value))


@pytest.mark.parametrize('changes', [{'buyAmountMillionJpy': 0}, {'jsfFinanceThousandShares': 0, 'ownFinanceThousandShares': 0}])
def test_zero_denominator_never_becomes_zero_percent(changes):
    with pytest.raises(ValueError, match='zero_denominator'):
        valuation.calculate(inputs(**changes))


def test_new_and_old_layouts_use_same_inputs_ignoring_lending_tokyo_and_changes():
    old, new = valuation.extract(old_grid()), valuation.extract(new_grid())
    assert old['inputs'] == new['inputs'] == inputs()
    assert old['value'] == new['value'] == valuation.calculate(inputs())['value']
    assert old['periodEnd'] == '2026-08-28' and new['periodEnd'] == '2026-09-25'


def test_reference_units_are_required_and_financing_label_cannot_be_replaced_by_lending():
    g = old_grid(); g[15][7] = '貸株高 Shares'
    with pytest.raises(ValueError, match='financing_columns'):
        valuation.extract(g)
    g = new_grid(); g[4][11] = '百万円'
    with pytest.raises(ValueError, match='unit'):
        valuation.extract(g)
    g = new_grid(); g[17][3] = '株数Shs.'
    with pytest.raises(ValueError, match='amount_row'):
        valuation.extract(g)


def test_notes_cannot_be_mistaken_for_the_financing_block():
    g = old_grid(); g.append([''] * 8 + ['貸借取引残高は千株未満を切り捨て'])
    assert valuation.extract(g)['inputs'] == inputs()


def test_ambiguous_or_missing_labels_are_not_guessed():
    g = new_grid(); g.append(g[16][:])
    with pytest.raises(ValueError, match='layout_ambiguous'):
        valuation.extract(g)
    g = old_grid(); g[16][1] = '東京 Tokyo'
    with pytest.raises(ValueError, match='two_market_row'):
        valuation.extract(g)


def test_current_labels_accept_the_official_bilingual_line_breaks():
    g = new_grid(); g[15][1] = '社内対当\nMatched Internally'
    g[16][1] = '貸借取引残高\n Outstanding loans by JSF'
    g[18][1] = '自己貸株・自己融資\nNon-JSF shares,Non-JSF funds'
    assert valuation.extract(g)['inputs'] == inputs()
