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
        "<table style='width:100%;border-collapse:collapse'>"
        "<tr><th align='left'>BOT</th><th align='left'>状態</th><th align='left'>言語</th><th align='left'>エントリ</th><th align='left'>リンク</th></tr>"
        + "".join(bot_rows)
        + "</table>"
        if bot_rows
        else "<p class='muted'>まだ BOT がありません。Discord で <code>/cloud create</code> を実行してください。</p>"
    )
    bot_options = "".join(
        f'<option value="{html.escape(str(bot["id"]))}">{html.escape(bot["name"])}</option>' for bot in bots
    )
    file_manager = f"""
<h2>ファイル管理</h2>
<div class="card file-manager">
  <div class="file-toolbar">
    <label>BOT <select id="file-bot">{bot_options}</select></label>
    <label class="btn secondary" for="file-upload">ファイル / ZIP を選択</label>
    <input id="file-upload" type="file" hidden>
    <button class="btn secondary" id="file-refresh" type="button">更新</button>
  </div>
  <div id="file-drop" class="file-drop">ここにファイルまたは ZIP をドラッグ＆ドロップ</div>
  <div class="file-workspace">
    <div id="file-tree" class="file-tree"><span class="muted">BOT を選択してください</span></div>
    <div class="file-editor">
      <div><code id="file-current">ファイル未選択</code></div>
      <textarea id="file-content" spellcheck="false" disabled></textarea>
      <div class="file-actions">
        <button class="btn" id="file-save" type="button" disabled>保存</button>
        <button class="btn secondary" id="file-download" type="button" disabled>ダウンロード</button>
        <button class="btn danger" id="file-delete" type="button" disabled>削除</button>
      </div>
    </div>
  </div>
  <p id="file-status" class="muted" role="status"></p>
</div>
<script>
(() => {{
  const bot = document.querySelector('#file-bot'), tree = document.querySelector('#file-tree');
  const editor = document.querySelector('#file-content'), current = document.querySelector('#file-current');
  const status = document.querySelector('#file-status'), upload = document.querySelector('#file-upload');
  const buttons = ['save', 'download', 'delete'].map(x => document.querySelector('#file-' + x));
  let selected = '';
  const api = path => '/api/bots/' + encodeURIComponent(bot.value) + '/files' + (path ? '/' + path.split('/').map(encodeURIComponent).join('/') : '');
  const message = text => status.textContent = text;
  async function json(response) {{
    const data = await response.json().catch(() => ({{error: 'リクエストに失敗しました'}}));
    if (!response.ok) throw new Error(data.error || 'リクエストに失敗しました');
    return data;
  }}
  async function refresh() {{
    if (!bot.value) return;
    try {{
      const data = await json(await fetch(api('')));
      tree.replaceChildren();
      data.files.forEach(file => {{
        const row = document.createElement('button');
        row.type = 'button'; row.className = 'file-row ' + file.type;
        row.textContent = (file.type === 'directory' ? '📁 ' : '📄 ') + file.path;
        if (file.type === 'file') row.onclick = () => openFile(file.path);
        else row.disabled = true;
        tree.append(row);
      }});
      if (!data.files.length) tree.textContent = 'ファイルがありません';
      message('');
    }} catch (error) {{ message(error.message); }}
  }}
  async function openFile(path) {{
    selected = path; current.textContent = path;
    buttons.forEach(x => x.disabled = false);
    try {{
      const data = await json(await fetch(api(path) + '?text=1'));
      editor.value = data.content; editor.disabled = false; message('テキストファイルを開きました');
    }} catch (error) {{ editor.value = ''; editor.disabled = true; message(error.message); }}
  }}
  async function sendFile(file) {{
    const form = new FormData(); form.append('file', file);
    try {{ await json(await fetch(api(''), {{method: 'POST', body: form}})); message(file.name + ' をアップロードしました'); await refresh(); }}
    catch (error) {{ message(error.message); }}
  }}
  document.querySelector('#file-refresh').onclick = refresh;
  bot.onchange = () => {{ selected = ''; editor.value = ''; editor.disabled = true; buttons.forEach(x => x.disabled = true); refresh(); }};
  upload.onchange = () => upload.files[0] && sendFile(upload.files[0]);
  const drop = document.querySelector('#file-drop');
  drop.ondragover = event => {{ event.preventDefault(); drop.classList.add('active'); }};
  drop.ondragleave = () => drop.classList.remove('active');
  drop.ondrop = event => {{ event.preventDefault(); drop.classList.remove('active'); if (event.dataTransfer.files[0]) sendFile(event.dataTransfer.files[0]); }};
  buttons[0].onclick = async () => {{ try {{ await json(await fetch(api(selected), {{method:'PUT', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{content:editor.value}})}})); message('保存しました'); }} catch(error) {{ message(error.message); }} }};
  buttons[1].onclick = () => {{ if (selected) location.href = api(selected); }};
  buttons[2].onclick = async () => {{ if (!selected || !confirm(selected + ' を削除しますか？')) return; try {{ await json(await fetch(api(selected), {{method:'DELETE'}})); selected=''; editor.value=''; editor.disabled=true; buttons.forEach(x=>x.disabled=true); await refresh(); message('削除しました'); }} catch(error) {{ message(error.message); }} }};
  refresh();
}})();
</script>
""" if bots else ""

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
{file_manager}
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
