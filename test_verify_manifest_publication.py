import base64

import pytest

from scripts.verify_manifest_publication import (
    PublicationVerificationError,
    verify_authoritative,
    wait_for_raw,
)


EXPECTED = b'{"deploymentId":"dep-current1"}\n'
COMMIT = "c" * 40


def test_authoritative_ref_and_blob_exact_bytes_succeed():
    commit = verify_authoritative(
        expected_bytes=EXPECTED,
        fetch_ref=lambda: {"object": {"sha": COMMIT}},
        fetch_content=lambda sha: {
            "type": "file",
            "encoding": "base64",
            "content": base64.b64encode(EXPECTED).decode("ascii"),
        },
    )
    assert commit == COMMIT


def test_authoritative_write_failure_is_distinct():
    with pytest.raises(
        PublicationVerificationError,
        match="authoritative_bytes_mismatch",
    ):
        verify_authoritative(
            expected_bytes=EXPECTED,
            fetch_ref=lambda: {"object": {"sha": COMMIT}},
            fetch_content=lambda sha: {
                "type": "file",
                "encoding": "base64",
                "content": base64.b64encode(b"stale").decode("ascii"),
            },
        )


def test_public_raw_may_be_stale_then_converge_without_republish():
    values = iter([b"stale", b"stale", EXPECTED])
    attempts = wait_for_raw(
        expected_bytes=EXPECTED,
        fetch_raw=lambda _: next(values),
        timeout_seconds=300,
        poll_seconds=0,
        monotonic=lambda: 0,
        sleep=lambda _: None,
    )
    assert attempts == 3


def test_public_raw_convergence_timeout_is_bounded():
    clock = iter([0, 0, 301])
    with pytest.raises(
        PublicationVerificationError,
        match="public_raw_convergence_timeout",
    ):
        wait_for_raw(
            expected_bytes=EXPECTED,
            fetch_raw=lambda _: b"stale",
            timeout_seconds=300,
            poll_seconds=0,
            monotonic=lambda: next(clock),
            sleep=lambda _: None,
        )
