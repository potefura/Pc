from datetime import datetime, timezone

import discord

from . import config
from .cloud import Cloud
from .resources import dir_size, format_bytes


def status_emoji(status: str) -> str:
    return "🟢" if status == "running" else "⚫"


def bot_embed(bot: dict, *, logs: str | None = None, site_url: str | None = None) -> discord.Embed:
    color = config.COLORS["green"] if bot["status"] == "running" else config.COLORS["gray"]
    embed = discord.Embed(
        title=f"{status_emoji(bot['status'])} {bot['name']}",
        color=color,
        timestamp=datetime.fromtimestamp(bot["createdAt"] / 1000, tz=timezone.utc),
    )
    embed.add_field(name="ID", value=f"`{bot['id']}`", inline=True)
    embed.add_field(name="状態", value="稼働中" if bot["status"] == "running" else "停止", inline=True)
    embed.add_field(name="ランタイム", value=f"`{bot.get('runtime') or 'python'}`", inline=True)
    embed.add_field(name="エントリ", value=f"`{bot['entry']}`", inline=True)
    embed.add_field(name="自動再起動", value="ON" if bot.get("autoRestart") else "OFF", inline=True)
    embed.add_field(name="再起動回数", value=str(bot.get("restarts", 0)), inline=True)
    if site_url:
        embed.add_field(name="サイト", value=site_url, inline=False)
    if logs:
        embed.add_field(name="ログ", value=f"```\n{logs[:900]}\n```", inline=False)
    if bot.get("lastError"):
        embed.add_field(name="エラー", value=str(bot["lastError"])[:500], inline=False)
    embed.set_footer(text="そーCloud · Discordだけで完結する BOT クラウド")
    return embed


def list_embed(bots: list[dict], user: discord.User | discord.Member, site_base: str) -> discord.Embed:
    running = sum(1 for b in bots if b["status"] == "running")
    if bots:
        lines = [
            f"{status_emoji(b['status'])} **{b['name']}** · `{b.get('runtime') or 'python'}` · `{b['id']}`"
            for b in bots
        ]
        description = "\n".join(lines)
    else:
        description = "まだBOTがありません。`/cloud create` で作成してください。"
    embed = discord.Embed(
        title="そーCloud",
        description=description,
        color=config.COLORS["blurple"],
    )
    embed.add_field(name="稼働", value=f"{running}/{len(bots)}", inline=True)
    embed.add_field(name="オーナー", value=user.mention, inline=True)
    embed.add_field(name="サイト一覧", value=site_base, inline=False)
    embed.set_footer(text="パネルのボタンから起動・停止できます")
    return embed


def help_embed(site_base: str) -> discord.Embed:
    embed = discord.Embed(
        title="そーCloud の使い方",
        description="Webダッシュボードは不要です。Discordの中だけで、言語を問わずBOTをデプロイして起動できます。未導入の言語は起動時に自動インストールします（Termux / Linux / Windows）。",
        color=config.COLORS["blurple"],
    )
    embed.add_field(
        name="最短スタート",
        value=(
            "1. `/cloud create name:mybot`\n"
            "2. `/cloud token name:mybot` でトークン設定\n"
            "3. `/cloud start name:mybot` または `/cloud panel`"
        ),
        inline=False,
    )
    embed.add_field(
        name="自分のコードを載せる",
        value="`/cloud create` にソースまたは `.zip` を添付。言語は自動判定し、未導入なら自動で入れます。`language` で明示もできます。",
        inline=False,
    )
    embed.add_field(
        name="コマンド",
        value=(
            "`/cloud create` 作成\n"
            "`/cloud token` トークン（他人には見えません）\n"
            "`/cloud start` `/cloud stop` `/cloud restart`\n"
            "`/cloud logs` `/cloud list` `/cloud panel`\n"
            "`/cloud site` 公開URL\n"
            "`/cloud config` サイト設定（Cloudflare）\n"
            "`/cloud storage` 個人フォルダ情報\n"
            "`/cloud env` 環境変数\n"
            "`/cloud delete` 削除"
        ),
        inline=False,
    )
    embed.add_field(
        name="サイト公開",
        value=(
            f"各BOTの `public/` フォルダが自動ホストされます。\n"
            f"一覧: {site_base}\n"
            "Cloudflare 利用時は `.env` の `PUBLIC_URL` / `CLOUDFLARE_DOMAIN` を設定してください。"
        ),
        inline=False,
    )
    embed.add_field(
        name="個人ストレージ",
        value="ユーザーごとに `users/<あなたのID>/` 以下にBOT・ファイルが自動保存されます。",
        inline=False,
    )
    return embed


def site_config_embed() -> discord.Embed:
    settings = config.site_settings_summary()
    embed = discord.Embed(
        title="サイト公開設定",
        description="Cloudflare 経由でアクセスする場合は `.env` で以下を設定します。",
        color=config.COLORS["blurple"],
    )
    for key, value in settings.items():
        embed.add_field(name=key, value=value, inline=False)
    embed.add_field(
        name="BOTのURL形式",
        value=f"`{config.display_public_url()}/s/<BOT ID>/<BOT名>/`",
        inline=False,
    )
    if config.CLOUDFLARE_TUNNEL:
        embed.add_field(
            name="Cloudflare Tunnel 例",
            value=(
                "```\n"
                "cloudflared tunnel --url http://localhost:8080\n"
                "```\n"
                "表示された URL または独自ドメインを `PUBLIC_URL` に設定"
            ),
            inline=False,
        )
    elif config.CLOUDFLARE_ENABLED:
        embed.add_field(
            name="Cloudflare プロキシ例",
            value=(
                "DNS でオレンジ雲（プロキシ）を ON → オリジンは `SITE_PORT`\n"
                "`PUBLIC_URL=https://cloud.example.com`"
            ),
            inline=False,
        )
    if config.DISCORD_CLIENT_ID and config.DISCORD_CLIENT_SECRET:
        redirect = config.OAUTH_REDIRECT_URI or f"{config.display_public_url()}/auth/callback"
        embed.add_field(
            name="Discord ログイン",
            value=f"Developer Portal の Redirect URI:\n`{redirect}`",
            inline=False,
        )
    return embed


def storage_embed(user: discord.User | discord.Member, path: str, bot_count: int, disk: str) -> discord.Embed:
    embed = discord.Embed(
        title="個人ストレージ",
        description="あなた専用のフォルダにBOTとファイルが自動保存されています。",
        color=config.COLORS["blurple"],
    )
    embed.add_field(name="ユーザー", value=user.mention, inline=True)
    embed.add_field(name="BOT数", value=str(bot_count), inline=True)
    embed.add_field(name="使用量", value=disk, inline=True)
    embed.add_field(name="パス", value=f"`{path}`", inline=False)
    embed.add_field(
        name="構成",
        value="`bots/` — 各BOTのコード・データ\n`files/` — 個人用ファイル保存先",
        inline=False,
    )
    return embed


class BotSelect(discord.ui.Select):
    def __init__(self, cloud: Cloud, owner_id: str, bots: list[dict], selected_id: str | None) -> None:
        self.cloud = cloud
        self.owner_id = owner_id
        options = [
            discord.SelectOption(
                label=b["name"][:100],
                value=b["id"],
                description=f"{'稼働中' if b['status'] == 'running' else '停止'} · {b.get('runtime') or 'python'}",
                default=b["id"] == selected_id,
            )
            for b in bots[:25]
        ]
        super().__init__(placeholder="操作するBOTを選択", custom_id="cloud:select", options=options or [discord.SelectOption(label="なし", value="_none")])

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.values[0] == "_none":
            return
        await interaction.response.edit_message(**panel_payload(self.cloud, self.owner_id, self.values[0]))


class PanelView(discord.ui.View):
    def __init__(self, cloud: Cloud, owner_id: str, selected_id: str | None) -> None:
        super().__init__(timeout=300)
        self.cloud = cloud
        self.owner_id = owner_id
        self.selected_id = selected_id
        bots = cloud.list(owner_id)
        if bots:
            self.add_item(BotSelect(cloud, owner_id, bots, selected_id))

    @discord.ui.button(label="起動", style=discord.ButtonStyle.success, custom_id="cloud:start")
    async def start_btn(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._action(interaction, "start")

    @discord.ui.button(label="停止", style=discord.ButtonStyle.danger, custom_id="cloud:stop")
    async def stop_btn(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._action(interaction, "stop")

    @discord.ui.button(label="再起動", style=discord.ButtonStyle.primary, custom_id="cloud:restart")
    async def restart_btn(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._action(interaction, "restart")

    @discord.ui.button(label="ログ", style=discord.ButtonStyle.secondary, custom_id="cloud:logs")
    async def logs_btn(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if not self.selected_id:
            await interaction.response.send_message("先にBOTを選択してください", ephemeral=True)
            return
        bot = self.cloud.state["bots"].get(self.selected_id)
        if not bot or bot["ownerId"] != self.owner_id:
            await interaction.response.send_message("操作できません", ephemeral=True)
            return
        logs = self.cloud.get_logs(bot["id"], 25)
        await interaction.response.send_message(
            embed=bot_embed(bot, logs=logs, site_url=self.cloud.site_url(bot)),
            ephemeral=True,
        )

    @discord.ui.button(label="更新", style=discord.ButtonStyle.secondary, custom_id="cloud:refresh")
    async def refresh_btn(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.edit_message(**panel_payload(self.cloud, self.owner_id, self.selected_id))

    async def _action(self, interaction: discord.Interaction, action: str) -> None:
        if not self.selected_id:
            await interaction.response.send_message("先にBOTを選択してください", ephemeral=True)
            return
        bot = self.cloud.state["bots"].get(self.selected_id)
        if not bot or bot["ownerId"] != self.owner_id:
            await interaction.response.send_message("操作できません", ephemeral=True)
            return
        await interaction.response.defer()
        try:
            if action == "start":
                await self.cloud.start(bot["id"])
            elif action == "stop":
                await self.cloud.stop(bot["id"])
            elif action == "restart":
                await self.cloud.restart(bot["id"])
        except Exception as err:
            await interaction.followup.send(f"⚠️ {err}", ephemeral=True)
        await interaction.edit_original_response(**panel_payload(self.cloud, self.owner_id, self.selected_id))


class TokenModal(discord.ui.Modal, title="BOTトークン"):
    token = discord.ui.TextInput(
        label="Discord Bot Token",
        placeholder="MTEx...  （Developer Portal の Bot トークン）",
        required=True,
        min_length=50,
    )

    def __init__(self, cloud: Cloud, bot: dict) -> None:
        super().__init__()
        self.cloud = cloud
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        tok = str(self.token.value).strip()
        if len(tok) < 50:
            await interaction.response.send_message("トークンが短すぎます", ephemeral=True)
            return
        self.cloud.set_env(self.bot["id"], self.bot["ownerId"], "DISCORD_TOKEN", tok)
        await interaction.response.send_message(
            f"✅ **{self.bot['name']}** のトークンを保存しました。\n"
            f"`/cloud start name:{self.bot['name']}` で起動できます。",
            ephemeral=True,
        )


def panel_payload(cloud: Cloud, owner_id: str, selected_id: str | None) -> dict:
    bots = cloud.list(owner_id)
    sel = next((b for b in bots if b["id"] == selected_id), None) if selected_id else None
    if sel:
        return {
            "embeds": [bot_embed(sel, logs=cloud.get_logs(sel["id"], 12), site_url=cloud.site_url(sel))],
            "view": PanelView(cloud, owner_id, sel["id"]),
        }
    user = type("U", (), {"id": owner_id, "mention": f"<@{owner_id}>"})()
    return {
        "embeds": [list_embed(bots, user, config.display_public_url())],
        "view": PanelView(cloud, owner_id, selected_id),
    }
