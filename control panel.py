"""
cogs/control_panel.py — ⚙️ Beluga Control Panel
Dashboard เดียวที่มีปุ่มเปิด/ปิดแต่ละระบบ (welcome, verify, rules, antiraid, autorole)
Config แยกตาม guild ใน MongoDB อยู่แล้ว (ดู db.py) ทำให้บอทตัวเดียวคุมได้หลายเซิร์ฟ
"""

import discord
from discord import app_commands
from discord.ext import commands

import db

SYSTEM_LABELS = {
    "welcome": "🎨 Welcome Designer",
    "verify": "🔐 Verify Setup",
    "rules": "📜 Rules & Rank Editor",
    "antiraid": "🛡️ Anti-Raid & Security",
    "autorole": "🏅 Auto Role Timeline",
}


class TogglePanelView(discord.ui.View):
    def __init__(self, guild_id: int, systems_enabled: dict):
        super().__init__(timeout=120)
        self.guild_id = guild_id
        for key, label in SYSTEM_LABELS.items():
            enabled = systems_enabled.get(key, True)
            self.add_item(self.make_button(key, label, enabled))

    def make_button(self, key: str, label: str, enabled: bool) -> discord.ui.Button:
        style = discord.ButtonStyle.success if enabled else discord.ButtonStyle.danger
        status = "เปิดอยู่" if enabled else "ปิดอยู่"
        button = discord.ui.Button(label=f"{label} — {status}", style=style, custom_id=f"panel:{key}")

        async def callback(interaction: discord.Interaction):
            cfg = await db.get_guild_config(self.guild_id)
            new_state = not cfg["systems_enabled"].get(key, True)
            await db.set_system_enabled(self.guild_id, key, new_state)
            refreshed = await db.get_guild_config(self.guild_id)
            new_view = TogglePanelView(self.guild_id, refreshed["systems_enabled"])
            await interaction.response.edit_message(view=new_view)

        button.callback = callback
        return button


class ControlPanel(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="beluga-panel", description="เปิด Control Panel เปิด/ปิดระบบต่าง ๆ (แอดมินเท่านั้น)"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def beluga_panel(self, interaction: discord.Interaction):
        cfg = await db.get_guild_config(interaction.guild_id)
        embed = discord.Embed(
            title="⚙️ Beluga Control Panel",
            description="กดปุ่มเพื่อเปิด/ปิดแต่ละระบบสำหรับเซิร์ฟเวอร์นี้",
            color=discord.Color.blurple(),
        )
        view = TogglePanelView(interaction.guild_id, cfg["systems_enabled"])
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ControlPanel(bot))
