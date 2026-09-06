"""
cogs/activity.py — 📊 Activity / Stats Dashboard
นับข้อความ + เวลาเข้าห้องเสียงของสมาชิกแต่ละคน แล้วสรุปเป็นอันดับ/กราฟ
"""

import io
import os
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont

import db

CHART_FONT_PATH = os.path.join(os.path.dirname(__file__), "..", "fonts", "mali.ttf")


def format_hours(seconds: int) -> str:
    hours = seconds / 3600
    if hours < 1:
        return f"{int(seconds / 60)} นาที"
    return f"{hours:.1f} ชม."


def render_rank_bar(rank: int, total: int, length: int = 10) -> str:
    """แปลงอันดับเป็นแถบภาพ ██████░░░░ — อันดับ 1 = เต็มแถบ, อันดับสุดท้าย = ว่างเกือบหมด"""
    if total <= 1:
        fraction = 1.0
    else:
        fraction = 1 - (rank - 1) / (total - 1)
    filled = round(fraction * length)
    filled = max(0, min(length, filled))
    return "🟩" * filled + "⬜" * (length - filled)


def render_activity_chart(daily_series: list, width: int = 700, height: int = 320) -> bytes:
    """วาดกราฟเส้นคู่ (ข้อความ vs เวลาเสียง) ย้อนหลังตามจำนวนวันใน daily_series
    สเกลแต่ละเส้นตาม max ของตัวเอง เพื่อให้เห็นแนวโน้มเทียบกันได้แม้หน่วยต่างกัน"""
    pad_left, pad_right, pad_top, pad_bottom = 50, 30, 40, 50
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    img = Image.new("RGB", (width, height), (24, 24, 30))
    draw = ImageDraw.Draw(img)

    try:
        font_small = ImageFont.truetype(CHART_FONT_PATH, 14)
        font_legend = ImageFont.truetype(CHART_FONT_PATH, 16)
    except Exception:
        font_small = ImageFont.load_default()
        font_legend = font_small

    dates = [d for d, _, _ in daily_series]
    messages = [m for _, m, _ in daily_series]
    voice_minutes = [v / 60 for _, _, v in daily_series]

    max_msg = max(messages) if max(messages, default=0) > 0 else 1
    max_voice = max(voice_minutes) if max(voice_minutes, default=0) > 0 else 1

    n = len(dates)
    step_x = plot_w / max(n - 1, 1)

    def to_xy(values, max_val):
        points = []
        for i, v in enumerate(values):
            x = pad_left + i * step_x
            y = pad_top + plot_h - (v / max_val) * plot_h
            points.append((x, y))
        return points

    draw.line(
        [(pad_left, pad_top), (pad_left, pad_top + plot_h), (pad_left + plot_w, pad_top + plot_h)],
        fill=(70, 70, 80),
        width=2,
    )

    msg_points = to_xy(messages, max_msg)
    voice_points = to_xy(voice_minutes, max_voice)

    if len(msg_points) > 1:
        draw.line(msg_points, fill=(100, 160, 255), width=3, joint="curve")
    if len(voice_points) > 1:
        draw.line(voice_points, fill=(255, 110, 180), width=3, joint="curve")

    label_every = max(n // 6, 1)
    for i, d in enumerate(dates):
        if i % label_every == 0 or i == n - 1:
            short_label = d[5:]  # "MM-DD"
            draw.text(
                (pad_left + i * step_x - 12, pad_top + plot_h + 8),
                short_label,
                font=font_small,
                fill=(160, 160, 170),
            )

    draw.ellipse((pad_left, 10, pad_left + 10, 20), fill=(100, 160, 255))
    draw.text((pad_left + 16, 8), "ข้อความ", font=font_legend, fill=(220, 220, 230))
    draw.ellipse((pad_left + 110, 10, pad_left + 120, 20), fill=(255, 110, 180))
    draw.text((pad_left + 126, 8), "เวลาเสียง (นาที)", font=font_legend, fill=(220, 220, 230))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class Activity(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # เก็บเวลาที่แต่ละคนเข้าห้องเสียงไว้ในหน่วยความจำ (guild_id, user_id) -> datetime
        self.voice_join_times: dict[tuple, datetime] = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        if not await db.is_system_enabled(message.guild.id, "activity"):
            return
        await db.track_message(message.guild.id, message.author.id, message.channel.id)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ):
        if member.bot:
            return
        key = (member.guild.id, member.id)
        now = datetime.now(timezone.utc)

        if before.channel is None and after.channel is not None:
            self.voice_join_times[key] = now
        elif before.channel is not None and after.channel is None:
            join_time = self.voice_join_times.pop(key, None)
            if join_time and await db.is_system_enabled(member.guild.id, "activity"):
                elapsed = int((now - join_time).total_seconds())
                await db.track_voice_time(member.guild.id, member.id, elapsed)

    @app_commands.command(name="stats", description="ดูสถิติกิจกรรมของสมาชิก (ข้อความ/เวลาเสียง)")
    @app_commands.describe(member="เลือกสมาชิก (เว้นว่าง = ดูของตัวเอง)")
    async def stats(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        await interaction.response.defer()

        totals = await db.get_user_totals(interaction.guild_id, target.id)
        msg_rank, msg_total_users = await db.get_rank(interaction.guild_id, target.id, "total_messages")
        voice_rank, _ = await db.get_rank(interaction.guild_id, target.id, "total_voice_seconds")

        msg_7d, voice_7d = await db.get_window_sum(interaction.guild_id, target.id, 7)
        msg_30d, voice_30d = await db.get_window_sum(interaction.guild_id, target.id, 30)

        top_channels = await db.get_top_channels(interaction.guild_id, target.id, limit=3)
        daily_series = await db.get_daily_series(interaction.guild_id, target.id, days=14)

        embed = discord.Embed(
            title=f"📊 สถิติของ {target.display_name}",
            color=target.color if target.color.value else discord.Color.blurple(),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(
            name="🏆 อันดับในเซิร์ฟ",
            value=(
                f"ข้อความ: **#{msg_rank}** / {msg_total_users}\n"
                f"{render_rank_bar(msg_rank, msg_total_users)}\n"
                f"เวลาเสียง: **#{voice_rank}** / {msg_total_users}\n"
                f"{render_rank_bar(voice_rank, msg_total_users)}"
            ),
            inline=False,
        )
        embed.add_field(
            name="💬 ข้อความ",
            value=f"7 วัน: **{msg_7d}**\n30 วัน: **{msg_30d}**\nตลอดกาล: **{totals['total_messages']}**",
            inline=True,
        )
        embed.add_field(
            name="🎙️ เวลาเสียง",
            value=(
                f"7 วัน: **{format_hours(voice_7d)}**\n"
                f"30 วัน: **{format_hours(voice_30d)}**\n"
                f"ตลอดกาล: **{format_hours(totals['total_voice_seconds'])}**"
            ),
            inline=True,
        )
        if top_channels:
            lines = []
            for ch_id, count in top_channels:
                ch = interaction.guild.get_channel(ch_id)
                name = ch.mention if ch else f"#{ch_id}"
                lines.append(f"{name} — {count} ข้อความ")
            embed.add_field(name="📌 ห้องที่ใช้บ่อยสุด", value="\n".join(lines), inline=False)

        embed.set_footer(
            text=f"เข้าร่วมเซิร์ฟเมื่อ {target.joined_at.strftime('%d/%m/%Y') if target.joined_at else 'ไม่ทราบ'} • "
            f"สร้างบัญชีเมื่อ {target.created_at.strftime('%d/%m/%Y')}"
        )

        try:
            chart_bytes = render_activity_chart(daily_series)
            file = discord.File(io.BytesIO(chart_bytes), filename="activity_chart.png")
            embed.set_image(url="attachment://activity_chart.png")
            await interaction.followup.send(embed=embed, file=file)
        except Exception:
            await interaction.followup.send(embed=embed)

    @app_commands.command(name="leaderboard", description="ดูอันดับสมาชิกที่ active สุดในเซิร์ฟ")
    @app_commands.describe(metric="เลือกจัดอันดับตามอะไร")
    @app_commands.choices(
        metric=[
            app_commands.Choice(name="💬 ข้อความ", value="total_messages"),
            app_commands.Choice(name="🎙️ เวลาเสียง", value="total_voice_seconds"),
        ]
    )
    async def leaderboard(self, interaction: discord.Interaction, metric: app_commands.Choice[str]):
        await interaction.response.defer()
        top = await db.get_leaderboard(interaction.guild_id, metric.value, limit=10)
        if not top:
            await interaction.followup.send("ยังไม่มีข้อมูลสถิติเลยครับ")
            return

        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, (user_id, value) in enumerate(top):
            prefix = medals[i] if i < 3 else f"`#{i + 1}`"
            value_text = format_hours(value) if metric.value == "total_voice_seconds" else f"{value} ข้อความ"
            lines.append(f"{prefix} <@{user_id}> — **{value_text}**")

        embed = discord.Embed(
            title=f"🏆 Leaderboard — {metric.name}",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Activity(bot))
