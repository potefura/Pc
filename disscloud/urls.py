import json
from urllib.parse import quote, urlparse

from aiohttp import web

from . import config


def _scheme_from_request(request: web.Request) -> str | None:
    cf_visitor = request.headers.get("CF-Visitor", "")
    if cf_visitor:
        try:
            data = json.loads(cf_visitor)
            scheme = data.get("scheme")
            if scheme in ("http", "https"):
                return scheme
        except (json.JSONDecodeError, TypeError):
            pass
    proto = request.headers.get("X-Forwarded-Proto", "")
    if proto in ("http", "https"):
        return proto.split(",")[0].strip()
    return None


def _host_from_request(request: web.Request) -> str | None:
    for header in ("X-Forwarded-Host", "Host"):
        value = request.headers.get(header, "")
        if value:
            return value.split(",")[0].strip()
    return None


def public_base_url(request: web.Request | None = None) -> str:
    """Discord 用リンクは config.PUBLIC_URL。サイト内リンクはプロキシヘッダーも考慮。"""
    if config.PUBLIC_URL:
        return config.PUBLIC_URL.rstrip("/")

    if request and config.TRUST_PROXY:
        scheme = _scheme_from_request(request)
        host = _host_from_request(request)
        if scheme and host:
            return f"{scheme}://{host}".rstrip("/")

    if request:
        return str(request.url.with_path("")).rstrip("/")

    return f"http://localhost:{config.SITE_PORT}"


def bot_site_url(
    bot_id: str,
    slug: str,
    request: web.Request | None = None,
    *,
    base_url: str | None = None,
) -> str:
    """Return the canonical site URL; the slug is descriptive, not an identifier."""
    base = (base_url or public_base_url(request)).rstrip("/")
    return f"{base}/s/{quote(str(bot_id), safe='')}/{quote(str(slug), safe='')}/"


def is_cloudflare_request(request: web.Request) -> bool:
    return bool(request.headers.get("CF-Ray") or request.headers.get("CF-Connecting-IP"))


@web.middleware
async def proxy_middleware(request: web.Request, handler):
    if config.TRUST_PROXY:
        scheme = _scheme_from_request(request)
        host = _host_from_request(request)
        if scheme and host:
            request["public_base"] = f"{scheme}://{host}".rstrip("/")
    return await handler(request)


def request_public_base(request: web.Request) -> str:
    cached = request.get("public_base")
    if cached:
        return str(cached).rstrip("/")
    return public_base_url(request)
