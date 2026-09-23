"""
cogs/theme.py — 🎨 Global Theme Color
ตั้งสีหลักครั้งเดียว แล้วอัปเดตสีของทุกระบบ (welcome, goodbye, verify, rules, ticket) พร้อมกัน
ไม่ใช่ "ค่าเริ่มต้นแบบ fallback" แต่เป็นการเขียนทับสีทุกระบบทันที — เห็นผลชัดเจน คาดเดาได้ง่าย
"""

import discord
from discord import app_commands
from discord.ext import commands

import db
import style
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

        try:
            preview_color = int(hex_color.lstrip("#"), 16)
        except ValueError:
            await interaction.response.send_message(
                embed=style.error("ใส่ hex code ไม่ถูกต้องครับ เช่น `#a0d2eb` หรือ `a0d2eb`", system="theme"),
                ephemeral=True,
            )
            return

        for section in THEMED_SECTIONS:
            await db.update_guild_section(interaction.guild_id, section, {"color": hex_color})

        embed = style.success(
            f"ตั้งสีธีม `{hex_color}` ให้ครบ **{len(THEMED_SECTIONS)} ระบบ** แล้ว\n"
            f"{style.DIVIDER}\n"
            + "\n".join(f"• {s}" for s in THEMED_SECTIONS)
            + f"\n{style.DIVIDER}\n"
            + "⚠️ ต้องโพสต์แผงใหม่ (`/verify-post-panel`, `/ticket-panel`, `/rules-post`) "
            "หรือกด \"นำไปใช้จริง\" ใน `/welcome-editor`/`/goodbye-editor` เพื่อให้เห็นสีใหม่",
            title="ตั้งสีธีมเรียบร้อย",
            system="theme",
        )
        embed.color = preview_color
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="theme-view", description="ดูสีปัจจุบันของทุกระบบในเซิร์ฟนี้"
    )
    async def theme_view(self, interaction: discord.Interaction):
        cfg = await db.get_guild_config(interaction.guild_id)
        embed = style.brand_embed(
            title="🎨 สีธีมปัจจุบันของเซิร์ฟเวอร์นี้",
            description=f"ตั้งใหม่ทีเดียวทุกระบบด้วย `/theme-set-color`\n{style.DIVIDER}",
            system="theme",
            thumbnail=interaction.guild.icon.url if interaction.guild.icon else None,
        )
        for section in THEMED_SECTIONS:
            color = cfg.get(section, {}).get("color", "*(ไม่ได้ตั้ง — ใช้ค่าเริ่มต้น)*")
            embed.add_field(name=f"{style.SYSTEM_ICON.get(section, '🎨')} {section}", value=f"`{color}`", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Theme(bot))
