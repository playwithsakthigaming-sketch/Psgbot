import discord
import aiosqlite
import os
import aiohttp
from discord.ext import commands, tasks
from discord import app_commands

DB_NAME = "bot.db"
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

CHECK_INTERVAL = 2  # minutes

# ================= DATABASE =================
async def setup_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS youtube_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            youtube_channel TEXT,
            discord_channel INTEGER,
            role_ping INTEGER,
            message TEXT,
            last_video TEXT
        )
        """)
        await db.commit()


# ================= COG =================
class YouTube(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_videos.start()

    # ---------------- SETUP ----------------
    @app_commands.command(name="setup_channel", description="Add YouTube alert channel")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_channel(
        self,
        interaction: discord.Interaction,
        youtube_channel: str,
        discord_channel: discord.TextChannel,
        role: discord.Role = None,
        message: str = "🔴 {title}\n{url}"
    ):
        await interaction.response.defer(ephemeral=True)

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("""
            INSERT INTO youtube_alerts
            (guild_id, youtube_channel, discord_channel, role_ping, message, last_video)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (
                interaction.guild.id,
                youtube_channel,
                discord_channel.id,
                role.id if role else None,
                message,
                None
            ))
            await db.commit()

        await interaction.followup.send("✅ YouTube channel added!")

    # ---------------- REMOVE ----------------
    @app_commands.command(name="remove_channel", description="Remove YouTube alert")
    @app_commands.checks.has_permissions(administrator=True)
    async def remove_channel(self, interaction: discord.Interaction, youtube_channel: str):
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "DELETE FROM youtube_alerts WHERE youtube_channel=? AND guild_id=?",
                (youtube_channel, interaction.guild.id)
            )
            await db.commit()

        await interaction.response.send_message("✅ Channel removed", ephemeral=True)

    # ---------------- LIST ----------------
    @app_commands.command(name="list_channels", description="List YouTube alerts")
    async def list_channels(self, interaction: discord.Interaction):
        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute(
                "SELECT youtube_channel FROM youtube_alerts WHERE guild_id=?",
                (interaction.guild.id,)
            )
            rows = await cur.fetchall()

        if not rows:
            return await interaction.response.send_message("No channels set")

        text = "\n".join([f"• {r[0]}" for r in rows])
        await interaction.response.send_message(f"📺 Tracked Channels:\n{text}")

    # ---------------- TEST ----------------
    @app_commands.command(name="youtube_test", description="Test YouTube API")
    async def youtube_test(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send("✅ YouTube system running")

    # ---------------- CHECK LOOP ----------------
    @tasks.loop(minutes=CHECK_INTERVAL)
    async def check_videos(self):
        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute("SELECT * FROM youtube_alerts")
            rows = await cur.fetchall()

        for row in rows:
            (
                id,
                guild_id,
                channel_id,
                discord_channel_id,
                role_ping,
                custom_msg,
                last_video
            ) = row

            video = await self.fetch_latest_video(channel_id)
            if not video:
                continue

            video_id = video["id"]
            title = video["title"]
            url = video["url"]
            live = video["live"]

            if last_video == video_id:
                continue

            guild = self.bot.get_guild(guild_id)
            if not guild:
                continue

            channel = guild.get_channel(discord_channel_id)
            if not channel:
                continue

            role_text = f"<@&{role_ping}>" if role_ping else ""

            text = custom_msg.replace("{title}", title).replace("{url}", url)

            embed = discord.Embed(
                title="🔴 LIVE NOW!" if live else "📺 New Video",
                description=text,
                color=discord.Color.red() if live else discord.Color.blue()
            )

            await channel.send(content=role_text, embed=embed)

            async with aiosqlite.connect(DB_NAME) as db:
                await db.execute(
                    "UPDATE youtube_alerts SET last_video=? WHERE id=?",
                    (video_id, id)
                )
                await db.commit()

    # ---------------- FETCH VIDEO ----------------
    async def fetch_latest_video(self, channel_id):
        url = (
            f"https://www.googleapis.com/youtube/v3/search"
            f"?part=snippet&channelId={channel_id}"
            f"&order=date&maxResults=1&key={YOUTUBE_API_KEY}"
        )

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()

        if "items" not in data or not data["items"]:
            return None

        item = data["items"][0]
        video_id = item["id"].get("videoId")
        if not video_id:
            return None

        live = item["snippet"]["liveBroadcastContent"] == "live"

        return {
            "id": video_id,
            "title": item["snippet"]["title"],
            "url": f"https://youtu.be/{video_id}",
            "live": live
        }

    @check_videos.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()
        await setup_db()


async def setup(bot: commands.Bot):
    await bot.add_cog(YouTube(bot))
