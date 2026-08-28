"""
log_system.py — ระบบ log หลังบ้านของ Beluga
เก็บทุกอย่างเป็นข้อความ/embed ในห้อง Discord (ไม่ใช้ไฟล์/ฐานข้อมูลในเครื่อง)
เพราะ Render free tier ล้าง disk ทุกครั้งที่ deploy ใหม่ — เก็บใน Discord แทนคือถาวรแน่นอน
"""

import datetime
from typing import Optional
import discord
import db

LOG_CHANNEL_NAME = '📋log-ระบบ'

LOG_COLORS = {
    'join': discord.Color.green(),
    'leave': discord.Color.orange(),
    'kick': discord.Color.red(),
    'ban': discord.Color.dark_red(),
    'unban': discord.Color.blurple(),
    'role': discord.Color.gold(),
    'nickname': discord.Color.teal(),
    'timeout': discord.Color.dark_orange(),
    'msg_delete': discord.Color.dark_grey(),
    'msg_edit': discord.Color.light_grey(),
    'voice': discord.Color.purple(),
}


async def ensure_log_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
  """หาห้อง log ถ้าไม่มีให้สร้างใหม่ ซ่อนจาก @everyone (แอดมินยังเห็นได้เสมอเพราะสิทธิ์ Administrator ข้ามการซ่อนห้อง)"""
  existing = discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)
  if existing is not None:
    return existing

  overwrites = {
      guild.default_role: discord.PermissionOverwrite(view_channel=False),
      guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True),
  }
  try:
    channel = await guild.create_text_channel(
        LOG_CHANNEL_NAME,
        overwrites=overwrites,
        topic='ห้อง log อัตโนมัติของระบบ (มองเห็นเฉพาะแอดมิน)',
        reason='สร้างห้อง log หลังบ้านอัตโนมัติ',
    )
    print(f'📋 สร้างห้อง log "{LOG_CHANNEL_NAME}" ในเซิร์ฟ "{guild.name}" เรียบร้อย')
    return channel
  except discord.Forbidden:
    print(f'⚠️ สร้างห้อง log ไม่ได้ในเซิร์ฟ "{guild.name}" เพราะบอทไม่มีสิทธิ์ Manage Channels')
    return None
  except discord.HTTPException as e:
    print(f'⚠️ สร้างห้อง log ไม่สำเร็จ: {e}')
    return None


async def send_log(guild: discord.Guild, embed: discord.Embed):
  channel = await ensure_log_channel(guild)
  if channel is None:
    return
  try:
    await channel.send(embed=embed)
  except discord.Forbidden:
    print(f'⚠️ บอทไม่มีสิทธิ์ส่งข้อความในห้อง log ของเซิร์ฟ "{guild.name}"')
  except discord.HTTPException as e:
    print(f'⚠️ ส่ง log ไม่สำเร็จ: {e}')


def _fmt_dt(dt: Optional[datetime.datetime]) -> str:
  if dt is None:
    return 'ไม่ทราบ'
  return discord.utils.format_dt(dt, style='R')  # เช่น "3 วันที่แล้ว"


async def _find_audit_actor(guild: discord.Guild, action: discord.AuditLogAction, target_id: int, seconds: int = 5):
  """หาว่าใครเป็นคนทำ action นี้ล่าสุด (ใช้เช็คว่าคนออกเพราะถูกเตะ/แบน หรือใครสั่ง timeout) — ต้องมีสิทธิ์ View Audit Log"""
  try:
    async for entry in guild.audit_logs(action=action, limit=5):
      if entry.target and getattr(entry.target, 'id', None) == target_id:
        age = (discord.utils.utcnow() - entry.created_at).total_seconds()
        if age <= seconds:
          return entry
  except discord.Forbidden:
    pass
  except discord.HTTPException:
    pass
  return None


# ---------- สมาชิกเข้าเซิร์ฟ ----------
async def log_member_join(member: discord.Member):
  await db.record_event(member.guild.id, 'join', {'user_id': member.id})

  embed = discord.Embed(
      title='📥 สมาชิกเข้าเซิร์ฟ',
      color=LOG_COLORS['join'],
      timestamp=discord.utils.utcnow(),
  )
  embed.set_thumbnail(url=member.display_avatar.url)
  embed.add_field(name='สมาชิก', value=f'{member.mention} (`{member}`)', inline=False)
  embed.add_field(name='สร้างบัญชีเมื่อ', value=_fmt_dt(member.created_at), inline=True)
  embed.add_field(name='ลำดับสมาชิก', value=str(member.guild.member_count), inline=True)
  await send_log(member.guild, embed)


# ---------- สมาชิกออกจากเซิร์ฟ (เช็คว่าออกเอง/ถูกเตะ) ----------
async def log_member_remove(member: discord.Member):
  kick_entry = await _find_audit_actor(member.guild, discord.AuditLogAction.kick, member.id)
  await db.record_event(
      member.guild.id,
      'kick' if kick_entry is not None else 'leave',
      {'user_id': member.id},
  )

  if kick_entry is not None:
    embed = discord.Embed(
        title='👢 สมาชิกถูกเตะออก',
        color=LOG_COLORS['kick'],
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name='สมาชิก', value=f'`{member}` (ID: {member.id})', inline=False)
    embed.add_field(name='ผู้สั่งเตะ', value=str(kick_entry.user), inline=True)
    embed.add_field(name='เหตุผล', value=kick_entry.reason or 'ไม่ระบุ', inline=True)
  else:
    role_names = ', '.join(r.name for r in member.roles if r.name != '@everyone') or 'ไม่มี'
    joined_days = (discord.utils.utcnow() - member.joined_at).days if member.joined_at else '?'
    embed = discord.Embed(
        title='📤 สมาชิกออกจากเซิร์ฟ',
        color=LOG_COLORS['leave'],
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name='สมาชิก', value=f'`{member}` (ID: {member.id})', inline=False)
    embed.add_field(name='อยู่ในเซิร์ฟมา', value=f'{joined_days} วัน', inline=True)
    embed.add_field(name='ยศที่มี', value=role_names[:1024], inline=False)

  embed.set_footer(text=f'เหลือสมาชิก {member.guild.member_count} คน')
  await send_log(member.guild, embed)


# ---------- แบน / ปลดแบน ----------
async def log_member_ban(guild: discord.Guild, user: discord.User):
  await db.record_event(guild.id, 'ban', {'user_id': user.id})
  ban_entry = await _find_audit_actor(guild, discord.AuditLogAction.ban, user.id)
  embed = discord.Embed(
      title='🔨 สมาชิกถูกแบน',
      color=LOG_COLORS['ban'],
      timestamp=discord.utils.utcnow(),
  )
  embed.add_field(name='สมาชิก', value=f'`{user}` (ID: {user.id})', inline=False)
  if ban_entry is not None:
    embed.add_field(name='ผู้สั่งแบน', value=str(ban_entry.user), inline=True)
    embed.add_field(name='เหตุผล', value=ban_entry.reason or 'ไม่ระบุ', inline=True)
  await send_log(guild, embed)


async def log_member_unban(guild: discord.Guild, user: discord.User):
  await db.record_event(guild.id, 'unban', {'user_id': user.id})
  embed = discord.Embed(
      title='🕊️ สมาชิกถูกปลดแบน',
      description=f'`{user}` (ID: {user.id})',
      color=LOG_COLORS['unban'],
      timestamp=discord.utils.utcnow(),
  )
  await send_log(guild, embed)


# ---------- เปลี่ยนยศ / ชื่อเล่น / timeout ----------
async def log_member_update(before: discord.Member, after: discord.Member):
  guild = after.guild

  # เปลี่ยนยศ
  before_roles = set(before.roles)
  after_roles = set(after.roles)
  added = after_roles - before_roles
  removed = before_roles - after_roles
  if added or removed:
    embed = discord.Embed(title='🏷️ ยศเปลี่ยนแปลง', color=LOG_COLORS['role'], timestamp=discord.utils.utcnow())
    embed.add_field(name='สมาชิก', value=f'{after.mention} (`{after}`)', inline=False)
    if added:
      embed.add_field(name='ได้รับยศ', value=', '.join(r.name for r in added), inline=True)
    if removed:
      embed.add_field(name='ถูกถอดยศ', value=', '.join(r.name for r in removed), inline=True)
    await send_log(guild, embed)

  # เปลี่ยนชื่อเล่น
  if before.nick != after.nick:
    embed = discord.Embed(title='✏️ เปลี่ยนชื่อเล่น', color=LOG_COLORS['nickname'], timestamp=discord.utils.utcnow())
    embed.add_field(name='สมาชิก', value=f'{after.mention} (`{after}`)', inline=False)
    embed.add_field(name='ชื่อเดิม', value=before.nick or before.name, inline=True)
    embed.add_field(name='ชื่อใหม่', value=after.nick or after.name, inline=True)
    await send_log(guild, embed)

  # timeout (mute ชั่วคราว)
  before_timeout = before.timed_out_until
  after_timeout = after.timed_out_until
  if before_timeout != after_timeout:
    if after_timeout is not None:
      entry = await _find_audit_actor(guild, discord.AuditLogAction.member_update, after.id)
      embed = discord.Embed(title='🔇 สมาชิกโดน Timeout', color=LOG_COLORS['timeout'], timestamp=discord.utils.utcnow())
      embed.add_field(name='สมาชิก', value=f'{after.mention} (`{after}`)', inline=False)
      embed.add_field(name='ปลด Timeout เมื่อ', value=_fmt_dt(after_timeout), inline=True)
      if entry is not None:
        embed.add_field(name='ผู้สั่ง', value=str(entry.user), inline=True)
        if entry.reason:
          embed.add_field(name='เหตุผล', value=entry.reason, inline=False)
    else:
      embed = discord.Embed(title='🔊 ปลด Timeout แล้ว', color=LOG_COLORS['timeout'], timestamp=discord.utils.utcnow())
      embed.add_field(name='สมาชิก', value=f'{after.mention} (`{after}`)', inline=False)
    await send_log(guild, embed)


# ---------- ข้อความถูกลบ / แก้ไข ----------
async def log_message_delete(message: discord.Message):
  if message.author.bot or message.guild is None:
    return
  content = message.content or '*(ไม่มีข้อความ / เป็นไฟล์แนบ)*'
  if len(content) > 500:
    content = content[:500] + '…'
  embed = discord.Embed(
      title='🗑️ ข้อความถูกลบ',
      color=LOG_COLORS['msg_delete'],
      timestamp=discord.utils.utcnow(),
  )
  embed.add_field(name='ผู้เขียน', value=f'{message.author.mention} (`{message.author}`)', inline=False)
  embed.add_field(name='ห้อง', value=message.channel.mention, inline=True)
  embed.add_field(name='ข้อความ', value=content, inline=False)
  await send_log(message.guild, embed)


async def log_message_edit(before: discord.Message, after: discord.Message):
  if before.author.bot or before.guild is None:
    return
  if before.content == after.content:
    return  # ไม่ได้แก้เนื้อหา (อาจแค่แปะ embed preview) ไม่ต้อง log
  before_content = (before.content or '*(ว่าง)*')[:400]
  after_content = (after.content or '*(ว่าง)*')[:400]
  embed = discord.Embed(
      title='📝 ข้อความถูกแก้ไข',
      color=LOG_COLORS['msg_edit'],
      timestamp=discord.utils.utcnow(),
  )
  embed.add_field(name='ผู้เขียน', value=f'{before.author.mention} (`{before.author}`)', inline=False)
  embed.add_field(name='ห้อง', value=f'{before.channel.mention} • [ไปที่ข้อความ]({after.jump_url})', inline=True)
  embed.add_field(name='ก่อนแก้', value=before_content, inline=False)
  embed.add_field(name='หลังแก้', value=after_content, inline=False)
  await send_log(before.guild, embed)


# ---------- ห้องเสียง ----------
async def log_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
  if before.channel == after.channel:
    return  # ไม่ได้เปลี่ยนห้อง (เช่นแค่ mute/deafen) ไม่ต้อง log

  if before.channel is None and after.channel is not None:
    title, desc = '🔊 เข้าห้องเสียง', f'{member.mention} เข้าห้อง {after.channel.mention}'
  elif before.channel is not None and after.channel is None:
    title, desc = '🔈 ออกจากห้องเสียง', f'{member.mention} ออกจากห้อง {before.channel.mention}'
  else:
    title, desc = '🔀 ย้ายห้องเสียง', f'{member.mention} ย้ายจาก {before.channel.mention} ไป {after.channel.mention}'

  embed = discord.Embed(title=title, description=desc, color=LOG_COLORS['voice'], timestamp=discord.utils.utcnow())
  await send_log(member.guild, embed)
