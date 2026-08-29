"""
cogs/autorole.py — 🏅 Auto Role Timeline Config
กำหนดว่ากี่วันได้ยศอะไร (เช่น 7d Member, 30d Active, 60d Veteran, 90d Legend)
เปิด auto_grant ให้บอทแจกอัตโนมัติ หรือปิดไว้ให้สมาชิกกดรับเองที่ห้อง claim
"""

from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

import db


async def sync_guild_roles(guild: discord.Guild) -> int:
    """เช็คสมาชิกทุกคนในเซิร์ฟ แจกยศตาม autorole timeline ที่ยังไม่ได้ คืนค่าจำนวนคนที่ได้ยศเพิ่ม
    ใช้ทั้งจาก background task (check_timeline) และคำสั่ง /force-sync-roles"""
    cfg = (await db.get_guild_config(guild.id))["autorole"]
    timeline = sorted(cfg["timeline"], key=lambda t: t["days"])
    now = datetime.now(timezone.utc)
    granted = 0
    for member in guild.members:
        if member.bot or member.joined_at is None:
            continue
        days_in_server = (now - member.joined_at).days
        eligible = [t for t in timeline if t["role_id"] and days_in_server >= t["days"]]
        if not eligible:
            continue
        target = max(eligible, key=lambda t: t["days"])
        role = guild.get_role(target["role_id"])
        if role and role not in member.roles:
            try:
                await member.add_roles(role, reason="Auto Role Timeline")
                granted += 1
            except discord.Forbidden:
                pass
    return granted


class ClaimRoleView(discord.ui.View):
    """ปุ่มถาวรสำหรับห้อง #รับยศต่างๆ เมื่อ auto_grant ปิดอยู่"""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="รับยศตามอายุสมาชิก",
        emoji="🏅",
        style=discord.ButtonStyle.primary,
        custom_id="beluga:autorole:claim",
    )
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = (await db.get_guild_config(interaction.guild_id))["autorole"]
        member = interaction.user
        days_in_server = (datetime.now(timezone.utc) - member.joined_at).days
        eligible = [t for t in cfg["timeline"] if t["role_id"] and days_in_server >= t["days"]]
        if not eligible:
            await interaction.response.send_message(
                f"คุณอยู่มา {days_in_server} วัน ยังไม่ถึงเกณฑ์รับยศครับ", ephemeral=True
            )
            return
        best = max(eligible, key=lambda t: t["days"])
        role = interaction.guild.get_role(best["role_id"])
        if role is None:
            await interaction.response.send_message("⚠️ ยศนี้ถูกลบไปแล้ว", ephemeral=True)
            return
        if role in member.roles:
            await interaction.response.send_message("คุณมียศนี้อยู่แล้วครับ", ephemeral=True)
            return
        await member.add_roles(role, reason="รับยศตามอายุสมาชิก (self-claim)")
        await interaction.response.send_message(f"🎉 ได้รับยศ {role.mention} แล้ว!", ephemeral=True)


class AutoRole(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(ClaimRoleView())
        self.check_timeline.start()

    def cog_unload(self):
        self.check_timeline.cancel()

    @tasks.loop(hours=6)
    async def check_timeline(self):
        for guild in self.bot.guilds:
            if not await db.is_system_enabled(guild.id, "autorole"):
                continue
            cfg = (await db.get_guild_config(guild.id))["autorole"]
            if not cfg.get("auto_grant", True):
                continue
            await sync_guild_roles(guild)

    @check_timeline.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    @app_commands.command(
        name="autorole-set", description="ตั้งค่ายศตามจำนวนวันในเซิร์ฟ (แอดมินเท่านั้น)"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(days="จำนวนวันที่ต้องอยู่ในเซิร์ฟ", role="ยศที่จะได้รับ", label="ชื่อระดับ (เช่น Member, Veteran)")
    async def autorole_set(
        self, interaction: discord.Interaction, days: int, role: discord.Role, label: str
    ):
        cfg = (await db.get_guild_config(interaction.guild_id))["autorole"]
        timeline = [t for t in cfg["timeline"] if t["days"] != days]
        timeline.append({"days": days, "role_id": role.id, "label": label})
        await db.update_guild_section(interaction.guild_id, "autorole", {"timeline": timeline})
        await interaction.response.send_message(
            f"✅ ตั้งค่า {days} วัน = {role.mention} ({label}) แล้ว", ephemeral=True
        )

    @app_commands.command(
        name="autorole-mode", description="เลือกโหมด: แจกอัตโนมัติ หรือ ให้กดรับเอง (แอดมินเท่านั้น)"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="แจกอัตโนมัติ", value="auto"),
            app_commands.Choice(name="ให้สมาชิกกดรับเอง", value="claim"),
        ]
    )
    async def autorole_mode(self, interaction: discord.Interaction, mode: app_commands.Choice[str]):
        await db.update_guild_section(
            interaction.guild_id, "autorole", {"auto_grant": mode.value == "auto"}
        )
        await interaction.response.send_message(f"✅ ตั้งโหมดเป็น: {mode.name}", ephemeral=True)

    @app_commands.command(
        name="autorole-post-claim", description="โพสต์ปุ่มรับยศในห้องนี้ (แอดมินเท่านั้น)"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def autorole_post_claim(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🏅 รับยศตามอายุสมาชิก",
            description="กดปุ่มด้านล่างเพื่อตรวจสอบและรับยศตามระยะเวลาที่คุณอยู่ในเซิร์ฟเวอร์",
            color=discord.Color.gold(),
        )
        await interaction.channel.send(embed=embed, view=ClaimRoleView())
        await db.update_guild_section(
            interaction.guild_id, "autorole", {"claim_channel_id": interaction.channel_id}
        )
        await interaction.response.send_message("✅ โพสต์ปุ่มรับยศแล้ว", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoRole(bot))
