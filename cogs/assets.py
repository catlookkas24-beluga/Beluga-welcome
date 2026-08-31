"""
cogs/assets.py — 📁 Custom Asset Storage
คลังเก็บไฟล์ที่แอดมินอัปโหลดเอง (รูป/ฟอนต์/config) เก็บถาวรใน MongoDB (GridFS)
ไม่มีการประมวลผล/เรนเดอร์อะไรกับไฟล์ในนี้ — เก็บไว้ให้ระบบอื่น (เช่น font-preview) มาเรียกใช้ต่อ
"""

import discord
from discord import app_commands
from discord.ext import commands

import db
from .checks import require_permission

TYPE_LABELS = {"image": "🖼️ รูปภาพ", "font": "🔤 ฟอนต์", "config": "📄 Config/Text"}


class Assets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="asset-upload", description="อัปโหลดไฟล์ (รูป/ฟอนต์/config) เก็บถาวร (แอดมินเท่านั้น)"
    )
    @require_permission()
    @app_commands.describe(
        file="ไฟล์ที่จะอัปโหลด (.png .jpg .jpeg .webp / .ttf .otf / .json .txt)",
        label="ชื่อเรียกไฟล์นี้ (เอาไว้เลือกใช้ทีหลัง)",
    )
    async def asset_upload(
        self, interaction: discord.Interaction, file: discord.Attachment, label: str
    ):
        asset_type = db.detect_asset_type(file.filename)
        if asset_type is None:
            await interaction.response.send_message(
                "⚠️ นามสกุลไฟล์นี้ไม่รองรับ ต้องเป็น .png .jpg .jpeg .webp (รูป), "
                ".ttf .otf (ฟอนต์), หรือ .json .txt (config) เท่านั้น",
                ephemeral=True,
            )
            return
        if file.size > db.MAX_ASSET_SIZE_BYTES:
            await interaction.response.send_message(
                f"⚠️ ไฟล์ใหญ่เกินไป ({file.size / 1024 / 1024:.1f}MB) จำกัดไว้ที่ 5MB",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        data = await file.read()
        file_id = await db.save_asset(
            interaction.guild_id, file.filename, data, asset_type, label
        )
        await interaction.followup.send(
            f"✅ อัปโหลด **{label}** ({TYPE_LABELS[asset_type]}) แล้ว\n"
            f"ขนาด: {len(data) / 1024:.1f} KB | ID: `{file_id}`",
            ephemeral=True,
        )

    @app_commands.command(name="asset-list", description="ดูรายชื่อไฟล์ที่อัปโหลดไว้ทั้งหมด")
    @require_permission()
    async def asset_list(self, interaction: discord.Interaction):
        assets = await db.list_assets(interaction.guild_id)
        if not assets:
            await interaction.response.send_message(
                "ยังไม่มีไฟล์ที่อัปโหลดไว้เลยครับ ใช้ `/asset-upload` เพื่อเริ่มอัปโหลด", ephemeral=True
            )
            return

        embed = discord.Embed(title="📁 ไฟล์ที่อัปโหลดไว้", color=discord.Color.blurple())
        for asset_type, label in TYPE_LABELS.items():
            items = [a for a in assets if a["asset_type"] == asset_type]
            if not items:
                continue
            value = "\n".join(
                f"• **{a['label']}** ({a['length'] / 1024:.1f} KB) — ID: `{a['file_id']}`"
                for a in items
            )
            embed.add_field(name=label, value=value, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="asset-delete", description="ลบไฟล์ที่อัปโหลดไว้ (แอดมินเท่านั้น)")
    @require_permission()
    @app_commands.describe(file_id="ID ของไฟล์ (ดูได้จาก /asset-list)")
    async def asset_delete(self, interaction: discord.Interaction, file_id: str):
        try:
            deleted = await db.delete_asset(interaction.guild_id, file_id)
        except Exception:
            await interaction.response.send_message("⚠️ ไม่พบไฟล์ ID นี้", ephemeral=True)
            return
        if deleted:
            await interaction.response.send_message("🗑️ ลบไฟล์แล้ว", ephemeral=True)
        else:
            await interaction.response.send_message(
                "⚠️ ไม่พบไฟล์นี้ในเซิร์ฟเวอร์นี้ (อาจเป็นไฟล์ของเซิร์ฟอื่น)", ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(Assets(bot))
