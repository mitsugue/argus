#!/usr/bin/env python3
"""Minimal one-symbol v4r10 read-only smoke test.

Output is intentionally limited to stable status/error classifications.  Secret
values, provider text, virtual URLs, response bodies, and raw market fields are
never printed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import warnings

# Running ``python scripts/...`` otherwise places only scripts/ on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore", module=r"urllib3(?:\..*)?")

from argus_providers.tachibana.client import TachibanaReadOnlyClient
from argus_providers.tachibana.config import TachibanaConfig
from argus_providers.tachibana.models import (
    ErrorClass,
    Freshness,
    MarketStatus,
    TachibanaError,
    TachibanaObservation,
)
from argus_providers.tachibana.normalization import normalize_market_price
from argus_providers.tachibana.session import TachibanaSession
from argus_providers.tachibana.session_truth import (
    JapanCashPhase,
    parse_provider_datetime,
    resolve_jp_cash_session,
)


def _observation_is_usable_and_fresh(
    observation: TachibanaObservation, *, now: datetime
) -> bool:
    current_price = observation.fields.get("current_price")
    return (
        isinstance(current_price, (int, float))
        and not isinstance(current_price, bool)
        and current_price > 0
        and observation.field_availability.get("current_price") is True
        and observation.source_timestamp is not None
        and observation.freshness == Freshness.FRESH
        and observation.market_status == MarketStatus.OPEN
        and observation.fresh_until is not None
        and observation.fresh_until >= now.astimezone(timezone.utc)
    )


def _smoke_pass_allowed(
    observation: TachibanaObservation, *, teardown: bool, now: datetime
) -> bool:
    return teardown and _observation_is_usable_and_fresh(observation, now=now)


def main() -> int:
    session: TachibanaSession | None = None
    normalized = None
    failure_class: str | None = None
    authenticated = False
    teardown = False
    try:
        config = TachibanaConfig.from_env()
        if not config.enabled:
            failure_class = ErrorClass.DISABLED.value
        else:
            session = TachibanaSession(config)
            session.authenticate()
            authenticated = True
            client = TachibanaReadOnlyClient(session)
            provider_calendar_date = client.provider_calendar_date()
            response = client.market_price(("6501",), (
                "pDPP", "tDPP:T", "pPRP", "pDOP", "pDHP", "pDLP", "pDV",
            ))
            rows = response.get("aCLMMfdsMarketPrice")
            if not isinstance(rows, list) or len(rows) != 1:
                raise TachibanaError(ErrorClass.PROVIDER)
            received_at = datetime.now(timezone.utc)
            provider_time = parse_provider_datetime(response.get("p_rv_date"))
            session_truth = resolve_jp_cash_session(
                now=received_at,
                provider_time=provider_time,
                provider_calendar_date=provider_calendar_date,
            )
            normalized = normalize_market_price(
                rows[0], received_at=received_at,
                market_date=session_truth.market_date,
                market_status=session_truth.market_status,
                market_date_verified=bool(
                    session_truth.market_date_verified
                    and session_truth.phase in {
                        JapanCashPhase.OPEN,
                        JapanCashPhase.AFTERNOON_OPEN,
                    }
                ),
                market_data_timestamp=provider_time,
                market_data_date_verified=bool(
                    session_truth.provider_calendar_current
                    and session_truth.event_packet_current
                ),
                fresh_for_seconds=config.fresh_for_seconds,
            )
    except TachibanaError as exc:
        failure_class = exc.classification.value
    except Exception:
        failure_class = "UNCLASSIFIED_SAFE_FAILURE"
    finally:
        # Teardown is deliberately centralized here so normalization failures
        # and unexpected safe failures cannot strand a credential-equivalent
        # virtual URL in the session object.
        if authenticated and session is not None:
            teardown = session.logout()

    if failure_class is not None:
        print(f"TACHIBANA_SMOKE=BLOCKED CLASS={failure_class}")
        return 2
    if normalized is None:
        print("TACHIBANA_SMOKE=BLOCKED CLASS=UNCLASSIFIED_SAFE_FAILURE")
        return 2
    if not _smoke_pass_allowed(
        normalized, teardown=teardown, now=datetime.now(timezone.utc)
    ):
        if not teardown:
            print("TACHIBANA_SMOKE=BLOCKED CLASS=TEARDOWN_FAILED")
            return 3
        print("TACHIBANA_SMOKE=BLOCKED CLASS=UNUSABLE_OR_STALE")
        return 2
    print(
        "TACHIBANA_SMOKE=PASS "
        "TIMESTAMP_PARSED=true LOGOUT=true SECRETS_EXPOSED=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
