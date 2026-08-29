"""
cogs/welcome.py — 🎨 Welcome Designer
แอดมินพิมพ์ /welcome-editor แล้วบอทเด้ง Modal ให้กรอก title/description/hex color/รูป
รองรับตัวแปร {user} {server_name} {server_membercount} แทรกในข้อความได้เลย
"""

import discord
from discord import app_commands
from discord.ext import commands

import db


def render_variables(text: str, member: discord.Member, use_mention: bool = True) -> str:
    if not text:
        return ""
    user_value = member.mention if use_mention else member.display_name
    return (
        text.replace("{user}", user_value)
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
        # 🖼️ Wallpaper Live Preview — ยังไม่เซฟลง DB ทันที เก็บไว้ใน view ชั่วคราวก่อน
        # ให้แอดมินเลือกเองว่าจะ Apply จริงหรือ Cancel ทิ้ง
        pending_data = {
            "title": self.title_input.value,
            "description": self.description_input.value,
            "color": self.color_input.value,
            "image_url": self.image_input.value or None,
        }
        preview = build_welcome_embed(pending_data, interaction.user)
        view = WallpaperPreviewView(interaction.guild_id, interaction.user.id, pending_data)
        await interaction.response.send_message(
            "🖼️ นี่คือตัวอย่าง — **ยังไม่ถูกบันทึก** จนกว่าจะกด \"นำไปใช้จริง\"",
            embed=preview,
            view=view,
            ephemeral=True,
        )


class WallpaperPreviewView(discord.ui.View):
    """ปุ่มควบคุมของระบบ Wallpaper Live Preview — พรีวิวซ้ำได้/Apply/คืนค่าเดิม"""

    def __init__(self, guild_id: int, editor_id: int, pending_data: dict):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.editor_id = editor_id
        self.pending_data = pending_data

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.editor_id:
            await interaction.response.send_message(
                "ปุ่มนี้ใช้ได้เฉพาะคนที่เปิดหน้าต่างแก้ไขนี้เท่านั้นครับ", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="พรีวิวตัวอย่าง", emoji="👁️", style=discord.ButtonStyle.secondary)
    async def preview(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = build_welcome_embed(self.pending_data, interaction.user)
        await interaction.response.send_message(
            "👁️ ตัวอย่าง (ยังไม่บันทึก):", embed=embed, ephemeral=True
        )

    @discord.ui.button(label="นำไปใช้จริง", emoji="✅", style=discord.ButtonStyle.success)
    async def apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        await db.update_guild_section(self.guild_id, "welcome", self.pending_data)
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="✅ บันทึกและนำไปใช้จริงแล้ว!", view=self
        )

    @discord.ui.button(label="คืนค่าเดิม", emoji="🔄", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="🔄 ยกเลิกแล้ว ไม่มีการบันทึกการเปลี่ยนแปลงใด ๆ", embed=None, view=self
        )


def build_welcome_embed(cfg: dict, member: discord.Member) -> discord.Embed:
    embed = discord.Embed(
        # Discord ไม่ resolve mention ในช่อง title/footer/author เลยใช้ display_name แทน
        # กันโชว์เป็นรหัสดิบ <@id> เหมือนระบบเก่า
        title=render_variables(cfg.get("title", ""), member, use_mention=False),
        description=render_variables(cfg.get("description", ""), member, use_mention=True),
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
        # ส่ง mention จริงแยกข้อความ วงเล็บต่อท้าย เพื่อให้แจ้งเตือนสมาชิกใหม่ได้จริง
        # (เหมือนระบบเก่า) เพราะ title ของ embed โชว์ mention แบบกดได้ไม่ได้
        await channel.send(content=f"({member.mention})")


async def setup(bot: commands.Bot):
    await bot.add_cog(Welcome(bot))
