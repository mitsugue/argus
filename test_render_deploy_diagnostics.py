"""Read-only Render deploy diagnostics: shape tolerance, selection, masking."""
import importlib.util
import pathlib

import pytest

_spec = importlib.util.spec_from_file_location(
    "render_deploy_diagnostics",
    pathlib.Path(__file__).with_name("scripts") / "render_deploy_diagnostics.py")
rdd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rdd)

SERVICE = "srv-d8j2hts8aovs738s1in0"


def _fake_fetch(calls):
    def fetch(url):
        calls.append(url)
        if url.endswith("/services/" + SERVICE):
            return {"id": SERVICE, "name": "argus-backend", "ownerId": "tea-123"}
        if "/deploys?limit=" in url:
            return [
                {"deploy": {"id": "dep-live", "status": "live", "trigger": "new_commit",
                            "createdAt": "2026-09-28T09:30:00Z", "finishedAt": "2026-09-28T09:36:00Z",
                            "commit": {"id": "3d48b436" + "0" * 32, "message": "Release v13.7.54\n\nbody"}}},
                {"deploy": {"id": "dep-fail", "status": "build_failed", "trigger": "new_commit",
                            "createdAt": "2026-09-28T10:27:00Z", "finishedAt": "2026-09-28T10:39:00Z",
                            "commit": {"id": "e2b775e0" + "0" * 32, "message": "Merge pull request #509 rnd_SECRETSECRET1234"}}},
            ]
        if "/logs?" in url:
            if "endTime=2026-09-28T10%3A39%3A00Z" in url:
                return {"logs": [
                    {"timestamp": "2026-09-28T10:38:59Z", "message": "ERROR: pip failed Authorization: Bearer abc.def"},
                    {"timestamp": "2026-09-28T10:38:58Z", "message": "Collecting openai"}],
                    "hasMore": True, "nextStartTime": "2026-09-28T10:27:00Z",
                    "nextEndTime": "2026-09-28T10:38:58Z"}
            return {"logs": [{"timestamp": "2026-09-28T10:27:05Z", "message": "==> Running build command 'pip install -r requirements.txt'"}],
                    "hasMore": False}
        raise AssertionError(url)
    return fetch


def test_diagnose_lists_deploys_and_fetches_the_newest_failed_build_log():
    calls = []
    result = rdd.diagnose(_fake_fetch(calls), service_id=SERVICE, limit=5)
    assert [row["status"] for row in result["deploys"]] == ["live", "build_failed"]
    assert result["newestFailed"]["id"] == "dep-fail"
    assert result["newestFailed"]["subject"] == "Merge pull request #509 [masked]"
    assert result["buildLogStatus"] == "fetched"
    messages = [row["message"] for row in result["buildLog"]]
    assert messages[0].startswith("==> Running build command")
    assert messages[-1] == "ERROR: pip failed Authorization: [masked]"
    assert sum("/logs?" in url for url in calls) == 2
    assert all("ownerId=tea-123" in url for url in calls if "/logs?" in url)
    summary = rdd.summarize(result)
    assert "build_failed" in summary and "rnd_SECRET" not in summary and "Bearer abc" not in summary


def test_no_failed_deploy_and_shape_tolerance():
    def fetch(url):
        if url.endswith("/services/" + SERVICE):
            return {"ownerId": "tea-1"}
        return {"deploys": [{"id": "d1", "status": "live", "createdAt": "2026-01-01T00:00:00Z"}]}
    result = rdd.diagnose(fetch, service_id=SERVICE)
    assert result["newestFailed"] is None and result["buildLogStatus"] == "no_failed_deploy"
    assert "No failed deploy" in rdd.summarize(result)
    with pytest.raises(rdd.DiagnosticsError):
        rdd.diagnose(fetch, service_id="not-a-service")


def test_build_log_paging_is_bounded():
    pages = []

    def fetch(url):
        pages.append(url)
        return {"logs": [{"timestamp": f"t{len(pages)}", "message": "x"}],
                "hasMore": True, "nextStartTime": "s", "nextEndTime": f"e{len(pages)}"}
    lines = rdd.fetch_build_log(fetch, owner_id="o", service_id=SERVICE,
                                start="a", end="b", max_pages=3)
    assert len(pages) == 3 and len(lines) == 3


def test_mask_covers_token_shapes_but_not_commit_shas():
    sha = "e2b775e039b6a3abadb00d4c36e16332b65e41df"
    text = f"commit {sha} key rnd_abcdefghijkl token ghp_{'a' * 30} sk-{'b' * 20}"
    masked = rdd.mask(text)
    assert sha in masked and "rnd_" not in masked and "ghp_" not in masked and "sk-b" not in masked
