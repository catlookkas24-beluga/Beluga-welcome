"""
cogs/music.py — 🎵 Music Player
เล่นเพลงจาก YouTube หรือลิงก์ตรง ๆ ในห้องเสียง มี queue, skip, pause/resume, volume
ใช้ yt-dlp ดึงลิงก์เสียงจริง แล้วสตรีมผ่าน FFmpeg เข้า voice channel

ต้องติดตั้ง ffmpeg บนเครื่อง/เซิร์ฟที่รันบอทด้วย (ไม่ใช่ pip package)
บน Render: เพิ่ม apt package "ffmpeg" ผ่าน Dockerfile หรือ buildpack ที่รองรับ apt
"""

import asyncio
import logging
import os

import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp

log = logging.getLogger("beluga")

# ต้องมี cookies.txt (รูปแบบ Netscape) เพื่อผ่านการเช็ค "Sign in to confirm you're not a bot" ของ YouTube
# หาไฟล์ตามลำดับนี้: Render Secret File ก่อน แล้วค่อย fallback มาที่ root โปรเจกต์
_COOKIE_CANDIDATES = ["/etc/secrets/cookies.txt", "cookies.txt"]
COOKIES_FILE = next((p for p in _COOKIE_CANDIDATES if os.path.isfile(p)), None)

if COOKIES_FILE:
    log.info(f"[music] พบไฟล์ cookies ที่ {COOKIES_FILE} — จะใช้ยืนยันตัวตนกับ YouTube")
else:
    log.warning("[music] ไม่พบไฟล์ cookies.txt — ถ้า YouTube ขึ้น 'Sign in to confirm you're not a bot' ต้องเพิ่มไฟล์นี้")

YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
}
if COOKIES_FILE:
    YTDL_OPTIONS["cookiefile"] = COOKIES_FILE

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)


class Track:
    """เพลงเดี่ยว ๆ ในคิว — เก็บแค่ข้อมูลที่ต้องโชว์ + stream url ที่ยังใช้ได้ตอนนั้น"""

    def __init__(self, title: str, webpage_url: str, stream_url: str, duration: int, requester: discord.Member):
        self.title = title
        self.webpage_url = webpage_url
        self.stream_url = stream_url
        self.duration = duration
        self.requester = requester

    def duration_str(self) -> str:
        if not self.duration:
            return "ไม่ทราบความยาว"
        minutes, seconds = divmod(int(self.duration), 60)
        return f"{minutes}:{seconds:02d}"


class GuildMusicState:
    """สถานะเพลงต่อ 1 เซิร์ฟ — คิว, ตัวที่เล่นอยู่, volume"""

    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        self.queue: list[Track] = []
        self.current: Track | None = None
        self.volume: float = 0.5
        self.voice_client: discord.VoiceClient | None = None


async def extract_track(query: str, requester: discord.Member) -> Track | None:
    """ยิง query (ชื่อเพลง/ลิงก์) ไปหา yt-dlp — บล็อคจึงต้องรันใน executor แยก thread"""
    loop = asyncio.get_event_loop()

    def _extract():
        info = ytdl.extract_info(query, download=False)
        if "entries" in info:  # ผลลัพธ์จากการค้นหา (ytsearch:) จะมาเป็น list
            if not info["entries"]:
                return None
            info = info["entries"][0]
        return info

    info = await loop.run_in_executor(None, _extract)
    if info is None:
        return None

    return Track(
        title=info.get("title", "ไม่ทราบชื่อเพลง"),
        webpage_url=info.get("webpage_url", query),
        stream_url=info["url"],
        duration=info.get("duration", 0),
        requester=requester,
    )


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.states: dict[int, GuildMusicState] = {}

    def get_state(self, guild_id: int) -> GuildMusicState:
        if guild_id not in self.states:
            self.states[guild_id] = GuildMusicState(guild_id)
        return self.states[guild_id]

    # ---------- ตัวเล่นเพลงหลัก ----------

    def _play_next(self, guild_id: int):
        """เรียกจาก callback ของ FFmpegPCMAudio ตอนเพลงจบ (รันอยู่ใน thread อื่น จึงต้อง schedule กลับ event loop)"""
        state = self.states.get(guild_id)
        if state is None:
            return
        coro = self._start_next_track(guild_id)
        asyncio.run_coroutine_threadsafe(coro, self.bot.loop)

    async def _start_next_track(self, guild_id: int):
        state = self.get_state(guild_id)

        if not state.queue:
            state.current = None
            return

        track = state.queue.pop(0)
        state.current = track

        if state.voice_client is None or not state.voice_client.is_connected():
            return

        source = discord.FFmpegPCMAudio(track.stream_url, **FFMPEG_OPTIONS)
        source = discord.PCMVolumeTransformer(source, volume=state.volume)

        def after_playing(error):
            if error:
                log.error(f"เล่นเพลงพลาด (guild {guild_id}): {error}")
            self._play_next(guild_id)

        state.voice_client.play(source, after=after_playing)

    async def _ensure_voice(self, interaction: discord.Interaction) -> discord.VoiceClient | None:
        """เข้าห้องเสียงที่ผู้ใช้อยู่ ถ้ายังไม่เข้า — คืน None ถ้าผู้ใช้ไม่ได้อยู่ในห้องเสียงเลย"""
        member = interaction.user
        if member.voice is None or member.voice.channel is None:
            await interaction.response.send_message(
                "⛔ ต้องเข้าห้องเสียงก่อนถึงจะสั่งเล่นเพลงได้ครับ", ephemeral=True
            )
            return None

        state = self.get_state(interaction.guild_id)
        channel = member.voice.channel

        if state.voice_client is None or not state.voice_client.is_connected():
            state.voice_client = await channel.connect()
        elif state.voice_client.channel != channel:
            await state.voice_client.move_to(channel)

        return state.voice_client

    # ---------- Slash commands ----------

    @app_commands.command(name="play", description="เล่นเพลงจาก YouTube/ลิงก์ (ถ้ามีเล่นอยู่แล้วจะเข้าคิวต่อ)")
    @app_commands.describe(query="ชื่อเพลงที่จะค้นหา หรือลิงก์ YouTube/เพลงตรง ๆ")
    async def play(self, interaction: discord.Interaction, query: str):
        if interaction.guild is None:
            return
        voice_client = await self._ensure_voice(interaction)
        if voice_client is None:
            return

        await interaction.response.defer()

        track = await extract_track(query, interaction.user)
        if track is None:
            await interaction.followup.send("⛔ หาเพลงนี้ไม่เจอครับ ลองคำอื่นหรือลิงก์อื่นดูนะ")
            return

        state = self.get_state(interaction.guild_id)
        state.queue.append(track)

        if voice_client.is_playing() or voice_client.is_paused():
            await interaction.followup.send(
                f"➕ เข้าคิวแล้ว: **{track.title}** ({track.duration_str()}) — อันดับที่ {len(state.queue)}"
            )
        else:
            await interaction.followup.send(f"▶️ กำลังเล่น: **{track.title}** ({track.duration_str()})")
            await self._start_next_track(interaction.guild_id)

    @app_commands.command(name="skip", description="ข้ามเพลงที่กำลังเล่นอยู่ ไปเพลงต่อไปในคิว")
    async def skip(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        if state.voice_client is None or not (state.voice_client.is_playing() or state.voice_client.is_paused()):
            await interaction.response.send_message("⛔ ไม่มีเพลงกำลังเล่นอยู่ครับ", ephemeral=True)
            return
        state.voice_client.stop()  # การ stop() จะไป trigger after_playing ให้เล่นเพลงต่อไปเอง
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

    @app_commands.command(name="stop", description="หยุดเพลง ล้างคิวทั้งหมด แล้วออกจากห้องเสียง")
    async def stop(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        state.queue.clear()
        state.current = None
        if state.voice_client is not None:
            await state.voice_client.disconnect()
            state.voice_client = None
        await interaction.response.send_message("⏹️ หยุดเพลงและออกจากห้องเสียงแล้วครับ")

    @app_commands.command(name="queue", description="ดูคิวเพลงที่รออยู่")
    async def show_queue(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)

        embed = discord.Embed(title="🎵 คิวเพลง", color=discord.Color.blurple())

        if state.current:
            embed.add_field(
                name="กำลังเล่น",
                value=f"**{state.current.title}** ({state.current.duration_str()}) — ขอโดย {state.current.requester.mention}",
                inline=False,
            )
        else:
            embed.add_field(name="กำลังเล่น", value="ไม่มีเพลงเล่นอยู่", inline=False)

        if state.queue:
            lines = [
                f"{i+1}. **{t.title}** ({t.duration_str()}) — ขอโดย {t.requester.mention}"
                for i, t in enumerate(state.queue[:10])
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
        await interaction.response.send_message(
            f"🎶 กำลังเล่น: **{state.current.title}** ({state.current.duration_str()}) "
            f"— ขอโดย {state.current.requester.mention}\n{state.current.webpage_url}"
        )

    @app_commands.command(name="volume", description="ปรับระดับเสียง (0-100)")
    @app_commands.describe(level="ระดับเสียง 0-100")
    async def volume(self, interaction: discord.Interaction, level: app_commands.Range[int, 0, 100]):
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
        await state.voice_client.disconnect()
        state.voice_client = None
        await interaction.response.send_message("👋 ออกจากห้องเสียงแล้วครับ")


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
