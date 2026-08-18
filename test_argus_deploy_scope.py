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
            "checkpointStage1": False,
        }, result)

    def test_react_only_deploys_pages_and_preserves_soak(self):
        result = deploy_scope.classify(
            ["web/src/components/today/ArgusTodayPanel.tsx"])
        self.assertTrue(result["frontendDeploy"])
        self.assertFalse(result["backendDeploy"])
        self.assertTrue(result["preserveBackendSoak"])

    def test_python_backend_change_starts_new_soak(self):
        result = deploy_scope.classify(["argus_market_replay.py"])
        self.assertFalse(result["frontendDeploy"])
        self.assertTrue(result["backendDeploy"])
        self.assertTrue(result["newBackendSoak"])
        self.assertFalse(result["checkpointStage1"])

    def test_shared_api_type_deploys_both_planes(self):
        result = deploy_scope.classify(["web/src/types/chartIntelligence.ts"])
        self.assertTrue(result["frontendDeploy"])
        self.assertTrue(result["backendDeploy"])
        self.assertTrue(result["newBackendSoak"])
        self.assertFalse(result["checkpointStage1"])

    def test_checkpoint_v2_stage1_deploys_without_formal_soak(self):
        result = deploy_scope.classify(
            list(deploy_scope.CHECKPOINT_STAGE1_BACKEND_PATHS) + [
                ".github/workflows/checkpoint-v2-gate.yml",
                "docs/ops/checkpoint-v2-pre-merge-closure.md",
                "test_argus_checkpoint_v2_stage1.py",
            ])
        self.assertTrue(result["backendDeploy"])
        self.assertFalse(result["newBackendSoak"])
        self.assertTrue(result["preserveBackendSoak"])
        self.assertTrue(result["checkpointStage1"])

    def test_stage1_closure_actual_backend_scope_suppresses_formal_soak(self):
        result = deploy_scope.classify([
            "argus_checkpoint_v2.py",
            "argus_checkpoint_v2_stage1.py",
            "argus_runtime.py",
            "backend-version.json",
            "scanner.py",
        ])
        self.assertTrue(result["backendDeploy"])
        self.assertFalse(result["newBackendSoak"])
        self.assertTrue(result["preserveBackendSoak"])
        self.assertTrue(result["checkpointStage1"])

    def test_checkpoint_stage1_mixed_backend_change_fails_closed(self):
        result = deploy_scope.classify([
            "argus_checkpoint_v2_stage1.py",
            "requirements.txt",
        ])
        self.assertTrue(result["backendDeploy"])
        self.assertTrue(result["newBackendSoak"])
        self.assertFalse(result["preserveBackendSoak"])
        self.assertFalse(result["checkpointStage1"])

    def test_settings_only_does_not_restart_backend(self):
        result = deploy_scope.classify(["web/src/routes/Settings.tsx"])
        self.assertTrue(result["frontendDeploy"])
        self.assertFalse(result["backendDeploy"])

    def test_canonical_product_version_deploys_both_consumers(self):
        result = deploy_scope.classify(["product-version.json"])
        self.assertTrue(result["frontendDeploy"])
        self.assertTrue(result["backendDeploy"])

    def test_public_acceptance_workflow_is_frontend_plane(self):
        result = deploy_scope.classify(
            [".github/workflows/market-public-acceptance.yml"])
        self.assertTrue(result["frontendDeploy"])
        self.assertFalse(result["backendDeploy"])

    def test_shared_warm_profile_actions_are_frontend_plane(self):
        result = deploy_scope.classify([
            ".github/actions/warm-profile-seed/action.yml",
            ".github/actions/warm-profile-consumer/action.yml",
        ])
        self.assertTrue(result["frontendDeploy"])
        self.assertFalse(result["backendDeploy"])

    def test_zero_install_runtime_contract_is_frontend_plane(self):
        result = deploy_scope.classify([
            ".github/actions/acceptance-runtime-preflight/action.yml",
            "release/v13-acceptance-runtime.json",
            "scripts/v13_5_release_certificate.py",
            "web/scripts/acceptance-runtime.mjs",
        ])
        self.assertTrue(result["frontendDeploy"])
        self.assertFalse(result["backendDeploy"])

    def test_snapshot_release_contract_is_frontend_deploy_plane_only(self):
        result = deploy_scope.classify(
            ["release/v13-snapshot-readiness-contract.json"])
        self.assertTrue(result["frontendDeploy"])
        self.assertFalse(result["backendDeploy"])

    def test_public_candidate_identity_gate_is_frontend_plane_only(self):
        result = deploy_scope.classify(
            ["scripts/verify_public_candidate_release.py"])
        self.assertTrue(result["frontendDeploy"])
        self.assertFalse(result["backendDeploy"])

    def test_pages_deploys_candidate_before_seed_and_acceptance(self):
        workflow = (ROOT / ".github/workflows/deploy-pages.yml").read_text()
        self.assertIn("backend-infrastructure-readiness:", workflow)
        self.assertIn("candidate-identity:", workflow)
        self.assertIn(
            "needs: [build, backend-infrastructure-readiness, "
            "acceptance-runtime-admission]", workflow)
        self.assertIn(
            "needs: [scope, deploy, backend-infrastructure-readiness]", workflow)
        self.assertIn(
            "needs: [scope, candidate-identity, business-snapshot-trigger, "
            "acceptance-runtime-admission]", workflow)
        self.assertIn(
            "needs: [scope, deploy, candidate-identity, "
            "seed-warm-profile, business-snapshot-acceptance, "
            "backend-infrastructure-readiness, "
            "acceptance-runtime-admission]", workflow)
        self.assertIn(
            "web/scripts/release-state-machine.mjs", workflow)
        self.assertIn(
            "scripts/verify_public_candidate_release.py", workflow)
        self.assertIn(
            "backend-infrastructure-readiness-${{ github.sha }}", workflow)
        self.assertIn(
            "public-candidate-identity-${{ github.sha }}", workflow)
        self.assertIn(
            "enforce-public-candidate-identity: 'true'", workflow)
        self.assertNotIn(
            "needs: [build, seed-warm-profile, "
            "backend-infrastructure-readiness]", workflow)

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
        product = json.loads((ROOT / "product-version.json").read_text())
        frontend = json.loads((ROOT / "web/package.json").read_text())["version"]
        backend = json.loads((ROOT / "backend-version.json").read_text())["version"]
        self.assertEqual("v13.5", product["productVersion"])
        self.assertEqual("13.3.7", frontend)
        self.assertEqual("13.4.14", backend)

    def test_release_gate_names_product_and_component_coordinates(self):
        source = (ROOT / "scripts/release_gate.sh").read_text()
        self.assertIn('"productVersion": "$PRODUCT_VERSION"', source)
        self.assertIn('"frontendVersion": "$FRONTEND_VERSION"', source)
        self.assertIn('"backendVersion": "$BACKEND_VERSION"', source)
        self.assertNotIn('{"version": "$FRONTEND_VERSION"', source)

    def test_release_gate_enforces_render_skip_contract(self):
        workflow = (ROOT / ".github/workflows/release-gate.yml").read_text()
        self.assertIn("fetch-depth: 0", workflow)
        self.assertIn("python3 -B scripts/render_deploy_guard.py", workflow)
        self.assertIn("github.event.pull_request.title", workflow)
