from scripts.verify_production_backend_release import evaluate


SHA = "e" * 40


def test_verified_get_evidence_matches_exact_candidate():
    ok, reason = evaluate(
        health_status=200,
        health={
            "status": "ok",
            "buildSha": SHA[:7],
            "backendVersion": "13.3.6",
        },
        ready_status=200,
        ready={"ready": True, "buildSha": SHA[:7]},
        expected_sha=SHA,
        expected_version="13.3.6",
    )
    assert ok is True
    assert reason == "verified"


def test_failed_deploy_or_wrong_version_cannot_publish():
    mismatch, mismatch_reason = evaluate(
        health_status=200,
        health={
            "status": "ok",
            "buildSha": "f" * 7,
            "backendVersion": "13.3.6",
        },
        ready_status=200,
        ready={"ready": True},
        expected_sha=SHA,
        expected_version="13.3.6",
    )
    unavailable, unavailable_reason = evaluate(
        health_status=502,
        health=None,
        ready_status=503,
        ready=None,
        expected_sha=SHA,
        expected_version="13.3.6",
    )
    assert mismatch is False and mismatch_reason == "health_sha_mismatch"
    assert unavailable is False and unavailable_reason == "health_unavailable"
