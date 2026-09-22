"""
cogs/info.py — ℹ️ Bot Info & Status

คำสั่ง /info — โชว์ประวัติ/สถานะของบอทตัวนี้ในที่เดียว: วันที่สร้างบัญชี Discord,
วันที่เริ่มพัฒนาโปรเจกต์, อัปเดตล่าสุด, ไอดีบอท (ไม่ใช่ token — ปลอดภัยเปิดเผยได้),
สถานะการเชื่อมต่อ MongoDB, สถานะ FFmpeg, ping, uptime, จำนวนเซิร์ฟเวอร์/ผู้ใช้

⚠️ ส่วนที่ต้องแก้เองด้วยมือ (ดูค่าคงที่ด้านล่าง):
  - BOT_CREATED_DATE — วันที่เริ่มพัฒนาโปรเจกต์จริง (ผมไม่มีข้อมูลนี้ ใส่ placeholder ไว้ก่อน)
  - LAST_UPDATED / BOT_VERSION — อัปเดตทุกครั้งที่ deploy ฟีเจอร์ใหญ่ ให้ตรงกับ COMMAND_REFERENCE.pdf
  - CHANGELOG — เพิ่มบรรทัดใหม่ด้านบนสุดทุกครั้งที่มีอัปเดตใหญ่
  - BOT_SYSTEM_COUNT / BOT_COMMAND_COUNT — ให้ตรงกับตัวเลขในคู่มือคำสั่งเสมอ

ส่วนวันที่สร้างบัญชี Discord (bot.user.created_at), ไอดีบอท, ping, uptime, จำนวนเซิร์ฟเวอร์/
ผู้ใช้ และสถานะ MongoDB/FFmpeg ดึงจากระบบจริงอัตโนมัติ ไม่ต้องแก้อะไร
"""

import logging
import platform
import time
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import db

log = logging.getLogger("beluga")

# ============================================================================
# ✍️ ค่าคงที่ที่ต้องแก้เอง — อัปเดตทุกครั้งที่มีการเปลี่ยนแปลงใหญ่
# ============================================================================

BOT_NAME = "Anyaluga"
BOT_TAGLINE = "บอทดูแลเซิร์ฟเวอร์ Beluga — ต้อนรับ/ยืนยันตัวตน/ระบบความปลอดภัย/เพลง และอื่นๆ"

# TODO: ใส่วันที่เริ่มพัฒนาโปรเจกต์จริง (รูปแบบ YYYY-MM-DD) — ผมไม่มีข้อมูลนี้ให้เดาเอง
BOT_CREATED_DATE = "2026-XX-XX"

BOT_VERSION = "Demo v.5"
LAST_UPDATED = "2026-09-22"  # วันที่อัปเดตคู่มือ/ฟีเจอร์ล่าสุด (ตรงกับ COMMAND_REFERENCE.pdf)

# ให้ตรงกับตัวเลขในคู่มือคำสั่งเสมอ (ปัจจุบันคือ 78 คำสั่ง / 15 ระบบ ตาม Demo v.5)
BOT_SYSTEM_COUNT = 15
BOT_COMMAND_COUNT = 78

# เพิ่มบรรทัดใหม่ไว้บนสุดทุกครั้งที่มีอัปเดตใหญ่ — โชว์แค่ 3 รายการล่าสุดใน /info
CHANGELOG: list[str] = [
    "🎵 Demo v.5 (2026-09-22) — เพิ่มระบบ Music & Sound System (17 คำสั่ง): คลังเพลง, EQ 11 พรีเซ็ต, ตัดเสียง/ภาพจากวิดีโอ, สีธีมต่อเซิร์ฟเวอร์",
    "📘 Demo v.4 — ปรับปรุงคู่มือคำสั่งให้ครอบคลุม 61 คำสั่ง 14 ระบบ",
]


# ============================================================================
# ℹ️ Info Cog
# ============================================================================

class Info(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # เวลาที่ cog นี้ถูกโหลด — ใช้ประมาณ uptime ของบอท (ใกล้เคียงเวลาบอทเริ่มทำงานจริง)
        self.start_time = time.monotonic()

    def _format_uptime(self) -> str:
        seconds = int(time.monotonic() - self.start_time)
        days, seconds = divmod(seconds, 86400)
        hours, seconds = divmod(seconds, 3600)
        minutes, seconds = divmod(seconds, 60)
        parts = []
        if days:
            parts.append(f"{days} วัน")
        if hours:
            parts.append(f"{hours} ชม.")
        if minutes:
            parts.append(f"{minutes} นาที")
        if not parts:
            parts.append(f"{seconds} วิ")
        return " ".join(parts)

    async def _check_mongo_status(self) -> tuple[bool, float]:
        """เช็คว่า MongoDB เชื่อมต่อได้ไหม คืนค่า (สถานะ, เวลาตอบสนอง ms)"""
        start = time.monotonic()
        try:
            await db._client.admin.command("ping")
            elapsed_ms = (time.monotonic() - start) * 1000
            return True, elapsed_ms
        except Exception as e:
            log.warning(f"[info] เช็ค MongoDB ไม่สำเร็จ: {e}")
            return False, 0.0

    def _check_ffmpeg_status(self) -> Optional[str]:
        """เช็คสถานะ FFmpeg ถ้า Music cog โหลดอยู่ — คืน None ถ้าไม่มี Music cog ในบอทนี้"""
        music_cog = self.bot.get_cog("Music")
        if music_cog is None:
            return None
        try:
            from cogs.music import FFmpegConfig
            if FFmpegConfig.check_ffmpeg_available():
                version = FFmpegConfig.get_ffmpeg_version() or "ไม่ทราบเวอร์ชั่น"
                return f"✅ พร้อมใช้งาน ({version})"
            return "❌ ไม่พบ FFmpeg บนเซิร์ฟเวอร์"
        except Exception as e:
            log.warning(f"[info] เช็ค FFmpeg ไม่สำเร็จ: {e}")
            return "⚠️ เช็คสถานะไม่สำเร็จ"

    @app_commands.command(name="info", description="ดูประวัติและสถานะการทำงานของบอทตัวนี้")
    async def info(self, interaction: discord.Interaction):
        await interaction.response.defer()

        bot_user = self.bot.user
        mongo_ok, mongo_ms = await self._check_mongo_status()
        ffmpeg_status = self._check_ffmpeg_status()

        total_members = sum(g.member_count or 0 for g in self.bot.guilds)
        ping_ms = round(self.bot.latency * 1000)

        embed = discord.Embed(
            title=f"ℹ️ {BOT_NAME} — ข้อมูลบอท",
            description=BOT_TAGLINE,
            color=0x5865F2,
        )
        if bot_user.display_avatar:
            embed.set_thumbnail(url=bot_user.display_avatar.url)

        # ---------- ประวัติ ----------
        embed.add_field(name="🆔 Bot ID", value=f"`{bot_user.id}`", inline=True)
        embed.add_field(
            name="📅 สร้างบัญชี Discord",
            value=f"<t:{int(bot_user.created_at.timestamp())}:D>",
            inline=True,
        )
        embed.add_field(name="🚀 เริ่มพัฒนาโปรเจกต์", value=BOT_CREATED_DATE, inline=True)
        embed.add_field(name="🔄 อัปเดตล่าสุด", value=f"{LAST_UPDATED} ({BOT_VERSION})", inline=True)
        embed.add_field(
            name="⚙️ ระบบทั้งหมด",
            value=f"{BOT_SYSTEM_COUNT} ระบบ / {BOT_COMMAND_COUNT} คำสั่ง",
            inline=True,
        )
        embed.add_field(name="\u200b", value="\u200b", inline=True)  # ดัน layout ให้ครบแถว

        # ---------- สถานะการทำงาน ----------
        embed.add_field(name="🏓 Ping", value=f"{ping_ms} ms", inline=True)
        embed.add_field(name="⏱️ Uptime", value=self._format_uptime(), inline=True)
        embed.add_field(name="🌐 เซิร์ฟเวอร์", value=f"{len(self.bot.guilds)} เซิร์ฟเวอร์", inline=True)
        embed.add_field(name="👥 ผู้ใช้ทั้งหมด", value=f"~{total_members:,} คน", inline=True)
        embed.add_field(
            name="🗄️ ฐานข้อมูล (MongoDB)",
            value=f"✅ เชื่อมต่อปกติ ({mongo_ms:.0f} ms)" if mongo_ok else "❌ เชื่อมต่อไม่ได้",
            inline=True,
        )
        if ffmpeg_status is not None:
            embed.add_field(name="🎚️ FFmpeg", value=ffmpeg_status, inline=True)

        # ---------- Changelog ล่าสุด ----------
        if CHANGELOG:
            recent = "\n".join(f"• {line}" for line in CHANGELOG[:3])
            embed.add_field(name="📜 อัปเดตล่าสุด", value=recent, inline=False)

        embed.set_footer(
            text=f"discord.py {discord.__version__} · Python {platform.python_version()}"
        )
        embed.timestamp = datetime.now(timezone.utc)

        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Info(bot))
