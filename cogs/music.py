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
import subprocess
import shutil
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
FFMPEG_OPTIONS = {
    "reconnect": 1,
    "reconnect_streamed": 1,
    "reconnect_delay_max": 5,
    "http_persistent": 1,
}


class FFmpegConfig:
    """จัดการการตั้งค่า FFmpeg version และ options"""

    @staticmethod
    def get_ffmpeg_path() -> Optional[str]:
        return shutil.which("ffmpeg")

    @staticmethod
    def check_ffmpeg_available() -> bool:
        return FFmpegConfig.get_ffmpeg_path() is not None

    @staticmethod
    def get_ffmpeg_version() -> Optional[str]:
        try:
            result = subprocess.run(
                ["ffmpeg", "-version"], capture_output=True, text=True, timeout=5
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


def make_bar(value: int, min_val: int = -10, max_val: int = 20, length: int = 10) -> str:
    """สร้างแถบ progress bar แบบ unicode สำหรับโชว์ค่า bass/treble"""
    ratio = (value - min_val) / (max_val - min_val)
    filled = max(0, min(length, round(ratio * length)))
    return "█" * filled + "░" * (length - filled)


# ============================================================================
# 🎵 Queue Items & Audio Filter
# ============================================================================

class QueueItem:
    __slots__ = ("title", "url", "requester")

    def __init__(self, title: str, url: str, requester: discord.Member):
        self.title = title
        self.url = url
        self.requester = requester


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
        self.current: Optional[QueueItem] = None
        self.volume: float = 0.5
        self.audio_filter = AudioFilter()
        self.voice_client: Optional[discord.VoiceClient] = None
        self.text_channel: Optional[discord.abc.Messageable] = None

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

def build_eq_embed(audio_filter: AudioFilter) -> discord.Embed:
    """สร้าง embed สวยๆ โชว์สถานะ EQ ปัจจุบัน"""
    preset_data = EQ_PRESETS[audio_filter.preset]

    embed = discord.Embed(
        title="🎚️ Equalizer",
        description=f"{preset_data['emoji']} **{preset_data['label']}**\n{preset_data['desc']}",
        color=discord.Color.from_rgb(114, 137, 218),
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
        embed = build_eq_embed(state.audio_filter)
        await interaction.response.edit_message(embed=embed, view=self.view)


class EQResetButton(discord.ui.Button):
    def __init__(self, music_cog: "Music", guild_id: int):
        super().__init__(label="รีเซ็ตเป็นค่าเริ่มต้น", style=discord.ButtonStyle.secondary, emoji="🔄")
        self.music_cog = music_cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        state = self.music_cog.get_state(self.guild_id)
        state.audio_filter.apply_preset(DEFAULT_PRESET)
        embed = build_eq_embed(state.audio_filter)
        await interaction.response.edit_message(embed=embed, view=self.view)


class EQBassDownButton(discord.ui.Button):
    def __init__(self, music_cog: "Music", guild_id: int):
        super().__init__(label="เบส -", style=discord.ButtonStyle.primary, emoji="🔉", row=1)
        self.music_cog = music_cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        state = self.music_cog.get_state(self.guild_id)
        state.audio_filter.set_bass(max(-10, state.audio_filter.bass - 2))
        await interaction.response.edit_message(embed=build_eq_embed(state.audio_filter), view=self.view)


class EQBassUpButton(discord.ui.Button):
    def __init__(self, music_cog: "Music", guild_id: int):
        super().__init__(label="เบส +", style=discord.ButtonStyle.primary, emoji="🔊", row=1)
        self.music_cog = music_cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        state = self.music_cog.get_state(self.guild_id)
        state.audio_filter.set_bass(min(20, state.audio_filter.bass + 2))
        await interaction.response.edit_message(embed=build_eq_embed(state.audio_filter), view=self.view)


class EQTrebleDownButton(discord.ui.Button):
    def __init__(self, music_cog: "Music", guild_id: int):
        super().__init__(label="แหลม -", style=discord.ButtonStyle.success, emoji="🔅", row=1)
        self.music_cog = music_cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        state = self.music_cog.get_state(self.guild_id)
        state.audio_filter.set_treble(max(-10, state.audio_filter.treble - 2))
        await interaction.response.edit_message(embed=build_eq_embed(state.audio_filter), view=self.view)


class EQTrebleUpButton(discord.ui.Button):
    def __init__(self, music_cog: "Music", guild_id: int):
        super().__init__(label="แหลม +", style=discord.ButtonStyle.success, emoji="🔆", row=1)
        self.music_cog = music_cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        state = self.music_cog.get_state(self.guild_id)
        state.audio_filter.set_treble(min(20, state.audio_filter.treble + 2))
        await interaction.response.edit_message(embed=build_eq_embed(state.audio_filter), view=self.view)


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
            return

        item = state.queue.pop(0)
        state.current = item

        if state.voice_client is None or not state.voice_client.is_connected():
            return

        if not FFmpegConfig.check_ffmpeg_available():
            if state.text_channel:
                await state.text_channel.send("❌ FFmpeg ไม่พบ — ไม่สามารถเล่นเพลงได้")
            return

        try:
            source = discord.FFmpegPCMAudio(item.url, **state.build_ffmpeg_options())
            source = discord.PCMVolumeTransformer(source, volume=state.volume)

            def after_playing(error):
                if error:
                    log.error(f"[music] เล่นเพลงพลาด (guild {guild_id}): {error}")
                self._play_next(guild_id)

            state.voice_client.play(source, after=after_playing)
            if state.text_channel is not None:
                preset_data = EQ_PRESETS[state.audio_filter.preset]
                await state.text_channel.send(
                    f"▶️ กำลังเล่น: **{item.title}** — ขอโดย {item.requester.mention}\n"
                    f"-# {preset_data['emoji']} EQ: {preset_data['label']}"
                )
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
    @app_commands.describe(name="ชื่อเพลงที่จะใช้เรียก", url="ลิงก์ไฟล์เสียงตรง (mp3/wav/etc)")
    async def addsong(self, interaction: discord.Interaction, name: str, url: str):
        if not url.startswith(("http://", "https://")):
            await interaction.response.send_message(
                "⛔ ลิงก์ต้องขึ้นต้นด้วย http:// หรือ https:// ครับ", ephemeral=True
            )
            return
        await db.add_song(interaction.guild_id, name, url, interaction.user.id)
        await interaction.response.send_message(f"✅ เพิ่ม **{name}** เข้าคลังเพลงแล้วครับ")

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
        embed = discord.Embed(title="🎵 คลังเพลง", description="\n".join(lines), color=discord.Color.blurple())
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
            title, url = query, query
        else:
            song = await db.get_song(interaction.guild_id, query)
            if song is None:
                await interaction.followup.send("⛔ ไม่เจอเพลงนี้ในคลังครับ ลองเช็คชื่อด้วย `/songlist`")
                return
            title, url = song["name"], song["url"]

        state = self.get_state(interaction.guild_id)
        state.queue.append(QueueItem(title, url, interaction.user))

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
        await interaction.response.send_message("⏸️ พักเพลงไว้แล้วครับ")

    @app_commands.command(name="resume", description="เล่นเพลงที่พักไว้ต่อ")
    async def resume(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        if state.voice_client is None or not state.voice_client.is_paused():
            await interaction.response.send_message("⛔ ไม่มีเพลงที่พักไว้ครับ", ephemeral=True)
            return
        state.voice_client.resume()
        await interaction.response.send_message("▶️ เล่นต่อแล้วครับ")

    @app_commands.command(name="stop", description="หยุดเพลง ล้างคิว แล้วออกจากห้องเสียง")
    async def stop(self, interaction: discord.Interaction):
        await interaction.response.defer()
        state = self.get_state(interaction.guild_id)
        state.queue.clear()
        state.current = None
        if state.voice_client is not None:
            await state.voice_client.disconnect()
            state.voice_client = None
        await interaction.followup.send("⏹️ หยุดเพลงและออกจากห้องเสียงแล้วครับ")

    @app_commands.command(name="queue", description="ดูคิวเพลงที่รออยู่")
    async def show_queue(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        embed = discord.Embed(title="🎵 คิวเพลง", color=discord.Color.blurple())

        if state.current:
            embed.add_field(
                name="กำลังเล่น",
                value=f"**{state.current.title}** — ขอโดย {state.current.requester.mention}",
                inline=False,
            )
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
            await interaction.response.send_message("⛔ ไม่มีเพลงเล่นอยู่ครับ", ephemeral=True)
            return
        await interaction.response.send_message(f"🎶 กำลังเล่น: **{state.current.title}**")

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

        await interaction.response.send_message(embed=build_eq_embed(state.audio_filter))

    @app_commands.command(name="eqmenu", description="เปิดเมนู EQ แบบ interactive เลือก/ปรับได้เลย")
    async def eqmenu(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        embed = build_eq_embed(state.audio_filter)
        view = EQView(self, interaction.guild_id)
        await interaction.response.send_message(embed=embed, view=view)

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
        await interaction.followup.send("👋 ออกจากห้องเสียงแล้วครับ")

    @app_commands.command(name="ffmpeginfo", description="ดูข้อมูล FFmpeg ที่ติดตั้ง")
    async def ffmpeginfo(self, interaction: discord.Interaction):
        if not FFmpegConfig.check_ffmpeg_available():
            await interaction.response.send_message(
                f"❌ FFmpeg ไม่พบ\nต้องติดตั้ง FFmpeg {FFMPEG_VERSION_REQUIRED}+ ก่อนรันบอท"
            )
            return

        embed = discord.Embed(title="ℹ️ FFmpeg Information", color=discord.Color.green())
        embed.add_field(name="ข้อกำหนด", value=f"`FFmpeg {FFMPEG_VERSION_REQUIRED}+`", inline=False)
        embed.add_field(name="ติดตั้งแล้ว", value=f"`{FFmpegConfig.get_ffmpeg_version()}`", inline=False)
        embed.add_field(name="Path", value=f"`{FFmpegConfig.get_ffmpeg_path()}`", inline=False)
        await interaction.response.send_message(embed=embed)


# ============================================================================
# Setup
# ============================================================================

async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
