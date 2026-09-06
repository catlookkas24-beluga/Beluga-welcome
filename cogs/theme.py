"""
cogs/theme.py — 🎨 Global Theme Color
ตั้งสีหลักครั้งเดียว แล้วอัปเดตสีของทุกระบบ (welcome, goodbye, verify, rules, ticket) พร้อมกัน
ไม่ใช่ "ค่าเริ่มต้นแบบ fallback" แต่เป็นการเขียนทับสีทุกระบบทันที — เห็นผลชัดเจน คาดเดาได้ง่าย
"""

import discord
from discord import app_commands
from discord.ext import commands

import db
from checks import require_permission

THEMED_SECTIONS = ["welcome", "goodbye", "verify", "rules", "ticket"]


class Theme(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="theme-set-color",
        description="ตั้งสีหลักให้ทุกระบบพร้อมกัน (welcome, goodbye, verify, rules, ticket) (แอดมินเท่านั้น)",
    )
    @require_permission()
    @app_commands.describe(hex_color="สี hex เช่น #a0d2eb")
    async def theme_set_color(self, interaction: discord.Interaction, hex_color: str):
        hex_color = hex_color.strip()
        if not hex_color.startswith("#"):
            hex_color = "#" + hex_color

        for section in THEMED_SECTIONS:
            await db.update_guild_section(interaction.guild_id, section, {"color": hex_color})

        await interaction.response.send_message(
            f"✅ ตั้งสีธีม `{hex_color}` ให้ครบ **{len(THEMED_SECTIONS)} ระบบ** แล้ว: "
            f"{', '.join(THEMED_SECTIONS)}\n"
            f"⚠️ ต้องโพสต์แผงใหม่ (`/verify-post-panel`, `/ticket-panel`, `/rules-post`) "
            f"หรือกด \"นำไปใช้จริง\" ใน `/welcome-editor`/`/goodbye-editor` เพื่อให้เห็นสีใหม่",
            ephemeral=True,
        )

    @app_commands.command(
        name="theme-view", description="ดูสีปัจจุบันของทุกระบบในเซิร์ฟนี้"
    )
    async def theme_view(self, interaction: discord.Interaction):
        cfg = await db.get_guild_config(interaction.guild_id)
        embed = discord.Embed(title="🎨 สีปัจจุบันของแต่ละระบบ", color=discord.Color.blurple())
        for section in THEMED_SECTIONS:
            color = cfg.get(section, {}).get("color", "(ไม่ได้ตั้ง)")
            embed.add_field(name=section, value=f"`{color}`", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Theme(bot))
