"""
cogs/permissions.py — 🔑 Permission Manager
ตั้งสิทธิ์ยศในห้องต่าง ๆ ผ่านคำสั่งเดียว ไม่ต้องเข้าไปตั้งทีละห้องใน Discord Server Settings
- /permission-set: ปรับทั้งเซิร์ฟ หรือเฉพาะหมวดหมู่เดียว
- /permission-set-bulk: เลือกได้หลายหมวดหมู่พร้อมกันผ่าน dropdown
"""

import discord
from discord import app_commands
from discord.ext import commands

from checks import require_permission

# Thai label -> ชื่อ attribute ของ discord.PermissionOverwrite
PERMISSION_MAP = {
    "ดูห้อง": "view_channel",
    "ส่งข้อความ": "send_messages",
    "อ่านประวัติข้อความ": "read_message_history",
    "แนบไฟล์": "attach_files",
    "ฝังลิงก์ (embed)": "embed_links",
    "ใช้อีโมจิภายนอก": "use_external_emojis",
    "เพิ่มรีแอกชัน": "add_reactions",
    "จัดการข้อความ": "manage_messages",
    "สร้างเธรด": "create_public_threads",
    "กล่าวถึง @everyone": "mention_everyone",
    "เชื่อมต่อห้องเสียง": "connect",
    "พูดในห้องเสียง": "speak",
}

VALUE_MAP = {"allow": True, "deny": False, "reset": None}


class BulkCategorySelectView(discord.ui.View):
    """เลือกได้หลายหมวดหมู่พร้อมกัน (สูงสุด 25) แล้วกดยืนยันทีเดียว — ถ้าไม่เลือกเลยแล้วกดยืนยัน = ทั้งเซิร์ฟ"""

    def __init__(self, role: discord.Role, permission_key: str, bool_value, editor_id: int):
        super().__init__(timeout=120)
        self.role = role
        self.permission_key = permission_key
        self.bool_value = bool_value
        self.editor_id = editor_id
        self.selected_categories: list = []

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.editor_id:
            await interaction.response.send_message(
                "ใช้ได้เฉพาะคนที่สั่งคำสั่งนี้เท่านั้นครับ", ephemeral=True
            )
            return False
        return True

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        channel_types=[discord.ChannelType.category],
        placeholder="เลือกหมวดหมู่ (เลือกได้หลายอัน สูงสุด 25) — ไม่เลือก = ทั้งเซิร์ฟ",
        min_values=0,
        max_values=25,
    )
    async def select_categories(
        self, interaction: discord.Interaction, select: discord.ui.ChannelSelect
    ):
        self.selected_categories = select.values
        names = ", ".join(c.name for c in self.selected_categories) or "(ยังไม่เลือก = ทั้งเซิร์ฟ)"
        await interaction.response.edit_message(
            content=f"เลือกไว้: {names}\nกด **ยืนยันตั้งค่า** เมื่อพร้อม", view=self
        )

    @discord.ui.button(label="ยืนยันตั้งค่า", emoji="✅", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        if self.selected_categories:
            channels = []
            for partial_cat in self.selected_categories:
                full_cat = guild.get_channel(partial_cat.id)
                if full_cat is not None:
                    channels.extend(full_cat.channels)
        else:
            channels = guild.channels

        updated, failed = 0, 0
        for ch in channels:
            try:
                overwrite = ch.overwrites_for(self.role)
                setattr(overwrite, self.permission_key, self.bool_value)
                await ch.set_permissions(
                    self.role,
                    overwrite=overwrite,
                    reason=f"ตั้งผ่าน /permission-set-bulk โดย {interaction.user}",
                )
                updated += 1
            except (discord.Forbidden, discord.HTTPException):
                failed += 1

        scope_text = (
            f"**{len(self.selected_categories)} หมวดหมู่** ที่เลือก" if self.selected_categories else "**ทั้งเซิร์ฟ**"
        )
        result = f"✅ ตั้งสิทธิ์ให้ {self.role.mention} ใน {scope_text} สำเร็จ **{updated} ห้อง**"
        if failed:
            result += f"\n⚠️ ล้มเหลว {failed} ห้อง — เช็คสิทธิ์ **Manage Channels** ของบอท"

        for item in self.children:
            item.disabled = True
        await interaction.edit_original_response(content=result, view=self)


class Permissions(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="permission-set",
        description="ตั้งสิทธิ์ของยศในห้องต่างๆ ทั้งเซิร์ฟหรือเฉพาะหมวดหมู่ (แอดมินเท่านั้น)",
    )
    @require_permission()
    @app_commands.describe(
        role="ยศที่จะตั้งสิทธิ์",
        permission="สิทธิ์ที่จะปรับ",
        value="อนุญาต / ปฏิเสธ / รีเซ็ตกลับเป็นค่าเริ่มต้น",
        category="ถ้าระบุ จะปรับเฉพาะห้องในหมวดหมู่นี้เท่านั้น (ไม่ระบุ = ปรับทั้งเซิร์ฟ)",
    )
    @app_commands.choices(
        permission=[app_commands.Choice(name=k, value=v) for k, v in PERMISSION_MAP.items()],
        value=[
            app_commands.Choice(name="✅ อนุญาต", value="allow"),
            app_commands.Choice(name="❌ ปฏิเสธ", value="deny"),
            app_commands.Choice(name="🔄 รีเซ็ต (ค่าเริ่มต้น)", value="reset"),
        ],
    )
    async def permission_set(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        permission: app_commands.Choice[str],
        value: app_commands.Choice[str],
        category: discord.CategoryChannel = None,
    ):
        await interaction.response.defer(ephemeral=True)

        channels = category.channels if category else interaction.guild.channels
        bool_value = VALUE_MAP[value.value]

        updated, failed = 0, 0
        for ch in channels:
            try:
                overwrite = ch.overwrites_for(role)
                setattr(overwrite, permission.value, bool_value)
                await ch.set_permissions(
                    role, overwrite=overwrite, reason=f"ตั้งผ่าน /permission-set โดย {interaction.user}"
                )
                updated += 1
            except (discord.Forbidden, discord.HTTPException):
                failed += 1

        scope_text = f"หมวดหมู่ **{category.name}**" if category else "**ทั้งเซิร์ฟ**"
        result = f"✅ ตั้งสิทธิ์ให้ {role.mention} ใน {scope_text} สำเร็จ **{updated} ห้อง**"
        if failed:
            result += f"\n⚠️ ล้มเหลว {failed} ห้อง — เช็คว่า role ของบอทมีสิทธิ์ **Manage Channels** ในห้องนั้นไหม"
        await interaction.followup.send(result, ephemeral=True)

    @app_commands.command(
        name="permission-set-bulk",
        description="ตั้งสิทธิ์ยศได้หลายหมวดหมู่พร้อมกันในคำสั่งเดียว (แอดมินเท่านั้น)",
    )
    @require_permission()
    @app_commands.describe(
        role="ยศที่จะตั้งสิทธิ์",
        permission="สิทธิ์ที่จะปรับ",
        value="อนุญาต / ปฏิเสธ / รีเซ็ตกลับเป็นค่าเริ่มต้น",
    )
    @app_commands.choices(
        permission=[app_commands.Choice(name=k, value=v) for k, v in PERMISSION_MAP.items()],
        value=[
            app_commands.Choice(name="✅ อนุญาต", value="allow"),
            app_commands.Choice(name="❌ ปฏิเสธ", value="deny"),
            app_commands.Choice(name="🔄 รีเซ็ต (ค่าเริ่มต้น)", value="reset"),
        ],
    )
    async def permission_set_bulk(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        permission: app_commands.Choice[str],
        value: app_commands.Choice[str],
    ):
        bool_value = VALUE_MAP[value.value]
        view = BulkCategorySelectView(role, permission.value, bool_value, interaction.user.id)
        await interaction.response.send_message(
            "เลือกหมวดหมู่ที่จะปรับจากเมนูด้านล่าง (เลือกได้หลายอัน) แล้วกด **ยืนยันตั้งค่า**\n"
            "ไม่เลือกเลยแล้วกดยืนยัน = ปรับทั้งเซิร์ฟ",
            view=view,
            ephemeral=True,
        )

    @app_commands.command(
        name="permission-view", description="ดูว่ายศนี้มีสิทธิ์พิเศษ (override) ในห้องไหนบ้าง"
    )
    @require_permission()
    async def permission_view(self, interaction: discord.Interaction, role: discord.Role):
        await interaction.response.defer(ephemeral=True)
        lines = []
        for ch in interaction.guild.channels:
            overwrite = ch.overwrites.get(role)
            if overwrite is None:
                continue
            allows, denies = overwrite.pair()
            allow_names = [p for p, v in allows if v]
            deny_names = [p for p, v in denies if v]
            if allow_names or deny_names:
                parts = []
                if allow_names:
                    parts.append("✅ " + ", ".join(allow_names[:5]))
                if deny_names:
                    parts.append("❌ " + ", ".join(deny_names[:5]))
                lines.append(f"**#{ch.name}** — {' | '.join(parts)}")

        if not lines:
            await interaction.followup.send(
                f"ยศ {role.mention} ยังไม่มีสิทธิ์พิเศษ (override) ในห้องไหนเลย", ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"🔑 สิทธิ์พิเศษของ {role.name}",
            description="\n".join(lines[:25]),
            color=role.color,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Permissions(bot))
