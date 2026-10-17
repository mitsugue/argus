# -*- coding: utf-8 -*-
"""Clean-process entry point for the deterministic J-Quants breadth worker."""
import argparse
import atexit
import os
import signal
from multiprocessing.connection import Connection
from pathlib import Path
import resource
import subprocess
import sys
import types


class CleanProcess:
    """Run the dedicated entry point without replaying the server's main file."""

    def __init__(self, job_id, parent_connection, child_connection,
                 memory_soft_limit_mb, ledger_seed):
        self.job_id = job_id
        self.parent_connection = parent_connection
        self.child_connection = child_connection
        self.memory_soft_limit_mb = memory_soft_limit_mb
        self.ledger_seed = ledger_seed
        self.process = None

    def start(self):
        descriptor = self.child_connection.fileno()
        self.process = subprocess.Popen([
            sys.executable, str(Path(__file__).resolve()),
            "--job-id", self.job_id, "--connection-fd", str(descriptor),
            "--memory-limit-mb", str(self.memory_soft_limit_mb),
            "--parent-pid", str(os.getpid()),
        ], pass_fds=(descriptor,))
        # The parent must not keep a reader for the child's endpoint while
        # sending a large seed: otherwise a failed child can leave send blocked.
        self.child_connection.close()
        try:
            self.parent_connection.send(self.ledger_seed)
        except BaseException:
            if self.is_alive():
                self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            raise
        finally:
            self.ledger_seed = None
        atexit.register(self.terminate)

    def is_alive(self):
        return self.process is not None and self.process.poll() is None

    def join(self, timeout=None):
        if self.process is not None:
            try:
                self.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                pass
            if self.process.poll() is not None:
                atexit.unregister(self.terminate)

    def terminate(self):
        if self.is_alive():
            self.process.terminate()

    @property
    def exitcode(self):
        return self.process.poll() if self.process is not None else None


def _disable_quote_adapter():
    """Keep the breadth-only process from loading the stateful moomoo SDK."""
    adapter = types.ModuleType("moomoo")

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("quote_adapter_disabled_in_breadth_worker")

    adapter.OpenQuoteContext = unavailable
    adapter.OpenSecTradeContext = unavailable
    adapter.RET_OK = 0
    sys.modules["moomoo"] = adapter


def process_entry(job_id, connection, memory_soft_limit_mb, ledger_seed=None):
    """Import the backend only after isolating unrelated quote side effects."""
    adapter_preloaded = "moomoo" in sys.modules
    _disable_quote_adapter()
    connection.send({"op": "startup", "entryPoint": Path(__file__).name,
                     "quoteAdapterPreloaded": adapter_preloaded})
    response = connection.recv()
    if not isinstance(response, dict) or response.get("ok") is not True:
        raise RuntimeError("breadth_parent_ipc_failed")
    import scanner
    scanner._jquants_breadth_process_entry(
        job_id, connection, memory_soft_limit_mb, ledger_seed)


def _bind_parent_lifetime(parent_pid):
    if os.getppid() != parent_pid:
        raise RuntimeError("breadth_parent_process_changed")
    if sys.platform.startswith("linux"):
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(1, signal.SIGTERM, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "breadth_parent_lifetime_unavailable")
        if os.getppid() != parent_pid:
            raise RuntimeError("breadth_parent_process_changed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--connection-fd", type=int, required=True)
    parser.add_argument("--memory-limit-mb", type=int, required=True)
    parser.add_argument("--parent-pid", type=int, required=True)
    args = parser.parse_args()
    _bind_parent_lifetime(args.parent_pid)
    limit = max(256, min(args.memory_limit_mb, 1280))
    _, hard = resource.getrlimit(resource.RLIMIT_DATA)
    limit_bytes = limit * 1024 * 1024
    try:
        resource.setrlimit(resource.RLIMIT_DATA,
                           (min(limit_bytes, hard) if hard not in
                            (-1, resource.RLIM_INFINITY) else limit_bytes, hard))
    except (ValueError, OSError):
        # macOS does not implement this Linux allocation limit consistently.
        # Production Linux must enforce it before receiving the seed.
        if sys.platform != "darwin":
            raise
    connection = Connection(args.connection_fd)
    try:
        ledger_seed = connection.recv()
        if not isinstance(ledger_seed, dict):
            raise ValueError("breadth_ledger_seed_invalid")
        process_entry(args.job_id, connection, limit, ledger_seed)
    finally:
        connection.close()


if __name__ == "__main__":
    main()
