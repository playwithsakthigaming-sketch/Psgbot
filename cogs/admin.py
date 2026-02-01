import discord
from discord.ext import commands, tasks
from discord import app_commands
import datetime
import aiosqlite
import os
import sys
import time

DB_NAME = "bot.db"
START_TIME = time.time()


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.status_index = 0
        self.status_list = [
            discord.Game(name="Watching moderation and activity"),
            discord.Activity(type=discord.ActivityType.watching, name="premium member security"),
            discord.Game(name="Playing Play With Sakthi Gaming")
        ]

    # ========================
    # BOT READY
    # ========================
    @commands.Cog.listener()
    async def on_ready(self):
        if not self.status_loop.is_running():
            self.status_loop.start()
            print("✅ Status rotation started")

    # ========================
    # STATUS LOOP
    # ========================
    @tasks.loop(seconds=10)
    async def status_loop(self):
        activity = self.status_list[self.status_index]
        await self.bot.change_presence(activity=activity)
        self.status_index = (self.status_index + 1) % len(self.status_list)

    @status_loop.before_loop
    async def before_status_loop(self):
        await self.bot.wait_until_ready()

    # ========================
    # /ping
    # ========================
    @app_commands.command(name="ping", description="🏓 Check bot latency")
    async def ping(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"🏓 Pong! `{latency}ms`", ephemeral=True)

    # ========================
    # /botinfo
    # ========================
    @app_commands.command(name="botinfo", description="🤖 Show bot information")
    async def botinfo(self, interaction: discord.Interaction):
        uptime = int(time.time() - START_TIME)

        embed = discord.Embed(
            title="🤖 Bot Info",
            color=discord.Color.gold(),
            timestamp=datetime.datetime.utcnow()
        )

        embed.add_field(name="Servers", value=len(self.bot.guilds), inline=True)
        embed.add_field(name="Users", value=len(self.bot.users), inline=True)
        embed.add_field(name="Latency", value=f"{round(self.bot.latency*1000)}ms", inline=True)
        embed.add_field(name="Uptime", value=f"{uptime//3600}h {(uptime%3600)//60}m", inline=True)

        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    # ========================
    # /serverstatus
    # ========================
    @app_commands.command(name="serverstatus", description="📊 Show server status")
    async def serverstatus(self, interaction: discord.Interaction):
        guild = interaction.guild
        online = sum(m.status != discord.Status.offline for m in guild.members)

        embed = discord.Embed(
            title="📊 Server Status",
            color=discord.Color.green(),
            timestamp=datetime.datetime.utcnow()
        )

        embed.add_field(name="Server", value=guild.name, inline=False)
        embed.add_field(name="Members", value=guild.member_count, inline=True)
        embed.add_field(name="Online", value=online, inline=True)
        embed.add_field(name="Channels", value=len(guild.channels), inline=True)
        embed.add_field(name="Roles", value=len(guild.roles), inline=True)
        embed.add_field(name="Boost Level", value=guild.premium_tier, inline=True)

        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        await interaction.response.send_message(embed=embed)

    # ========================
    # /playerinfo
    # ========================
    @app_commands.command(name="playerinfo", description="👤 Show user information")
    async def playerinfo(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user

        premium_status = "❌ No"
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute("SELECT tier FROM premium WHERE user_id=?", (member.id,))
            row = await cursor.fetchone()
            if row:
                premium_status = f"✅ {row[0].capitalize()}"

        embed = discord.Embed(
            title="👤 Player Info",
            color=discord.Color.blue(),
            timestamp=datetime.datetime.utcnow()
        )

        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Username", value=member.name, inline=True)
        embed.add_field(name="User ID", value=member.id, inline=True)
        embed.add_field(name="Premium", value=premium_status, inline=True)
        embed.add_field(name="Joined Server", value=member.joined_at.strftime("%d-%m-%Y"), inline=False)
        embed.add_field(name="Account Created", value=member.created_at.strftime("%d-%m-%Y"), inline=False)
        embed.add_field(name="Top Role", value=member.top_role.mention, inline=False)

        await interaction.response.send_message(embed=embed)

    # ========================
    # /setstatus
    # ========================
    @app_commands.command(name="setstatus", description="🤖 Set bot activity manually")
    @app_commands.checks.has_permissions(administrator=True)
    async def setstatus(self, interaction: discord.Interaction, mode: str, text: str):
        await interaction.response.defer(ephemeral=True)

        mode = mode.lower()
        if mode == "playing":
            activity = discord.Game(name=text)
        elif mode == "watching":
            activity = discord.Activity(type=discord.ActivityType.watching, name=text)
        elif mode == "listening":
            activity = discord.Activity(type=discord.ActivityType.listening, name=text)
        else:
            return await interaction.followup.send("❌ Mode must be: playing / watching / listening", ephemeral=True)

        await self.bot.change_presence(activity=activity)
        await interaction.followup.send(f"✅ Bot status updated to **{mode} {text}**", ephemeral=True)

    # ========================
    # /restart
    # ========================
    @app_commands.command(name="restart", description="♻ Restart the bot")
    @app_commands.checks.has_permissions(administrator=True)
    async def restart(self, interaction: discord.Interaction):
        await interaction.response.send_message("♻ Restarting bot...", ephemeral=True)
        os.execv(sys.executable, ["python"] + sys.argv)

    # ========================
    # /dm
    # ========================
    @app_commands.command(name="dm", description="✉ Send DM to a user")
    @app_commands.checks.has_permissions(administrator=True)
    async def dm(self, interaction: discord.Interaction, member: discord.Member, message: str):
        try:
            await member.send(message)
            await interaction.response.send_message("✅ DM sent", ephemeral=True)
        except:
            await interaction.response.send_message("❌ Could not send DM", ephemeral=True)

    # ========================
    # /dmall
    # ========================
    @app_commands.command(name="dmall", description="📢 DM all server members")
    @app_commands.checks.has_permissions(administrator=True)
    async def dmall(self, interaction: discord.Interaction, message: str):
        await interaction.response.defer(ephemeral=True)
        count = 0
        for member in interaction.guild.members:
            if not member.bot:
                try:
                    await member.send(message)
                    count += 1
                except:
                    pass
        await interaction.followup.send(f"✅ Sent DM to {count} members", ephemeral=True)

    # ========================
    # /addemoji
    # ========================
    @app_commands.command(name="addemoji", description="😀 Upload an emoji to the server")
    @app_commands.checks.has_permissions(manage_emojis=True)
    async def addemoji(self, interaction: discord.Interaction, name: str, emoji: discord.Attachment):
        await interaction.response.defer(ephemeral=True)

        if not emoji.content_type.startswith("image"):
            return await interaction.followup.send("❌ Please upload a valid image (PNG/JPG/GIF)", ephemeral=True)

        try:
            image_bytes = await emoji.read()

            new_emoji = await interaction.guild.create_custom_emoji(
                name=name,
                image=image_bytes
            )

            await interaction.followup.send(
                f"✅ Emoji uploaded successfully! {new_emoji}",
                ephemeral=True
            )

        except discord.Forbidden:
            await interaction.followup.send("❌ I don't have permission to manage emojis.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to upload emoji: {e}", ephemeral=True)

    # ========================
    # CHANNEL MANAGEMENT
    # ========================
    @app_commands.command(name="create_channel", description="➕ Create a new channel")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def create_channel(self, interaction: discord.Interaction, name: str, channel_type: str):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        channel_type = channel_type.lower()

        if channel_type == "text":
            channel = await guild.create_text_channel(name)
        elif channel_type == "voice":
            channel = await guild.create_voice_channel(name)
        elif channel_type == "forum":
            channel = await guild.create_forum_channel(name)
        elif channel_type == "stage":
            channel = await guild.create_stage_channel(name)
        else:
            return await interaction.followup.send("❌ channel_type must be: text / voice / forum / stage", ephemeral=True)

        await interaction.followup.send(f"✅ Channel created: {channel.mention}", ephemeral=True)

    @app_commands.command(name="delete_channel", description="🗑 Delete a channel")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def delete_channel(self, interaction: discord.Interaction, channel: discord.abc.GuildChannel):
        await interaction.response.defer(ephemeral=True)
        await channel.delete()
        await interaction.followup.send("✅ Channel deleted", ephemeral=True)

    # ========================
    # CLEAR CHAT
    # ========================
    @app_commands.command(name="clear_chat", description="🧹 Clear messages")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear_chat(self, interaction: discord.Interaction, amount: int):
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"🧹 Deleted {len(deleted)} messages", ephemeral=True)


# ========================
# SETUP
# ========================
async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))
