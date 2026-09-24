"""
cogs/music.py — 🎧 Music Player (Cute Pastel Edition 🌸)

เล่นเพลงจาก "คลังเพลง" (ลิงก์ไฟล์เสียงตรง) ไม่ผ่าน YouTube เลย เลยไม่โดนบล็อก IP ของ cloud server
เก็บชื่อ+ลิงก์ไว้ใน MongoDB ผ่าน db.py

⚙️ ข้อกำหนด:
  • FFmpeg 9.0.2+ บนเครื่อง/เซิร์ฟที่รันบอท (ไม่ใช่ pip package)
  • discord.py พร้อม voice support (+ davey สำหรับ voice เข้ารหัสของ Discord)

ขั้นตอนใช้งาน:
  1. /addsongfromvideo แนบไฟล์วิดีโอ/เสียง → บอทตัดเสียงให้ + เก็บลิงก์ไว้ในคลัง (ลิงก์ไม่หมดอายุ
     เพราะบอทจำที่อยู่ข้อความไว้แล้วดึงลิงก์ใหม่ทุกครั้งก่อนเล่น)
     หรือ /addsong ชื่อ ลิงก์ — ถ้ามีลิงก์ตรงจากที่อื่นอยู่แล้ว (ลิงก์ CDN ของ Discord จะหมดอายุเอง ไม่แนะนำ)
  2. /play ชื่อเพลง (มี autocomplete) หรือ /play ลิงก์ ก็ได้
  3. คุมเพลงด้วยปุ่มบน Now Playing panel หรือ /skip /pause /resume /stop /volume
  4. /eqmenu ปรับเสียง • /thememenu เปลี่ยนสีธีม

🆕 รอบนี้:
  • หน้าตาใหม่ทั้งหมด (พาสเทล/อีโมจิ) ผ่าน style.py
  • ปุ่มบน panel ต้องอยู่ห้องเสียงเดียวกับบอทถึงกดได้ + ปุ่มมี custom_id ใช้ได้หลัง restart
  • เครื่องเล่นใหม่: repeat/previous/skip ไม่ตีกันแล้ว (ใช้ token + lock ต่อเซิร์ฟ)
  • ลิงก์ Discord CDN หมดอายุ → ดึงลิงก์ใหม่จากข้อความต้นทางให้อัตโนมัติ
  • ออกจากห้องเองเมื่อไม่มีคนอยู่/เงียบนาน • จำสีธีม/ระดับเสียง/EQ ข้าม restart
"""

import asyncio
import ipaddress
import logging
import os
import random
import shutil
import socket
import subprocess
import tempfile
import time
from typing import Optional
from urllib.parse import urlparse

import discord
from discord import app_commands
from discord.ext import commands

import db
import style
from checks import require_permission

log = logging.getLogger("beluga")

# ============================================================================
# 🎛️ FFmpeg Configuration
# ============================================================================

FFMPEG_VERSION_REQUIRED = "9.0.2"

# ตั้งค่า env var FFMPEG_PATH บน Render ให้ชี้ไปที่ binary ที่ดาวน์โหลดมาเอง (เช่น "./bin/ffmpeg")
# ไม่ตั้งไว้ = ใช้ "ffmpeg" จาก system PATH ตามปกติ
FFMPEG_EXECUTABLE = os.environ.get("FFMPEG_PATH", "ffmpeg")

# 🔒 อนุญาตให้ ffmpeg เปิดได้แค่ http/https เท่านั้น (กัน playlist ที่ชี้ไป file:// หรือโปรโตคอลแปลก ๆ)
PROTOCOL_WHITELIST = "http,https,tcp,tls,crypto"

FFMPEG_OPTIONS = {
    "protocol_whitelist": PROTOCOL_WHITELIST,
    "reconnect": 1,
    "reconnect_streamed": 1,
    "reconnect_delay_max": 5,
    # หมายเหตุ: "http_persistent" เป็น option เฉพาะของ HLS demuxer — อย่าใส่ตรงนี้ FFmpeg จะ error
}


class FFmpegConfig:
    """จัดการการตั้งค่า FFmpeg"""

    @staticmethod
    def get_ffmpeg_path() -> Optional[str]:
        if os.path.isfile(FFMPEG_EXECUTABLE) and os.access(FFMPEG_EXECUTABLE, os.X_OK):
            return os.path.abspath(FFMPEG_EXECUTABLE)
        return shutil.which(FFMPEG_EXECUTABLE)

    @staticmethod
    def check_ffmpeg_available() -> bool:
        return FFmpegConfig.get_ffmpeg_path() is not None

    _cached_version: Optional[str] = None

    @staticmethod
    def get_ffmpeg_version() -> Optional[str]:
        """อ่านเวอร์ชันครั้งเดียวแล้วจำไว้ (info.py เรียกแบบ sync — จึงไม่ยิง subprocess ซ้ำทุกครั้ง)"""
        if FFmpegConfig._cached_version:
            return FFmpegConfig._cached_version
        path = FFmpegConfig.get_ffmpeg_path()
        if path is None:
            return None
        try:
            result = subprocess.run([path, "-version"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                FFmpegConfig._cached_version = result.stdout.split("\n")[0]
                return FFmpegConfig._cached_version
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
        return None


# ============================================================================
# 🎚️ EQ Presets — คลังพรีเซ็ตเสียงสำเร็จรูป
# ============================================================================
# แต่ละพรีเซ็ตกำหนด bass/treble เริ่มต้น + extra filter chain (เอฟเฟกต์ pitch/tempo)
# Discord ใช้เสียง 48kHz เลย resample เป็น 48000 ก่อนทุกครั้ง pitch จะได้ตรงตามที่ตั้งใจ

EQ_PRESETS: dict[str, dict] = {
    "flat": {
        "emoji": "🤍", "label": "Flat (ปกติ)",
        "desc": "เสียงต้นฉบับ ไม่มีเอฟเฟกต์พิเศษ",
        "bass": 0, "treble": 0, "extra": [],
    },
    "bass_boost": {
        "emoji": "🥁", "label": "Bass Boost",
        "desc": "เน้นเบสหนักแน่น เหมาะ EDM / Hip-Hop",
        "bass": 15, "treble": 0, "extra": [],
    },
    "treble_boost": {
        "emoji": "✨", "label": "Treble Boost",
        "desc": "เน้นเสียงแหลมใส เหมาะเพลง acoustic",
        "bass": 0, "treble": 10, "extra": [],
    },
    "vocal_boost": {
        "emoji": "🎤", "label": "Vocal Boost",
        "desc": "ดันเสียงร้องให้เด่นชัดขึ้น",
        "bass": -3, "treble": 6, "extra": [],
    },
    "party": {
        "emoji": "🎉", "label": "Party Mode",
        "desc": "เบส+แหลมเพิ่มพร้อมกัน ฟังมันส์สุด",
        "bass": 12, "treble": 8, "extra": [],
    },
    "nightcore": {
        "emoji": "⚡", "label": "Nightcore",
        "desc": "เร่งความเร็ว+คีย์สูงขึ้น สไตล์ nightcore",
        "bass": 0, "treble": 0,
        "extra": ["aresample=48000", "asetrate=48000*1.25", "aresample=48000", "atempo=1.05"],
    },
    "vaporwave": {
        "emoji": "🌴", "label": "Vaporwave",
        "desc": "ลดความเร็ว+คีย์ต่ำลง บรรยากาศ chill",
        "bass": 3, "treble": 0,
        "extra": ["aresample=48000", "asetrate=48000*0.85", "aresample=48000", "atempo=0.95"],
    },
    "deep": {
        "emoji": "🐻", "label": "Deep Voice",
        "desc": "เสียงทุ้มต่ำลงโดยไม่เปลี่ยนความเร็วเพลง",
        "bass": 5, "treble": -3,
        "extra": ["aresample=48000", "asetrate=48000*0.9", "aresample=48000", "atempo=1.111"],
    },
    "chipmunk": {
        "emoji": "🐿️", "label": "Chipmunk",
        "desc": "เสียงสูงแบบตัวการ์ตูน ไม่เปลี่ยนความเร็วเพลง",
        "bass": -3, "treble": 5,
        "extra": ["aresample=48000", "asetrate=48000*1.4", "aresample=48000", "atempo=0.714"],
    },
    "8d": {
        "emoji": "🌀", "label": "8D Audio",
        "desc": "เสียงหมุนรอบทิศ ใส่หูฟังฟังฟินมาก",
        "bass": 2, "treble": 2,
        "extra": ["apulsator=hz=0.09"],
    },
    "karaoke": {
        "emoji": "🎙️", "label": "Karaoke",
        "desc": "พยายามตัดเสียงร้องออก เหลือดนตรี (ไม่การันตี 100%)",
        "bass": 0, "treble": 0,
        "extra": ["pan=stereo|c0=c0-c1|c1=c1-c0"],
    },
}

DEFAULT_PRESET = "flat"

# ============================================================================
# 🎨 Theme Colors — สีธีม embed ที่ตั้งได้ต่อ guild (พาสเทลทั้งชุด)
# ============================================================================

THEME_PRESETS: dict[str, int] = {
    "บับเบิ้ลกัม": 0xFF9EC4,
    "สตรอว์เบอร์รี": 0xFF7A8A,
    "พีช": 0xFFB38A,
    "เลมอน": 0xFFF1A8,
    "มิ้นต์": 0x8FE3B0,
    "สกาย": 0xA5D8FF,
    "ลาเวนเดอร์": 0xC4B5FD,
    "องุ่น": 0xB197FC,
    "ขาวนม": 0xFFF5F7,
    "ราตรี": 0x2B2D42,
}
DEFAULT_COLOR = style.DEFAULT_COLOR

THEME_EMOJI: dict[str, str] = {
    "บับเบิ้ลกัม": "🍬",
    "สตรอว์เบอร์รี": "🍓",
    "พีช": "🍑",
    "เลมอน": "🍋",
    "มิ้นต์": "🍃",
    "สกาย": "☁️",
    "ลาเวนเดอร์": "🔮",
    "องุ่น": "🍇",
    "ขาวนม": "🥛",
    "ราตรี": "🌙",
}


def parse_color(raw: str) -> Optional[int]:
    """แปลง input เป็นค่าสี — รับได้ทั้งชื่อพรีเซ็ตและ hex code เช่น #ff8800 หรือ ff8800"""
    key = raw.strip().lower()
    for name, value in THEME_PRESETS.items():
        if name.lower() == key:
            return value
    hex_str = raw.strip().lstrip("#")
    if len(hex_str) == 6:
        try:
            return int(hex_str, 16)
        except ValueError:
            return None
    return None


NUM_EMOJI = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
BOT_NAME = "Anyaluga"
MUSIC_LABEL = "Music Room"

# ============================================================================
# 🎵 Queue Items & Audio Filter
# ============================================================================


class QueueItem:
    __slots__ = ("title", "url", "requester", "thumbnail", "duration", "msg_ref", "refreshed_at")

    def __init__(
        self,
        title: str,
        url: str,
        requester: discord.Member,
        thumbnail: Optional[str] = None,
        duration: Optional[float] = None,
        msg_ref: Optional[tuple[int, int]] = None,
    ):
        self.title = title
        self.url = url
        self.requester = requester
        self.thumbnail = thumbnail
        self.duration = duration
        # (channel_id, message_id) ของข้อความที่เก็บไฟล์ไว้ — ไว้ดึงลิงก์ CDN ใหม่ก่อนเล่น
        self.msg_ref = msg_ref
        self.refreshed_at: float = 0.0  # monotonic time ที่ดึงลิงก์ใหม่ล่าสุด (0 = ยังไม่เคย)


class AudioFilter:
    """จัดการ EQ ปัจจุบันของ guild — พรีเซ็ต + bass/treble ที่ override เองได้"""

    def __init__(self):
        self.preset: str = DEFAULT_PRESET
        self.bass: int = 0
        self.treble: int = 0
        self.extra_filters: list[str] = []

    def apply_preset(self, preset_key: str):
        data = EQ_PRESETS[preset_key]
        self.preset = preset_key
        self.bass = data["bass"]
        self.treble = data["treble"]
        self.extra_filters = list(data["extra"])

    def set_bass(self, value: int):
        self.bass = value

    def set_treble(self, value: int):
        self.treble = value

    def to_filter_string(self) -> Optional[str]:
        parts = list(self.extra_filters)
        if self.bass != 0 or self.treble != 0:
            parts.append(f"bass=g={self.bass}")
            parts.append(f"treble=g={self.treble}")
        if not parts:
            return None
        return ",".join(parts)

    def is_active(self) -> bool:
        return bool(self.extra_filters) or self.bass != 0 or self.treble != 0


class GuildMusicState:
    def __init__(self):
        self.queue: list[QueueItem] = []
        self.history: list[QueueItem] = []
        self.current: Optional[QueueItem] = None
        self.volume: float = 0.5
        self.audio_filter = AudioFilter()
        self.voice_client: Optional[discord.VoiceClient] = None
        self.text_channel: Optional[discord.abc.Messageable] = None
        self.color: int = DEFAULT_COLOR

        # 🎵 Now Playing control panel state
        self.panel_message: Optional[discord.Message] = None
        self.panel_task: Optional[asyncio.Task] = None
        self.started_at: Optional[float] = None
        self.paused_at: Optional[float] = None
        self.paused_total: float = 0.0
        self.repeat: str = "off"  # off / one / all
        self.shuffle: bool = False
        self.favorites: set[str] = set()

        # ⚙️ เครื่องเล่น: ป้องกันสั่งซ้อน/callback เก่าตีกัน
        self.lock = asyncio.Lock()
        self.play_token: int = 0
        self.fail_streak: int = 0
        self.leave_task: Optional[asyncio.Task] = None
        self.leave_reason: Optional[str] = None
        self.settings_loaded: bool = False

    def build_ffmpeg_options(self) -> dict:
        before_options = " ".join(f"-{key} {val}" for key, val in FFMPEG_OPTIONS.items())
        options = "-vn"
        filter_str = self.audio_filter.to_filter_string()
        if filter_str:
            options += f' -af "{filter_str}"'
        return {"before_options": before_options, "options": options}


# ============================================================================
# 🧰 Helpers
# ============================================================================


def _format_time(seconds: Optional[float]) -> str:
    if seconds is None or seconds < 0:
        return "--:--"
    seconds = int(seconds)
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def get_panel_elapsed(state: GuildMusicState) -> float:
    if state.started_at is None:
        return 0.0
    now = time.monotonic()
    paused_total = state.paused_total
    if state.paused_at is not None:
        paused_total += max(0.0, now - state.paused_at)
    return max(0.0, now - state.started_at - paused_total)


def _progress_line(elapsed: float, duration: Optional[float]) -> str:
    if not duration or duration <= 0:
        return f"`{_format_time(elapsed)} / --:--`\n🎀 {style.heart_bar(0.0)}"
    ratio = elapsed / duration
    return f"`{_format_time(elapsed)} / {_format_time(duration)}`\n🎀 {style.heart_bar(ratio)}"


def _is_discord_cdn(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host.endswith("discordapp.com") or host.endswith("discordapp.net") or host.endswith("discord.com")


async def _url_is_public(url: str) -> bool:
    """🔒 ยอมรับเฉพาะ http/https ที่ชี้ไปยัง IP สาธารณะ (กัน SSRF ไปยัง localhost / เครือข่ายภายใน)"""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False
        host = parsed.hostname
        try:
            ips = [ipaddress.ip_address(host)]
        except ValueError:
            loop = asyncio.get_running_loop()
            infos = await asyncio.wait_for(
                loop.getaddrinfo(host, None, type=socket.SOCK_STREAM), timeout=5
            )
            ips = [ipaddress.ip_address(info[4][0]) for info in infos]
        return bool(ips) and all(ip.is_global for ip in ips)
    except Exception:
        return False


async def _reply(interaction: discord.Interaction, *, embed: Optional[discord.Embed] = None,
                 ephemeral: bool = False, **kwargs):
    """ตอบ interaction ไม่ว่าจะ defer ไปแล้วหรือยัง"""
    if embed is not None:
        kwargs["embed"] = embed
    if interaction.response.is_done():
        return await interaction.followup.send(ephemeral=ephemeral, **kwargs)
    return await interaction.response.send_message(ephemeral=ephemeral, **kwargs)


def _warn(text: str, **kw) -> discord.Embed:
    return style.warn(text, system="music", **kw)


def _ok(text: str, **kw) -> discord.Embed:
    return style.success(text, system="music", **kw)


def _err(text: str, **kw) -> discord.Embed:
    return style.error(text, system="music", **kw)


# ============================================================================
# 🖼️ Embed Builders
# ============================================================================


def build_music_panel_embed(state: GuildMusicState) -> discord.Embed:
    """สร้าง Now Playing panel สไตล์การ์ดเพลงน่ารัก ๆ"""
    if state.current is None:
        embed = style.brand_embed(
            title="🌙 ตอนนี้เงียบจังเลย~",
            description=(
                "ยังไม่มีเพลงเล่นอยู่น้า\n"
                "ลองพิมพ์ `/play` เพลงโปรดมาฟังด้วยกันสิ 🎶"
            ),
            color=state.color,
            system="music",
            timestamp=False,
        )
        embed.set_author(name=f"🎧 {BOT_NAME} {MUSIC_LABEL}")
        return embed

    item = state.current
    vc = state.voice_client
    if vc and vc.is_paused():
        status = "⏸️ พักอยู่น้า"
    elif vc and vc.is_playing():
        status = "▶️ กำลังเล่น"
    else:
        status = "💤 รอสักครู่"

    repeat_label = {"off": "ปิด", "one": "เพลงนี้ 🔂", "all": "ทั้งคิว 🔁"}.get(state.repeat, "ปิด")
    preset = EQ_PRESETS[state.audio_filter.preset]
    is_fav = item.url in state.favorites

    embed = style.brand_embed(
        title=f"🎶 {style.clip(item.title, 240)}",
        description=(
            f"💌 ขอโดย {item.requester.mention}\n\n"
            f"{status}\n"
            f"{_progress_line(get_panel_elapsed(state), item.duration)}"
        ),
        color=state.color,
        system="music",
        footer_extra=(
            f"ถัดไป: {style.clip(state.queue[0].title, 45)}" if state.queue else "ไม่มีเพลงถัดไปแล้วน้า"
        ),
        thumbnail=item.thumbnail,
        timestamp=False,
    )
    embed.set_author(name=f"🎧 กำลังฟังอยู่ที่ {BOT_NAME} {MUSIC_LABEL}")

    embed.add_field(name="🎛️ EQ", value=f"{preset['emoji']} {preset['label']}", inline=True)
    embed.add_field(name="🔊 เสียง", value=f"**{round(state.volume * 100)}%**", inline=True)
    embed.add_field(name="📋 คิว", value=f"**{len(state.queue)}** เพลง", inline=True)
    embed.add_field(name="🔁 วนซ้ำ", value=repeat_label, inline=True)
    embed.add_field(name="🔀 สุ่ม", value="เปิด ✨" if state.shuffle else "ปิด", inline=True)
    embed.add_field(name="💝 ถูกใจ", value="💖 ชอบเพลงนี้!" if is_fav else "🤍 ยังไม่ได้กด", inline=True)
    return embed


def build_queue_embed(state: GuildMusicState) -> discord.Embed:
    embed = style.brand_embed(
        title="📋 คิวเพลงของเรา ♡",
        color=state.color,
        system="music",
        footer_extra=f"ทั้งหมด {len(state.queue)} เพลงในคิว",
        thumbnail=state.current.thumbnail if state.current else None,
    )
    if state.current:
        embed.add_field(
            name="🎶 กำลังเล่น",
            value=f"**{style.clip(state.current.title, 200)}**\n💌 {state.current.requester.mention}",
            inline=False,
        )
    else:
        embed.add_field(name="🎶 กำลังเล่น", value="ยังไม่มีเลยน้า~ 🌙", inline=False)

    if state.queue:
        lines = [
            f"{NUM_EMOJI[i] if i < len(NUM_EMOJI) else '▫️'} **{style.clip(item.title, 50)}** — {item.requester.mention}"
            for i, item in enumerate(state.queue[:10])
        ]
        if len(state.queue) > 10:
            lines.append(f"…และอีก **{len(state.queue) - 10}** เพลงน้า 🍡")
        embed.add_field(name="🍡 รอคิวอยู่", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="🍡 รอคิวอยู่", value="ยังไม่มีเพลงรอเลย เพิ่มด้วย `/play` ได้น้า", inline=False)
    return embed


def build_eq_embed(audio_filter: AudioFilter, color: int = DEFAULT_COLOR) -> discord.Embed:
    """embed โชว์สถานะ EQ ปัจจุบัน"""
    preset_data = EQ_PRESETS[audio_filter.preset]

    def bar(value: int) -> str:
        return style.heart_bar((value + 10) / 30, 10)

    embed = style.brand_embed(
        title="🎛️ Equalizer สุดน่ารัก",
        description=f"{preset_data['emoji']} **{preset_data['label']}**\n{preset_data['desc']}\n{style.DIVIDER}",
        color=color,
        system="music",
        footer_extra="มีผลตั้งแต่เพลงถัดไป • /skip เพื่อให้มีผลทันที",
        timestamp=False,
    )
    embed.add_field(name="🥁 เบส (Bass)", value=f"{bar(audio_filter.bass)}  **{audio_filter.bass:+d}**", inline=False)
    embed.add_field(name="✨ แหลม (Treble)", value=f"{bar(audio_filter.treble)}  **{audio_filter.treble:+d}**", inline=False)
    if audio_filter.extra_filters:
        embed.add_field(name="🪄 เอฟเฟกต์พิเศษ", value="เปิดใช้งานอยู่ (ปรับ pitch/tempo)", inline=False)
    return embed


def build_theme_embed(color: int) -> discord.Embed:
    """พรีวิวสีธีมปัจจุบัน — ใช้สีจริงเป็นแถบสีของ embed เอง"""
    hex_code = f"#{color:06X}"
    preset_name = next((name for name, value in THEME_PRESETS.items() if value == color), None)
    label = f"{THEME_EMOJI.get(preset_name, '🎨')} **{preset_name}**" if preset_name else "🎨 **สีที่คุณเลือกเอง**"
    return style.brand_embed(
        title="🎨 Theme Menu",
        description=(
            f"{label}\nโค้ดสี: `{hex_code}`\n{style.DIVIDER}\n"
            "สีนี้จะใช้กับ embed เพลงทั้งหมด (Now Playing, Queue, EQ ฯลฯ) 🌈"
        ),
        color=color,
        system="theme",
        footer_extra='เลือกจาก dropdown หรือกด "สีกำหนดเอง" เพื่อใส่ hex code',
        timestamp=False,
    )


# ============================================================================
# 🕹️ Interactive EQ Menu (Select + Buttons)
# ============================================================================


class EQSelect(discord.ui.Select):
    def __init__(self, music_cog: "Music", guild_id: int):
        options = [
            discord.SelectOption(
                label=data["label"], description=data["desc"][:100], emoji=data["emoji"], value=key
            )
            for key, data in EQ_PRESETS.items()
        ]
        super().__init__(placeholder="🎧 เลือกพรีเซ็ต EQ...", options=options, min_values=1, max_values=1)
        self.music_cog = music_cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        state = self.music_cog.get_state(self.guild_id)
        state.audio_filter.apply_preset(self.values[0])
        await interaction.response.edit_message(embed=build_eq_embed(state.audio_filter, state.color), view=self.view)
        await self.music_cog._save_settings(self.guild_id)


class EQAdjustButton(discord.ui.Button):
    """ปุ่มปรับเบส/แหลมทีละ 2 ขั้น"""

    def __init__(self, music_cog: "Music", guild_id: int, *, target: str, delta: int, label: str, emoji: str,
                 button_style: discord.ButtonStyle):
        super().__init__(label=label, style=button_style, emoji=emoji, row=1)
        self.music_cog = music_cog
        self.guild_id = guild_id
        self.target = target
        self.delta = delta

    async def callback(self, interaction: discord.Interaction):
        state = self.music_cog.get_state(self.guild_id)
        flt = state.audio_filter
        if self.target == "bass":
            flt.set_bass(max(-10, min(20, flt.bass + self.delta)))
        else:
            flt.set_treble(max(-10, min(20, flt.treble + self.delta)))
        await interaction.response.edit_message(embed=build_eq_embed(flt, state.color), view=self.view)
        await self.music_cog._save_settings(self.guild_id)


class EQResetButton(discord.ui.Button):
    def __init__(self, music_cog: "Music", guild_id: int):
        super().__init__(label="รีเซ็ต", style=discord.ButtonStyle.secondary, emoji="🔄", row=2)
        self.music_cog = music_cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        state = self.music_cog.get_state(self.guild_id)
        state.audio_filter.apply_preset(DEFAULT_PRESET)
        await interaction.response.edit_message(embed=build_eq_embed(state.audio_filter, state.color), view=self.view)
        await self.music_cog._save_settings(self.guild_id)


class EQView(discord.ui.View):
    """เมนู EQ แบบ interactive — เลือกพรีเซ็ตจาก dropdown หรือกดปุ่มปรับละเอียดทีละขั้น"""

    def __init__(self, music_cog: "Music", guild_id: int):
        super().__init__(timeout=180)
        self.music_cog = music_cog
        self.guild_id = guild_id
        self.message: Optional[discord.Message] = None
        self.add_item(EQSelect(music_cog, guild_id))
        P, S = discord.ButtonStyle.primary, discord.ButtonStyle.success
        self.add_item(EQAdjustButton(music_cog, guild_id, target="bass", delta=-2, label="เบส -", emoji="🔉", button_style=P))
        self.add_item(EQAdjustButton(music_cog, guild_id, target="bass", delta=2, label="เบส +", emoji="🥁", button_style=P))
        self.add_item(EQAdjustButton(music_cog, guild_id, target="treble", delta=-2, label="แหลม -", emoji="🔅", button_style=S))
        self.add_item(EQAdjustButton(music_cog, guild_id, target="treble", delta=2, label="แหลม +", emoji="✨", button_style=S))
        self.add_item(EQResetButton(music_cog, guild_id))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await self.music_cog._can_control(
            interaction, self.music_cog.get_state(self.guild_id), strict=False
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


# ============================================================================
# 🎨 Interactive Theme Menu (Select + Custom Hex Modal)
# ============================================================================


class ThemeSelect(discord.ui.Select):
    def __init__(self, music_cog: "Music", guild_id: int):
        options = [
            discord.SelectOption(label=name, emoji=THEME_EMOJI.get(name, "🎨"), value=name)
            for name in THEME_PRESETS.keys()
        ]
        super().__init__(placeholder="🎨 เลือกสีธีมจากพรีเซ็ต...", options=options, min_values=1, max_values=1)
        self.music_cog = music_cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        state = self.music_cog.get_state(self.guild_id)
        state.color = THEME_PRESETS[self.values[0]]
        await interaction.response.edit_message(embed=build_theme_embed(state.color), view=self.view)
        await self.music_cog._save_settings(self.guild_id)


class ThemeCustomHexModal(discord.ui.Modal, title="🖌️ ใส่สีกำหนดเอง"):
    hex_input = discord.ui.TextInput(
        label="Hex code (ไม่ต้องใส่ #)", placeholder="เช่น ff8800", min_length=6, max_length=7
    )

    def __init__(self, music_cog: "Music", guild_id: int, view: "ThemeView"):
        super().__init__()
        self.music_cog = music_cog
        self.guild_id = guild_id
        self.theme_view = view

    async def on_submit(self, interaction: discord.Interaction):
        parsed = parse_color(self.hex_input.value)
        if parsed is None:
            await interaction.response.send_message(
                embed=_warn("ใส่สีไม่ถูกต้องน้า — พิมพ์ hex code 6 หลัก เช่น `ff8800`"), ephemeral=True
            )
            return
        state = self.music_cog.get_state(self.guild_id)
        state.color = parsed
        await interaction.response.edit_message(embed=build_theme_embed(state.color), view=self.theme_view)
        await self.music_cog._save_settings(self.guild_id)


class ThemeCustomButton(discord.ui.Button):
    def __init__(self, music_cog: "Music", guild_id: int):
        super().__init__(label="สีกำหนดเอง", style=discord.ButtonStyle.primary, emoji="🖌️", row=1)
        self.music_cog = music_cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ThemeCustomHexModal(self.music_cog, self.guild_id, self.view))


class ThemeResetButton(discord.ui.Button):
    def __init__(self, music_cog: "Music", guild_id: int):
        super().__init__(label="กลับเป็นบับเบิ้ลกัม", style=discord.ButtonStyle.secondary, emoji="🍬", row=1)
        self.music_cog = music_cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        state = self.music_cog.get_state(self.guild_id)
        state.color = DEFAULT_COLOR
        await interaction.response.edit_message(embed=build_theme_embed(state.color), view=self.view)
        await self.music_cog._save_settings(self.guild_id)


class ThemeView(discord.ui.View):
    """เมนูตั้งสีธีมแบบ interactive — ใช้ได้เฉพาะคนที่เปิดเมนู"""

    def __init__(self, music_cog: "Music", guild_id: int, owner_id: int):
        super().__init__(timeout=180)
        self.owner_id = owner_id
        self.message: Optional[discord.Message] = None
        self.add_item(ThemeSelect(music_cog, guild_id))
        self.add_item(ThemeCustomButton(music_cog, guild_id))
        self.add_item(ThemeResetButton(music_cog, guild_id))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                embed=_warn("เมนูนี้ใช้ได้เฉพาะคนที่เปิดนะน้า"), ephemeral=True
            )
            return False
        return True

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


# ============================================================================
# 🕹️ Now Playing Control Panel (ปุ่ม)
# ============================================================================

PANEL_PREFIX = "anyaluga:music:"


class MusicPanelButton(discord.ui.Button):
    def __init__(self, *, action: str, emoji: str, button_style: discord.ButtonStyle, row: int,
                 label: Optional[str] = None):
        super().__init__(label=label, emoji=emoji, style=button_style, row=row, custom_id=f"{PANEL_PREFIX}{action}")
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        view: "MusicPanelView" = self.view  # type: ignore
        await view.cog.handle_panel_action(interaction, self.action)


class MusicPanelView(discord.ui.View):
    """ปุ่ม Now Playing (persistent — ปุ่มมี custom_id ใช้ได้แม้หลัง restart)

    แถว 1: ⏮️ ⏯️ ⏭️ ⏹️ 🔀
    แถว 2: 🔁 🔉 🔊 📋 💝
    แถว 3: 🎛️ EQ • 🎨 ธีม
    """

    def __init__(self, cog: "Music", state: Optional[GuildMusicState] = None):
        super().__init__(timeout=None)
        self.cog = cog
        G, P, S, D = (discord.ButtonStyle.secondary, discord.ButtonStyle.primary,
                      discord.ButtonStyle.success, discord.ButtonStyle.danger)

        shuffle_on = bool(state and state.shuffle)
        repeat_mode = state.repeat if state else "off"
        is_fav = bool(state and state.current and state.current.url in state.favorites)
        is_paused = bool(state and state.voice_client and state.voice_client.is_paused())

        self.add_item(MusicPanelButton(action="previous", emoji="⏮️", button_style=G, row=0))
        self.add_item(MusicPanelButton(action="pause", emoji="▶️" if is_paused else "⏸️", button_style=P, row=0))
        self.add_item(MusicPanelButton(action="skip", emoji="⏭️", button_style=G, row=0))
        self.add_item(MusicPanelButton(action="stop", emoji="⏹️", button_style=D, row=0))
        self.add_item(MusicPanelButton(action="shuffle", emoji="🔀", button_style=S if shuffle_on else G, row=0))

        self.add_item(MusicPanelButton(
            action="repeat", emoji="🔂" if repeat_mode == "one" else "🔁",
            button_style=S if repeat_mode != "off" else G, row=1))
        self.add_item(MusicPanelButton(action="volume_down", emoji="🔉", button_style=G, row=1))
        self.add_item(MusicPanelButton(action="volume_up", emoji="🔊", button_style=G, row=1))
        self.add_item(MusicPanelButton(action="queue", emoji="📋", button_style=G, row=1))
        self.add_item(MusicPanelButton(action="favorite", emoji="💖" if is_fav else "🤍", button_style=G, row=1))

        self.add_item(MusicPanelButton(action="eq", emoji="🎛️", label="EQ", button_style=G, row=2))
        self.add_item(MusicPanelButton(action="theme", emoji="🎨", label="ธีม", button_style=G, row=2))


# ============================================================================
# 🎶 Music Cog — Main Controller
# ============================================================================


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.states: dict[int, GuildMusicState] = {}
        self.ffmpeg_version: Optional[str] = None
        self._bg_tasks: set[asyncio.Task] = set()

    def _spawn(self, coro) -> asyncio.Task:
        """create_task แบบเก็บ reference ไว้ (กัน task ถูก garbage-collect กลางทาง)"""
        task = asyncio.create_task(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        return task

    async def cog_load(self):
        # ทำให้ปุ่มบน panel เก่า ๆ ยังกดได้หลัง restart (ปุ่มไม่ผูกกับ guild — อ่านจาก interaction)
        self.bot.add_view(MusicPanelView(self))
        if not FFmpegConfig.check_ffmpeg_available():
            log.error(
                "❌ FFmpeg ไม่พบบนระบบ — Music cog จะเล่นเพลงไม่ได้ "
                f"ติดตั้ง FFmpeg {FFMPEG_VERSION_REQUIRED}+ ก่อนรันบอท"
            )
        else:
            self.ffmpeg_version = await asyncio.to_thread(FFmpegConfig.get_ffmpeg_version)
            log.info(f"✅ FFmpeg พบ: {self.ffmpeg_version}")

    async def cog_unload(self):
        for state in self.states.values():
            for task in (state.panel_task, state.leave_task):
                if task and not task.done():
                    task.cancel()

    def get_state(self, guild_id: int) -> GuildMusicState:
        if guild_id not in self.states:
            self.states[guild_id] = GuildMusicState()
        return self.states[guild_id]

    # ---------- Settings (จำข้าม restart) ----------

    async def _load_settings(self, guild_id: int):
        state = self.get_state(guild_id)
        if state.settings_loaded:
            return
        state.settings_loaded = True
        try:
            cfg = (await db.get_guild_config(guild_id)).get("music", {}) or {}
            raw_color = cfg.get("color")
            if raw_color:
                state.color = int(str(raw_color).lstrip("#"), 16)
            if isinstance(cfg.get("volume"), (int, float)):
                state.volume = max(0.0, min(2.0, cfg["volume"] / 100))
            if cfg.get("eq_preset") in EQ_PRESETS:
                state.audio_filter.apply_preset(cfg["eq_preset"])
            if isinstance(cfg.get("eq_bass"), int):
                state.audio_filter.set_bass(max(-10, min(20, cfg["eq_bass"])))
            if isinstance(cfg.get("eq_treble"), int):
                state.audio_filter.set_treble(max(-10, min(20, cfg["eq_treble"])))
        except Exception as exc:
            log.warning("[music] โหลดการตั้งค่าไม่สำเร็จ (guild %s): %s", guild_id, exc)

    async def _save_settings(self, guild_id: int):
        state = self.get_state(guild_id)
        try:
            await db.update_guild_section(guild_id, "music", {
                "color": f"#{state.color:06X}",
                "volume": round(state.volume * 100),
                "eq_preset": state.audio_filter.preset,
                "eq_bass": state.audio_filter.bass,
                "eq_treble": state.audio_filter.treble,
            })
        except Exception as exc:
            log.warning("[music] บันทึกการตั้งค่าไม่สำเร็จ (guild %s): %s", guild_id, exc)

    # ---------- Permission helpers ----------

    async def _has_command_permission(self, interaction: discord.Interaction, command_name: str) -> bool:
        """เช็คแบบเดียวกับ checks.require_permission แต่ไม่ส่งข้อความตอบเอง"""
        if interaction.guild is None:
            return False
        if interaction.user.guild_permissions.manage_guild:
            return True
        try:
            allowed = set(await db.get_allowed_roles(interaction.guild_id, command_name))
        except Exception:
            return False
        return bool(allowed & {r.id for r in interaction.user.roles})

    async def _can_control(self, interaction: discord.Interaction, state: GuildMusicState,
                           *, strict: bool = True) -> bool:
        """ต้องอยู่ห้องเสียงเดียวกับบอทถึงจะคุมเพลงได้ (คนมีสิทธิ์ Manage Server ข้ามได้)

        strict=False: ถ้าบอทยังไม่ได้อยู่ในห้องเสียง ให้ผ่านได้ (เช่น เปิดเมนู EQ ตอนบอทว่าง)"""
        if interaction.guild is None:
            return False
        if interaction.user.guild_permissions.manage_guild:
            return True
        vc = state.voice_client
        if vc is None or not vc.is_connected():
            if strict:
                await _reply(interaction, embed=_warn("บอทยังไม่ได้อยู่ในห้องเสียงเลยน้า~ ลอง `/play` ก่อนนะ"), ephemeral=True)
                return False
            return True
        user_voice = getattr(interaction.user, "voice", None)
        if user_voice is None or user_voice.channel != vc.channel:
            await _reply(
                interaction,
                embed=_warn(f"ต้องเข้ามาอยู่ในห้อง {vc.channel.mention} ก่อนน้า ถึงจะสั่งเพลงได้~ 🎧"),
                ephemeral=True,
            )
            return False
        return True

    # ---------- Media helpers ----------

    async def _probe_duration(self, url: str) -> Optional[float]:
        """พยายามอ่านความยาวไฟล์เสียงด้วย ffprobe; ถ้าอ่านไม่ได้ให้ None"""
        ffmpeg_path = FFmpegConfig.get_ffmpeg_path()
        if not ffmpeg_path:
            return None

        probe_path = os.environ.get("FFPROBE_PATH")
        if not probe_path:
            candidate = os.path.join(os.path.dirname(ffmpeg_path), "ffprobe")
            probe_path = candidate if os.path.isfile(candidate) else "ffprobe"

        try:
            proc = await asyncio.create_subprocess_exec(
                probe_path,
                "-v", "error",
                "-protocol_whitelist", PROTOCOL_WHITELIST,
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=8)
            except asyncio.TimeoutError:
                proc.kill()
                return None
            if proc.returncode == 0:
                value = float(stdout.decode().strip())
                return value if value > 0 else None
        except (ValueError, FileNotFoundError, OSError):
            pass
        return None

    async def _fill_duration(self, guild_id: int, item: QueueItem):
        """probe ความยาวเพลงเบื้องหลัง (ไม่หน่วงการเริ่มเล่น)"""
        if item.duration is None:
            item.duration = await self._probe_duration(item.url)

    async def _refresh_media(self, item: QueueItem):
        """ลิงก์ CDN ของ Discord หมดอายุเป็นระยะ — ดึงลิงก์ใหม่จากข้อความต้นทางก่อนเล่นทุกครั้ง"""
        if not item.msg_ref or time.monotonic() - item.refreshed_at < 1800:
            return  # ไม่มีที่อยู่ข้อความ หรือเพิ่งดึงมาไม่นาน (กันยิง API รัว ๆ ตอน repeat เพลงสั้น)
        item.refreshed_at = time.monotonic()
        channel_id, message_id = item.msg_ref
        try:
            channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
            message = await channel.fetch_message(message_id)
            if message.attachments:
                item.url = message.attachments[0].url
                if len(message.attachments) > 1:
                    item.thumbnail = message.attachments[1].url
        except (discord.NotFound, discord.Forbidden):
            log.warning("[music] หาข้อความต้นทางของเพลง %r ไม่เจอแล้ว — ใช้ลิงก์เดิมไปก่อน", item.title)
        except discord.HTTPException as exc:
            log.warning("[music] ดึงลิงก์ใหม่ของ %r ไม่สำเร็จ: %s", item.title, exc)

    async def _notify(self, state: GuildMusicState, embed: discord.Embed):
        if state.text_channel is None:
            return
        try:
            await state.text_channel.send(embed=embed)
        except discord.HTTPException:
            pass

    # ---------- Panel ----------

    async def update_music_panel(self, guild_id: int, *, repost: bool = False):
        state = self.get_state(guild_id)
        if state.text_channel is None:
            return

        state.color = await style.theme_color(guild_id, "music")
        embed = build_music_panel_embed(state)
        view = MusicPanelView(self, state)

        # ถ้ามีข้อความอื่นแทรกลงมาแล้ว ให้โพสต์ panel ใหม่ที่ก้นห้องแทนการแก้ข้อความเก่าที่ถูกดันขึ้นไป
        if repost and state.panel_message is not None:
            last_id = getattr(state.text_channel, "last_message_id", None)
            if last_id is not None and last_id != state.panel_message.id:
                try:
                    await state.panel_message.delete()
                except discord.HTTPException:
                    pass
                state.panel_message = None

        if state.panel_message is not None:
            try:
                await state.panel_message.edit(embed=embed, view=view)
                return
            except (discord.NotFound, discord.HTTPException):
                state.panel_message = None

        try:
            state.panel_message = await state.text_channel.send(embed=embed, view=view)
        except discord.HTTPException as exc:
            log.warning("[music] ส่ง Now Playing panel ไม่สำเร็จ: %s", exc)

    async def _panel_loop(self, guild_id: int):
        """อัปเดต progress bar ทุก 10 วินาที (แก้เฉพาะ embed — ปุ่มไม่ต้องส่งซ้ำ)"""
        try:
            while True:
                await asyncio.sleep(10)
                state = self.get_state(guild_id)
                if state.current is None or state.panel_message is None:
                    return
                if state.voice_client and state.voice_client.is_paused():
                    continue
                try:
                    await state.panel_message.edit(embed=build_music_panel_embed(state))
                except discord.NotFound:
                    state.panel_message = None
                    return
                except discord.HTTPException:
                    pass
        except asyncio.CancelledError:
            return

    def _restart_panel_loop(self, guild_id: int):
        state = self.get_state(guild_id)
        if state.panel_task and not state.panel_task.done():
            state.panel_task.cancel()
        state.panel_task = asyncio.create_task(self._panel_loop(guild_id))

    def _stop_panel_loop(self, state: GuildMusicState):
        if state.panel_task and not state.panel_task.done():
            state.panel_task.cancel()
        state.panel_task = None

    # ---------- Playback Engine ----------
    # กติกา: ทุกการเปลี่ยนเพลง (จบเอง/ข้าม/ก่อนหน้า/เริ่มใหม่) ต้องผ่าน _advance() ที่เดียว
    # - ใช้ lock ต่อเซิร์ฟ กันสั่งซ้อน
    # - play_token เพิ่มทุกครั้งที่เปลี่ยนเพลง → callback "เพลงจบ" ของเพลงเก่าที่ถูก stop() จะถูกเมินอัตโนมัติ

    @staticmethod
    def _push_history(state: GuildMusicState, item: QueueItem):
        state.history.append(item)
        state.history = state.history[-20:]

    def _enqueue(self, state: GuildMusicState, item: QueueItem):
        if state.shuffle and state.queue:
            state.queue.insert(random.randint(0, len(state.queue)), item)
        else:
            state.queue.append(item)

    async def _advance(self, guild_id: int, reason: str, *, expected_token: Optional[int] = None):
        """reason: start | ended | skip | previous | restart"""
        state = self.get_state(guild_id)
        async with state.lock:
            if expected_token is not None and expected_token != state.play_token:
                return  # callback ของเพลงเก่า ถูกแทนที่ไปแล้ว
            if reason == "start" and state.current is not None:
                return  # มีเพลงเล่นอยู่แล้ว (มีคนสั่ง /play พร้อมกัน)

            state.play_token += 1
            vc = state.voice_client
            connected = vc is not None and vc.is_connected()
            if connected and (vc.is_playing() or vc.is_paused()):
                vc.stop()

            cur = state.current
            nxt: Optional[QueueItem] = None

            if reason == "restart":
                nxt = cur
            elif reason == "previous":
                if cur is not None and (get_panel_elapsed(state) > 5 or not state.history):
                    nxt = cur  # กดก่อนหน้าตอนเพลงเล่นมาได้สักพัก = เริ่มเพลงนี้ใหม่
                elif state.history:
                    nxt = state.history.pop()
                    if cur is not None:
                        state.queue.insert(0, cur)
            else:  # start / ended / skip
                if cur is not None:
                    if reason == "ended" and state.repeat == "one":
                        nxt = cur
                    else:
                        self._push_history(state, cur)
                        if state.repeat == "all":
                            state.queue.append(cur)
                if nxt is None and state.queue:
                    nxt = state.queue.pop(0)

            if nxt is None:
                await self._go_idle(guild_id, state)
                return
            await self._begin(guild_id, state, nxt)

    async def _go_idle(self, guild_id: int, state: GuildMusicState):
        state.current = None
        state.started_at = None
        state.paused_at = None
        state.paused_total = 0.0
        self._stop_panel_loop(state)
        await self.update_music_panel(guild_id)
        if state.voice_client is not None:
            self._schedule_leave(guild_id, 300, "idle")

    async def _begin(self, guild_id: int, state: GuildMusicState, item: QueueItem):
        vc = state.voice_client
        if vc is None or not vc.is_connected():
            state.queue.insert(0, item)  # ห้องเสียงหลุด — เก็บเพลงไว้ในคิวก่อน ไม่ทำหาย
            state.current = None
            self._stop_panel_loop(state)
            return

        if not FFmpegConfig.check_ffmpeg_available():
            await self._notify(state, _err("ไม่พบ FFmpeg บนเครื่องเซิร์ฟเวอร์ เลยเล่นเพลงไม่ได้น้า 😢"))
            await self._go_idle(guild_id, state)
            return

        await self._refresh_media(item)
        state.current = item

        try:
            source = discord.FFmpegPCMAudio(
                item.url,
                executable=FFmpegConfig.get_ffmpeg_path() or FFMPEG_EXECUTABLE,
                **state.build_ffmpeg_options(),
            )
            source = discord.PCMVolumeTransformer(source, volume=state.volume)
            token = state.play_token

            def after_playing(error):
                asyncio.run_coroutine_threadsafe(
                    self._safe_track_end(guild_id, token, error), self.bot.loop
                )

            vc.play(source, after=after_playing)
        except Exception as exc:
            log.error("[music] เริ่มเล่นไม่สำเร็จ: %s", exc)
            await self._notify(state, _err(f"เริ่มเล่น **{style.clip(item.title, 80)}** ไม่สำเร็จน้า: `{exc}`"))
            await self._go_idle(guild_id, state)
            return

        state.started_at = time.monotonic()
        state.paused_at = None
        state.paused_total = 0.0
        self._cancel_leave(state)
        self._spawn(self._fill_duration(guild_id, item))
        await self.update_music_panel(guild_id, repost=True)
        self._restart_panel_loop(guild_id)

    async def _safe_track_end(self, guild_id: int, token: int, error: Optional[Exception]):
        try:
            await self._on_track_end(guild_id, token, error)
        except Exception:
            log.exception("[music] จัดการตอนเพลงจบพลาด (guild %s)", guild_id)

    async def _on_track_end(self, guild_id: int, token: int, error: Optional[Exception]):
        state = self.get_state(guild_id)
        if token != state.play_token:
            return
        lasted = time.monotonic() - state.started_at if state.started_at else 0.0
        item = state.current
        failed = error is not None or (
            lasted < 1.0 and item is not None and (item.duration is None or item.duration > 3)
        )
        reason = "ended"
        if failed:
            state.fail_streak += 1
            reason = "skip"  # เพลงพัง → ข้ามไปเลย ไม่วนซ้ำเพลงเสีย
            if error:
                log.error("[music] เล่นเพลงพลาด (guild %s): %s", guild_id, error)
            if item is not None:
                await self._notify(
                    state,
                    _err(f"เล่น **{style.clip(item.title, 80)}** ไม่ได้น้า… เช็คลิงก์ไฟล์อีกทีนะ 🥺"),
                )
            if state.fail_streak >= 3:
                state.fail_streak = 0
                state.queue.clear()
                state.repeat = "off"
                await self._notify(state, _warn("เพลงพังติดกันหลายเพลงแล้ว เลยหยุดคิวไว้ก่อนน้า 🍯"))
        else:
            state.fail_streak = 0
        await self._advance(guild_id, reason, expected_token=token)

    async def _cleanup(self, guild_id: int, *, keep_queue: bool = False):
        """หยุดเล่น ออกจากห้องเสียง (keep_queue=True = เก็บคิวไว้ ใช้กับ /leave)"""
        state = self.get_state(guild_id)
        async with state.lock:
            state.play_token += 1
            self._cancel_leave(state)
            self._stop_panel_loop(state)
            vc = state.voice_client
            state.voice_client = None
            if keep_queue and state.current is not None:
                state.queue.insert(0, state.current)
            elif not keep_queue:
                state.queue.clear()
                state.history.clear()
            state.current = None
            state.started_at = None
            state.paused_at = None
            state.paused_total = 0.0
            state.fail_streak = 0
            if vc is not None:
                try:
                    if vc.is_playing() or vc.is_paused():
                        vc.stop()
                    if vc.is_connected():
                        await vc.disconnect()
                except Exception as exc:
                    log.warning("[music] ตัดการเชื่อมต่อเสียงไม่สำเร็จ: %s", exc)
        await self.update_music_panel(guild_id)

    # ---------- Auto-leave ----------

    def _cancel_leave(self, state: GuildMusicState):
        if state.leave_task and not state.leave_task.done() and state.leave_task is not asyncio.current_task():
            state.leave_task.cancel()
        state.leave_task = None
        state.leave_reason = None

    def _schedule_leave(self, guild_id: int, delay: int, reason: str):
        state = self.get_state(guild_id)
        if state.leave_task and not state.leave_task.done():
            state.leave_task.cancel()
        state.leave_reason = reason
        state.leave_task = asyncio.create_task(self._leave_after(guild_id, delay, reason))

    async def _leave_after(self, guild_id: int, delay: int, reason: str):
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        state = self.get_state(guild_id)
        vc = state.voice_client
        if vc is None or not vc.is_connected():
            return
        if reason == "alone" and any(not m.bot for m in vc.channel.members):
            return
        if reason == "idle" and state.current is not None:
            return
        text = ("ไม่มีใครอยู่ในห้องแล้ว บอทขอไปพักก่อนน้า~ 🌙" if reason == "alone"
                else "เงียบไปนานแล้ว บอทขอไปนอนก่อนน้า~ พิมพ์ `/play` ปลุกได้เลย 💤")
        await self._notify(state, style.info(text, title="ไว้เจอกันใหม่น้า", system="music"))
        state.leave_task = None
        await self._cleanup(guild_id, keep_queue=False)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState,
                                    after: discord.VoiceState):
        state = self.states.get(member.guild.id)
        if state is None or state.voice_client is None:
            return

        if self.bot.user is not None and member.id == self.bot.user.id:
            if after.channel is None:  # ถูกเตะ/ตัดการเชื่อมต่อจากฝั่ง Discord
                await self._cleanup(member.guild.id, keep_queue=False)
            return

        vc = state.voice_client
        if not vc.is_connected():
            return
        if any(not m.bot for m in vc.channel.members):
            if state.leave_reason == "alone":
                self._cancel_leave(state)
        else:
            self._schedule_leave(member.guild.id, 60, "alone")

    async def _ensure_voice(self, interaction: discord.Interaction) -> Optional[discord.VoiceClient]:
        member = interaction.user
        if member.voice is None or member.voice.channel is None:
            await _reply(interaction, embed=_warn("เข้าห้องเสียงก่อนน้า ถึงจะสั่งเล่นเพลงได้~ 🎧"), ephemeral=True)
            return None

        state = self.get_state(interaction.guild_id)
        channel = member.voice.channel
        vc = state.voice_client

        try:
            if vc is None or not vc.is_connected():
                existing = interaction.guild.voice_client
                if existing is not None and existing.is_connected():
                    state.voice_client = existing  # มีการเชื่อมต่อค้างอยู่จากก่อนหน้า — ใช้ต่อ
                    if existing.channel != channel and state.current is None:
                        await existing.move_to(channel)
                else:
                    state.voice_client = await channel.connect()
            elif vc.channel != channel:
                if state.current is not None:
                    await _reply(
                        interaction,
                        embed=_warn(f"บอทกำลังเล่นเพลงให้ห้อง {vc.channel.mention} อยู่~ เข้าไปฟังด้วยกันก่อนน้า 🎶"),
                        ephemeral=True,
                    )
                    return None
                await vc.move_to(channel)
        except discord.Forbidden:
            await _reply(interaction, embed=_err("บอทไม่มีสิทธิ์เข้าห้องเสียงนั้นน้า เช็ค Connect / Speak ให้หน่อยนะ"), ephemeral=True)
            return None
        except (asyncio.TimeoutError, discord.ClientException) as exc:
            log.error("[music] เชื่อมต่อห้องเสียงไม่สำเร็จ: %s", exc)
            await _reply(interaction, embed=_err("เชื่อมต่อห้องเสียงไม่สำเร็จน้า ลองใหม่อีกครั้งนะ"), ephemeral=True)
            return None

        state.text_channel = interaction.channel
        return state.voice_client

    # ---------- Panel button handler ----------

    async def handle_panel_action(self, interaction: discord.Interaction, action: str):
        if interaction.guild_id is None:
            return
        guild_id = interaction.guild_id
        state = self.get_state(guild_id)
        await self._load_settings(guild_id)

        # --- ปุ่มที่ทุกคนกดได้ ---
        if action == "queue":
            await interaction.response.send_message(embed=build_queue_embed(state), ephemeral=True)
            return

        if action == "favorite":
            if state.current is None:
                await interaction.response.send_message(embed=_warn("ยังไม่มีเพลงเล่นอยู่เลยน้า~"), ephemeral=True)
                return
            url = state.current.url
            if url in state.favorites:
                state.favorites.remove(url)
            else:
                state.favorites.add(url)
            await self._refresh_clicked_panel(interaction, state)
            return

        if action == "theme":
            if not await self._has_command_permission(interaction, "thememenu"):
                await interaction.response.send_message(
                    embed=_warn("เปลี่ยนธีมได้เฉพาะคนที่มีสิทธิ์ **Manage Server** น้า"), ephemeral=True
                )
                return
            view = ThemeView(self, guild_id, interaction.user.id)
            await interaction.response.send_message(embed=build_theme_embed(state.color), view=view, ephemeral=True)
            view.message = await interaction.original_response()
            return

        # --- ปุ่มควบคุมเสียง: ต้องอยู่ห้องเดียวกับบอท ---
        if not await self._can_control(interaction, state):
            return

        if action == "eq":
            view = EQView(self, guild_id)
            await interaction.response.send_message(
                embed=build_eq_embed(state.audio_filter, state.color), view=view, ephemeral=True
            )
            view.message = await interaction.original_response()
            return

        if state.current is None and action != "stop":
            await interaction.response.send_message(embed=_warn("ยังไม่มีเพลงเล่นอยู่เลยน้า~"), ephemeral=True)
            return

        await interaction.response.defer()  # รับปุ่มไว้ก่อน แล้วค่อยอัปเดต panel ทีหลัง

        vc = state.voice_client
        if action == "pause":
            if vc and vc.is_playing():
                vc.pause()
                state.paused_at = time.monotonic()
            elif vc and vc.is_paused():
                vc.resume()
                if state.paused_at is not None:
                    state.paused_total += max(0.0, time.monotonic() - state.paused_at)
                state.paused_at = None
        elif action == "skip":
            await self._advance(guild_id, "skip")
        elif action == "previous":
            await self._advance(guild_id, "previous")
        elif action == "stop":
            await self._cleanup(guild_id, keep_queue=False)
        elif action == "shuffle":
            state.shuffle = not state.shuffle
            if state.shuffle and len(state.queue) > 1:
                random.shuffle(state.queue)
        elif action == "repeat":
            state.repeat = {"off": "one", "one": "all", "all": "off"}.get(state.repeat, "off")
        elif action in ("volume_down", "volume_up"):
            step = -0.1 if action == "volume_down" else 0.1
            state.volume = max(0.0, min(2.0, round(state.volume + step, 2)))
            if vc and vc.source:
                vc.source.volume = state.volume
            self._spawn(self._save_settings(guild_id))

        await self._refresh_clicked_panel(interaction, state)

    async def _refresh_clicked_panel(self, interaction: discord.Interaction, state: GuildMusicState):
        """อัปเดตข้อความ panel ที่ถูกกด + panel หลักของเซิร์ฟ (ถ้าเป็นคนละข้อความ)"""
        embed = build_music_panel_embed(state)
        view = MusicPanelView(self, state)
        try:
            if interaction.response.is_done():
                await interaction.edit_original_response(embed=embed, view=view)
            else:
                await interaction.response.edit_message(embed=embed, view=view)
        except discord.NotFound:
            pass  # panel ถูกลบ/โพสต์ใหม่ไปแล้วระหว่างเปลี่ยนเพลง — ไม่เป็นไร
        except discord.HTTPException as exc:
            log.warning("[music] อัปเดต panel ที่ถูกกดไม่สำเร็จ: %s", exc)
        main = state.panel_message
        if main is not None and (interaction.message is None or main.id != interaction.message.id):
            await self.update_music_panel(interaction.guild_id)

    # ========================================================================
    # 📚 Song Library Commands
    # ========================================================================

    async def _song_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        if interaction.guild_id is None:
            return []
        try:
            songs = await db.list_songs(interaction.guild_id)
        except Exception:
            return []
        cur = current.lower()
        return [
            app_commands.Choice(name=style.clip(s["name"], 100), value=style.clip(s["name"], 100))
            for s in songs if cur in s["name"].lower()
        ][:25]

    @app_commands.command(name="addsong", description="เพิ่มเพลงเข้าคลัง (ลิงก์ไฟล์เสียงตรง)")
    @require_permission()
    @app_commands.describe(
        name="ชื่อเพลงที่จะใช้เรียก",
        url="ลิงก์ไฟล์เสียงตรง (mp3/wav/etc)",
        thumbnail="ลิงก์รูปภาพปก (ไม่บังคับ) — โชว์เป็นภาพประกอบตอนเล่นเพลง",
    )
    async def addsong(self, interaction: discord.Interaction, name: str, url: str,
                      thumbnail: Optional[str] = None):
        await interaction.response.defer()
        if not await _url_is_public(url):
            await interaction.followup.send(embed=_warn("ลิงก์ต้องขึ้นต้นด้วย http:// หรือ https:// และเป็นเว็บสาธารณะน้า"), ephemeral=True)
            return
        if thumbnail is not None and not thumbnail.startswith(("http://", "https://")):
            await interaction.followup.send(embed=_warn("ลิงก์ภาพปกต้องขึ้นต้นด้วย http:// หรือ https:// น้า"), ephemeral=True)
            return

        await db.add_song(interaction.guild_id, name, url, interaction.user.id, thumbnail_url=thumbnail)

        note = ""
        if _is_discord_cdn(url):
            note = (
                "\n\n🍯 **โปรดทราบ:** ลิงก์ของ Discord หมดอายุเป็นระยะ เพลงนี้อาจเล่นไม่ได้ในวันถัด ๆ ไป\n"
                "ใช้ `/addsongfromvideo` แนบไฟล์แทน บอทจะดูแลลิงก์ให้เองไม่หมดอายุน้า ✨"
            )
        await interaction.followup.send(embed=_ok(f"เพิ่ม **{style.clip(name, 100)}** เข้าคลังเพลงแล้วน้า 🎶{note}"))

    @app_commands.command(
        name="addsongfromvideo",
        description="แนบวิดีโอ/เสียง บอทตัดเสียง+จับภาพนิ่งเป็นปกให้ แล้วเก็บเข้าคลัง (ลิงก์ไม่หมดอายุ)",
    )
    @require_permission()
    @app_commands.describe(
        name="ชื่อเพลงที่จะใช้เรียก",
        video="ไฟล์วิดีโอหรือเสียง (mp4/mov/mp3 ฯลฯ) — ตามขนาดที่ Discord อนุญาตอัปโหลด",
        thumbnail_time="วินาทีในคลิปที่จะจับภาพเป็นปก (ค่าเริ่มต้น 0 = เฟรมแรก)",
    )
    async def addsongfromvideo(
        self,
        interaction: discord.Interaction,
        name: str,
        video: discord.Attachment,
        thumbnail_time: Optional[app_commands.Range[int, 0, 3600]] = 0,
    ):
        ctype = video.content_type or ""
        if not ctype.startswith(("video/", "audio/")):
            await interaction.response.send_message(embed=_warn("ไฟล์ที่แนบต้องเป็นวิดีโอหรือไฟล์เสียงน้า"), ephemeral=True)
            return
        if not FFmpegConfig.check_ffmpeg_available():
            await interaction.response.send_message(embed=_err("ไม่พบ FFmpeg เลยตัดเสียงไม่ได้น้า"), ephemeral=True)
            return

        await interaction.response.defer()
        ffmpeg_bin = FFmpegConfig.get_ffmpeg_path() or FFMPEG_EXECUTABLE
        is_video = ctype.startswith("video/")

        async def run_ffmpeg(*args: str, timeout: int = 180):
            proc = await asyncio.create_subprocess_exec(
                ffmpeg_bin, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            try:
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                return None, b"timeout"
            return proc.returncode, stderr

        tmp_dir = tempfile.mkdtemp(prefix="anyaluga_media_")
        try:
            stamp = int(time.time())
            ext = os.path.splitext(video.filename)[1] or (".mp4" if is_video else ".mp3")
            src_path = os.path.join(tmp_dir, f"input{ext}")
            audio_path = os.path.join(tmp_dir, "audio.m4a")
            thumb_path = os.path.join(tmp_dir, "thumb.jpg")

            await video.save(src_path)

            # Discord voice เล่นได้แต่เสียง → ตัดเสียงออกมาเป็น AAC
            code, err = await run_ffmpeg("-y", "-i", src_path, "-vn", "-c:a", "aac", "-b:a", "128k", audio_path)
            if code != 0 or not os.path.isfile(audio_path):
                log.error("[music] ตัดเสียงไม่สำเร็จ: %s", err.decode(errors="ignore")[-500:])
                await interaction.followup.send(embed=_err("ตัดเสียงจากไฟล์นี้ไม่สำเร็จน้า ลองไฟล์อื่นดูนะ"))
                return

            has_thumbnail = False
            if is_video:
                code, _ = await run_ffmpeg(
                    "-y", "-ss", str(thumbnail_time), "-i", src_path, "-frames:v", "1", "-q:v", "3", thumb_path,
                    timeout=60,
                )
                has_thumbnail = code == 0 and os.path.isfile(thumb_path)

            # อัปโหลดไฟล์ที่ตัดแล้วเข้าห้องนี้ → เก็บ "ที่อยู่ข้อความ" ไว้ ไม่พึ่งลิงก์ CDN ที่หมดอายุ
            files = [discord.File(audio_path, filename=f"anyaluga_{stamp}.m4a")]
            if has_thumbnail:
                files.append(discord.File(thumb_path, filename=f"anyaluga_{stamp}.jpg"))
            try:
                upload_msg = await interaction.channel.send(
                    content=f"📦 ไฟล์คลังของ **{style.clip(name, 100)}** (ห้ามลบข้อความนี้น้า ไม่งั้นเพลงจะหายไปด้วย 🥺)",
                    files=files,
                )
            except discord.HTTPException as exc:
                log.error("[music] อัปโหลดไฟล์เสียงเข้าห้องไม่สำเร็จ: %s", exc)
                await interaction.followup.send(embed=_err(
                    "อัปโหลดไฟล์เสียงที่ตัดแล้วเข้าห้องนี้ไม่สำเร็จน้า (ไฟล์อาจใหญ่เกินที่ Discord ให้อัปโหลด "
                    "หรือบอทไม่มีสิทธิ์ส่งไฟล์) ลองไฟล์ที่สั้นลงนะ"
                ))
                return
            audio_url = upload_msg.attachments[0].url
            thumb_url = upload_msg.attachments[1].url if has_thumbnail and len(upload_msg.attachments) > 1 else None

            await db.add_song(
                interaction.guild_id, name, audio_url, interaction.user.id,
                thumbnail_url=thumb_url, message_ref=(upload_msg.channel.id, upload_msg.id),
            )

            state = self.get_state(interaction.guild_id)
            embed = style.brand_embed(
                title="🎶 เพิ่มเพลงเข้าคลังแล้วน้า~",
                description=f"**{style.clip(name, 100)}** พร้อมเล่นแล้ว!\n🍡 ใช้ `/play {style.clip(name, 60)}` ได้เลย",
                color=state.color, system="music", thumbnail=thumb_url,
            )
            await interaction.followup.send(embed=embed)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @app_commands.command(name="removesong", description="ลบเพลงออกจากคลัง")
    @require_permission()
    @app_commands.describe(name="ชื่อเพลงที่จะลบ")
    @app_commands.autocomplete(name=_song_autocomplete)
    async def removesong(self, interaction: discord.Interaction, name: str):
        removed = await db.remove_song(interaction.guild_id, name)
        if removed:
            await interaction.response.send_message(embed=_ok(f"ลบ **{style.clip(name, 100)}** ออกจากคลังแล้วน้า 🗑️"))
        else:
            await interaction.response.send_message(embed=_warn("ไม่เจอเพลงชื่อนี้ในคลังเลยน้า"), ephemeral=True)

    @app_commands.command(name="songlist", description="ดูรายชื่อเพลงทั้งหมดในคลัง")
    async def songlist(self, interaction: discord.Interaction):
        songs = await db.list_songs(interaction.guild_id)
        state = self.get_state(interaction.guild_id)
        if not songs:
            await interaction.response.send_message(
                embed=style.info("คลังเพลงยังว่างอยู่เลยน้า~ เพิ่มเพลงแรกด้วย `/addsongfromvideo` ได้เลย 🎶",
                                 title="ยังไม่มีเพลงเลย", system="music")
            )
            return
        lines = [f"💿 **{style.clip(s['name'], 80)}**" for s in songs[:30]]
        if len(songs) > 30:
            lines.append(f"…และอีก **{len(songs) - 30}** เพลงน้า 🍡")
        embed = style.brand_embed(
            title="🎵 คลังเพลงของเรา ♡",
            description="\n".join(lines) + f"\n{style.DIVIDER}\nพิมพ์ `/play` แล้วเลือกชื่อเพลงได้เลยน้า~",
            color=state.color, system="music", footer_extra=f"ทั้งหมด {len(songs)} เพลง",
        )
        await interaction.response.send_message(embed=embed)

    # ========================================================================
    # ▶️ Playback Control Commands
    # ========================================================================

    @app_commands.command(name="play", description="เล่นเพลงจากคลัง หรือลิงก์ไฟล์เสียงตรง")
    @app_commands.describe(query="ชื่อเพลงในคลัง หรือลิงก์ไฟล์เสียงตรง")
    @app_commands.autocomplete(query=_song_autocomplete)
    async def play(self, interaction: discord.Interaction, query: str):
        if interaction.guild is None:
            return
        await interaction.response.defer()
        guild_id = interaction.guild_id
        await self._load_settings(guild_id)
        state = self.get_state(guild_id)

        if interaction.user.voice is None or interaction.user.voice.channel is None:
            await interaction.followup.send(embed=_warn("เข้าห้องเสียงก่อนน้า ถึงจะสั่งเล่นเพลงได้~ 🎧"), ephemeral=True)
            return

        # 1) หาเพลงให้เจอก่อน แล้วค่อยเข้าห้อง (กันบอทเข้าห้องมาเฉย ๆ แล้วบอกว่าไม่เจอเพลง)
        msg_ref = None
        if query.startswith(("http://", "https://")):
            if not await _url_is_public(query):
                await interaction.followup.send(embed=_warn("ลิงก์นี้เล่นไม่ได้น้า (ต้องเป็นเว็บสาธารณะที่ขึ้นต้นด้วย http/https)"), ephemeral=True)
                return
            title, url, thumbnail = query.rsplit("/", 1)[-1].split("?")[0] or query, query, None
        else:
            song = await db.get_song(guild_id, query)
            if song is None:
                await interaction.followup.send(embed=_warn("ไม่เจอเพลงนี้ในคลังเลยน้า ลองเช็คชื่อด้วย `/songlist` นะ"), ephemeral=True)
                return
            title, url, thumbnail, msg_ref = song["name"], song["url"], song.get("thumbnail_url"), song.get("message_ref")

        voice_client = await self._ensure_voice(interaction)
        if voice_client is None:
            return

        item = QueueItem(style.clip(title, 200), url, interaction.user, thumbnail, msg_ref=msg_ref)
        self._enqueue(state, item)
        starting_now = state.current is None and len(state.queue) == 1

        if not starting_now:
            embed = style.brand_embed(
                title="➕ เข้าคิวแล้วน้า~",
                description=f"🎶 **{style.clip(item.title, 200)}**\n📍 อันดับที่ **{len(state.queue)}** • 💌 ขอโดย {interaction.user.mention}",
                color=state.color, system="music", thumbnail=thumbnail,
            )
            await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send(embed=style.brand_embed(
                title="▶️ เริ่มเล่นแล้วน้า~",
                description=f"🎶 **{style.clip(item.title, 200)}**\nสนุกกับเพลงนะ 💖",
                color=state.color, system="music", thumbnail=thumbnail,
            ))
        if state.current is None:
            await self._advance(guild_id, "start")

    @app_commands.command(name="skip", description="ข้ามเพลงไปเพลงต่อไปในคิว")
    async def skip(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        if not await self._can_control(interaction, state):
            return
        if state.current is None:
            await interaction.response.send_message(embed=_warn("ยังไม่มีเพลงเล่นอยู่เลยน้า~"), ephemeral=True)
            return
        title = state.current.title
        await interaction.response.defer()
        await self._advance(interaction.guild_id, "skip")
        await interaction.followup.send(embed=_ok(f"ข้าม **{style.clip(title, 100)}** ให้แล้วน้า ⏭️", title="ข้ามเพลงแล้ว~"))

    @app_commands.command(name="pause", description="พักเพลงที่กำลังเล่นไว้ชั่วคราว")
    async def pause(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        if not await self._can_control(interaction, state):
            return
        if state.voice_client is None or not state.voice_client.is_playing():
            await interaction.response.send_message(embed=_warn("ยังไม่มีเพลงที่กำลังเล่นอยู่เลยน้า~"), ephemeral=True)
            return
        state.voice_client.pause()
        state.paused_at = time.monotonic()
        await interaction.response.send_message(embed=_ok("พักเพลงไว้ให้แล้วน้า ⏸️", title="พักก่อนน้า~"))
        await self.update_music_panel(interaction.guild_id)

    @app_commands.command(name="resume", description="เล่นเพลงที่พักไว้ต่อ")
    async def resume(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        if not await self._can_control(interaction, state):
            return
        if state.voice_client is None or not state.voice_client.is_paused():
            await interaction.response.send_message(embed=_warn("ไม่มีเพลงที่พักไว้เลยน้า~"), ephemeral=True)
            return
        state.voice_client.resume()
        if state.paused_at is not None:
            state.paused_total += max(0.0, time.monotonic() - state.paused_at)
        state.paused_at = None
        await interaction.response.send_message(embed=_ok("เล่นต่อแล้วน้า ▶️", title="กลับมาแล้ว~"))
        await self.update_music_panel(interaction.guild_id)

    @app_commands.command(name="stop", description="หยุดเพลง ล้างคิว แล้วออกจากห้องเสียง")
    async def stop(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        if not await self._can_control(interaction, state):
            return
        await interaction.response.defer()
        await self._cleanup(interaction.guild_id, keep_queue=False)
        await interaction.followup.send(embed=_ok("หยุดเพลง ล้างคิว และออกจากห้องเสียงแล้วน้า ⏹️", title="ไว้เจอกันใหม่~"))

    @app_commands.command(name="queue", description="ดูคิวเพลงที่รออยู่")
    async def show_queue(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        await self._load_settings(interaction.guild_id)
        await interaction.response.send_message(embed=build_queue_embed(state))

    @app_commands.command(name="nowplaying", description="ดูว่ากำลังเล่นเพลงอะไรอยู่ (โพสต์ panel ใหม่)")
    async def nowplaying(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id
        state = self.get_state(guild_id)
        await self._load_settings(guild_id)

        old = state.panel_message
        state.text_channel = interaction.channel
        await interaction.response.send_message(embed=build_music_panel_embed(state), view=MusicPanelView(self, state))
        state.panel_message = await interaction.original_response()
        if old is not None and old.id != state.panel_message.id:
            try:
                await old.delete()
            except discord.HTTPException:
                pass
        if state.current is not None and (state.panel_task is None or state.panel_task.done()):
            self._restart_panel_loop(guild_id)

    # ========================================================================
    # 🎚️ EQ / Theme / Volume
    # ========================================================================

    @app_commands.command(name="eq", description="ตั้งค่า EQ ด้วยพรีเซ็ตสำเร็จรูป หรือปรับเบส/แหลมเอง")
    @app_commands.describe(
        preset="เลือกพรีเซ็ตสำเร็จรูป",
        bass="ปรับเบสเอง -10 ถึง 20 (ทับค่าพรีเซ็ต)",
        treble="ปรับแหลมเอง -10 ถึง 20 (ทับค่าพรีเซ็ต)",
    )
    @app_commands.choices(preset=[
        app_commands.Choice(name=f"{data['emoji']} {data['label']} — {data['desc']}"[:100], value=key)
        for key, data in EQ_PRESETS.items()
    ])
    async def eq(
        self,
        interaction: discord.Interaction,
        preset: Optional[app_commands.Choice[str]] = None,
        bass: Optional[app_commands.Range[int, -10, 20]] = None,
        treble: Optional[app_commands.Range[int, -10, 20]] = None,
    ):
        guild_id = interaction.guild_id
        state = self.get_state(guild_id)
        await self._load_settings(guild_id)
        if not await self._can_control(interaction, state, strict=False):
            return

        if preset is not None:
            state.audio_filter.apply_preset(preset.value)
        if bass is not None:
            state.audio_filter.set_bass(bass)
        if treble is not None:
            state.audio_filter.set_treble(treble)

        await interaction.response.send_message(embed=build_eq_embed(state.audio_filter, state.color))
        await self._save_settings(guild_id)

    @app_commands.command(name="eqmenu", description="เปิดเมนู EQ แบบ interactive เลือก/ปรับได้เลย")
    async def eqmenu(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id
        state = self.get_state(guild_id)
        await self._load_settings(guild_id)
        if not await self._can_control(interaction, state, strict=False):
            return
        view = EQView(self, guild_id)
        await interaction.response.send_message(embed=build_eq_embed(state.audio_filter, state.color), view=view)
        view.message = await interaction.original_response()

    async def _theme_color_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        current_lower = current.lower()
        matches = [name for name in THEME_PRESETS if current_lower in name.lower()] or list(THEME_PRESETS)
        return [app_commands.Choice(name=f"{THEME_EMOJI.get(n, '🎨')} {n}", value=n) for n in matches[:25]]

    @app_commands.command(name="settheme", description="ตั้งสีธีม embed ของบอทในเซิร์ฟเวอร์นี้")
    @require_permission()
    @app_commands.describe(color="เลือกพรีเซ็ต หรือพิมพ์ hex code เอง เช่น #ff8800")
    @app_commands.autocomplete(color=_theme_color_autocomplete)
    async def settheme(self, interaction: discord.Interaction, color: str):
        parsed = parse_color(color)
        if parsed is None:
            await interaction.response.send_message(
                embed=_warn("ใส่สีไม่ถูกต้องน้า — เลือกจากพรีเซ็ต หรือพิมพ์ hex code เช่น `#ff8800`"), ephemeral=True
            )
            return
        await self._load_settings(interaction.guild_id)
        state = self.get_state(interaction.guild_id)
        state.color = parsed
        embed = style.brand_embed(
            title="🎨 ตั้งสีธีมใหม่แล้วน้า~",
            description=f"ดูตัวอย่างสีนี้ได้จากแถบสีด้านซ้ายเลย 🌈\nโค้ดสี: `#{parsed:06X}`",
            color=parsed, system="theme",
        )
        await interaction.response.send_message(embed=embed)
        await self._save_settings(interaction.guild_id)

    @app_commands.command(name="thememenu", description="เปิดเมนูตั้งสีธีมแบบ interactive เลือก/ใส่ hex เองได้เลย")
    @require_permission()
    async def thememenu(self, interaction: discord.Interaction):
        await self._load_settings(interaction.guild_id)
        state = self.get_state(interaction.guild_id)
        view = ThemeView(self, interaction.guild_id, interaction.user.id)
        await interaction.response.send_message(embed=build_theme_embed(state.color), view=view)
        view.message = await interaction.original_response()

    @app_commands.command(name="volume", description="ปรับระดับเสียง (0-200)")
    @app_commands.describe(level="ระดับเสียง 0-200 (100 = ปกติ, เกิน 100 = ดังกว่าต้นฉบับ)")
    async def volume(self, interaction: discord.Interaction, level: app_commands.Range[int, 0, 200]):
        guild_id = interaction.guild_id
        state = self.get_state(guild_id)
        await self._load_settings(guild_id)
        if not await self._can_control(interaction, state, strict=False):
            return
        state.volume = level / 100
        vc = state.voice_client
        if vc is not None and vc.source is not None:
            vc.source.volume = state.volume
        face = "🔇" if level == 0 else "🔉" if level < 60 else "🔊"
        await interaction.response.send_message(
            embed=_ok(f"{face} ปรับเสียงเป็น **{level}%** แล้วน้า\n{style.heart_bar(level / 200)}", title="ปรับเสียงแล้ว~")
        )
        await self._save_settings(guild_id)
        await self.update_music_panel(guild_id)

    @app_commands.command(name="leave", description="ออกจากห้องเสียง (ไม่ล้างคิว)")
    async def leave(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        if state.voice_client is None:
            await interaction.response.send_message(embed=_warn("บอทไม่ได้อยู่ในห้องเสียงเลยน้า~"), ephemeral=True)
            return
        if not await self._can_control(interaction, state):
            return
        await interaction.response.defer()
        await self._cleanup(interaction.guild_id, keep_queue=True)
        await interaction.followup.send(embed=_ok("ออกจากห้องเสียงแล้วน้า (คิวยังอยู่ครบ) 👋", title="บ๊ายบาย~"))

    @app_commands.command(name="ffmpeginfo", description="ดูข้อมูล FFmpeg ที่ติดตั้ง (แอดมินเท่านั้น)")
    @require_permission()
    async def ffmpeginfo(self, interaction: discord.Interaction):
        if not FFmpegConfig.check_ffmpeg_available():
            await interaction.response.send_message(
                embed=_err(f"ไม่พบ FFmpeg เลยน้า ต้องติดตั้ง FFmpeg {FFMPEG_VERSION_REQUIRED}+ ก่อนรันบอท"), ephemeral=True
            )
            return
        state = self.get_state(interaction.guild_id)
        embed = style.brand_embed(title="🎚️ FFmpeg Information", color=state.color, system="music")
        embed.add_field(name="📌 ข้อกำหนด", value=f"`FFmpeg {FFMPEG_VERSION_REQUIRED}+`", inline=False)
        embed.add_field(name="✅ ติดตั้งแล้ว", value=f"`{self.ffmpeg_version or 'ไม่ทราบเวอร์ชัน'}`", inline=False)
        embed.add_field(name="📂 Path", value=f"`{FFmpegConfig.get_ffmpeg_path()}`", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ============================================================================
# Setup
# ============================================================================

async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
