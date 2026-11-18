import scanner

ORIGIN = "https://mitsugue.github.io"


def _preflight(client, path, headers="x-argus-owner-session", origin=ORIGIN):
    return client.open(path, method="OPTIONS", headers={
        "Origin": origin,
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": headers,
    })


def test_owner_read_preflight_is_cacheable_for_the_pages_origin():
    response = _preflight(scanner.app.test_client(), "/api/argus/watchlist")
    assert response.headers["Access-Control-Allow-Origin"] == ORIGIN
    assert response.headers["Access-Control-Max-Age"] == "600"
    assert scanner.CORS_PREFLIGHT_MAX_AGE_SECONDS == 600


def test_owner_session_preflight_is_cacheable_and_keeps_its_narrow_allow_list():
    response = _preflight(scanner.app.test_client(), "/api/argus/owner-auth/session",
                          headers="x-argus-owner-session, x-argus-owner-nonce")
    assert response.headers["Access-Control-Allow-Origin"] == ORIGIN
    assert response.headers["Access-Control-Max-Age"] == "600"
    assert "x-argus-owner-nonce" in response.headers["Access-Control-Allow-Headers"].lower()


def test_foreign_origin_and_server_only_route_get_no_cached_allow():
    client = scanner.app.test_client()
    foreign = _preflight(client, "/api/argus/watchlist", origin="https://evil.example")
    assert "Access-Control-Allow-Origin" not in foreign.headers
    assert "Access-Control-Max-Age" not in foreign.headers
    diag = _preflight(client, "/api/argus/admin/diagnostics/operational")
    assert "Access-Control-Allow-Origin" not in diag.headers
    assert "Access-Control-Max-Age" not in diag.headers
