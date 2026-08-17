"""V11.12.0 backend wiring — action-priority endpoints watchlist-level only,
leak-free, plus standing regressions."""
import json

import scanner


class _Boom:
    def __getattr__(self, name):
        raise AssertionError(f"network call attempted via requests.{name}")


def test_handoff_has_action_priority_section():
    ah = scanner.argus_action_priority.handoff_section(
        scanner._action_priority_items(cap=10))
    assert ah["title"] == "Action Priority Summary"
