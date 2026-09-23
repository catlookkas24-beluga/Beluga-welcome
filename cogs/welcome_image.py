"""
cogs/welcome_image.py — 🖼️🔤 Welcome Image Composite
เอา 3 ระบบที่แยกกันมาต่อกันจริง: Asset Storage (พื้นหลัง) + Font Engine (ฟอนต์) + Welcome (ข้อความ)
วาด avatar เป็นวงกลม + เขียนข้อความด้วยฟอนต์ที่เลือก ทับบนรูปพื้นหลังที่อัปโหลดไว้
ถ้าเปิดใช้งาน จะแทนที่ "Main Image URL" ของ embed ต้อนรับด้วยรูปที่เรนเดอร์สดนี้แทน
"""

import io

import discord
from discord import app_commands
from discord.ext import commands

from PIL import Image, ImageDraw, ImageFont

import db
import style
from cogs.font import load_font_bytes, font_autocomplete, parse_hex_color
from cogs.welcome import render_variables

POSITION_CHOICES = ["top", "center", "bottom"]


def _compute_position(position: str, canvas_size: tuple, box_size: tuple) -> tuple:
    canvas_w, canvas_h = canvas_size
    box_w, box_h = box_size
    x = (canvas_w - box_w) // 2
    if position == "top":
        y = int(canvas_h * 0.08)
    elif position == "bottom":
        y = canvas_h - box_h - int(canvas_h * 0.08)
    else:
        y = (canvas_h - box_h) // 2
    return (x, y)


def render_welcome_composite(
    background_bytes: bytes,
    avatar_bytes: bytes | None,
    font_bytes: bytes,
    text: str,
    text_color: tuple,
    font_size: int,
    avatar_size: int,
    avatar_position: str,
    text_position: str,
) -> bytes:
    """วาด avatar วงกลม + ข้อความ ทับบนรูปพื้นหลัง คืนค่าเป็น PNG bytes"""
    bg = Image.open(io.BytesIO(background_bytes)).convert("RGBA")

    if avatar_bytes:
        avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
        avatar = avatar.resize((avatar_size, avatar_size))
        mask = Image.new("L", (avatar_size, avatar_size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, avatar_size, avatar_size), fill=255)
        avatar.putalpha(mask)
        pos = _compute_position(avatar_position, bg.size, (avatar_size, avatar_size))
        bg.paste(avatar, pos, avatar)

    draw = ImageDraw.Draw(bg)
    font_obj = ImageFont.truetype(io.BytesIO(font_bytes), font_size)
    bbox = draw.textbbox((0, 0), text, font=font_obj)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    text_x, text_y = _compute_position(text_position, bg.size, (text_w, text_h))
    draw.text((text_x - bbox[0], text_y - bbox[1]), text, font=font_obj, fill=text_color)

    buf = io.BytesIO()
    bg.save(buf, format="PNG")
    return buf.getvalue()


async def _render_with_cfg(cfg: dict, guild_id: int, member: discord.Member) -> discord.File | None:
    """render composite รูปจาก config ที่ระบุ (ใช้ทั้ง on_member_join จริง และ preview)"""
    if not cfg.get("background_asset_id"):
        return None
    try:
        background_bytes = await db.get_asset_bytes(cfg["background_asset_id"])
    except Exception:
        return None
    loaded_font = await load_font_bytes(guild_id, cfg.get("font_key", "mali"))
    if loaded_font is None:
        return None
    font_bytes, _ = loaded_font
    avatar_bytes = None
    if cfg.get("avatar_enabled", True):
        avatar_bytes = await member.display_avatar.replace(size=256).read()
    text = render_variables(cfg.get("text_template", ""), member, use_mention=False)
    text_color = parse_hex_color(cfg.get("text_color", "#ffffff"))
    try:
        image_bytes = render_welcome_composite(
            background_bytes,
            avatar_bytes,
            font_bytes,
            text,
            text_color,
            cfg.get("font_size", 48),
            cfg.get("avatar_size", 128),
            cfg.get("avatar_position", "center"),
            cfg.get("text_position", "bottom"),
        )
    except Exception:
        return None
    return discord.File(io.BytesIO(image_bytes), filename="welcome_composite.png")


async def build_composite_file(guild_id: int, member: discord.Member) -> discord.File | None:
    """เช็ค config welcome_image ของเซิร์ฟนี้ ถ้าเปิดใช้งานและตั้งค่าครบ จะ render รูปคืนมา
    ถ้ายังไม่เปิด/ตั้งค่าไม่ครบ คืนค่า None (ให้ welcome.py fallback ไปใช้ image_url แบบเดิม)"""
    cfg = (await db.get_guild_config(guild_id))["welcome_image"]
    if not cfg.get("enabled"):
        return None
    return await _render_with_cfg(cfg, guild_id, member)


class WelcomeImage(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="welcome-image-set-background",
        description="ตั้งรูปพื้นหลังสำหรับ Welcome Image (แอดมินเท่านั้น)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_background(self, interaction: discord.Interaction, image: discord.Attachment):
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
            interaction.guild_id, image.filename, data, "image", "welcome_background"
        )
        await db.update_guild_section(
            interaction.guild_id, "welcome_image", {"background_asset_id": file_id}
        )
        await interaction.followup.send(
            "✅ ตั้งรูปพื้นหลังแล้ว ใช้ `/welcome-image-preview` เพื่อดูตัวอย่าง", ephemeral=True
        )

    @app_commands.command(
        name="welcome-image-config", description="ปรับแต่งข้อความ/ฟอนต์/avatar บน Welcome Image (แอดมินเท่านั้น)"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        font="ฟอนต์ที่จะใช้เขียนข้อความ",
        text="ข้อความ (ใช้ {user_name} {server_name} {server_membercount} ได้)",
        color="สีตัวอักษร hex",
        font_size="ขนาดตัวอักษร (พิกเซล)",
        text_position="ตำแหน่งข้อความ",
        avatar_enabled="แสดง avatar วงกลมไหม",
        avatar_size="ขนาด avatar (พิกเซล)",
        avatar_position="ตำแหน่ง avatar",
    )
    @app_commands.autocomplete(font=font_autocomplete)
    @app_commands.choices(
        text_position=[app_commands.Choice(name=p, value=p) for p in POSITION_CHOICES],
        avatar_position=[app_commands.Choice(name=p, value=p) for p in POSITION_CHOICES],
    )
    async def config(
        self,
        interaction: discord.Interaction,
        font: str = None,
        text: str = None,
        color: str = None,
        font_size: int = None,
        text_position: app_commands.Choice[str] = None,
        avatar_enabled: bool = None,
        avatar_size: int = None,
        avatar_position: app_commands.Choice[str] = None,
    ):
        updates = {}
        if font is not None:
            updates["font_key"] = font
        if text is not None:
            updates["text_template"] = text
        if color is not None:
            updates["text_color"] = color
        if font_size is not None:
            updates["font_size"] = font_size
        if text_position is not None:
            updates["text_position"] = text_position.value
        if avatar_enabled is not None:
            updates["avatar_enabled"] = avatar_enabled
        if avatar_size is not None:
            updates["avatar_size"] = avatar_size
        if avatar_position is not None:
            updates["avatar_position"] = avatar_position.value

        if not updates:
            await interaction.response.send_message(
                "⚠️ ใส่พารามิเตอร์อย่างน้อย 1 อย่างที่จะปรับ", ephemeral=True
            )
            return

        await db.update_guild_section(interaction.guild_id, "welcome_image", updates)
        await interaction.response.send_message(
            f"✅ อัปเดตค่าแล้ว ({len(updates)} รายการ) ลอง `/welcome-image-preview` ดูผลลัพธ์",
            ephemeral=True,
        )

    @app_commands.command(
        name="welcome-image-toggle",
        description="เปิด/ปิดการใช้ Welcome Image แทน image_url ปกติ (แอดมินเท่านั้น)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def toggle(self, interaction: discord.Interaction, enabled: bool):
        cfg = (await db.get_guild_config(interaction.guild_id))["welcome_image"]
        if enabled and not cfg.get("background_asset_id"):
            await interaction.response.send_message(
                "⚠️ ยังไม่ได้ตั้งรูปพื้นหลัง ใช้ `/welcome-image-set-background` ก่อน", ephemeral=True
            )
            return
        await db.update_guild_section(interaction.guild_id, "welcome_image", {"enabled": enabled})
        status = "เปิดใช้งาน ✅" if enabled else "ปิดใช้งาน (กลับไปใช้ image_url ปกติ)"
        await interaction.response.send_message(f"Welcome Image: {status}", ephemeral=True)

    @app_commands.command(
        name="welcome-image-preview", description="ดูตัวอย่าง Welcome Image ปัจจุบัน"
    )
    async def preview(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        cfg = (await db.get_guild_config(interaction.guild_id))["welcome_image"]
        if not cfg.get("background_asset_id"):
            await interaction.followup.send(
                "⚠️ ยังไม่ได้ตั้งรูปพื้นหลัง ใช้ `/welcome-image-set-background` ก่อน", ephemeral=True
            )
            return

        # บังคับ render แม้ enabled=False เพื่อให้ดูตัวอย่างก่อนตัดสินใจเปิดใช้งานจริง
        forced_cfg = {**cfg, "enabled": True}
        file = await _render_with_cfg(forced_cfg, interaction.guild_id, interaction.user)
        if file is None:
            await interaction.followup.send(
                "⚠️ เรนเดอร์ไม่สำเร็จ เช็คว่าตั้งฟอนต์/รูปถูกต้องหรือยัง", ephemeral=True
            )
            return
        embed = discord.Embed(title="🖼️ ตัวอย่าง Welcome Image", color=style.DEFAULT_COLOR)
        embed.set_footer(text=f"{style.SYSTEM_ICON['welcome']} {style.BRAND}")
        embed.set_image(url="attachment://welcome_composite.png")
        await interaction.followup.send(embed=embed, file=file, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(WelcomeImage(bot))
