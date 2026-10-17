#!/usr/bin/env python3
"""Counts-only AI usage report for a public workflow log (owner request 2026-10-16).

Reads the owner-only `/api/argus/ai-cost` document saved by the workflow and
prints calls, correction calls, rejection reasons and tokens per UTC day.
Every field whose name refers to money is removed before anything is printed;
the repository and its logs are public.
"""
import json
import math
import re
import sys

MONEY = re.compile(r"usd|cost|price|budget|spent|remaining|reserve|invoice|amount", re.IGNORECASE)
REDUCTION_RELEASED_ON = "2026-10-11"   # 13.8.91: dates rendered by the engine


def strip_money(value):
    """Remove every key that names money, at any depth."""
    if isinstance(value, dict):
        return {k: strip_money(v) for k, v in value.items() if not MONEY.search(str(k))}
    if isinstance(value, list):
        return [strip_money(v) for v in value]
    return value


def _ratio(numerator, denominator):
    return round(numerator / denominator, 3) if denominator else None


def report(document):
    clean = strip_money(document)
    lines = ["## AI 使用量（回数・トークンのみ。金額は出さない）", ""]
    groups = ((clean.get("featureUsage") or {}).get("summary") or {}).get("groups") or []
    by_day = {}
    for group in groups:
        row = by_day.setdefault(group.get("dayUtc"), {})
        feature = str(group.get("feature"))
        cell = row.setdefault(feature, {"calls": 0, "inputTokens": 0, "outputTokens": 0, "cachedInputTokens": 0})
        cell["calls"] += int(group.get("providerCalls") or 0)
        for key in ("inputTokens", "outputTokens", "cachedInputTokens"):
            cell[key] += int(group.get(key) or 0)
    lines += ["### 用途ごとの呼び出し回数（UTC 日）", "", "| 日 | 用途 | 呼び出し | 入力トークン | 出力トークン | 使い回し入力 |", "|---|---|---|---|---|---|"]
    for day in sorted(d for d in by_day if d):
        for feature, cell in sorted(by_day[day].items(), key=lambda kv: -kv[1]["calls"]):
            lines.append(f"| {day} | {feature} | {cell['calls']} | {cell['inputTokens']} | {cell['outputTokens']} | {cell['cachedInputTokens']} |")
    brief = clean.get("briefCallReport") or {}
    days = brief.get("days") or []
    lines += ["", "### 統合AIの見立て（保存された版のみ）", "",
              "| 日 | 版 | AI あり | 修正あり | 呼び出し | 修正の呼び出し | 修正の割合 | 1版あたり入力 | 1版あたり出力 | 最初の却下理由 |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for row in days:
        with_ai = row.get("viewsWithAi") or 0
        reasons = ", ".join(f"{k}:{v}" for k, v in sorted((row.get("firstRejectionReasons") or {}).items(), key=lambda kv: -kv[1])[:3])
        lines.append(f"| {row.get('dayUtc')} | {row.get('views')} | {with_ai} | {row.get('viewsWithCorrection')} | "
                     f"{row.get('aiCalls')} | {row.get('correctionCalls')} | {_ratio(row.get('viewsWithCorrection') or 0, with_ai)} | "
                     f"{_ratio(row.get('inputTokens') or 0, with_ai)} | {_ratio(row.get('outputTokens') or 0, with_ai)} | {reasons} |")
    labels = {"SCHEDULED": "定時", "EVENT": "発表直後", "NO_PREVIOUS": "保存版なし", "NOT_RECORDED": "記録前"}
    lines += ["", "### 作り直しの理由と結論の変化（保存された版のみ）", "",
              "| 日 | 版 | 結論が変わった版 | 理由 | 変わった材料 |", "|---|---|---|---|---|"]
    for row in days:
        triggers = ", ".join(f"{labels.get(k, k)}:{v}" for k, v in sorted((row.get("triggers") or {}).items(), key=lambda kv: -kv[1]))
        groups = ", ".join(f"{k}:{v}" for k, v in sorted((row.get("changedFactGroups") or {}).items(), key=lambda kv: -kv[1])[:4])
        lines.append(f"| {row.get('dayUtc')} | {row.get('views')} | {row.get('conclusionChanged', 0)} | {triggers} | {groups} |")
    for label, chosen in (("13.8.91 より前", [r for r in days if r.get("dayUtc", "") < REDUCTION_RELEASED_ON]),
                          ("13.8.91 以降", [r for r in days if r.get("dayUtc", "") >= REDUCTION_RELEASED_ON])):
        with_ai = sum(r.get("viewsWithAi") or 0 for r in chosen)
        lines += ["", f"- {label}：{len(chosen)}日・AI あり {with_ai} 版・修正ありの割合 "
                  f"{_ratio(sum(r.get('viewsWithCorrection') or 0 for r in chosen), with_ai)}・"
                  f"1版あたり呼び出し {_ratio(sum(r.get('aiCalls') or 0 for r in chosen), with_ai)}・"
                  f"1版あたり入力 {_ratio(sum(r.get('inputTokens') or 0 for r in chosen), with_ai)}・"
                  f"1版あたり出力 {_ratio(sum(r.get('outputTokens') or 0 for r in chosen), with_ai)}"]
    lines += ["", f"- 見立ての集計の読み取り：{brief.get('readStatus')}（保存されなかった失敗の生成は含まない）",
              f"- 使用記録の読み取り：{(clean.get('featureUsage') or {}).get('readStatus')}"]
    text = "\n".join(lines) + "\n"
    leaked = money_leaks(document, text)
    if leaked:
        # The check reads the text that would be printed, not the filtered
        # document: a money value reaching the output by any path stops here.
        raise SystemExit(f"money_value_in_report:{leaked}")
    return text


def _money_values(value, inside=False):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _money_values(child, inside or bool(MONEY.search(str(key))))
    elif isinstance(value, list):
        for child in value:
            yield from _money_values(child, inside)
    elif inside and isinstance(value, float) and math.isfinite(value) and value != int(value):
        yield value


def money_leaks(document, text):
    """Count of money signs or money values (decimals under a money field) in the text."""
    lowered = text.lower()
    signs = sum(lowered.count(sign) for sign in ("$", "usd", "ドル", "円"))
    values = {f"{v:.6f}".rstrip("0") for v in _money_values(document)} | {repr(v) for v in _money_values(document)}
    return signs + sum(1 for v in values if len(v) >= 4 and v in text)


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    with open(argv[0], encoding="utf-8") as handle:
        document = json.load(handle)
    sys.stdout.write(report(document))


if __name__ == "__main__":
    main()
