"""Every scheduled read of the production backend carries the operational token.

2026-09-28: owner authentication went live and four scheduled jobs went dark the
same evening: the prediction ledger, the market alerts, the event ledger and the
weekly JPX credit import, each fetching a formerly public route with a bare curl.
This test names the rule those failures taught. A workflow that runs on a
schedule and reads the production host sends X-ARGUS-ADMIN-TOKEN on every
backend read, except the two liveness routes that are deliberately open.

A shell command continued with a trailing backslash is judged as one command,
so a header on the next line counts. Calls made through workflow_http.py pass
the token as --header-env and are judged on the same joined command.
"""
import pathlib
import re

from scripts import recovery_admission

ROOT = pathlib.Path(__file__).resolve().parent
WORKFLOWS = ROOT / ".github" / "workflows"
HOST = "argus-backend-3j2m.onrender.com"
OPEN_ROUTES = ("/healthz", "/readyz")
BACKEND_READ = re.compile(r'"\$BE(/api/argus/[^"\s]*)"')
TOKEN_MARKERS = ("X-ARGUS-ADMIN-TOKEN", "--header-env X-ARGUS-ADMIN-TOKEN")


def logical_commands(text):
    """Yield (first_line_number, joined_command) with backslash continuations folded."""
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        start = index
        joined = lines[index].rstrip()
        while joined.endswith("\\") and index + 1 < len(lines):
            index += 1
            joined = joined[:-1] + " " + lines[index].strip()
        yield start + 1, joined
        index += 1


RECOVERY_OWNED = {
    pathlib.PurePosixPath(path).name
    for path in (*recovery_admission.RECOVERY_PAYLOAD_PATHS,
                 *recovery_admission.DUAL_SCOPE_RECOVERY_PAYLOAD_PATHS)
    if path.startswith(".github/workflows/")
}


def _scheduled_backend_workflows():
    """Product workflows that run on a schedule and read the production host.

    Workflows owned by the Recovery route are proven and changed there; this
    test does not reach into them.
    """
    for path in sorted(WORKFLOWS.glob("*.yml")):
        if path.name in RECOVERY_OWNED:
            continue
        text = path.read_text(encoding="utf-8")
        if HOST in text and re.search(r"^\s*-\s*cron:", text, re.MULTILINE):
            yield path, text


def test_every_scheduled_backend_read_sends_the_operational_token():
    offenders = []
    for path, text in _scheduled_backend_workflows():
        for number, command in logical_commands(text):
            match = BACKEND_READ.search(command)
            if not match or match.group(1).startswith(OPEN_ROUTES):
                continue
            if not any(marker in command for marker in TOKEN_MARKERS):
                offenders.append(f"{path.name}:{number}: {command.strip()[:110]}")
    assert offenders == [], offenders


def test_the_four_jobs_that_went_dark_are_in_scope():
    names = {path.name for path, _ in _scheduled_backend_workflows()}
    assert {"prediction-ledger.yml", "market-alerts.yml",
            "event-ledger.yml", "jpx-credit-weekly.yml"} <= names


def test_the_token_is_supplied_from_the_repository_secret_not_a_literal():
    for path, text in _scheduled_backend_workflows():
        if "X-ARGUS-ADMIN-TOKEN" in text:
            assert "${{ secrets.ARGUS_ADMIN_TOKEN }}" in text, path.name
            assert not re.search(r'X-ARGUS-ADMIN-TOKEN:\s*[A-Za-z0-9]{16,}', text), path.name
