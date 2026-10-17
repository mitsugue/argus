#!/usr/bin/env python3
"""One-time LOCAL Gmail authorization for the ARGUS dedicated news mailbox.

Run this on your own machine (never in CI). It performs the installed-app
OAuth consent for the READ-ONLY Gmail scope and prints the refresh token to
YOUR terminal only — paste it into the Render environment yourself. Nothing
is written to disk, the repository, or any log.

Usage:
  python3 scripts/news_gmail_authorize.py --client-id <id> --client-secret <secret>

Then in the opened browser window, sign in as the DEDICATED news mailbox
account (not your personal account) and approve read-only access.
"""
from __future__ import annotations

import argparse
import http.server
import json
import secrets
import threading
import urllib.parse
import urllib.request
import webbrowser

SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
PORT = 8765


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--client-secret", required=True)
    args = parser.parse_args()

    state = secrets.token_urlsafe(16)
    redirect = f"http://127.0.0.1:{PORT}/callback"
    consent = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": args.client_id, "redirect_uri": redirect,
        "response_type": "code", "scope": SCOPE, "access_type": "offline",
        "prompt": "consent", "state": state,
    })

    received: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            query = urllib.parse.parse_qs(
                urllib.parse.urlsplit(self.path).query)
            if query.get("state", [""])[0] == state and query.get("code"):
                received["code"] = query["code"][0]
                body = b"ARGUS: authorization received. Close this tab."
            else:
                body = b"ARGUS: invalid callback."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print("Opening browser for consent (sign in as the DEDICATED news mailbox)…")
    webbrowser.open(consent)
    print(f"If the browser did not open, visit:\n{consent}\n")
    while "code" not in received:
        pass
    server.shutdown()

    data = urllib.parse.urlencode({
        "client_id": args.client_id, "client_secret": args.client_secret,
        "code": received["code"], "grant_type": "authorization_code",
        "redirect_uri": redirect,
    }).encode()
    with urllib.request.urlopen(urllib.request.Request(
            TOKEN_URL, data=data, method="POST")) as response:
        token = json.load(response)
    refresh = token.get("refresh_token")
    if not refresh:
        print("ERROR: no refresh_token returned. Remove the app's previous "
              "access at myaccount.google.com/permissions and rerun.")
        return 1
    print("\n=== COPY INTO RENDER ENVIRONMENT (never share elsewhere) ===")
    print(f"ARGUS_NEWS_GMAIL_REFRESH_TOKEN={refresh}")
    print("============================================================")
    print("Scope granted:", token.get("scope"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
