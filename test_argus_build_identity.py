"""Deterministic tests for the EC2 build-identity deployment gate."""
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
NOW = "2026-07-22T07:00:00Z"


class BuildIdentityResolutionTests(unittest.TestCase):
    def resolve(self, trusted=OLD, backend=OLD[:7], state=None,
                now=NOW, grace=900, error=None, static=""):
        return identity.resolve_identity(
            trusted_sha=trusted, backend_sha=backend, state=state or {},
            now_iso=now, grace_seconds=grace, upstream_error=error,
            static_sha=static)

    def test_old_main_old_backend_is_verified(self):
        decision, state = self.resolve()
        self.assertEqual(decision["status"], "verified")
        self.assertFalse(decision["buildMismatch"])
        self.assertEqual(state["lastVerifiedSha"], OLD)

    def test_new_main_old_backend_is_expected_skip_during_grace(self):
        decision, state = self.resolve(trusted=NEW, backend=OLD[:7])
        self.assertEqual(decision["status"], "expected_skip")
        self.assertEqual(decision["errorClass"], "deployment_transition")
        self.assertEqual(state["transitionSha"], NEW)

    def test_new_main_new_backend_clears_transition_and_verifies(self):
        decision, state = self.resolve(
            trusted=NEW, backend=NEW[:7],
            state={"transitionSha": NEW,
                   "transitionStartedAt": "2026-07-22T06:55:00Z"})
        self.assertEqual(decision["status"], "verified")
        self.assertNotIn("transitionSha", state)
        self.assertEqual(state["lastVerifiedSha"], NEW)

    def test_transition_timeout_is_failure(self):
        decision, _ = self.resolve(
            trusted=NEW, backend=OLD[:7],
            state={"transitionSha": NEW,
                   "transitionStartedAt": "2026-07-22T06:00:00Z"},
            grace=900)
        self.assertEqual(decision["status"], "failure")
        self.assertEqual(decision["errorClass"],
                         "deployment_transition_timeout")

    def test_github_down_uses_only_matching_last_verified_sha(self):
        decision, _ = self.resolve(
            trusted="", backend=OLD[:7], error="github_unavailable",
            state={"lastVerifiedSha": OLD,
                   "lastVerifiedAt": "2026-07-22T06:30:00Z"})
        self.assertEqual(decision["status"], "verified")
        self.assertEqual(decision["identitySource"],
                         "last_verified_fallback")

    def test_github_down_rejects_unmatched_or_missing_verified_state(self):
        mismatch, _ = self.resolve(
            trusted="", backend=NEW[:7], error="github_unavailable",
            state={"lastVerifiedSha": OLD})
        missing, _ = self.resolve(
            trusted="", backend=NEW[:7], error="github_unavailable")
        self.assertEqual(mismatch["status"], "failure")
        self.assertEqual(missing["status"], "failure")
        self.assertEqual(mismatch["errorClass"], "github_unavailable")

    def test_static_pin_is_bootstrap_only_and_must_match_backend(self):
        accepted, _ = self.resolve(
            trusted="", backend=OLD[:7], error="github_unavailable",
            static=OLD)
        rejected, _ = self.resolve(
            trusted="", backend=NEW[:7], error="github_unavailable",
            static=OLD)
        self.assertEqual(accepted["identitySource"],
                         "static_bootstrap_fallback")
        self.assertEqual(accepted["status"], "verified")
        self.assertEqual(rejected["status"], "failure")

    def test_backend_health_never_promotes_itself(self):
        decision, state = self.resolve(
            trusted="", backend=NEW[:7], error="github_unavailable")
        self.assertEqual(decision["status"], "failure")
        self.assertNotIn("lastVerifiedSha", state)


class BuildIdentityDeploymentContractTests(unittest.TestCase):
    def test_root_atomic_state_and_safe_decision_contract(self):
        source = PATH.read_text()
        self.assertIn("os.geteuid() != 0", source)
        self.assertIn("os.replace(temporary, path)", source)
        self.assertIn("mode=0o600", source)
        self.assertNotIn("ARGUS_ADMIN_TOKEN", source)


if __name__ == "__main__":
    unittest.main()
