"""The checkpoint gate never publishes the production state in the clear (2026-10-19).

The repository is public; its workflow artifacts can be downloaded by anyone
signed in to GitHub. The shared production-shaped state travels sealed.
"""
import pathlib
import re

WORKFLOW = pathlib.Path(".github/workflows/checkpoint-v2-gate.yml").read_text()


def jobs():
    body = WORKFLOW.split("\njobs:\n", 1)[1]
    parts = re.split(r"^  ([a-z0-9-]+):\n", body, flags=re.M)
    return {parts[i]: re.split(r"^      - ", parts[i + 1], flags=re.M)[1:] for i in range(1, len(parts), 2)}


def test_the_shared_state_is_sealed_before_upload():
    producer = jobs()["exact-public-state"]
    seal = next(i for i, s in enumerate(producer) if s.startswith("name: Seal the shared exact state"))
    upload = next(i for i, s in enumerate(producer) if "upload-artifact" in s)
    assert seal < upload
    assert "owner-artifact-envelope.mjs seal" in producer[seal]
    assert "rm -rf artifacts/plain-source" in producer[seal]
    assert "path: artifacts/sealed-source\n" in producer[upload]


def test_no_upload_carries_the_plain_state_and_every_consumer_opens_it():
    consumers = 0
    for job, items in jobs().items():
        for index, step in enumerate(items):
            if "upload-artifact" in step:
                assert "checkpoint-v2-exact-source.json" not in step, job
            if "download-artifact" in step and "checkpoint-v2-exact-source-" in step:
                consumers += 1
                assert "path: artifacts/sealed-source\n" in step, job
                assert "owner-artifact-envelope.mjs unseal" in items[index + 1], job
                assert "ARGUS_OWNER_ARTIFACT_KEY" in items[index + 1], job
    assert consumers == 6  # 既存5検査と、失敗時だけの非公開保全も同じ暗号化境界で読む。
