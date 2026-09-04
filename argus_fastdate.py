"""ARGUS v13.5.52 — lock-free ``strptime`` for hot paths.

``datetime.strptime`` routes every call through ``_strptime._strptime``, which
serialises the whole process on one module-level lock (``_cache_lock``).  On
the single-CPU Render runtime that lock became the production stall observed
on 2026-09-03/04: the Tachibana packet loop, the SHO row evaluation and the
public GET routes all parse timestamps, so a CPU-bound parser thread starved
every request that needed one more date parse (a public route with ~35 parses
took 65 s, a route with none stayed sub-second).

This module is a drop-in replacement for the directive subset ARGUS uses
(``%Y %m %d %H %M %S %f %z`` plus literal text).  It compiles one regular
expression per format (dict cache, no lock — dict updates are atomic under the
GIL) and builds the ``datetime`` directly, so the range validation and the
``ValueError`` contract match ``datetime.strptime``.  Any directive outside the
subset falls back to ``datetime.strptime`` unchanged, so behaviour never
diverges silently.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, Optional, Tuple

_DIRECTIVES: Dict[str, str] = {
    "Y": r"(?P<Y>\d{4})",
    "m": r"(?P<m>1[0-2]|0[1-9]|[1-9])",
    "d": r"(?P<d>3[01]|[12]\d|0[1-9]|[1-9]| [1-9])",
    "H": r"(?P<H>2[0-3]|[0-1]\d|\d)",
    "M": r"(?P<M>[0-5]\d|\d)",
    "S": r"(?P<S>6[0-1]|[0-5]\d|\d)",
    "f": r"(?P<f>[0-9]{1,6})",
    # The whole pattern compiles with IGNORECASE, so ``Z`` needs an explicit
    # case-sensitive group or a lowercase ``z`` would be accepted as UTC where
    # the stdlib raises — the one silent divergence a differential run against
    # datetime.strptime found (v13.5.53).
    "z": r"(?P<z>(?-i:Z)|[+-]\d{2}:?[0-5]\d(?::?[0-5]\d(?:\.\d{1,6})?)?)",
}

# format -> (compiled regex, None) or (None, None) when the format needs the
# stdlib path (a directive outside the supported subset, or a duplicate).
_CACHE: Dict[str, Optional["re.Pattern[str]"]] = {}
_STDLIB: Callable[[str, str], datetime] = datetime.strptime


def _compile(fmt: str) -> Optional["re.Pattern[str]"]:
    parts = []
    seen = set()
    i = 0
    while i < len(fmt):
        ch = fmt[i]
        if ch == "%":
            if i + 1 >= len(fmt):
                return None
            code = fmt[i + 1]
            i += 2
            if code == "%":
                parts.append(re.escape("%"))
                continue
            if code not in _DIRECTIVES or code in seen:
                return None
            seen.add(code)
            parts.append(_DIRECTIVES[code])
            continue
        if ch.isspace():
            parts.append(r"\s+")
            i += 1
            while i < len(fmt) and fmt[i].isspace():
                i += 1
            continue
        parts.append(re.escape(ch))
        i += 1
    return re.compile("".join(parts), re.IGNORECASE)


def _pattern(fmt: str) -> Optional["re.Pattern[str]"]:
    try:
        return _CACHE[fmt]
    except KeyError:
        pattern = _compile(fmt)
        if len(_CACHE) > 256:
            _CACHE.clear()
        _CACHE[fmt] = pattern
        return pattern


def _tz(text: str) -> timezone:
    if text.upper() == "Z":
        return timezone.utc
    sign = -1 if text[0] == "-" else 1
    body = text[1:].replace(":", "")
    hours = int(body[:2])
    minutes = int(body[2:4])
    seconds = 0
    micro = 0
    rest = body[4:]
    if rest:
        if "." in rest:
            sec_text, frac = rest.split(".", 1)
            seconds = int(sec_text or "0")
            micro = int(frac.ljust(6, "0")[:6])
        else:
            seconds = int(rest)
    delta = timedelta(hours=hours, minutes=minutes, seconds=seconds,
                      microseconds=micro)
    if delta > timedelta(hours=24) - timedelta(microseconds=1):
        raise ValueError("offset must be a timedelta strictly between "
                         "-timedelta(hours=24) and timedelta(hours=24)")
    return timezone(sign * delta)


def strptime(text: str, fmt: str) -> datetime:
    """Lock-free ``datetime.strptime`` for the ARGUS directive subset."""
    if not isinstance(text, str) or not isinstance(fmt, str):
        return _STDLIB(text, fmt)
    pattern = _pattern(fmt)
    if pattern is None:
        return _STDLIB(text, fmt)
    match = pattern.fullmatch(text)
    if match is None:
        # Same exception family and message shape as the stdlib parser.
        if pattern.match(text):
            raise ValueError(
                f"unconverted data remains: {text[pattern.match(text).end():]}")
        raise ValueError(f"time data {text!r} does not match format {fmt!r}")
    g = match.groupdict()
    micro = int(g["f"].ljust(6, "0")) if g.get("f") else 0
    tzinfo = _tz(g["z"]) if g.get("z") else None
    return datetime(
        int(g["Y"]) if g.get("Y") else 1900,
        int(g["m"]) if g.get("m") else 1,
        int(g["d"]) if g.get("d") else 1,
        int(g["H"]) if g.get("H") else 0,
        int(g["M"]) if g.get("M") else 0,
        int(g["S"]) if g.get("S") else 0,
        micro,
        tzinfo=tzinfo,
    )


def supported(fmt: str) -> bool:
    """True when ``fmt`` is served lock-free (diagnostics/tests only)."""
    return _pattern(fmt) is not None
