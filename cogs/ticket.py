"""
cogs/ticket.py — 🎫 Ticket System
เปิดตั๋วขอความช่วยเหลือส่วนตัว: กดปุ่มในแผงแล้วบอทสร้างห้องส่วนตัวให้คุยกับทีมงาน
"""

import asyncio

import discord
from discord import app_commands
from discord.ext import commands

import db
import style
from checks import require_permission
from cogs.welcome import render_variables, parse_hex_color


def build_ticket_panel_embed(cfg: dict) -> discord.Embed:
    embed = discord.Embed(
        title=cfg.get("title", "🎫 เปิดตั๋วขอความช่วยเหลือ"),
        description=cfg.get("description", "กดปุ่มด้านล่างเพื่อเปิดห้องส่วนตัวคุยกับทีมงาน")
        + f"\n{style.DIVIDER}",
        color=parse_hex_color(cfg.get("color", "#5865f2")),
    )
    embed.set_footer(text=f"{style.SYSTEM_ICON['ticket']} {style.BRAND} • ทีมงานจะเห็นตั๋วที่คุณเปิดเท่านั้น")
    return embed


class TicketPanelView(discord.ui.View):
    """View ถาวร (persistent) ที่ติดกับแผงเปิดตั๋ว"""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="เปิดตั๋ว",
        emoji="🎫",
        style=discord.ButtonStyle.primary,
        custom_id="beluga:ticket:open",
    )
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        member = interaction.user
        cfg = (await db.get_guild_config(guild.id))["ticket"]

        category_id = cfg.get("category_id")
        if not category_id:
            await interaction.followup.send(
                "⚠️ ยังไม่ได้ตั้งค่าระบบตั๋ว กรุณาแจ้งแอดมินให้ใช้ `/ticket-setup` ก่อน", ephemeral=True
            )
            return
        category = guild.get_channel(category_id)
        if category is None:
            await interaction.followup.send(
                "⚠️ หมวดหมู่ตั๋วถูกลบไปแล้ว กรุณาแจ้งแอดมิน", ephemeral=True
            )
            return

        # กันเปิดตั๋วซ้ำหลายอันพร้อมกัน
        existing_channel_id = await db.get_open_ticket_channel_id(guild.id, member.id)
        if existing_channel_id:
            existing_channel = guild.get_channel(existing_channel_id)
            if existing_channel:
                await interaction.followup.send(
                    f"คุณมีตั๋วที่เปิดอยู่แล้วที่ {existing_channel.mention} ครับ", ephemeral=True
                )
                return
            # ห้องถูกลบไปแล้วแต่ record ยังค้าง — ปิด record เก่าแล้วให้เปิดใหม่ได้
            await db.close_ticket_record(existing_channel_id)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_channels=True
            ),
        }
        for role_id in cfg.get("support_role_ids", []):
            role = guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True
                )

        safe_name = "".join(c for c in member.name.lower() if c.isalnum() or c in "-_")[:20] or "user"
        try:
            channel = await category.create_text_channel(
                f"ticket-{safe_name}",
                overwrites=overwrites,
                reason=f"เปิดตั๋วโดย {member}",
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "⚠️ บอทไม่มีสิทธิ์สร้างห้อง เช็ค **Manage Channels** ในหมวดหมู่นั้นด้วยครับ", ephemeral=True
            )
            return

        await db.create_ticket_record(guild.id, channel.id, member.id)

        welcome_text = render_variables(
            cfg.get("welcome_text", "สวัสดีครับ {user} ทีมงานจะเข้ามาช่วยเหลือเร็ว ๆ นี้"),
            member,
            use_mention=True,
        )
        embed = discord.Embed(
            title="🎫 ตั๋วนี้เปิดแล้ว", description=f"{welcome_text}\n{style.DIVIDER}", color=discord.Color.blurple()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"{style.SYSTEM_ICON['ticket']} {style.BRAND} • เปิดโดย {member.display_name}")
        await channel.send(embed=embed, view=TicketCloseView())

        await interaction.followup.send(f"✅ เปิดตั๋วแล้วที่ {channel.mention}", ephemeral=True)


class TicketCloseView(discord.ui.View):
    """View ถาวรสำหรับปุ่มปิดตั๋วในห้องตั๋ว"""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="ปิดตั๋ว",
        emoji="🔒",
        style=discord.ButtonStyle.danger,
        custom_id="beluga:ticket:close",
    )
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        cfg = (await db.get_guild_config(guild.id))["ticket"]
        support_role_ids = set(cfg.get("support_role_ids", []))
        member_role_ids = {r.id for r in interaction.user.roles}

        is_support = bool(support_role_ids & member_role_ids)
        is_admin = interaction.user.guild_permissions.manage_guild
        if not (is_support or is_admin):
            await interaction.response.send_message(
                "⛔ เฉพาะทีมงานหรือแอดมินเท่านั้นที่ปิดตั๋วได้ครับ", ephemeral=True
            )
            return

        await interaction.response.send_message(
            "🔒 ตั๋วนี้ถูกปิดแล้ว ห้องจะถูกลบในอีก 5 วินาที..."
        )
        await db.close_ticket_record(interaction.channel_id)
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete(reason=f"ตั๋วถูกปิดโดย {interaction.user}")
        except discord.Forbidden:
            pass


class Ticket(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # ลงทะเบียน persistent view ตอนบอทเริ่มทำงาน เพื่อให้ปุ่มยังกดได้แม้บอท restart
        bot.add_view(TicketPanelView())
        bot.add_view(TicketCloseView())

    @app_commands.command(
        name="ticket-setup",
        description="ตั้งค่าระบบตั๋ว: หมวดหมู่ที่จะสร้างห้องตั๋ว + ยศทีมงานที่เห็นตั๋วได้ (แอดมินเท่านั้น)",
    )
    @require_permission()
    @app_commands.describe(
        category="หมวดหมู่ที่จะสร้างห้องตั๋วใหม่ทุกครั้ง",
        support_role="ยศทีมงานที่จะเห็น/ตอบตั๋วได้ (เรียกคำสั่งนี้หลายครั้งเพื่อเพิ่มได้หลายยศ)",
    )
    async def ticket_setup(
        self,
        interaction: discord.Interaction,
        category: discord.CategoryChannel,
        support_role: discord.Role,
    ):
        cfg = await db.get_guild_config(interaction.guild_id)
        support_role_ids = cfg["ticket"].get("support_role_ids", [])
        if support_role.id not in support_role_ids:
            support_role_ids.append(support_role.id)
        await db.update_guild_section(
            interaction.guild_id,
            "ticket",
            {"category_id": category.id, "support_role_ids": support_role_ids},
        )
        await interaction.response.send_message(
            f"✅ ตั้งค่าตั๋วแล้ว: หมวดหมู่ **{category.name}**, ยศทีมงาน {support_role.mention} "
            f"(รวมตอนนี้ {len(support_role_ids)} ยศ) — ใช้ `/ticket-setup` ซ้ำเพื่อเพิ่มยศอื่นได้",
            ephemeral=True,
        )

    @app_commands.command(
        name="ticket-remove-support-role", description="เอายศทีมงานออกจากระบบตั๋ว (แอดมินเท่านั้น)"
    )
    @require_permission()
    async def ticket_remove_support_role(self, interaction: discord.Interaction, role: discord.Role):
        cfg = await db.get_guild_config(interaction.guild_id)
        support_role_ids = cfg["ticket"].get("support_role_ids", [])
        if role.id in support_role_ids:
            support_role_ids.remove(role.id)
        await db.update_guild_section(
            interaction.guild_id, "ticket", {"support_role_ids": support_role_ids}
        )
        await interaction.response.send_message(f"🗑️ เอา {role.mention} ออกจากทีมงานตั๋วแล้ว", ephemeral=True)

    @app_commands.command(name="ticket-panel", description="โพสต์แผงเปิดตั๋วในห้องนี้ (แอดมินเท่านั้น)")
    @require_permission()
    async def ticket_panel(self, interaction: discord.Interaction):
        cfg = await db.get_guild_config(interaction.guild_id)
        if not cfg["ticket"].get("category_id"):
            await interaction.response.send_message(
                "⚠️ ยังไม่ได้ตั้งค่าระบบตั๋ว ใช้ `/ticket-setup` ก่อน", ephemeral=True
            )
            return
        embed = build_ticket_panel_embed(cfg["ticket"])
        await interaction.channel.send(embed=embed, view=TicketPanelView())
        await db.update_guild_section(
            interaction.guild_id, "ticket", {"panel_channel_id": interaction.channel_id}
        )
        await interaction.response.send_message("✅ โพสต์แผงเปิดตั๋วแล้ว", ephemeral=True)

    @app_commands.command(
        name="ticket-editor", description="แก้ข้อความ/สีของแผงเปิดตั๋วและข้อความต้อนรับในห้องตั๋ว (แอดมินเท่านั้น)"
    )
    @require_permission()
    @app_commands.describe(
        title="หัวข้อแผงเปิดตั๋ว",
        description="คำอธิบายแผงเปิดตั๋ว",
        color="สี hex ของแผง",
        welcome_text="ข้อความต้อนรับในห้องตั๋วที่เปิดใหม่ (ใช้ {user} ได้)",
    )
    async def ticket_editor(
        self,
        interaction: discord.Interaction,
        title: str = None,
        description: str = None,
        color: str = None,
        welcome_text: str = None,
    ):
        updates = {}
        if title is not None:
            updates["title"] = title
        if description is not None:
            updates["description"] = description
        if color is not None:
            updates["color"] = color
        if welcome_text is not None:
            updates["welcome_text"] = welcome_text
        if not updates:
            await interaction.response.send_message("⚠️ ใส่พารามิเตอร์อย่างน้อย 1 อย่าง", ephemeral=True)
            return
        await db.update_guild_section(interaction.guild_id, "ticket", updates)
        await interaction.response.send_message(
            f"✅ อัปเดตแล้ว ({len(updates)} รายการ) ใช้ `/ticket-panel` เพื่อโพสต์แผงใหม่ให้เห็นผล",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Ticket(bot))
