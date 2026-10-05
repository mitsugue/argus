import pytest

from argus_public_feed_fetch import fetch_text, MAX_SECONDS


class Response:
    def __init__(self, status=200, chunks=(b"public text",), location=None):
        self.status_code = status
        self.headers = {} if location is None else {"Location": location}
        self.chunks = chunks
        self.closed = False

    def iter_content(self, size):
        yield from self.chunks

    def close(self):
        self.closed = True


def test_redirect_target_is_rejected_before_the_connection():
    calls = []
    first = Response(302, location="https://169.254.169.254/private")

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return first

    text, info = fetch_text("https://public.test/feed", get=get,
        safe_url=lambda url: url.startswith("https://public.test/"), max_bytes=100)
    assert text is None and info["errorClass"] == "destination_rejected"
    assert len(calls) == 1 and calls[0][1]["allow_redirects"] is False
    assert first.closed
    assert "169.254" not in str(info) and "private" not in str(info)


def test_relative_public_redirect_retains_the_original_text():
    replies = [Response(301, location="../current.xml"),
               Response(chunks=(b"<rss>", "株".encode(), b"</rss>"))]
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        return replies[len(calls)-1]

    text, info = fetch_text("https://public.test/news/old.xml", get=get,
        safe_url=lambda url: url.startswith("https://public.test/"), max_bytes=100)
    assert calls == ["https://public.test/news/old.xml", "https://public.test/current.xml"]
    assert text == "<rss>株</rss>" and info["httpStatus"] == 200 and info["errorClass"] is None
    assert all(r.closed for r in replies)


def test_a_redirect_loop_is_bounded_and_every_response_is_closed():
    replies = []

    def get(url, **kwargs):
        response = Response(302, location="/same")
        replies.append(response)
        return response

    text, info = fetch_text("https://public.test/same", get=get,
        safe_url=lambda url: True, max_bytes=100)
    assert text is None and info["errorClass"] == "redirect_limit_exceeded"
    assert len(replies) == 4 and all(r.closed for r in replies)


@pytest.mark.parametrize("response,reason", [
    (Response(403), "http_unavailable"),
    (Response(302), "redirect_location_missing"),
    (Response(chunks=()), "response_empty"),
    (Response(chunks=(b"<rss/>", b"over the limit")), "response_bound_exceeded"),
])
def test_rejected_reads_return_no_partial_text_and_close(response, reason):
    text, info = fetch_text("https://public.test/feed", get=lambda *a, **k: response,
                           safe_url=lambda url: True, max_bytes=7)
    assert text is None and info["errorClass"] == reason and response.closed
    assert set(info) == {"httpStatus", "errorClass", "elapsedSeconds"}


def test_slow_drip_cannot_keep_the_feed_accepted_past_the_deadline():
    tick = [0]
    response = Response()

    def stream(size):
        for _ in range(100):
            tick[0] += 10
            yield b"public chunk"

    response.iter_content = stream
    text, info = fetch_text("https://public.test/feed", get=lambda *a, **k: response,
        safe_url=lambda url: True, max_bytes=1000, clock=lambda: tick[0])
    assert text is None and info["errorClass"] == "deadline_exceeded"
    assert info["elapsedSeconds"] == 30 and response.closed


def test_redirect_chain_reuses_one_deadline_and_shrinks_request_timeouts():
    tick, timeouts, replies = [0], [], []

    def get(url, **kwargs):
        timeouts.append(kwargs["timeout"])
        tick[0] += 10
        response = Response(302, location="/next")
        replies.append(response)
        return response

    text, info = fetch_text("https://public.test/feed", get=get,
        safe_url=lambda url: True, max_bytes=100, clock=lambda: tick[0])
    assert text is None and info["errorClass"] == "deadline_exceeded"
    assert timeouts == [12, 12, MAX_SECONDS-20] and all(r.closed for r in replies)


def test_credentials_and_transport_errors_are_never_reflected():
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        raise RuntimeError("secret-cookie private response body")
    text, info = fetch_text("https://user:password@public.test/feed", get=get,
        safe_url=lambda url: True, max_bytes=100)
    assert text is None and not calls and info["errorClass"] == "destination_rejected"
    text, info = fetch_text("https://public.test/feed", get=get,
        safe_url=lambda url: True, max_bytes=100)
    assert text is None and info["errorClass"] == "transport_unavailable"
    assert "secret-cookie" not in str(info) and "private response" not in str(info)


def test_body_iteration_failure_also_closes_the_response():
    response = Response()
    def fail(size):
        yield b"first bytes"
        raise RuntimeError("private network detail")
    response.iter_content = fail
    text, info = fetch_text("https://public.test/feed", get=lambda *a, **k: response,
                           safe_url=lambda url: True, max_bytes=100)
    assert text is None and response.closed and info["errorClass"] == "transport_unavailable"
