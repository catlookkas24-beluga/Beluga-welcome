"""
db.py
เลเยอร์คุยกับ MongoDB ทั้งหมดอยู่ที่นี่ที่เดียว — ทุก cog เรียกผ่านฟังก์ชันในไฟล์นี้
เก็บ config แยกตาม guild_id เป็นเอกสารเดียวต่อเซิร์ฟเวอร์ ทำให้บอทตัวเดียวดูแลได้หลายเซิร์ฟ
"""

import os
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorGridFSBucket
from bson import ObjectId

MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "beluga_control")

_client = AsyncIOMotorClient(MONGO_URI)
_db = _client[MONGO_DB_NAME]
guilds = _db["guild_configs"]

# GridFS bucket สำหรับเก็บไฟล์ที่ผู้ใช้อัปโหลด (รูป/ฟอนต์/config) แบบถาวร
# ไม่หายตอน redeploy บอท (ต่างจากดิสก์ของ Render ที่ล้างทุกครั้งที่ deploy ใหม่)
# สร้างแบบ lazy (ตอนถูกเรียกใช้ครั้งแรก) เพราะ motor เวอร์ชันใหม่ต้องการ event loop
# ที่ทำงานอยู่แล้วตอนสร้าง — ถ้าสร้างตอน import module จะ crash ทันที (ยังไม่มี event loop)
_assets_bucket = None


def _get_assets_bucket() -> AsyncIOMotorGridFSBucket:
    global _assets_bucket
    if _assets_bucket is None:
        _assets_bucket = AsyncIOMotorGridFSBucket(_db, bucket_name="assets")
    return _assets_bucket


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
    "welcome_image": {
        "enabled": False,
        "background_asset_id": None,
        "font_key": "mali",
        "text_template": "ยินดีต้อนรับ {user_name}",
        "text_color": "#ffffff",
        "font_size": 48,
        "text_position": "bottom",
        "avatar_enabled": True,
        "avatar_size": 128,
        "avatar_position": "center",
    },
    "verify": {
        "channel_id": None,
        "role_id": None,
        "explain_text": "ยืนยันตัวตนเพื่อป้องกันบอทและผู้ใช้ปลอม ช่วยให้เซิร์ฟเวอร์ปลอดภัยขึ้นครับ",
        "banner_asset_id": None,
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


async def reset_guild_config(guild_id: int) -> None:
    """⚡ Force Reset Config — เขียนทับ config ของเซิร์ฟนี้กลับเป็นค่าโรงงานทั้งหมด
    (ไม่แตะไฟล์ asset ที่อัปโหลดไว้ใน GridFS — อันนั้นต้องลบแยกถ้าต้องการ)"""
    await guilds.replace_one(
        {"_id": guild_id}, {"_id": guild_id, **DEFAULT_CONFIG}, upsert=True
    )


# ---------------- Asset Storage (GridFS) ----------------
# เก็บไฟล์ที่แอดมินอัปโหลดเอง (รูปพื้นหลัง, ฟอนต์, ไฟล์ config) แยกตาม guild_id
# ไม่ประมวลผล/เรนเดอร์อะไรกับไฟล์เหล่านี้ — เป็นแค่คลังเก็บไฟล์

ALLOWED_ASSET_TYPES = {
    "image": {".png", ".jpg", ".jpeg", ".webp"},
    "font": {".ttf", ".otf"},
    "config": {".json", ".txt"},
}
MAX_ASSET_SIZE_BYTES = 5 * 1024 * 1024  # 5MB


def detect_asset_type(filename: str) -> str | None:
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    for asset_type, extensions in ALLOWED_ASSET_TYPES.items():
        if ext in extensions:
            return asset_type
    return None


async def save_asset(guild_id: int, filename: str, data: bytes, asset_type: str, label: str) -> str:
    """อัปโหลดไฟล์เข้า GridFS คืนค่า file_id เป็น string"""
    file_id = await _get_assets_bucket().upload_from_stream(
        filename,
        data,
        metadata={
            "guild_id": guild_id,
            "asset_type": asset_type,
            "label": label,
        },
    )
    return str(file_id)


async def list_assets(guild_id: int, asset_type: str | None = None) -> list[dict]:
    query = {"metadata.guild_id": guild_id}
    if asset_type:
        query["metadata.asset_type"] = asset_type
    cursor = _get_assets_bucket().find(query)
    results = []
    async for doc in cursor:
        results.append(
            {
                "file_id": str(doc._id),
                "filename": doc.filename,
                "label": doc.metadata.get("label", doc.filename),
                "asset_type": doc.metadata.get("asset_type"),
                "length": doc.length,
            }
        )
    return results


async def get_asset_bytes(file_id: str) -> bytes:
    stream = await _get_assets_bucket().open_download_stream(ObjectId(file_id))
    return await stream.read()


async def delete_asset(guild_id: int, file_id: str) -> bool:
    """ลบไฟล์ ตรวจสอบก่อนว่าไฟล์นี้เป็นของ guild นี้จริงก่อนลบ (กันลบข้ามเซิร์ฟ)"""
    grid_out = await _get_assets_bucket().open_download_stream(ObjectId(file_id))
    if grid_out.metadata.get("guild_id") != guild_id:
        return False
    await _get_assets_bucket().delete(ObjectId(file_id))
    return True
