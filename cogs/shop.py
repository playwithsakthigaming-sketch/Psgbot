import discord, aiosqlite, time, asyncio
from discord.ext import commands
from discord import app_commands

DB_NAME = "bot.db"


# ================= PRODUCT CARD =================
def product_embed(item_id, name, price, stock, image_url, category):
    embed = discord.Embed(
        title=name,
        description=(
            f"📦 **Category:** {category}\n"
            f"💰 **Price:** {price} coins\n"
            f"📊 **Stock:** {stock}\n\n"
            "Click **BUY** to fill the purchase form and receive your link in DM."
        ),
        color=discord.Color.purple()
    )
    if image_url:
        embed.set_image(url=image_url)
    embed.set_footer(text=f"Item ID: {item_id}")
    return embed


# ================= BUY MODAL =================
class BuyModal(discord.ui.Modal, title="🛒 Purchase Form"):
    customer_name = discord.ui.TextInput(
        label="Your Name",
        required=True
    )

    email = discord.ui.TextInput(
        label="Your Email",
        required=True
    )

    coupon = discord.ui.TextInput(
        label="Coupon Code (optional)",
        required=False
    )

    def __init__(self, item_id):
        super().__init__()
        self.item_id = item_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        async with aiosqlite.connect(DB_NAME) as db:

            # Get item info
            cur = await db.execute("""
            SELECT shop_items.name, shop_items.price, shop_items.stock,
                   shop_items.product_link
            FROM shop_items
            WHERE shop_items.id=?
            """, (self.item_id,))
            item = await cur.fetchone()

            if not item:
                return await interaction.followup.send("❌ Item not found.")

            name, price, stock, link = item

            if stock <= 0:
                return await interaction.followup.send("❌ Out of stock.")

            # Get balance
            cur = await db.execute(
                "SELECT balance FROM coins WHERE user_id=?",
                (interaction.user.id,)
            )
            row = await cur.fetchone()
            balance = row[0] if row else 0

            if balance < price:
                return await interaction.followup.send("❌ Not enough coins.")

            # Deduct coins
            await db.execute(
                "UPDATE coins SET balance = balance - ? WHERE user_id=?",
                (price, interaction.user.id)
            )

            # Reduce stock
            await db.execute(
                "UPDATE shop_items SET stock = stock - 1 WHERE id=?",
                (self.item_id,)
            )

            # Save order
            await db.execute("""
            INSERT INTO orders (user_id, item_name, total, timestamp)
            VALUES (?,?,?,?)
            """, (interaction.user.id, name, price, int(time.time())))

            await db.commit()

        # Send DM and auto delete after 10 minutes
        try:
            dm_msg = await interaction.user.send(
                f"🎉 **Purchase Successful!**\n\n"
                f"👤 Name: {self.customer_name.value}\n"
                f"📧 Email: {self.email.value}\n"
                f"🎟 Coupon: {self.coupon.value or 'None'}\n\n"
                f"📦 Product: **{name}**\n"
                f"💰 Price: {price} coins\n\n"
                f"🔗 **Your Link (auto deletes in 10 minutes):**\n{link}"
            )

            await asyncio.sleep(600)  # 10 minutes
            await dm_msg.delete()

            dm_status = "📩 Link sent to your DM (auto deleted in 10 min)."

        except:
            dm_status = "⚠️ I couldn't DM you. Enable DMs."

        await interaction.followup.send(
            f"✅ Purchase complete!\n{dm_status}",
            ephemeral=True
        )


# ================= BUY BUTTON VIEW =================
class BuyView(discord.ui.View):
    def __init__(self, item_id):
        super().__init__(timeout=None)
        self.item_id = item_id

    @discord.ui.button(label="🛒 BUY", style=discord.ButtonStyle.success)
    async def buy(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BuyModal(self.item_id))


# ================= SHOP COG =================
class Shop(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


    # -------- ADD CATEGORY --------
    @app_commands.command(name="add_category")
    @app_commands.checks.has_permissions(administrator=True)
    async def add_category(self, interaction: discord.Interaction, name: str):
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "INSERT OR IGNORE INTO shop_categories(name) VALUES(?)",
                (name,)
            )
            await db.commit()

        await interaction.response.send_message(
            f"✅ Category `{name}` added", ephemeral=True
        )


    # -------- ADD PRODUCT --------
    @app_commands.command(name="add_product")
    @app_commands.checks.has_permissions(administrator=True)
    async def add_product(
        self,
        interaction: discord.Interaction,
        name: str,
        price: int,
        stock: int,
        image_url: str,
        category: str,
        product_link: str
    ):
        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute(
                "SELECT id FROM shop_categories WHERE name=?",
                (category,)
            )
            row = await cur.fetchone()

            if not row:
                return await interaction.response.send_message(
                    "❌ Category not found", ephemeral=True
                )

            category_id = row[0]

            await db.execute("""
            INSERT INTO shop_items (name, price, stock, image_url, category_id, product_link)
            VALUES (?,?,?,?,?,?)
            """, (name, price, stock, image_url, category_id, product_link))

            await db.commit()

        await interaction.response.send_message(
            f"✅ Product `{name}` added", ephemeral=True
        )


    # -------- RESTOCK PRODUCT --------
    @app_commands.command(name="restock", description="Admin restock product")
    @app_commands.checks.has_permissions(administrator=True)
    async def restock(self, interaction: discord.Interaction, item_id: int, amount: int):
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "UPDATE shop_items SET stock = stock + ? WHERE id=?",
                (amount, item_id)
            )
            await db.commit()

        await interaction.response.send_message(
            f"✅ Item `{item_id}` restocked by {amount}",
            ephemeral=True
        )


    # -------- SHOW SHOP --------
    @app_commands.command(name="shop")
    async def shop(self, interaction: discord.Interaction):

        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute("""
            SELECT shop_items.id, shop_items.name, shop_items.price,
                   shop_items.stock, shop_items.image_url,
                   shop_categories.name
            FROM shop_items
            JOIN shop_categories ON shop_items.category_id = shop_categories.id
            """)
            items = await cur.fetchall()

        if not items:
            return await interaction.response.send_message("🛒 Shop is empty")

        for item_id, name, price, stock, image_url, category in items:
            embed = product_embed(item_id, name, price, stock, image_url, category)
            await interaction.channel.send(embed=embed, view=BuyView(item_id))

        await interaction.response.send_message("🛒 Shop loaded!", ephemeral=True)


    # -------- USER ORDER HISTORY --------
    @app_commands.command(name="order_history")
    async def order_history(self, interaction: discord.Interaction):

        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute(
                "SELECT item_name, total, timestamp FROM orders WHERE user_id=?",
                (interaction.user.id,)
            )
            rows = await cur.fetchall()

        if not rows:
            return await interaction.response.send_message(
                "📦 No orders yet", ephemeral=True
            )

        embed = discord.Embed(title="📜 Your Order History")

        for name, total, ts in rows:
            embed.add_field(
                name=name,
                value=f"💰 {total} coins\n🕒 <t:{ts}:R>",
                inline=False
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)


    # -------- ADMIN ALL ORDERS --------
    @app_commands.command(name="all_orders", description="Admin view all orders")
    @app_commands.checks.has_permissions(administrator=True)
    async def all_orders(self, interaction: discord.Interaction):

        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute(
                "SELECT user_id, item_name, total, timestamp FROM orders"
            )
            rows = await cur.fetchall()

        if not rows:
            return await interaction.response.send_message("No orders yet.", ephemeral=True)

        embed = discord.Embed(title="📦 All Orders")

        for user_id, name, total, ts in rows:
            embed.add_field(
                name=f"{name}",
                value=f"👤 <@{user_id}>\n💰 {total} coins\n🕒 <t:{ts}:R>",
                inline=False
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)


# ================= SETUP =================
async def setup(bot: commands.Bot):
    await bot.add_cog(Shop(bot))
