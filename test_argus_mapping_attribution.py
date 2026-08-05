"""Deterministic contracts for Linux Checkpoint V2 mapping attribution."""
from __future__ import annotations

import json
from unittest import mock

import argus_mapping_attribution as mapping
from scripts.summarize_mmap_trace import summarize


def _row(address, perms, path="", *, size=4, rss=4, anon=4,
         flags="rd wr mr mw me ac sd"):
    start = int(address, 16)
    end = start + size * 1024
    return (f"{start:x}-{end:x} {perms} 00000000 00:00 0 {path}\n"
            f"Size: {size} kB\nRss: {rss} kB\nPss: {rss} kB\n"
            f"Private_Clean: 0 kB\nPrivate_Dirty: {rss} kB\n"
            "Shared_Clean: 0 kB\nShared_Dirty: 0 kB\n"
            f"Anonymous: {anon} kB\nSwap: 0 kB\n"
            "KernelPageSize: 4 kB\nMMUPageSize: 4 kB\n"
            f"VmFlags: {flags}\n")


def test_parse_records_preserves_required_metrics_and_stable_fingerprint():
    first = mapping.parse_smaps(_row("1000", "rw-p", "[heap]"))[0]
    moved = mapping.parse_smaps(_row("9000", "rw-p", "[heap]"))[0]
    assert first.category == "heap"
    assert first.metrics["Rss"] == 4096
    assert first.metrics["Pss"] == 4096
    assert first.metrics["Anonymous"] == 4096
    assert first.metrics["KernelPageSize"] == 4096
    assert first.vm_flags == ("rd", "wr", "mr", "mw", "me", "ac", "sd")
    assert first.fingerprint() == moved.fingerprint()


def test_every_required_mapping_class_is_explicit_and_paths_are_redacted():
    text = "".join([
        _row("1000", "r-xp", "/usr/local/bin/python"),
        _row("2000", "r-xp", "/usr/lib/libsqlite3.so.0"),
        _row("3000", "rw-p", "/tmp/v2-generation-" + "a" * 32 +
             "/checkpoint-v2.sqlite"),
        _row("4000", "rw-p", "/tmp/.v2-pending-x/checkpoint-v2.sqlite"),
        _row("5000", "rw-p", "/tmp/state.incident-1.v1338-tmp"),
        _row("6000", "rw-p", "/tmp/gone (deleted)"),
        _row("7000", "rw-p", "[stack]"),
        _row("8000", "rw-p", "[stack:7]"),
        _row("9000", "rw-s", ""),
        _row("a000", "r-xp", "/usr/lib/libc.so.6"),
        _row("b000", "r-xp", "[vdso]"),
    ])
    records = mapping.parse_smaps(text)
    categories = {row.category for row in records}
    assert categories >= {
        "Python executable or extension", "SQLite library",
        "retained SQLite generation file", "V2 temporary generation file",
        "legacy checkpoint or incident temp", "deleted file", "main stack",
        "thread stack", "anonymous shared mapping", "shared library",
        "kernel/vdso/vvar/vsyscall",
    }
    structured = [row.diagnostic_record() for row in records]
    assert all("/tmp/" not in row["pathnameClass"] for row in structured)


def test_glibc_arena_pair_and_large_mmap_are_separate_categories():
    committed_kib = 1024
    reserved_kib = 64 * 1024 - committed_kib
    text = (_row("10000000", "rw-p", size=committed_kib,
                 rss=128, anon=128) +
            _row(f"{0x10000000 + committed_kib * 1024:x}", "---p",
                 size=reserved_kib, rss=0, anon=0, flags="mr mw me nr sd") +
            _row("30000000", "rw-p", size=512, rss=256, anon=256))
    records = mapping.parse_smaps(text)
    assert [row.category for row in records[:2]] == [
        "allocator arena", "allocator arena"]
    assert records[2].category == "allocator large-object mmap"


def test_category_delta_and_precise_gate_projection():
    before = mapping.parse_smaps(_row("1000", "rw-p", "[heap]"))
    after = mapping.parse_smaps(
        _row("9000", "rw-p", "[heap]") +
        _row("b000", "rw-p", "/tmp/v2-generation-" + "b" * 32 +
             "/checkpoint-v2.sqlite"))
    summary = {"categories": mapping.category_summary(after, before)}
    assert summary["categories"]["heap"]["survivingFromEarlier"] == 1
    gate = mapping.gate_projection(summary)
    assert gate["retainedGenerationFileMappings"] == 1
    assert gate["unknownMappings"] == 0


def test_allocator_diagnostics_fail_safe_off_linux():
    with mock.patch.object(mapping.sys, "platform", "darwin"):
        report = mapping.glibc_allocator_diagnostics()
    assert report["supported"] is False
    assert report["systemBytes"] is None


def test_syscall_trace_summary_links_create_unmap_and_redacts_paths(tmp_path):
    trace = tmp_path / "mmap-trace.17"
    trace.write_text(
        "1.0 mmap(NULL, 4096, PROT_READ|PROT_WRITE, "
        "MAP_PRIVATE|MAP_ANONYMOUS, -1, 0) = 0x1000\n"
        "2.0 mmap(NULL, 8192, PROT_READ, MAP_PRIVATE, "
        "3</work/private/checkpoint-v2.sqlite>, 0) = 0x2000\n"
        "3.0 munmap(0x1000, 4096) = 0\n")
    report = summarize([trace])
    assert report["mappingsCreated"] == 2
    assert report["mappingsUnmapped"] == 1
    assert report["persistentMappings"] == 1
    assert "/work/private" not in json.dumps(report)
