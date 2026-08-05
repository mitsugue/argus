"""Linux mapping/glibc attribution used only by the isolated V2 probe."""
from __future__ import annotations

import collections
import ctypes
import dataclasses
import hashlib
import os
import pathlib
import re
import sys
import xml.etree.ElementTree as ET
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

_HEADER = re.compile(
    r"^(?P<start>[0-9a-f]+)-(?P<end>[0-9a-f]+)\s+(?P<perms>\S+)\s+"
    r"(?P<offset>[0-9a-f]+)\s+(?P<device>\S+)\s+(?P<inode>\d+)\s*(?P<path>.*)$")
_KB_FIELDS = {"Size", "Rss", "Pss", "Private_Clean", "Private_Dirty",
              "Shared_Clean", "Shared_Dirty", "Anonymous", "Swap",
              "KernelPageSize", "MMUPageSize"}
_GENERATION_RE = re.compile(r"v2-generation-([0-9a-f]{32})")
_ARENA_RESERVATION = 64 * 1024 * 1024


@dataclasses.dataclass
class MappingRecord:
    start: int
    end: int
    permissions: str
    offset: int
    device: str
    inode: int
    pathname: str
    metrics: Dict[str, int]
    vm_flags: Tuple[str, ...]
    category: str = "unknown"

    @property
    def virtual_bytes(self) -> int:
        return self.end - self.start

    def fingerprint(self) -> str:
        stable = (self.category, normalized_path(self.pathname, self.category),
                  self.permissions, self.offset, self.device,
                  self.inode if self.pathname and not
                  self.pathname.startswith("[") else 0,
                  self.virtual_bytes, tuple(sorted(self.vm_flags)))
        return hashlib.sha256(repr(stable).encode()).hexdigest()[:24]

    def diagnostic_record(self) -> Dict[str, Any]:
        """Aggregated artifact record; raw paths stay only in raw smaps."""
        return {
            "startAddress": f"0x{self.start:x}",
            "endAddress": f"0x{self.end:x}",
            "virtualBytes": self.virtual_bytes,
            "permissions": self.permissions,
            "fileOffset": self.offset,
            "device": self.device,
            "inode": self.inode,
            "pathnameClass": redacted_path(self.pathname, self.category),
            "category": self.category,
            "fingerprint": self.fingerprint(),
            **{key: self.metrics.get(key, 0) for key in _KB_FIELDS},
            "VmFlags": list(self.vm_flags),
        }


def parse_smaps(text: str) -> List[MappingRecord]:
    records: List[MappingRecord] = []
    current = None
    for raw in text.splitlines():
        match = _HEADER.match(raw)
        if match:
            current = MappingRecord(
                int(match["start"], 16), int(match["end"], 16),
                match["perms"], int(match["offset"], 16), match["device"],
                int(match["inode"]), match["path"].strip(), {}, ())
            records.append(current)
            continue
        if current is None:
            continue
        key, separator, value = raw.partition(":")
        if separator and key in _KB_FIELDS and value.split():
            current.metrics[key] = int(value.split()[0]) * 1024
        elif separator and key == "VmFlags":
            current.vm_flags = tuple(value.split())
    classify_records(records)
    return records


def _anonymous_private(row: MappingRecord) -> bool:
    return (not row.pathname or row.pathname.startswith("[anon:")) and \
        row.permissions.endswith("p")


def _mark_arena_pairs(records: Sequence[MappingRecord]) -> None:
    anonymous = [row for row in records if _anonymous_private(row)]
    by_start = {row.start: row for row in anonymous}
    for row in anonymous:
        following = by_start.get(row.end)
        if following is None or not following.permissions.startswith("---"):
            continue
        combined = row.virtual_bytes + following.virtual_bytes
        if combined >= _ARENA_RESERVATION and \
                combined % _ARENA_RESERVATION == 0:
            row.category = following.category = "allocator arena"


def classify_records(records: Sequence[MappingRecord], *,
                     active_generation: Optional[str] = None) -> None:
    for row in records:
        path, lower = row.pathname, row.pathname.lower()
        generation_match = _GENERATION_RE.search(lower)
        if path in {"[vdso]", "[vvar]", "[vvar_vclock]", "[vsyscall]"}:
            row.category = "kernel/vdso/vvar/vsyscall"
        elif path == "[heap]":
            row.category = "heap"
        elif path == "[stack]":
            row.category = "main stack"
        elif path.startswith("[stack:"):
            row.category = "thread stack"
        elif "(deleted)" in lower:
            row.category = "deleted file"
        elif ".v1338-tmp" in lower or ".incident-" in lower:
            row.category = "legacy checkpoint or incident temp"
        elif ".v2-pending-" in lower:
            row.category = "V2 temporary generation file"
        elif "checkpoint-v2.sqlite" in lower or generation_match:
            row.category = ("active SQLite generation file" if
                            active_generation and generation_match and
                            generation_match.group(1) == active_generation
                            else "retained SQLite generation file")
        elif "libsqlite" in lower:
            row.category = "SQLite library"
        elif lower.startswith("/dev/shm") or "memfd:" in lower:
            row.category = "shared memory"
        elif "python" in lower and (lower.endswith("/python") or
                                     "libpython" in lower or
                                     lower.endswith(".so")):
            row.category = "Python executable or extension"
        elif path and not path.startswith("[") and (
                ".so" in lower or "/lib" in lower):
            row.category = "shared library"
        elif not path and row.permissions.endswith("s"):
            row.category = "anonymous shared mapping"
        elif _anonymous_private(row):
            row.category = ("allocator large-object mmap" if
                            row.virtual_bytes >= 128 * 1024 else
                            "anonymous private mapping")
        elif path.startswith("["):
            row.category = "anonymous private mapping"
        elif path:
            row.category = "shared library"
        else:
            row.category = "unknown"
    _mark_arena_pairs(records)


def normalized_path(path: str, category: str) -> str:
    if category in {"active SQLite generation file",
                    "retained SQLite generation file",
                    "V2 temporary generation file"}:
        return _GENERATION_RE.sub("v2-generation-<id>", path)
    if category in {"allocator arena", "allocator large-object mmap",
                    "anonymous private mapping", "anonymous shared mapping"}:
        return category
    return path


def redacted_path(path: str, category: str) -> str:
    """No host/private directory is emitted by the structured diagnostic."""
    if not path:
        return "<anonymous>"
    if path.startswith("["):
        return path
    if category in {"active SQLite generation file",
                    "retained SQLite generation file"}:
        return "<checkpoint-v2-generation>/checkpoint-v2.sqlite"
    if category == "V2 temporary generation file":
        return "<checkpoint-v2-pending>"
    if category == "legacy checkpoint or incident temp":
        return "<immutable-incident-evidence>"
    return f"<{category}>/{pathlib.PurePosixPath(path).name}"


def category_summary(records: Sequence[MappingRecord],
                     previous: Optional[Sequence[MappingRecord]] = None
                     ) -> Dict[str, Any]:
    previous = previous or ()
    output = {}
    for category in sorted({row.category for row in records} |
                           {row.category for row in previous}):
        selected = [row for row in records if row.category == category]
        old = [row for row in previous if row.category == category]
        new_counts = collections.Counter(row.fingerprint() for row in selected)
        old_counts = collections.Counter(row.fingerprint() for row in old)
        output[category] = {
            "mappingCount": len(selected),
            "virtualBytes": sum(row.virtual_bytes for row in selected),
            "rssBytes": sum(row.metrics.get("Rss", 0) for row in selected),
            "pssBytes": sum(row.metrics.get("Pss", 0) for row in selected),
            "anonymousResidentBytes": sum(
                row.metrics.get("Anonymous", 0) for row in selected),
            "newLogicalMappings": sum((new_counts - old_counts).values()),
            "removedLogicalMappings": sum((old_counts - new_counts).values()),
            "survivingFromEarlier": sum((new_counts & old_counts).values()),
        }
    all_new = collections.Counter(row.fingerprint() for row in records)
    all_old = collections.Counter(row.fingerprint() for row in previous)
    output["__total__"] = {
        "mappingCount": len(records),
        "virtualBytes": sum(row.virtual_bytes for row in records),
        "rssBytes": sum(row.metrics.get("Rss", 0) for row in records),
        "pssBytes": sum(row.metrics.get("Pss", 0) for row in records),
        "anonymousResidentBytes": sum(
            row.metrics.get("Anonymous", 0) for row in records),
        "newLogicalMappings": sum((all_new - all_old).values()),
        "removedLogicalMappings": sum((all_old - all_new).values()),
        "survivingFromEarlier": sum((all_new & all_old).values()),
    }
    return output


def snapshot_process_maps(artifact_root: pathlib.Path, tag: str, *,
                          previous: Optional[Sequence[MappingRecord]] = None,
                          active_generation: Optional[str] = None
                          ) -> Tuple[List[MappingRecord], Dict[str, Any]]:
    maps_text = pathlib.Path("/proc/self/maps").read_text()
    smaps_text = pathlib.Path("/proc/self/smaps").read_text()
    safe_tag = re.sub(r"[^A-Za-z0-9_.-]", "_", tag)
    artifact_root.mkdir(parents=True, exist_ok=True)
    # Raw kernel evidence is an access-controlled CI artifact, never public
    # endpoint telemetry. Structured JSON below contains only path classes.
    (artifact_root / f"{safe_tag}.maps").write_text(maps_text)
    (artifact_root / f"{safe_tag}.smaps").write_text(smaps_text)
    records = parse_smaps(smaps_text)
    classify_records(records, active_generation=active_generation)
    return records, {"tag": tag, "categories": category_summary(
        records, previous), "records": [row.diagnostic_record()
                                       for row in records]}


class Mallinfo2(ctypes.Structure):
    _fields_ = [(name, ctypes.c_size_t) for name in (
        "arena", "ordblks", "smblks", "hblks", "hblkhd", "usmblks",
        "fsmblks", "uordblks", "fordblks", "keepcost")]


def glibc_allocator_diagnostics() -> Dict[str, Any]:
    result = {"supported": False, "arenaCount": None, "systemBytes": None,
              "inUseBytes": None, "freeRetainedBytes": None,
              "mmapCount": None, "mmapBytes": None}
    if not sys.platform.startswith("linux"):
        return result
    libc = ctypes.CDLL(None)
    if not hasattr(libc, "mallinfo2"):
        return result
    libc.mallinfo2.restype = Mallinfo2
    info = libc.mallinfo2()
    result.update({"supported": True,
                   "systemBytes": int(info.arena + info.hblkhd),
                   "inUseBytes": int(info.uordblks + info.hblkhd),
                   "freeRetainedBytes": int(info.fordblks),
                   "mmapCount": int(info.hblks),
                   "mmapBytes": int(info.hblkhd)})
    if not hasattr(libc, "malloc_info"):
        return result
    import tempfile
    with tempfile.TemporaryFile(mode="w+b") as handle:
        duplicate = os.dup(handle.fileno())
        libc.fdopen.argtypes = [ctypes.c_int, ctypes.c_char_p]
        libc.fdopen.restype = ctypes.c_void_p
        stream = libc.fdopen(duplicate, b"w+")
        if not stream:
            os.close(duplicate)
            return result
        libc.malloc_info.argtypes = [ctypes.c_int, ctypes.c_void_p]
        libc.malloc_info.restype = ctypes.c_int
        libc.fflush.argtypes = [ctypes.c_void_p]
        libc.fclose.argtypes = [ctypes.c_void_p]
        status = libc.malloc_info(0, stream)
        libc.fflush(stream)
        libc.fclose(stream)
        if status:
            return result
        handle.seek(0)
        try:
            result["arenaCount"] = len(ET.fromstring(handle.read()).findall(
                "heap"))
        except ET.ParseError:
            pass
    return result


def gate_projection(summary: Mapping[str, Any]) -> Dict[str, Any]:
    categories = summary.get("categories") or {}
    count = lambda name: int((categories.get(name) or {}).get(
        "mappingCount") or 0)
    return {
        "activeGenerationFileMappings": count(
            "active SQLite generation file"),
        "retainedGenerationFileMappings": count(
            "retained SQLite generation file"),
        "v2TempMappings": count("V2 temporary generation file"),
        "deletedMappings": count("deleted file"),
        "incidentTempMappings": count(
            "legacy checkpoint or incident temp"),
        "unknownMappings": count("unknown"),
        "threadStackMappings": count("thread stack"),
        "sharedLibraryMappings": count("shared library"),
        "allocatorArenaMappings": count("allocator arena"),
        "allocatorLargeMmapMappings": count("allocator large-object mmap"),
        "allocatorAnonymousBytes": sum(int(
            (categories.get(name) or {}).get("anonymousResidentBytes") or 0)
            for name in ("heap", "allocator arena",
                         "allocator large-object mmap",
                         "anonymous private mapping")),
    }
