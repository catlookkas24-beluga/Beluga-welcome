# -*- coding: utf-8 -*-
"""
style.py — 🌸 ชุดสไตล์กลางของ Anyaluga (Cute Pastel Edition)

ทุก embed / ข้อความตอบกลับของบอทควรผ่านไฟล์นี้ เพื่อให้หน้าตาเป็นแบรนด์เดียวกัน:
สีพาสเทลสดใส • อีโมจิเยอะ • น้ำเสียงน่ารัก

ใช้ง่าย:
    import style
    style.success("ตั้งค่าเรียบร้อย")        # 🌸 เขียวมิ้นต์
    style.error("ไม่พบไฟล์")                # 🙈 ชมพูโคราล
    style.warn("ยังไม่ได้ตั้งค่า")           # 🍯 เหลืองเนย
    style.info("มีอะไรมาบอก")               # 💌 ฟ้าสกาย
    style.brand_embed(title=..., system="music")   # embed พื้นฐาน + footer แบรนด์

API เดิม (brand_embed / success / error / warn / theme_color / DIVIDER / BRAND /
SYSTEM_ICON / DEFAULT_COLOR / COLOR_*) ยังใช้ได้เหมือนเดิมทั้งหมด
"""

import random
from datetime import datetime, timezone

import discord

import db

# ============================================================================
# 🎨 Palette — พาสเทลสดใส
# ============================================================================

DEFAULT_COLOR = 0xFF9EC4   # 🍬 ชมพูบับเบิ้ลกัม (สีหลักของแบรนด์)
COLOR_SUCCESS = 0x8FE3B0   # 🍃 เขียวมิ้นต์
COLOR_ERROR = 0xFF7A8A     # 🍓 ชมพูโคราล
COLOR_WARN = 0xFFD98E      # 🍯 เหลืองเนย
COLOR_INFO = 0xA5D8FF      # ☁️ ฟ้าสกาย
COLOR_LAVENDER = 0xC4B5FD  # 🔮 ลาเวนเดอร์
COLOR_PEACH = 0xFFB38A     # 🍑 พีช
COLOR_LEMON = 0xFFF1A8     # 🍋 เลมอน

# ============================================================================
# ✨ ตัวประกอบฉาก
# ============================================================================

DIVIDER = "🌸 ┈┈┈┈ ✿ ┈┈┈┈ 🌸"
BRAND = "Anyaluga ♡"

# ไอคอนประจำแต่ละระบบ — ใช้ต่อท้าย footer ให้รู้ทันทีว่า embed นี้มาจากระบบไหน
SYSTEM_ICON = {
    "welcome": "🌸",
    "goodbye": "🌙",
    "verify": "🎀",
    "rules": "📖",
    "antiraid": "🛡️",
    "autorole": "🍓",
    "ticket": "🎫",
    "activity": "🐣",
    "music": "🎧",
    "assets": "🧸",
    "font": "🖋️",
    "theme": "🎨",
    "permissions": "🔐",
    "cmdperms": "🗝️",
    "panel": "🎛️",
    "force": "⚡",
    "info": "💡",
}

# หัวข้อสุ่ม — ให้บอทดูมีชีวิตชีวา ไม่จำเจ
_SUCCESS_TITLES = ["สำเร็จแล้วน้า~", "เรียบร้อยจ้า", "เสร็จแล้วว~", "จัดให้เรียบร้อย!"]
_ERROR_TITLES = ["อุ๊ปส์! ไม่สำเร็จ", "เอ๊ะ มีอะไรผิดพลาด", "ขอโทษน้า ทำไม่ได้"]
_WARN_TITLES = ["โปรดทราบน้า", "แป๊บนึงนะ", "ระวังนิดนึง"]
_INFO_TITLES = ["มีข่าวมาบอก~", "ข้อมูลน้อย ๆ", "รู้ไว้นะ"]

SUCCESS_EMOJI = ["🌸", "✨", "🎀", "💖"]
ERROR_EMOJI = ["🙈", "🥺", "💦"]
WARN_EMOJI = ["🍯", "🌼", "⚠️"]
INFO_EMOJI = ["💌", "☁️", "🫧"]


def heart_bar(ratio: float, length: int = 10, *, head: str = "🌸",
              filled: str = "💗", empty: str = "🤍") -> str:
    """แถบอีโมจิน่ารัก ๆ — ratio 0.0-1.0 (ใช้ทำ progress / EQ)"""
    ratio = max(0.0, min(1.0, ratio))
    n = max(0, min(length - 1, int(ratio * length)))
    return filled * n + head + empty * (length - n - 1)


def footer(system: str | None = None, extra: str | None = None) -> str:
    """ข้อความ footer มาตรฐาน: '🌸 Anyaluga ♡ • ข้อความเสริม'"""
    text = f"{SYSTEM_ICON.get(system, '✨')} {BRAND}"
    if extra:
        text += f" • {extra}"
    return text


def clip(text: str, limit: int) -> str:
    """ตัดข้อความให้ไม่เกินลิมิตของ Discord (title 256 / field 1024 ฯลฯ)"""
    text = str(text)
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


async def theme_color(guild_id: int, section: str) -> int:
    """ดึงสีธีมที่ตั้งไว้ผ่าน /theme-set-color สำหรับ section นี้ (welcome/goodbye/verify/rules/ticket/music)
    ถ้ายังไม่ได้ตั้งจะคืนค่า DEFAULT_COLOR ให้อัตโนมัติ"""
    try:
        cfg = await db.get_guild_config(guild_id)
        raw = (cfg.get(section, {}) or {}).get("color")
        if raw:
            return int(str(raw).lstrip("#"), 16)
    except Exception:
        pass
    return DEFAULT_COLOR


def brand_embed(
    *,
    title: str | None = None,
    description: str | None = None,
    color: int | None = None,
    system: str | None = None,
    footer_extra: str | None = None,
    thumbnail: str | None = None,
    image: str | None = None,
    author_name: str | None = None,
    author_icon: str | None = None,
    timestamp: bool = True,
) -> discord.Embed:
    """สร้าง embed พื้นฐานที่มีแบรนด์ Anyaluga ติดมาให้ครบ — ใช้แทน discord.Embed(...) ตรงๆ"""
    embed = discord.Embed(
        title=clip(title, 256) if title else None,
        description=clip(description, 4096) if description else None,
        color=color if color is not None else DEFAULT_COLOR,
    )
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    if image:
        embed.set_image(url=image)
    if author_name:
        embed.set_author(name=author_name, icon_url=author_icon)

    embed.set_footer(text=footer(system, footer_extra))

    if timestamp:
        embed.timestamp = datetime.now(timezone.utc)
    return embed


def _status_embed(emoji_pool, title_pool, color, description, title, system, footer_extra):
    emoji = random.choice(emoji_pool)
    heading = title if title else random.choice(title_pool)
    return brand_embed(
        title=f"{emoji} {heading}",
        description=description,
        color=color,
        system=system,
        footer_extra=footer_extra,
    )


def success(description: str, *, title: str | None = None, system: str | None = None,
            footer_extra: str | None = None) -> discord.Embed:
    return _status_embed(SUCCESS_EMOJI, _SUCCESS_TITLES, COLOR_SUCCESS, description, title, system, footer_extra)


def error(description: str, *, title: str | None = None, system: str | None = None,
          footer_extra: str | None = None) -> discord.Embed:
    return _status_embed(ERROR_EMOJI, _ERROR_TITLES, COLOR_ERROR, description, title, system, footer_extra)


def warn(description: str, *, title: str | None = None, system: str | None = None,
         footer_extra: str | None = None) -> discord.Embed:
    return _status_embed(WARN_EMOJI, _WARN_TITLES, COLOR_WARN, description, title, system, footer_extra)


def info(description: str, *, title: str | None = None, system: str | None = None,
         footer_extra: str | None = None) -> discord.Embed:
    return _status_embed(INFO_EMOJI, _INFO_TITLES, COLOR_INFO, description, title, system, footer_extra)
