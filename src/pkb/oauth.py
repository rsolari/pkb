from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import httpx

from .config import Settings


AUTH_URL = "https://x.com/i/oauth2/authorize"
TOKEN_URL = "https://api.x.com/2/oauth2/token"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def make_pkce_pair() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def build_authorization_url(settings: Settings, code_challenge: str, state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": settings.client_id,
        "redirect_uri": settings.redirect_uri,
        "scope": " ".join(settings.scopes),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


class _CallbackHandler(BaseHTTPRequestHandler):
    server: "_CallbackServer"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        self.server.callback_params = {key: values[0] for key, values in params.items() if values}
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            b"<html><body><h1>Authorization received</h1><p>You can return to the terminal.</p></body></html>"
        )


class _CallbackServer(HTTPServer):
    callback_params: dict[str, str] | None = None


def _callback_host_port(redirect_uri: str) -> tuple[str, int]:
    parsed = urllib.parse.urlparse(redirect_uri)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return host, port


def exchange_code(settings: Settings, code: str, verifier: str) -> dict[str, Any]:
    data = {
        "grant_type": "authorization_code",
        "client_id": settings.client_id,
        "redirect_uri": settings.redirect_uri,
        "code": code,
        "code_verifier": verifier,
    }
    auth = (settings.client_id, settings.client_secret) if settings.client_secret else None
    with httpx.Client(timeout=30) as client:
        response = client.post(
            TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            auth=auth,
        )
        response.raise_for_status()
        token = response.json()
    token["obtained_at"] = int(time.time())
    return token


def refresh_token(settings: Settings, refresh: str) -> dict[str, Any]:
    data = {
        "grant_type": "refresh_token",
        "client_id": settings.client_id,
        "refresh_token": refresh,
    }
    auth = (settings.client_id, settings.client_secret) if settings.client_secret else None
    with httpx.Client(timeout=30) as client:
        response = client.post(
            TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            auth=auth,
        )
        response.raise_for_status()
        token = response.json()
    token["obtained_at"] = int(time.time())
    return token


def save_token(path: Path, token: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(token, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)


def load_token(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def token_is_expired(token: dict[str, Any], skew_seconds: int = 120) -> bool:
    expires_in = int(token.get("expires_in", 0) or 0)
    obtained_at = int(token.get("obtained_at", 0) or 0)
    if not expires_in or not obtained_at:
        return False
    return time.time() >= obtained_at + expires_in - skew_seconds


def authenticate(settings: Settings, open_browser: bool = True) -> dict[str, Any]:
    if not settings.client_id:
        raise ValueError("Set X_CLIENT_ID in .env or the environment before running auth.")
    verifier, challenge = make_pkce_pair()
    state = secrets.token_urlsafe(24)
    auth_url = build_authorization_url(settings, challenge, state)
    host, port = _callback_host_port(settings.redirect_uri)
    server = _CallbackServer((host, port), _CallbackHandler)
    print(f"Open this URL to authorize:\n{auth_url}\n", flush=True)
    if open_browser:
        webbrowser.open(auth_url)
    print(f"Waiting for callback on {settings.redirect_uri} ...", flush=True)
    while server.callback_params is None:
        server.handle_request()
    params = server.callback_params
    if params.get("state") != state:
        raise RuntimeError("OAuth state mismatch.")
    if "error" in params:
        raise RuntimeError(f"OAuth error: {params['error']}")
    code = params.get("code")
    if not code:
        raise RuntimeError("OAuth callback did not include a code.")
    token = exchange_code(settings, code, verifier)
    save_token(settings.token_path, token)
    return token


def get_valid_token(settings: Settings) -> dict[str, Any]:
    token = load_token(settings.token_path)
    if token_is_expired(token) and token.get("refresh_token"):
        refreshed = refresh_token(settings, token["refresh_token"])
        if "refresh_token" not in refreshed:
            refreshed["refresh_token"] = token["refresh_token"]
        save_token(settings.token_path, refreshed)
        return refreshed
    return token
