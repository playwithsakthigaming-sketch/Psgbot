import discord, aiosqlite, time
from discord.ext import commands
from discord import app_commands

DB_NAME = "bot.db"

# ================= EMBED CARD =================
def product_embed(item_id, name, price, stock, image_url, category):
    embed = discord.Embed(
        title=name,
        description=(
            f"📦 **Category:** {category}\n"
            f"💰 **Price:** `{price} coins`\n"
            f"📊 **Stock:** `{stock}`\n\n"
            f"Click **ADD** to put this item in your cart."
        ),
        color=discord.Color.dark_purple()
    )
    embed.set_image(url=image_url)
    embed.set_footer(text=f"Item ID: {item_id}")
    return embed


# ================= ADD BUTTON =================
class AddToCartView(discord.ui.View):
    def __init__(self, item_id):
        super().__init__(timeout=None)
        self.item_id = item_id

    @discord.ui.button(label="🛒 ADD", style=discord.ButtonStyle.success)
    async def add(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("""
            INSERT INTO carts (user_id, item_id, quantity)
            VALUES (?, ?, 1)
            """, (interaction.user.id, self.item_id))
            await db.commit()

        await interaction.response.send_message(
            "✅ Added to your cart!", ephemeral=True
        )


# ================= SHOP COG =================
class Shop(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


    # ---------------- ADD CATEGORY ----------------
    @app_commands.command(name="add_category")
    @app_commands.checks.has_permissions(administrator=True)
    async def add_category(self, interaction: discord.Interaction, name: str):
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("INSERT OR IGNORE INTO shop_categories(name) VALUES(?)", (name,))
            await db.commit()

        await interaction.response.send_message("✅ Category added", ephemeral=True)


    # ---------------- ADD PRODUCT ----------------
    @app_commands.command(name="add_product")
    @app_commands.checks.has_permissions(administrator=True)
    async def add_product(
        self,
        interaction: discord.Interaction,
        name: str,
        price: int,
        stock: int,
        image_url: str,
        category: str
    ):
        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute("SELECT id FROM shop_categories WHERE name=?", (category,))
            row = await cur.fetchone()
            if not row:
                return await interaction.response.send_message("❌ Category not found", ephemeral=True)

            cat_id = row[0]
            await db.execute("""
            INSERT INTO shop_items (name, price, stock, image_url, category_id)
            VALUES (?,?,?,?,?)
            """, (name, price, stock, image_url, cat_id))
            await db.commit()

        await interaction.response.send_message("✅ Product added", ephemeral=True)


    # ---------------- SHOW SHOP ----------------
    @app_commands.command(name="shop")
    async def shop(self, interaction: discord.Interaction):
        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute("""
            SELECT shop_items.id, shop_items.name, shop_items.price,
                   shop_items.stock, shop_items.image_url, shop_categories.name
            FROM shop_items
            JOIN shop_categories ON shop_items.category_id = shop_categories.id
            """)
            items = await cur.fetchall()

        if not items:
            return await interaction.response.send_message("🛒 Shop is empty")

        for item in items:
            item_id, name, price, stock, image_url, category = item
            embed = product_embed(item_id, name, price, stock, image_url, category)
            view = AddToCartView(item_id)
            await interaction.channel.send(embed=embed, view=view)

        await interaction.response.send_message("✅ Shop loaded", ephemeral=True)


    # ---------------- VIEW CART ----------------
    @app_commands.command(name="cart")
    async def cart(self, interaction: discord.Interaction):
        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute("""
            SELECT shop_items.name, shop_items.price, carts.quantity
            FROM carts
            JOIN shop_items ON carts.item_id = shop_items.id
            WHERE carts.user_id=?
            """, (interaction.user.id,))
            items = await cur.fetchall()

        if not items:
            return await interaction.response.send_message("🛒 Your cart is empty")

        total = 0
        msg = ""
        for name, price, qty in items:
            subtotal = price * qty
            total += subtotal
            msg += f"**{name}** x{qty} = `{subtotal} coins`\n"

        embed = discord.Embed(
            title="🛒 Your Cart",
            description=msg + f"\n💰 **Total: {total} coins**",
            color=discord.Color.gold()
        )

        await interaction.response.send_message(embed=embed)


    # ---------------- CHECKOUT ----------------
    @app_commands.command(name="checkout")
    async def checkout(self, interaction: discord.Interaction):
        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute("""
            SELECT shop_items.id, shop_items.price, carts.quantity
            FROM carts
            JOIN shop_items ON carts.item_id = shop_items.id
            WHERE carts.user_id=?
            """, (interaction.user.id,))
            items = await cur.fetchall()

            if not items:
                return await interaction.response.send_message("❌ Cart empty")

            total = sum(price * qty for _, price, qty in items)

            cur = await db.execute("SELECT balance FROM coins WHERE user_id=?", (interaction.user.id,))
            bal = await cur.fetchone()
            if not bal or bal[0] < total:
                return await interaction.response.send_message("❌ Not enough coins")

            await db.execute("UPDATE coins SET balance = balance - ? WHERE user_id=?", (total, interaction.user.id))

            for item_id, price, qty in items:
                await db.execute("UPDATE shop_items SET stock = stock - ? WHERE id=?", (qty, item_id))

            await db.execute("DELETE FROM carts WHERE user_id=?", (interaction.user.id,))
            await db.execute("INSERT INTO orders(user_id,total,timestamp) VALUES(?,?,?)",
                             (interaction.user.id, total, int(time.time())))

            await db.commit()

        await interaction.response.send_message("✅ Order successful!")


    # ---------------- ORDER HISTORY ----------------
    @app_commands.command(name="order_history")
    async def order_history(self, interaction: discord.Interaction):
        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute("""
            SELECT total, timestamp FROM orders WHERE user_id=?
            """, (interaction.user.id,))
            rows = await cur.fetchall()

        if not rows:
            return await interaction.response.send_message("No orders yet")

        msg = ""
        for total, ts in rows:
            msg += f"💰 `{total} coins` | 🕒 <t:{ts}:R>\n"

        embed = discord.Embed(title="📜 Order History", description=msg, color=discord.Color.blue())
        await interaction.response.send_message(embed=embed)


# ================= SETUP =================
async def setup(bot: commands.Bot):
    await bot.add_cog(Shop(bot))
