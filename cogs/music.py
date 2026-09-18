
import os
import logging
from dataclasses import dataclass

import discord
import mafic

from discord import app_commands
from discord.ext import commands


log = logging.getLogger(__name__)


# =====================================
# CONFIG
# =====================================

LAVALINK_HOST = os.getenv("LAVALINK_HOST", "localhost")
LAVALINK_PORT = int(os.getenv("LAVALINK_PORT", "2333"))
LAVALINK_PASSWORD = os.getenv(
    "LAVALINK_PASSWORD",
    "youshallnotpass",
)
LAVALINK_SECURE = (
    os.getenv("LAVALINK_SECURE", "false").lower() == "true"
)


# =====================================
# QUEUE ITEM
# =====================================

@dataclass
class QueueItem:
    track: mafic.Track
    requester: discord.Member


# =====================================
# MUSIC PLAYER
# =====================================

class MusicPlayer(mafic.Player):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.queue: list[QueueItem] = []
        self.text_channel: discord.abc.Messageable | None = None

    async def play_next(self):
        if not self.queue:
            return

        item = self.queue.pop(0)

        try:
            await self.play(item.track)

            if self.text_channel:
                await self.text_channel.send(
                    f"🎶 กำลังเล่น: **{item.track.title}**"
                )

        except Exception:
            log.exception("เล่นเพลงถัดไปไม่สำเร็จ")


# =====================================
# MUSIC COG
# =====================================

class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pool = mafic.NodePool(bot)
        self.node_ready = False

    async def cog_load(self):
        await self.connect_lavalink()

    async def cog_unload(self):
        try:
            await self.pool.close()
        except Exception:
            log.exception("ปิด Lavalink ไม่สำเร็จ")

    async def connect_lavalink(self):
        if self.node_ready:
            return

        try:
            await self.pool.create_node(
                host=LAVALINK_HOST,
                port=LAVALINK_PORT,
                label="MAIN",
                password=LAVALINK_PASSWORD,
                secure=LAVALINK_SECURE,
                player_cls=MusicPlayer,
            )

            self.node_ready = True
            log.info("เชื่อมต่อ Lavalink สำเร็จ")

        except Exception:
            log.exception("เชื่อมต่อ Lavalink ไม่สำเร็จ")

    # =================================
    # VOICE
    # =================================

    async def ensure_voice(
        self,
        interaction: discord.Interaction,
    ) -> MusicPlayer | None:

        if interaction.guild is None:
            await interaction.followup.send(
                "❌ คำสั่งนี้ใช้ได้เฉพาะในเซิร์ฟเวอร์",
                ephemeral=True,
            )
            return None

        user = interaction.user

        if not isinstance(user, discord.Member):
            return None

        if user.voice is None or user.voice.channel is None:
            await interaction.followup.send(
                "❌ กรุณาเข้าห้องเสียงก่อน",
                ephemeral=True,
            )
            return None

        channel = user.voice.channel
        voice_client = interaction.guild.voice_client

        try:
            if voice_client is None:
                player = await channel.connect(
                    cls=MusicPlayer,
                    timeout=20.0,
                    reconnect=True,
                )
            else:
                if voice_client.channel != channel:
                    await voice_client.move_to(channel)

                player = voice_client

            if not isinstance(player, MusicPlayer):
                await interaction.followup.send(
                    "❌ ไม่สามารถสร้าง Music Player ได้",
                    ephemeral=True,
                )
                return None

            player.text_channel = interaction.channel

            return player

        except Exception:
            log.exception("เชื่อมต่อห้องเสียงไม่สำเร็จ")

            await interaction.followup.send(
                "❌ เชื่อมต่อห้องเสียงไม่สำเร็จ",
                ephemeral=True,
            )
            return None

    async def get_player(
        self,
        interaction: discord.Interaction,
    ) -> MusicPlayer | None:

        if interaction.guild is None:
            await interaction.followup.send(
                "❌ ไม่พบเซิร์ฟเวอร์",
                ephemeral=True,
            )
            return None

        voice_client = interaction.guild.voice_client

        if not isinstance(voice_client, MusicPlayer):
            await interaction.followup.send(
                "❌ บอทยังไม่ได้อยู่ในห้องเสียง",
                ephemeral=True,
            )
            return None

        voice_client.text_channel = interaction.channel

        return voice_client

    # =================================
    # EVENTS
    # =================================

    @commands.Cog.listener()
    async def on_mafic_track_end(
        self,
        event: mafic.TrackEndEvent,
    ):
        player = event.player

        if isinstance(player, MusicPlayer):
            await player.play_next()

    @commands.Cog.listener()
    async def on_mafic_track_exception(
        self,
        event: mafic.TrackExceptionEvent,
    ):
        log.error("Track exception: %s", event)

        player = event.player

        if isinstance(player, MusicPlayer):
            await player.play_next()

    @commands.Cog.listener()
    async def on_mafic_track_stuck(
        self,
        event: mafic.TrackStuckEvent,
    ):
        log.warning("Track stuck: %s", event)

        player = event.player

        if isinstance(player, MusicPlayer):
            await player.play_next()

    # =================================
    # PLAY
    # =================================

    @app_commands.command(
        name="play",
        description="เปิดเพลงจาก URL หรือคำค้นหา",
    )
    @app_commands.describe(query="ชื่อเพลงหรือ URL")
    async def play(
        self,
        interaction: discord.Interaction,
        query: str,
    ):
        # ตอบรับ Interaction ก่อนเสมอ
        await interaction.response.defer()

        player = await self.ensure_voice(interaction)

        if player is None:
            return

        try:
            tracks = await player.fetch_tracks(query)

            if not tracks:
                await interaction.followup.send(
                    "❌ ไม่พบเพลงที่ค้นหา"
                )
                return

            if isinstance(tracks, mafic.Playlist):
                found_tracks = tracks.tracks
            else:
                found_tracks = tracks

            if not found_tracks:
                await interaction.followup.send(
                    "❌ ไม่พบเพลง"
                )
                return

            for track in found_tracks:
                player.queue.append(
                    QueueItem(
                        track=track,
                        requester=interaction.user,
                    )
                )

            if player.current is None:
                await player.play_next()

                await interaction.followup.send(
                    f"▶️ เริ่มเล่น **{found_tracks[0].title}**"
                )
            else:
                await interaction.followup.send(
                    f"✅ เพิ่มเพลงลงคิวแล้ว "
                    f"**{len(found_tracks)} เพลง**"
                )

        except Exception:
            log.exception("คำสั่ง play ผิดพลาด")

            await interaction.followup.send(
                "❌ ไม่สามารถโหลดเพลงได้"
            )

    # =================================
    # SKIP
    # =================================

    @app_commands.command(
        name="skip",
        description="ข้ามเพลงปัจจุบัน",
    )
    async def skip(self, interaction: discord.Interaction):
        await interaction.response.defer()

        player = await self.get_player(interaction)

        if player is None:
            return

        if player.current is None:
            await interaction.followup.send(
                "❌ ไม่มีเพลงที่กำลังเล่น"
            )
            return

        await player.stop()

        await interaction.followup.send(
            "⏭️ ข้ามเพลงแล้ว"
        )

    # =================================
    # PAUSE
    # =================================

    @app_commands.command(
        name="pause",
        description="หยุดเพลงชั่วคราว",
    )
    async def pause(self, interaction: discord.Interaction):
        await interaction.response.defer()

        player = await self.get_player(interaction)

        if player is None:
            return

        await player.pause(True)

        await interaction.followup.send(
            "⏸️ หยุดเพลงชั่วคราวแล้ว"
        )

    # =================================
    # RESUME
    # =================================

    @app_commands.command(
        name="resume",
        description="เล่นเพลงต่อ",
    )
    async def resume(self, interaction: discord.Interaction):
        await interaction.response.defer()

        player = await self.get_player(interaction)

        if player is None:
            return

        await player.pause(False)

        await interaction.followup.send(
            "▶️ เล่นเพลงต่อแล้ว"
        )

    # =================================
    # STOP
    # =================================

    @app_commands.command(
        name="stop",
        description="หยุดเพลงและล้างคิว",
    )
    async def stop(self, interaction: discord.Interaction):
        await interaction.response.defer()

        player = await self.get_player(interaction)

        if player is None:
            return

        player.queue.clear()

        await player.stop()

        await interaction.followup.send(
            "⏹️ หยุดเพลงและล้างคิวแล้ว"
        )

    # =================================
    # QUEUE
    # =================================

    @app_commands.command(
        name="queue",
        description="ดูคิวเพลง",
    )
    async def queue(self, interaction: discord.Interaction):
        await interaction.response.defer()

        player = await self.get_player(interaction)

        if player is None:
            return

        if not player.queue:
            await interaction.followup.send(
                "📭 คิวเพลงว่าง"
            )
            return

        lines = []

        for index, item in enumerate(
            player.queue[:20],
            start=1,
        ):
            lines.append(
                f"`{index}.` {item.track.title}"
            )

        embed = discord.Embed(
            title="🎵 Music Queue",
            description="\n".join(lines),
            color=discord.Color.blurple(),
        )

        await interaction.followup.send(
            embed=embed
        )

    # =================================
    # NOW PLAYING
    # =================================

    @app_commands.command(
        name="nowplaying",
        description="ดูเพลงที่กำลังเล่น",
    )
    async def nowplaying(
        self,
        interaction: discord.Interaction,
    ):
        await interaction.response.defer()

        player = await self.get_player(interaction)

        if player is None:
            return

        if player.current is None:
            await interaction.followup.send(
                "📭 ไม่มีเพลงที่กำลังเล่น"
            )
            return

        track = player.current

        embed = discord.Embed(
            title="🎶 Now Playing",
            description=f"**{track.title}**",
            color=discord.Color.green(),
        )

        embed.add_field(
            name="ศิลปิน",
            value=track.author or "ไม่ทราบ",
            inline=False,
        )

        embed.add_field(
            name="สถานะ",
            value=(
                "⏸️ หยุดชั่วคราว"
                if player.paused
                else "▶️ กำลังเล่น"
            ),
            inline=False,
        )

        await interaction.followup.send(
            embed=embed
        )

    # =================================
    # VOLUME
    # =================================

    @app_commands.command(
        name="volume",
        description="ปรับระดับเสียง",
    )
    @app_commands.describe(
        level="ระดับเสียง 0-1000",
    )
    async def volume(
        self,
        interaction: discord.Interaction,
        level: app_commands.Range[int, 0, 1000],
    ):
        await interaction.response.defer()

        player = await self.get_player(interaction)

        if player is None:
            return

        await player.set_volume(level)

        await interaction.followup.send(
            f"🔊 ตั้งเสียงเป็น **{level}%** แล้ว"
        )

    # =================================
    # LEAVE
    # =================================

    @app_commands.command(
        name="leave",
        description="ให้บอทออกจากห้องเสียง",
    )
    async def leave(self, interaction: discord.Interaction):
        await interaction.response.defer()

        player = await self.get_player(interaction)

        if player is None:
            return

        player.queue.clear()

        await player.disconnect()

        await interaction.followup.send(
            "👋 ออกจากห้องเสียงแล้ว"
        )


# =====================================
# SETUP
# =====================================

async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
