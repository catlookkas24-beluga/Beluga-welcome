"""
cogs/welcome.py — 🎨 Welcome Designer
แอดมินพิมพ์ /welcome-editor แล้วบอทเด้ง Modal ให้กรอก title/description/hex color/รูป/ฟอนต์
รองรับตัวแปร {user} {user_name} {server_name} {server_membercount} แทรกในข้อความได้เลย

ถ้าใส่ "ฟอนต์" ไว้ด้วย: บอทจะดาวน์โหลดรูปจาก Main Image URL มาใช้เป็นพื้นหลัง
วาด avatar วงกลม + ข้อความ Title ทับด้วยฟอนต์ที่เลือก แล้วใช้รูปที่เรนเดอร์นี้แทน image ปกติ
ถ้าเว้นว่างฟอนต์ไว้ ระบบจะทำงานแบบเดิมทุกอย่าง (ใช้ Main Image URL ตรง ๆ)
"""

import asyncio
import io
import random

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont

import db
import style
from checks import require_permission
from cogs.font import load_font_bytes, parse_hex_color as parse_hex_rgba


def render_variables(text: str, member: discord.Member, use_mention: bool = True) -> str:
    if not text:
        return ""
    user_value = member.mention if use_mention else member.display_name
    return (
        text.replace("{user_name}", member.display_name)
        .replace("{user}", user_value)
        .replace("{server_name}", member.guild.name)
        .replace("{server_membercount}", str(member.guild.member_count))
    )


def parse_hex_color(hex_str: str) -> discord.Color:
    try:
        hex_str = hex_str.strip().lstrip("#")
        return discord.Color(int(hex_str, 16))
    except (ValueError, AttributeError):
        return discord.Color(style.DEFAULT_COLOR)


async def fetch_image_bytes(url: str) -> bytes | None:
    """โหลดรูปจาก URL มาเป็น bytes เอง (ตามด้วย redirect ได้ ต่างจากการฝัง URL ตรงใน embed
    ที่ Discord ต้องการไฟล์ตรง ๆ เท่านั้น) คืนค่า None ถ้าโหลดไม่สำเร็จ"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return None
                return await resp.read()
    except Exception:
        return None


def _compute_position(position: str, canvas_size: tuple, box_size: tuple) -> tuple:
    canvas_w, canvas_h = canvas_size
    box_w, box_h = box_size
    x = (canvas_w - box_w) // 2
    if position == "top":
        y = int(canvas_h * 0.08)
    elif position == "bottom":
        y = canvas_h - box_h - int(canvas_h * 0.08)
    else:
        y = (canvas_h - box_h) // 2
    return (x, y)


def render_avatar_text_on_background(
    background_bytes: bytes,
    avatar_bytes: bytes | None,
    font_bytes: bytes,
    text: str,
    text_color: tuple = (255, 255, 255, 255),
    font_size: int = 48,
    avatar_size: int = 128,
    avatar_position: str = "center",
    text_position: str = "bottom",
    border_color: tuple = None,
    border_width: int = 0,
) -> bytes:
    """วาด avatar วงกลม + ข้อความ ทับบนรูปพื้นหลัง — ปรับตำแหน่ง/ขนาด/กรอบได้ คืนค่าเป็น PNG bytes"""
    bg = Image.open(io.BytesIO(background_bytes)).convert("RGBA")
    bg_w, bg_h = bg.size

    if avatar_bytes:
        avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((avatar_size, avatar_size))
        mask = Image.new("L", (avatar_size, avatar_size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, avatar_size, avatar_size), fill=255)
        avatar.putalpha(mask)
        avatar_pos = _compute_position(avatar_position, (bg_w, bg_h), (avatar_size, avatar_size))
        bg.paste(avatar, avatar_pos, avatar)

    draw = ImageDraw.Draw(bg)
    font_obj = ImageFont.truetype(io.BytesIO(font_bytes), font_size)
    bbox = draw.textbbox((0, 0), text, font=font_obj)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    text_x, text_y = _compute_position(text_position, (bg_w, bg_h), (text_w, text_h))
    draw.text((text_x - bbox[0], text_y - bbox[1]), text, font=font_obj, fill=text_color)

    if border_width > 0 and border_color:
        for i in range(border_width):
            draw.rectangle([(i, i), (bg_w - 1 - i, bg_h - 1 - i)], outline=border_color)

    buf = io.BytesIO()
    bg.save(buf, format="PNG")
    return buf.getvalue()


def build_welcome_embed(cfg: dict, member: discord.Member) -> discord.Embed:
    embed = discord.Embed(
        # Discord ไม่ resolve mention ในช่อง title/footer/author เลยใช้ display_name แทน
        # กันโชว์เป็นรหัสดิบ <@id> เหมือนระบบเก่า
        title=render_variables(cfg.get("title", ""), member, use_mention=False),
        description=render_variables(cfg.get("description", ""), member, use_mention=True),
        color=parse_hex_color(cfg.get("color", "#FF9EC4")),
    )
    if cfg.get("image_url"):
        embed.set_image(url=cfg["image_url"])
    embed.set_thumbnail(url=member.display_avatar.url)

    if cfg.get("author_name"):
        author_kwargs = {"name": render_variables(cfg["author_name"], member, use_mention=False)}
        if cfg.get("author_icon_url"):
            author_kwargs["icon_url"] = cfg["author_icon_url"]
        embed.set_author(**author_kwargs)

    if cfg.get("footer_text"):
        footer_kwargs = {"text": render_variables(cfg["footer_text"], member, use_mention=False)}
        if cfg.get("footer_icon_url"):
            footer_kwargs["icon_url"] = cfg["footer_icon_url"]
        embed.set_footer(**footer_kwargs)
    else:
        embed.set_footer(text=f"{style.SYSTEM_ICON['welcome']} {style.BRAND}")

    for field in cfg.get("fields", [])[:3]:
        embed.add_field(
            name=render_variables(field.get("name", ""), member, use_mention=False),
            value=render_variables(field.get("value", ""), member, use_mention=False),
            inline=field.get("inline", True),
        )

    return embed


def build_extra_embed(cfg: dict, member: discord.Member) -> discord.Embed | None:
    """📨 Multi-Embed — embed ที่สองต่อท้าย embed หลัก (เช่น แยกกฎ/ลิงก์ห้องสำคัญ)
    คืนค่า None ถ้าไม่ได้ตั้ง extra_embed_title ไว้"""
    if not cfg.get("extra_embed_title"):
        return None
    return discord.Embed(
        title=render_variables(cfg["extra_embed_title"], member, use_mention=False),
        description=render_variables(cfg.get("extra_embed_description", ""), member, use_mention=True),
        color=parse_hex_color(cfg.get("color", "#FF9EC4")),
    )


async def build_welcome_message(
    cfg: dict, member: discord.Member, guild_id: int
) -> tuple[discord.Embed, "discord.File | None", "discord.Embed | None"]:
    """สร้าง embed ต้อนรับ — ถ้าตั้งฟอนต์ไว้ด้วย จะพยายามเรนเดอร์ avatar+ข้อความทับพื้นหลังให้
    ถ้าเรนเดอร์ไม่สำเร็จ (โหลดรูป/ฟอนต์ไม่ได้) จะ fallback ไปใช้ Main Image URL แบบปกติเงียบ ๆ

    🎲 Random Message System: ถ้ามี image_urls (หลายรูป) ตั้งไว้ จะสุ่มเลือก 1 รูปมาใช้ทุกครั้ง
    แทนที่ image_url เดี่ยว (ทำงานร่วมกับฟอนต์ composite ได้ปกติ เพราะแค่สุ่มว่าจะใช้รูปไหนเป็นพื้นหลัง)

    📨 คืนค่า extra_embed (embed ที่สอง) มาด้วย ถ้าตั้ง Multi-Embed ไว้"""
    render_cfg = dict(cfg)
    image_urls = cfg.get("image_urls") or []
    if image_urls:
        render_cfg["image_url"] = random.choice(image_urls)

    embed = build_welcome_embed(render_cfg, member)
    extra_embed = build_extra_embed(render_cfg, member)
    file = None

    font_key = render_cfg.get("font_key")
    image_url = render_cfg.get("image_url")
    if font_key and image_url:
        bg_bytes = await fetch_image_bytes(image_url)
        if bg_bytes:
            loaded_font = await load_font_bytes(guild_id, font_key)
            if loaded_font:
                font_bytes, _ = loaded_font
                avatar_bytes = None
                if render_cfg.get("avatar_enabled", True):
                    try:
                        avatar_bytes = await member.display_avatar.replace(size=256).read()
                    except Exception:
                        avatar_bytes = None
                text = render_variables(render_cfg.get("title", ""), member, use_mention=False)
                border_color_hex = render_cfg.get("border_color")
                border_rgba = parse_hex_rgba(border_color_hex) if border_color_hex else None
                text_color_hex = render_cfg.get("text_color", "#ffffff")
                text_rgba = parse_hex_rgba(text_color_hex) if text_color_hex else (255, 255, 255, 255)
                try:
                    image_bytes = await asyncio.to_thread(render_avatar_text_on_background, 
                        bg_bytes,
                        avatar_bytes,
                        font_bytes,
                        text,
                        text_color=text_rgba,
                        avatar_size=render_cfg.get("avatar_size", 128),
                        avatar_position=render_cfg.get("avatar_position", "center"),
                        text_position=render_cfg.get("text_position", "bottom"),
                        border_color=border_rgba,
                        border_width=render_cfg.get("border_width", 0),
                    )
                    file = discord.File(io.BytesIO(image_bytes), filename="welcome_composite.png")
                    embed.set_image(url="attachment://welcome_composite.png")
                except Exception:
                    file = None  # เรนเดอร์พัง — ปล่อยให้ embed ใช้ image_url ปกติต่อไป (ตั้งไว้แล้วด้านบน)

    return embed, file, extra_embed


class WelcomeEditorModal(discord.ui.Modal, title="🎨 Welcome Designer"):
    def __init__(self, current: dict):
        super().__init__()
        self.title_input = discord.ui.TextInput(
            label="Title",
            style=discord.TextStyle.paragraph,
            default=current.get("title", ""),
            max_length=256,
        )
        self.description_input = discord.ui.TextInput(
            label="Description",
            style=discord.TextStyle.paragraph,
            default=current.get("description", ""),
            max_length=1000,
        )
        self.color_input = discord.ui.TextInput(
            label="Hex Color (เช่น #FF9EC4)",
            default=current.get("color", "#FF9EC4"),
            max_length=7,
        )
        self.image_input = discord.ui.TextInput(
            label="Main Image URL / GIF (เว้นว่างได้)",
            default=current.get("image_url") or "",
            required=False,
            max_length=500,
        )
        self.font_input = discord.ui.TextInput(
            label="ฟอนต์ (ไม่บังคับ) ดูชื่อจาก /font-list",
            placeholder="เช่น mali, pattaya (เว้นว่าง = ไม่วาดทับรูป)",
            default=current.get("font_key") or "",
            required=False,
            max_length=100,
        )
        for item in (
            self.title_input,
            self.description_input,
            self.color_input,
            self.image_input,
            self.font_input,
        ):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        # 🖼️ Wallpaper Live Preview — ยังไม่เซฟลง DB ทันที เก็บไว้ใน view ชั่วคราวก่อน
        # ให้แอดมินเลือกเองว่าจะ Apply จริงหรือ Cancel ทิ้ง
        cfg = await db.get_guild_config(interaction.guild_id)
        pending_data = dict(cfg["welcome"])  # เก็บฟีเจอร์เดิม (author/footer/fields ฯลฯ) ไว้ครบ
        pending_data.update(
            {
                "title": self.title_input.value,
                "description": self.description_input.value,
                "color": self.color_input.value,
                "image_url": self.image_input.value or None,
                "font_key": self.font_input.value.strip() or None,
            }
        )
        embed, file, extra_embed = await build_welcome_message(
            pending_data, interaction.user, interaction.guild_id
        )
        view = WallpaperPreviewView(interaction.guild_id, interaction.user.id, pending_data)
        embeds = [embed] + ([extra_embed] if extra_embed else [])
        kwargs = {
            "content": "🖼️ นี่คือตัวอย่าง — **ยังไม่ถูกบันทึก** จนกว่าจะกด \"นำไปใช้จริง\"",
            "embeds": embeds,
            "view": view,
            "ephemeral": True,
        }
        if file:
            kwargs["file"] = file
        await interaction.followup.send(**kwargs)


class WallpaperPreviewView(discord.ui.View):
    """ปุ่มควบคุมของระบบ Wallpaper Live Preview — พรีวิวซ้ำได้/Apply/คืนค่าเดิม"""

    def __init__(self, guild_id: int, editor_id: int, pending_data: dict):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.editor_id = editor_id
        self.pending_data = pending_data

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.editor_id:
            await interaction.response.send_message(
                embed=style.warn("ปุ่มนี้ใช้ได้เฉพาะคนที่เปิดหน้าต่างแก้ไขนี้เท่านั้นครับ"), ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="พรีวิวตัวอย่าง", emoji="👁️", style=discord.ButtonStyle.secondary)
    async def preview(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        embed, file, extra_embed = await build_welcome_message(
            self.pending_data, interaction.user, self.guild_id
        )
        embeds = [embed] + ([extra_embed] if extra_embed else [])
        kwargs = {"content": "👁️ ตัวอย่าง (ยังไม่บันทึก):", "embeds": embeds, "ephemeral": True}
        if file:
            kwargs["file"] = file
        await interaction.followup.send(**kwargs)

    @discord.ui.button(label="นำไปใช้จริง", emoji="✅", style=discord.ButtonStyle.success)
    async def apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        await db.update_guild_section(self.guild_id, "welcome", self.pending_data)
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="✅ บันทึกและนำไปใช้จริงแล้ว!", view=self
        )

    @discord.ui.button(label="คืนค่าเดิม", emoji="🔄", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="🔄 ยกเลิกแล้ว ไม่มีการบันทึกการเปลี่ยนแปลงใด ๆ", embed=None, view=self
        )


class Welcome(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="welcome-editor", description="เปิดหน้าต่างแก้ไข embed ต้อนรับ (แอดมินเท่านั้น)"
    )
    @require_permission()
    async def welcome_editor(self, interaction: discord.Interaction):
        cfg = await db.get_guild_config(interaction.guild_id)
        await interaction.response.send_modal(WelcomeEditorModal(cfg["welcome"]))

    @app_commands.command(
        name="welcome-set-channel", description="ตั้งห้องที่จะโพสต์ข้อความต้อนรับ (แอดมินเท่านั้น)"
    )
    @require_permission()
    async def welcome_set_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        await db.update_guild_section(
            interaction.guild_id, "welcome", {"channel_id": channel.id}
        )
        await interaction.response.send_message(
            embed=style.success(f"ตั้งห้องต้อนรับเป็น {channel.mention} แล้ว"), ephemeral=True
        )

    @app_commands.command(
        name="welcome-add-image",
        description="🎲 เพิ่มรูป/GIF เข้าคลังต้อนรับ (มีหลายรูป = สุ่มใช้ทุกครั้งที่มีคนเข้า) (แอดมินเท่านั้น)",
    )
    @require_permission()
    @app_commands.describe(url="ลิงก์รูปหรือ GIF")
    async def welcome_add_image(self, interaction: discord.Interaction, url: str):
        cfg = await db.get_guild_config(interaction.guild_id)
        image_urls = cfg["welcome"].get("image_urls") or []
        image_urls.append(url)
        await db.update_guild_section(interaction.guild_id, "welcome", {"image_urls": image_urls})
        await interaction.response.send_message(
            embed=style.success(f"เพิ่มรูปแล้ว ตอนนี้มีทั้งหมด **{len(image_urls)} รูป** ในคลัง (บอทจะสุ่มเลือก 1 รูปทุกครั้งที่มีคนเข้าเซิร์ฟ)"),
            ephemeral=True,
        )

    @app_commands.command(
        name="welcome-list-images", description="ดูรายชื่อรูป/GIF ทั้งหมดในคลังต้อนรับ"
    )
    @require_permission()
    async def welcome_list_images(self, interaction: discord.Interaction):
        cfg = await db.get_guild_config(interaction.guild_id)
        image_urls = cfg["welcome"].get("image_urls") or []
        if not image_urls:
            await interaction.response.send_message(
                embed=style.info("ยังไม่มีรูปในคลังเลยครับ ใช้ `/welcome-add-image` เพื่อเริ่มเพิ่ม (ตอนนี้ใช้ Main Image URL "
                "จาก `/welcome-editor` เดี่ยว ๆ อยู่)"),
                ephemeral=True,
            )
            return
        lines = [f"{i + 1}. {url}" for i, url in enumerate(image_urls)]
        await interaction.response.send_message(
            embed=style.info(f"📋 มีทั้งหมด {len(image_urls)} รูปในคลัง:\n" + "\n".join(lines)), ephemeral=True
        )

    @app_commands.command(
        name="welcome-remove-image", description="ลบรูปออกจากคลังต้อนรับตามลำดับที่ (ดูจาก /welcome-list-images)"
    )
    @require_permission()
    @app_commands.describe(index="ลำดับที่ของรูป (เริ่มจาก 1)")
    async def welcome_remove_image(self, interaction: discord.Interaction, index: int):
        cfg = await db.get_guild_config(interaction.guild_id)
        image_urls = cfg["welcome"].get("image_urls") or []
        if index < 1 or index > len(image_urls):
            await interaction.response.send_message(
                embed=style.warn(f"ลำดับไม่ถูกต้อง (มีทั้งหมด {len(image_urls)} รูป)"), ephemeral=True
            )
            return
        removed = image_urls.pop(index - 1)
        await db.update_guild_section(interaction.guild_id, "welcome", {"image_urls": image_urls})
        await interaction.response.send_message(
            embed=style.info(f"🗑️ ลบรูปที่ {index} แล้ว (`{removed[:60]}...`)"), ephemeral=True
        )

    # ---------------- 👤 Author / Footer ----------------

    @app_commands.command(
        name="welcome-set-author", description="ตั้งช่อง Author (ชื่อ+ไอคอนเล็กด้านบน embed) (แอดมินเท่านั้น)"
    )
    @require_permission()
    @app_commands.describe(
        name="ชื่อที่โชว์ (เว้นว่างเพื่อลบ author ออก, ใช้ {user_name} {server_name} ได้)",
        icon_url="ไอคอนเล็กข้าง author (ไม่บังคับ)",
    )
    async def welcome_set_author(
        self, interaction: discord.Interaction, name: str = "", icon_url: str = None
    ):
        await db.update_guild_section(
            interaction.guild_id,
            "welcome",
            {"author_name": name or None, "author_icon_url": icon_url},
        )
        await interaction.response.send_message(embed=style.success("ตั้งค่า Author แล้ว"), ephemeral=True)

    @app_commands.command(
        name="welcome-set-footer", description="ตั้งช่อง Footer (ข้อความเล็กด้านล่าง embed) (แอดมินเท่านั้น)"
    )
    @require_permission()
    @app_commands.describe(
        text="ข้อความ footer (เว้นว่างเพื่อลบ footer ออก)",
        icon_url="ไอคอนเล็กข้าง footer (ไม่บังคับ)",
    )
    async def welcome_set_footer(
        self, interaction: discord.Interaction, text: str = "", icon_url: str = None
    ):
        await db.update_guild_section(
            interaction.guild_id,
            "welcome",
            {"footer_text": text or None, "footer_icon_url": icon_url},
        )
        await interaction.response.send_message(embed=style.success("ตั้งค่า Footer แล้ว"), ephemeral=True)

    # ---------------- 📋 Embed Fields ----------------

    @app_commands.command(
        name="welcome-add-field", description="เพิ่มช่องข้อมูลย่อยใน embed (สูงสุด 3 ช่อง) (แอดมินเท่านั้น)"
    )
    @require_permission()
    @app_commands.describe(name="หัวข้อของช่อง", value="ค่าของช่อง", inline="วางเรียงแนวนอนไหม")
    async def welcome_add_field(
        self, interaction: discord.Interaction, name: str, value: str, inline: bool = True
    ):
        cfg = await db.get_guild_config(interaction.guild_id)
        fields = cfg["welcome"].get("fields", [])
        if len(fields) >= 3:
            await interaction.response.send_message(
                embed=style.warn("ใส่ได้สูงสุด 3 ช่อง ใช้ `/welcome-clear-fields` ก่อนถ้าจะเปลี่ยนใหม่"), ephemeral=True
            )
            return
        fields.append({"name": name, "value": value, "inline": inline})
        await db.update_guild_section(interaction.guild_id, "welcome", {"fields": fields})
        await interaction.response.send_message(
            embed=style.success(f"เพิ่มช่อง '{name}' แล้ว (ตอนนี้มี {len(fields)}/3 ช่อง)"), ephemeral=True
        )

    @app_commands.command(name="welcome-clear-fields", description="ลบช่องข้อมูลย่อยทั้งหมดออก (แอดมินเท่านั้น)")
    @require_permission()
    async def welcome_clear_fields(self, interaction: discord.Interaction):
        await db.update_guild_section(interaction.guild_id, "welcome", {"fields": []})
        await interaction.response.send_message(embed=style.info("🗑️ ลบช่องข้อมูลย่อยทั้งหมดแล้ว"), ephemeral=True)

    # ---------------- 📨 Multi-Embed ----------------

    @app_commands.command(
        name="welcome-set-extra-embed",
        description="ตั้ง embed ที่สองต่อท้าย เช่น แยกกฎ/ลิงก์ห้องสำคัญ (แอดมินเท่านั้น)",
    )
    @require_permission()
    @app_commands.describe(
        title="หัวข้อ embed ที่สอง (เว้นว่างเพื่อปิดการส่ง embed ที่สอง)",
        description="รายละเอียด (ใช้ {user} {server_name} ได้)",
    )
    async def welcome_set_extra_embed(
        self, interaction: discord.Interaction, title: str = "", description: str = ""
    ):
        await db.update_guild_section(
            interaction.guild_id,
            "welcome",
            {"extra_embed_title": title or None, "extra_embed_description": description or None},
        )
        status = "เปิดใช้งาน" if title else "ปิดการส่ง (เว้น title ว่างไว้)"
        await interaction.response.send_message(embed=style.success(f"ตั้ง embed ที่สอง: {status}"), ephemeral=True)

    # ---------------- 🖼️ Composite Position / Border ----------------

    @app_commands.command(
        name="welcome-composite-config",
        description="ปรับตำแหน่ง avatar/ข้อความ และกรอบของรูป composite (แอดมินเท่านั้น)",
    )
    @require_permission()
    @app_commands.describe(
        avatar_position="ตำแหน่ง avatar บนรูป",
        avatar_size="ขนาด avatar (พิกเซล)",
        text_position="ตำแหน่งข้อความบนรูป",
        border_color="สีกรอบ hex (เว้นว่าง = ไม่มีกรอบ)",
        border_width="ความหนากรอบ (พิกเซล, 0 = ไม่มีกรอบ)",
    )
    @app_commands.choices(
        avatar_position=[
            app_commands.Choice(name="บน", value="top"),
            app_commands.Choice(name="กลาง", value="center"),
            app_commands.Choice(name="ล่าง", value="bottom"),
        ],
        text_position=[
            app_commands.Choice(name="บน", value="top"),
            app_commands.Choice(name="กลาง", value="center"),
            app_commands.Choice(name="ล่าง", value="bottom"),
        ],
    )
    async def welcome_composite_config(
        self,
        interaction: discord.Interaction,
        avatar_position: app_commands.Choice[str] = None,
        avatar_size: int = None,
        text_position: app_commands.Choice[str] = None,
        border_color: str = None,
        border_width: int = None,
    ):
        updates = {}
        if avatar_position is not None:
            updates["avatar_position"] = avatar_position.value
        if avatar_size is not None:
            updates["avatar_size"] = avatar_size
        if text_position is not None:
            updates["text_position"] = text_position.value
        if border_color is not None:
            updates["border_color"] = border_color or None
        if border_width is not None:
            updates["border_width"] = border_width
        if not updates:
            await interaction.response.send_message(embed=style.warn("ใส่พารามิเตอร์อย่างน้อย 1 อย่าง"), ephemeral=True)
            return
        await db.update_guild_section(interaction.guild_id, "welcome", updates)
        await interaction.response.send_message(
            embed=style.success(f"อัปเดต composite config แล้ว ({len(updates)} รายการ) — ใช้กับรูปที่ตั้งฟอนต์ไว้เท่านั้น"),
            ephemeral=True,
        )

    # ---------------- 🎲 Delay / DM ----------------

    @app_commands.command(
        name="welcome-set-delay", description="หน่วงเวลาก่อนส่งข้อความต้อนรับ (แอดมินเท่านั้น)"
    )
    @require_permission()
    @app_commands.describe(seconds="จำนวนวินาทีที่จะหน่วง (0 = ส่งทันที, สูงสุด 300)")
    async def welcome_set_delay(self, interaction: discord.Interaction, seconds: int):
        seconds = max(0, min(seconds, 300))
        await db.update_guild_section(interaction.guild_id, "welcome", {"delay_seconds": seconds})
        await interaction.response.send_message(embed=style.success(f"ตั้งค่าหน่วงเวลาเป็น {seconds} วินาทีแล้ว"), ephemeral=True)

    @app_commands.command(
        name="welcome-toggle-dm", description="เปิด/ปิดการส่ง DM ต้อนรับแยกจากที่โพสต์ในห้อง (แอดมินเท่านั้น)"
    )
    @require_permission()
    async def welcome_toggle_dm(self, interaction: discord.Interaction, enabled: bool):
        await db.update_guild_section(interaction.guild_id, "welcome", {"dm_enabled": enabled})
        status = "เปิด ✅" if enabled else "ปิด"
        await interaction.response.send_message(embed=style.info(f"DM ต้อนรับ: {status}"), ephemeral=True)

    # ---------------- 📊 Statistics ----------------

    @app_commands.command(name="welcome-stats", description="ดูจำนวนครั้งที่ส่งข้อความต้อนรับไปแล้ว")
    async def welcome_stats(self, interaction: discord.Interaction):
        cfg = await db.get_guild_config(interaction.guild_id)
        count = cfg["welcome"].get("send_count", 0)
        await interaction.response.send_message(
            embed=style.info(f"📊 ส่งข้อความต้อนรับไปแล้วทั้งหมด **{count} ครั้ง**"), ephemeral=True
        )

    # ---------------- 🎨 Preset / Theme System ----------------

    @app_commands.command(
        name="welcome-save-preset", description="บันทึกดีไซน์ต้อนรับปัจจุบันเป็น preset ไว้สลับใช้ (แอดมินเท่านั้น)"
    )
    @require_permission()
    @app_commands.describe(name="ชื่อ preset เช่น christmas, halloween, ปกติ")
    async def welcome_save_preset(self, interaction: discord.Interaction, name: str):
        cfg = await db.get_guild_config(interaction.guild_id)
        await db.save_welcome_preset(interaction.guild_id, name, cfg["welcome"])
        await interaction.response.send_message(embed=style.success(f"บันทึก preset '{name}' แล้ว"), ephemeral=True)

    @app_commands.command(
        name="welcome-load-preset", description="โหลด preset ที่บันทึกไว้มาใช้ทันที (แอดมินเท่านั้น)"
    )
    @require_permission()
    @app_commands.describe(name="ชื่อ preset ที่จะโหลด")
    async def welcome_load_preset(self, interaction: discord.Interaction, name: str):
        preset_config = await db.load_welcome_preset(interaction.guild_id, name)
        if preset_config is None:
            await interaction.response.send_message(
                embed=style.warn(f"ไม่พบ preset '{name}' เช็คชื่อจาก `/welcome-list-presets`"), ephemeral=True
            )
            return
        await db.update_guild_section(interaction.guild_id, "welcome", preset_config)
        await interaction.response.send_message(embed=style.success(f"โหลด preset '{name}' มาใช้แล้ว"), ephemeral=True)

    @app_commands.command(name="welcome-list-presets", description="ดูรายชื่อ preset ทั้งหมดที่บันทึกไว้")
    async def welcome_list_presets(self, interaction: discord.Interaction):
        names = await db.list_welcome_presets(interaction.guild_id)
        if not names:
            await interaction.response.send_message(
                embed=style.info("ยังไม่มี preset เลยครับ ใช้ `/welcome-save-preset` เพื่อบันทึกชุดแรก"), ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=style.info("🎨 Preset ที่มี:\n" + "\n".join(f"• {n}" for n in names)), ephemeral=True
        )

    @app_commands.command(name="welcome-delete-preset", description="ลบ preset ที่บันทึกไว้ (แอดมินเท่านั้น)")
    @require_permission()
    @app_commands.describe(name="ชื่อ preset ที่จะลบ")
    async def welcome_delete_preset(self, interaction: discord.Interaction, name: str):
        deleted = await db.delete_welcome_preset(interaction.guild_id, name)
        if deleted:
            await interaction.response.send_message(embed=style.info(f"🗑️ ลบ preset '{name}' แล้ว"), ephemeral=True)
        else:
            await interaction.response.send_message(embed=style.warn(f"ไม่พบ preset '{name}'"), ephemeral=True)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        if not await db.is_system_enabled(member.guild.id, "welcome"):
            return
        cfg = await db.get_guild_config(member.guild.id)
        welcome_cfg = cfg["welcome"]
        channel_id = welcome_cfg.get("channel_id")

        delay_seconds = welcome_cfg.get("delay_seconds", 0)
        if delay_seconds:
            await asyncio.sleep(min(delay_seconds, 300))  # กันตั้งค่าเผลอเลขสูงเกินจนบอทค้าง

        embed, file, extra_embed = await build_welcome_message(welcome_cfg, member, member.guild.id)

        if channel_id:
            channel = member.guild.get_channel(channel_id)
            if channel is not None:
                embeds = [embed] + ([extra_embed] if extra_embed else [])
                if file:
                    await channel.send(embeds=embeds, file=file)
                else:
                    await channel.send(embeds=embeds)
                # ส่ง mention จริงแยกข้อความ วงเล็บต่อท้าย เพื่อให้แจ้งเตือนสมาชิกใหม่ได้จริง
                # (เหมือนระบบเก่า) เพราะ title ของ embed โชว์ mention แบบกดได้ไม่ได้
                await channel.send(content=f"({member.mention})")
                await db.increment_welcome_send_count(member.guild.id)

        if welcome_cfg.get("dm_enabled"):
            try:
                await member.send(embed=embed)
            except (discord.Forbidden, discord.HTTPException):
                pass  # เปิด DM ปิดไว้ หรือส่งไม่สำเร็จ — ไม่ต้องทำอะไรต่อ


async def setup(bot: commands.Bot):
    await bot.add_cog(Welcome(bot))
