"""Startup lines are visible in the hosting log; nothing else is.

2026-09-29: the owner could not confirm from the Render dashboard whether the
application had started or how many processes were running, because every
operational line goes to an in-process ring and never to stdout. The ring
must stay in-process — security events name the request IP, AI lines name
spend and models — so exactly the startup lines are echoed, with the process
id, which is also what answers "is one process running".
"""
import ast
import io
import pathlib
import re
from contextlib import redirect_stdout

import scanner


def test_add_log_is_silent_by_default_and_always_fills_the_ring():
    before = len(scanner.LOG_BUFFER)
    stream = io.StringIO()
    with redirect_stdout(stream):
        scanner.add_log("quiet line")
    assert stream.getvalue() == ""
    assert len(scanner.LOG_BUFFER) == min(before + 1, scanner.LOG_BUFFER.maxlen)
    assert scanner.LOG_BUFFER[-1].endswith("quiet line")


def test_echo_writes_one_line_with_the_process_id():
    import os
    stream = io.StringIO()
    with redirect_stdout(stream):
        scanner.add_log("boot line", echo=True)
    printed = stream.getvalue()
    assert printed.count("\n") == 1
    assert f"[argus pid={os.getpid()}]" in printed
    assert "boot line" in printed
    # The ring keeps the same text it always kept, without the pid prefix.
    assert scanner.LOG_BUFFER[-1].endswith("boot line")
    assert "pid=" not in scanner.LOG_BUFFER[-1]


def _echoed_messages():
    """Every add_log(..., echo=True) call's message source, from the tree."""
    tree = ast.parse(pathlib.Path("scanner.py").read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "add_log"
                and any(keyword.arg == "echo"
                        and isinstance(keyword.value, ast.Constant)
                        and keyword.value.value is True
                        for keyword in node.keywords)):
            out.append(ast.unparse(node.args[0]))
    return out


def test_only_startup_facts_reach_the_hosting_log():
    messages = _echoed_messages()
    assert 1 <= len(messages) <= 6, messages
    # No echoed line may carry anything about a person, a request or spend.
    forbidden = re.compile(
        r"ip=|\bip\b|cost|\$|token|password|secret|key|symbol|email|model",
        re.IGNORECASE)
    for message in messages:
        assert not forbidden.search(message), message
    # They say what an owner needs: the build, the scheduler, the boot result.
    joined = " ".join(messages)
    assert "ARGUS backend" in joined
    assert "Scheduler started" in joined
    assert "Boot complete" in joined


def test_the_in_process_ring_is_still_the_only_home_for_the_rest():
    source = pathlib.Path("scanner.py").read_text(encoding="utf-8")
    security = [line for line in source.split("\n")
                if "add_log(" in line and "[SECURITY]" in line]
    assert security, "the security lines are expected to exist"
    for line in security:
        assert "echo=True" not in line, line
    assert "LOG_BUFFER.append" in source
    assert source.count("print(f\"[argus pid=") == 1
