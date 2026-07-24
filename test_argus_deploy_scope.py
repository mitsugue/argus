import json
import pathlib
import unittest

import yaml

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

    def test_render_blueprint_allowlist_matches_classifier(self):
        blueprint = yaml.safe_load((ROOT / "render.yaml").read_text())
        service = blueprint["services"][0]
        self.assertEqual("checksPass", service["autoDeployTrigger"])
        self.assertEqual(list(deploy_scope.RENDER_BACKEND_PATHS),
                         service["buildFilter"]["paths"])
        self.assertEqual([], service["buildFilter"]["ignoredPaths"])

    def test_release_versions_are_independent(self):
        frontend = json.loads((ROOT / "web/package.json").read_text())["version"]
        backend = json.loads((ROOT / "backend-version.json").read_text())["version"]
        self.assertEqual("13.2.2", frontend)
        self.assertEqual("13.2.2", backend)
