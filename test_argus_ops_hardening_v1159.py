"""ARGUS V11.5.9 — P0.5 ops hardening: redaction scripts / secret-free docs /
OpenD 10.8 runbook presence / us_only status semantics."""
import json
import os
import re
import subprocess

import scanner

SCRIPTS_DIR = "bridge/scripts"
EXPECTED_SCRIPTS = [
    "check_opend_status.sh", "check_bridge_status.sh", "safe_opend_process_view.sh",
    "safe_public_bridge_status.sh", "request_pic_verify_code.sh",
    "submit_pic_verify_code.sh", "request_sms_verify_code.sh",
    "submit_sms_verify_code.sh", "restart_argus_bridge.sh",
]
REDACT_TARGETS = ["login_account", "login_pwd", "oken", "ecret", "mac", "uth", "assword"]


def _read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


# ── scripts exist, are executable, and redact ────────────────────────────────

def test_all_scripts_exist_with_shebang():
    for s in EXPECTED_SCRIPTS + ["_redact.sh", "_telnet.sh"]:
        p = os.path.join(SCRIPTS_DIR, s)
        assert os.path.isfile(p), f"missing {s}"
        src = _read(p)
        assert src.startswith("#!/usr/bin/env bash"), f"{s}: shebang"
        assert os.access(p, os.X_OK), f"{s}: not executable"


def test_redact_filter_covers_all_targets():
    src = _read(os.path.join(SCRIPTS_DIR, "_redact.sh"))
    for t in ("login_account", "login_pwd", "REDACTED"):
        assert t in src, t
    # token/secret/hmac/auth/password covered case-insensitively
    for word in ("Tt][Oo][Kk][Ee][Nn", "Ss][Ee][Cc][Rr][Ee][Tt", "Hh][Mm][Aa][Cc",
                 "Aa][Uu][Tt][Hh", "Pp][Aa][Ss][Ss][Ww][Oo][Rr][Dd"):
        assert word in src, f"redact pattern missing: {word}"


def test_redact_filter_actually_redacts():
    """Run the real filter against a synthetic credential-looking line."""
    sample = ("./OpenD -login_account=12345678 -login_pwd=Hunter2Pass "
              "-login_pwd_md5=abcdef token=AAAA secret=BBBB hmac_key=CCCC "
              "password=DDDD auth=EEEE\n")
    out = subprocess.run(
        ["bash", "-c", f'source {SCRIPTS_DIR}/_redact.sh; redact'],
        input=sample, capture_output=True, text=True).stdout
    for leaked in ("12345678", "Hunter2Pass", "abcdef", "AAAA", "BBBB", "CCCC",
                   "DDDD", "EEEE"):
        assert leaked not in out, f"leaked: {leaked} in {out!r}"
    assert "[REDACTED]" in out


def test_process_view_and_log_scripts_pipe_through_redact():
    for s in ("safe_opend_process_view.sh", "check_opend_status.sh",
              "check_bridge_status.sh", "restart_argus_bridge.sh"):
        src = _read(os.path.join(SCRIPTS_DIR, s))
        assert "_redact.sh" in src and "redact" in src, f"{s}: no redaction pipe"


def test_submit_scripts_never_echo_codes():
    for s in ("submit_pic_verify_code.sh", "submit_sms_verify_code.sh"):
        src = _read(os.path.join(SCRIPTS_DIR, s))
        assert "read -r -s" in src, f"{s}: code must be silent-input"
        assert 'echo "$CODE"' not in src and "echo $CODE" not in src, f"{s}: echoes code"
        assert "unset CODE" in src, f"{s}: code not cleared"
        assert re.search(r"grep -viE? 'code='", src), f"{s}: response must strip code echo"


# ── docs/scripts carry no raw secrets ────────────────────────────────────────

def test_bridge_tree_has_no_raw_secrets():
    """Placeholder-only: no real-looking values for credentials in the repo.

    Scans TEXT sources only. On CI, pytest imports bridge/moomoo_push and
    CPython drops bridge/__pycache__/*.pyc (binary) into the tree — reading
    those as UTF-8 crashed this test on EVERY CI run since v11.5.9 while
    passing locally (no pycache there). Secrets live in source text; caches
    and binaries are pruned, and decoding is lenient as a belt-and-braces
    (the scanned patterns are pure ASCII, so replacement never hides them)."""
    offenders = []
    for root, dirs, files in os.walk("bridge"):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git")]
        for fn in files:
            if fn.endswith((".pyc", ".pyo", ".so", ".zip", ".png", ".jpg")):
                continue
            p = os.path.join(root, fn)
            with open(p, encoding="utf-8", errors="replace") as f:
                src = f.read()
            for m in re.finditer(r"(ARGUS_ADMIN_TOKEN|ARGUS_BRIDGE_HMAC_SECRET)[ \t]*=[ \t]*([^\n]*)", src):
                val = m.group(2).strip('"\'')
                if val and val not in ("PUT-YOUR-TOKEN-HERE",) and not val.startswith("$"):
                    offenders.append(f"{p}: {m.group(1)}={val[:6]}…")
            for m in re.finditer(r"-login_pwd[a-z_0-9]*=(\S+)", src):
                val = m.group(1).strip('"\'')
                # only placeholders / redaction artifacts / shell vars allowed
                if val and not re.match(r"^(\[REDACTED\]|\.\.\.|<|\$|\\1|\)\[)", val):
                    offenders.append(f"{p}: login_pwd literal {val[:6]}…")
    assert not offenders, offenders


def test_opend_service_example_no_secret_env():
    src = _read("bridge/opend.service.example")
    assert "Environment=" not in src or "SECRET" not in src.upper().split("ENVIRONMENT=")[1][:80]
    assert re.search(r"^Environment=", src, re.M) is None, "no Environment= lines at all"
    assert "127.0.0.1" in src                     # localhost-only guidance
    assert "残存リスク" in src                      # honest residual-risk note
    assert "10.8.6818" in src


def test_runbook_covers_required_topics():
    src = _read("bridge/README.md")
    for needle in ("10.8.6818", "10.7.6718", "PicVerifyCode.png", "req_pic_verify_code",
                   "input_pic_verify_code", "req_phone_verify_code", "input_phone_verify_code",
                   "US Stocks LV3", "JPN Stocks 権限なし", "US-onlyモードは意図的",
                   "moomoo_OpenD_latest.tar.gz", "残存リスク", "絶対に貼らない",
                   "check_opend_status.sh", "telnet_ip", "22222"):
        assert needle in src, f"runbook missing: {needle}"
    # graphic-code staleness warning
    assert "失効" in src


def test_no_old_10_7_path_hardcoded_outside_history():
    """The old OpenD dir may appear only as a historical note in the runbook."""
    hits = []
    for root, dirs, files in os.walk("."):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "dist", "dev-dist")]
        for fn in files:
            if not fn.endswith((".py", ".md", ".sh", ".yml", ".service", ".example")):
                continue
            p = os.path.join(root, fn)
            try:
                src = _read(p)
            except Exception:
                continue
            if "moomoo_OpenD_10.7" in src and "test_argus_ops_hardening" not in p:
                hits.append(p)
    assert hits in ([], ["./bridge/README.md"]), f"old path hardcoded: {hits}"


# ── status semantics: us_only is healthy, JP disabled is not a failure ───────

def test_us_only_reported_and_not_a_failure(monkeypatch):
    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "tok")
    hb = {"at": scanner._ai_now_iso(), "bridgeVersion": "11.5.7", "bridgeMode": "us_only",
          "openDStatus": "connected", "lastQuotePushAt": scanner._ai_now_iso(),
          "lastUSQuotePushAt": scanner._ai_now_iso(), "lastJPQuotePushAt": None,
          "acceptedCountLastPush": 12, "usRealtimeStatus": "ok",
          "jpRealtimeStatus": "disabled", "jpFallbackActive": True,
          "jpLastErrorClass": None, "diskUsagePct": 15.6, "intervalSec": 15}
    with scanner.app.test_client() as c:
        c.post("/api/argus/bridge/heartbeat", json={"heartbeat": hb},
               headers={"X-ARGUS-ADMIN-TOKEN": "tok"})
        d = c.get("/api/argus/bridge/status").get_json()
    assert d["bridgeMode"] == "us_only"
    assert d["bridgeProcess"] == "ok"                 # JP disabled ≠ bridge failure
    assert d["jpRealtimeStatus"] == "disabled"
    lamps = {l["key"]: l for l in scanner._system_health()["lamps"]}
    assert lamps["bridge"]["status"] == "ok"
    assert lamps["jp_realtime"]["status"] == "off"    # gray, not warning/stopped
    blob = json.dumps(d, ensure_ascii=False).lower()
    for bad in ('"token":', '"secret":', '"password":', '"login_pwd', '"login_account'):
        assert bad not in blob, bad
