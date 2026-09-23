"""
cogs/antiraid.py — 🛡️ Anti-Raid & Security Config
ตั้ง Raid Threshold (คนเข้าเซิร์ฟต่อวินาที) และเกณฑ์ Flag บัญชีใหม่ (อายุบัญชีขั้นต่ำ)
เมื่อเกินเกณฑ์ บอทจะแจ้งเตือนในห้องที่กำหนด
"""

from collections import deque
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

import db
import style
from checks import require_permission


class AntiRaid(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # เก็บ timestamp การ join ล่าสุดของแต่ละ guild ไว้ในหน่วยความจำ (guild_id -> deque[datetime])
        self.join_windows: dict[int, deque] = {}

    async def alert(self, guild: discord.Guild, channel_id, embed: discord.Embed):
        if not channel_id:
            return
        channel = guild.get_channel(channel_id)
        if channel:
            await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if not await db.is_system_enabled(member.guild.id, "antiraid"):
            return
        cfg = (await db.get_guild_config(member.guild.id))["antiraid"]

        # --- เช็คอายุบัญชีใหม่ ---
        account_age_days = (datetime.now(timezone.utc) - member.created_at).days
        if account_age_days < cfg.get("min_account_age_days", 7):
            await self.alert(
                member.guild,
                cfg.get("alert_channel_id"),
                style.warn(
                    f"{member.mention} สร้างบัญชีมาแค่ **{account_age_days} วัน**",
                    title="🚩 บัญชีใหม่", system="antiraid",
                ),
            )

        # --- เช็ค raid (join ถี่ผิดปกติ) ---
        window = self.join_windows.setdefault(member.guild.id, deque())
        now = datetime.now(timezone.utc)
        window.append(now)
        window_seconds = cfg.get("window_seconds", 10)
        while window and (now - window[0]).total_seconds() > window_seconds:
            window.popleft()

        if len(window) >= cfg.get("join_threshold", 5):
            await self.alert(
                member.guild,
                cfg.get("alert_channel_id"),
                style.error(
                    f"มีคนเข้าเซิร์ฟ **{len(window)} คน** ภายใน **{window_seconds} วินาที** กรุณาตรวจสอบ",
                    title="🛡️ แจ้งเตือน Raid", system="antiraid",
                ),
            )

    @app_commands.command(
        name="antiraid-config", description="ตั้งค่าระบบป้องกัน Raid (แอดมินเท่านั้น)"
    )
    @require_permission()
    @app_commands.describe(
        join_threshold="จำนวนคนเข้าเซิร์ฟที่ถือว่าผิดปกติ",
        window_seconds="ภายในกี่วินาที",
        min_account_age_days="อายุบัญชีขั้นต่ำ (วัน) ก่อนจะถูก flag",
        alert_channel="ห้องที่จะส่งแจ้งเตือน",
    )
    async def antiraid_config(
        self,
        interaction: discord.Interaction,
        join_threshold: int,
        window_seconds: int,
        min_account_age_days: int,
        alert_channel: discord.TextChannel,
    ):
        await db.update_guild_section(
            interaction.guild_id,
            "antiraid",
            {
                "join_threshold": join_threshold,
                "window_seconds": window_seconds,
                "min_account_age_days": min_account_age_days,
                "alert_channel_id": alert_channel.id,
            },
        )
        await interaction.response.send_message(
            embed=style.success(
                f"เกิน **{join_threshold} คน** ใน **{window_seconds} วิ** จะแจ้งเตือน\n"
                f"flag บัญชีอายุน้อยกว่า **{min_account_age_days} วัน** ที่ห้อง {alert_channel.mention}",
                title="ตั้งค่า Anti-Raid แล้ว", system="antiraid",
            ),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(AntiRaid(bot))
