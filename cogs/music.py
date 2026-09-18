"""
cogs/music.py — 🎵 Music Player (Lavalink ผ่าน Mafic)

เล่นเพลงจาก YouTube/ลิงก์ผ่าน Lavalink server แยกต่างหาก แทนที่จะดึงเสียงเองด้วย yt-dlp
ต้องมี Lavalink server แยกต่างหาก (self-host หรือใช้ public node ก็ได้) ตั้งค่าผ่าน:
    LAVALINK_HOST      — โฮสต์ของ Lavalink node (จำเป็น)
    LAVALINK_PORT      — พอร์ต (จำเป็น)
    LAVALINK_PASSWORD  — รหัสผ่านของ node (จำเป็น)
    LAVALINK_SECURE    — "true"/"false" ใช้ SSL หรือไม่ (ค่าเริ่มต้น: false)
ถ้าไม่ตั้งค่าไว้ คำสั่งเพลงจะขึ้น error แจ้งให้ตั้งค่าก่อนใช้งาน
"""

import logging
import os

import discord
import mafic
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("beluga")

LAVALINK_HOST = os.getenv("LAVALINK_HOST")
LAVALINK_PORT = os.getenv("LAVALINK_PORT")
LAVALINK_PASSWORD = os.getenv("LAVALINK_PASSWORD")
LAVALINK_SECURE = os.getenv("LAVALINK_SECURE", "false").lower() == "true"


class QueueItem:
    """เพลง 1 รายการในคิว พร้อมข้อมูลคนขอ (mafic.Track เก็บ custom data ไม่สะดวก จึงห่อเองอีกชั้น)"""

    __slots__ = ("track", "requester")

    def __init__(self, track: mafic.Track, requester: discord.Member):
        self.track = track
        self.requester = requester

    def duration_str(self) -> str:
        ms = self.track.length or 0
        minutes, seconds = divmod(int(ms / 1000), 60)
        return f"{minutes}:{seconds:02d}"


class MusicPlayer(mafic.Player):
    """Player ต่อ 1 ห้องเสียง — เก็บคิวของเราเองไว้ข้างใน (mafic ไม่มีระบบคิวในตัว)"""

    def __init__(self, client: commands.Bot, channel: discord.VoiceChannel):
        super().__init__(client, channel)
        self.queue: list[QueueItem] = []
        self.text_channel: discord.abc.Messageable | None = None


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pool: mafic.NodePool = mafic.NodePool(bot)
        self.node_ready = False

    async def cog_load(self):
        if not (LAVALINK_HOST and LAVALINK_PORT and LAVALINK_PASSWORD):
            log.warning(
                "[music] ยังไม่ได้ตั้งค่า LAVALINK_HOST/LAVALINK_PORT/LAVALINK_PASSWORD "
                "— คำสั่งเพลงจะใช้งานไม่ได้จนกว่าจะตั้งค่า"
            )
            return
        try:
            await self.pool.create_node(
                host=LAVALINK_HOST,
                port=int(LAVALINK_PORT),
                label="MAIN",
                password=LAVALINK_PASSWORD,
                secure=LAVALINK_SECURE,
            )
            self.node_ready = True
            log.info(f"[music] เชื่อมต่อ Lavalink node สำเร็จ ({LAVALINK_HOST}:{LAVALINK_PORT})")
        except Exception as error:
            log.error(f"[music] เชื่อมต่อ Lavalink node ไม่สำเร็จ: {error}")

    # ---------- ตัวเล่นเพลงหลัก ----------

    async def _ensure_voice(self, interaction: discord.Interaction) -> MusicPlayer | None:
        if not self.node_ready:
            await interaction.response.send_message(
                "⛔ ระบบเพลงยังไม่พร้อมใช้งานครับ (ยังไม่ได้เชื่อมต่อ Lavalink server — เช็ค "
                "LAVALINK_HOST/PORT/PASSWORD ใน Render ก่อน แล้วดู log ตอนบอทเริ่มทำงานว่าเชื่อมต่อสำเร็จไหม)",
                ephemeral=True,
            )
            return None

        member = interaction.user
        if member.voice is None or member.voice.channel is None:
            await interaction.response.send_message(
                "⛔ ต้องเข้าห้องเสียงก่อนถึงจะสั่งเล่นเพลงได้ครับ", ephemeral=True
            )
            return None

        channel = member.voice.channel
        player = interaction.guild.voice_client

        if player is None:
            player = await channel.connect(cls=MusicPlayer)
        elif player.channel != channel:
            await player.move_to(channel)

        player.text_channel = interaction.channel
        return player

    @commands.Cog.listener()
    async def on_track_end(self, event: mafic.TrackEndEvent):
        player = event.player
        if not isinstance(player, MusicPlayer):
            return
        if not player.queue:
            return
        next_item = player.queue.pop(0)
        await player.play(next_item.track)
        if player.text_channel is not None:
            await player.text_channel.send(
                f"▶️ กำลังเล่น: **{next_item.track.title}** ({next_item.duration_str()})"
            )

    @commands.Cog.listener()
    async def on_track_exception(self, event: mafic.TrackExceptionEvent):
        player = event.player
        log.error(f"[music] เล่นเพลงพลาด (guild {player.guild.id}): {event.exception}")
        if isinstance(player, MusicPlayer) and player.text_channel is not None:
            await player.text_channel.send(f"⛔ เล่นเพลงนี้ไม่สำเร็จ: `{event.exception.get('message', 'ไม่ทราบสาเหตุ')}`")

    # ---------- Slash commands ----------

    @app_commands.command(name="play", description="เล่นเพลงจาก YouTube/ลิงก์ (ถ้ามีเล่นอยู่แล้วจะเข้าคิวต่อ)")
    @app_commands.describe(query="ชื่อเพลงที่จะค้นหา หรือลิงก์ YouTube/เพลงตรง ๆ")
    async def play(self, interaction: discord.Interaction, query: str):
        if interaction.guild is None:
            return
        player = await self._ensure_voice(interaction)
        if player is None:
            return

        await interaction.response.defer()

        search_query = query if query.startswith(("http://", "https://")) else f"ytsearch:{query}"

        try:
            results = await player.fetch_tracks(search_query)
        except Exception as error:
            log.error(f"[music] fetch_tracks พลาด: {error}")
            await interaction.followup.send("⛔ ดึงข้อมูลเพลงไม่สำเร็จ ลองใหม่อีกครั้งครับ")
            return

        if not results:
            await interaction.followup.send("⛔ หาเพลงนี้ไม่เจอครับ ลองคำอื่นหรือลิงก์อื่นดูนะ")
            return

        if isinstance(results, mafic.Playlist):
            tracks = results.tracks
        else:
            tracks = [results[0]]

        first = tracks[0]
        player.queue.extend(QueueItem(t, interaction.user) for t in tracks[1:])

        if player.current is not None:
            player.queue.insert(0, QueueItem(first, interaction.user))
            await interaction.followup.send(
                f"➕ เข้าคิวแล้ว: **{first.title}**"
                + (f" และอีก {len(tracks) - 1} เพลงจากเพลย์ลิสต์" if len(tracks) > 1 else "")
            )
        else:
            await player.play(first)
            await interaction.followup.send(f"▶️ กำลังเล่น: **{first.title}**")

    @app_commands.command(name="skip", description="ข้ามเพลงที่กำลังเล่นอยู่ ไปเพลงต่อไปในคิว")
    async def skip(self, interaction: discord.Interaction):
        player = interaction.guild.voice_client
        if player is None or player.current is None:
            await interaction.response.send_message("⛔ ไม่มีเพลงกำลังเล่นอยู่ครับ", ephemeral=True)
            return
        await player.stop()
        await interaction.response.send_message("⏭️ ข้ามเพลงแล้วครับ")

    @app_commands.command(name="pause", description="พักเพลงที่กำลังเล่นไว้ชั่วคราว")
    async def pause(self, interaction: discord.Interaction):
        player = interaction.guild.voice_client
        if player is None or player.current is None:
            await interaction.response.send_message("⛔ ไม่มีเพลงกำลังเล่นอยู่ครับ", ephemeral=True)
            return
        await player.pause(True)
        await interaction.response.send_message("⏸️ พักเพลงไว้แล้วครับ")

    @app_commands.command(name="resume", description="เล่นเพลงที่พักไว้ต่อ")
    async def resume(self, interaction: discord.Interaction):
        player = interaction.guild.voice_client
        if player is None or not player.paused:
            await interaction.response.send_message("⛔ ไม่มีเพลงที่พักไว้ครับ", ephemeral=True)
            return
        await player.pause(False)
        await interaction.response.send_message("▶️ เล่นต่อแล้วครับ")

    @app_commands.command(name="stop", description="หยุดเพลง ล้างคิวทั้งหมด แล้วออกจากห้องเสียง")
    async def stop(self, interaction: discord.Interaction):
        player = interaction.guild.voice_client
        if player is not None:
            if isinstance(player, MusicPlayer):
                player.queue.clear()
            await player.disconnect()
        await interaction.response.send_message("⏹️ หยุดเพลงและออกจากห้องเสียงแล้วครับ")

    @app_commands.command(name="queue", description="ดูคิวเพลงที่รออยู่")
    async def show_queue(self, interaction: discord.Interaction):
        player = interaction.guild.voice_client

        embed = discord.Embed(title="🎵 คิวเพลง", color=discord.Color.blurple())

        if player is not None and player.current is not None:
            embed.add_field(name="กำลังเล่น", value=f"**{player.current.title}**", inline=False)
        else:
            embed.add_field(name="กำลังเล่น", value="ไม่มีเพลงเล่นอยู่", inline=False)

        if isinstance(player, MusicPlayer) and player.queue:
            lines = [
                f"{i+1}. **{item.track.title}** — ขอโดย {item.requester.mention}"
                for i, item in enumerate(player.queue[:10])
            ]
            if len(player.queue) > 10:
                lines.append(f"...และอีก {len(player.queue) - 10} เพลง")
            embed.add_field(name="รอในคิว", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="รอในคิว", value="ไม่มีเพลงในคิว", inline=False)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="nowplaying", description="ดูว่ากำลังเล่นเพลงอะไรอยู่")
    async def nowplaying(self, interaction: discord.Interaction):
        player = interaction.guild.voice_client
        if player is None or player.current is None:
            await interaction.response.send_message("⛔ ไม่มีเพลงเล่นอยู่ครับ", ephemeral=True)
            return
        await interaction.response.send_message(f"🎶 กำลังเล่น: **{player.current.title}**\n{player.current.uri}")

    @app_commands.command(name="volume", description="ปรับระดับเสียง (0-100)")
    @app_commands.describe(level="ระดับเสียง 0-100")
    async def volume(self, interaction: discord.Interaction, level: app_commands.Range[int, 0, 100]):
        player = interaction.guild.voice_client
        if player is None:
            await interaction.response.send_message("⛔ บอทไม่ได้อยู่ในห้องเสียงครับ", ephemeral=True)
            return
        await player.set_volume(level)
        await interaction.response.send_message(f"🔊 ปรับเสียงเป็น {level}% แล้วครับ")

    @app_commands.command(name="leave", description="ออกจากห้องเสียง (ไม่ล้างคิว)")
    async def leave(self, interaction: discord.Interaction):
        player = interaction.guild.voice_client
        if player is None:
            await interaction.response.send_message("⛔ บอทไม่ได้อยู่ในห้องเสียงครับ", ephemeral=True)
            return
        await player.disconnect()
        await interaction.response.send_message("👋 ออกจากห้องเสียงแล้วครับ")


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
