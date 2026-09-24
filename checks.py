"""
checks.py — 🔑 ตัวเช็คสิทธิ์กลางที่ทุกคำสั่งของบอทเรียกใช้ (แทน app_commands.checks.has_permissions เดิม)

หลักการ:
- คนที่มีสิทธิ์ Manage Server ใช้ได้ทุกคำสั่งเสมอ (bypass เหมือนเดิม)
- แอดมินปลดล็อกให้ยศอื่นใช้คำสั่งเฉพาะได้ผ่าน /cmdperm-grant (เก็บใน MongoDB แยกตาม guild)
- ถ้ายังไม่ตั้งค่าอะไรไว้เลยสำหรับคำสั่งนั้น (ไม่มียศไหนถูกปลดล็อก) จะต้องมี Manage Server เท่านั้น
  (พฤติกรรมเดิมก่อนมีระบบนี้ ไม่กระทบของเก่า)
"""

import discord
from discord import app_commands

import db
import style


def require_permission():
    """ใช้แทน @app_commands.checks.has_permissions(...) เดิมทุกจุด"""

    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            await interaction.response.send_message(
                embed=style.warn("คำสั่งนี้ใช้ในเซิร์ฟเวอร์เท่านั้นน้า 🏠", system="cmdperms"), ephemeral=True
            )
            return False

        if interaction.user.guild_permissions.manage_guild:
            return True

        command_name = interaction.command.qualified_name if interaction.command else None
        if command_name is None:
            return False

        allowed_role_ids = set(await db.get_allowed_roles(interaction.guild_id, command_name))
        if not allowed_role_ids:
            await interaction.response.send_message(
                embed=style.warn(
                    "คำสั่งนี้ต้องมีสิทธิ์ **Manage Server** หรือได้รับอนุญาตจากแอดมินน้า 🎀\n"
                    "(แอดมินให้สิทธิ์ยศอื่นได้ผ่าน `/cmdperm-grant`)",
                    title="ยังใช้คำสั่งนี้ไม่ได้น้า", system="cmdperms",
                ),
                ephemeral=True,
            )
            return False

        user_role_ids = {r.id for r in interaction.user.roles}
        if user_role_ids & allowed_role_ids:
            return True

        await interaction.response.send_message(
            embed=style.warn(
                "ยศของคุณยังไม่ได้รับอนุญาตให้ใช้คำสั่งนี้ ลองติดต่อแอดมินถ้าต้องการสิทธิ์เพิ่มน้า 💌",
                title="ยังใช้คำสั่งนี้ไม่ได้น้า", system="cmdperms",
            ),
            ephemeral=True,
        )
        return False

    return app_commands.check(predicate)
