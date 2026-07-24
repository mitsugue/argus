import json
import sys
import types
import unittest

import argus_release_identity as identity
import argus_remote_durability as durability

_moomoo = types.ModuleType("moomoo")
_moomoo.OpenQuoteContext = lambda *args, **kwargs: None
_moomoo.OpenSecTradeContext = lambda *args, **kwargs: None
_moomoo.RET_OK = 0
sys.modules.setdefault("moomoo", _moomoo)

import scanner


class ReleaseIdentityTests(unittest.TestCase):
    def test_version_sources_are_independent_and_current(self):
        self.assertEqual("13.3.1", identity.backend_version())
        self.assertEqual("13.3.0", identity.frontend_version())
        self.assertEqual(identity.backend_version(),
                         scanner._semantic_app_version())
        self.assertEqual(identity.frontend_version(),
                         scanner._frontend_semantic_version())

    def test_four_coordinates_are_never_inferred(self):
        value = identity.release_identity(
            backend_sha="backend1", frontend_sha="frontend1")
        self.assertEqual({
            "backendVersion": "13.3.1",
            "backendBuildSha": "backend1",
            "frontendVersion": "13.3.0",
            "frontendBuildSha": "frontend1",
        }, value)
        unknown = identity.release_identity(backend_sha=None)
        self.assertEqual("unknown", unknown["backendBuildSha"])
        self.assertEqual("unknown", unknown["frontendBuildSha"])

    def test_public_build_identity_retains_compatibility_fields(self):
        value = durability.build_identity(
            app_version="13.3.0", backend_sha="abc1234",
            frontend_version="13.3.0", frontend_sha="def5678")
        self.assertEqual("13.3.0", value["appVersion"])
        self.assertEqual("13.3.0", value["backendVersion"])
        self.assertEqual("abc1234", value["backendBuildSha"])
        self.assertEqual("13.3.0", value["frontendVersion"])
        self.assertEqual("def5678", value["frontendBuildSha"])

    def test_version_files_are_plain_public_metadata(self):
        backend = json.loads(identity.BACKEND_VERSION_FILE.read_text())
        frontend = json.loads(identity.FRONTEND_VERSION_FILE.read_text())
        self.assertEqual({"version": "13.3.1"}, backend)
        self.assertEqual("13.3.0", frontend["version"])


if __name__ == "__main__":
    unittest.main()
