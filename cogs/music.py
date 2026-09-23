"""
cogs/music.py — 🎵 Music Player (คลังเพลงจากลิงก์ไฟล์เสียงตรง)

หลังจากลองใช้ yt-dlp และ Lavalink ดึงเสียงจาก YouTube มาทั้งวันแล้วเจอปัญหา
YouTube บล็อกบอท/IP ของ cloud server อยู่เรื่อย ๆ จนแก้ไม่จบ — ระบบนี้เลือกเล่นจาก
"ลิงก์ไฟล์เสียงตรง" (mp3/wav ที่อัปโหลดไว้ที่อื่นแล้ว) แทน ไม่ผ่าน YouTube เลย
จึงไม่มีทางโดนบล็อกแบบเดียวกัน เก็บชื่อ+ลิงก์ไว้ใน MongoDB ผ่าน db.py

⚙️ ข้อกำหนด:
  • FFmpeg 9.0.2+ บนเครื่อง/เซิร์ฟที่รันบอท (ไม่ใช่ pip package)
  • discord.py พร้อม voice support

ขั้นตอนใช้งาน:
  1. แปลงเพลงเป็น mp3 ด้วยแอปที่คุณมีอยู่แล้ว
  2. อัปโหลดไฟล์ไปที่ไหนก็ได้ที่ให้ "ลิงก์ตรง" ถึงไฟล์ (เช่น อัปโหลดใส่ channel ใน Discord
     เอง แล้วคลิกขวาที่ไฟล์ > Copy Link)
  3. ใช้ /addsong ชื่อเพลง ลิงก์ เพื่อเก็บเข้าคลัง
  4. /play ชื่อเพลง เพื่อเล่น (หรือ /play ลิงก์ ถ้าอยากเล่นแบบไม่บันทึกไว้ก่อนก็ได้)
  5. /eqmenu เพื่อเปิดเมนู EQ แบบเลือกได้จริง หรือ /eq preset:xxx เพื่อสั่งตรงๆ

หมายเหตุ: Lavalink server ที่เคยตั้งไว้ (service beluga-lavalink) ยังไม่ได้ลบทิ้ง
เผื่ออนาคตอยากกลับมาลองใหม่ (เช่น ผ่าน proxy IP อื่น) — แค่ตอนนี้บอทไม่ได้เรียกใช้แล้ว
"""

import asyncio
import logging
import os
import subprocess
import shutil
import tempfile
import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import db

log = logging.getLogger("beluga")

# ============================================================================
# 🎛️ FFmpeg Configuration
# ============================================================================

FFMPEG_VERSION_REQUIRED = "9.0.2"

# ตั้งค่า env var FFMPEG_PATH บน Render ให้ชี้ไปที่ binary ที่ดาวน์โหลดมาเอง
# (เช่น "./bin/ffmpeg") เพราะ apt install บน Debian ให้แค่ 5.x เท่านั้น
# ไม่ตั้งไว้ = ใช้ "ffmpeg" จาก system PATH ตามปกติ (อาจได้เวอร์ชั่นเก่า)
FFMPEG_EXECUTABLE = os.environ.get("FFMPEG_PATH", "ffmpeg")

FFMPEG_OPTIONS = {
    "reconnect": 1,
    "reconnect_streamed": 1,
    "reconnect_delay_max": 5,
    # หมายเหตุ: เคยมี "http_persistent": 1 อยู่ตรงนี้ — เอาออกแล้วเพราะเป็น option
    # เฉพาะของ HLS demuxer (.m3u8) เท่านั้น ไม่ใช่ option ของ http/https protocol
    # ทั่วไป พอใช้เปิดไฟล์เดี่ยวอย่าง .m4a/.mp3 ตรงๆ FFmpeg 9.0.2 จะ error
    # "Option not found" ทันที
}


class FFmpegConfig:
    """จัดการการตั้งค่า FFmpeg version และ options"""

    @staticmethod
    def get_ffmpeg_path() -> Optional[str]:
        # รองรับทั้ง path ตรงๆ (เช่น ./bin/ffmpeg) และชื่อคำสั่งใน PATH (เช่น ffmpeg)
        if os.path.isfile(FFMPEG_EXECUTABLE) and os.access(FFMPEG_EXECUTABLE, os.X_OK):
            return os.path.abspath(FFMPEG_EXECUTABLE)
        return shutil.which(FFMPEG_EXECUTABLE)

    @staticmethod
    def check_ffmpeg_available() -> bool:
        return FFmpegConfig.get_ffmpeg_path() is not None

    @staticmethod
    def get_ffmpeg_version() -> Optional[str]:
        path = FFmpegConfig.get_ffmpeg_path()
        if path is None:
            return None
        try:
            result = subprocess.run(
                [path, "-version"], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return result.stdout.split("\n")[0]
            return None
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None


# ============================================================================
# 🎚️ EQ Presets — คลังพรีเซ็ตเสียงสำเร็จรูป
# ============================================================================
# แต่ละพรีเซ็ตกำหนด bass/treble เริ่มต้น + extra filter chain (สำหรับเอฟเฟกต์พิเศษ
# เช่น nightcore/vaporwave ที่ต้องปรับ pitch+tempo ด้วย asetrate/atempo)
# ผู้ใช้เลือกพรีเซ็ตแล้วยังปรับ bass/treble ทับเองได้อีกทีผ่าน /eq

EQ_PRESETS: dict[str, dict] = {
    "flat": {
        "emoji": "⚪",
        "label": "Flat (ปกติ)",
        "desc": "เสียงต้นฉบับ ไม่มีเอฟเฟกต์พิเศษ",
        "bass": 0, "treble": 0, "extra": [],
    },
    "bass_boost": {
        "emoji": "🔊",
        "label": "Bass Boost",
        "desc": "เน้นเบสหนักแน่น เหมาะ EDM / Hip-Hop",
        "bass": 15, "treble": 0, "extra": [],
    },
    "treble_boost": {
        "emoji": "✨",
        "label": "Treble Boost",
        "desc": "เน้นเสียงแหลมใส เหมาะเพลง acoustic",
        "bass": 0, "treble": 10, "extra": [],
    },
    "vocal_boost": {
        "emoji": "🎤",
        "label": "Vocal Boost",
        "desc": "ดันเสียงร้องให้เด่นชัดขึ้น",
        "bass": -3, "treble": 6, "extra": [],
    },
    "party": {
        "emoji": "🎉",
        "label": "Party Mode",
        "desc": "เบส+แหลมเพิ่มพร้อมกัน ฟังมันส์สุด",
        "bass": 12, "treble": 8, "extra": [],
    },
    "nightcore": {
        "emoji": "⚡",
        "label": "Nightcore",
        "desc": "เร่งความเร็ว+คีย์สูงขึ้น สไตล์ nightcore",
        "bass": 0, "treble": 0,
        "extra": ["asetrate=44100*1.25", "aresample=44100", "atempo=1.05"],
    },
    "vaporwave": {
        "emoji": "🌴",
        "label": "Vaporwave",
        "desc": "ลดความเร็ว+คีย์ต่ำลง บรรยากาศ chill",
        "bass": 3, "treble": 0,
        "extra": ["asetrate=44100*0.85", "aresample=44100", "atempo=0.95"],
    },
    "deep": {
        "emoji": "🕳️",
        "label": "Deep Voice",
        "desc": "เสียงทุ้มต่ำลงโดยไม่เปลี่ยนความเร็วเพลง",
        "bass": 5, "treble": -3,
        "extra": ["asetrate=44100*0.9", "aresample=44100", "atempo=1.111"],
    },
    "chipmunk": {
        "emoji": "🐿️",
        "label": "Chipmunk",
        "desc": "เสียงสูงแบบตัวการ์ตูน ไม่เปลี่ยนความเร็วเพลง",
        "bass": -3, "treble": 5,
        "extra": ["asetrate=44100*1.4", "aresample=44100", "atempo=0.714"],
    },
    "8d": {
        "emoji": "🌀",
        "label": "8D Audio",
        "desc": "เสียงหมุนรอบทิศ ใส่หูฟังฟังฟินมาก",
        "bass": 2, "treble": 2,
        "extra": ["apulsator=hz=0.09"],
    },
    "karaoke": {
        "emoji": "🎙️",
        "label": "Karaoke",
        "desc": "พยายามตัดเสียงร้องออก เหลือดนตรี (ไม่การันตี 100%)",
        "bass": 0, "treble": 0,
        "extra": ["pan=stereo|c0=c0-c1|c1=c1-c0"],
    },
}

DEFAULT_PRESET = "flat"


# ============================================================================
# 🎨 Theme Colors — สีธีม embed ที่ตั้งได้ต่อ guild
# ============================================================================

THEME_PRESETS: dict[str, int] = {
    "blurple": 0x5865F2,
    "แดง": 0xED4245,
    "ส้ม": 0xE67E22,
    "เหลือง": 0xF1C40F,
    "เขียว": 0x57F287,
    "ฟ้า": 0x3498DB,
    "ม่วง": 0x9B59B6,
    "ชมพู": 0xEB459E,
    "ขาว": 0xFFFFFF,
    "ดำ": 0x23272A,
}
DEFAULT_COLOR = THEME_PRESETS["blurple"]


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


def make_bar(value: int, min_val: int = -10, max_val: int = 20, length: int = 10) -> str:
    """สร้างแถบ progress bar แบบ unicode สำหรับโชว์ค่า bass/treble"""
    ratio = (value - min_val) / (max_val - min_val)
    filled = max(0, min(length, round(ratio * length)))
    return "█" * filled + "░" * (length - filled)


# ============================================================================
# 🎵 Queue Items & Audio Filter
# ============================================================================

class QueueItem:
    __slots__ = ("title", "url", "requester", "thumbnail", "duration")

    def __init__(
        self,
        title: str,
        url: str,
        requester: discord.Member,
        thumbnail: Optional[str] = None,
        duration: Optional[float] = None,
    ):
        self.title = title
        self.url = url
        self.requester = requester
        self.thumbnail = thumbnail
        self.duration = duration


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

    def build_ffmpeg_options(self) -> dict:
        before_parts = [f"-{key} {val}" for key, val in FFMPEG_OPTIONS.items()]
        before_options = " ".join(before_parts)

        options = "-vn"
        filter_str = self.audio_filter.to_filter_string()
        if filter_str:
            options += f' -af "{filter_str}"'

        return {"before_options": before_options, "options": options}


# ============================================================================
# 🖼️ Embed Builder
# ============================================================================

def build_eq_embed(audio_filter: AudioFilter, color: int = DEFAULT_COLOR) -> discord.Embed:
    """สร้าง embed สวยๆ โชว์สถานะ EQ ปัจจุบัน"""
    preset_data = EQ_PRESETS[audio_filter.preset]

    embed = discord.Embed(
        title="🎚️ Equalizer",
        description=f"{preset_data['emoji']} **{preset_data['label']}**\n{preset_data['desc']}",
        color=color,
    )
    embed.add_field(
        name="เบส (Bass)",
        value=f"`{make_bar(audio_filter.bass)}`  **{audio_filter.bass:+d}**",
        inline=False,
    )
    embed.add_field(
        name="แหลม (Treble)",
        value=f"`{make_bar(audio_filter.treble)}`  **{audio_filter.treble:+d}**",
        inline=False,
    )
    if audio_filter.extra_filters:
        embed.add_field(name="เอฟเฟกต์พิเศษ", value="✅ เปิดใช้งานอยู่ (ปรับ pitch/tempo)", inline=False)
    embed.set_footer(text="มีผลตั้งแต่เพลงถัดไป — ใช้ /skip เพื่อให้มีผลทันที")
    return embed


# ============================================================================
# 🕹️ Interactive EQ Menu (Select + Buttons)
# ============================================================================

class EQSelect(discord.ui.Select):
    def __init__(self, music_cog: "Music", guild_id: int):
        options = [
            discord.SelectOption(
                label=data["label"],
                description=data["desc"][:100],
                emoji=data["emoji"],
                value=key,
            )
            for key, data in EQ_PRESETS.items()
        ]
        super().__init__(
            placeholder="🎧 เลือกพรีเซ็ต EQ...",
            options=options,
            min_values=1,
            max_values=1,
        )
        self.music_cog = music_cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        state = self.music_cog.get_state(self.guild_id)
        state.audio_filter.apply_preset(self.values[0])
        embed = build_eq_embed(state.audio_filter, state.color)
        await interaction.response.edit_message(embed=embed, view=self.view)


class EQResetButton(discord.ui.Button):
    def __init__(self, music_cog: "Music", guild_id: int):
        super().__init__(label="รีเซ็ตเป็นค่าเริ่มต้น", style=discord.ButtonStyle.secondary, emoji="🔄")
        self.music_cog = music_cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        state = self.music_cog.get_state(self.guild_id)
        state.audio_filter.apply_preset(DEFAULT_PRESET)
        embed = build_eq_embed(state.audio_filter, state.color)
        await interaction.response.edit_message(embed=embed, view=self.view)


class EQBassDownButton(discord.ui.Button):
    def __init__(self, music_cog: "Music", guild_id: int):
        super().__init__(label="เบส -", style=discord.ButtonStyle.primary, emoji="🔉", row=1)
        self.music_cog = music_cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        state = self.music_cog.get_state(self.guild_id)
        state.audio_filter.set_bass(max(-10, state.audio_filter.bass - 2))
        await interaction.response.edit_message(embed=build_eq_embed(state.audio_filter, state.color), view=self.view)


class EQBassUpButton(discord.ui.Button):
    def __init__(self, music_cog: "Music", guild_id: int):
        super().__init__(label="เบส +", style=discord.ButtonStyle.primary, emoji="🔊", row=1)
        self.music_cog = music_cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        state = self.music_cog.get_state(self.guild_id)
        state.audio_filter.set_bass(min(20, state.audio_filter.bass + 2))
        await interaction.response.edit_message(embed=build_eq_embed(state.audio_filter, state.color), view=self.view)


class EQTrebleDownButton(discord.ui.Button):
    def __init__(self, music_cog: "Music", guild_id: int):
        super().__init__(label="แหลม -", style=discord.ButtonStyle.success, emoji="🔅", row=1)
        self.music_cog = music_cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        state = self.music_cog.get_state(self.guild_id)
        state.audio_filter.set_treble(max(-10, state.audio_filter.treble - 2))
        await interaction.response.edit_message(embed=build_eq_embed(state.audio_filter, state.color), view=self.view)


class EQTrebleUpButton(discord.ui.Button):
    def __init__(self, music_cog: "Music", guild_id: int):
        super().__init__(label="แหลม +", style=discord.ButtonStyle.success, emoji="🔆", row=1)
        self.music_cog = music_cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        state = self.music_cog.get_state(self.guild_id)
        state.audio_filter.set_treble(min(20, state.audio_filter.treble + 2))
        await interaction.response.edit_message(embed=build_eq_embed(state.audio_filter, state.color), view=self.view)


class EQView(discord.ui.View):
    """เมนู EQ แบบ interactive — เลือกพรีเซ็ตจาก dropdown หรือกดปุ่มปรับละเอียดทีละขั้น"""

    def __init__(self, music_cog: "Music", guild_id: int):
        super().__init__(timeout=180)
        self.add_item(EQSelect(music_cog, guild_id))
        self.add_item(EQBassDownButton(music_cog, guild_id))
        self.add_item(EQBassUpButton(music_cog, guild_id))
        self.add_item(EQTrebleDownButton(music_cog, guild_id))
        self.add_item(EQTrebleUpButton(music_cog, guild_id))
        self.add_item(EQResetButton(music_cog, guild_id))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ============================================================================
# 🎵 Now Playing Control Panel
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


def _progress_bar(elapsed: float, duration: Optional[float], length: int = 24) -> str:
    if not duration or duration <= 0:
        return "🔘" + "─" * (length - 1)
    ratio = max(0.0, min(1.0, elapsed / duration))
    filled = max(0, min(length, round(ratio * length)))
    return "━" * filled + "●" + "─" * max(0, length - filled - 1)


def get_panel_elapsed(state: GuildMusicState) -> float:
    if state.started_at is None:
        return 0.0
    now = time.monotonic()
    paused_total = state.paused_total
    if state.paused_at is not None:
        paused_total += max(0.0, now - state.paused_at)
    return max(0.0, now - state.started_at - paused_total)


BOT_NAME = "Anyaluga"


def build_music_panel_embed(state: GuildMusicState) -> discord.Embed:
    """สร้าง Now Playing panel สไตล์การ์ดเพลง (คล้ายตัวอย่างที่ส่งมา) พร้อมแบรนด์ Anyaluga"""
    if state.current is None:
        embed = discord.Embed(
            title="ไม่มีเพลงกำลังเล่นอยู่",
            description="ใช้ `/play` เพื่อเริ่มเพลง",
            color=state.color,
        )
        embed.set_author(name=f"🎵 {BOT_NAME}")
        embed.set_footer(text=f"{BOT_NAME} • Audio Library")
        return embed

    item = state.current
    elapsed = get_panel_elapsed(state)
    duration = item.duration

    if state.voice_client and state.voice_client.is_paused():
        status = "⏸️ Paused"
    elif state.voice_client and state.voice_client.is_playing():
        status = "▶️ Playing"
    else:
        status = "⏹️ Stopped"

    progress = _progress_bar(elapsed, duration)
    time_text = f"{_format_time(elapsed)} / {_format_time(duration)}"

    preset_data = EQ_PRESETS[state.audio_filter.preset]
    repeat_label = {"off": "ปิด", "one": "เพลงนี้", "all": "ทั้งหมด"}.get(state.repeat, "ปิด")
    shuffle_label = "เปิด" if state.shuffle else "ปิด"
    favorite_label = "❤️" if item.url in state.favorites else "♡"

    embed = discord.Embed(
        title=item.title,
        description=(
            f"{item.requester.mention}\n\n"
            f"`{time_text}`\n"
            f"`{progress}`"
        ),
        color=state.color,
    )
    # แถบเล็กด้านบน เลียนแบบ "Playing from ..." ในตัวอย่าง
    embed.set_author(name=f"🎵 {BOT_NAME} • เล่นจาก Audio Library")

    if item.thumbnail:
        embed.set_thumbnail(url=item.thumbnail)

    embed.add_field(
        name="สถานะ",
        value=f"{status}  •  🎛️ {preset_data['emoji']} **{preset_data['label']}**",
        inline=False,
    )
    embed.add_field(name="🔁 วนซ้ำ", value=repeat_label, inline=True)
    embed.add_field(name="🔀 สุ่ม", value=shuffle_label, inline=True)
    embed.add_field(name=f"{favorite_label} ถูกใจ", value="\u200b", inline=True)
    embed.add_field(name="📋 คิว", value=f"{len(state.queue)} เพลง", inline=True)

    embed.set_footer(
        text=(
            f"พิมพ์ชื่อเพลงเพื่อเพิ่มเพลง • Vol: {round(state.volume * 100)}% "
            f"• Repeat: {repeat_label}"
        )
    )
    return embed


class MusicPanelButton(discord.ui.Button):
    def __init__(self, label: str, emoji: str, style: discord.ButtonStyle, action: str, row: int):
        super().__init__(label=label, emoji=emoji, style=style, row=row)
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        view: "MusicPanelView" = self.view  # type: ignore
        await view.handle_action(interaction, self.action)


class MusicPanelView(discord.ui.View):
    """ปุ่ม Now Playing: ⏮️ ⏸️ ⏭️ ⏹️ 🔀 / 🔁 🔉 🔊 📋 ❤️"""

    def __init__(self, music_cog: "Music", guild_id: int):
        super().__init__(timeout=None)
        self.music_cog = music_cog
        self.guild_id = guild_id

        # Row 0
        self.add_item(MusicPanelButton("ก่อนหน้า", "⏮️", discord.ButtonStyle.secondary, "previous", 0))
        self.add_item(MusicPanelButton("พัก/เล่นต่อ", "⏸️", discord.ButtonStyle.primary, "pause", 0))
        self.add_item(MusicPanelButton("ถัดไป", "⏭️", discord.ButtonStyle.secondary, "skip", 0))
        self.add_item(MusicPanelButton("หยุด", "⏹️", discord.ButtonStyle.danger, "stop", 0))
        self.add_item(MusicPanelButton("สุ่ม", "🔀", discord.ButtonStyle.secondary, "shuffle", 0))

        # Row 1
        self.add_item(MusicPanelButton("วนซ้ำ", "🔁", discord.ButtonStyle.secondary, "repeat", 1))
        self.add_item(MusicPanelButton("เบา", "🔉", discord.ButtonStyle.secondary, "volume_down", 1))
        self.add_item(MusicPanelButton("ดัง", "🔊", discord.ButtonStyle.secondary, "volume_up", 1))
        self.add_item(MusicPanelButton("คิว", "📋", discord.ButtonStyle.secondary, "queue", 1))
        self.add_item(MusicPanelButton("ถูกใจ", "❤️", discord.ButtonStyle.secondary, "favorite", 1))

    async def handle_action(self, interaction: discord.Interaction, action: str):
        state = self.music_cog.get_state(self.guild_id)

        if action == "pause":
            if state.voice_client is None:
                await interaction.response.send_message("⛔ บอทยังไม่ได้อยู่ในห้องเสียงครับ", ephemeral=True)
                return
            if state.voice_client.is_playing():
                state.voice_client.pause()
                state.paused_at = time.monotonic()
            elif state.voice_client.is_paused():
                state.voice_client.resume()
                if state.paused_at is not None:
                    state.paused_total += max(0.0, time.monotonic() - state.paused_at)
                state.paused_at = None
            else:
                await interaction.response.send_message("⛔ ไม่มีเพลงกำลังเล่นครับ", ephemeral=True)
                return

        elif action == "skip":
            if state.voice_client is None or not (state.voice_client.is_playing() or state.voice_client.is_paused()):
                await interaction.response.send_message("⛔ ไม่มีเพลงกำลังเล่นครับ", ephemeral=True)
                return
            state.voice_client.stop()

        elif action == "stop":
            state.queue.clear()
            state.current = None
            if state.panel_task:
                state.panel_task.cancel()
                state.panel_task = None
            if state.voice_client is not None:
                await state.voice_client.disconnect()
                state.voice_client = None

        elif action == "previous":
            if state.current is None:
                await interaction.response.send_message("⛔ ไม่มีเพลงปัจจุบันครับ", ephemeral=True)
                return
            elapsed = get_panel_elapsed(state)
            if elapsed > 5:
                # กดก่อนหน้าระหว่างเพลง = เริ่มเพลงปัจจุบันใหม่
                if state.voice_client and state.voice_client.is_playing():
                    state.voice_client.stop()
                state.queue.insert(0, state.current)
            elif state.history:
                previous = state.history.pop()
                if state.voice_client and (state.voice_client.is_playing() or state.voice_client.is_paused()):
                    state.voice_client.stop()
                state.queue.insert(0, state.current)
                state.queue.insert(0, previous)
            else:
                await interaction.response.send_message("⛔ ยังไม่มีเพลงก่อนหน้าครับ", ephemeral=True)
                return

        elif action == "shuffle":
            state.shuffle = not state.shuffle
            if state.shuffle and len(state.queue) > 1:
                import random
                random.shuffle(state.queue)

        elif action == "repeat":
            state.repeat = {"off": "one", "one": "all", "all": "off"}.get(state.repeat, "off")

        elif action == "volume_down":
            state.volume = max(0.0, round(state.volume - 0.1, 2))
            if state.voice_client and state.voice_client.source:
                state.voice_client.source.volume = state.volume

        elif action == "volume_up":
            state.volume = min(2.0, round(state.volume + 0.1, 2))
            if state.voice_client and state.voice_client.source:
                state.voice_client.source.volume = state.volume

        elif action == "queue":
            if state.queue:
                lines = [
                    f"`{i+1:02d}` **{item.title}**"
                    for i, item in enumerate(state.queue[:10])
                ]
                if len(state.queue) > 10:
                    lines.append(f"...และอีก {len(state.queue) - 10} เพลง")
                msg = "📋 **คิวเพลง**\n" + "\n".join(lines)
            else:
                msg = "📋 **คิวเพลง**\nไม่มีเพลงรออยู่ครับ"
            await interaction.response.send_message(msg, ephemeral=True)
            return

        elif action == "favorite":
            if state.current is None:
                await interaction.response.send_message("⛔ ไม่มีเพลงปัจจุบันครับ", ephemeral=True)
                return
            if state.current.url in state.favorites:
                state.favorites.remove(state.current.url)
            else:
                state.favorites.add(state.current.url)

        await self.music_cog.update_music_panel(self.guild_id)
        if not interaction.response.is_done():
            await interaction.response.edit_message(
                embed=build_music_panel_embed(state),
                view=self,
            )


# ============================================================================
# 🎶 Music Cog — Main Controller
# ============================================================================

class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.states: dict[int, GuildMusicState] = {}
        self._check_ffmpeg_on_startup()

    def _check_ffmpeg_on_startup(self):
        if not FFmpegConfig.check_ffmpeg_available():
            log.error(
                f"❌ FFmpeg ไม่พบบนระบบ — Music cog จะไม่ทำงาน "
                f"ติดตั้ง FFmpeg {FFMPEG_VERSION_REQUIRED}+ ก่อนรันบอท"
            )
        else:
            log.info(f"✅ FFmpeg พบ: {FFmpegConfig.get_ffmpeg_version()}")

    def get_state(self, guild_id: int) -> GuildMusicState:
        if guild_id not in self.states:
            self.states[guild_id] = GuildMusicState()
        return self.states[guild_id]

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
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=8)
            if proc.returncode == 0:
                value = float(stdout.decode().strip())
                return value if value > 0 else None
        except (asyncio.TimeoutError, ValueError, FileNotFoundError, OSError):
            pass
        return None

    async def update_music_panel(self, guild_id: int):
        state = self.get_state(guild_id)
        if state.text_channel is None:
            return

        embed = build_music_panel_embed(state)
        view = MusicPanelView(self, guild_id)

        try:
            if state.panel_message is not None:
                await state.panel_message.edit(embed=embed, view=view)
                return
        except (discord.NotFound, discord.HTTPException):
            state.panel_message = None

        try:
            state.panel_message = await state.text_channel.send(embed=embed, view=view)
        except discord.HTTPException as exc:
            log.warning("[music] ส่ง Now Playing panel ไม่สำเร็จ: %s", exc)

    async def _panel_loop(self, guild_id: int):
        """อัปเดต progress bar ทุก 5 วินาที"""
        try:
            while True:
                await asyncio.sleep(5)
                state = self.get_state(guild_id)
                if state.current is None or state.panel_message is None:
                    return
                try:
                    await state.panel_message.edit(
                        embed=build_music_panel_embed(state),
                        view=MusicPanelView(self, guild_id),
                    )
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

    # ---------- Playback Management ----------

    def _play_next(self, guild_id: int):
        state = self.states.get(guild_id)
        if state is None:
            return
        asyncio.run_coroutine_threadsafe(self._start_next_track(guild_id), self.bot.loop)

    async def _start_next_track(self, guild_id: int):
        state = self.get_state(guild_id)

        if not state.queue:
            state.current = None
            state.started_at = None
            state.paused_at = None
            state.paused_total = 0.0
            if state.panel_task and not state.panel_task.done():
                state.panel_task.cancel()
                state.panel_task = None
            await self.update_music_panel(guild_id)
            return

        item = state.queue.pop(0)
        if state.current is not None:
            state.history.append(state.current)
            state.history = state.history[-20:]
        state.current = item
        state.started_at = time.monotonic()
        state.paused_at = None
        state.paused_total = 0.0

        if item.duration is None:
            item.duration = await self._probe_duration(item.url)

        if state.voice_client is None or not state.voice_client.is_connected():
            return

        if not FFmpegConfig.check_ffmpeg_available():
            if state.text_channel:
                await state.text_channel.send("❌ FFmpeg ไม่พบ — ไม่สามารถเล่นเพลงได้")
            return

        try:
            source = discord.FFmpegPCMAudio(
                item.url,
                executable=FFmpegConfig.get_ffmpeg_path() or FFMPEG_EXECUTABLE,
                **state.build_ffmpeg_options(),
            )
            source = discord.PCMVolumeTransformer(source, volume=state.volume)

            def after_playing(error):
                if error:
                    log.error(f"[music] เล่นเพลงพลาด (guild {guild_id}): {error}")

                # repeat one = ใส่เพลงเดิมกลับเข้าคิว
                state = self.states.get(guild_id)
                if state and state.current and state.repeat == "one":
                    state.queue.insert(0, state.current)
                elif state and state.current and state.repeat == "all":
                    state.queue.append(state.current)

                self._play_next(guild_id)

            state.voice_client.play(source, after=after_playing)
            await self.update_music_panel(guild_id)
            self._restart_panel_loop(guild_id)
        except Exception as e:
            log.error(f"[music] เกิด error ขณะเล่น: {e}")
            if state.text_channel:
                await state.text_channel.send(f"❌ เกิด error: {e}")

    async def _ensure_voice(self, interaction: discord.Interaction) -> Optional[discord.VoiceClient]:
        member = interaction.user
        if member.voice is None or member.voice.channel is None:
            await interaction.followup.send("⛔ ต้องเข้าห้องเสียงก่อนถึงจะสั่งเล่นเพลงได้ครับ")
            return None

        state = self.get_state(interaction.guild_id)
        channel = member.voice.channel

        if state.voice_client is None or not state.voice_client.is_connected():
            state.voice_client = await channel.connect()
        elif state.voice_client.channel != channel:
            await state.voice_client.move_to(channel)

        state.text_channel = interaction.channel
        return state.voice_client

    # ---------- Song Library Commands ----------

    @app_commands.command(name="addsong", description="เพิ่มเพลงเข้าคลัง (ลิงก์ไฟล์เสียงตรง)")
    @app_commands.describe(
        name="ชื่อเพลงที่จะใช้เรียก",
        url="ลิงก์ไฟล์เสียงตรง (mp3/wav/etc)",
        thumbnail="ลิงก์รูปภาพปก (ไม่บังคับ) — โชว์เป็นภาพประกอบตอนเล่นเพลง",
    )
    async def addsong(
        self,
        interaction: discord.Interaction,
        name: str,
        url: str,
        thumbnail: Optional[str] = None,
    ):
        if not url.startswith(("http://", "https://")):
            await interaction.response.send_message(
                "⛔ ลิงก์ต้องขึ้นต้นด้วย http:// หรือ https:// ครับ", ephemeral=True
            )
            return
        if thumbnail is not None and not thumbnail.startswith(("http://", "https://")):
            await interaction.response.send_message(
                "⛔ ลิงก์ภาพปกต้องขึ้นต้นด้วย http:// หรือ https:// ครับ", ephemeral=True
            )
            return

        try:
            # db.py ต้องรองรับ thumbnail_url เป็น keyword เพิ่มเติม (ดูหมายเหตุท้ายไฟล์)
            await db.add_song(interaction.guild_id, name, url, interaction.user.id, thumbnail_url=thumbnail)
        except TypeError:
            # db.py ตัวเก่ายังไม่รองรับ thumbnail_url — เก็บแบบไม่มีภาพปกไปก่อน
            await db.add_song(interaction.guild_id, name, url, interaction.user.id)
            if thumbnail is not None:
                log.warning("db.add_song ยังไม่รองรับ thumbnail_url — ข้ามภาพปกไปก่อน (ดูหมายเหตุท้าย music.py)")

        await interaction.response.send_message(f"✅ เพิ่ม **{name}** เข้าคลังเพลงแล้วครับ")

    @app_commands.command(
        name="addsongfromvideo",
        description="อัปโหลดวิดีโอที่อัดเอง บอทจะตัดเสียง+จับภาพนิ่งเป็นปกให้อัตโนมัติ",
    )
    @app_commands.describe(
        name="ชื่อเพลงที่จะใช้เรียก",
        video="ไฟล์วิดีโอที่อัดมา (mp4/mov ฯลฯ) — จำกัดตามขนาดไฟล์ที่ Discord อนุญาตอัปโหลด",
        thumbnail_time="วินาทีในคลิปที่จะจับภาพเป็นปก (ค่าเริ่มต้น 0 = เฟรมแรก)",
    )
    async def addsongfromvideo(
        self,
        interaction: discord.Interaction,
        name: str,
        video: discord.Attachment,
        thumbnail_time: Optional[app_commands.Range[int, 0, 3600]] = 0,
    ):
        if not (video.content_type and video.content_type.startswith("video/")):
            await interaction.response.send_message("⛔ ไฟล์ที่แนบต้องเป็นวิดีโอครับ", ephemeral=True)
            return

        await interaction.response.defer()

        ffmpeg_bin = FFmpegConfig.get_ffmpeg_path() or FFMPEG_EXECUTABLE
        if not FFmpegConfig.check_ffmpeg_available():
            await interaction.followup.send("❌ FFmpeg ไม่พบ — ตัดเสียงจากวิดีโอไม่ได้ครับ")
            return

        tmp_dir = tempfile.mkdtemp(prefix="beluga_video_")
        try:
            ext = os.path.splitext(video.filename)[1] or ".mp4"
            video_path = os.path.join(tmp_dir, f"input{ext}")
            audio_path = os.path.join(tmp_dir, "audio.m4a")
            thumb_path = os.path.join(tmp_dir, "thumb.jpg")

            await video.save(video_path)

            # ตัดเสียงออกมาเป็น AAC — Discord voice เล่นได้แค่เสียง ไม่มีทางเล่น "วิดีโอ" ในห้องเสียงได้จริง
            audio_proc = await asyncio.create_subprocess_exec(
                ffmpeg_bin, "-y", "-i", video_path, "-vn", "-c:a", "aac", "-b:a", "192k", audio_path,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            _, audio_stderr = await audio_proc.communicate()

            if audio_proc.returncode != 0 or not os.path.isfile(audio_path):
                log.error(f"[music] ตัดเสียงจากวิดีโอไม่สำเร็จ: {audio_stderr.decode(errors='ignore')[-500:]}")
                await interaction.followup.send("❌ ตัดเสียงจากวิดีโอไม่สำเร็จ ลองไฟล์อื่นดูครับ")
                return

            # จับภาพนิ่งจากวิดีโอไว้เป็นปกเพลง (ภาพประกอบ) — แทนที่การเล่นวิดีโอจริง
            thumb_proc = await asyncio.create_subprocess_exec(
                ffmpeg_bin, "-y", "-ss", str(thumbnail_time), "-i", video_path,
                "-frames:v", "1", "-q:v", "3", thumb_path,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            await thumb_proc.communicate()
            has_thumbnail = thumb_proc.returncode == 0 and os.path.isfile(thumb_path)

            # อัปโหลดไฟล์ที่ตัดแล้วเข้า channel นี้เพื่อเอาลิงก์ CDN ของ Discord มาเก็บใน DB แทนไฟล์วิดีโอเต็มๆ
            files_to_send = [discord.File(audio_path, filename=f"{name}.m4a")]
            if has_thumbnail:
                files_to_send.append(discord.File(thumb_path, filename=f"{name}.jpg"))

            upload_msg = await interaction.channel.send(
                content=f"📦 ไฟล์คลังของ **{name}** (ตัดจากวิดีโอที่อัปโหลด)", files=files_to_send
            )
            audio_url = upload_msg.attachments[0].url
            thumb_url = upload_msg.attachments[1].url if has_thumbnail and len(upload_msg.attachments) > 1 else None

            try:
                await db.add_song(interaction.guild_id, name, audio_url, interaction.user.id, thumbnail_url=thumb_url)
            except TypeError:
                await db.add_song(interaction.guild_id, name, audio_url, interaction.user.id)
                log.warning("db.add_song ยังไม่รองรับ thumbnail_url — ข้ามภาพปกไปก่อน (ดูหมายเหตุท้าย music.py)")

            state = self.get_state(interaction.guild_id)
            embed = discord.Embed(
                description=f"✅ เพิ่ม **{name}** เข้าคลังแล้วครับ — ตัดเสียง+ภาพปกจากวิดีโอให้อัตโนมัติ",
                color=state.color,
            )
            if thumb_url:
                embed.set_thumbnail(url=thumb_url)
            await interaction.followup.send(embed=embed)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @app_commands.command(name="removesong", description="ลบเพลงออกจากคลัง")
    @app_commands.describe(name="ชื่อเพลงที่จะลบ")
    async def removesong(self, interaction: discord.Interaction, name: str):
        removed = await db.remove_song(interaction.guild_id, name)
        if removed:
            await interaction.response.send_message(f"🗑️ ลบ **{name}** ออกจากคลังแล้วครับ")
        else:
            await interaction.response.send_message("⛔ ไม่เจอเพลงชื่อนี้ในคลังครับ", ephemeral=True)

    @app_commands.command(name="songlist", description="ดูรายชื่อเพลงทั้งหมดในคลัง")
    async def songlist(self, interaction: discord.Interaction):
        songs = await db.list_songs(interaction.guild_id)
        if not songs:
            await interaction.response.send_message("คลังเพลงยังว่างอยู่ครับ ลองเพิ่มด้วย `/addsong` ก่อน")
            return
        lines = [f"• {s['name']}" for s in songs[:30]]
        if len(songs) > 30:
            lines.append(f"...และอีก {len(songs) - 30} เพลง")
        embed = discord.Embed(title="🎵 คลังเพลง", description="\n".join(lines), color=self.get_state(interaction.guild_id).color)
        await interaction.response.send_message(embed=embed)

    # ---------- Playback Control Commands ----------

    @app_commands.command(name="play", description="เล่นเพลงจากคลัง หรือลิงก์ไฟล์เสียงตรง")
    @app_commands.describe(query="ชื่อเพลงในคลัง หรือลิงก์ไฟล์เสียงตรง")
    async def play(self, interaction: discord.Interaction, query: str):
        if interaction.guild is None:
            return

        await interaction.response.defer()

        voice_client = await self._ensure_voice(interaction)
        if voice_client is None:
            return

        if query.startswith(("http://", "https://")):
            title, url, thumbnail = query, query, None
        else:
            song = await db.get_song(interaction.guild_id, query)
            if song is None:
                await interaction.followup.send("⛔ ไม่เจอเพลงนี้ในคลังครับ ลองเช็คชื่อด้วย `/songlist`")
                return
            title, url = song["name"], song["url"]
            thumbnail = song.get("thumbnail_url")

        state = self.get_state(interaction.guild_id)
        state.queue.append(QueueItem(title, url, interaction.user, thumbnail))

        if voice_client.is_playing() or voice_client.is_paused():
            await interaction.followup.send(f"➕ เข้าคิวแล้ว: **{title}** — อันดับที่ {len(state.queue)}")
        else:
            await interaction.followup.send(f"▶️ กำลังเล่น: **{title}**")
            await self._start_next_track(interaction.guild_id)

    @app_commands.command(name="skip", description="ข้ามเพลงไปเพลงต่อไปในคิว")
    async def skip(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        if state.voice_client is None or not (state.voice_client.is_playing() or state.voice_client.is_paused()):
            await interaction.response.send_message("⛔ ไม่มีเพลงกำลังเล่นอยู่ครับ", ephemeral=True)
            return
        state.voice_client.stop()
        await interaction.response.send_message("⏭️ ข้ามเพลงแล้วครับ")

    @app_commands.command(name="pause", description="พักเพลงที่กำลังเล่นไว้ชั่วคราว")
    async def pause(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        if state.voice_client is None or not state.voice_client.is_playing():
            await interaction.response.send_message("⛔ ไม่มีเพลงกำลังเล่นอยู่ครับ", ephemeral=True)
            return
        state.voice_client.pause()
        state.paused_at = time.monotonic()
        await self.update_music_panel(interaction.guild_id)
        await interaction.response.send_message("⏸️ พักเพลงไว้แล้วครับ")

    @app_commands.command(name="resume", description="เล่นเพลงที่พักไว้ต่อ")
    async def resume(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        if state.voice_client is None or not state.voice_client.is_paused():
            await interaction.response.send_message("⛔ ไม่มีเพลงที่พักไว้ครับ", ephemeral=True)
            return
        state.voice_client.resume()
        if state.paused_at is not None:
            state.paused_total += max(0.0, time.monotonic() - state.paused_at)
        state.paused_at = None
        await self.update_music_panel(interaction.guild_id)
        await interaction.response.send_message("▶️ เล่นต่อแล้วครับ")

    @app_commands.command(name="stop", description="หยุดเพลง ล้างคิว แล้วออกจากห้องเสียง")
    async def stop(self, interaction: discord.Interaction):
        await interaction.response.defer()
        state = self.get_state(interaction.guild_id)
        state.queue.clear()
        state.current = None
        state.started_at = None
        state.paused_at = None
        state.paused_total = 0.0
        if state.panel_task and not state.panel_task.done():
            state.panel_task.cancel()
            state.panel_task = None
        if state.voice_client is not None:
            await state.voice_client.disconnect()
            state.voice_client = None
        await self.update_music_panel(interaction.guild_id)
        await interaction.followup.send("⏹️ หยุดเพลงและออกจากห้องเสียงแล้วครับ")

    @app_commands.command(name="queue", description="ดูคิวเพลงที่รออยู่")
    async def show_queue(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        embed = discord.Embed(title="🎵 คิวเพลง", color=state.color)

        if state.current:
            embed.add_field(
                name="กำลังเล่น",
                value=f"**{state.current.title}** — ขอโดย {state.current.requester.mention}",
                inline=False,
            )
            if state.current.thumbnail:
                embed.set_thumbnail(url=state.current.thumbnail)
        else:
            embed.add_field(name="กำลังเล่น", value="ไม่มีเพลงเล่นอยู่", inline=False)

        if state.queue:
            lines = [
                f"{i+1}. **{item.title}** — ขอโดย {item.requester.mention}"
                for i, item in enumerate(state.queue[:10])
            ]
            if len(state.queue) > 10:
                lines.append(f"...และอีก {len(state.queue) - 10} เพลง")
            embed.add_field(name="รอในคิว", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="รอในคิว", value="ไม่มีเพลงในคิว", inline=False)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="nowplaying", description="ดูว่ากำลังเล่นเพลงอะไรอยู่")
    async def nowplaying(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        if state.current is None:
            await interaction.response.send_message(
                embed=build_music_panel_embed(state),
                view=MusicPanelView(self, interaction.guild_id),
            )
            return

        await interaction.response.send_message(
            embed=build_music_panel_embed(state),
            view=MusicPanelView(self, interaction.guild_id),
        )

    # ---------- EQ Commands ----------

    @app_commands.command(name="eq", description="ตั้งค่า EQ ด้วยพรีเซ็ตสำเร็จรูป หรือปรับเบส/แหลมเอง")
    @app_commands.describe(
        preset="เลือกพรีเซ็ตสำเร็จรูป",
        bass="ปรับเบสเอง -10 ถึง 20 (ทับค่าพรีเซ็ต)",
        treble="ปรับแหลมเอง -10 ถึง 20 (ทับค่าพรีเซ็ต)",
    )
    @app_commands.choices(preset=[
        app_commands.Choice(name=f"{data['emoji']} {data['label']} — {data['desc']}", value=key)
        for key, data in EQ_PRESETS.items()
    ])
    async def eq(
        self,
        interaction: discord.Interaction,
        preset: Optional[app_commands.Choice[str]] = None,
        bass: Optional[app_commands.Range[int, -10, 20]] = None,
        treble: Optional[app_commands.Range[int, -10, 20]] = None,
    ):
        state = self.get_state(interaction.guild_id)

        if preset is not None:
            state.audio_filter.apply_preset(preset.value)
        if bass is not None:
            state.audio_filter.set_bass(bass)
        if treble is not None:
            state.audio_filter.set_treble(treble)

        await interaction.response.send_message(embed=build_eq_embed(state.audio_filter, state.color))

    @app_commands.command(name="eqmenu", description="เปิดเมนู EQ แบบ interactive เลือก/ปรับได้เลย")
    async def eqmenu(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        embed = build_eq_embed(state.audio_filter, state.color)
        view = EQView(self, interaction.guild_id)
        await interaction.response.send_message(embed=embed, view=view)

    # ---------- Theme Commands ----------

    async def _theme_color_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        current_lower = current.lower()
        matches = [name for name in THEME_PRESETS.keys() if current_lower in name.lower()]
        if not matches:
            matches = list(THEME_PRESETS.keys())
        return [app_commands.Choice(name=name, value=name) for name in matches[:25]]

    @app_commands.command(name="settheme", description="ตั้งสีธีม embed ของบอทในเซิร์ฟเวอร์นี้")
    @app_commands.describe(color="เลือกพรีเซ็ต หรือพิมพ์ hex code เอง เช่น #ff8800")
    @app_commands.autocomplete(color=_theme_color_autocomplete)
    async def settheme(self, interaction: discord.Interaction, color: str):
        parsed = parse_color(color)
        if parsed is None:
            await interaction.response.send_message(
                "⛔ ใส่สีไม่ถูกต้องครับ — เลือกจากพรีเซ็ต หรือพิมพ์ hex code เช่น `#ff8800`",
                ephemeral=True,
            )
            return
        state = self.get_state(interaction.guild_id)
        state.color = parsed
        embed = discord.Embed(description="🎨 ตั้งสีธีมใหม่เรียบร้อยแล้วครับ ดูตัวอย่างสีนี้ได้เลย", color=parsed)
        await interaction.response.send_message(embed=embed)

    # ---------- Volume & Voice Control ----------

    @app_commands.command(name="volume", description="ปรับระดับเสียง (0-200)")
    @app_commands.describe(level="ระดับเสียง 0-200 (100 = ปกติ, เกิน 100 = ดังกว่าต้นฉบับ)")
    async def volume(self, interaction: discord.Interaction, level: app_commands.Range[int, 0, 200]):
        state = self.get_state(interaction.guild_id)
        state.volume = level / 100
        if state.voice_client is not None and state.voice_client.source is not None:
            state.voice_client.source.volume = state.volume
        await interaction.response.send_message(f"🔊 ปรับเสียงเป็น {level}% แล้วครับ")

    @app_commands.command(name="leave", description="ออกจากห้องเสียง (ไม่ล้างคิว)")
    async def leave(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        if state.voice_client is None:
            await interaction.response.send_message("⛔ บอทไม่ได้อยู่ในห้องเสียงครับ", ephemeral=True)
            return
        await interaction.response.defer()
        await state.voice_client.disconnect()
        state.voice_client = None
        if state.panel_task and not state.panel_task.done():
            state.panel_task.cancel()
            state.panel_task = None
        await self.update_music_panel(interaction.guild_id)
        await interaction.followup.send("👋 ออกจากห้องเสียงแล้วครับ")

    @app_commands.command(name="ffmpeginfo", description="ดูข้อมูล FFmpeg ที่ติดตั้ง")
    async def ffmpeginfo(self, interaction: discord.Interaction):
        if not FFmpegConfig.check_ffmpeg_available():
            await interaction.response.send_message(
                f"❌ FFmpeg ไม่พบ\nต้องติดตั้ง FFmpeg {FFMPEG_VERSION_REQUIRED}+ ก่อนรันบอท"
            )
            return

        embed = discord.Embed(title="ℹ️ FFmpeg Information", color=self.get_state(interaction.guild_id).color)
        embed.add_field(name="ข้อกำหนด", value=f"`FFmpeg {FFMPEG_VERSION_REQUIRED}+`", inline=False)
        embed.add_field(name="ติดตั้งแล้ว", value=f"`{FFmpegConfig.get_ffmpeg_version()}`", inline=False)
        embed.add_field(name="Path", value=f"`{FFmpegConfig.get_ffmpeg_path()}`", inline=False)
        await interaction.response.send_message(embed=embed)


# ============================================================================
# Setup
# ============================================================================

async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
