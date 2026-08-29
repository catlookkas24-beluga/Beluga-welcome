"""
db.py
เลเยอร์คุยกับ MongoDB ทั้งหมดอยู่ที่นี่ที่เดียว — ทุก cog เรียกผ่านฟังก์ชันในไฟล์นี้
เก็บ config แยกตาม guild_id เป็นเอกสารเดียวต่อเซิร์ฟเวอร์ ทำให้บอทตัวเดียวดูแลได้หลายเซิร์ฟ
"""

import os
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "beluga_control")

_client = AsyncIOMotorClient(MONGO_URI)
_db = _client[MONGO_DB_NAME]
guilds = _db["guild_configs"]


async def warm_up():
    """เรียกตอนบอทเริ่มทำงาน เพื่อเปิดการเชื่อมต่อ MongoDB ล่วงหน้า
    ป้องกัน interaction แรกที่ user สั่งค้าง/timeout เพราะรอ TLS handshake"""
    await _client.admin.command("ping")

# ค่าเริ่มต้นของแต่ละระบบ — ใช้ตอนเซิร์ฟเวอร์ยังไม่มี config ใน DB เลย
DEFAULT_CONFIG = {
    "systems_enabled": {
        "welcome": True,
        "verify": True,
        "rules": True,
        "antiraid": True,
        "autorole": True,
    },
    "welcome": {
        "channel_id": None,
        "title": "🎉 ยินดีต้อนรับ {user} สู่ {server_name}!",
        "description": "ตอนนี้เซิร์ฟเวอร์มี {server_membercount} สมาชิกแล้ว!",
        "color": "#a0d2eb",
        "image_url": None,
    },
    "verify": {
        "channel_id": None,
        "role_id": None,
        "explain_text": "ยืนยันตัวตนเพื่อป้องกันบอทและผู้ใช้ปลอม ช่วยให้เซิร์ฟเวอร์ปลอดภัยขึ้นครับ",
    },
    "rules": {
        "channel_id": None,
        "message_id": None,
        "rules_text": "1. เคารพกันและกัน\n2. ห้ามสแปม\n3. ห้ามโฆษณาที่ไม่ได้รับอนุญาต",
        "rank_text": "7 วัน = ส่งรูปได้ | 30 วัน = เข้าเสียงได้",
    },
    "antiraid": {
        "join_threshold": 5,
        "window_seconds": 10,
        "min_account_age_days": 7,
        "alert_channel_id": None,
    },
    "autorole": {
        "auto_grant": True,
        "claim_channel_id": None,
        "timeline": [
            {"days": 7, "role_id": None, "label": "Member"},
            {"days": 30, "role_id": None, "label": "Active"},
            {"days": 60, "role_id": None, "label": "Veteran"},
            {"days": 90, "role_id": None, "label": "Legend"},
        ],
    },
}


def _merge_defaults(doc: dict) -> dict:
    """เติม key ที่ขาดไปด้วยค่า default แบบ recursive (กันเอกสารเก่าที่ schema ยังไม่ครบ)"""
    merged = {}
    for key, default_val in DEFAULT_CONFIG.items():
        stored_val = doc.get(key)
        if isinstance(default_val, dict) and isinstance(stored_val, dict):
            merged[key] = {**default_val, **stored_val}
        elif stored_val is not None:
            merged[key] = stored_val
        else:
            merged[key] = default_val
    return merged


async def get_guild_config(guild_id: int) -> dict:
    doc = await guilds.find_one({"_id": guild_id})
    if doc is None:
        fresh = {"_id": guild_id, **DEFAULT_CONFIG}
        await guilds.insert_one(fresh)
        return fresh
    return {"_id": guild_id, **_merge_defaults(doc)}


async def update_guild_section(guild_id: int, section: str, values: dict) -> None:
    """อัปเดตเฉพาะ sub-document ของ section หนึ่ง (เช่น 'welcome', 'verify') แบบ upsert"""
    await guilds.update_one(
        {"_id": guild_id},
        {"$set": {f"{section}.{k}": v for k, v in values.items()}},
        upsert=True,
    )


async def set_system_enabled(guild_id: int, system_name: str, enabled: bool) -> None:
    await guilds.update_one(
        {"_id": guild_id},
        {"$set": {f"systems_enabled.{system_name}": enabled}},
        upsert=True,
    )


async def is_system_enabled(guild_id: int, system_name: str) -> bool:
    cfg = await get_guild_config(guild_id)
    return cfg["systems_enabled"].get(system_name, True)
