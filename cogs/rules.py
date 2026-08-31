"""
cogs/rules.py — 📜 Rules & Rank Text Editor
แก้กฎ 11 ข้อ หรือเงื่อนไขเลื่อนยศผ่าน Modal ได้เลย ไม่ต้องแตะไฟล์
พอกดบันทึก ข้อความในห้องกฎจะถูก edit ให้เป็นเนื้อหาใหม่ทันที
"""

import discord
from discord import app_commands
from discord.ext import commands

import db
from checks import require_permission


def build_rules_embed(cfg: dict) -> discord.Embed:
    embed = discord.Embed(
        title="📜 กฎของเซิร์ฟเวอร์",
        description=cfg.get("rules_text", ""),
        color=discord.Color.orange(),
    )
    if cfg.get("rank_text"):
        embed.add_field(name="🏅 เงื่อนไขการเลื่อนยศ", value=cfg["rank_text"], inline=False)
    return embed


class RulesEditorModal(discord.ui.Modal, title="📜 แก้ไขกฎเซิร์ฟเวอร์"):
    def __init__(self, current: dict):
        super().__init__()
        self.rules_input = discord.ui.TextInput(
            label="ข้อความกฎ",
            style=discord.TextStyle.paragraph,
            default=current.get("rules_text", ""),
            max_length=4000,
        )
        self.rank_input = discord.ui.TextInput(
            label="เงื่อนไขการเลื่อนยศ",
            style=discord.TextStyle.paragraph,
            default=current.get("rank_text", ""),
            required=False,
            max_length=1000,
        )
        self.add_item(self.rules_input)
        self.add_item(self.rank_input)

    async def on_submit(self, interaction: discord.Interaction):
        await db.update_guild_section(
            interaction.guild_id,
            "rules",
            {"rules_text": self.rules_input.value, "rank_text": self.rank_input.value},
        )
        cfg = await db.get_guild_config(interaction.guild_id)
        rules_cfg = cfg["rules"]
        updated = False
        if rules_cfg.get("channel_id") and rules_cfg.get("message_id"):
            channel = interaction.guild.get_channel(rules_cfg["channel_id"])
            if channel:
                try:
                    msg = await channel.fetch_message(rules_cfg["message_id"])
                    await msg.edit(embed=build_rules_embed(rules_cfg))
                    updated = True
                except discord.NotFound:
                    pass
        note = "และอัปเดตข้อความในห้องกฎแล้ว" if updated else "(ยังไม่ได้ผูกกับข้อความในห้องกฎ ใช้ /rules-post ก่อน)"
        await interaction.response.send_message(f"✅ บันทึกกฎใหม่แล้ว {note}", ephemeral=True)


class Rules(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="rules-editor", description="เปิดหน้าต่างแก้ไขกฎ (แอดมินเท่านั้น)")
    @require_permission()
    async def rules_editor(self, interaction: discord.Interaction):
        cfg = await db.get_guild_config(interaction.guild_id)
        await interaction.response.send_modal(RulesEditorModal(cfg["rules"]))

    @app_commands.command(
        name="rules-post", description="โพสต์ข้อความกฎในห้องนี้ (ผูกไว้เพื่ออัปเดตอัตโนมัติในอนาคต)"
    )
    @require_permission()
    async def rules_post(self, interaction: discord.Interaction):
        cfg = await db.get_guild_config(interaction.guild_id)
        embed = build_rules_embed(cfg["rules"])
        msg = await interaction.channel.send(embed=embed)
        await db.update_guild_section(
            interaction.guild_id,
            "rules",
            {"channel_id": interaction.channel_id, "message_id": msg.id},
        )
        await interaction.response.send_message("✅ โพสต์กฎและผูกห้องนี้แล้ว", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Rules(bot))
