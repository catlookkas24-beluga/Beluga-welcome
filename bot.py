"""
bot.py
จุดเริ่มรันบอท — โหลดทุก cog แล้วเชื่อมต่อ Discord
รันด้วย: python bot.py
"""

import os
import asyncio
import logging

import discord
from discord.ext import commands
from dotenv import load_dotenv
from aiohttp import web

load_dotenv()

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("beluga")

TOKEN = os.getenv("DISCORD_TOKEN")
PORT = int(os.getenv("PORT", "10000"))  # Render จะกำหนด PORT มาให้เองผ่าน env


async def health_check(request):
    return web.Response(text="Beluga bot is alive")


async def start_web_server():
    """เปิด HTTP server เล็ก ๆ ไว้ให้ Render เจอพอร์ต และให้ UptimeRobot ping ได้"""
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    log.info(f"เปิด health-check web server ที่พอร์ต {PORT} แล้ว")

intents = discord.Intents.default()
intents.members = True          # จำเป็นสำหรับ welcome / autorole / antiraid
intents.message_content = True  # จำเป็นถ้าจะใช้ prefix command เสริมในอนาคต

bot = commands.Bot(command_prefix="!", intents=intents)

INITIAL_COGS = [
    "cogs.welcome",
    "cogs.verify",
    "cogs.rules",
    "cogs.antiraid",
    "cogs.autorole",
    "cogs.control_panel",
]


@bot.event
async def on_ready():
    log.info(f"เข้าสู่ระบบในชื่อ {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        log.info(f"ซิงก์ slash command แล้ว {len(synced)} คำสั่ง")
    except Exception as e:
        log.error(f"ซิงก์ slash command ไม่สำเร็จ: {e}")


async def main():
    await start_web_server()
    async with bot:
        for cog in INITIAL_COGS:
            await bot.load_extension(cog)
            log.info(f"โหลด {cog} แล้ว")
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
