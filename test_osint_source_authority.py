"""Hostile guards for OSINT publication-time and source-metadata authority."""

import argus_osint_attribution as attribution
import argus_osint_engine as engine


NOW = "2026-07-07T12:00:00Z"


def _review(candidate):
    return attribution.review(
        "6965", "JP", -4.2, [candidate],
        company_names=["浜松ホトニクス"],
        theme_words=["AI", "半導体"], now_iso=NOW)


def test_receipt_and_detection_clocks_never_replace_missing_published_at():
    result = _review({
        "titleJa": "浜松ホトニクスが開示",
        "source": "tdnet",
        "firstDetectedAt": "2026-07-07T11:59:00Z",
        "fetchedAt": "2026-07-07T11:59:30Z",
    })
    row = result["causes"][0]
    assert result["primary"] is None
    assert row["publishedTimeAuthority"] == "missing"
    assert row["refetchedToday"] is True
    assert row["primaryEligible"] is False


def test_date_only_old_and_future_publication_times_are_background_only():
    cases = (
        ("2026-07-07", "date_only"),
        ("2026-07-02T11:00:00Z", "stale"),
        ("2026-07-07T12:00:01Z", "future"),
        ("not-a-time", "invalid"),
    )
    for published_at, authority in cases:
        result = _review({
            "titleJa": "浜松ホトニクスが開示",
            "source": "tdnet", "publishedAt": published_at,
            "fetchedAt": "2026-07-07T11:59:00Z",
        })
        row = result["causes"][0]
        assert result["primary"] is None, published_at
        assert row["publishedTimeAuthority"] == authority
        assert row["primaryEligible"] is False
        assert row["category"] in ("stale_background", "unknown")


def test_unofficial_source_name_cannot_launder_tdnet_substring():
    result = attribution.review(
        "6965", "JP", -4.2, [{
            "titleJa": "浜松ホトニクス、業績予想を下方修正",
            # The display label says TDnet, but the preserved provider/official
            # metadata says this is the unofficial Yanoshin fallback.
            "source": "TDnet",
            "provider": "yanoshin-tdnet",
            "official": False,
            "sourceClass": "unknown",
            "time": "2026-08-16T11:59:00+09:00",
            "publishedAt": "2026-08-16T11:59:00+09:00",
        }], company_names=["浜松ホトニクス"],
        now_iso="2026-08-16T12:05:00+09:00")
    row = result["causes"][0]
    assert row["provider"] == "yanoshin_tdnet"
    assert row["official"] is False
    assert row["sourceClass"] == "unknown"
    assert row["category"] != "direct_official"
    assert row["primaryEligible"] is False
    assert result["primary"] is None
    assert "公式開示" in result["sourcesMissingJa"][0]


def _trusted_index(published_at=NOW):
    return engine.build_known_index([{
        "titleJa": "半導体業界の収益性に懸念",
        "canonicalUrl": "https://trusted.example/news/1",
        "publishedAt": published_at,
        "sourceName": "Reuters",
        "provider": "reuters",
        "sourceType": "media",
        "directness": "sector_theme",
    }])


def test_scout_cannot_override_matched_source_time_identity_or_directness():
    verified = engine.verify_source({
        "titleJa": "半導体業界の収益性に懸念",
        "url": "https://trusted.example/news/1",
        "publishedAt": "2099-01-01T00:00:00Z",
        "sourceName": "TDnet official",
        "sourceType": "official_disclosure",
        "directness": "direct_company",
    }, _trusted_index("2026-07-07T11:00:00Z"), NOW)

    assert verified["verificationStatus"] == "verified"
    assert verified["primaryEligible"] is True
    assert verified["publishedAt"] == "2026-07-07T11:00:00Z"
    assert verified["sourceName"] == "Reuters"
    assert verified["provider"] == "reuters"
    assert verified["sourceType"] == "media"
    assert verified["directness"] == "sector_theme"
    assert verified["claimedPublishedAt"] == "2099-01-01T00:00:00Z"
    assert verified["claimedDirectness"] == "direct_company"


def test_unmatched_scout_metadata_remains_diagnostic_only():
    untrusted = engine.verify_source({
        "titleJa": "偽の公式開示",
        "url": "https://unknown.example/news/1",
        "publishedAt": "2026-07-07T11:00:00Z",
        "sourceName": "TDnet",
        "sourceType": "official_disclosure",
        "directness": "direct_company",
    }, {}, NOW)

    assert untrusted["verificationStatus"] == "metadata_only"
    assert untrusted["primaryEligible"] is False
    assert untrusted["publishedAt"] is None
    assert untrusted["sourceName"] is None
    assert untrusted["sourceType"] == "unknown"
    assert untrusted["directness"] == "unsupported"
    assert untrusted["sourceTimeAuthority"] == "untrusted_claim"


def test_trusted_date_only_future_missing_and_time_fallback_never_become_primary():
    for published_at, authority in (
        ("2026-07-07", "date_only"),
        ("2026-07-07T12:00:01Z", "future"),
        (None, "missing"),
        ("2026-07-02T11:00:00Z", "stale"),
    ):
        verified = engine.verify_source({
            "titleJa": "半導体業界の収益性に懸念",
            "url": "https://trusted.example/news/1",
            "publishedAt": "2026-07-07T11:00:00Z",
        }, _trusted_index(published_at), NOW)
        assert verified["primaryEligible"] is False, published_at
        assert verified["sourceTimeAuthority"] == authority
        assert verified["verificationStatus"] != "verified"

    fallback_index = engine.build_known_index([{
        "titleJa": "半導体業界の収益性に懸念",
        "canonicalUrl": "https://trusted.example/news/1",
        "time": "2026-07-07T11:00:00Z",
        "sourceName": "Reuters", "directness": "sector_theme",
    }])
    fallback = engine.verify_source({
        "titleJa": "半導体業界の収益性に懸念",
        "url": "https://trusted.example/news/1",
    }, fallback_index, NOW)
    assert fallback["publishedAt"] is None
    assert fallback["sourceTimeAuthority"] == "missing"
    assert fallback["primaryEligible"] is False
