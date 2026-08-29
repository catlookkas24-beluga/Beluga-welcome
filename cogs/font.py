"""
cogs/font.py — 🔤 ระบบปรับแต่งรูปแบบอักษร (Font Preview System)
มีฟอนต์ default 5 แบบมากับระบบ + รองรับฟอนต์ custom ที่แอดมินอัปโหลดผ่าน /asset-upload
ใช้ดูตัวอย่างหน้าตาฟอนต์ก่อนตัดสินใจเลือกใช้ ไม่ได้เอาไปวางทับรูปอื่นใด ๆ
"""

import io
import os

import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont

import db

FONTS_DIR = os.path.join(os.path.dirname(__file__), "..", "fonts")

# ฟอนต์ default 5 แบบที่มากับระบบ — ไฟล์ .ttf ต้องอยู่ในโฟลเดอร์ fonts/ แล้ว
# ⚠️ Changa One และ Playwrite DE LA Guides ไม่มีตัวอักษรไทยในฟอนต์ (เช็คด้วย fontTools แล้ว)
#    พิมพ์ข้อความไทยด้วย 2 ฟอนต์นี้จะไม่ขึ้น (กล่องว่าง/สี่เหลี่ยม) — ใช้ได้เฉพาะอังกฤษ/ตัวเลข
BUILTIN_FONTS = {
    "mali": {"label": "Mali (ลายมือกลม น่ารัก)", "file": "mali.ttf", "thai": True},
    "pattaya": {"label": "Pattaya (เก๋ มีเอกลักษณ์)", "file": "pattaya.ttf", "thai": True},
    "playpen_sans_thai": {
        "label": "Playpen Sans Thai (หนา เด่น)",
        "file": "playpen_sans_thai.ttf",
        "thai": True,
    },
    "changa_one": {
        "label": "Changa One (หนา กลม) ⚠️ ไม่รองรับไทย",
        "file": "changa_one.ttf",
        "thai": False,
    },
    "playwrite_guides": {
        "label": "Playwrite DE LA Guides (ลายมือฝึกเขียน) ⚠️ ไม่รองรับไทย",
        "file": "playwrite_guides.ttf",
        "thai": False,
    },
}

BG_PRESETS = {
    "ขาว": (255, 255, 255, 255),
    "ดำ": (24, 24, 27, 255),
    "โปร่งใส": (0, 0, 0, 0),
}


def parse_hex_color(hex_str: str, default=(0, 0, 0, 255)):
    try:
        hex_str = hex_str.strip().lstrip("#")
        r, g, b = int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16)
        return (r, g, b, 255)
    except Exception:
        return default


async def load_font_bytes(guild_id: int, font_key: str) -> tuple[bytes, str] | None:
    """คืนค่า (ไฟล์ฟอนต์เป็น bytes, ชื่อที่โชว์) — เช็คทั้ง built-in และ custom ที่อัปโหลด"""
    if font_key in BUILTIN_FONTS:
        info = BUILTIN_FONTS[font_key]
        path = os.path.join(FONTS_DIR, info["file"])
        if not os.path.exists(path):
            return None
        with open(path, "rb") as f:
            return f.read(), info["label"]

    # เช็คฟอนต์ custom ที่อัปโหลดไว้ (font_key เป็น GridFS file_id)
    try:
        assets = await db.list_assets(guild_id, asset_type="font")
        match = next((a for a in assets if a["file_id"] == font_key), None)
        if match is None:
            return None
        data = await db.get_asset_bytes(font_key)
        return data, match["label"]
    except Exception:
        return None


async def font_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """แสดงรายชื่อฟอนต์เป็น dropdown อัตโนมัติ (built-in 5 แบบ + custom ที่อัปโหลดของเซิร์ฟนี้)"""
    choices = []
    current_lower = current.lower()
    for key, info in BUILTIN_FONTS.items():
        if current_lower in key.lower() or current_lower in info["label"].lower():
            choices.append(app_commands.Choice(name=info["label"][:100], value=key))
    try:
        customs = await db.list_assets(interaction.guild_id, asset_type="font")
        for a in customs:
            if current_lower in a["label"].lower():
                choices.append(app_commands.Choice(name=f"🔤 {a['label']}"[:100], value=a["file_id"]))
    except Exception:
        pass
    return choices[:25]


class Font(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="font-list", description="ดูรายชื่อฟอนต์ทั้งหมดที่มีให้ใช้")
    async def font_list(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🔤 ฟอนต์ที่มีให้ใช้", color=discord.Color.gold())
        builtin_lines = []
        for key, info in BUILTIN_FONTS.items():
            builtin_lines.append(f"• `{key}` — {info['label']}")
        embed.add_field(
            name="ฟอนต์ระบบ (5 แบบ)", value="\n".join(builtin_lines), inline=False
        )

        custom_fonts = await db.list_assets(interaction.guild_id, asset_type="font")
        if custom_fonts:
            custom_lines = [
                f"• `{a['file_id']}` — {a['label']}" for a in custom_fonts
            ]
            embed.add_field(
                name="ฟอนต์ที่อัปโหลดเอง", value="\n".join(custom_lines), inline=False
            )
        else:
            embed.add_field(
                name="ฟอนต์ที่อัปโหลดเอง",
                value="ยังไม่มี — ใช้ `/asset-upload` เพื่ออัปโหลดไฟล์ .ttf/.otf",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="font-preview", description="ดูตัวอย่างข้อความด้วยฟอนต์ที่เลือก")
    @app_commands.describe(
        text="ข้อความที่จะแสดง",
        font="เลือกฟอนต์จากรายการ",
        color="สีตัวอักษร hex (ค่าเริ่มต้น #000000)",
        background="สีพื้นหลัง",
    )
    @app_commands.choices(
        background=[app_commands.Choice(name=k, value=k) for k in BG_PRESETS]
    )
    @app_commands.autocomplete(font=font_autocomplete)
    async def font_preview(
        self,
        interaction: discord.Interaction,
        text: str,
        font: str,
        color: str = "#000000",
        background: app_commands.Choice[str] = None,
    ):
        await interaction.response.defer()

        loaded = await load_font_bytes(interaction.guild_id, font)
        if loaded is None:
            await interaction.followup.send(
                "⚠️ ไม่พบฟอนต์นี้ ลองเช็คชื่อ/ID จาก `/font-list` อีกครั้ง"
            )
            return
        font_bytes, font_label = loaded

        bg_name = background.value if background else "ขาว"
        bg_rgba = BG_PRESETS.get(bg_name, (255, 255, 255, 255))
        text_rgba = parse_hex_color(color)

        try:
            image_bytes = render_text_preview(text, font_bytes, text_rgba, bg_rgba)
        except Exception as e:
            await interaction.followup.send(f"⚠️ เรนเดอร์รูปไม่สำเร็จ: `{e}`")
            return

        file = discord.File(io.BytesIO(image_bytes), filename="font_preview.png")
        embed = discord.Embed(
            title="🔤 ตัวอย่างฟอนต์",
            description=f"ฟอนต์: **{font_label}**",
            color=discord.Color.gold(),
        )
        embed.set_image(url="attachment://font_preview.png")
        await interaction.followup.send(embed=embed, file=file)


def render_text_preview(
    text: str, font_bytes: bytes, text_rgba: tuple, bg_rgba: tuple, font_size: int = 64
) -> bytes:
    """วาดข้อความตัวอย่างลงพื้นหลังสีเรียบ คืนค่าเป็น PNG bytes"""
    font_obj = ImageFont.truetype(io.BytesIO(font_bytes), font_size)

    # วัดขนาดข้อความก่อน เพื่อกำหนดขนาดรูปให้พอดี
    dummy_img = Image.new("RGBA", (10, 10))
    dummy_draw = ImageDraw.Draw(dummy_img)
    bbox = dummy_draw.textbbox((0, 0), text, font=font_obj)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    padding = 40
    img_w, img_h = text_w + padding * 2, text_h + padding * 2
    img = Image.new("RGBA", (img_w, img_h), bg_rgba)
    draw = ImageDraw.Draw(img)
    draw.text((padding - bbox[0], padding - bbox[1]), text, font=font_obj, fill=text_rgba)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def setup(bot: commands.Bot):
    await bot.add_cog(Font(bot))
