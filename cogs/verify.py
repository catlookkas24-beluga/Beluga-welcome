"""
cogs/verify.py — 🔐 Interactive Verify Setup
เปลี่ยนจากระบบกดอีโมจิเป็นปุ่ม [ ✅ ยืนยันตัวตน ] และ [ ❓ ทำไมต้องยืนยัน ]
แอดมินตั้งค่ายศที่จะแจกผ่าน Dropdown (discord.ui.Select) และแก้ข้อความอธิบายผ่าน Modal
"""

import io

import discord
from discord import app_commands
from discord.ext import commands

import db
from checks import require_permission
from cogs.welcome import parse_hex_color


async def build_verify_panel_message(guild_id: int) -> tuple[discord.Embed, discord.File | None]:
    """สร้าง embed แผงยืนยันตัวตน — แนบ banner ให้อัตโนมัติถ้าตั้งไว้แล้ว (ใช้ร่วมกันทั้ง
    /verify-post-panel และ /verify-setup-gate กันลืมแนบ banner ไม่ตรงกัน)"""
    cfg = await db.get_guild_config(guild_id)
    banner_asset_id = cfg["verify"].get("banner_asset_id")

    embed = discord.Embed(
        title="ยืนยันตัวตน",
        description="กดปุ่มด้านล่างเพื่อยืนยันตัวตนและเข้าใช้งานเซิร์ฟเวอร์แบบเต็มรูปแบบ",
        color=parse_hex_color(cfg["verify"].get("color", "#2ecc71")),
    )

    file = None
    if banner_asset_id:
        try:
            banner_bytes = await db.get_asset_bytes(banner_asset_id)
            file = discord.File(io.BytesIO(banner_bytes), filename="verify_banner.png")
            embed.set_image(url="attachment://verify_banner.png")
        except Exception:
            file = None  # ไฟล์อาจถูกลบไปแล้ว — โพสต์ต่อโดยไม่มี banner แทนที่จะพัง

    return embed, file


class ExplainModal(discord.ui.Modal, title="❓ ทำไมต้องยืนยันตัวตน"):
    explain = discord.ui.TextInput(
        label="ข้อความอธิบาย",
        style=discord.TextStyle.paragraph,
        max_length=1000,
    )

    def __init__(self, current_text: str):
        super().__init__()
        self.explain.default = current_text

    async def on_submit(self, interaction: discord.Interaction):
        await db.update_guild_section(
            interaction.guild_id, "verify", {"explain_text": self.explain.value}
        )
        await interaction.response.send_message(
            "✅ อัปเดตข้อความอธิบายแล้ว", ephemeral=True
        )


class VerifyPanelView(discord.ui.View):
    """View ถาวร (persistent) ที่ติดอยู่กับข้อความยืนยันตัวตนในห้อง"""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="ยืนยันตัวตน",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="beluga:verify:confirm",
    )
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = await db.get_guild_config(interaction.guild_id)
        role_id = cfg["verify"].get("role_id")
        if not role_id:
            await interaction.response.send_message(
                "⚠️ ยังไม่ได้ตั้งค่ายศสำหรับยืนยันตัวตน กรุณาแจ้งแอดมิน", ephemeral=True
            )
            return
        role = interaction.guild.get_role(role_id)
        if role is None:
            await interaction.response.send_message(
                "⚠️ ยศที่ตั้งไว้ถูกลบไปแล้ว กรุณาแจ้งแอดมิน", ephemeral=True
            )
            return
        if role in interaction.user.roles:
            await interaction.response.send_message(
                "คุณยืนยันตัวตนไปแล้วครับ ✅", ephemeral=True
            )
            return
        await interaction.user.add_roles(role, reason="ยืนยันตัวตนผ่านปุ่ม")
        await interaction.response.send_message(
            "🎉 ยืนยันตัวตนสำเร็จ! ยินดีต้อนรับครับ", ephemeral=True
        )

    @discord.ui.button(
        label="ทำไมต้องยืนยัน",
        emoji="❓",
        style=discord.ButtonStyle.secondary,
        custom_id="beluga:verify:explain",
    )
    async def explain(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = await db.get_guild_config(interaction.guild_id)
        text = cfg["verify"].get("explain_text", "")
        await interaction.response.send_message(text or "ยังไม่มีข้อความอธิบาย", ephemeral=True)


class RoleSelectView(discord.ui.View):
    """ใช้ครั้งเดียวตอนแอดมิน setup — เลือกยศที่จะแจกให้หลังยืนยันตัวตน"""

    def __init__(self):
        super().__init__(timeout=180)

    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="เลือกยศที่จะมอบให้หลังยืนยันตัวตน")
    async def role_select(
        self, interaction: discord.Interaction, select: discord.ui.RoleSelect
    ):
        role = select.values[0]
        await db.update_guild_section(interaction.guild_id, "verify", {"role_id": role.id})
        await interaction.response.send_message(
            f"✅ ตั้งยศยืนยันตัวตนเป็น {role.mention} แล้ว", ephemeral=True
        )


class Verify(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # ลงทะเบียน persistent view ตอนบอทเริ่มทำงาน เพื่อให้ปุ่มยังกดได้แม้บอท restart
        bot.add_view(VerifyPanelView())

    @app_commands.command(
        name="verify-set-role", description="ตั้งยศที่จะมอบให้หลังยืนยันตัวตน (แอดมินเท่านั้น)"
    )
    @require_permission()
    async def verify_set_role(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "เลือกยศจากเมนูด้านล่าง:", view=RoleSelectView(), ephemeral=True
        )

    @app_commands.command(
        name="verify-set-explain", description="แก้ไขข้อความ 'ทำไมต้องยืนยัน' (แอดมินเท่านั้น)"
    )
    @require_permission()
    async def verify_set_explain(self, interaction: discord.Interaction):
        cfg = await db.get_guild_config(interaction.guild_id)
        await interaction.response.send_modal(
            ExplainModal(cfg["verify"].get("explain_text", ""))
        )

    @app_commands.command(
        name="verify-set-banner",
        description="ตั้งภาพประกอบ (banner) ด้านบนแผงยืนยันตัวตน (แอดมินเท่านั้น)",
    )
    @require_permission()
    async def verify_set_banner(self, interaction: discord.Interaction, image: discord.Attachment):
        asset_type = db.detect_asset_type(image.filename)
        if asset_type != "image":
            await interaction.response.send_message(
                "⚠️ ต้องเป็นไฟล์รูป .png .jpg .jpeg .webp เท่านั้น", ephemeral=True
            )
            return
        if image.size > db.MAX_ASSET_SIZE_BYTES:
            await interaction.response.send_message("⚠️ ไฟล์ใหญ่เกิน 5MB", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        data = await image.read()
        file_id = await db.save_asset(
            interaction.guild_id, image.filename, data, "image", "verify_banner"
        )
        await db.update_guild_section(interaction.guild_id, "verify", {"banner_asset_id": file_id})
        await interaction.followup.send(
            "✅ ตั้งภาพ banner แล้ว ใช้ `/verify-post-panel` เพื่อโพสต์แผงใหม่อีกครั้งให้เห็นผล",
            ephemeral=True,
        )

    @app_commands.command(
        name="verify-set-color",
        description="ตั้งสี hex ของแผงยืนยันตัวตน (แอดมินเท่านั้น)",
    )
    @require_permission()
    @app_commands.describe(hex_color="สี hex เช่น #2ecc71")
    async def verify_set_color(self, interaction: discord.Interaction, hex_color: str):
        await db.update_guild_section(interaction.guild_id, "verify", {"color": hex_color})
        await interaction.response.send_message(
            f"✅ ตั้งสีแผงยืนยันตัวตนเป็น `{hex_color}` แล้ว ใช้ `/verify-post-panel` เพื่อโพสต์แผงใหม่ให้เห็นผล",
            ephemeral=True,
        )

    @app_commands.command(
        name="verify-setup-gate",
        description="🚪 สร้างห้องยืนยันตัวตน+กฎอัตโนมัติ และล็อกไม่ให้คนที่ยังไม่มียศเห็นห้องอื่นเลย (แอดมินเท่านั้น)",
    )
    @require_permission()
    @app_commands.describe(
        verified_role="ยศที่จะแจกหลังยืนยันตัวตน (คนที่มียศนี้จะเห็นห้องอื่นทั้งหมด)"
    )
    async def verify_setup_gate(self, interaction: discord.Interaction, verified_role: discord.Role):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        everyone = guild.default_role

        # 1. หา/สร้างหมวดหมู่ "เริ่มต้นที่นี่" พร้อมห้องยืนยันตัวตน + กฎ
        category = discord.utils.get(guild.categories, name="🚪 เริ่มต้นที่นี่")
        if category is None:
            category = await guild.create_category("🚪 เริ่มต้นที่นี่", reason="Verify Gate Setup")

        verify_channel = discord.utils.get(category.text_channels, name="ยืนยันตัวตน")
        if verify_channel is None:
            verify_channel = await category.create_text_channel(
                "ยืนยันตัวตน", reason="Verify Gate Setup"
            )

        rules_channel = discord.utils.get(category.text_channels, name="กฎ")
        if rules_channel is None:
            rules_channel = await category.create_text_channel("กฎ", reason="Verify Gate Setup")

        # 2. ล็อกห้องอื่นทั้งหมด (ยกเว้นในหมวดนี้) ไม่ให้ @everyone เห็น
        #    แต่ยศที่ยืนยันแล้วยังเห็นได้ปกติ
        locked, failed = 0, 0
        for ch in guild.channels:
            if ch.id == category.id or getattr(ch, "category_id", None) == category.id:
                continue
            try:
                await ch.set_permissions(everyone, view_channel=False, reason="Verify Gate Setup")
                await ch.set_permissions(verified_role, view_channel=True, reason="Verify Gate Setup")
                locked += 1
            except (discord.Forbidden, discord.HTTPException):
                failed += 1

        # 3. เปิดให้ @everyone เห็นหมวด/ห้องเริ่มต้น แต่ส่งข้อความไม่ได้ (พิมพ์ได้แค่หลังยืนยัน)
        await category.set_permissions(
            everyone, view_channel=True, send_messages=False, reason="Verify Gate Setup"
        )
        await verify_channel.set_permissions(
            everyone, view_channel=True, send_messages=False, reason="Verify Gate Setup"
        )
        await rules_channel.set_permissions(
            everyone, view_channel=True, send_messages=False, reason="Verify Gate Setup"
        )

        # 4. ผูก role/channel เข้ากับระบบ verify เดิม แล้วโพสต์แผงปุ่มให้เลย (แนบ banner ถ้าตั้งไว้แล้ว)
        await db.update_guild_section(
            interaction.guild_id,
            "verify",
            {"role_id": verified_role.id, "channel_id": verify_channel.id},
        )
        embed, file = await build_verify_panel_message(interaction.guild_id)
        if file:
            await verify_channel.send(embed=embed, view=VerifyPanelView(), file=file)
        else:
            await verify_channel.send(embed=embed, view=VerifyPanelView())

        warning = ""
        if failed:
            warning = f"\n⚠️ ล้มเหลว {failed} ห้อง — เช็คว่าบอทมีสิทธิ์ **Manage Channels** ในห้องนั้นไหม"

        await interaction.followup.send(
            f"✅ ตั้งค่า Verify Gate เสร็จแล้ว!\n"
            f"- สร้างหมวด **{category.name}** พร้อมห้อง {verify_channel.mention} และ {rules_channel.mention}\n"
            f"- ล็อกห้องอื่น **{locked} ห้อง** ไม่ให้คนที่ยังไม่มียศ {verified_role.mention} เห็น"
            f"{warning}\n\n"
            f"⚠️ **สำคัญ**: ยศ/สมาชิกที่มีสิทธิ์ **Administrator** จะยังเห็นทุกห้องตามปกติ (Discord ยกเว้นให้อัตโนมัติ) "
            f"แต่ถ้ามีทีมงาน/มอดที่ไม่มี Administrator ต้องเพิ่ม role นั้นให้เห็นห้องที่จำเป็นด้วยตัวเอง "
            f"(ใช้ `/permission-set` ได้) ไม่งั้นจะโดนล็อกไปด้วย",
            ephemeral=True,
        )

    @app_commands.command(
        name="verify-post-panel", description="โพสต์แผงปุ่มยืนยันตัวตนในห้องนี้ (แอดมินเท่านั้น)"
    )
    @require_permission()
    async def verify_post_panel(self, interaction: discord.Interaction):
        embed, file = await build_verify_panel_message(interaction.guild_id)
        if file:
            await interaction.channel.send(embed=embed, view=VerifyPanelView(), file=file)
        else:
            await interaction.channel.send(embed=embed, view=VerifyPanelView())

        await db.update_guild_section(
            interaction.guild_id, "verify", {"channel_id": interaction.channel_id}
        )
        await interaction.response.send_message("✅ โพสต์แผงยืนยันตัวตนแล้ว", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Verify(bot))
