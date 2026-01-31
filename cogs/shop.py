import discord, aiosqlite, time, asyncio
from discord.ext import commands
from discord import app_commands

DB_NAME = "bot.db"


# ================= PRODUCT EMBED =================
def product_embed(guild, item_id, name, price, stock, image_url, category):
    color = discord.Color.red() if stock <= 0 else discord.Color.green()

    desc = (
        f"📦 **Category:** {category}\n"
        f"💰 **Price:** {price} coins\n"
        f"📊 **Stock:** {stock}\n\n"
    )

    if stock <= 0:
        desc += "❌ **OUT OF STOCK**"
    else:
        desc += "Click **Confirm Payment** to continue purchase."

    embed = discord.Embed(title=name, description=desc, color=color)

    if image_url:
        embed.set_image(url=image_url)

    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    embed.set_footer(text=f"Item ID: {item_id}")
    return embed


# ================= BUY MODAL =================
class BuyModal(discord.ui.Modal, title="🛒 Purchase Form"):
    customer_name = discord.ui.TextInput(label="Your Name", required=True)
    email = discord.ui.TextInput(label="Your Email", required=True)
    coupon = discord.ui.TextInput(label="Coupon Code (optional)", required=False)

    def __init__(self, item_id):
        super().__init__()
        self.item_id = item_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        async with aiosqlite.connect(DB_NAME) as db:

            # Get product
            cur = await db.execute(
                "SELECT name, price, stock, product_link FROM shop_items WHERE id=?",
                (self.item_id,)
            )
            item = await cur.fetchone()

            if not item:
                return await interaction.followup.send("❌ Item not found.")

            name, price, stock, link = item

            if stock <= 0:
                return await interaction.followup.send("❌ Out of stock.")

            final_price = price
            coupon_code = self.coupon.value.strip().upper()

            # ===== COUPON VALIDATION =====
            if coupon_code:
                cur = await db.execute(
                    "SELECT discount, expires FROM coupons WHERE code=?",
                    (coupon_code,)
                )
                coupon = await cur.fetchone()

                if not coupon:
                    return await interaction.followup.send("❌ Invalid coupon code.")

                discount, expires = coupon

                if expires < int(time.time()):
                    return await interaction.followup.send("❌ Coupon expired.")

                discount_amount = int(price * (discount / 100))
                final_price = price - discount_amount

            # Get balance
            cur = await db.execute(
                "SELECT balance FROM coins WHERE user_id=?",
                (interaction.user.id,)
            )
            row = await cur.fetchone()
            balance = row[0] if row else 0

            if balance < final_price:
                return await interaction.followup.send(
                    f"❌ Not enough coins. Need {final_price} coins."
                )

            # Deduct coins
            await db.execute(
                "UPDATE coins SET balance = balance - ? WHERE user_id=?",
                (final_price, interaction.user.id)
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
            """, (interaction.user.id, name, final_price, int(time.time())))

            await db.commit()

        # Send DM (auto delete after 10 min)
        try:
            dm_msg = await interaction.user.send(
                f"🎉 **Purchase Successful!**\n\n"
                f"📦 Product: **{name}**\n"
                f"💰 Final Price: {final_price} coins\n"
                f"🎟 Coupon: {coupon_code or 'None'}\n\n"
                f"🔗 **Your Link (auto deletes in 30 sec):**\n{link}"
            )

            await asyncio.sleep(30)
            await dm_msg.delete()

        except:
            pass

        await interaction.followup.send(
            f"✅ Purchase complete!\n💰 Final price: {final_price} coins",
            ephemeral=True
        )


# ================= VIEW =================
class ShopView(discord.ui.View):
    def __init__(self, item_id, stock):
        super().__init__(timeout=None)
        self.item_id = item_id

        if stock <= 0:
            self.confirm.disabled = True
            self.confirm.label = "❌ Out of Stock"
            self.confirm.style = discord.ButtonStyle.danger

    @discord.ui.button(label="💳 Confirm Payment", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BuyModal(self.item_id))


# ================= AUTO REFRESH TASK =================
async def auto_refresh_message(bot, message, item_id):
    while True:
        await asyncio.sleep(10)

        try:
            async with aiosqlite.connect(DB_NAME) as db:
                cur = await db.execute("""
                SELECT shop_items.id, shop_items.name, shop_items.price,
                       shop_items.stock, shop_items.image_url,
                       shop_categories.name
                FROM shop_items
                JOIN shop_categories ON shop_items.category_id = shop_categories.id
                WHERE shop_items.id=?
                """, (item_id,))
                item = await cur.fetchone()

            if not item:
                return

            item_id, name, price, stock, image_url, category = item
            embed = product_embed(message.guild, item_id, name, price, stock, image_url, category)
            view = ShopView(item_id, stock)

            await message.edit(embed=embed, view=view)

        except discord.NotFound:
            return
        except:
            pass


# ================= SHOP COG =================
class Shop(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


    # -------- ADD CATEGORY --------
    @app_commands.command(name="add_category", description="Add shop category")
    @app_commands.checks.has_permissions(administrator=True)
    async def add_category(self, interaction: discord.Interaction, name: str):

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "INSERT OR IGNORE INTO shop_categories(name) VALUES(?)",
                (name,)
            )
            await db.commit()

        await interaction.response.send_message(
            f"✅ Category `{name}` added successfully.",
            ephemeral=True
        )


    # -------- ADD PRODUCT --------
    @app_commands.command(name="add_product", description="Add product to shop")
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
                    "❌ Category not found. Create it first using /add_category",
                    ephemeral=True
                )

            category_id = row[0]

            await db.execute("""
            INSERT INTO shop_items (name, price, stock, image_url, category_id, product_link)
            VALUES (?,?,?,?,?,?)
            """, (name, price, stock, image_url, category_id, product_link))

            await db.commit()

        await interaction.response.send_message(
            f"✅ Product `{name}` added successfully!",
            ephemeral=True
        )


    # -------- SHOW SHOP --------
    @app_commands.command(name="shop", description="View shop")
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
            embed = product_embed(interaction.guild, item_id, name, price, stock, image_url, category)
            view = ShopView(item_id, stock)
            msg = await interaction.channel.send(embed=embed, view=view)

            # start auto refresh loop
            self.bot.loop.create_task(auto_refresh_message(self.bot, msg, item_id))

        await interaction.response.send_message(
            "🛒 Shop loaded (auto refresh every 10 seconds)",
            ephemeral=True
        )


# ================= SETUP =================
async def setup(bot: commands.Bot):
    await bot.add_cog(Shop(bot))
