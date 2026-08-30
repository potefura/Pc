import html
from typing import Any

from . import config
from .auth import avatar_url, oauth_enabled
from .cloud import Cloud
from .resources import dir_size, format_bytes
from .store import user_dir
from .urls import bot_site_url


def _base_style() -> str:
    return """
:root { color-scheme: dark; }
body { font-family: ui-sans-serif, system-ui; background: #0f1115; color: #e8eaed; margin: 0; }
a { color: #5865f2; text-decoration: none; }
a:hover { text-decoration: underline; }
header { display: flex; align-items: center; justify-content: space-between; padding: 16px 24px; border-bottom: 1px solid #2c313a; }
main { max-width: 920px; margin: 32px auto; padding: 0 20px 48px; }
.card { background: #1a1d24; border: 1px solid #2c313a; border-radius: 12px; padding: 20px; }
.grid { display: grid; gap: 12px; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); }
.btn { display: inline-flex; align-items: center; gap: 8px; background: #5865f2; color: white; border: none; border-radius: 8px; padding: 10px 16px; font-weight: 600; cursor: pointer; text-decoration: none; }
.btn:hover { background: #4752c4; text-decoration: none; }
.btn.secondary { background: #2c313a; }
.muted { color: #9aa0a6; }
.ok { color: #57f287; }
.off { color: #9aa0a6; }
.user { display: flex; align-items: center; gap: 10px; }
.user img { width: 36px; height: 36px; border-radius: 50%; }
"""


def _layout(title: str, body: str, header_extra: str = "") -> str:
    return f"""<!DOCTYPE html>
<html lang="ja"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} · そーCloud</title>
<style>{_base_style()}</style>
</head><body>
<header>
  <a href="/"><strong>そーCloud</strong></a>
  <div>{header_extra}</div>
</header>
<main>{body}</main>
</body></html>"""


def landing_page(cloud: Cloud, public_base: str, user: dict[str, Any] | None) -> str:
    if user:
        header = f"""<div class="user">
          <img src="{html.escape(avatar_url(user))}" alt="">
          <span>{html.escape(user.get('global_name') or user.get('username', ''))}</span>
          <a class="btn secondary" href="/dashboard">ダッシュボード</a>
          <a class="btn secondary" href="/auth/logout">ログアウト</a>
        </div>"""
        intro = "<p class='muted'>ログイン済み — Discord と同期されています。</p>"
    elif oauth_enabled():
        header = '<a class="btn" href="/auth/login">Discord でログイン</a>'
        intro = "<p class='muted'>Discord でログインすると、BOT・ファイルが同期されます。</p>"
    else:
        header = '<span class="muted">ログイン未設定</span>'
        intro = "<p class='muted'>.env に DISCORD_CLIENT_ID / CLIENT_SECRET / SESSION_SECRET を設定してください。</p>"

    bots = cloud.list(user["id"] if user else None) if user else cloud.list()
    cards = []
    for bot in bots:
        href = bot_site_url(bot["id"], bot["name"], base_url=public_base)
        status = "稼働中" if bot["status"] == "running" else "停止"
        cards.append(
            f'<a class="card" href="{html.escape(href)}"><strong>{html.escape(bot["name"])}</strong>'
            f'<span class="muted">{status} · {html.escape(str(bot.get("runtime") or "python"))}</span></a>'
        )
    grid = "".join(cards) if cards else "<p class='muted'>まだサイトがありません</p>"
    body = f"""
<h1>そーCloud</h1>
{intro}
<div class="grid" style="margin-top:24px">{grid}</div>
"""
    return _layout("ホーム", body, header)


def dashboard_page(user: dict[str, Any], cloud: Cloud, profile: dict[str, Any]) -> str:
    owner_id = str(user["id"])
    bots = cloud.list(owner_id)
    path = user_dir(owner_id)
    disk = format_bytes(dir_size(path))
    running = sum(1 for b in bots if b["status"] == "running")
    synced = profile.get("last_sync_at")
    synced_text = f"<code>{synced}</code>" if synced else "—"

    bot_rows = []
    for bot in bots:
        site = bot_site_url(bot["id"], bot["name"])
        status_cls = "ok" if bot["status"] == "running" else "off"
        status = "稼働中" if bot["status"] == "running" else "停止"
        bot_rows.append(
            f"<tr>"
            f"<td><strong>{html.escape(bot['name'])}</strong></td>"
            f"<td class='{status_cls}'>{status}</td>"
            f"<td><code>{html.escape(str(bot.get('runtime') or 'python'))}</code></td>"
            f"<td><code>{html.escape(bot['entry'])}</code></td>"
            f"<td><a href='{html.escape(site)}'>サイト</a></td>"
            f"</tr>"
        )
    table = (
        "<table style='width:100%;border-collapse:collapse'>"
        "<tr><th align='left'>BOT</th><th align='left'>状態</th><th align='left'>言語</th><th align='left'>エントリ</th><th align='left'>リンク</th></tr>"
        + "".join(bot_rows)
        + "</table>"
        if bot_rows
        else "<p class='muted'>まだ BOT がありません。Discord で <code>/cloud create</code> を実行してください。</p>"
    )

    header = f"""<div class="user">
      <img src="{html.escape(avatar_url(user))}" alt="">
      <span>{html.escape(user.get('global_name') or user.get('username', ''))}</span>
      <a class="btn secondary" href="/auth/logout">ログアウト</a>
    </div>"""

    body = f"""
<h1>ダッシュボード</h1>
<p class="muted">Discord アカウントと同期済み（ID: <code>{html.escape(owner_id)}</code>）</p>
<div class="card" style="margin:20px 0">
  <p><strong>ストレージ</strong> {disk} · <strong>BOT</strong> {running}/{len(bots)} 稼働</p>
  <p class="muted">最終同期: {synced_text}</p>
  <p class="muted">フォルダ: <code>{html.escape(str(path))}</code></p>
</div>
<h2>あなたの BOT</h2>
<div class="card">{table}</div>
<p class="muted" style="margin-top:16px">BOT の作成・起動は Discord の <code>/cloud</code> コマンドから行えます。サイト上のデータは自動で同じフォルダに保存されます。</p>
"""
    return _layout("ダッシュボード", body, header)


def login_required_page() -> str:
    body = """
<h1>ログインが必要です</h1>
<p class="muted">このページを見るには Discord でログインしてください。</p>
<p><a class="btn" href="/auth/login">Discord でログイン</a></p>
"""
    return _layout("ログイン", body, '<a href="/">ホーム</a>')


def oauth_error_page(message: str) -> str:
    body = f"""
<h1>ログインエラー</h1>
<p class="muted">{html.escape(message)}</p>
<p><a href="/">ホームに戻る</a></p>
"""
    return _layout("エラー", body)
