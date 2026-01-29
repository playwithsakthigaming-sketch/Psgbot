import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
import aiosqlite
import os

DB_NAME = "bot.db"
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

CHECK_INTERVAL = 120  # seconds

# =========================
# YOUTUBE COG
# =========================
class YouTube(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # =========================
    # START LOOP AFTER READY
    # =========================
    @commands.Cog.listener()
    async def on_ready(self):
        if not self.check_videos.is_running():
            self.check_videos.start()
            print("✅ YouTube alert loop started")

    # =========================
    # SETUP CHANNEL
    # =========================
    @app_commands.command(name="setup_channel", description="Add YouTube alert channel")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_channel(
        self,
        interaction: discord.Interaction,
        youtube_channel: str,
        discord_channel: discord.TextChannel,
        role: discord.Role = None,
        message: str = "📢 New video!\n{title}\n{url}"
    ):
        await interaction.response.defer(ephemeral=True)

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("""
            INSERT OR REPLACE INTO youtube_alerts
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

        await interaction.followup.send("✅ YouTube channel added successfully!")

    # =========================
    # REMOVE CHANNEL
    # =========================
    @app_commands.command(name="remove_channel", description="Remove YouTube alert channel")
    @app_commands.checks.has_permissions(administrator=True)
    async def remove_channel(self, interaction: discord.Interaction, youtube_channel: str):
        await interaction.response.defer(ephemeral=True)

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "DELETE FROM youtube_alerts WHERE guild_id=? AND youtube_channel=?",
                (interaction.guild.id, youtube_channel)
            )
            await db.commit()

        await interaction.followup.send("✅ Channel removed")

    # =========================
    # LIST CHANNELS
    # =========================
    @app_commands.command(name="list_channels", description="List YouTube alert channels")
    async def list_channels(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute(
                "SELECT youtube_channel FROM youtube_alerts WHERE guild_id=?",
                (interaction.guild.id,)
            )
            rows = await cursor.fetchall()

        if not rows:
            return await interaction.followup.send("❌ No YouTube channels added")

        text = "\n".join(f"• {r[0]}" for r in rows)
        await interaction.followup.send(f"📺 **Tracked Channels:**\n{text}")

    # =========================
    # TEST COMMAND
    # =========================
    @app_commands.command(name="youtube_test", description="Test YouTube system")
    async def youtube_test(self, interaction: discord.Interaction):
        await interaction.response.send_message("✅ YouTube system running!", ephemeral=True)

    # =========================
    # FETCH LATEST VIDEO
    # =========================
    async def fetch_latest_video(self, channel_id: str):
        url = (
            "https://www.googleapis.com/youtube/v3/search"
            f"?part=snippet&channelId={channel_id}"
            f"&maxResults=1&order=date&type=video&key={YOUTUBE_API_KEY}"
        )

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()

        if "items" not in data or not data["items"]:
            return None

        item = data["items"][0]
        video_id = item["id"]["videoId"]
        title = item["snippet"]["title"]
        thumbnail = item["snippet"]["thumbnails"]["high"]["url"]

        # Detect Shorts
        is_shorts = "#shorts" in title.lower()

        return {
            "video_id": video_id,
            "title": title,
            "url": f"https://youtu.be/{video_id}",
            "thumbnail": thumbnail,
            "shorts": is_shorts
        }

    # =========================
    # LOOP CHECK
    # =========================
    @tasks.loop(seconds=CHECK_INTERVAL)
    async def check_videos(self):
        if not YOUTUBE_API_KEY:
            print("❌ YOUTUBE_API_KEY missing")
            return

        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute("SELECT * FROM youtube_alerts")
            rows = await cursor.fetchall()

        for row in rows:
            guild_id, channel_id, discord_channel_id, role_ping, message, last_video = row

            data = await self.fetch_latest_video(channel_id)
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
                title="📺 New YouTube Video",
                description=data["title"],
                color=discord.Color.red()
            )
            embed.set_image(url=data["thumbnail"])
            embed.add_field(name="Watch", value=data["url"])

            text = message.replace("{title}", data["title"]).replace("{url}", data["url"])

            await channel.send(content=role_text + text, embed=embed)

            async with aiosqlite.connect(DB_NAME) as db:
                await db.execute(
                    "UPDATE youtube_alerts SET last_video=? WHERE guild_id=? AND youtube_channel=?",
                    (data["video_id"], guild_id, channel_id)
                )
                await db.commit()

    @check_videos.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()


# =========================
# SETUP
# =========================
async def setup(bot: commands.Bot):
    await bot.add_cog(YouTube(bot))
