"""
db.py — เก็บ event ประวัติ (เข้า/ออก/เตะ/แบน) ลง MongoDB Atlas (ฟรี, ถาวร, ไม่หายตอน Render redeploy)
ติดตั้งก่อนใช้งาน: pip install motor

ต้องตั้ง Environment Variable ชื่อ MONGODB_URI บน Render ก่อน (ดูวิธีสมัคร MongoDB Atlas แยกต่างหาก)
ถ้ายังไม่ตั้ง ระบบจะข้ามการบันทึกลง DB ไปเฉยๆ (บอทไม่ error ไม่ crash) แค่ไม่มีสถิติย้อนหลังให้ดู
"""

import os
import datetime
import motor.motor_asyncio

MONGODB_URI = os.environ.get('MONGODB_URI')

_client = None
_db = None

if MONGODB_URI:
  try:
    _client = motor.motor_asyncio.AsyncIOMotorClient(MONGODB_URI)
    _db = _client['beluga']
    print('🗄️ เชื่อมต่อ MongoDB Atlas สำเร็จ')
  except Exception as e:
    print(f'⚠️ เชื่อมต่อ MongoDB ไม่สำเร็จ: {e}')
    _db = None
else:
  print('⚠️ ยังไม่ได้ตั้งค่า MONGODB_URI — ข้ามการเก็บสถิติย้อนหลัง (log ลง Discord ยังทำงานปกติ)')


def is_connected() -> bool:
  return _db is not None


async def record_event(guild_id: int, event_type: str, data: dict = None):
  """บันทึก event หนึ่งรายการ เช่น join / leave / kick / ban / unban"""
  if _db is None:
    return
  doc = {
      'guild_id': guild_id,
      'event_type': event_type,
      'timestamp': datetime.datetime.utcnow(),
  }
  if data:
    doc.update(data)
  try:
    await _db.events.insert_one(doc)
  except Exception as e:
    print(f'⚠️ บันทึก event ลง MongoDB ไม่สำเร็จ: {e}')


async def count_since(guild_id: int, event_type: str, since: datetime.datetime) -> int:
  """นับจำนวน event ประเภทหนึ่งตั้งแต่เวลาที่กำหนดถึงตอนนี้"""
  if _db is None:
    return 0
  try:
    return await _db.events.count_documents({
        'guild_id': guild_id,
        'event_type': event_type,
        'timestamp': {'$gte': since},
    })
  except Exception as e:
    print(f'⚠️ ดึงสถิติจาก MongoDB ไม่สำเร็จ: {e}')
    return 0


async def daily_counts(guild_id: int, event_type: str, days: int = 30) -> list:
  """สรุปจำนวน event รายวันย้อนหลัง N วัน คืนค่าเป็น list ของ {'date': 'YYYY-MM-DD', 'count': N}
  เรียงจากวันเก่าสุดไปใหม่สุด — ใช้ทำกราฟได้ในอนาคต (เช่นตอนทำ dashboard เว็บ)"""
  if _db is None:
    return []
  since = datetime.datetime.utcnow() - datetime.timedelta(days=days)
  pipeline = [
      {'$match': {'guild_id': guild_id, 'event_type': event_type, 'timestamp': {'$gte': since}}},
      {'$group': {
          '_id': {'$dateToString': {'format': '%Y-%m-%d', 'date': '$timestamp'}},
          'count': {'$sum': 1},
      }},
      {'$sort': {'_id': 1}},
  ]
  try:
    cursor = _db.events.aggregate(pipeline)
    results = await cursor.to_list(length=days + 1)
    return [{'date': r['_id'], 'count': r['count']} for r in results]
  except Exception as e:
    print(f'⚠️ สรุปสถิติรายวันจาก MongoDB ไม่สำเร็จ: {e}')
    return []
