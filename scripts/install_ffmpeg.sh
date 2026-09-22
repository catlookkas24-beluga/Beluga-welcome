#!/usr/bin/env bash
# scripts/install_ffmpeg.sh
# ดาวน์โหลด FFmpeg 9.0.x static build (BtbN/FFmpeg-Builds) มาไว้ที่ ./bin/ffmpeg
# ใช้แทน apt install ffmpeg ที่ Debian ให้แค่เวอร์ชั่น 5.x
set -euo pipefail

FFMPEG_URL="https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n9.0-latest-linux64-gpl-9.0.tar.xz"

echo "⬇️  กำลังดาวน์โหลด FFmpeg 9.0 static build..."
mkdir -p bin
curl -fL -o /tmp/ffmpeg.tar.xz "$FFMPEG_URL"

echo "📦 กำลังแตกไฟล์..."
tar -xf /tmp/ffmpeg.tar.xz -C /tmp

FFMPEG_DIR=$(find /tmp -maxdepth 1 -type d -name "ffmpeg-n9.0*" | head -n1)

if [ -z "$FFMPEG_DIR" ]; then
    echo "❌ ไม่เจอโฟลเดอร์ที่แตกออกมา — ยกเลิกการติดตั้ง"
    exit 1
fi

cp "$FFMPEG_DIR/bin/ffmpeg" bin/ffmpeg
chmod +x bin/ffmpeg

# เก็บกวาดไฟล์ชั่วคราว
rm -rf /tmp/ffmpeg.tar.xz "$FFMPEG_DIR"

echo "✅ ติดตั้งเสร็จแล้ว — เวอร์ชั่นที่ได้:"
./bin/ffmpeg -version | head -n1
