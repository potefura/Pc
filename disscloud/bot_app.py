import asyncio
import os
import re
import signal

import discord
from discord import app_commands
from discord.ext import commands

from . import config
from .cloud import Cloud
from .gateway import Gateway
from .resources import dir_size, format_bytes
from .runtime import language_choices
from .store import ensure_user_profile, user_dir
from .ui import (
    TokenModal,
    bot_embed,
    help_embed,
    list_embed,
    panel_payload,
    site_config_embed,
    storage_embed,
)

def admin_ids() -> set[str]:
    raw = os.getenv("ADMIN_IDS", "")
    return {s.strip() for s in raw.split(",") if s.strip()}


def can_manage(interaction: discord.Interaction, bot: dict | None) -> bool:
    if not bot:
        return False
    if bot["ownerId"] == str(interaction.user.id):
        return True
    if str(interaction.user.id) in admin_ids():
        return True
    if isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator:
        return True
    return False


class SouCloudBot(commands.Bot):
    def __init__(self, cloud: Cloud) -> None:
        intents = discord.Intents.all()
        super().__init__(command_prefix="!", intents=intents)
        self.cloud = cloud
        self.selected: dict[str, str] = {}

    async def setup_hook(self) -> None:
        self.tree.add_command(cloud_group)
        await self.sync_commands()

    async def sync_commands(self) -> list[str]:
        """アプリコマンドを全サーバー対象でグローバル同期する。"""
        commands_synced = await self.tree.sync()
        result = f"グローバル: {len(commands_synced)}件"
        print(f"スラッシュコマンド同期完了 — {result}")
        return [result]

    def require_bot(self, interaction: discord.Interaction, name: str) -> dict:
        bot = self.cloud.get(name, str(interaction.user.id)) or self.cloud.get(name)
        if not bot:
            raise ValueError(f"BOT「{name}」が見つかりません")
        if not can_manage(interaction, bot):
            raise ValueError("このBOTを操作する権限がありません")
        return bot


cloud_group = app_commands.Group(name="cloud", description="そーCloud — DiscordだけでBOTを起動するクラウド")


async def bot_name_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    bots = interaction.client.cloud.list(str(interaction.user.id))
    current_lower = current.lower()
    choices = []
    for bot in bots:
        if current_lower and current_lower not in bot["name"].lower():
            continue
        emoji = "🟢" if bot["status"] == "running" else "⚫"
        choices.append(app_commands.Choice(name=f"{emoji} {bot['name']}", value=bot["name"]))
        if len(choices) >= 25:
            break
    return choices


async def language_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    return [app_commands.Choice(name=name, value=name) for name in language_choices(current)]


@cloud_group.command(name="help", description="使い方")
async def cloud_help(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(embed=help_embed(config.display_public_url()), ephemeral=True)


@cloud_group.command(name="config", description="サイト公開設定（Cloudflare URL など）を表示")
async def cloud_config(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(embed=site_config_embed(), ephemeral=True)


@cloud_group.command(name="sync", description="スラッシュコマンドを再同期（管理者のみ）")
async def cloud_sync(interaction: discord.Interaction) -> None:
    is_admin = str(interaction.user.id) in admin_ids()
    if isinstance(interaction.user, discord.Member):
        is_admin = is_admin or interaction.user.guild_permissions.administrator
    if not is_admin:
        raise ValueError("このコマンドは管理者だけが実行できます")
    await interaction.response.defer(ephemeral=True)
    results = await interaction.client.sync_commands()
    await interaction.followup.send("✅ コマンドを再同期しました\n" + "\n".join(results), ephemeral=True)


@cloud_group.command(name="list", description="自分のBOT一覧")
async def cloud_list(interaction: discord.Interaction) -> None:
    bots = interaction.client.cloud.list(str(interaction.user.id))
    await interaction.response.send_message(
        embed=list_embed(bots, interaction.user, config.display_public_url()),
        ephemeral=True,
    )


@cloud_group.command(name="panel", description="起動パネル（ボタン操作）")
async def cloud_panel(interaction: discord.Interaction) -> None:
    bots = interaction.client.cloud.list(str(interaction.user.id))
    selected = interaction.client.selected.get(str(interaction.user.id)) or (bots[0]["id"] if bots else None)
    if selected:
        interaction.client.selected[str(interaction.user.id)] = selected
    payload = panel_payload(interaction.client.cloud, str(interaction.user.id), selected)
    await interaction.response.send_message(**payload, ephemeral=True)


@cloud_group.command(name="create", description="BOTを作成（テンプレート or ファイル添付）")
@app_commands.describe(
    name="BOT名",
    source="任意言語のソース / zip を添付すると自分のコードで作成",
    language="言語（省略時はファイルから自動判定。未導入なら自動インストール）",
)
@app_commands.autocomplete(language=language_autocomplete)
async def cloud_create(
    interaction: discord.Interaction,
    name: str,
    source: discord.Attachment | None = None,
    language: str | None = None,
) -> None:
    await interaction.response.defer(ephemeral=True)
    if source and source.size > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise ValueError(f"ファイルは {config.MAX_UPLOAD_MB}MB までです")
    bot = await interaction.client.cloud.create(
        owner_id=str(interaction.user.id),
        name=name,
        username=str(interaction.user),
        source_url=source.url if source else None,
        filename=source.filename if source else None,
        template=source is None,
        language=language,
    )
    await interaction.followup.send(
        content=(
            f"✅ **{bot['name']}** を作成しました（`{bot.get('runtime', 'python')}` / `{bot['entry']}`）\n"
            f"サイト: {interaction.client.cloud.site_url(bot)}\n"
            f"次に `/cloud token name:{bot['name']}` でゲストBOTのトークンを入れてから起動してください。"
        ),
        embed=bot_embed(bot, site_url=interaction.client.cloud.site_url(bot)),
    )


@cloud_group.command(name="deploy", description="BOTのソースを安全に更新")
@app_commands.describe(
    name="更新するBOT名",
    source="新しいソースファイル / zip",
    language="言語（省略時はファイルから自動判定）",
)
@app_commands.autocomplete(name=bot_name_autocomplete, language=language_autocomplete)
async def cloud_deploy(
    interaction: discord.Interaction,
    name: str,
    source: discord.Attachment,
    language: str | None = None,
) -> None:
    await interaction.response.defer(ephemeral=True)
    bot = interaction.client.require_bot(interaction, name)
    if source.size > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise ValueError(f"ファイルは {config.MAX_UPLOAD_MB}MB までです")
    result = await interaction.client.cloud.deploy(bot["id"], source.url, source.filename, language)
    restart_result = "再起動済み" if result["restarted"] else "停止状態を維持"
    await interaction.followup.send(
        f"✅ **{bot['name']}** をデプロイしました\n"
        f"ランタイム: `{result['runtime']}`\n"
        f"エントリ: `{result['entry']}`\n"
        f"実行状態: {restart_result}",
        ephemeral=True,
    )


@cloud_group.command(name="token", description="ゲストBOTのトークンを設定（モーダル・他人には見えません）")
@app_commands.autocomplete(name=bot_name_autocomplete)
async def cloud_token(interaction: discord.Interaction, name: str) -> None:
    bot = interaction.client.require_bot(interaction, name)
    await interaction.response.send_modal(TokenModal(interaction.client.cloud, bot))


@cloud_group.command(name="start", description="BOTを起動")
@app_commands.autocomplete(name=bot_name_autocomplete)
async def cloud_start(interaction: discord.Interaction, name: str) -> None:
    await interaction.response.defer(ephemeral=True)
    bot = interaction.client.require_bot(interaction, name)
    await interaction.client.cloud.start(bot["id"])
    await interaction.followup.send(
        content=f"🟢 **{bot['name']}** を起動しました",
        embed=bot_embed(bot, site_url=interaction.client.cloud.site_url(bot)),
    )


@cloud_group.command(name="stop", description="BOTを停止")
@app_commands.autocomplete(name=bot_name_autocomplete)
async def cloud_stop(interaction: discord.Interaction, name: str) -> None:
    await interaction.response.defer(ephemeral=True)
    bot = interaction.client.require_bot(interaction, name)
    await interaction.client.cloud.stop(bot["id"])
    await interaction.followup.send(
        content=f"⚫ **{bot['name']}** を停止しました",
        embed=bot_embed(bot, site_url=interaction.client.cloud.site_url(bot)),
    )


@cloud_group.command(name="restart", description="BOTを再起動")
@app_commands.autocomplete(name=bot_name_autocomplete)
async def cloud_restart(interaction: discord.Interaction, name: str) -> None:
    await interaction.response.defer(ephemeral=True)
    bot = interaction.client.require_bot(interaction, name)
    await interaction.client.cloud.restart(bot["id"])
    await interaction.followup.send(
        content=f"🔄 **{bot['name']}** を再起動しました",
        embed=bot_embed(bot, site_url=interaction.client.cloud.site_url(bot)),
    )


@cloud_group.command(name="logs", description="ログを表示")
@app_commands.autocomplete(name=bot_name_autocomplete)
async def cloud_logs(interaction: discord.Interaction, name: str) -> None:
    bot = interaction.client.require_bot(interaction, name)
    logs = interaction.client.cloud.get_logs(bot["id"], 25)
    await interaction.response.send_message(
        embed=bot_embed(bot, logs=logs, site_url=interaction.client.cloud.site_url(bot)),
        ephemeral=True,
    )


@cloud_group.command(name="site", description="公開サイトURLを表示")
@app_commands.autocomplete(name=bot_name_autocomplete)
async def cloud_site(interaction: discord.Interaction, name: str) -> None:
    bot = interaction.client.require_bot(interaction, name)
    url = interaction.client.cloud.site_url(bot)
    await interaction.response.send_message(
        f"🌐 **{bot['name']}** のサイト: {url}\n`public/` フォルダに HTML を置くと公開されます。",
        ephemeral=True,
    )


@cloud_group.command(name="storage", description="個人フォルダの情報を表示")
async def cloud_storage(interaction: discord.Interaction) -> None:
    owner_id = str(interaction.user.id)
    ensure_user_profile(owner_id, str(interaction.user))
    path = user_dir(owner_id)
    bots = interaction.client.cloud.list(owner_id)
    disk = format_bytes(dir_size(path))
    await interaction.response.send_message(
        embed=storage_embed(interaction.user, str(path), len(bots), disk),
        ephemeral=True,
    )


@cloud_group.command(name="env", description="環境変数を設定")
@app_commands.autocomplete(name=bot_name_autocomplete)
async def cloud_env(interaction: discord.Interaction, name: str, key: str, value: str | None = None) -> None:
    await interaction.response.defer(ephemeral=True)
    bot = interaction.client.require_bot(interaction, name)
    key = key.upper()
    if not re.match(r"^[A-Z_][A-Z0-9_]*$", key):
        raise ValueError("変数名が不正です")
    interaction.client.cloud.set_env(bot["id"], bot["ownerId"], key, value or "")
    keys = [k for k in interaction.client.cloud.get_env(bot["id"], bot["ownerId"]) if k != "DISCORD_TOKEN"]
    if value:
        msg = f"✅ `{key}` を保存しました（値は表示しません）"
    else:
        msg = f"🗑️ `{key}` を削除しました\n現在のキー: {', '.join(keys) or '(なし)'}"
    await interaction.followup.send(msg)


@cloud_group.command(name="delete", description="BOTを削除")
@app_commands.autocomplete(name=bot_name_autocomplete)
async def cloud_delete(interaction: discord.Interaction, name: str) -> None:
    await interaction.response.defer(ephemeral=True)
    bot = interaction.client.require_bot(interaction, name)
    await interaction.client.cloud.remove(bot["id"])
    await interaction.followup.send(f"🗑️ **{bot['name']}** を削除しました")


async def run() -> None:
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit(".env に DISCORD_TOKEN を設定してください（このクラウド本体のBOTトークン）")

    cloud = Cloud()
    gateway = Gateway(cloud)
    await gateway.start()

    bot = SouCloudBot(cloud)

    @bot.tree.error
    async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        original = getattr(error, "original", error)
        message = str(original) or "コマンドの実行中にエラーが発生しました"
        if interaction.response.is_done():
            await interaction.followup.send(f"⚠️ {message}", ephemeral=True)
        else:
            await interaction.response.send_message(f"⚠️ {message}", ephemeral=True)
        print(f"コマンドエラー: {type(original).__name__}: {original}")

    @bot.event
    async def on_ready() -> None:
        print(f"そーCloud 起動: {bot.user}")

    loop = asyncio.get_running_loop()

    def shutdown() -> None:
        asyncio.create_task(_shutdown(cloud, gateway, bot))

    async def _shutdown(c: Cloud, g: Gateway, b: SouCloudBot) -> None:
        await c.stop_all()
        await g.stop()
        await b.close()

    if os.name != "nt":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, shutdown)

    try:
        await bot.start(token)
    finally:
        await cloud.stop_all()
        await gateway.stop()


if __name__ == "__main__":
    asyncio.run(run())
