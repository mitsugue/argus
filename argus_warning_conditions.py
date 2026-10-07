"""Versioned, read-only warning conditions; legacy evidence stays unchanged."""
from collections.abc import Mapping
from copy import deepcopy
from math import isfinite

RULE_VERSION = "jp-warning-conditions-v2"
NAMES = ("信用売り残が少ない", "日経レバの制度信用倍率", "日本株の優位性低下",
         "推計EPSの下方修正", "海外投資家の売り越し", "VIXのMACDが上向き", "好決算でも株価下落")
RULES = {1: "二市場の信用売り残が8,000億円未満", 2: "1570の制度信用倍率が1倍以上",
         5: "最新の公表週で海外投資家が売り越し", 6: "VIXのMACD線がシグナル線より上（ARGUSの12・26・9）"}
UNDEFINED = {3: "低下を測る期間・基準が未確定", 4: "最新推計EPSの低下を測る期間・基準が未確定",
             7: "好決算・集計期間・最低件数の測定規則なし"}


def _number(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        return float(value) if isfinite(value) else None
    except (OverflowError, ValueError):
        return None


def _mapping(value):
    return value if isinstance(value, Mapping) else {}


def project_warning_conditions(evidence, *, cutoff, performance=None, adopted_rules=None):
    # Imported at the seam to avoid a module cycle. The admitted sealed input,
    # not compact legacy counts or retrospective event-study results, is used.
    from jp_market_engine import (_content_id_valid, _cutoff, _instant, fact_note_ja,
                                  CANONICAL_JP_MARKET_ENGINE_RFC_SHA256)
    limit = _cutoff(cutoff)
    admitted = (isinstance(evidence, Mapping) and evidence.get("informationCutoff") == cutoff
                and evidence.get("canonicalRfcSha256") == CANONICAL_JP_MARKET_ENGINE_RFC_SHA256
                and _content_id_valid(evidence, "jp-market-engine-evidence-"))
    families = _mapping(evidence.get("families")) if admitted else {}
    from argus_warning_candidates import admitted_results, RULE_VERSION as ADOPTED_VERSION
    adopted = admitted_results(adopted_rules, cutoff) if admitted else None
    output = []
    for n, name in enumerate(NAMES, 1):
        family = f"D{n:02}"
        source = _mapping(families.get(family))
        status = source.get("status")
        try:
            fact = (fact_note_ja(family, source) or "").replace("公表", "利用可能") or None
        except (OverflowError, ValueError, TypeError, AttributeError):
            fact = None
        row = {"id": f"WARN-{n:02}", "family": family, "ruleId": f"{RULE_VERSION}.{family}",
               "nameJa": name, "direction": "WARNING", "status": status, "state": "UNAVAILABLE",
               "conditionMet": None, "ruleStatus": "DEFINED", "lineage": "ORIGINAL_DIRECTION",
               "conditionRuleJa": RULES.get(n), "distance": None,
               "factNoteJa": fact, "valuationBasis": source.get("valuationBasis"),
               "performance": {"ruleId": f"{RULE_VERSION}.{family}", "status": "UNVALIDATED", "evaluated": 0},
               "probability": None, "actionAuthority": False}
        if n in UNDEFINED:
            row.update(ruleStatus="RULE_NOT_DEFINED", reasonJa=UNDEFINED[n], conditionRuleJa=UNDEFINED[n])
            if status == "AVAILABLE":
                row["state"] = "DATA_GATED"
        elif status == "AVAILABLE":
            value = None
            features = _mapping(source.get("features"))
            known = features.get("shortBalanceKnownAt") if n == 1 else source.get("knownAt") or source.get("availableFrom")
            period = features.get("shortBalancePeriodEnd") if n == 1 else source.get("periodEnd")
            if n == 1:
                value = _number(features.get("shortBalance"))
                threshold, operator, unit = 800_000_000_000, "<", "JPY"
                if value is not None and value < 0:
                    value = None
            elif n == 2:
                if source.get("ratioBasis") == "STANDARDIZED_MARGIN":
                    value = _number(source.get("marginRatio"))
                threshold, operator, unit = 1, ">=", "RATIO"
                if value is not None and value < 0:
                    value = None
            elif n == 5:
                value = _number(source.get("flowValue"))
                threshold, operator, unit = 0, "<", "JPY"
            else:
                row.update(lineage="ARGUS_CANDIDATE", parameterStatus="ORIGINAL_PARAMETERS_UNKNOWN")
                baseline, proof = _mapping(source.get("argusBaseline")), _mapping(source.get("pointInTimeProof"))
                sample = baseline.get("sampleCount")
                if (baseline.get("parameters") == {"fast": 12, "slow": 26, "signal": 9}
                        and type(sample) is int and sample >= 35
                        and baseline.get("uniqueSessionCount") == sample
                        and type(proof.get("includedCount")) is int and proof["includedCount"] >= sample):
                    value = _number(baseline.get("warningHistogram"))
                threshold, operator, unit = 0, ">", "MACD_GAP"
            instant = _instant(known) if isinstance(known, str) and "T" in known else None
            if value is None or instant is None or instant > limit:
                row.update(state="DATA_GATED", reasonJa="必要な値・定義・利用可能時刻・履歴を確認できません")
            else:
                met = value < threshold if operator == "<" else value > threshold if operator == ">" else value >= threshold
                row.update(state="ACTIVE" if met else "CLEAR", conditionMet=met, value=value,
                           threshold={"operator": operator, "value": threshold, "unit": unit},
                           distance={"signedFromBoundary": value-threshold, "unit": unit, "operator": operator,
                                     "atBoundary": value == threshold, "boundaryCounts": operator == ">="},
                           sourcePeriodEnd=period, knowledgeTime=known)
        if status in ("STALE", "LICENSE_BLOCKED", "NOT_APPLICABLE"):
            row["state"] = status
        elif status in ("PARTIAL", "UNVALIDATED", "DATA_GATED"):
            row["state"] = "DATA_GATED"
        if admitted and performance is not None:
            from argus_warning_history import performance_for
            result = performance_for(performance, family, cutoff)
            if result is not None:
                row["performance"] = deepcopy(result)
        if adopted and family in adopted:
            row.update(deepcopy(adopted[family]))
            # A new rule never inherits a legacy/support or v2 grade.
            row['performance']={'ruleId':row['ruleId'],'status':'UNVALIDATED','evaluated':0}
            from argus_warning_candidates_history import performance_for as adopted_performance_for
            study_result = adopted_performance_for(adopted_rules.get('performanceStudy'),family,cutoff)
            if study_result is not None: row['performance']=deepcopy(study_result)
        output.append(row)
    support = [{"family": family, "legacyRuleId": f"legacy-v1.{family}", "conditionMet": source.get("conditionMet"),
                "status": source.get("status"), "performanceReusedForWarning": False}
               for family in ("D03", "D05", "D06", "D07")
               if isinstance((source := families.get(family)), Mapping)]
    return {"schemaVersion": ADOPTED_VERSION if adopted else RULE_VERSION, "informationCutoff": cutoff,
            "adoptedRulesArtifactId": adopted_rules.get('artifactId') if adopted else None,
            "sourceArtifactId": evidence.get("artifactId") if admitted else None, "rejectedEvidence": not admitted,
            "signals": output, "activeCount": sum(row["state"] == "ACTIVE" for row in output),
            "measurableCount": sum(row["state"] in ("ACTIVE", "CLEAR") for row in output), "total": 7,
            "legacySupportEvidence": deepcopy(support), "countPredictsCrash": False, "validationStatus": "UNVALIDATED",
            "probability": None, "actionAuthority": False, "automaticAiCalls": 0}
