"""
cogs/info.py — ℹ️ Bot Info & Status

คำสั่ง /info — โชว์ประวัติ/สถานะของบอทตัวนี้ในที่เดียว: วันที่สร้างบัญชี Discord,
วันที่เริ่มพัฒนาโปรเจกต์, เวอร์ชันปัจจุบัน, changelog ล่าสุด, ไอดีบอท (ไม่ใช่ token —
เปิดเผยได้ปลอดภัย), สถานะ MongoDB, สถานะ FFmpeg, ping, uptime, CPU/RAM, จำนวนเซิร์ฟเวอร์/ผู้ใช้

⚙️ แก้ข้อมูลโปรเจกต์ (วันที่เริ่ม/เวอร์ชัน/changelog) ผ่าน /info-edit — เปิดเป็น Modal (popup
ฟอร์ม) ให้กรอกรหัสยืนยัน + รายละเอียด แบบส่วนตัว ไม่มีใครในห้องเห็นค่าที่กรอก

📅 /info-set-created-here — ตั้ง "วันที่เริ่มพัฒนาโปรเจกต์" อัตโนมัติจากวันที่สร้าง
เซิร์ฟเวอร์ที่ใช้คำสั่งนี้ (ไม่ต้องพิมพ์วันที่เอง กันพิมพ์ผิด) — ใช้คำสั่งนี้ในเซิร์ฟเวอร์
หลักของโปรเจกต์ (เช่น Beluga) ถ้าบอทอยู่หลายเซิร์ฟ ต้องเลือกรันในอันที่ถูกต้องเอง

⚠️ ทำไมใช้ Modal แทนใส่รหัสเป็น parameter ของ slash command ตรงๆ:
Discord โชว์ "[ชื่อคุณ] used /คำสั่ง พร้อมค่าพารามิเตอร์ทั้งหมด" ให้ทุกคนในห้องเห็น
แม้บอทจะตอบกลับแบบ ephemeral ก็ตาม — ถ้าใส่รหัสเป็น parameter ตรงๆ รหัสจะหลุดทันที
Modal เป็นวิธีเดียวที่ Discord ให้กรอกข้อมูลแบบส่วนตัวจริงๆ (เห็นแค่คนพิมพ์คนเดียว)

🔑 ต้องตั้ง environment variable INFO_EDIT_CODE บน Render ก่อนถึงจะใช้ /info-edit ได้
(ถ้าไม่ตั้งไว้ ระบบจะปฏิเสธการแก้ไขทุกครั้ง เป็นค่า default แบบปลอดภัยไว้ก่อน)
เจ้าของบอท (ตามที่ตั้งใน Discord Developer Portal) ข้ามรหัสได้เลยไม่ต้องกรอก

📦 ต้องติดตั้งเพิ่ม: pip install psutil (ใส่ใน requirements.txt ด้วย) — ใช้อ่าน CPU/RAM
"""

import asyncio
import hmac
import logging
import os
import platform
import time
from datetime import datetime, timezone
from typing import Optional

import discord
import psutil
from discord import app_commands
from discord.ext import commands

import db

log = logging.getLogger("beluga")

BOT_NAME = "Anyaluga"
BOT_TAGLINE = "บอทดูแลเซิร์ฟเวอร์ Beluga — ต้อนรับ/ยืนยันตัวตน/ระบบความปลอดภัย/เพลง และอื่นๆ"

# แสดงกี่รายการล่าสุดใน /info (ดูทั้งหมดได้ที่ /info-list-changelog)
CHANGELOG_PREVIEW_COUNT = 3


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _is_valid_date(date_str: str) -> bool:
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _code_is_correct(entered: str) -> bool:
    """เทียบรหัสแบบ constant-time กัน timing attack — คืน False เสมอถ้ายังไม่ได้ตั้ง INFO_EDIT_CODE ไว้"""
    secret = os.environ.get("INFO_EDIT_CODE")
    if not secret:
        return False
    return hmac.compare_digest(entered.strip(), secret)


# ============================================================================
# 📝 Modal — ฟอร์มแก้ไขข้อมูลบอทแบบส่วนตัว (รหัส+ค่าไม่มีใครเห็นนอกจากคนกรอก)
# ============================================================================

class InfoEditModal(discord.ui.Modal, title="แก้ไขข้อมูลบอท"):
    code = discord.ui.TextInput(
        label="รหัสยืนยัน",
        placeholder="กรอกรหัสยืนยัน (เจ้าของบอทเว้นว่างได้)",
        required=False,
        max_length=100,
    )
    action = discord.ui.TextInput(
        label="ประเภท (created/version/changelog/remove)",
        placeholder="เช่น version",
        max_length=20,
    )
    value = discord.ui.TextInput(
        label="ค่า",
        style=discord.TextStyle.paragraph,
        placeholder="created→YYYY-MM-DD | version→v1.2 | changelog→ข้อความ | remove→เลข index",
        max_length=300,
    )

    def __init__(self, cog: "Info"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        is_owner = await self.cog.bot.is_owner(interaction.user)
        if not is_owner and not _code_is_correct(self.code.value):
            await interaction.response.send_message("⛔ รหัสยืนยันไม่ถูกต้องครับ", ephemeral=True)
            return

        action_type = self.action.value.strip().lower()
        val = self.value.value.strip()

        if action_type == "created":
            if not _is_valid_date(val):
                await interaction.response.send_message("⛔ รูปแบบวันที่ผิดครับ ใช้ YYYY-MM-DD เช่น 2026-06-01", ephemeral=True)
                return
            await db.set_bot_created_date(val)
            await interaction.response.send_message(f"✅ ตั้งวันที่เริ่มพัฒนาโปรเจกต์เป็น **{val}** แล้วครับ", ephemeral=True)

        elif action_type == "version":
            today = _today_str()
            await db.set_bot_version(val, today)
            await interaction.response.send_message(f"✅ ตั้งเวอร์ชันเป็น **{val}** แล้วครับ (อัปเดตล่าสุด: {today})", ephemeral=True)

        elif action_type == "changelog":
            today = _today_str()
            full_entry = f"({today}) {val}"
            await db.add_bot_changelog(full_entry)
            await db.set_bot_last_updated(today)
            await interaction.response.send_message(f"✅ เพิ่ม changelog แล้วครับ:\n> {full_entry}", ephemeral=True)

        elif action_type == "remove":
            try:
                idx = int(val)
            except ValueError:
                await interaction.response.send_message("⛔ ช่อง 'ค่า' ต้องเป็นเลข index ครับ (ดูได้จาก /info-list-changelog)", ephemeral=True)
                return
            removed = await db.remove_bot_changelog(idx)
            if removed:
                await interaction.response.send_message(f"🗑️ ลบ changelog รายการที่ `{idx}` แล้วครับ", ephemeral=True)
            else:
                await interaction.response.send_message("⛔ ไม่เจอ index นี้ครับ", ephemeral=True)

        else:
            await interaction.response.send_message(
                "⛔ ประเภทไม่ถูกต้องครับ ใช้ได้แค่: `created`, `version`, `changelog`, `remove`",
                ephemeral=True,
            )


class SetCreatedFromGuildModal(discord.ui.Modal, title="ตั้งวันที่เริ่มโปรเจกต์"):
    code = discord.ui.TextInput(
        label="รหัสยืนยัน",
        placeholder="กรอกรหัสยืนยัน (เจ้าของบอทเว้นว่างได้)",
        required=False,
        max_length=100,
    )

    def __init__(self, cog: "Info"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        is_owner = await self.cog.bot.is_owner(interaction.user)
        if not is_owner and not _code_is_correct(self.code.value):
            await interaction.response.send_message("⛔ รหัสยืนยันไม่ถูกต้องครับ", ephemeral=True)
            return

        if interaction.guild is None:
            await interaction.response.send_message(
                "⛔ ต้องใช้คำสั่งนี้ในเซิร์ฟเวอร์ครับ (ใช้ใน DM ไม่ได้ เพราะไม่มีวันที่สร้างเซิร์ฟเวอร์ให้อ้างอิง)",
                ephemeral=True,
            )
            return

        date_str = interaction.guild.created_at.strftime("%Y-%m-%d")
        await db.set_bot_created_date(date_str)
        await interaction.response.send_message(
            f"✅ ตั้งวันที่เริ่มพัฒนาโปรเจกต์เป็น **{date_str}** แล้วครับ "
            f"(ดึงจากวันที่สร้างเซิร์ฟเวอร์ **{interaction.guild.name}**)",
            ephemeral=True,
        )


# ============================================================================
# 🔴 Live Update — ปุ่มให้บอทแก้ไขข้อความเดิมทุกไม่กี่วินาที (ไม่ใช่ push จริงจาก Discord
# เพราะ Discord ไม่มีระบบนั้น แต่ผลที่เห็นจะเหมือน real-time)
# ============================================================================

LIVE_UPDATE_INTERVAL = 3     # วินาทีต่อการอัปเดตหนึ่งครั้ง — เร็วกว่านี้เสี่ยงโดน rate limit
LIVE_DURATION_SECONDS = 180  # หยุดอัตโนมัติหลังจากนี้ กันลืมปิดแล้วรันค้างไปเรื่อยๆ


class LiveInfoView(discord.ui.View):
    def __init__(self, cog: "Info", embed: discord.Embed, field_indices: dict):
        super().__init__(timeout=LIVE_DURATION_SECONDS + 30)
        self.cog = cog
        self.embed = embed
        self.field_indices = field_indices
        self.is_live = False
        self.task: Optional[asyncio.Task] = None
        self.message: Optional[discord.Message] = None

    @discord.ui.button(label="🔴 อัปเดตสด", style=discord.ButtonStyle.danger)
    async def toggle_live(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.is_live:
            self.is_live = True
            button.label = "⏹️ หยุดอัปเดตสด"
            button.style = discord.ButtonStyle.secondary
            self.message = interaction.message
            await interaction.response.edit_message(view=self)
            self.task = asyncio.create_task(self._live_loop())
        else:
            await self._stop_live()
            await interaction.response.edit_message(view=self)

    async def _live_loop(self):
        elapsed = 0
        try:
            while elapsed < LIVE_DURATION_SECONDS:
                await asyncio.sleep(LIVE_UPDATE_INTERVAL)
                elapsed += LIVE_UPDATE_INTERVAL

                cpu, ram_used, ram_total, bot_ram = self.cog._get_resource_usage()
                ping_ms = round(self.cog.bot.latency * 1000)
                uptime = self.cog._format_uptime()

                fi = self.field_indices
                self.embed.set_field_at(fi["ping"], name="🏓 Ping", value=f"{ping_ms} ms", inline=True)
                self.embed.set_field_at(fi["uptime"], name="⏱️ Uptime", value=uptime, inline=True)
                self.embed.set_field_at(fi["cpu"], name="🖥️ CPU", value=f"{cpu:.1f}%", inline=True)
                self.embed.set_field_at(
                    fi["ram"], name="💾 RAM (เครื่อง)",
                    value=f"{ram_used:,.0f} / {ram_total:,.0f} MB", inline=True,
                )
                self.embed.set_field_at(fi["bot_ram"], name="🤖 RAM (เฉพาะบอท)", value=f"{bot_ram:,.0f} MB", inline=True)
                self.embed.timestamp = datetime.now(timezone.utc)

                if self.message is not None:
                    await self.message.edit(embed=self.embed)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.warning(f"[info] live update loop หยุดเพราะ error: {e}")
        finally:
            self.is_live = False
            for child in self.children:
                if isinstance(child, discord.ui.Button):
                    child.label = "🔴 อัปเดตสด (หมดเวลา — กดใหม่ได้)"
                    child.style = discord.ButtonStyle.danger
            if self.message is not None:
                try:
                    await self.message.edit(view=self)
                except discord.HTTPException:
                    pass

    async def _stop_live(self):
        self.is_live = False
        if self.task is not None:
            self.task.cancel()
            self.task = None
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.label = "🔴 อัปเดตสด"
                child.style = discord.ButtonStyle.danger

    async def on_timeout(self):
        if self.task is not None:
            self.task.cancel()
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


# ============================================================================
# ℹ️ Info Cog
# ============================================================================

class Info(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.start_time = time.monotonic()
        # เรียก cpu_percent ครั้งแรกไว้ล่วงหน้า (ค่ารอบแรกไม่มีความหมาย ทิ้งไป) เพื่อให้
        # /info เรียกครั้งถัดไปได้ค่า non-blocking ที่แม่นจริงแทนที่จะต้องรอ interval
        psutil.cpu_percent(interval=None)
        self._process = psutil.Process()

    # ---------- Helpers ----------

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
        start = time.monotonic()
        try:
            await db._client.admin.command("ping")
            return True, (time.monotonic() - start) * 1000
        except Exception as e:
            log.warning(f"[info] เช็ค MongoDB ไม่สำเร็จ: {e}")
            return False, 0.0

    def _check_ffmpeg_status(self) -> Optional[str]:
        if self.bot.get_cog("Music") is None:
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

    def _get_resource_usage(self) -> tuple[float, float, float, float]:
        """คืน (cpu_percent ทั้งระบบ, ram_used_mb ทั้งระบบ, ram_total_mb ทั้งระบบ, ram_bot_mb เฉพาะโปรเซสบอท)"""
        cpu_percent = psutil.cpu_percent(interval=None)
        vm = psutil.virtual_memory()
        ram_used_mb = vm.used / (1024 ** 2)
        ram_total_mb = vm.total / (1024 ** 2)
        bot_ram_mb = self._process.memory_info().rss / (1024 ** 2)
        return cpu_percent, ram_used_mb, ram_total_mb, bot_ram_mb

    # ---------- /info ----------

    @app_commands.command(name="info", description="ดูประวัติและสถานะการทำงานของบอทตัวนี้")
    async def info(self, interaction: discord.Interaction):
        await interaction.response.defer()

        bot_user = self.bot.user
        meta = await db.get_bot_meta()
        mongo_ok, mongo_ms = await self._check_mongo_status()
        ffmpeg_status = self._check_ffmpeg_status()
        cpu_percent, ram_used_mb, ram_total_mb, bot_ram_mb = self._get_resource_usage()

        total_members = sum(g.member_count or 0 for g in self.bot.guilds)
        ping_ms = round(self.bot.latency * 1000)

        created_date = meta["created_date"] or "ยังไม่ได้ตั้งค่า (ใช้ /info-edit)"
        version = meta["version"] or "ยังไม่ได้ตั้งค่า"
        last_updated = meta["last_updated"] or "ยังไม่ได้ตั้งค่า"

        embed = discord.Embed(
            title=f"ℹ️ {BOT_NAME} — ข้อมูลบอท",
            description=BOT_TAGLINE,
            color=0x5865F2,
        )
        if bot_user.display_avatar:
            embed.set_thumbnail(url=bot_user.display_avatar.url)

        embed.add_field(name="🆔 Bot ID", value=f"`{bot_user.id}`", inline=True)
        embed.add_field(
            name="📅 สร้างบัญชี Discord",
            value=f"<t:{int(bot_user.created_at.timestamp())}:D>",
            inline=True,
        )
        embed.add_field(name="🚀 เริ่มพัฒนาโปรเจกต์", value=created_date, inline=True)
        embed.add_field(name="🏷️ เวอร์ชันปัจจุบัน", value=version, inline=True)
        embed.add_field(name="🔄 อัปเดตล่าสุด", value=last_updated, inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)

        embed.add_field(name="🏓 Ping", value=f"{ping_ms} ms", inline=True)
        ping_idx = len(embed.fields) - 1
        embed.add_field(name="⏱️ Uptime", value=self._format_uptime(), inline=True)
        uptime_idx = len(embed.fields) - 1
        embed.add_field(name="🌐 เซิร์ฟเวอร์", value=f"{len(self.bot.guilds)} เซิร์ฟเวอร์", inline=True)
        embed.add_field(name="👥 ผู้ใช้ทั้งหมด", value=f"~{total_members:,} คน", inline=True)
        embed.add_field(
            name="🗄️ MongoDB",
            value=f"✅ ปกติ ({mongo_ms:.0f} ms)" if mongo_ok else "❌ เชื่อมต่อไม่ได้",
            inline=True,
        )
        if ffmpeg_status is not None:
            embed.add_field(name="🎚️ FFmpeg", value=ffmpeg_status, inline=True)

        embed.add_field(name="🖥️ CPU", value=f"{cpu_percent:.1f}%", inline=True)
        cpu_idx = len(embed.fields) - 1
        embed.add_field(name="💾 RAM (เครื่อง)", value=f"{ram_used_mb:,.0f} / {ram_total_mb:,.0f} MB", inline=True)
        ram_idx = len(embed.fields) - 1
        embed.add_field(name="🤖 RAM (เฉพาะบอท)", value=f"{bot_ram_mb:,.0f} MB", inline=True)
        bot_ram_idx = len(embed.fields) - 1

        if meta["changelog"]:
            recent = "\n".join(f"• {line}" for line in meta["changelog"][:CHANGELOG_PREVIEW_COUNT])
            more = len(meta["changelog"]) - CHANGELOG_PREVIEW_COUNT
            if more > 0:
                recent += f"\n-# และอีก {more} รายการ — ดูทั้งหมดที่ /info-list-changelog"
            embed.add_field(name="📜 Changelog ล่าสุด", value=recent, inline=False)

        embed.set_footer(text=f"discord.py {discord.__version__} · Python {platform.python_version()} · กด 🔴 เพื่อดูสถานะสดทุก {LIVE_UPDATE_INTERVAL} วิ")
        embed.timestamp = datetime.now(timezone.utc)

        field_indices = {
            "ping": ping_idx,
            "uptime": uptime_idx,
            "cpu": cpu_idx,
            "ram": ram_idx,
            "bot_ram": bot_ram_idx,
        }
        view = LiveInfoView(self, embed, field_indices)
        sent_message = await interaction.followup.send(embed=embed, view=view)
        view.message = sent_message

    # ---------- แก้ไขข้อมูลโปรเจกต์ ----------

    @app_commands.command(name="info-edit", description="แก้ไขข้อมูลบอท (เปิดฟอร์มกรอกรหัสยืนยันแบบส่วนตัว)")
    async def info_edit(self, interaction: discord.Interaction):
        await interaction.response.send_modal(InfoEditModal(self))

    @app_commands.command(
        name="info-set-created-here",
        description="ตั้งวันที่เริ่มพัฒนาโปรเจกต์ = วันที่สร้างเซิร์ฟเวอร์นี้ (ใช้ในเซิร์ฟเวอร์หลักของโปรเจกต์)",
    )
    async def info_set_created_here(self, interaction: discord.Interaction):
        await interaction.response.send_modal(SetCreatedFromGuildModal(self))

    @app_commands.command(name="info-list-changelog", description="ดู changelog ทั้งหมดพร้อมเลข index")
    async def info_list_changelog(self, interaction: discord.Interaction):
        meta = await db.get_bot_meta()
        changelog = meta["changelog"]
        if not changelog:
            await interaction.response.send_message("ยังไม่มี changelog เลยครับ ลองเพิ่มด้วย `/info-edit`")
            return
        lines = [f"`{i}` — {entry}" for i, entry in enumerate(changelog)]
        embed = discord.Embed(title="📜 Changelog ทั้งหมด", description="\n".join(lines[:25]), color=0x5865F2)
        if len(lines) > 25:
            embed.set_footer(text=f"แสดง 25 จากทั้งหมด {len(lines)} รายการ")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Info(bot))
