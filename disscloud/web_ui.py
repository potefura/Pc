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
.file-toolbar, .file-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.file-toolbar select { margin-left: 6px; padding: 8px; color: inherit; background: #0f1115; border: 1px solid #3b414c; border-radius: 6px; }
.file-drop { margin: 16px 0; padding: 20px; text-align: center; border: 2px dashed #3b414c; border-radius: 10px; color: #9aa0a6; }
.file-drop.active { border-color: #5865f2; background: #20243b; }
.file-workspace { display: grid; grid-template-columns: minmax(200px, 1fr) 2fr; gap: 16px; }
.file-tree { min-height: 280px; max-height: 430px; overflow: auto; padding: 8px; background: #111318; border-radius: 8px; }
.file-row { display: block; width: 100%; padding: 7px; color: inherit; background: transparent; border: 0; border-radius: 5px; text-align: left; cursor: pointer; }
.file-row:hover:not(:disabled) { background: #2c313a; }.file-row:disabled { cursor: default; }
.file-editor textarea { box-sizing: border-box; width: 100%; min-height: 330px; margin: 10px 0; padding: 12px; resize: vertical; color: #e8eaed; background: #0f1115; border: 1px solid #3b414c; border-radius: 8px; font: 13px ui-monospace, monospace; }
.btn.danger { background: #da373c; }
@media (max-width: 700px) { .file-workspace { grid-template-columns: 1fr; } }
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
        href = f"{public_base.rstrip('/')}/s/{bot['name']}/"
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
        site = bot_site_url(bot["name"])
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
        "<table id='bot-table' style='width:100%;border-collapse:collapse'>"
        "<tr><th align='left'>BOT</th><th align='left'>状態</th><th align='left'>言語</th><th align='left'>エントリ</th><th align='left'>リンク</th></tr>"
        + "".join(bot_rows)
        + "</table>"
        if bot_rows
        else "<p id='bot-empty' class='muted'>まだ BOT がありません。Discord で <code>/cloud create</code> を実行してください。</p>"
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
<div class="card" id="bots">{table}</div>
<h2>ログ</h2>
<div class="card"><pre id="event-log" style="white-space:pre-wrap;max-height:280px;overflow:auto">(ログなし)</pre></div>
<h2>ファイル</h2>
<div class="card"><ul id="file-tree" style="font-family:ui-monospace,monospace"><li class="muted">読み込み中...</li></ul></div>
<p class="muted" style="margin-top:16px">BOT の作成・起動は Discord の <code>/cloud</code> コマンドから行えます。サイト上のデータは自動で同じフォルダに保存されます。</p>
<script>
(() => {{
  const ownerId = {owner_id!r};
  let retry = 1000, socket, refreshTimer;
  const botNames = new Map();

  function renderBots(data) {{
    const box = document.getElementById('bots');
    box.replaceChildren();
    botNames.clear();
    if (!data.bots.length) {{
      const empty = document.createElement('p'); empty.className = 'muted';
      empty.textContent = 'まだ BOT がありません。Discord で /cloud create を実行してください。'; box.append(empty); return;
    }}
    const table = document.createElement('table'); table.style.cssText = 'width:100%;border-collapse:collapse';
    const head = table.insertRow(); ['BOT','状態','言語','エントリ','リンク'].forEach(x => {{ const th=document.createElement('th'); th.align='left'; th.textContent=x; head.append(th); }});
    data.bots.forEach(bot => {{
      botNames.set(bot.id, bot.name);
      const row=table.insertRow();
      [bot.name, bot.status === 'running' ? '稼働中' : '停止', bot.runtime, bot.entry].forEach((x,i) => {{ const td=row.insertCell(); td.textContent=x; if(i===1) td.className=bot.status==='running'?'ok':'off'; }});
      const link=document.createElement('a'); link.href=bot.site; link.textContent='サイト'; row.insertCell().append(link);
    }});
    box.append(table);
    const logs = data.bots.map(bot => `# ${{bot.name}}\n${{bot.logs}}`).join('\n\n');
    document.getElementById('event-log').textContent = logs || '(ログなし)';
  }}

  async function refreshMe() {{
    const response = await fetch('/api/me', {{cache:'no-store'}});
    if (response.status === 401) {{ location.href='/auth/login'; return; }}
    renderBots(await response.json());
  }}
  async function refreshFiles() {{
    const response = await fetch('/api/files', {{cache:'no-store'}}); if (!response.ok) return;
    const ul=document.getElementById('file-tree'); ul.replaceChildren();
    const files=(await response.json()).files;
    files.forEach(file => {{ const li=document.createElement('li'); li.textContent=`${{botNames.get(file.botId)||file.botId}}/${{file.path}}${{file.directory?'/':''}}`; ul.append(li); }});
    if (!files.length) {{ const li=document.createElement('li'); li.className='muted'; li.textContent='ファイルなし'; ul.append(li); }}
  }}
  function reconcile() {{
    clearTimeout(refreshTimer);
    refreshTimer=setTimeout(() => Promise.all([refreshMe(), refreshFiles()]).catch(() => {{}}), 80);
  }}
  function connect() {{
    const scheme=location.protocol==='https:'?'wss:':'ws:';
    socket=new WebSocket(`${{scheme}}//${{location.host}}/api/events`);
    socket.onopen=() => {{ retry=1000; Promise.all([refreshMe(), refreshFiles()]).catch(() => {{}}); }};
    socket.onmessage=message => {{
      let event; try {{ event=JSON.parse(message.data); }} catch (_) {{ return; }}
      if (event.ownerId !== ownerId) return;
      if (event.type === 'log.appended') {{
        const log=document.getElementById('event-log');
        log.textContent += `\n[${{botNames.get(event.botId)||event.botId}}] ${{event.state.line}}`; log.scrollTop=log.scrollHeight;
      }} else if (event.type.startsWith('file.')) {{ refreshFiles().catch(() => {{}}); }}
      else if (event.type.startsWith('bot.')) {{ reconcile(); }}
    }};
    socket.onclose=() => {{ const wait=retry; retry=Math.min(retry*2,30000); setTimeout(connect, wait); }};
    socket.onerror=() => socket.close();
  }}
  Promise.all([refreshMe(), refreshFiles()]).finally(connect);
}})();
</script>
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
