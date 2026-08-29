"""
cogs/welcome.py — 🎨 Welcome Designer
แอดมินพิมพ์ /welcome-editor แล้วบอทเด้ง Modal ให้กรอก title/description/hex color/รูป
รองรับตัวแปร {user} {server_name} {server_membercount} แทรกในข้อความได้เลย
"""

import discord
from discord import app_commands
from discord.ext import commands

import db


def render_variables(text: str, member: discord.Member) -> str:
    if not text:
        return ""
    return (
        text.replace("{user}", member.mention)
        .replace("{server_name}", member.guild.name)
        .replace("{server_membercount}", str(member.guild.member_count))
    )


def parse_hex_color(hex_str: str) -> discord.Color:
    try:
        hex_str = hex_str.strip().lstrip("#")
        return discord.Color(int(hex_str, 16))
    except (ValueError, AttributeError):
        return discord.Color.blurple()


class WelcomeEditorModal(discord.ui.Modal, title="🎨 Welcome Designer"):
    def __init__(self, current: dict):
        super().__init__()
        self.title_input = discord.ui.TextInput(
            label="Title",
            default=current.get("title", ""),
            max_length=256,
        )
        self.description_input = discord.ui.TextInput(
            label="Description",
            style=discord.TextStyle.paragraph,
            default=current.get("description", ""),
            max_length=1000,
        )
        self.color_input = discord.ui.TextInput(
            label="Hex Color (เช่น #a0d2eb)",
            default=current.get("color", "#a0d2eb"),
            max_length=7,
        )
        self.image_input = discord.ui.TextInput(
            label="Main Image URL / GIF (เว้นว่างได้)",
            default=current.get("image_url") or "",
            required=False,
            max_length=500,
        )
        for item in (
            self.title_input,
            self.description_input,
            self.color_input,
            self.image_input,
        ):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        await db.update_guild_section(
            interaction.guild_id,
            "welcome",
            {
                "title": self.title_input.value,
                "description": self.description_input.value,
                "color": self.color_input.value,
                "image_url": self.image_input.value or None,
            },
        )
        preview = build_welcome_embed(
            {
                "title": self.title_input.value,
                "description": self.description_input.value,
                "color": self.color_input.value,
                "image_url": self.image_input.value or None,
            },
            interaction.user,
        )
        await interaction.response.send_message(
            "✅ บันทึกการตั้งค่า Welcome Designer แล้ว นี่คือตัวอย่าง:",
            embed=preview,
            ephemeral=True,
        )


def build_welcome_embed(cfg: dict, member: discord.Member) -> discord.Embed:
    embed = discord.Embed(
        title=render_variables(cfg.get("title", ""), member),
        description=render_variables(cfg.get("description", ""), member),
        color=parse_hex_color(cfg.get("color", "#a0d2eb")),
    )
    if cfg.get("image_url"):
        embed.set_image(url=cfg["image_url"])
    embed.set_thumbnail(url=member.display_avatar.url)
    return embed


class Welcome(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="welcome-editor", description="เปิดหน้าต่างแก้ไข embed ต้อนรับ (แอดมินเท่านั้น)"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def welcome_editor(self, interaction: discord.Interaction):
        cfg = await db.get_guild_config(interaction.guild_id)
        await interaction.response.send_modal(WelcomeEditorModal(cfg["welcome"]))

    @app_commands.command(
        name="welcome-set-channel", description="ตั้งห้องที่จะโพสต์ข้อความต้อนรับ (แอดมินเท่านั้น)"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def welcome_set_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        await db.update_guild_section(
            interaction.guild_id, "welcome", {"channel_id": channel.id}
        )
        await interaction.response.send_message(
            f"✅ ตั้งห้องต้อนรับเป็น {channel.mention} แล้ว", ephemeral=True
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        if not await db.is_system_enabled(member.guild.id, "welcome"):
            return
        cfg = await db.get_guild_config(member.guild.id)
        channel_id = cfg["welcome"].get("channel_id")
        if not channel_id:
            return
        channel = member.guild.get_channel(channel_id)
        if channel is None:
            return
        embed = build_welcome_embed(cfg["welcome"], member)
        await channel.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Welcome(bot))
