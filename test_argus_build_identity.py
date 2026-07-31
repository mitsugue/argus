"""Deterministic tests for the EC2 production-manifest identity gate."""
import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).parent
PATH = ROOT / "scripts/argus_build_identity.py"
SPEC = importlib.util.spec_from_file_location("argus_build_identity", PATH)
identity = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(identity)

OLD = "1" * 40
NEW = "2" * 40
NOW = "2026-07-31T00:00:00Z"


def manifest(sha=OLD, deployed_at="2026-07-30T00:00:00Z"):
    return {
        "schema": "argus-production-release-manifest-v1",
        "service": "argus-backend",
        "environment": "production",
        "buildSha": sha,
        "version": "13.3.6",
        "deployedAt": deployed_at,
        "deploymentId": "deploy-1",
        "verifiedHealth": True,
        "verifiedReady": True,
    }


class BuildIdentityResolutionTests(unittest.TestCase):
    def resolve(
        self,
        trusted=None,
        backend=OLD[:7],
        state=None,
        now=NOW,
        grace=900,
        error=None,
        static="",
    ):
        return identity.resolve_identity(
            manifest=manifest() if trusted is None else trusted,
            backend_sha=backend,
            state=state or {},
            now_iso=now,
            grace_seconds=grace,
            manifest_error=error,
            static_sha=static,
        )

    def test_manifest_match_is_verified_and_persists_full_sha(self):
        decision, state = self.resolve()
        self.assertEqual(decision["status"], "verified")
        self.assertEqual(
            decision["identitySource"], "production_release_manifest")
        self.assertFalse(decision["buildMismatch"])
        self.assertEqual(state["lastVerifiedSha"], OLD)
        self.assertEqual(
            state["lastManifestDeployedAt"], "2026-07-30T00:00:00Z")

    def test_frontend_or_pages_main_change_is_irrelevant(self):
        first, state = self.resolve()
        second, next_state = self.resolve(state=state)
        self.assertEqual(first["expectedBuildSha"], OLD)
        self.assertEqual(second["expectedBuildSha"], OLD)
        self.assertEqual(next_state["lastVerifiedSha"], OLD)

    def test_manifest_advance_old_backend_is_expected_skip_during_grace(self):
        decision, state = self.resolve(
            trusted=manifest(NEW), backend=OLD[:7])
        self.assertEqual(decision["status"], "expected_skip")
        self.assertEqual(decision["errorClass"], "deployment_transition")
        self.assertEqual(state["transitionSha"], NEW)

    def test_manifest_advance_then_new_backend_clears_transition(self):
        decision, state = self.resolve(
            trusted=manifest(NEW),
            backend=NEW[:7],
            state={
                "transitionSha": NEW,
                "transitionStartedAt": "2026-07-30T23:55:00Z",
            },
        )
        self.assertEqual(decision["status"], "verified")
        self.assertNotIn("transitionSha", state)
        self.assertEqual(state["lastVerifiedSha"], NEW)

    def test_transition_timeout_fails_closed(self):
        decision, _ = self.resolve(
            trusted=manifest(NEW),
            backend=OLD[:7],
            state={
                "transitionSha": NEW,
                "transitionStartedAt": "2026-07-30T23:00:00Z",
            },
            grace=900,
        )
        self.assertEqual(decision["status"], "failure")
        self.assertEqual(
            decision["errorClass"], "deployment_transition_timeout")

    def test_manifest_outage_uses_only_matching_last_verified_degraded(self):
        decision, _ = self.resolve(
            trusted=None,
            backend=OLD[:7],
            error="production_manifest_unavailable",
            state={"lastVerifiedSha": OLD},
        )
        self.assertEqual(decision["status"], "verified")
        self.assertEqual(
            decision["identitySource"], "last_verified_fallback")
        self.assertTrue(decision["degraded"])

    def test_manifest_outage_rejects_fallback_mismatch(self):
        decision, _ = self.resolve(
            trusted=None,
            backend=NEW[:7],
            error="production_manifest_unavailable",
            state={"lastVerifiedSha": OLD},
        )
        self.assertEqual(decision["status"], "failure")

    def test_static_pin_is_first_install_only_and_must_match(self):
        accepted, _ = self.resolve(
            trusted=None,
            backend=OLD[:7],
            error="production_manifest_unavailable",
            static=OLD,
        )
        rejected, _ = self.resolve(
            trusted=None,
            backend=NEW[:7],
            error="production_manifest_unavailable",
            static=OLD,
        )
        self.assertEqual(
            accepted["identitySource"], "static_bootstrap_fallback")
        self.assertEqual(accepted["status"], "verified")
        self.assertTrue(accepted["degraded"])
        self.assertEqual(rejected["status"], "failure")

    def test_verified_state_has_priority_over_static_pin(self):
        decision, _ = self.resolve(
            trusted=None,
            backend=NEW[:7],
            error="production_manifest_unavailable",
            state={"lastVerifiedSha": NEW},
            static=OLD,
        )
        self.assertEqual(decision["status"], "verified")
        self.assertEqual(
            decision["identitySource"], "last_verified_fallback")
        self.assertEqual(decision["expectedBuildSha"], NEW)

    def test_backend_health_never_promotes_itself(self):
        decision, state = self.resolve(
            trusted=None,
            backend=NEW[:7],
            error="production_manifest_unavailable",
        )
        self.assertEqual(decision["status"], "failure")
        self.assertNotIn("lastVerifiedSha", state)

    def test_rollback_manifest_with_older_sha_is_verified(self):
        state = {
            "lastVerifiedSha": NEW,
            "lastManifestDeployedAt": "2026-07-30T00:00:00Z",
        }
        decision, next_state = self.resolve(
            trusted=manifest(
                OLD, deployed_at="2026-07-31T00:00:00Z"),
            backend=OLD[:7],
            state=state,
            now="2026-07-31T00:01:00Z",
        )
        self.assertEqual(decision["status"], "verified")
        self.assertEqual(next_state["lastVerifiedSha"], OLD)

    def test_observed_sha_must_be_valid(self):
        short, _ = self.resolve(backend="abc")
        malformed, _ = self.resolve(backend="notasha")
        self.assertEqual(short["errorClass"], "backend_build_unavailable")
        self.assertEqual(malformed["status"], "failure")


class BuildIdentityDeploymentContractTests(unittest.TestCase):
    def test_root_atomic_state_and_safe_decision_contract(self):
        source = PATH.read_text()
        self.assertIn("os.geteuid() != 0", source)
        self.assertIn("os.replace(temporary, path)", source)
        self.assertIn("mode=0o600", source)
        self.assertNotIn("ARGUS_ADMIN_TOKEN", source)
        self.assertNotIn("/commits/main", source)


if __name__ == "__main__":
    unittest.main()
