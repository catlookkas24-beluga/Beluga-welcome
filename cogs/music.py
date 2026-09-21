"""
cogs/music.py — 🎵 Music Player (คลังเพลงจากลิงก์ไฟล์เสียงตรง)

หลังจากลองใช้ yt-dlp และ Lavalink ดึงเสียงจาก YouTube มาทั้งวันแล้วเจอปัญหา
YouTube บล็อกบอท/IP ของ cloud server อยู่เรื่อย ๆ จนแก้ไม่จบ — ระบบนี้เลือกเล่นจาก
"ลิงก์ไฟล์เสียงตรง" (mp3/wav ที่อัปโหลดไว้ที่อื่นแล้ว) แทน ไม่ผ่าน YouTube เลย
จึงไม่มีทางโดนบล็อกแบบเดียวกัน เก็บชื่อ+ลิงก์ไว้ใน MongoDB ผ่าน db.py

ขั้นตอนใช้งาน:
  1. แปลงเพลงเป็น mp3 ด้วยแอปที่คุณมีอยู่แล้ว
  2. อัปโหลดไฟล์ไปที่ไหนก็ได้ที่ให้ "ลิงก์ตรง" ถึงไฟล์ (เช่น อัปโหลดใส่ channel ใน Discord
     เอง แล้วคลิกขวาที่ไฟล์ > Copy Link)
  3. ใช้ /addsong ชื่อเพลง ลิงก์ เพื่อเก็บเข้าคลัง
  4. /play ชื่อเพลง เพื่อเล่น (หรือ /play ลิงก์ ถ้าอยากเล่นแบบไม่บันทึกไว้ก่อนก็ได้)

ต้องมี ffmpeg บนเครื่อง/เซิร์ฟที่รันบอทด้วย (ไม่ใช่ pip package)

หมายเหตุ: Lavalink server ที่เคยตั้งไว้ (service beluga-lavalink) ยังไม่ได้ลบทิ้ง
เผื่ออนาคตอยากกลับมาลองใหม่ (เช่น ผ่าน proxy IP อื่น) — แค่ตอนนี้บอทไม่ได้เรียกใช้แล้ว
"""

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

import db

log = logging.getLogger("beluga")

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}


class QueueItem:
    __slots__ = ("title", "url", "requester")

    def __init__(self, title: str, url: str, requester: discord.Member):
        self.title = title
        self.url = url
        self.requester = requester


class GuildMusicState:
    def __init__(self):
        self.queue: list[QueueItem] = []
        self.current: QueueItem | None = None
        self.volume: float = 0.5
        self.voice_client: discord.VoiceClient | None = None
        self.text_channel: discord.abc.Messageable | None = None


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.states: dict[int, GuildMusicState] = {}

    def get_state(self, guild_id: int) -> GuildMusicState:
        if guild_id not in self.states:
            self.states[guild_id] = GuildMusicState()
        return self.states[guild_id]

    # ---------- ตัวเล่นเพลงหลัก ----------

    def _play_next(self, guild_id: int):
        """เรียกจาก callback ของ FFmpegPCMAudio ตอนเพลงจบ (รันอยู่ใน thread อื่น จึงต้อง schedule กลับ event loop)"""
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

        source = discord.FFmpegPCMAudio(item.url, **FFMPEG_OPTIONS)
        source = discord.PCMVolumeTransformer(source, volume=state.volume)

        def after_playing(error):
            if error:
                log.error(f"[music] เล่นเพลงพลาด (guild {guild_id}): {error}")
            self._play_next(guild_id)

        state.voice_client.play(source, after=after_playing)
        if state.text_channel is not None:
            await state.text_channel.send(f"▶️ กำลังเล่น: **{item.title}**")

    async def _ensure_voice(self, interaction: discord.Interaction) -> discord.VoiceClient | None:
        """ต้องเรียกหลัง defer() เสมอ — ใช้ followup.send สำหรับ error ทุกกรณี ไม่ใช่ response.send_message"""
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

    # ---------- Slash commands: คลังเพลง ----------

    @app_commands.command(name="addsong", description="เพิ่มเพลงเข้าคลัง (ต้องเป็นลิงก์ไฟล์เสียงตรง เช่น .mp3)")
    @app_commands.describe(name="ชื่อเพลงที่จะใช้เรียก", url="ลิงก์ไฟล์เสียงตรง (mp3/wav)")
    async def addsong(self, interaction: discord.Interaction, name: str, url: str):
        if not url.startswith(("http://", "https://")):
            await interaction.response.send_message("⛔ ลิงก์ต้องขึ้นต้นด้วย http:// หรือ https:// ครับ", ephemeral=True)
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

    # ---------- Slash commands: เล่นเพลง ----------

    @app_commands.command(name="play", description="เล่นเพลงจากคลัง (ใส่ชื่อ) หรือลิงก์ไฟล์เสียงตรง")
    @app_commands.describe(query="ชื่อเพลงในคลัง หรือลิงก์ไฟล์เสียงตรง")
    async def play(self, interaction: discord.Interaction, query: str):
        if interaction.guild is None:
            return

        await interaction.response.defer()  # มาก่อนทุกอย่าง กันเชื่อมต่อห้องเสียงช้าจน interaction หมดอายุ

        voice_client = await self._ensure_voice(interaction)
        if voice_client is None:
            return

        if query.startswith(("http://", "https://")):
            title, url = query, query
        else:
            song = await db.get_song(interaction.guild_id, query)
            if song is None:
                await interaction.followup.send(
                    "⛔ ไม่เจอเพลงนี้ในคลังครับ ลองเช็คชื่อด้วย `/songlist` หรือเพิ่มก่อนด้วย `/addsong`"
                )
                return
            title, url = song["name"], song["url"]

        state = self.get_state(interaction.guild_id)
        state.queue.append(QueueItem(title, url, interaction.user))

        if voice_client.is_playing() or voice_client.is_paused():
            await interaction.followup.send(f"➕ เข้าคิวแล้ว: **{title}** — อันดับที่ {len(state.queue)}")
        else:
            await interaction.followup.send(f"▶️ กำลังเล่น: **{title}**")
            await self._start_next_track(interaction.guild_id)

    @app_commands.command(name="skip", description="ข้ามเพลงที่กำลังเล่นอยู่ ไปเพลงต่อไปในคิว")
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

    @app_commands.command(name="stop", description="หยุดเพลง ล้างคิวทั้งหมด แล้วออกจากห้องเสียง")
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
        await interaction.response.defer()
        await state.voice_client.disconnect()
        state.voice_client = None
        await interaction.followup.send("👋 ออกจากห้องเสียงแล้วครับ")


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
