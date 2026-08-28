"""
cogs/verify.py — 🔐 Interactive Verify Setup
เปลี่ยนจากระบบกดอีโมจิเป็นปุ่ม [ ✅ ยืนยันตัวตน ] และ [ ❓ ทำไมต้องยืนยัน ]
แอดมินตั้งค่ายศที่จะแจกผ่าน Dropdown (discord.ui.Select) และแก้ข้อความอธิบายผ่าน Modal
"""

import discord
from discord import app_commands
from discord.ext import commands

import db


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
    @app_commands.checks.has_permissions(manage_guild=True)
    async def verify_set_role(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "เลือกยศจากเมนูด้านล่าง:", view=RoleSelectView(), ephemeral=True
        )

    @app_commands.command(
        name="verify-set-explain", description="แก้ไขข้อความ 'ทำไมต้องยืนยัน' (แอดมินเท่านั้น)"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def verify_set_explain(self, interaction: discord.Interaction):
        cfg = await db.get_guild_config(interaction.guild_id)
        await interaction.response.send_modal(
            ExplainModal(cfg["verify"].get("explain_text", ""))
        )

    @app_commands.command(
        name="verify-post-panel", description="โพสต์แผงปุ่มยืนยันตัวตนในห้องนี้ (แอดมินเท่านั้น)"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def verify_post_panel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="ยืนยันตัวตน",
            description="กดปุ่มด้านล่างเพื่อยืนยันตัวตนและเข้าใช้งานเซิร์ฟเวอร์แบบเต็มรูปแบบ",
            color=discord.Color.green(),
        )
        await interaction.channel.send(embed=embed, view=VerifyPanelView())
        await db.update_guild_section(
            interaction.guild_id, "verify", {"channel_id": interaction.channel_id}
        )
        await interaction.response.send_message("✅ โพสต์แผงยืนยันตัวตนแล้ว", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Verify(bot))
