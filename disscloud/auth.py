import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import aiohttp
from aiohttp import web

from . import config, store

DISCORD_API = "https://discord.com/api"
DISCORD_AUTH_URL = "https://discord.com/api/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
OAUTH_SCOPES = "identify"
SESSION_COOKIE = "soucloud_session"
STATE_COOKIE = "soucloud_oauth_state"
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 days


def _sign(payload: str) -> str:
    return hmac.new(config.SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()


def _encode(data: dict[str, Any]) -> str:
    raw = base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode()).decode()
    return f"{raw}.{_sign(raw)}"


def _decode(token: str) -> dict[str, Any] | None:
    if not token or "." not in token:
        return None
    raw, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(_sign(raw), sig):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(raw.encode()))
    except (json.JSONDecodeError, ValueError):
        return None
    expires = data.get("exp", 0)
    if expires and time.time() > expires:
        return None
    return data


def oauth_redirect_uri(request: web.Request | None = None) -> str:
    if config.OAUTH_REDIRECT_URI:
        return config.OAUTH_REDIRECT_URI.rstrip("/")
    from .urls import public_base_url

    return f"{public_base_url(request)}/auth/callback"


def oauth_enabled() -> bool:
    return bool(config.DISCORD_CLIENT_ID and config.DISCORD_CLIENT_SECRET and config.SESSION_SECRET)


def get_session_user(request: web.Request) -> dict[str, Any] | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    data = _decode(token)
    if not data or "id" not in data:
        return None
    return data


def set_session_cookie(response: web.Response, user: dict[str, Any]) -> None:
    payload = {
        "id": str(user["id"]),
        "username": user.get("username", ""),
        "global_name": user.get("global_name") or user.get("username", ""),
        "avatar": user.get("avatar"),
        "exp": int(time.time()) + SESSION_MAX_AGE,
    }
    response.set_cookie(
        SESSION_COOKIE,
        _encode(payload),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="Lax",
        secure=config.PUBLIC_URL.startswith("https://") if config.PUBLIC_URL else False,
    )


def clear_session_cookie(response: web.Response) -> None:
    response.del_cookie(SESSION_COOKIE, path="/")


def build_login_url(request: web.Request) -> str:
    state = secrets.token_urlsafe(24)
    params = {
        "client_id": config.DISCORD_CLIENT_ID,
        "redirect_uri": oauth_redirect_uri(request),
        "response_type": "code",
        "scope": OAUTH_SCOPES,
        "state": state,
        "prompt": "none",
    }
    request.app["oauth_states"] = getattr(request.app, "oauth_states", {})
    request.app["oauth_states"][state] = time.time()
    url = f"{DISCORD_AUTH_URL}?{urlencode(params)}"
    return url


def valid_oauth_state(app: web.Application, state: str) -> bool:
    states: dict[str, float] = app.get("oauth_states", {})
    created = states.pop(state, None)
    if created is None:
        return False
    return time.time() - created < 600


async def exchange_code(request: web.Request, code: str) -> dict[str, Any]:
    redirect = oauth_redirect_uri(request)
    data = {
        "client_id": config.DISCORD_CLIENT_ID,
        "client_secret": config.DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    async with aiohttp.ClientSession() as session:
        async with session.post(DISCORD_TOKEN_URL, data=data, headers=headers) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise web.HTTPBadRequest(text=f"トークン取得失敗: {text[:200]}")
            token_data = await resp.json()
        access_token = token_data["access_token"]
        async with session.get(
            f"{DISCORD_API}/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
        ) as resp:
            if resp.status != 200:
                raise web.HTTPBadRequest(text="ユーザー情報の取得に失敗しました")
            return await resp.json()


def sync_user_from_discord(user: dict[str, Any]) -> dict[str, Any]:
    """Discord ログイン時に users/<id>/ を同期する。"""
    profile = store.sync_discord_profile(user)
    return profile


def avatar_url(user: dict[str, Any], size: int = 64) -> str:
    uid = user.get("id", "")
    avatar = user.get("avatar")
    if avatar:
        return f"https://cdn.discordapp.com/avatars/{uid}/{avatar}.png?size={size}"
    default = int(uid) % 5 if uid.isdigit() else 0
    return f"https://cdn.discordapp.com/embed/avatars/{default}.png"
