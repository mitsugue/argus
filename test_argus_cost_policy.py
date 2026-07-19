import unittest

import argus_cost_policy as cp


class CostPolicyTests(unittest.TestCase):
    def test_deterministic_blocks_all_generated_ai(self):
        state = cp.default_state()
        for provider in cp.PROVIDERS:
            result = cp.authorize(
                state, provider=provider, purpose="scheduled", automatic=True,
                estimated_cost_usd=0.01, estimated_tokens=100)
            self.assertFalse(result["allowed"])
            self.assertEqual(result["classification"], "expected_skip")
            self.assertEqual(result["status"], "deterministic_mode")

    def test_event_opt_in_is_explicit_bounded_and_fail_closed(self):
        state = cp.configure(cp.default_state(), mode="EVENT_OPT_IN",
                             event_opt_in=True, event_id="CPI-1",
                             event_enabled=True, providers=["openai"],
                             event_budget_usd=0.5, event_token_limit=5000)
        allowed = cp.authorize(
            state, provider="openai", purpose="event_analysis", automatic=True,
            event_id="CPI-1", event_phase="pre", estimated_cost_usd=0.1,
            estimated_tokens=1000)
        self.assertTrue(allowed["allowed"])
        state = cp.record_execution(
            state, provider="openai", purpose="event_analysis",
            at="2026-07-20T01:00:00Z", estimated_cost_usd=0.1,
            event_id="CPI-1", event_phase="pre")
        duplicate = cp.authorize(
            state, provider="openai", purpose="event_analysis", automatic=True,
            event_id="CPI-1", event_phase="pre", estimated_cost_usd=0.1,
            estimated_tokens=1000)
        self.assertEqual(duplicate["reason"], "event_phase_already_run")
        unknown_cost = cp.authorize(
            state, provider="openai", purpose="event_analysis", automatic=True,
            event_id="CPI-1", event_phase="post", estimated_cost_usd=None,
            estimated_tokens=1000)
        self.assertEqual(unknown_cost["reason"], "cost_unknown")

    def test_manual_requires_confirmation_and_never_authorizes_automatic(self):
        state = cp.default_state("MANUAL")
        denied = cp.authorize(
            state, provider="gemini", purpose="manual_api", automatic=True,
            confirmation=True, estimated_cost_usd=0.01, estimated_tokens=100)
        self.assertEqual(denied["reason"], "manual_only")
        denied = cp.authorize(
            state, provider="gemini", purpose="manual_api", automatic=False,
            confirmation=False, estimated_cost_usd=0.01, estimated_tokens=100)
        self.assertEqual(denied["reason"], "confirmation_required")
        allowed = cp.authorize(
            state, provider="gemini", purpose="manual_api", automatic=False,
            confirmation=True, estimated_cost_usd=0.01, estimated_tokens=100)
        self.assertTrue(allowed["allowed"])

    def test_public_status_counts_providers_without_secrets(self):
        state = cp.default_state()
        state = cp.record_execution(state, provider="openai", purpose="manual_api",
                                    at="2026-07-20T01:00:00Z", estimated_cost_usd=0.02)
        view = cp.public_status(state, "2026-07-20T02:00:00Z")
        self.assertEqual(view["todayRuns"]["openai"], 1)
        self.assertFalse(view["automaticAiEnabled"])
        self.assertNotIn("apiKey", view)


if __name__ == "__main__":
    unittest.main()
