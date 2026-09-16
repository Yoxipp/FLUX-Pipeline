# api_auth.py — protect the local API from web pages (security, S1).
#
# The backend listens on 127.0.0.1, but any web page open in a browser can still send
# requests to it (and CORS allows Origin "null", which sandboxed iframes also use).
# Routes like /dcc/execute run Python inside the DCCs, so browser requests must prove
# they come from the FLUX window.
#
# Rule:
#   * request carries X-Flux-Token == API_TOKEN            -> allowed (FLUX renderer;
#     the Electron main process injects the header on every request to the backend)
#   * request has neither Origin nor Sec-Fetch-Site         -> allowed (not a browser:
#     DCC plugins, scripts, tests; browsers always send one of them)
#   * otherwise                                             -> 403
# /health and CORS preflights stay open. GET /auth/token hands the token to
# non-browser callers only (the Electron main process fetches it with Node http).

from __future__ import annotations

import hmac
import json
import os
import secrets

TOKEN_HEADER = "x-flux-token"
TOKEN_PATH = "/auth/token"

# Fresh per backend process unless forced by the environment.
API_TOKEN: str = os.environ.get("FLUX_API_TOKEN") or secrets.token_urlsafe(32)

_OPEN_PATHS = {"/health"}


def _headers(scope: dict) -> dict[str, str]:
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}


def is_browser_request(headers: dict[str, str]) -> bool:
    """True when a browser sent the request (it always adds Origin or Sec-Fetch-Site)."""
    return bool(headers.get("origin") or headers.get("sec-fetch-site"))


def has_valid_token(headers: dict[str, str]) -> bool:
    return hmac.compare_digest(headers.get(TOKEN_HEADER, ""), API_TOKEN)


def is_allowed(scope: dict) -> bool:
    headers = _headers(scope)
    path = scope.get("path", "")
    if scope["type"] == "http" and scope.get("method") == "OPTIONS":
        return True
    if path in _OPEN_PATHS:
        return True
    if path == TOKEN_PATH:
        return not is_browser_request(headers)
    return has_valid_token(headers) or not is_browser_request(headers)


class ApiAuthMiddleware:
    """Pure ASGI middleware so it guards WebSockets as well as HTTP."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket") or is_allowed(scope):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4403})
            return
        body = json.dumps({"detail": "Forbidden: FLUX API token required"}).encode()
        await send({
            "type": "http.response.start",
            "status": 403,
            "headers": [(b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode())],
        })
        await send({"type": "http.response.body", "body": body})
