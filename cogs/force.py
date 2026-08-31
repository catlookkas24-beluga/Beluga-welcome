"""
cogs/force.py — ⚡ Force Sync & Emergency Reset
คำสั่งฉุกเฉินสำหรับแอดมิน: บังคับซิงก์ยศ, โพสต์ทับข้อความเก่า, คืนค่าโรงงาน
"""

import discord
from discord import app_commands
from discord.ext import commands

import db
from .checks import require_permission
from cogs.autorole import sync_guild_roles
from cogs.welcome import build_welcome_embed


class Force(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="force-sync-roles",
        description="⚡ บังคับตรวจเช็คและแจกยศ Auto Role ย้อนหลังให้สมาชิกทุกคน (แอดมินเท่านั้น)",
    )
    @require_permission()
    async def force_sync_roles(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        granted = await sync_guild_roles(interaction.guild)
        await interaction.followup.send(
            f"✅ ซิงก์ยศเสร็จแล้ว — แจกยศเพิ่มให้ **{granted} คน**", ephemeral=True
        )

    @app_commands.command(
        name="force-overwrite-welcome",
        description="⚡ ลบข้อความต้อนรับเก่าในห้องนี้แล้วโพสต์เวอร์ชันล่าสุดทับ (แอดมินเท่านั้น)",
    )
    @require_permission()
    async def force_overwrite_welcome(self, interaction: discord.Interaction, limit: int = 20):
        await interaction.response.defer(ephemeral=True)
        cfg = await db.get_guild_config(interaction.guild_id)
        deleted = 0
        async for msg in interaction.channel.history(limit=limit):
            if msg.author.id == self.bot.user.id and msg.embeds:
                try:
                    await msg.delete()
                    deleted += 1
                except discord.Forbidden:
                    pass
        embed = build_welcome_embed(cfg["welcome"], interaction.user)
        await interaction.channel.send(embed=embed)
        await interaction.followup.send(
            f"✅ ลบข้อความเก่าไป {deleted} ข้อความ และโพสต์เวอร์ชันล่าสุดทับแล้ว", ephemeral=True
        )

    @app_commands.command(
        name="force-reset-config",
        description="⚡ คืนค่าโรงงานทุกระบบของเซิร์ฟนี้ (ล้างการตั้งค่าทั้งหมด แอดมินเท่านั้น)",
    )
    @require_permission()
    async def force_reset_config(self, interaction: discord.Interaction, confirm: bool):
        if not confirm:
            await interaction.response.send_message(
                "⚠️ คำสั่งนี้จะ**ล้างการตั้งค่าทั้งหมด**ของเซิร์ฟนี้กลับเป็นค่าเริ่มต้น "
                "(welcome, verify, rules, antiraid, autorole) — ถ้าต้องการจริง ๆ "
                "พิมพ์คำสั่งเดิมอีกครั้งพร้อมใส่ `confirm: True`",
                ephemeral=True,
            )
            return
        await db.reset_guild_config(interaction.guild_id)
        await interaction.response.send_message(
            "🔄 คืนค่าโรงงานเรียบร้อยแล้ว ทุกระบบกลับไปเป็นค่าเริ่มต้น "
            "(ไฟล์ asset ที่อัปโหลดไว้ยังอยู่ครบ ไม่ถูกลบ)",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Force(bot))
