"""
welcome_card.py — สร้างการ์ดต้อนรับ (Pillow) สำหรับ Anyaluga
ติดตั้งก่อนใช้งาน: pip install Pillow aiohttp
ต้องมีโฟลเดอร์ fonts/ (LINESeedSansTH_Bd.ttf, LINESeedSansTH_Rg.ttf) วางไว้ข้างๆ main.py
"""

import io
import os
import aiohttp
from PIL import Image, ImageDraw, ImageFont, ImageOps

FONT_DIR = os.path.join(os.path.dirname(__file__), 'fonts')
FONT_PATH_BOLD = os.path.join(FONT_DIR, 'LINESeedSansTH_Bd.ttf')
FONT_PATH_REGULAR = os.path.join(FONT_DIR, 'LINESeedSansTH_Rg.ttf')


async def _download_avatar_bytes(url: str) -> bytes:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            resp.raise_for_status()
            return await resp.read()


async def build_welcome_card(member) -> io.BytesIO:
    """สร้างการ์ดต้อนรับเป็น PNG แล้ว return เป็น BytesIO (ใช้กับ discord.File ได้ทันที)"""
    width, height = 900, 350
    card = Image.new("RGB", (width, height), color="#1e3c72")
    draw = ImageDraw.Draw(card)

    # gradient พื้นหลัง
    top_color = (30, 60, 114)
    bottom_color = (42, 82, 152)
    for x in range(width):
        ratio = x / width
        r = int(top_color[0] + (bottom_color[0] - top_color[0]) * ratio)
        g = int(top_color[1] + (bottom_color[1] - top_color[1]) * ratio)
        b = int(top_color[2] + (bottom_color[2] - top_color[2]) * ratio)
        draw.line([(x, 0), (x, height)], fill=(r, g, b))

    draw.rectangle([10, 10, width - 10, height - 10], outline=(255, 255, 255), width=6)

    # avatar วงกลม
    avatar_url = member.display_avatar.replace(size=256, format="png").url
    avatar_bytes = await _download_avatar_bytes(avatar_url)
    avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
    avatar_size = 180
    avatar_img = ImageOps.fit(avatar_img, (avatar_size, avatar_size))

    mask = Image.new("L", (avatar_size, avatar_size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, avatar_size, avatar_size), fill=255)
    avatar_img.putalpha(mask)

    avatar_x, avatar_y = 60, height // 2 - avatar_size // 2
    card.paste(avatar_img, (avatar_x, avatar_y), avatar_img)
    draw.ellipse(
        [avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size],
        outline="white",
        width=6,
    )

    # ฟอนต์ (ล้มเหลว = fallback เป็นฟอนต์ default, ตัวไทยจะไม่ขึ้น)
    try:
        font_title = ImageFont.truetype(FONT_PATH_BOLD, 40)
        font_name = ImageFont.truetype(FONT_PATH_BOLD, 34)
        font_sub = ImageFont.truetype(FONT_PATH_REGULAR, 24)
        font_small = ImageFont.truetype(FONT_PATH_REGULAR, 20)
    except OSError:
        font_title = font_name = font_sub = font_small = ImageFont.load_default()

    text_x = 280
    draw.text((text_x, 100), "WELCOME", font=font_title, fill="white")

    display_name = member.display_name
    if len(display_name) > 18:
        display_name = display_name[:16] + "…"
    draw.text((text_x, 160), display_name, font=font_name, fill="#ffdd57")

    draw.text(
        (text_x, 205),
        f"สมาชิกลำดับที่ {member.guild.member_count}",
        font=font_sub,
        fill="#e0e0e0",
    )
    draw.text((text_x, 245), member.guild.name, font=font_small, fill="#b0c4de")

    buffer = io.BytesIO()
    card.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer
