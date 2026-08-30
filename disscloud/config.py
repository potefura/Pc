import os
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MAX_BOTS_PER_USER = int(os.getenv("MAX_BOTS_PER_USER", "5"))
MAX_UPLOAD_MB = 15
MAX_ZIP_ENTRIES = 400
MAX_UNZIPPED_BYTES = 80 * 1024 * 1024
LOG_BUFFER_SIZE = 250
INSTALL_TIMEOUT_SEC = int(os.getenv("INSTALL_TIMEOUT_SEC", "180"))
RUNTIME_INSTALL_TIMEOUT_SEC = int(os.getenv("RUNTIME_INSTALL_TIMEOUT_SEC", "900"))

# ローカルで待ち受けるアドレス（Cloudflare Tunnel でもここは localhost:8080 のまま）
SITE_HOST = os.getenv("SITE_HOST", "0.0.0.0")
SITE_PORT = int(os.getenv("SITE_PORT", "8080"))

# Cloudflare 経由でユーザーに見せる公開 URL（Discord やサイトリンクで使う）
# 例: https://cloud.example.com  /  https://xxx.trycloudflare.com
CLOUDFLARE_ENABLED = os.getenv("CLOUDFLARE_ENABLED", "false").lower() in ("1", "true", "yes", "on")
CLOUDFLARE_TUNNEL = os.getenv("CLOUDFLARE_TUNNEL", "false").lower() in ("1", "true", "yes", "on")
CLOUDFLARE_DOMAIN = os.getenv("CLOUDFLARE_DOMAIN", "").strip().rstrip("/")

# PUBLIC_URL が未設定なら CLOUDFLARE_DOMAIN を使う。どちらもなければ localhost
_raw_public = os.getenv("PUBLIC_URL", "").strip() or CLOUDFLARE_DOMAIN
if _raw_public:
    PUBLIC_URL = _raw_public.rstrip("/")
elif CLOUDFLARE_ENABLED or CLOUDFLARE_TUNNEL:
    PUBLIC_URL = ""
else:
    PUBLIC_URL = f"http://localhost:{SITE_PORT}"

# Cloudflare プロキシ / Tunnel 経由の X-Forwarded-* ヘッダーを信頼する
_default_trust = "true" if (CLOUDFLARE_ENABLED or CLOUDFLARE_TUNNEL) else "false"
TRUST_PROXY = os.getenv("TRUST_PROXY", _default_trust).lower() in ("1", "true", "yes", "on")

# Discord OAuth2（サイトログイン）
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "").strip()
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "").strip()
SESSION_SECRET = os.getenv("SESSION_SECRET", "").strip()
OAUTH_REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI", "").strip().rstrip("/")

COLORS = {
    "blurple": 0x5865F2,
    "green": 0x57F287,
    "red": 0xED4245,
    "yellow": 0xFEE75C,
    "gray": 0x99AAB5,
}


def site_settings_summary() -> dict[str, str]:
    """現在のサイト公開設定を辞書で返す。"""
    return {
        "公開URL": PUBLIC_URL or "(未設定 — CLOUDFLARE_DOMAIN または PUBLIC_URL を .env に設定)",
        "ローカル待受": f"{SITE_HOST}:{SITE_PORT}",
        "Cloudflare": "有効" if CLOUDFLARE_ENABLED else "無効",
        "Cloudflare Tunnel": "有効" if CLOUDFLARE_TUNNEL else "無効",
        "プロキシ信頼": "有効" if TRUST_PROXY else "無効",
        "Cloudflareドメイン": CLOUDFLARE_DOMAIN or "(未設定)",
        "Discordログイン": "有効" if (DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET and SESSION_SECRET) else "無効",
    }


def display_public_url() -> str:
    """Discord 表示用の公開 URL（未設定時は localhost）。"""
    return PUBLIC_URL or f"http://localhost:{SITE_PORT}"


def validate_site_config() -> list[str]:
    """起動時の設定警告。"""
    warnings: list[str] = []
    if CLOUDFLARE_ENABLED or CLOUDFLARE_TUNNEL:
        if not PUBLIC_URL:
            warnings.append("CLOUDFLARE が有効ですが PUBLIC_URL / CLOUDFLARE_DOMAIN が未設定です")
        elif PUBLIC_URL.startswith("http://") and not PUBLIC_URL.startswith("http://localhost"):
            warnings.append("Cloudflare 公開 URL は https:// を推奨します（PUBLIC_URL を確認）")
    parsed = urlparse(PUBLIC_URL) if PUBLIC_URL else None
    if parsed and parsed.netloc and "localhost" in parsed.netloc and (CLOUDFLARE_ENABLED or CLOUDFLARE_TUNNEL):
        warnings.append("Cloudflare 利用時は PUBLIC_URL を本番ドメイン（https://...）に設定してください")
    if DISCORD_CLIENT_ID and not DISCORD_CLIENT_SECRET:
        warnings.append("DISCORD_CLIENT_ID は設定されていますが CLIENT_SECRET がありません")
    if (DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET) and not SESSION_SECRET:
        warnings.append("サイトログインには SESSION_SECRET の設定が必要です")
    return warnings
