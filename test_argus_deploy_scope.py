import json
import pathlib
import unittest

from scripts import deploy_scope


ROOT = pathlib.Path(__file__).parent


class DeployScopeTests(unittest.TestCase):
    def test_css_only_deploys_pages_and_preserves_soak(self):
        result = deploy_scope.classify(["web/src/styles/theme.css"])
        self.assertEqual({
            "frontendDeploy": True, "backendDeploy": False,
            "newBackendSoak": False, "preserveBackendSoak": True,
        }, result)

    def test_react_only_deploys_pages_and_preserves_soak(self):
        result = deploy_scope.classify(
            ["web/src/components/marketReplay/MarketContextReplay.tsx"])
        self.assertTrue(result["frontendDeploy"])
        self.assertFalse(result["backendDeploy"])
        self.assertTrue(result["preserveBackendSoak"])

    def test_python_backend_change_starts_new_soak(self):
        result = deploy_scope.classify(["argus_market_replay.py"])
        self.assertFalse(result["frontendDeploy"])
        self.assertTrue(result["backendDeploy"])
        self.assertTrue(result["newBackendSoak"])

    def test_shared_api_type_deploys_both_planes(self):
        result = deploy_scope.classify(["web/src/types/chartIntelligence.ts"])
        self.assertTrue(result["frontendDeploy"])
        self.assertTrue(result["backendDeploy"])
        self.assertTrue(result["newBackendSoak"])

    def test_guide_only_does_not_restart_backend(self):
        result = deploy_scope.classify(["web/src/routes/Guide.tsx"])
        self.assertTrue(result["frontendDeploy"])
        self.assertFalse(result["backendDeploy"])

    def test_public_acceptance_workflow_is_frontend_plane(self):
        result = deploy_scope.classify(
            [".github/workflows/market-public-acceptance.yml"])
        self.assertTrue(result["frontendDeploy"])
        self.assertFalse(result["backendDeploy"])

    def test_snapshot_release_gate_is_frontend_deploy_plane_only(self):
        result = deploy_scope.classify(
            ["scripts/verified_snapshot_release_gate.py"])
        self.assertTrue(result["frontendDeploy"])
        self.assertFalse(result["backendDeploy"])

    def test_pages_waits_for_verified_snapshot_readiness(self):
        workflow = (ROOT / ".github/workflows/deploy-pages.yml").read_text()
        self.assertIn("backend-readiness:", workflow)
        self.assertIn(
            "needs: [build, seed-warm-profile, backend-readiness]", workflow)
        self.assertIn(
            "scripts/verified_snapshot_release_gate.py", workflow)
        self.assertIn(
            "backend-snapshot-readiness-${{ github.sha }}", workflow)

    def test_render_blueprint_allowlist_matches_classifier(self):
        blueprint = (ROOT / "render.yaml").read_text()
        self.assertIn("autoDeployTrigger: commit", blueprint)
        path_block = blueprint.split("buildFilter:", 1)[1].split(
            "ignoredPaths:", 1)[0]
        configured = [
            line.strip()[2:] for line in path_block.splitlines()
            if line.strip().startswith("- ")
        ]
        self.assertEqual(list(deploy_scope.RENDER_BACKEND_PATHS),
                         configured)
        self.assertIn("ignoredPaths: []", blueprint)

    def test_release_versions_are_independent(self):
        frontend = json.loads((ROOT / "web/package.json").read_text())["version"]
        backend = json.loads((ROOT / "backend-version.json").read_text())["version"]
        self.assertEqual("13.3.0", frontend)
        self.assertEqual("13.3.1", backend)

    def test_release_gate_enforces_render_skip_contract(self):
        workflow = (ROOT / ".github/workflows/release-gate.yml").read_text()
        self.assertIn("fetch-depth: 0", workflow)
        self.assertIn("python3 -B scripts/render_deploy_guard.py", workflow)
        self.assertIn("github.event.pull_request.title", workflow)
