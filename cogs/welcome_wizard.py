"""
cogs/welcome_wizard.py — 🧙 Welcome Designer Wizard
เวอร์ชัน step-by-step ของ /welcome-editor เดิม — เดินเป็นขั้นตอนในข้อความเดียว
(แก้ไขข้อความเดิมไปเรื่อย ๆ ไม่ใช่ modal เดี่ยว) ใช้ schema เดียวกับ welcome.py 100%
ดังนั้น /welcome-editor, /welcome-composite-config ฯลฯ ของเดิมยังใช้ได้ปกติทุกอย่าง
ไม่มีอะไรชนกัน — นี่แค่เป็นอีกทางเข้าเพื่อ UX ที่นำทางชัดกว่า

5 ขั้นตอน: ข้อความ → รูป/ฟอนต์ → สไตล์ → ข้อมูลเพิ่มเติม → พรีวิว/บันทึก
ไม่มีการเขียนลง MongoDB จนกว่าจะกด "✅ บันทึกและใช้งานจริง" ในขั้นตอนสุดท้าย
(เหมือนหลักการ Wallpaper Live Preview เดิมใน welcome.py)
"""

import discord
from discord import app_commands
from discord.ext import commands

import db
from checks import require_permission
from cogs.font import BUILTIN_FONTS, font_autocomplete
from cogs.welcome import build_welcome_message, parse_hex_color

TOTAL_STEPS = 5
STEP_TITLES = {
    1: "📝 ข้อความต้อนรับ",
    2: "🖼️ รูปภาพ & ฟอนต์",
    3: "🎨 ออกแบบสไตล์",
    4: "➕ ข้อมูลเพิ่มเติม",
    5: "👁️ พรีวิว & บันทึก",
}

POSITION_OPTIONS = [
    discord.SelectOption(label="บน", value="top"),
    discord.SelectOption(label="กลาง", value="center", default=True),
    discord.SelectOption(label="ล่าง", value="bottom"),
]


def progress_bar(step: int) -> str:
    return "🟩" * step + "⬜" * (TOTAL_STEPS - step)


class WizardSession:
    """สถานะชั่วคราวของแต่ละคนที่เปิด wizard อยู่ — เก็บใน memory เท่านั้น เคลียร์เมื่อ view timeout"""

    def __init__(self, guild_id: int, editor_id: int, base: dict):
        self.guild_id = guild_id
        self.editor_id = editor_id
        self.step = 1
        self.data = dict(base)  # ทำงานบน copy เสมอ ไม่แตะ DB จริงจนกว่าจะกดบันทึก

    def summary_embed(self) -> discord.Embed:
        d = self.data
        embed = discord.Embed(
            title=f"🧙 Welcome Designer Wizard — {STEP_TITLES[self.step]}",
            description=progress_bar(self.step) + f"  ({self.step}/{TOTAL_STEPS})",
            color=parse_hex_color(d.get("color", "#a0d2eb")),
        )
        embed.add_field(name="หัวข้อ", value=(d.get("title") or "_ยังไม่ตั้ง_")[:200], inline=False)
        embed.add_field(
            name="คำอธิบาย", value=(d.get("description") or "_ยังไม่ตั้ง_")[:200], inline=False
        )
        embed.add_field(
            name="รูปพื้นหลัง / ฟอนต์",
            value=f"{'มีรูป ✅' if d.get('image_url') else 'ยังไม่มีรูป'} • ฟอนต์: `{d.get('font_key') or 'ไม่ใช้ (ไม่วาดทับรูป)'}`",
            inline=False,
        )
        embed.add_field(
            name="สี",
            value=f"หลัก `{d.get('color')}` • ข้อความ `{d.get('text_color', '#ffffff')}` • กรอบ `{d.get('border_color') or '(ไม่มี)'}`",
            inline=False,
        )
        embed.add_field(
            name="ข้อมูลเพิ่มเติม",
            value=(
                f"Author: {'เปิด' if d.get('author_name') else 'ปิด'} • "
                f"Footer: {'เปิด' if d.get('footer_text') else 'ปิด'} • "
                f"Fields: {len(d.get('fields') or [])}/3"
            ),
            inline=False,
        )
        return embed


async def render_step(interaction: discord.Interaction, session: WizardSession, *, from_modal: bool):
    view = STEP_VIEWS[session.step](session)
    embed = session.summary_embed()
    kwargs = {"embed": embed, "view": view}
    if from_modal:
        # modal on_submit ต้อง defer/response ก่อนแล้วค่อย edit ข้อความเดิมผ่าน followup
        await interaction.response.edit_message(**kwargs)
    else:
        await interaction.response.edit_message(**kwargs)


class WizardNavRow(discord.ui.View):
    """ปุ่ม ย้อนกลับ / ถัดไป / ยกเลิก ที่ทุกขั้นตอนมีเหมือนกัน — sub-class เพิ่มปุ่มเฉพาะขั้นของตัวเองได้"""

    def __init__(self, session: WizardSession):
        super().__init__(timeout=420)
        self.session = session

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.session.editor_id:
            await interaction.response.send_message(
                "ใช้ wizard นี้ได้เฉพาะคนที่เปิดเท่านั้นครับ", ephemeral=True
            )
            return False
        return True

    async def go_back(self, interaction: discord.Interaction):
        self.session.step = max(1, self.session.step - 1)
        await render_step(interaction, self.session, from_modal=False)

    async def cancel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🔄 ยกเลิก Wizard แล้ว", description="ไม่มีการบันทึกการเปลี่ยนแปลงใด ๆ", color=discord.Color.red()
        )
        await interaction.response.edit_message(embed=embed, view=None)


# ---------------- Step 1: ข้อความ ----------------

class Step1Modal(discord.ui.Modal, title="📝 ข้อความต้อนรับ"):
    def __init__(self, session: WizardSession):
        super().__init__()
        self.session = session
        self.title_input = discord.ui.TextInput(
            label="หัวข้อ (Title)",
            style=discord.TextStyle.paragraph,
            default=session.data.get("title", ""),
            max_length=256,
        )
        self.desc_input = discord.ui.TextInput(
            label="คำอธิบาย (ใช้ {user} {server_name} {server_membercount} ได้)",
            style=discord.TextStyle.paragraph,
            default=session.data.get("description", ""),
            max_length=1000,
        )
        self.add_item(self.title_input)
        self.add_item(self.desc_input)

    async def on_submit(self, interaction: discord.Interaction):
        self.session.data["title"] = self.title_input.value
        self.session.data["description"] = self.desc_input.value
        self.session.step = 2
        await render_step(interaction, self.session, from_modal=True)


class Step1View(WizardNavRow):
    def __init__(self, session: WizardSession):
        super().__init__(session)

    @discord.ui.button(label="แก้ไขข้อความ", emoji="✏️", style=discord.ButtonStyle.primary, row=0)
    async def edit_text(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(Step1Modal(self.session))

    @discord.ui.button(label="ถัดไป", emoji="➡️", style=discord.ButtonStyle.success, row=1)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.session.step = 2
        await render_step(interaction, self.session, from_modal=False)

    @discord.ui.button(label="ยกเลิก", emoji="✖️", style=discord.ButtonStyle.danger, row=1)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cancel(interaction)


# ---------------- Step 2: รูปภาพ & ฟอนต์ ----------------

class Step2ImageModal(discord.ui.Modal, title="🖼️ รูปภาพพื้นหลัง"):
    def __init__(self, session: WizardSession):
        super().__init__()
        self.session = session
        self.image_input = discord.ui.TextInput(
            label="Image URL / GIF (เว้นว่างได้)",
            default=session.data.get("image_url") or "",
            required=False,
            max_length=500,
        )
        self.add_item(self.image_input)

    async def on_submit(self, interaction: discord.Interaction):
        self.session.data["image_url"] = self.image_input.value or None
        await render_step(interaction, self.session, from_modal=True)


class FontSelect(discord.ui.Select):
    def __init__(self, session: WizardSession):
        self.session = session
        options = [discord.SelectOption(label="ไม่ใช้ฟอนต์ (ใช้รูปตรง ๆ)", value="__none__")]
        for key, info in BUILTIN_FONTS.items():
            options.append(discord.SelectOption(label=info["label"][:100], value=key))
        current = session.data.get("font_key") or "__none__"
        for opt in options:
            opt.default = opt.value == current
        super().__init__(placeholder="เลือกฟอนต์ (custom font พิมพ์ผ่าน /welcome-editor ได้)", options=options, row=1)

    async def callback(self, interaction: discord.Interaction):
        value = self.values[0]
        self.session.data["font_key"] = None if value == "__none__" else value
        await render_step(interaction, self.session, from_modal=False)


class Step2View(WizardNavRow):
    def __init__(self, session: WizardSession):
        super().__init__(session)
        self.add_item(FontSelect(session))

    @discord.ui.button(label="ตั้งรูปภาพ", emoji="🖼️", style=discord.ButtonStyle.primary, row=0)
    async def edit_image(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(Step2ImageModal(self.session))

    @discord.ui.button(label="ย้อนกลับ", emoji="⬅️", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.go_back(interaction)

    @discord.ui.button(label="ถัดไป", emoji="➡️", style=discord.ButtonStyle.success, row=2)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.session.step = 3
        await render_step(interaction, self.session, from_modal=False)

    @discord.ui.button(label="ยกเลิก", emoji="✖️", style=discord.ButtonStyle.danger, row=2)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cancel(interaction)


# ---------------- Step 3: สไตล์ ----------------

class Step3ColorModal(discord.ui.Modal, title="🎨 สีของงานออกแบบ"):
    def __init__(self, session: WizardSession):
        super().__init__()
        self.session = session
        self.color_input = discord.ui.TextInput(
            label="สีหลัก (แถบ embed) เช่น #a0d2eb",
            default=session.data.get("color", "#a0d2eb"),
            max_length=7,
        )
        self.text_color_input = discord.ui.TextInput(
            label="สีข้อความบนรูป composite เช่น #ffffff",
            default=session.data.get("text_color", "#ffffff"),
            max_length=7,
        )
        self.border_color_input = discord.ui.TextInput(
            label="สีกรอบรูป (เว้นว่าง = ไม่มีกรอบ)",
            default=session.data.get("border_color") or "",
            required=False,
            max_length=7,
        )
        self.add_item(self.color_input)
        self.add_item(self.text_color_input)
        self.add_item(self.border_color_input)

    async def on_submit(self, interaction: discord.Interaction):
        self.session.data["color"] = self.color_input.value
        self.session.data["text_color"] = self.text_color_input.value or "#ffffff"
        self.session.data["border_color"] = self.border_color_input.value or None
        await render_step(interaction, self.session, from_modal=True)


class AvatarPositionSelect(discord.ui.Select):
    def __init__(self, session: WizardSession):
        self.session = session
        options = [
            discord.SelectOption(label=f"Avatar: {o.label}", value=o.value)
            for o in POSITION_OPTIONS
        ]
        current = session.data.get("avatar_position", "center")
        for opt, base in zip(options, POSITION_OPTIONS):
            opt.default = base.value == current
        super().__init__(placeholder="ตำแหน่ง Avatar บนรูป", options=options, row=1)

    async def callback(self, interaction: discord.Interaction):
        self.session.data["avatar_position"] = self.values[0]
        await render_step(interaction, self.session, from_modal=False)


class TextPositionSelect(discord.ui.Select):
    def __init__(self, session: WizardSession):
        self.session = session
        options = [
            discord.SelectOption(label=f"ข้อความ: {o.label}", value=o.value)
            for o in POSITION_OPTIONS
        ]
        current = session.data.get("text_position", "bottom")
        for opt, base in zip(options, POSITION_OPTIONS):
            opt.default = base.value == current
        super().__init__(placeholder="ตำแหน่งข้อความบนรูป", options=options, row=2)

    async def callback(self, interaction: discord.Interaction):
        self.session.data["text_position"] = self.values[0]
        await render_step(interaction, self.session, from_modal=False)


class Step3View(WizardNavRow):
    def __init__(self, session: WizardSession):
        super().__init__(session)
        self.add_item(AvatarPositionSelect(session))
        self.add_item(TextPositionSelect(session))

    @discord.ui.button(label="ตั้งสี", emoji="🎨", style=discord.ButtonStyle.primary, row=0)
    async def edit_colors(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(Step3ColorModal(self.session))

    @discord.ui.button(label="ย้อนกลับ", emoji="⬅️", style=discord.ButtonStyle.secondary, row=3)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.go_back(interaction)

    @discord.ui.button(label="ถัดไป", emoji="➡️", style=discord.ButtonStyle.success, row=3)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.session.step = 4
        await render_step(interaction, self.session, from_modal=False)

    @discord.ui.button(label="ยกเลิก", emoji="✖️", style=discord.ButtonStyle.danger, row=3)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cancel(interaction)


# ---------------- Step 4: ข้อมูลเพิ่มเติม (Author / Footer / Fields) ----------------

class Step4Modal(discord.ui.Modal, title="➕ ข้อมูลเพิ่มเติม"):
    def __init__(self, session: WizardSession):
        super().__init__()
        self.session = session
        self.author_input = discord.ui.TextInput(
            label="Author name (เว้นว่าง = ปิด)",
            default=session.data.get("author_name") or "",
            required=False,
            max_length=256,
        )
        self.footer_input = discord.ui.TextInput(
            label="Footer text (เว้นว่าง = ปิด)",
            default=session.data.get("footer_text") or "",
            required=False,
            max_length=256,
        )
        field1 = (session.data.get("fields") or [{}])[0] if session.data.get("fields") else {}
        self.field_name_input = discord.ui.TextInput(
            label="Field #1 — หัวข้อ (เว้นว่าง = ไม่ใส่)",
            default=field1.get("name", ""),
            required=False,
            max_length=100,
        )
        self.field_value_input = discord.ui.TextInput(
            label="Field #1 — ค่า",
            default=field1.get("value", ""),
            required=False,
            max_length=200,
        )
        self.add_item(self.author_input)
        self.add_item(self.footer_input)
        self.add_item(self.field_name_input)
        self.add_item(self.field_value_input)

    async def on_submit(self, interaction: discord.Interaction):
        self.session.data["author_name"] = self.author_input.value or None
        self.session.data["footer_text"] = self.footer_input.value or None
        fields = list(self.session.data.get("fields") or [])
        if self.field_name_input.value:
            entry = {"name": self.field_name_input.value, "value": self.field_value_input.value, "inline": True}
            if fields:
                fields[0] = entry
            else:
                fields.append(entry)
        elif fields:
            fields = fields[1:]  # เคลียร์ field #1 ถ้าลบหัวข้อทิ้ง
        self.session.data["fields"] = fields[:3]
        await render_step(interaction, self.session, from_modal=True)


class Step4View(WizardNavRow):
    @discord.ui.button(label="แก้ข้อมูลเพิ่มเติม", emoji="✏️", style=discord.ButtonStyle.primary, row=0)
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(Step4Modal(self.session))

    @discord.ui.button(label="ย้อนกลับ", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.go_back(interaction)

    @discord.ui.button(label="ไปพรีวิว", emoji="👁️", style=discord.ButtonStyle.success, row=1)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.session.step = 5
        await render_step(interaction, self.session, from_modal=False)

    @discord.ui.button(label="ยกเลิก", emoji="✖️", style=discord.ButtonStyle.danger, row=1)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cancel(interaction)


# ---------------- Step 5: พรีวิว & บันทึก ----------------

class Step5View(WizardNavRow):
    @discord.ui.button(label="ย้อนกลับ", emoji="⬅️", style=discord.ButtonStyle.secondary, row=0)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.go_back(interaction)

    @discord.ui.button(label="รีเฟรชตัวอย่าง", emoji="🔄", style=discord.ButtonStyle.secondary, row=0)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        embed, file, extra_embed = await build_welcome_message(
            self.session.data, interaction.user, self.session.guild_id
        )
        embeds = [embed] + ([extra_embed] if extra_embed else [])
        kwargs = {"content": "👁️ ตัวอย่างจริง (ยังไม่บันทึก):", "embeds": embeds, "ephemeral": True}
        if file:
            kwargs["file"] = file
        await interaction.followup.send(**kwargs)

    @discord.ui.button(label="บันทึกเป็น Preset", emoji="💾", style=discord.ButtonStyle.secondary, row=1)
    async def save_preset(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SavePresetModal(self.session))

    @discord.ui.button(label="✅ บันทึกและใช้งานจริง", style=discord.ButtonStyle.success, row=2)
    async def apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        await db.update_guild_section(self.session.guild_id, "welcome", self.session.data)
        embed = discord.Embed(
            title="✅ บันทึกและใช้งานจริงแล้ว!",
            description="ค่าที่ตั้งไว้ทั้งหมดถูกนำไปใช้กับข้อความต้อนรับแล้วครับ",
            color=discord.Color.green(),
        )
        await interaction.response.edit_message(embed=embed, view=None)

    @discord.ui.button(label="ยกเลิก", emoji="✖️", style=discord.ButtonStyle.danger, row=2)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cancel(interaction)


class SavePresetModal(discord.ui.Modal, title="💾 บันทึกเป็น Preset"):
    name_input = discord.ui.TextInput(label="ชื่อ preset เช่น christmas, ปกติ", max_length=50)

    def __init__(self, session: WizardSession):
        super().__init__()
        self.session = session

    async def on_submit(self, interaction: discord.Interaction):
        await db.save_welcome_preset(self.session.guild_id, self.name_input.value, self.session.data)
        await interaction.response.send_message(
            f"✅ บันทึก preset '{self.name_input.value}' จากค่าที่กำลังออกแบบอยู่แล้ว (ยังไม่ apply เป็นค่าใช้งานจริง)",
            ephemeral=True,
        )


STEP_VIEWS = {1: Step1View, 2: Step2View, 3: Step3View, 4: Step4View, 5: Step5View}


class WelcomeWizard(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="welcome-wizard",
        description="🧙 ออกแบบข้อความต้อนรับแบบ step-by-step ทีละขั้น (แอดมินเท่านั้น)",
    )
    @require_permission()
    async def welcome_wizard(self, interaction: discord.Interaction):
        cfg = await db.get_guild_config(interaction.guild_id)
        session = WizardSession(interaction.guild_id, interaction.user.id, cfg["welcome"])
        view = Step1View(session)
        await interaction.response.send_message(embed=session.summary_embed(), view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(WelcomeWizard(bot))
