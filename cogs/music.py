"""
cogs/music.py — 🎵 Music Player (คลังเพลงจากลิงก์ไฟล์เสียงตรง)

หลังจากลองใช้ yt-dlp และ Lavalink ดึงเสียงจาก YouTube มาทั้งวันแล้วเจอปัญหา
YouTube บล็อกบอท/IP ของ cloud server อยู่เรื่อย ๆ จนแก้ไม่จบ — ระบบนี้เลือกเล่นจาก
"ลิงก์ไฟล์เสียงตรง" (mp3/wav ที่อัปโหลดไว้ที่อื่นแล้ว) แทน ไม่ผ่าน YouTube เลย
จึงไม่มีทางโดนบล็อกแบบเดียวกัน เก็บชื่อ+ลิงก์ไว้ใน MongoDB ผ่าน db.py

⚙️ ข้อกำหนด:
  • FFmpeg 9.0.2+ บนเครื่อง/เซิร์ฟที่รันบอท (ไม่ใช่ pip package)
  • discord.py พร้อมจากปืน voice support

ขั้นตอนใช้งาน:
  1. แปลงเพลงเป็น mp3 ด้วยแอปที่คุณมีอยู่แล้ว
  2. อัปโหลดไฟล์ไปที่ไหนก็ได้ที่ให้ "ลิงก์ตรง" ถึงไฟล์ (เช่น อัปโหลดใส่ channel ใน Discord
     เอง แล้วคลิกขวาที่ไฟล์ > Copy Link)
  3. ใช้ /addsong ชื่อเพลง ลิงก์ เพื่อเก็บเข้าคลัง
  4. /play ชื่อเพลง เพื่อเล่น (หรือ /play ลิงก์ ถ้าอยากเล่นแบบไม่บันทึกไว้ก่อนก็ได้)

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
        """หา path ของ ffmpeg — คืน None ถ้าไม่เจอ"""
        return shutil.which("ffmpeg")
    
    @staticmethod
    def check_ffmpeg_available() -> bool:
        """เช็ก ffmpeg ติดตั้งอยู่หรือไม่"""
        return FFmpegConfig.get_ffmpeg_path() is not None
    
    @staticmethod
    def get_ffmpeg_version() -> Optional[str]:
        """ดึง version ของ ffmpeg ที่ติดตั้ง"""
        try:
            result = subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                first_line = result.stdout.split("\n")[0]
                return first_line
            return None
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None


# ============================================================================
# 🎵 Queue Items & Guild Music State
# ============================================================================

class QueueItem:
    """รายการเพลงในคิว"""
    __slots__ = ("title", "url", "requester", "added_at")

    def __init__(self, title: str, url: str, requester: discord.Member):
        self.title = title
        self.url = url
        self.requester = requester
        self.added_at = asyncio.get_event_loop().time()


class AudioFilter:
    """จัดการ audio filter (bass + treble)"""
    
    def __init__(self, bass: int = 0, treble: int = 0):
        self.bass = bass
        self.treble = treble
    
    def to_filter_string(self) -> Optional[str]:
        """สร้าง FFmpeg audio filter string — คืน None ถ้าไม่มี filter"""
        if self.bass == 0 and self.treble == 0:
            return None
        return f"bass=g={self.bass},treble=g={self.treble}"
    
    def is_active(self) -> bool:
        """เช็ก filter มีการเปิดใช้งานหรือไม่"""
        return self.bass != 0 or self.treble != 0


class GuildMusicState:
    """สถานะการเล่นเพลงของแต่ละ guild"""
    
    def __init__(self):
        self.queue: list[QueueItem] = []
        self.current: Optional[QueueItem] = None
        self.volume: float = 0.5
        self.audio_filter = AudioFilter(bass=0, treble=0)
        self.voice_client: Optional[discord.VoiceClient] = None
        self.text_channel: Optional[discord.abc.Messageable] = None
        self.is_paused: bool = False

    def build_ffmpeg_options(self) -> dict:
        """สร้าง FFmpeg options ตามค่า EQ ปัจจุบัน"""
        before_options_parts = []
        
        # เพิ่ม reconnection options
        for key, val in FFMPEG_OPTIONS.items():
            before_options_parts.append(f"-{key} {val}")
        
        before_options = " ".join(before_options_parts)
        
        options = "-vn"
        filter_str = self.audio_filter.to_filter_string()
        
        if filter_str:
            options += f' -af "{filter_str}"'
        
        return {
            "before_options": before_options,
            "options": options
        }


# ============================================================================
# 🎶 Music Cog — Main Controller
# ============================================================================

class Music(commands.Cog):
    """Music player cog ที่ใช้ FFmpeg 9.0.2+ สำหรับเล่นไฟล์เสียงตรง"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.states: dict[int, GuildMusicState] = {}
        self._check_ffmpeg_on_startup()

    def _check_ffmpeg_on_startup(self):
        """เช็ก ffmpeg ติดตั้งอยู่หรือไม่ตอนเซิร์ฟเวอร์เริ่ม"""
        if not FFmpegConfig.check_ffmpeg_available():
            log.error(
                f"❌ FFmpeg ไม่พบบนระบบ — Music cog จะไม่ทำงาน "
                f"ติดตั้ง FFmpeg {FFMPEG_VERSION_REQUIRED}+ ก่อนรันบอท"
            )
        else:
            version_info = FFmpegConfig.get_ffmpeg_version()
            log.info(f"✅ FFmpeg พบ: {version_info}")

    def get_state(self, guild_id: int) -> GuildMusicState:
        """ดึง state ของ guild — สร้างใหม่ถ้ายังไม่มี"""
        if guild_id not in self.states:
            self.states[guild_id] = GuildMusicState()
        return self.states[guild_id]

    # ---------- Playback Management ----------

    def _play_next(self, guild_id: int):
        """เรียกจาก callback ของ FFmpegPCMAudio ตอนเพลงจบ"""
        state = self.states.get(guild_id)
        if state is None:
            return
        asyncio.run_coroutine_threadsafe(
            self._start_next_track(guild_id), 
            self.bot.loop
        )

    async def _start_next_track(self, guild_id: int):
        """เริ่มเล่นเพลงถัดไปจากคิว"""
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
                await state.text_channel.send(
                    "❌ FFmpeg ไม่พบ — ไม่สามารถเล่นเพลงได้"
                )
            return

        try:
            ffmpeg_options = state.build_ffmpeg_options()
            source = discord.FFmpegPCMAudio(item.url, **ffmpeg_options)
            source = discord.PCMVolumeTransformer(source, volume=state.volume)

            def after_playing(error):
                if error:
                    log.error(f"[music] เล่นเพลงพลาด (guild {guild_id}): {error}")
                self._play_next(guild_id)

            state.voice_client.play(source, after=after_playing)
            if state.text_channel is not None:
                await state.text_channel.send(
                    f"▶️ กำลังเล่น: **{item.title}** — ขอโดย {item.requester.mention}"
                )
        except Exception as e:
            log.error(f"[music] เกิด error ขณะเล่น: {e}")
            if state.text_channel:
                await state.text_channel.send(f"❌ เกิด error: {e}")

    async def _ensure_voice(self, interaction: discord.Interaction) -> Optional[discord.VoiceClient]:
        """ต้อง defer() ก่อน — ใช้ followup.send ทุกกรณี"""
        member = interaction.user
        if member.voice is None or member.voice.channel is None:
            await interaction.followup.send(
                "⛔ ต้องเข้าห้องเสียงก่อนถึงจะสั่งเล่นเพลงได้ครับ"
            )
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
        url="ลิงก์ไฟล์เสียงตรง (mp3/wav/etc)"
    )
    async def addsong(self, interaction: discord.Interaction, name: str, url: str):
        if not url.startswith(("http://", "https://")):
            await interaction.response.send_message(
                "⛔ ลิงก์ต้องขึ้นต้นด้วย http:// หรือ https:// ครับ",
                ephemeral=True
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
            await interaction.response.send_message(
                "⛔ ไม่เจอเพลงชื่อนี้ในคลังครับ",
                ephemeral=True
            )

    @app_commands.command(name="songlist", description="ดูรายชื่อเพลงทั้งหมดในคลัง")
    async def songlist(self, interaction: discord.Interaction):
        songs = await db.list_songs(interaction.guild_id)
        if not songs:
            await interaction.response.send_message(
                "คลังเพลงยังว่างอยู่ครับ ลองเพิ่มด้วย `/addsong` ก่อน"
            )
            return
        lines = [f"• {s['name']}" for s in songs[:30]]
        if len(songs) > 30:
            lines.append(f"...และอีก {len(songs) - 30} เพลง")
        embed = discord.Embed(
            title="🎵 คลังเพลง",
            description="\n".join(lines),
            color=discord.Color.blurple()
        )
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
                await interaction.followup.send(
                    "⛔ ไม่เจอเพลงนี้ในคลังครับ ลองเช็คชื่อด้วย `/songlist`"
                )
                return
            title, url = song["name"], song["url"]

        state = self.get_state(interaction.guild_id)
        state.queue.append(QueueItem(title, url, interaction.user))

        if voice_client.is_playing() or voice_client.is_paused():
            await interaction.followup.send(
                f"➕ เข้าคิวแล้ว: **{title}** — อันดับที่ {len(state.queue)}"
            )
        else:
            await interaction.followup.send(f"▶️ กำลังเล่น: **{title}**")
            await self._start_next_track(interaction.guild_id)

    @app_commands.command(name="skip", description="ข้ามเพลงไปเพลงต่อไปในคิว")
    async def skip(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        if state.voice_client is None or not (
            state.voice_client.is_playing() or state.voice_client.is_paused()
        ):
            await interaction.response.send_message(
                "⛔ ไม่มีเพลงกำลังเล่นอยู่ครับ",
                ephemeral=True
            )
            return
        state.voice_client.stop()
        await interaction.response.send_message("⏭️ ข้ามเพลงแล้วครับ")

    @app_commands.command(name="pause", description="พักเพลงที่กำลังเล่นไว้ชั่วคราว")
    async def pause(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        if state.voice_client is None or not state.voice_client.is_playing():
            await interaction.response.send_message(
                "⛔ ไม่มีเพลงกำลังเล่นอยู่ครับ",
                ephemeral=True
            )
            return
        state.voice_client.pause()
        state.is_paused = True
        await interaction.response.send_message("⏸️ พักเพลงไว้แล้วครับ")

    @app_commands.command(name="resume", description="เล่นเพลงที่พักไว้ต่อ")
    async def resume(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        if state.voice_client is None or not state.voice_client.is_paused():
            await interaction.response.send_message(
                "⛔ ไม่มีเพลงที่พักไว้ครับ",
                ephemeral=True
            )
            return
        state.voice_client.resume()
        state.is_paused = False
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
            await interaction.response.send_message(
                "⛔ ไม่มีเพลงเล่นอยู่ครับ",
                ephemeral=True
            )
            return
        await interaction.response.send_message(f"🎶 กำลังเล่น: **{state.current.title}**")

    # ---------- Audio Control & Settings ----------

    @app_commands.command(name="eq", description="ปรับ EQ เบส/แหลม (มีผลเพลงถัดไป)")
    @app_commands.describe(
        bass="ระดับเบส -10 ถึง 20 (ค่าเริ่มต้น 0 = ปิด)",
        treble="ระดับแหลม -10 ถึง 20 (ค่าเริ่มต้น 0)"
    )
    async def eq(
        self,
        interaction: discord.Interaction,
        bass: Optional[app_commands.Range[int, -10, 20]] = None,
        treble: Optional[app_commands.Range[int, -10, 20]] = None,
    ):
        state = self.get_state(interaction.guild_id)
        if bass is not None:
            state.audio_filter.bass = bass
        if treble is not None:
            state.audio_filter.treble = treble
        
        await interaction.response.send_message(
            f"🎚️ ตั้งค่า EQ แล้วครับ — เบส: **{state.audio_filter.bass}**, แหลม: **{state.audio_filter.treble}**\n"
            f"(มีผลตั้งแต่เพลงถัดไป ใช้ `/skip` เพื่อให้มีผลทันที)"
        )

    @app_commands.command(name="volume", description="ปรับระดับเสียง (0-200)")
    @app_commands.describe(
        level="ระดับเสียง 0-200 (100 = ปกติ, เกิน 100 = ดังกว่าต้นฉบับ)"
    )
    async def volume(
        self, 
        interaction: discord.Interaction, 
        level: app_commands.Range[int, 0, 200]
    ):
        state = self.get_state(interaction.guild_id)
        state.volume = level / 100
        if state.voice_client is not None and state.voice_client.source is not None:
            state.voice_client.source.volume = state.volume
        await interaction.response.send_message(f"🔊 ปรับเสียงเป็น {level}% แล้วครับ")

    @app_commands.command(name="leave", description="ออกจากห้องเสียง (ไม่ล้างคิว)")
    async def leave(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        if state.voice_client is None:
            await interaction.response.send_message(
                "⛔ บอทไม่ได้อยู่ในห้องเสียงครับ",
                ephemeral=True
            )
            return
        await interaction.response.defer()
        await state.voice_client.disconnect()
        state.voice_client = None
        await interaction.followup.send("👋 ออกจากห้องเสียงแล้วครับ")

    @app_commands.command(name="ffmpeginfo", description="ดูข้อมูล FFmpeg ที่ติดตั้ง")
    async def ffmpeginfo(self, interaction: discord.Interaction):
        """ตรวจสอบ FFmpeg version ที่ติดตั้ง"""
        if not FFmpegConfig.check_ffmpeg_available():
            await interaction.response.send_message(
                f"❌ FFmpeg ไม่พบ\n"
                f"ต้องติดตั้ง FFmpeg {FFMPEG_VERSION_REQUIRED}+ ก่อนรันบอท"
            )
            return
        
        version_info = FFmpegConfig.get_ffmpeg_version()
        ffmpeg_path = FFmpegConfig.get_ffmpeg_path()
        
        embed = discord.Embed(
            title="ℹ️ FFmpeg Information",
            color=discord.Color.green()
        )
        embed.add_field(name="ข้อกำหนด", value=f"`FFmpeg {FFMPEG_VERSION_REQUIRED}+`", inline=False)
        embed.add_field(name="ติดตั้งแล้ว", value=f"`{version_info}`", inline=False)
        embed.add_field(name="Path", value=f"`{ffmpeg_path}`", inline=False)
        
        await interaction.response.send_message(embed=embed)


# ============================================================================
# Setup
# ============================================================================

async def setup(bot: commands.Bot):
    """โหลด Music cog เข้าบอท"""
    await bot.add_cog(Music(bot))
