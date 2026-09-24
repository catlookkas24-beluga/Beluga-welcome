# 🌸 Anyaluga — Cute UI Update

## หน้าตาใหม่ (ทั้งบอท)
- `style.py` เขียนใหม่เป็นชุดสไตล์พาสเทล: สีหลักชมพูบับเบิ้ลกัม `#FF9EC4`, footer `Anyaluga ♡`, divider 🌸, หัวข้อสุ่มน่ารัก
  - เพิ่ม `style.info()`, `style.heart_bar()`, `style.footer()`, `style.clip()` — API เดิมใช้ได้เหมือนเดิมทั้งหมด
- ข้อความตอบกลับแบบ plain text ทุกจุด (~110 จุด) เปลี่ยนเป็น embed ผ่าน `style.success/error/warn/info`
- ค่าเริ่มต้นของ welcome / goodbye / verify / rules / ticket ปรับสีและข้อความให้น่ารัก
  (เซิร์ฟที่ตั้งค่าไว้แล้วไม่ถูกทับ — ใช้ได้เฉพาะเซิร์ฟใหม่ หรือหลัง `/force` reset)
- `/theme-set-color` ตั้งสีให้ระบบเพลงด้วย (เพิ่ม `music` เข้า THEMED_SECTIONS)
- error handler กลางใน `bot.py` — ตอบด้วย embed แทนที่จะขึ้น "แอปไม่ตอบสนอง"

## ระบบเพลง (cogs/music.py เขียนใหม่)
- Now Playing panel ใหม่: หัวใจ progress bar, การ์ด 6 ช่อง, บอกเพลงถัดไป, ปุ่ม 3 แถว (รวม 🎛️ EQ / 🎨 ธีม)
- `/play` มี autocomplete ชื่อเพลงจากคลัง
- Panel โพสต์ใหม่ที่ก้นห้องเมื่อเปลี่ยนเพลง (ถ้ามีข้อความอื่นแทรกลงมา)

## บั๊กที่แก้ไปพร้อมกัน
1. **ลิงก์ Discord CDN หมดอายุ** — `/addsongfromvideo` เก็บ channel_id + message_id ไว้ แล้วดึงลิงก์ใหม่ก่อนเล่นทุกครั้ง
   (รับไฟล์เสียงได้ด้วย ไม่ใช่แค่วิดีโอ) ⚠️ ห้ามลบข้อความที่บอทอัปโหลดไว้
2. **สิทธิ์** — ปุ่ม/คำสั่งคุมเพลงต้องอยู่ห้องเสียงเดียวกับบอท (Manage Server ข้ามได้),
   `/addsong` `/addsongfromvideo` `/removesong` `/settheme` `/thememenu` `/ffmpeginfo` ใช้ `require_permission()`
   (ให้ยศ DJ ใช้ได้ผ่าน `/cmdperm-grant`), บอทไม่ถูกลากย้ายห้องระหว่างเล่นแล้ว
3. **Pillow บล็อก event loop** — welcome / goodbye / chart / font-preview / welcome-image ใช้ `asyncio.to_thread`
4. **repeat / previous / skip** — เครื่องเล่นใหม่ใช้ token + lock ต่อเซิร์ฟ, callback เก่าไม่ตีกับคำสั่งใหม่แล้ว
   เพลงพังติดกัน 3 เพลงจะหยุดคิวเอง

## เพิ่มเติม
- ffmpeg จำกัดโปรโตคอล `http,https,tcp,tls,crypto` + ปฏิเสธลิงก์ที่ชี้ไป IP ภายใน/localhost
- Nightcore/Vaporwave/Deep/Chipmunk แก้ให้ pitch ตรง (Discord ใช้ 48kHz)
- จำสีธีม / ระดับเสียง / EQ ข้าม restart (เก็บที่ `guild_configs.<guild>.music`)
- ปุ่ม panel มี `custom_id` กดได้แม้หลัง restart
- ออกจากห้องเองเมื่อไม่มีคนอยู่ 60 วิ / เงียบนาน 5 นาที
- `bot.py`: ซิงก์ slash command ใน `setup_hook`, เช็ค DISCORD_TOKEN, `db.get_guild_config` กัน race ตอนเซิร์ฟใหม่

## หลังอัปเดต
ต้อง restart บอทหนึ่งครั้ง (slash command ซิงก์เองอัตโนมัติ)
เพลงที่เคยเพิ่มด้วย `/addsongfromvideo` เวอร์ชันเก่าไม่มี message_ref → ยังใช้ลิงก์เดิมจนกว่าจะหมดอายุ
แนะนำให้เพิ่มใหม่ด้วยคำสั่งนี้อีกครั้ง
