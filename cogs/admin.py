import discord
from discord.ext import commands, tasks
from discord import app_commands
import datetime
import aiosqlite
import os
import sys
import time
import aiohttp

DB_NAME = "bot.db"
START_TIME = time.time()


# ========================
# SERVER STATUS VIEW (Buttons)
# ========================
class ServerStatusView(discord.ui.View):
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=300)
        self.guild = guild

    def get_embed(self):
        online = sum(m.status != discord.Status.offline for m in self.guild.members)

        embed = discord.Embed(
            title="📊 Server Status",
            color=discord.Color.green(),
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="Server", value=self.guild.name, inline=False)
        embed.add_field(name="Members", value=self.guild.member_count, inline=True)
        embed.add_field(name="Online", value=online, inline=True)
        embed.add_field(name="Channels", value=len(self.guild.channels), inline=True)
        embed.add_field(name="Roles", value=len(self.guild.roles), inline=True)
        embed.add_field(name="Boost Level", value=self.guild.premium_tier, inline=True)

        if self.guild.icon:
            embed.set_thumbnail(url=self.guild.icon.url)

        return embed

    # 🔄 Refresh Button
    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.green, emoji="🔄")
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = self.get_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    # 🗑 Remove Button
    @discord.ui.button(label="Remove", style=discord.ButtonStyle.red, emoji="🗑")
    async def remove(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.message.delete()


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
    # /serverstatus (WITH BUTTONS)
    # ========================
    @app_commands.command(name="serverstatus", description="📊 Show server status with buttons")
    async def serverstatus(self, interaction: discord.Interaction):
        view = ServerStatusView(interaction.guild)
        embed = view.get_embed()
        await interaction.response.send_message(embed=embed, view=view)

    # ========================
    # /restart
    # ========================
    @app_commands.command(name="restart", description="♻ Restart the bot")
    @app_commands.checks.has_permissions(administrator=True)
    async def restart(self, interaction: discord.Interaction):
        await interaction.response.send_message("♻ Restarting bot...", ephemeral=True)
        os.execv(sys.executable, ["python"] + sys.argv)

    # ========================
    # /addemoji (FIXED - no timeout error)
    # ========================
    @app_commands.command(name="addemoji", description="😀 Add emoji using file, text or URL")
    @app_commands.checks.has_permissions(manage_emojis=True)
    async def addemoji(
        self,
        interaction: discord.Interaction,
        name: str,
        file: discord.Attachment = None,
        text: str = None,
        url: str = None
    ):
        await interaction.response.defer(ephemeral=True)

        if not file and not text and not url:
            return await interaction.followup.send(
                "❌ Please provide one of: **file / text / url**",
                ephemeral=True
            )

        image_bytes = None

        try:
            # ✅ From attachment file (PNG/JPG/GIF)
            if file:
                if not file.content_type or not file.content_type.startswith("image"):
                    return await interaction.followup.send(
                        "❌ File must be an image (PNG/JPG/GIF)",
                        ephemeral=True
                    )
                image_bytes = await file.read()

            # ✅ From custom emoji text
            elif text:
                if text.startswith("<") and text.endswith(">"):
                    emoji = await commands.EmojiConverter().convert(interaction, text)
                    image_bytes = await emoji.read()
                else:
                    return await interaction.followup.send(
                        "❌ Text must be custom emoji like <:name:id> or <a:name:id>",
                        ephemeral=True
                    )

            # ✅ From image URL
            elif url:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as resp:
                        if resp.status != 200:
                            return await interaction.followup.send(
                                "❌ Invalid image URL",
                                ephemeral=True
                            )
                        image_bytes = await resp.read()

            # ✅ Create emoji (supports GIF)
            new_emoji = await interaction.guild.create_custom_emoji(
                name=name,
                image=image_bytes,
                reason=f"Added by {interaction.user}"
            )

            await interaction.followup.send(
                f"✅ Emoji added successfully! {new_emoji}",
                ephemeral=True
            )

        except discord.Forbidden:
            await interaction.followup.send(
                "❌ I don't have permission to manage emojis.",
                ephemeral=True
            )
        except discord.HTTPException as e:
            await interaction.followup.send(
                f"❌ Discord error: {e}",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(
                f"❌ Failed to add emoji: {e}",
                ephemeral=True
            )

    # ========================
    # CLEAR CHAT
    # ========================
    @app_commands.command(name="clear_chat", description="🧹 Clear messages")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear_chat(self, interaction: discord.Interaction, amount: int):
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(
            f"🧹 Deleted {len(deleted)} messages",
            ephemeral=True
        )


# ========================
# SETUP
# ========================
async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))
