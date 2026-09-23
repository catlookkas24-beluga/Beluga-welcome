# -*- coding: utf-8 -*-
"""
style.py — 🎨 ชุดสไตล์ embed กลางของ Anyaluga
รวมทุกอย่างที่ทำให้ embed ทั้งบอทหน้าตาเป็นแบรนด์เดียวกัน: สี, footer, divider, ไอคอนต่อระบบ
ใช้ง่าย: import style แล้วเรียก style.brand_embed(...) / style.success(...) / style.error(...)
"""

from datetime import datetime, timezone

import discord

import db

DEFAULT_COLOR = 0x5865F2       # blurple — สีตั้งต้นเวลายังไม่มีธีมกำหนดเอง
COLOR_SUCCESS = 0x57F287       # เขียว
COLOR_ERROR = 0xED4245         # แดง
COLOR_WARN = 0xFEE75C          # เหลือง

DIVIDER = "┄" * 22
BRAND = "Anyaluga"

# ไอคอนประจำแต่ละระบบ — ใช้ต่อท้าย footer ให้รู้ทันทีว่า embed นี้มาจากระบบไหน
SYSTEM_ICON = {
    "welcome": "👋",
    "goodbye": "🚪",
    "verify": "🛡️",
    "rules": "📜",
    "antiraid": "🚨",
    "autorole": "⏳",
    "ticket": "🎫",
    "activity": "📊",
    "music": "🎵",
    "assets": "🗂️",
    "font": "🔤",
    "theme": "🎨",
    "permissions": "🔐",
    "cmdperms": "🔑",
    "panel": "🕹️",
    "force": "⚡",
    "info": "ℹ️",
}


async def theme_color(guild_id: int, section: str) -> int:
    """ดึงสีธีมที่ตั้งไว้ผ่าน /theme-set-color สำหรับ section นี้ (welcome/goodbye/verify/rules/ticket)
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
        title=title,
        description=description,
        color=color if color is not None else DEFAULT_COLOR,
    )
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    if image:
        embed.set_image(url=image)
    if author_name:
        embed.set_author(name=author_name, icon_url=author_icon)

    icon = SYSTEM_ICON.get(system, "✨")
    footer = f"{icon} {BRAND}"
    if footer_extra:
        footer += f" • {footer_extra}"
    embed.set_footer(text=footer)

    if timestamp:
        embed.timestamp = datetime.now(timezone.utc)
    return embed


def success(description: str, *, title: str = "สำเร็จ", system: str | None = None,
            footer_extra: str | None = None) -> discord.Embed:
    return brand_embed(title=f"✅ {title}", description=description,
                        color=COLOR_SUCCESS, system=system, footer_extra=footer_extra)


def error(description: str, *, title: str = "ทำรายการไม่สำเร็จ", system: str | None = None,
          footer_extra: str | None = None) -> discord.Embed:
    return brand_embed(title=f"⛔ {title}", description=description,
                        color=COLOR_ERROR, system=system, footer_extra=footer_extra)


def warn(description: str, *, title: str = "โปรดทราบ", system: str | None = None,
         footer_extra: str | None = None) -> discord.Embed:
    return brand_embed(title=f"⚠️ {title}", description=description,
                        color=COLOR_WARN, system=system, footer_extra=footer_extra)
