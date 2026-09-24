"""
cogs/goodbye.py — 👋 Goodbye Message
แอดมินพิมพ์ /goodbye-editor แล้วบอทเด้ง Modal ให้กรอก title/description/hex color/รูป/ฟอนต์
รองรับตัวแปร {user_name} {server_name} {server_membercount} แทรกในข้อความได้เลย
(ไม่มี {user} แบบ mention จริง เพราะสมาชิกออกจากเซิร์ฟไปแล้ว เมนชันจะไม่มีประโยชน์)

ใช้ helper function ชุดเดียวกับ welcome.py (render_variables, fetch_image_bytes,
render_avatar_text_on_background) เพื่อไม่ให้โค้ดซ้ำซ้อนกัน — ฟีเจอร์ฟอนต์ composite
ทำงานเหมือนกันทุกอย่าง
"""

import asyncio
import io
import random

import discord
from discord import app_commands
from discord.ext import commands

import db
import style
from checks import require_permission
from cogs.font import load_font_bytes
from cogs.welcome import (
    render_variables,
    parse_hex_color,
    fetch_image_bytes,
    render_avatar_text_on_background,
)


def build_goodbye_embed(cfg: dict, member: discord.Member) -> discord.Embed:
    embed = discord.Embed(
        title=render_variables(cfg.get("title", ""), member, use_mention=False),
        description=render_variables(cfg.get("description", ""), member, use_mention=False),
        color=parse_hex_color(cfg.get("color", "#C4B5FD")),
    )
    if cfg.get("image_url"):
        embed.set_image(url=cfg["image_url"])
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"{style.SYSTEM_ICON['goodbye']} {style.BRAND}")
    return embed


async def build_goodbye_message(
    cfg: dict, member: discord.Member, guild_id: int
) -> tuple[discord.Embed, discord.File | None]:
    """สร้าง embed อำลา — ถ้าตั้งฟอนต์ไว้ด้วย จะเรนเดอร์ avatar+ข้อความทับพื้นหลังให้
    เหมือน welcome ทุกอย่าง ล้มเหลวก็ fallback ไปใช้ Main Image URL แบบปกติเงียบ ๆ

    🎲 Random Message System: ถ้ามี image_urls (หลายรูป) ตั้งไว้ จะสุ่มเลือก 1 รูปมาใช้ทุกครั้ง"""
    render_cfg = dict(cfg)
    image_urls = cfg.get("image_urls") or []
    if image_urls:
        render_cfg["image_url"] = random.choice(image_urls)

    embed = build_goodbye_embed(render_cfg, member)
    file = None

    font_key = render_cfg.get("font_key")
    image_url = render_cfg.get("image_url")
    if font_key and image_url:
        bg_bytes = await fetch_image_bytes(image_url)
        if bg_bytes:
            loaded_font = await load_font_bytes(guild_id, font_key)
            if loaded_font:
                font_bytes, _ = loaded_font
                try:
                    avatar_bytes = await member.display_avatar.replace(size=256).read()
                except Exception:
                    avatar_bytes = None
                text = render_variables(render_cfg.get("title", ""), member, use_mention=False)
                try:
                    image_bytes = await asyncio.to_thread(render_avatar_text_on_background, 
                        bg_bytes, avatar_bytes, font_bytes, text
                    )
                    file = discord.File(io.BytesIO(image_bytes), filename="goodbye_composite.png")
                    embed.set_image(url="attachment://goodbye_composite.png")
                except Exception:
                    file = None

    return embed, file


class GoodbyeEditorModal(discord.ui.Modal, title="👋 Goodbye Message"):
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
            label="Hex Color (เช่น #C4B5FD)",
            default=current.get("color", "#C4B5FD"),
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
        pending_data = {
            "title": self.title_input.value,
            "description": self.description_input.value,
            "color": self.color_input.value,
            "image_url": self.image_input.value or None,
            "font_key": self.font_input.value.strip() or None,
        }
        embed, file = await build_goodbye_message(pending_data, interaction.user, interaction.guild_id)
        view = GoodbyePreviewView(interaction.guild_id, interaction.user.id, pending_data)
        kwargs = {
            "content": "👋 นี่คือตัวอย่าง — **ยังไม่ถูกบันทึก** จนกว่าจะกด \"นำไปใช้จริง\"",
            "embed": embed,
            "view": view,
            "ephemeral": True,
        }
        if file:
            kwargs["file"] = file
        await interaction.followup.send(**kwargs)


class GoodbyePreviewView(discord.ui.View):
    """ปุ่มควบคุมแบบเดียวกับ Wallpaper Live Preview ของ welcome — พรีวิว/Apply/คืนค่าเดิม"""

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
        embed, file = await build_goodbye_message(self.pending_data, interaction.user, self.guild_id)
        kwargs = {"content": "👁️ ตัวอย่าง (ยังไม่บันทึก):", "embed": embed, "ephemeral": True}
        if file:
            kwargs["file"] = file
        await interaction.followup.send(**kwargs)

    @discord.ui.button(label="นำไปใช้จริง", emoji="✅", style=discord.ButtonStyle.success)
    async def apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        await db.update_guild_section(self.guild_id, "goodbye", self.pending_data)
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="✅ บันทึกและนำไปใช้จริงแล้ว!", view=self)

    @discord.ui.button(label="คืนค่าเดิม", emoji="🔄", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="🔄 ยกเลิกแล้ว ไม่มีการบันทึกการเปลี่ยนแปลงใด ๆ", embed=None, view=self
        )


class Goodbye(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="goodbye-editor", description="เปิดหน้าต่างแก้ไข embed อำลา (แอดมินเท่านั้น)"
    )
    @require_permission()
    async def goodbye_editor(self, interaction: discord.Interaction):
        cfg = await db.get_guild_config(interaction.guild_id)
        await interaction.response.send_modal(GoodbyeEditorModal(cfg["goodbye"]))

    @app_commands.command(
        name="goodbye-set-channel", description="ตั้งห้องที่จะโพสต์ข้อความอำลา (แอดมินเท่านั้น)"
    )
    @require_permission()
    async def goodbye_set_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        await db.update_guild_section(
            interaction.guild_id, "goodbye", {"channel_id": channel.id}
        )
        await interaction.response.send_message(
            embed=style.success(f"ตั้งห้องอำลาเป็น {channel.mention} แล้ว"), ephemeral=True
        )

    @app_commands.command(
        name="goodbye-add-image",
        description="🎲 เพิ่มรูป/GIF เข้าคลังอำลา (มีหลายรูป = สุ่มใช้ทุกครั้งที่มีคนออก) (แอดมินเท่านั้น)",
    )
    @require_permission()
    @app_commands.describe(url="ลิงก์รูปหรือ GIF")
    async def goodbye_add_image(self, interaction: discord.Interaction, url: str):
        cfg = await db.get_guild_config(interaction.guild_id)
        image_urls = cfg["goodbye"].get("image_urls") or []
        image_urls.append(url)
        await db.update_guild_section(interaction.guild_id, "goodbye", {"image_urls": image_urls})
        await interaction.response.send_message(
            embed=style.success(f"เพิ่มรูปแล้ว ตอนนี้มีทั้งหมด **{len(image_urls)} รูป** ในคลัง"), ephemeral=True
        )

    @app_commands.command(
        name="goodbye-list-images", description="ดูรายชื่อรูป/GIF ทั้งหมดในคลังอำลา"
    )
    @require_permission()
    async def goodbye_list_images(self, interaction: discord.Interaction):
        cfg = await db.get_guild_config(interaction.guild_id)
        image_urls = cfg["goodbye"].get("image_urls") or []
        if not image_urls:
            await interaction.response.send_message(
                embed=style.info("ยังไม่มีรูปในคลังเลยครับ ใช้ `/goodbye-add-image` เพื่อเริ่มเพิ่ม"), ephemeral=True
            )
            return
        lines = [f"{i + 1}. {url}" for i, url in enumerate(image_urls)]
        await interaction.response.send_message(
            embed=style.info(f"📋 มีทั้งหมด {len(image_urls)} รูปในคลัง:\n" + "\n".join(lines)), ephemeral=True
        )

    @app_commands.command(
        name="goodbye-remove-image", description="ลบรูปออกจากคลังอำลาตามลำดับที่ (ดูจาก /goodbye-list-images)"
    )
    @require_permission()
    @app_commands.describe(index="ลำดับที่ของรูป (เริ่มจาก 1)")
    async def goodbye_remove_image(self, interaction: discord.Interaction, index: int):
        cfg = await db.get_guild_config(interaction.guild_id)
        image_urls = cfg["goodbye"].get("image_urls") or []
        if index < 1 or index > len(image_urls):
            await interaction.response.send_message(
                embed=style.warn(f"ลำดับไม่ถูกต้อง (มีทั้งหมด {len(image_urls)} รูป)"), ephemeral=True
            )
            return
        removed = image_urls.pop(index - 1)
        await db.update_guild_section(interaction.guild_id, "goodbye", {"image_urls": image_urls})
        await interaction.response.send_message(
            embed=style.info(f"🗑️ ลบรูปที่ {index} แล้ว (`{removed[:60]}...`)"), ephemeral=True
        )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        # หมายเหตุ: event นี้ยิงทั้งกรณีออกเอง / โดน kick / โดน ban — แยกสาเหตุไม่ได้
        # ถ้าอยากรู้สาเหตุจริงต้องเช็ค audit log เพิ่ม (ยังไม่ได้ทำในเวอร์ชันนี้)
        if member.bot:
            return
        if not await db.is_system_enabled(member.guild.id, "goodbye"):
            return
        cfg = await db.get_guild_config(member.guild.id)
        channel_id = cfg["goodbye"].get("channel_id")
        if not channel_id:
            return
        channel = member.guild.get_channel(channel_id)
        if channel is None:
            return

        embed, file = await build_goodbye_message(cfg["goodbye"], member, member.guild.id)
        if file:
            await channel.send(embed=embed, file=file)
        else:
            await channel.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Goodbye(bot))
