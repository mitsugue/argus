"""ARGUS v13.5.3 — dedicated news-mailbox intake (Gmail REST, read-only).

Minimum-access model: a DEDICATED news mailbox, OAuth refresh-token with the
read-only scope, no send/modify/delete capability requested — ever. All
transport is injected so every failure mode is testable without credentials.

Reliability model (§5, §7):
  PRIMARY   incremental users.history.list from a durably persisted historyId
  FALLBACK  bounded reconciliation (recent message ids) whenever the history
            cursor cannot be trusted (404 historyExpired, first run, restart
            with no cursor, or repeated API errors)
Duplicate notifications, duplicate emails, process restarts and Gmail history
gaps must never lose or double-process a message: processing is keyed by
immutable Gmail message ids recorded in a bounded seen-set.

Copyright boundary (§10): bodies are read transiently for classification only
(bounded excerpt); the module returns headline/provenance/excerpt to the
caller and never persists raw mail.
"""
from __future__ import annotations

import base64
import json
import re
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://gmail.googleapis.com/gmail/v1/users/me"

INTAKE_STATES = (
    "MAILBOX_UNCONFIGURED", "OAUTH_EXPIRED", "RECONCILIATION_FAILED",
    "AUTHENTICATION_FAILED", "DEGRADED", "HEALTHY",
)
MAX_EXCERPT_CHARS = 1800          # transient classification input only
MAX_SEEN_IDS = 2000               # bounded dedup memory
RECONCILE_WINDOW = "newer_than:2d"
MAX_RECONCILE_MESSAGES = 60


class IntakeAuthError(Exception):
    """OAuth refresh failed — surfaced as OAUTH_EXPIRED, never retried hot."""


def is_configured(env: Mapping[str, str]) -> bool:
    return all(env.get(key) for key in (
        "ARGUS_NEWS_GMAIL_CLIENT_ID", "ARGUS_NEWS_GMAIL_CLIENT_SECRET",
        "ARGUS_NEWS_GMAIL_REFRESH_TOKEN"))


def refresh_access_token(env: Mapping[str, str],
                         http: Callable[..., Any]) -> str:
    """Exchange the long-lived refresh token for a short-lived access token.
    Raises IntakeAuthError on a definitive auth failure (revoked/expired)."""
    response = http("POST", TOKEN_URL, data={
        "client_id": env["ARGUS_NEWS_GMAIL_CLIENT_ID"],
        "client_secret": env["ARGUS_NEWS_GMAIL_CLIENT_SECRET"],
        "refresh_token": env["ARGUS_NEWS_GMAIL_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }, timeout=20)
    if response.status_code in (400, 401):
        raise IntakeAuthError(f"token_refresh_{response.status_code}")
    response.raise_for_status()
    token = (response.json() or {}).get("access_token")
    if not token:
        raise IntakeAuthError("token_refresh_empty")
    return str(token)


# ── Sender authentication (§9) ──────────────────────────────────────────────

def _header(headers: Sequence[Mapping[str, str]], name: str) -> str:
    for row in headers or []:
        if str(row.get("name", "")).lower() == name.lower():
            return str(row.get("value") or "")
    return ""


def _domain_of(address_line: str) -> str:
    match = re.search(r"[\w.+-]+@([\w.-]+)", address_line or "")
    return match.group(1).lower() if match else ""


def authenticate_sender(headers: Sequence[Mapping[str, str]],
                        allowed_domains: Sequence[str]) -> Dict[str, Any]:
    """Strict source validation: the From domain must be owner-approved AND
    the receiving Gmail's Authentication-Results must show SPF or DKIM pass
    aligned with that domain. Anything else → QUARANTINE (never Major News).
    """
    from_domain = _domain_of(_header(headers, "From"))
    return_path_domain = _domain_of(_header(headers, "Return-Path"))
    auth_results = _header(headers, "Authentication-Results").lower()
    allowed = {domain.strip().lower() for domain in allowed_domains
               if domain and domain.strip()}
    reasons: List[str] = []
    if not allowed:
        reasons.append("no_allowed_domains_configured")
    domain_ok = from_domain and any(
        from_domain == d or from_domain.endswith("." + d) for d in allowed)
    if not domain_ok:
        reasons.append(f"from_domain_not_allowed:{from_domain or 'missing'}")
    spf_pass = "spf=pass" in auth_results
    dkim_pass = bool(re.search(r"dkim=pass", auth_results))
    dmarc_pass = "dmarc=pass" in auth_results
    if not (spf_pass or dkim_pass):
        reasons.append("no_spf_or_dkim_pass")
    # Official subscriptions ride shared mailing platforms
    # (GovDelivery/Granicus): the bounce Return-Path is the platform's, not
    # the agency's. A DKIM or DMARC pass on the real header chain is the
    # authority there — never a naive Return-Path string equality (§9).
    if return_path_domain and domain_ok and not (
            any(return_path_domain.endswith(d) for d in allowed)
            or dmarc_pass or dkim_pass):
        reasons.append(f"return_path_mismatch:{return_path_domain}")
    return {
        "authenticated": not reasons,
        "fromDomain": from_domain,
        "spf": spf_pass, "dkim": dkim_pass, "dmarc": dmarc_pass,
        "quarantineReasons": reasons,
    }


# ── Message normalization ───────────────────────────────────────────────────

def _decode_part(data: str) -> str:
    try:
        return base64.urlsafe_b64decode(data + "==").decode(
            "utf-8", "replace")
    except Exception:
        return ""


def _plain_excerpt(payload: Mapping[str, Any]) -> str:
    """Bounded text excerpt for classification — transient, never persisted."""
    stack = [payload]
    texts: List[str] = []
    while stack and sum(len(t) for t in texts) < MAX_EXCERPT_CHARS:
        part = stack.pop(0)
        mime = str(part.get("mimeType") or "")
        body = part.get("body") or {}
        if mime.startswith("text/plain") and body.get("data"):
            texts.append(_decode_part(body["data"]))
        elif mime.startswith("text/html") and body.get("data") and not texts:
            html = _decode_part(body["data"])
            texts.append(re.sub(r"<[^>]+>", " ", html))
        for child in part.get("parts") or []:
            stack.append(child)
    joined = re.sub(r"\s+", " ", " ".join(texts)).strip()
    return joined[:MAX_EXCERPT_CHARS]


_URL_RE = re.compile(r"https?://[\w./%#?=&+~-]+")


def normalize_message(raw: Mapping[str, Any]) -> Dict[str, Any]:
    payload = raw.get("payload") or {}
    headers = payload.get("headers") or []
    subject = _header(headers, "Subject")
    date_header = _header(headers, "Date")
    from_line = _header(headers, "From")
    internal_ms = raw.get("internalDate")
    received_epoch = (int(internal_ms) / 1000.0
                      if str(internal_ms or "").isdigit() else None)
    excerpt = _plain_excerpt(payload)
    url_match = _URL_RE.search(excerpt or "")
    link_domains: List[str] = []
    for url in _URL_RE.findall(excerpt or "")[:20]:
        host = re.sub(r"^https?://([^/]+).*$", r"\1", url).lower()
        if host and host not in link_domains:
            link_domains.append(host)
    return {
        "messageId": str(raw.get("id") or ""),
        "rfcMessageId": _header(headers, "Message-ID"),
        "subject": subject,
        "dateHeader": date_header,
        "fromDomain": _domain_of(from_line),
        "fromDisplay": re.sub(r"<[^>]*>", "", from_line).strip()[:80],
        "linkDomains": link_domains[:8],
        "receivedEpoch": received_epoch,
        "excerpt": excerpt,
        "url": url_match.group(0) if url_match else None,
        "headers": [{"name": h.get("name"), "value": h.get("value")}
                    for h in headers
                    if str(h.get("name", "")).lower() in (
                        "from", "return-path", "authentication-results",
                        "message-id", "date", "subject")],
    }


# ── Incremental intake ──────────────────────────────────────────────────────

def list_history_message_ids(access_token: str, start_history_id: str,
                             http: Callable[..., Any]) -> Dict[str, Any]:
    """users.history.list from the durable cursor. status:
    ok(ids,newHistoryId) | gap (cursor expired → reconcile) | error."""
    added: List[str] = []
    page_token = None
    new_history_id = start_history_id
    for _ in range(10):  # bounded pagination
        params = {"startHistoryId": start_history_id,
                  "historyTypes": "messageAdded", "maxResults": 100}
        if page_token:
            params["pageToken"] = page_token
        response = http("GET", f"{API}/history", params=params,
                        headers={"Authorization": f"Bearer {access_token}"},
                        timeout=20)
        if response.status_code == 404:
            return {"status": "gap"}
        if response.status_code == 401:
            return {"status": "auth_error"}
        if response.status_code != 200:
            return {"status": "error", "httpStatus": response.status_code}
        body = response.json() or {}
        for entry in body.get("history") or []:
            for row in entry.get("messagesAdded") or []:
                message_id = str((row.get("message") or {}).get("id") or "")
                if message_id and message_id not in added:
                    added.append(message_id)
        new_history_id = str(body.get("historyId") or new_history_id)
        page_token = body.get("nextPageToken")
        if not page_token:
            break
    return {"status": "ok", "messageIds": added,
            "newHistoryId": new_history_id}


def reconcile_message_ids(access_token: str,
                          http: Callable[..., Any],
                          window: str = RECONCILE_WINDOW,
                          max_messages: int = MAX_RECONCILE_MESSAGES,
                          ) -> Dict[str, Any]:
    """Bounded fallback: recent message ids by query — used on first run,
    history gaps, or repeated errors. Never downloads the whole mailbox.
    A larger window/count is used for owner-triggered BACKFILL (bounded to
    14 days / 150 messages by the caller contract)."""
    response = http("GET", f"{API}/messages",
                    params={"q": window,
                            "maxResults": min(int(max_messages), 150)},
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=20)
    if response.status_code == 401:
        return {"status": "auth_error"}
    if response.status_code != 200:
        return {"status": "error", "httpStatus": response.status_code}
    body = response.json() or {}
    ids = [str(row.get("id")) for row in body.get("messages") or []
           if row.get("id")]
    return {"status": "ok", "messageIds": ids}


def fetch_message(access_token: str, message_id: str,
                  http: Callable[..., Any]) -> Optional[Dict[str, Any]]:
    response = http("GET", f"{API}/messages/{message_id}",
                    params={"format": "full"},
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=25)
    if response.status_code != 200:
        return None
    return normalize_message(response.json() or {})


def current_history_id(access_token: str,
                       http: Callable[..., Any]) -> Optional[str]:
    response = http("GET", f"{API}/profile",
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=15)
    if response.status_code != 200:
        return None
    return str((response.json() or {}).get("historyId") or "") or None


def prune_seen(seen_ids: List[str]) -> List[str]:
    return seen_ids[-MAX_SEEN_IDS:]


def run_intake_cycle(*, env: Mapping[str, str], state: Mapping[str, Any],
                     http: Callable[..., Any],
                     now_epoch: float,
                     reconcile_window: str = RECONCILE_WINDOW,
                     max_messages: int = MAX_RECONCILE_MESSAGES,
                     ) -> Dict[str, Any]:
    """One reliable intake cycle. Returns new state + freshly normalized
    messages. Pure orchestration: durability of the returned state is the
    caller's job. Never raises for transport errors — every failure is a
    visible state (§27)."""
    result: Dict[str, Any] = {
        "messages": [], "state": dict(state), "cycleAt": now_epoch,
    }
    if not is_configured(env):
        result["status"] = "MAILBOX_UNCONFIGURED"
        return result
    try:
        token = refresh_access_token(env, http)
    except IntakeAuthError as exc:
        result["status"] = "OAUTH_EXPIRED"
        result["errorClass"] = str(exc)
        return result
    except Exception as exc:  # transient transport problems
        result["status"] = "DEGRADED"
        result["errorClass"] = type(exc).__name__
        return result

    seen: List[str] = list(state.get("seenMessageIds") or [])
    cursor = str(state.get("historyId") or "")
    new_ids: List[str] = []
    mode = "incremental"
    if cursor:
        listing = list_history_message_ids(token, cursor, http)
        if listing["status"] == "ok":
            new_ids = listing["messageIds"]
            result["state"]["historyId"] = listing["newHistoryId"]
        elif listing["status"] == "gap":
            mode = "reconcile"
        elif listing["status"] == "auth_error":
            result["status"] = "OAUTH_EXPIRED"
            return result
        else:
            result["status"] = "DEGRADED"
            result["errorClass"] = f"history_http_{listing.get('httpStatus')}"
            return result
    else:
        mode = "reconcile"

    if mode == "reconcile":
        listing = reconcile_message_ids(
            token, http, window=reconcile_window, max_messages=max_messages)
        if listing["status"] == "auth_error":
            result["status"] = "OAUTH_EXPIRED"
            return result
        if listing["status"] != "ok":
            result["status"] = "RECONCILIATION_FAILED"
            result["errorClass"] = f"list_http_{listing.get('httpStatus')}"
            return result
        new_ids = listing["messageIds"]
        fresh_cursor = current_history_id(token, http)
        if fresh_cursor:
            result["state"]["historyId"] = fresh_cursor

    fetched = 0
    for message_id in new_ids:
        if message_id in seen:
            continue  # duplicate notification / duplicate email
        message = fetch_message(token, message_id, http)
        seen.append(message_id)
        if message is None:
            continue
        result["messages"].append(message)
        fetched += 1
        if fetched >= min(int(max_messages), 150):
            break
    result["state"]["seenMessageIds"] = prune_seen(seen)
    result["state"]["lastSyncEpoch"] = now_epoch
    result["mode"] = mode
    result["status"] = "HEALTHY"
    return result
