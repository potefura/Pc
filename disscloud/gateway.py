import asyncio
import html
import mimetypes
from pathlib import Path

from aiohttp import web

from . import config, store
from .auth import (
    build_login_url,
    clear_session_cookie,
    exchange_code,
    get_session_user,
    oauth_enabled,
    set_session_cookie,
    sync_user_from_discord,
)
from .cloud import Cloud, extract_zip_safe
from .resources import dir_size, format_bytes, rss_of
from .urls import bot_site_url, proxy_middleware, request_public_base
from .web_ui import dashboard_page, landing_page, login_required_page, oauth_error_page

PUBLIC_DIRS = ("public", "site", "www", "web")

MIME_OVERRIDES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
}


def public_roots(bot_id: str, owner_id: str) -> list[Path]:
    base = store.bot_dir(bot_id, owner_id)
    return [base / name for name in PUBLIC_DIRS if (base / name).is_dir()]


def safe_join(root: Path, rel: str) -> Path | None:
    target = (root / rel).resolve()
    root_resolved = root.resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError:
        return None
    return target


SENSITIVE_NAMES = {".env", "cloud.log"}
SENSITIVE_RE = re.compile(r"(?:token|secret|authorization|password)\s*[:=]", re.IGNORECASE)


def bot_file_path(root: Path, rel: str, *, allow_root: bool = False) -> Path | None:
    """Resolve an API path without permitting absolute paths or symlink escapes."""
    if not isinstance(rel, str) or "\x00" in rel or Path(rel).is_absolute() or PureWindowsPath(rel).is_absolute():
        return None
    normalized = rel.replace("\\", "/")
    if any(part in ("", ".", "..") for part in normalized.split("/")):
        if not (allow_root and normalized in ("", ".")):
            return None
    target = safe_join(root, normalized)
    if target is None or (not allow_root and target == root.resolve()):
        return None
    return target


def is_sensitive_path(path: Path) -> bool:
    name = path.name.lower()
    return name in SENSITIVE_NAMES or "token" in name


def contains_sensitive_value(path: Path) -> bool:
    """Conservatively keep credential-looking text out of API responses."""
    try:
        if path.stat().st_size > config.MAX_UPLOAD_MB * 1024 * 1024:
            return False
        return bool(SENSITIVE_RE.search(path.read_text(encoding="utf-8")))
    except (UnicodeDecodeError, OSError):
        return False


def escape_html(text: str) -> str:
    return html.escape(str(text))


def status_html(bot: dict, disk: str, mem: str, site_url: str) -> str:
    running = bot["status"] == "running"
    state = "BOT 稼働中" if running else "BOT 停止中"
    css_class = "ok" if running else "off"
    return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape_html(bot["name"])}</title>
<style>
body{{font-family:ui-sans-serif,system-ui;background:#0f1115;color:#e8eaed;margin:0;display:grid;place-items:center;min-height:100vh}}
.box{{background:#1a1d24;border:1px solid #2c313a;border-radius:16px;padding:32px;max-width:520px}}
.ok{{color:#57f287}}.off{{color:#9aa0a6}}
code{{background:#0f1115;padding:2px 6px;border-radius:6px}}
a{{color:#5865f2}}
</style></head>
<body><div class="box">
<h1>{escape_html(bot["name"])}</h1>
<p class="{css_class}">{state}</p>
<p>ランタイム <code>{escape_html(str(bot.get("runtime") or "python"))}</code><br>
ストレージ使用 <code>{disk}</code><br>
メモリ使用 <code>{mem}</code></p>
<p>URL: <a href="{escape_html(site_url)}">{escape_html(site_url)}</a></p>
<p style="color:#9aa0a6;font-size:13px"><code>public/</code> に HTML を置くと、このページの代わりに公開されます。</p>
</div></body></html>"""


def try_static(bot_id: str, owner_id: str, url_path: str) -> Path | None:
    rel = url_path.lstrip("/") or "index.html"
    roots = public_roots(bot_id, owner_id)
    base = store.bot_dir(bot_id, owner_id)
    candidates: list[Path] = []

    for root in roots:
        candidates.append(safe_join(root, rel))
        if "." not in rel:
            candidates.append(safe_join(root, f"{rel}/index.html"))

    if not roots:
        candidates.append(safe_join(base, rel))
        if rel in ("index.html", ""):
            candidates.append(base / "index.html")

    for file_path in candidates:
        if file_path and file_path.is_file():
            return file_path
    return None


class Gateway:
    def __init__(self, cloud: Cloud) -> None:
        self.cloud = cloud
        self.runner: web.AppRunner | None = None

    def create_app(self) -> web.Application:
        app = web.Application(middlewares=[proxy_middleware])
        app["oauth_states"] = {}

        app.router.add_get("/", self.handle_root)
        app.router.add_get("/dashboard", self.handle_dashboard)
        app.router.add_get("/auth/login", self.handle_auth_login)
        app.router.add_get("/auth/callback", self.handle_auth_callback)
        app.router.add_get("/auth/logout", self.handle_auth_logout)
        app.router.add_get("/api/me", self.handle_api_me)
        # Canonical ID routes must precede the overlapping legacy name route.
        app.router.add_get("/s/{bot_id}/{slug}", self.handle_site)
        app.router.add_get("/s/{bot_id}/{slug}/", self.handle_site)
        app.router.add_get("/s/{bot_id}/{slug}/{path:.*}", self.handle_site_path)
        app.router.add_get("/s/{name}", self.handle_legacy_site)
        app.router.add_get("/s/{name}/", self.handle_legacy_site)
        return app

    async def start(self) -> None:
        app = self.create_app()
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, config.SITE_HOST, config.SITE_PORT)
        await site.start()

        public = config.PUBLIC_URL or f"http://localhost:{config.SITE_PORT}"
        mode = []
        if config.CLOUDFLARE_TUNNEL:
            mode.append("Tunnel")
        elif config.CLOUDFLARE_ENABLED:
            mode.append("Proxy")
        mode_text = f" [{', '.join(mode)}]" if mode else ""
        print(f"サイトゲートウェイ: ローカル {config.SITE_HOST}:{config.SITE_PORT}")
        print(f"公開 URL{mode_text}: {public}  （各BOTは {public}/s/<BOT ID>/<名前>/ ）")
        if oauth_enabled():
            from .auth import oauth_redirect_uri

            print(f"Discord ログイン: {oauth_redirect_uri()}")
        for warning in config.validate_site_config():
            print(f"⚠️  {warning}")

    async def stop(self) -> None:
        if self.runner:
            await self.runner.cleanup()

    async def handle_root(self, request: web.Request) -> web.Response:
        base = request_public_base(request)
        user = get_session_user(request)
        return web.Response(
            text=landing_page(self.cloud, base, user),
            content_type="text/html; charset=utf-8",
        )

    async def handle_dashboard(self, request: web.Request) -> web.Response:
        user = get_session_user(request)
        if not user:
            return web.Response(text=login_required_page(), content_type="text/html; charset=utf-8", status=401)
        profile = sync_user_from_discord(user)
        return web.Response(
            text=dashboard_page(user, self.cloud, profile),
            content_type="text/html; charset=utf-8",
        )

    async def handle_auth_login(self, request: web.Request) -> web.Response:
        if not oauth_enabled():
            return web.Response(
                text=oauth_error_page("Discord ログインが設定されていません"),
                content_type="text/html; charset=utf-8",
                status=503,
            )
        url = build_login_url(request)
        raise web.HTTPFound(url)

    async def handle_auth_callback(self, request: web.Request) -> web.Response:
        if not oauth_enabled():
            return web.Response(text=oauth_error_page("OAuth 未設定"), content_type="text/html; charset=utf-8", status=503)

        error = request.query.get("error")
        if error:
            return web.Response(
                text=oauth_error_page(f"Discord: {error}"),
                content_type="text/html; charset=utf-8",
                status=400,
            )

        code = request.query.get("code")
        state = request.query.get("state", "")
        if not code or not state:
            return web.Response(text=oauth_error_page("認証コードがありません"), content_type="text/html; charset=utf-8", status=400)

        from .auth import valid_oauth_state

        if not valid_oauth_state(request.app, state):
            return web.Response(text=oauth_error_page("無効な state です"), content_type="text/html; charset=utf-8", status=400)

        try:
            discord_user = await exchange_code(request, code)
        except web.HTTPBadRequest as err:
            return web.Response(text=oauth_error_page(str(err.text or err)), content_type="text/html; charset=utf-8", status=400)

        profile = sync_user_from_discord(discord_user)
        session_user = {
            "id": discord_user["id"],
            "username": discord_user.get("username", ""),
            "global_name": profile.get("global_name") or discord_user.get("global_name"),
            "avatar": discord_user.get("avatar"),
        }
        response = web.HTTPFound("/dashboard")
        set_session_cookie(response, session_user)
        return response

    async def handle_auth_logout(self, _request: web.Request) -> web.Response:
        response = web.HTTPFound("/")
        clear_session_cookie(response)
        return response

    async def handle_api_me(self, request: web.Request) -> web.Response:
        user = get_session_user(request)
        if not user:
            return web.json_response({"authenticated": False}, status=401)
        profile = store.load_user_profile(str(user["id"])) or {}
        bots = self.cloud.list(str(user["id"]))
        return web.json_response(
            {
                "authenticated": True,
                "user": user,
                "profile": profile,
                "bots": [
                    {
                        "id": b["id"],
                        "name": b["name"],
                        "status": b["status"],
                        "site": bot_site_url(b["id"], b["name"], request),
                    }
                    for b in bots
                ],
            }
        )

    def _find_bot(self, bot_id: str) -> dict | None:
        bot = self.cloud.get(bot_id)
        return bot if bot and bot["id"] == bot_id else None

    async def handle_site(self, request: web.Request) -> web.Response:
        return await self._serve_bot(request, request.match_info["bot_id"], "index.html")

    async def handle_site_path(self, request: web.Request) -> web.Response:
        path = request.match_info.get("path", "") or "index.html"
        return await self._serve_bot(request, request.match_info["bot_id"], path)

    async def handle_legacy_site(self, request: web.Request) -> web.Response:
        name = request.match_info["name"]
        matches = [bot for bot in self.cloud.list() if bot["name"].lower() == name.lower()]
        if len(matches) != 1:
            return web.Response(text="site not found", status=404, content_type="text/plain", charset="utf-8")
        bot = matches[0]
        raise web.HTTPFound(bot_site_url(bot["id"], bot["name"], request))

    async def _serve_bot(self, request: web.Request, bot_id: str, path: str) -> web.Response:
        bot = self._find_bot(bot_id)
        if not bot:
            return web.Response(text="site not found", status=404, content_type="text/plain", charset="utf-8")

        static_file = try_static(bot["id"], bot["ownerId"], path)
        if static_file:
            ext = static_file.suffix.lower()
            content_type = MIME_OVERRIDES.get(ext) or mimetypes.guess_type(str(static_file))[0] or "application/octet-stream"
            return web.FileResponse(
                static_file,
                headers={"Cache-Control": "no-store", "Content-Type": content_type},
            )

        disk = format_bytes(dir_size(store.bot_dir(bot["id"], bot["ownerId"])))
        mem = format_bytes(rss_of(bot.get("pid")))
        site_url = bot_site_url(bot["id"], bot["name"], request)
        return web.Response(
            text=status_html(bot, disk, mem, site_url),
            content_type="text/html",
            charset="utf-8",
        )
