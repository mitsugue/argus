import unittest

from scripts import render_deploy_guard


class RenderDeployGuardTests(unittest.TestCase):
    def test_frontend_only_requires_documented_skip_phrase(self):
        accepted, reason = render_deploy_guard.validate(
            ["web/src/App.tsx"], "fix: frontend")
        self.assertFalse(accepted)
        self.assertEqual("frontend_only_change_requires_skip_render", reason)

    def test_frontend_only_accepts_skip_render(self):
        accepted, reason = render_deploy_guard.validate(
            ["web/src/App.tsx"], "[skip render] fix: frontend")
        self.assertTrue(accepted)
        self.assertEqual("frontend_only_render_skip_confirmed", reason)

    def test_frontend_acceptance_script_is_frontend_only(self):
        accepted, _ = render_deploy_guard.validate(
            ["web/scripts/public-market-acceptance.mjs"],
            "[render skip] fix: acceptance")
        self.assertTrue(accepted)

    def test_backend_change_rejects_skip_phrase(self):
        accepted, reason = render_deploy_guard.validate(
            ["scanner.py"], "[skip render] fix: backend")
        self.assertFalse(accepted)
        self.assertEqual("backend_sensitive_change_must_not_skip_render", reason)

    def test_backend_change_without_skip_deploys(self):
        accepted, reason = render_deploy_guard.validate(
            ["argus_market_replay.py"], "fix: replay")
        self.assertTrue(accepted)
        self.assertEqual("backend_deploy_expected", reason)

    def test_render_blueprint_change_never_skips(self):
        accepted, _ = render_deploy_guard.validate(
            ["render.yaml"], "[skip render] chore: blueprint")
        self.assertFalse(accepted)


if __name__ == "__main__":
    unittest.main()
