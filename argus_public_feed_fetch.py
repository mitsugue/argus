"""Bounded public-text reads; redirects are checked before any next request.

No response body, URL, header, exception message or credential enters diagnostics.
The existing collector alone owns persistence, parsing and provider selection.
"""
from urllib.parse import urljoin, urlsplit
import time

REDIRECT_CODES = frozenset((301, 302, 303, 307, 308))
MAX_REDIRECTS = 3
MAX_SECONDS = 24


def fetch_text(url, *, get, safe_url, max_bytes, clock=time.monotonic):
    start = clock()
    deadline = start + MAX_SECONDS
    status = None

    def result(text=None, reason=None):
        return text, {"httpStatus": status, "errorClass": reason,
                      "elapsedSeconds": round(max(0, clock() - start), 3)}

    try:
        current = url
        for hop in range(MAX_REDIRECTS + 1):
            # Verify each destination before issuing the request; following an
            # automatic redirect and checking the final URL is too late.
            parsed = urlsplit(current)
            if parsed.username is not None or parsed.password is not None or not safe_url(current):
                return result(reason="destination_rejected")
            remaining = deadline - clock()
            if remaining <= 0:
                return result(reason="deadline_exceeded")
            response = get(current, timeout=min(12, remaining), allow_redirects=False,
                           headers={"User-Agent": "argus-research/1.0"}, stream=True)
            try:
                status = response.status_code
                if clock() >= deadline:
                    return result(reason="deadline_exceeded")
                if status in REDIRECT_CODES:
                    location = response.headers.get("Location")
                    if not isinstance(location, str) or not location.strip():
                        return result(reason="redirect_location_missing")
                    if hop == MAX_REDIRECTS:
                        return result(reason="redirect_limit_exceeded")
                    current = urljoin(current, location)
                    continue
                if status != 200:
                    return result(reason="http_unavailable")
                chunks, total = [], 0
                for chunk in response.iter_content(16384):
                    if clock() >= deadline:
                        return result(reason="deadline_exceeded")
                    total += len(chunk)
                    if total > max_bytes:
                        # A truncated feed is not a valid acquisition.
                        return result(reason="response_bound_exceeded")
                    chunks.append(chunk)
                if not total:
                    return result(reason="response_empty")
                return result(b"".join(chunks).decode("utf-8", "replace"))
            finally:
                response.close()
    except Exception:
        # Exception text can contain an address, provider body or headers.
        return result(reason="transport_unavailable")
    return result(reason="redirect_limit_exceeded")
