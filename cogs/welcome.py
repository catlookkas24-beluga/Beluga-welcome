"""
cogs/welcome.py — 🎨 Welcome Designer
"""

import io
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont

import db
from checks import require_permission
from cogs.font import load_font_bytes, parse_hex_color as parse_hex_rgba


def normalize_newlines(text: str) -> str:
    """เก็บ Enter จริงไว้ ไม่แปลง newline ให้หาย"""
    if not text:
        return ""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def render_variables(text: str, member: discord.Member, use_mention: bool = True) -> str:
    if not text:
        return ""
    text = normalize_newlines(text)
    user_value = member.mention if use_mention else member.display_name
    return (
        text.replace("{user_name}", member.display_name)
        .replace("{user}", user_value)
        .replace("{server_name}", member.guild.name)
        .replace("{server_membercount}", str(member.guild.member_count))
    )


def parse_hex_color(hex_str: str) -> discord.Color:
    try:
        hex_str = hex_str.strip().lstrip("#")
        return discord.Color(int(hex_str, 16))
    except (ValueError, AttributeError):
        return discord.Color.blurple()


async def fetch_image_bytes(url: str) -> bytes | None:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return None
                return await resp.read()
    except Exception:
        return None


def render_avatar_text_on_background(
    background_bytes: bytes,
    avatar_bytes: bytes | None,
    font_bytes: bytes,
    text: str,
    text_color: tuple = (255, 255, 255, 255),
    font_size: int = 48,
    avatar_size: int = 128,
) -> bytes:
    bg = Image.open(io.BytesIO(background_bytes)).convert("RGBA")
    bg_w, bg_h = bg.size

    if avatar_bytes:
        avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((avatar_size, avatar_size))
        mask = Image.new("L", (avatar_size, avatar_size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, avatar_size, avatar_size), fill=255)
        avatar.putalpha(mask)
        avatar_pos = ((bg_w - avatar_size) // 2, (bg_h - avatar_size) // 2 - int(bg_h * 0.08))
        bg.paste(avatar, avatar_pos, avatar)

    draw = ImageDraw.Draw(bg)
    font_obj = ImageFont.truetype(io.BytesIO(font_bytes), font_size)
    bbox = draw.textbbox((0, 0), text, font=font_obj)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    text_x = (bg_w - text_w) // 2
    text_y = bg_h - text_h - int(bg_h * 0.10)
    draw.text((text_x - bbox[0], text_y - bbox[1]), text, font=font_obj, fill=text_color)

    buf = io.BytesIO()
    bg.save(buf, format="PNG")
    return buf.getvalue()


def build_welcome_embed(cfg: dict, member: discord.Member) -> discord.Embed:
    embed = discord.Embed(
        title=render_variables(cfg.get("title", ""), member, use_mention=False),
        description=render_variables(cfg.get("description", ""), member, use_mention=True),
        color=parse_hex_color(cfg.get("color", "#a0d2eb")),
    )
    if cfg.get("image_url"):
        embed.set_image(url=cfg["image_url"])
    embed.set_thumbnail(url=member.display_avatar.url)
    return embed


async def build_welcome_message(cfg: dict, member: discord.Member, guild_id: int):
    embed = build_welcome_embed(cfg, member)
    file = None

    font_key = cfg.get("font_key")
    image_url = cfg.get("image_url")
    if font_key and image_url:
        bg_bytes = await fetch_image_bytes(image_url)
        if bg_bytes:
            loaded_font = await load_font_bytes(guild_id, font_key)
            if loaded_font:
                font_bytes, _ = loaded_font
                try:
                    avatar_bytes = await member.display_avatar.replace(size=256).read()
                except Exception:
                    avatar_bytes = None
                text = render_variables(cfg.get("title", ""), member, use_mention=False)
                try:
                    image_bytes = render_avatar_text_on_background(
                        bg_bytes, avatar_bytes, font_bytes, text
                    )
                    file = discord.File(io.BytesIO(image_bytes), filename="welcome_composite.png")
                    embed.set_image(url="attachment://welcome_composite.png")
                except Exception:
                    file = None

    return embed, file


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
            placeholder="พิมพ์ข้อความได้หลายบรรทัด — กด Enter เพื่อขึ้นบรรทัดใหม่",
            default=normalize_newlines(current.get("description", "")),
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
        self.font_input = discord.ui.TextInput(
            label="ฟอนต์ (ไม่บังคับ) ดูชื่อจาก /font-list",
            placeholder="เช่น mali, pattaya (เว้นว่าง = ไม่วาดทับรูป)",
            default=current.get("font_key") or "",
            required=False,
            max_length=100,
        )
        for item in (
            self.title_input,
            self.description_input,
            self.color_input,
            self.image_input,
            self.font_input,
        ):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        pending_data = {
            "title": self.title_input.value,
            "description": normalize_newlines(self.description_input.value),
            "color": self.color_input.value,
            "image_url": self.image_input.value or None,
            "font_key": self.font_input.value.strip() or None,
        }
        embed, file = await build_welcome_message(
            pending_data, interaction.user, interaction.guild_id
        )
        view = WallpaperPreviewView(
            interaction.guild_id, interaction.user.id, pending_data
        )
        kwargs = {
            "content": "🖼️ นี่คือตัวอย่าง — **ยังไม่ถูกบันทึก** จนกว่าจะกด \"นำไปใช้จริง\"",
            "embed": embed,
            "view": view,
            "ephemeral": True,
        }
        if file:
            kwargs["file"] = file
        await interaction.followup.send(**kwargs)


class WallpaperPreviewView(discord.ui.View):
    def __init__(self, guild_id: int, editor_id: int, pending_data: dict):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.editor_id = editor_id
        self.pending_data = pending_data

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.editor_id:
            await interaction.response.send_message(
                "ปุ่มนี้ใช้ได้เฉพาะคนที่เปิดหน้าต่างแก้ไขนี้เท่านั้นครับ",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="พรีวิวตัวอย่าง", emoji="👁️", style=discord.ButtonStyle.secondary)
    async def preview(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        embed, file = await build_welcome_message(
            self.pending_data, interaction.user, self.guild_id
        )
        kwargs = {"content": "👁️ ตัวอย่าง (ยังไม่บันทึก):", "embed": embed, "ephemeral": True}
        if file:
            kwargs["file"] = file
        await interaction.followup.send(**kwargs)

    @discord.ui.button(label="นำไปใช้จริง", emoji="✅", style=discord.ButtonStyle.success)
    async def apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        await db.update_guild_section(
            self.guild_id, "welcome", self.pending_data
        )
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
            content="🔄 ยกเลิกแล้ว ไม่มีการบันทึกการเปลี่ยนแปลงใด ๆ",
            embed=None,
            view=self,
        )


class Welcome(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="welcome-editor",
        description="เปิดหน้าต่างแก้ไข embed ต้อนรับ (แอดมินเท่านั้น)",
    )
    @require_permission()
    async def welcome_editor(self, interaction: discord.Interaction):
        cfg = await db.get_guild_config(interaction.guild_id)
        await interaction.response.send_modal(WelcomeEditorModal(cfg["welcome"]))

    @app_commands.command(
        name="welcome-set-channel",
        description="ตั้งห้องที่จะโพสต์ข้อความต้อนรับ (แอดมินเท่านั้น)",
    )
    @require_permission()
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

        embed, file = await build_welcome_message(
            cfg["welcome"], member, member.guild.id
        )
        if file:
            await channel.send(embed=embed, file=file)
        else:
            await channel.send(embed=embed)

        await channel.send(content=f"({member.mention})")


async def setup(bot: commands.Bot):
    await bot.add_cog(Welcome(bot))
