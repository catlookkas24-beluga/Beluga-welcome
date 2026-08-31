"""
cogs/cmdperms.py — 🔑 Command Permission Manager
กำหนดได้ว่ายศไหนใช้คำสั่งของบอทตัวไหนได้บ้าง แยกจากสิทธิ์ Manage Server ของ Discord

⚠️ คำสั่งในไฟล์นี้เองยังคงใช้ has_permissions(manage_guild=True) แบบเดิม (ไม่ใช่ระบบใหม่)
เพราะเป็นคำสั่ง "แจกสิทธิ์" เอง ถ้าปลดล็อกให้ยศอื่นมาแจกสิทธิ์ต่อได้ จะเกิดช่องโหว่ยกระดับสิทธิ์ตัวเอง
"""

import discord
from discord import app_commands
from discord.ext import commands

import db


async def command_name_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    all_commands = interaction.client.tree.get_commands()
    names = [cmd.qualified_name for cmd in all_commands]
    filtered = [n for n in names if current.lower() in n.lower()]
    return [app_commands.Choice(name=n, value=n) for n in sorted(filtered)[:25]]


class CommandPermissions(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="cmdperm-grant", description="อนุญาตให้ยศนี้ใช้คำสั่งที่ระบุได้ (แอดมินเท่านั้น)"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.autocomplete(command=command_name_autocomplete)
    @app_commands.describe(command="ชื่อคำสั่ง (ไม่ต้องมี /)", role="ยศที่จะให้สิทธิ์")
    async def cmdperm_grant(self, interaction: discord.Interaction, command: str, role: discord.Role):
        valid_names = {c.qualified_name for c in self.bot.tree.get_commands()}
        if command not in valid_names:
            await interaction.response.send_message(
                f"⚠️ ไม่พบคำสั่ง `{command}` — เช็คชื่อจาก autocomplete อีกครั้ง", ephemeral=True
            )
            return
        await db.add_allowed_role(interaction.guild_id, command, role.id)
        await interaction.response.send_message(
            f"✅ ให้สิทธิ์ {role.mention} ใช้คำสั่ง `/{command}` แล้ว", ephemeral=True
        )

    @app_commands.command(
        name="cmdperm-revoke", description="เอาสิทธิ์การใช้คำสั่งของยศนี้ออก (แอดมินเท่านั้น)"
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.autocomplete(command=command_name_autocomplete)
    @app_commands.describe(command="ชื่อคำสั่ง (ไม่ต้องมี /)", role="ยศที่จะเอาสิทธิ์ออก")
    async def cmdperm_revoke(self, interaction: discord.Interaction, command: str, role: discord.Role):
        await db.remove_allowed_role(interaction.guild_id, command, role.id)
        await interaction.response.send_message(
            f"🗑️ เอาสิทธิ์ {role.mention} ใช้คำสั่ง `/{command}` ออกแล้ว", ephemeral=True
        )

    @app_commands.command(
        name="cmdperm-grant-bulk",
        description="ให้ยศนี้ใช้ได้หลายคำสั่งพร้อมกันในครั้งเดียว (แอดมินเท่านั้น)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        role="ยศที่จะให้สิทธิ์",
        commands="ชื่อคำสั่งหลายอัน คั่นด้วยจุลภาค เช่น welcome-editor, rules-editor, autorole-set "
        "(เช็คชื่อที่ถูกต้องได้จาก /cmdperm-list-all)",
    )
    async def cmdperm_grant_bulk(
        self, interaction: discord.Interaction, role: discord.Role, commands: str
    ):
        valid_names = {c.qualified_name for c in self.bot.tree.get_commands()}
        requested = [c.strip() for c in commands.split(",") if c.strip()]

        granted, invalid = [], []
        for name in requested:
            if name in valid_names:
                await db.add_allowed_role(interaction.guild_id, name, role.id)
                granted.append(name)
            else:
                invalid.append(name)

        lines = [f"✅ ให้สิทธิ์ {role.mention} ใช้ **{len(granted)} คำสั่ง** สำเร็จ"]
        if granted:
            lines.append("`" + "`, `".join(granted) + "`")
        if invalid:
            lines.append(f"\n⚠️ ไม่พบคำสั่งเหล่านี้ (สะกดถูกไหม?): `" + "`, `".join(invalid) + "`")

        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @app_commands.command(name="cmdperm-list", description="ดูว่ายศไหนถูกให้สิทธิ์ใช้คำสั่งนี้บ้าง")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.autocomplete(command=command_name_autocomplete)
    async def cmdperm_list(self, interaction: discord.Interaction, command: str):
        role_ids = await db.get_allowed_roles(interaction.guild_id, command)
        if not role_ids:
            await interaction.response.send_message(
                f"ยังไม่มียศไหนถูกปลดล็อกสำหรับ `/{command}` เลย (ใช้ได้แค่คนที่มี Manage Server)",
                ephemeral=True,
            )
            return
        mentions = [f"<@&{rid}>" for rid in role_ids]
        await interaction.response.send_message(
            f"ยศที่ใช้ `/{command}` ได้เพิ่มเติม:\n" + "\n".join(mentions), ephemeral=True
        )

    @app_commands.command(name="cmdperm-list-all", description="ดูสิทธิ์คำสั่งทั้งหมดที่ตั้งไว้ในเซิร์ฟนี้")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cmdperm_list_all(self, interaction: discord.Interaction):
        all_perms = await db.get_all_command_permissions(interaction.guild_id)
        if not all_perms:
            await interaction.response.send_message(
                "ยังไม่มีการตั้งค่าสิทธิ์คำสั่งพิเศษเลยครับ (ทุกคำสั่งต้องมี Manage Server)",
                ephemeral=True,
            )
            return
        embed = discord.Embed(title="🔑 สิทธิ์คำสั่งที่ตั้งไว้", color=discord.Color.blurple())
        for cmd_name, role_ids in all_perms.items():
            if not role_ids:
                continue
            mentions = ", ".join(f"<@&{rid}>" for rid in role_ids)
            embed.add_field(name=f"/{cmd_name}", value=mentions, inline=False)
        if not embed.fields:
            await interaction.response.send_message(
                "ยังไม่มีการตั้งค่าสิทธิ์คำสั่งพิเศษเลยครับ", ephemeral=True
            )
            return
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(CommandPermissions(bot))
