"""Keep bounded material-event observations without duplicate cron triggers."""
from collections import Counter
from pathlib import Path
import re


def test_macro_week_has_no_duplicate_and_preserves_material_observation_times():
    workflow = Path(__file__).parent / '.github/workflows/macro-event-analysis.yml'
    cron = re.findall(r"^\s+- cron: '([^']+)'", workflow.read_text(), re.M)
    counts = Counter()
    for expression in cron:
        minute, hours, dom, month, dow = expression.split()
        assert (dom, month, dow) == ('*', '*', '1-5')
        for day in range(1, 6):
            for hour in map(int, hours.split(',')):
                counts[day, hour, int(minute)] += 1
    expected = {(day, hour, 35) for day in range(1, 6) for hour in (0, 6, 10)}
    expected |= {(day, hour, minute) for day in range(1, 6)
                 for hour, minute in [(12, 45), (13, 30), (14, 30), (20, 30)]}
    assert set(counts) == expected
    assert set(counts.values()) == {1}
    assert len(counts) == 35
