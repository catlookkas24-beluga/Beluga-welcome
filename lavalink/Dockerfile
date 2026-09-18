# ใช้ official Lavalink image ตรงๆ ไม่ต้องติดตั้งอะไรเพิ่มเอง
FROM ghcr.io/lavalink-devs/lavalink:4

# ใส่ config ของเราทับ config เริ่มต้นของ image
# หมายเหตุ: ถ้า build context คือ repo root (ไม่ใช่โฟลเดอร์ lavalink/ ตรงๆ)
# ให้เปลี่ยนบรรทัดล่างเป็น: COPY lavalink/application.yml /opt/Lavalink/application.yml
COPY application.yml /opt/Lavalink/application.yml
