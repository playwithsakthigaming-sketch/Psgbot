import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
import aiosqlite
import os
import re

DB_NAME = "bot.db"
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
CHECK_INTERVAL = 120  # seconds


# =========================
# Resolve Channel ID from URL / @handle / ID
# =========================
async def resolve_channel_id(input_text: str):
    if input_text.startswith("UC"):
        return input_text

    match = re.search(r"@([\w\-]+)", input_text)
    if not match:
        return None

    handle = match.group(1)

    url = (
        "https://www.googleapis.com/youtube/v3/channels"
        f"?part=id&forHandle=@{handle}&key={YOUTUBE_API_KEY}"
    )

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()

    if not data.get("items"):
        return None

    return data["items"][0]["id"]


# =========================
# YOUTUBE COG
# =========================
class YouTube(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -------------------------
    # Start loop safely
    # -------------------------
    @commands.Cog.listener()
    async def on_ready(self):
        if not self.check_videos.is_running():
            self.check_videos.start()
            print("✅ YouTube alert loop started")

    # -------------------------
    # SETUP CHANNEL
    # -------------------------
    @app_commands.command(name="setup_channel", description="Add YouTube alerts (URL or ID)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_channel(
        self,
        interaction: discord.Interaction,
        youtube_channel: str,
        discord_channel: discord.TextChannel,
        role: discord.Role = None,
        message: str = "📢 {type} alert!\n{title}\n{url}"
    ):
        await interaction.response.defer(ephemeral=True)

        try:
            channel_id = await resolve_channel_id(youtube_channel)
            if not channel_id:
                return await interaction.followup.send("❌ Invalid YouTube channel URL or ID")

            async with aiosqlite.connect(DB_NAME) as db:
                await db.execute("""
                INSERT OR REPLACE INTO youtube_alerts
                (guild_id, youtube_channel, discord_channel, role_ping, message, last_video)
                VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    interaction.guild.id,
                    channel_id,
                    discord_channel.id,
                    role.id if role else None,
                    message,
                    None
                ))
                await db.commit()

            await interaction.followup.send(f"✅ YouTube channel added:\n`{channel_id}`")

        except Exception as e:
            await interaction.followup.send(f"❌ Error: `{e}`")

    # -------------------------
    # ALIAS: /setchannel
    # -------------------------
    @app_commands.command(name="setchannel", description="Alias for setup_channel")
    @app_commands.checks.has_permissions(administrator=True)
    async def setchannel(
        self,
        interaction: discord.Interaction,
        youtube_channel: str,
        discord_channel: discord.TextChannel,
        role: discord.Role = None,
        message: str = "📢 {type} alert!\n{title}\n{url}"
    ):
        await self.setup_channel(interaction, youtube_channel, discord_channel, role, message)

    # -------------------------
    # REMOVE CHANNEL
    # -------------------------
    @app_commands.command(name="remove_channel")
    @app_commands.checks.has_permissions(administrator=True)
    async def remove_channel(self, interaction: discord.Interaction, youtube_channel: str):
        await interaction.response.defer(ephemeral=True)

        try:
            channel_id = await resolve_channel_id(youtube_channel)
            if not channel_id:
                return await interaction.followup.send("❌ Invalid channel")

            async with aiosqlite.connect(DB_NAME) as db:
                await db.execute(
                    "DELETE FROM youtube_alerts WHERE guild_id=? AND youtube_channel=?",
                    (interaction.guild.id, channel_id)
                )
                await db.commit()

            await interaction.followup.send("✅ Channel removed")

        except Exception as e:
            await interaction.followup.send(f"❌ Error: `{e}`")

    # -------------------------
    # LIST CHANNELS
    # -------------------------
    @app_commands.command(name="list_channels")
    async def list_channels(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute(
                "SELECT youtube_channel FROM youtube_alerts WHERE guild_id=?",
                (interaction.guild.id,)
            )
            rows = await cursor.fetchall()

        if not rows:
            return await interaction.followup.send("❌ No channels added")

        txt = "\n".join(f"• {r[0]}" for r in rows)
        await interaction.followup.send(f"📺 Tracked Channels:\n{txt}")

    # -------------------------
    # TEST
    # -------------------------
    @app_commands.command(name="youtube_test")
    async def youtube_test(self, interaction: discord.Interaction):
        await interaction.response.send_message("✅ YouTube system running", ephemeral=True)

    # -------------------------
    # FETCH VIDEO (Video / Shorts / Live)
    # -------------------------
    async def fetch_latest_video(self, channel_id):
        url = (
            "https://www.googleapis.com/youtube/v3/search"
            f"?part=snippet&channelId={channel_id}"
            f"&maxResults=1&order=date&type=video&key={YOUTUBE_API_KEY}"
        )

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()

        if not data.get("items"):
            return None

        item = data["items"][0]
        video_id = item["id"]["videoId"]
        title = item["snippet"]["title"]
        thumbnail = item["snippet"]["thumbnails"]["high"]["url"]

        is_live = item["snippet"]["liveBroadcastContent"] == "live"
        is_shorts = "#short" in title.lower()

        if is_live:
            vtype = "🔴 LIVE"
        elif is_shorts:
            vtype = "🎬 SHORTS"
        else:
            vtype = "📺 VIDEO"

        return {
            "video_id": video_id,
            "title": title,
            "url": f"https://youtu.be/{video_id}",
            "thumbnail": thumbnail,
            "type": vtype
        }

    # -------------------------
    # LOOP
    # -------------------------
    @tasks.loop(seconds=CHECK_INTERVAL)
    async def check_videos(self):
        if not YOUTUBE_API_KEY:
            print("❌ YOUTUBE_API_KEY missing")
            return

        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute("SELECT * FROM youtube_alerts")
            rows = await cursor.fetchall()

        for row in rows:
            guild_id, yt_channel, discord_channel_id, role_ping, message, last_video = row

            try:
                data = await self.fetch_latest_video(yt_channel)
                if not data:
                    continue

                if data["video_id"] == last_video:
                    continue

                guild = self.bot.get_guild(guild_id)
                if not guild:
                    continue

                channel = guild.get_channel(discord_channel_id)
                if not channel:
                    continue

                role_text = f"<@&{role_ping}>\n" if role_ping else ""

                embed = discord.Embed(
                    title=f"{data['type']} Alert",
                    description=data["title"],
                    color=discord.Color.red()
                )
                embed.set_image(url=data["thumbnail"])
                embed.add_field(name="Watch", value=data["url"])

                text = (
                    message.replace("{title}", data["title"])
                    .replace("{url}", data["url"])
                    .replace("{type}", data["type"])
                )

                await channel.send(content=role_text + text, embed=embed)

                async with aiosqlite.connect(DB_NAME) as db:
                    await db.execute(
                        "UPDATE youtube_alerts SET last_video=? WHERE guild_id=? AND youtube_channel=?",
                        (data["video_id"], guild_id, yt_channel)
                    )
                    await db.commit()

            except Exception as e:
                print("❌ YouTube loop error:", e)

    @check_videos.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()


# =========================
# SETUP
# =========================
async def setup(bot: commands.Bot):
    await bot.add_cog(YouTube(bot))
