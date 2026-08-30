import os
import discord
from discord import app_commands

token = os.environ.get("DISCORD_TOKEN")
if not token:
    raise SystemExit("DISCORD_TOKEN がありません。クラウド側で /cloud token を実行してください。")

DATA_DIR = os.environ.get("BOT_DATA_DIR", "data")
PUBLIC_DIR = os.environ.get("BOT_PUBLIC_DIR", "public")

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


@tree.command(name="ping", description="応答速度を確認")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("pong")


@tree.command(name="info", description="このBOTの情報")
async def info(interaction: discord.Interaction):
    await interaction.response.send_message(
        f"**{client.user}**\n"
        f"サーバー数: {len(client.guilds)}\n"
        f"データ保存先: `{DATA_DIR}`\n"
        f"サイト公開先: `{PUBLIC_DIR}`\n"
        f"起動元: そーCloud (Python)"
    )


@client.event
async def on_ready():
    await tree.sync()
    print(f"起動: {client.user} ({client.user.id})")


client.run(token)
