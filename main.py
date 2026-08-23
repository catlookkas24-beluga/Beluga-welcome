import os
import random
import datetime
import discord
from discord.ext import commands
from keep_alive import keep_alive

# ตั้งค่า Intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # ต้องเปิดเพื่อดักจับสมาชิกเข้า-ออก

bot = commands.Bot(command_prefix=commands.when_mentioned_or('!'), intents=intents)

# --- ล็อกให้ส่งข้อความเฉพาะห้องนี้เท่านั้น ---
WELCOME_CHANNEL_NAME = 'ต้อนรับ🎉'

# --- ยศที่จะแจกให้สมาชิกใหม่อัตโนมัติ ---
NEW_MEMBER_ROLE_NAME = 'Beluga ผู้มาเยือนเชิฟ'

# --- ระบบกด ✅ รับกฎ แลกยศ ---
RULES_REACT_CHANNELS = {'ต้อนรับ🎉', 'กฏ📜'}
RULES_REACT_EMOJI = '✅'
RULES_REACT_ROLE_NAME = 'Beluga ตัวน้อย'

# --- ระบบยศ "ผู้บุกเบิก" 20 คนแรกของกิจกรรมเปิดตัว ---
# นับจากจำนวนคนที่มียศนี้อยู่จริงในเซิร์ฟ (ไม่ใช่ไฟล์แยก) กัน Render รีเซ็ตข้อมูลตอน deploy ใหม่
PIONEER_ROLE_NAME = '🐱ผู้บุกเบิก Beluga🎉'
PIONEER_LIMIT = 20
PIONEER_EVENT_START = datetime.date(2026, 8, 5)
PIONEER_EVENT_END = datetime.date(2026, 8, 10)

# --- ระบบกดรีแอคชั่นรับยศเองในห้อง "รับยศต่างๆ" ---
# กด 🎤 = รับยศ Beluga ธรรมดา (ต้องอยู่เซิร์ฟครบ 7 วัน) / กด 👍 = รับยศ Beluga วัยกลาง (ต้องอยู่เซิร์ฟครบ 30 วัน)
ROLE_CLAIM_CHANNEL_NAME = 'รับยศต่างๆ'
ROLE_CLAIM_MAP = {
    '🎤': ('Beluga ธรรมดา', 7),
    '👍': ('Beluga วัยกลาง', 30),
}

# --- เนื้อหากฎของเซิร์ฟเวอร์ (ใช้กับคำสั่ง !กฏ) ---
SERVER_RULES_TEXT = (
    "✅หมายเหตุก่อนอ่าน: เซิร์ฟเวอร์แห่งนี้มีวัฒนธรรมการ \"ด่าแบบพองาม\" เป็นเอกลักษณ์ประจำถิ่น "
    "ผู้ดูแลระบบรับทราบและยอมรับพฤติกรรมดังกล่าวอย่างเป็นทางการ ตราบใดที่ยังอยู่ในขอบเขตของความสนุกสนานร่วมกัน "
    "มิใช่การกลั่นแกล้งอย่างจริงจัง\n\n"
    "**กฎระเบียบของเซิร์ฟเวอร์ Beluga มีดังนี้**\n"
    "กรุณาอ่านและปฏิบัติตามอย่างเคร่งครัด เพื่อความสงบเรียบร้อยของชุมชน\n\n"
    "**ข้อ 1 — การใช้ถ้อยคำ**\n"
    "ห้ามใช้คำหยาบคายในลักษณะที่ก่อให้เกิดความเสื่อมเสียแก่ผู้อื่นโดยไม่สมควร\n"
    "(หมายเหตุ: ด่ากันพองามได้ ถือเป็นวัฒนธรรมท้องถิ่นของเซิร์ฟนี้)\n\n"
    "**ข้อ 2 — การส่งข้อความซ้ำ**\n"
    "ห้ามส่งข้อความ รูปภาพ หรืออีโมจิซ้ำในลักษณะรบกวนการสนทนาปกติของสมาชิกท่านอื่น\n"
    "(ผู้ฝ่าฝืนจะได้รับสถานะ \"ห้ามพูด\" ชั่วคราว เพื่อให้เวลาไตร่ตรองพฤติกรรม)\n\n"
    "**ข้อ 3 — การประชาสัมพันธ์**\n"
    "ห้ามเผยแพร่ลิงก์เชิญเซิร์ฟเวอร์อื่นหรือช่องทางภายนอกใดๆ โดยไม่ได้รับอนุญาตจากผู้ดูแลระบบก่อน\n"
    "(ฝ่าฝืนข้อนี้ บอทจะเป็นผู้ตัดสินโทษเอง และบอทไม่มีความปรานี)\n\n"
    "**ข้อ 4 — ความเหมาะสมของเนื้อหา**\n"
    "ห้ามเผยแพร่เนื้อหาที่ไม่เหมาะสมสำหรับผู้ชมทั่วไป (NSFW) ในทุกช่องทางของเซิร์ฟเวอร์นี้โดยเด็ดขาด\n\n"
    "**ข้อ 5 — ความสัมพันธ์ระหว่างสมาชิก**\n"
    "สมาชิกทุกท่านพึงปฏิบัติต่อกันด้วยความเคารพในขั้นพื้นฐานของมนุษย์\n"
    "(การหยอกล้อเป็นเรื่องปกติของที่นี่ แต่การกลั่นแกล้งจนผู้อื่นเดือดร้อนจริง ถือเป็นความผิดร้ายแรง)\n\n"
    "**ข้อ 6 — ประเด็นอ่อนไหว**\n"
    "การสนทนาเรื่องการเมืองหรือประเด็นขัดแย้งทางความเชื่อ ให้ใช้วิจารณญาณและความสุภาพเป็นที่ตั้ง\n"
    "(หากบทสนทนาเริ่มเดือด ขอความกรุณาย้ายไปที่ข้อความส่วนตัว)\n\n"
    "**ข้อ 7 — การปฏิบัติตามคำสั่งผู้ดูแล**\n"
    "สมาชิกพึงให้ความร่วมมือกับผู้ดูแลระบบและผู้ควบคุมดูแล (Moderator) ในทุกกรณี\n"
    "(ยกเว้นเมื่อบอทเป็นผู้พูด กรณีนั้นไม่มีใครฟังบอทอยู่แล้ว)\n\n"
    "**ข้อ 8 — ลำดับขั้นของสมาชิก**\n"
    "สมาชิกใหม่จะได้รับสถานะ \"ผู้มาเยือน\" โดยอัตโนมัติ และต้องดำเนินการยอมรับกฎระเบียบนี้ "
    "ก่อนจะได้รับสิทธิ์ในการสื่อสารเต็มรูปแบบ\n\n"
    "**ข้อ 9 — การแอบอ้างตัวตน**\n"
    "ห้ามแอบอ้าง ปลอมตัว หรือสร้างความเข้าใจผิดว่าเป็นผู้ดูแลระบบ ผู้ควบคุมดูแล หรือบอทประจำเซิร์ฟเวอร์ "
    "ไม่ว่าจะด้วยชื่อ รูปภาพ หรือวิธีการใดก็ตาม\n"
    "(บอทตัวจริงมีแค่ตัวเดียว ถ้าเจอตัวปลอมคือมิจฉาชีพแน่นอน)\n\n"
    "**ข้อ 10 — ความปลอดภัยทางไซเบอร์**\n"
    "ห้ามเผยแพร่ลิงก์หรือไฟล์ที่เป็นอันตราย เช่น มัลแวร์ ฟิชชิง หรือเนื้อหาที่มีเจตนาหลอกลวงเพื่อขโมยข้อมูลส่วนตัวของสมาชิกท่านอื่นโดยเด็ดขาด\n"
    "(ผู้ฝ่าฝืนจะถูกดำเนินการทันทีโดยไม่มีการเตือนล่วงหน้า เนื่องจากเป็นภัยร้ายแรงต่อความปลอดภัยของทุกคน)\n\n"
    "**ข้อ 11 — บทลงโทษ**\n"
    "การฝ่าฝืนกฎข้อใดข้อหนึ่งข้างต้น อาจส่งผลให้ได้รับโทษตามความเหมาะสม ตั้งแต่การเตือน การจำกัดสิทธิ์ "
    "ไปจนถึงการยุติสมาชิกภาพอย่างถาวร\n\n"
    "เซิร์ฟเวอร์แห่งนี้ขอสงวนสิทธิ์ในการตีความและบังคับใช้กฎระเบียบข้างต้นแต่เพียงผู้เดียว "
    "การเข้าร่วมเซิร์ฟเวอร์ถือว่าท่านยินยอมรับทุกข้อโดยปริยาย 🗿\n\n"
    "⚠️ **หมายเหตุสำคัญ**: หากมีกรณีการทักหรือรบกวนสมาชิกท่านอื่นซ้ำๆ จนเกินขอบเขตความสมควร "
    "(เช่น ทักตื๊อ ทักแบบสร้างความอึดอัด หรือตามรังควานในหลายช่องทาง) โดยที่อีกฝ่ายแสดงความไม่สบายใจหรือขอให้หยุดแล้ว "
    "ผู้ดูแลระบบจะพิจารณาโทษ ตั้งแต่การเตือนไปจนถึงการเตะออกจากเซิร์ฟเวอร์ โดยไม่จำเป็นต้องรอให้เกิดความเสียหายร้ายแรงก่อน"
)

SERVER_RANK_TEXT = (
    "🌱 **เรื่องยศและลำดับขั้น**\n"
    "สมาชิกที่ต้องการเลื่อนยศให้สูงขึ้นจากสถานะเริ่มต้น จะต้องอยู่ในเซิร์ฟเวอร์นี้เป็นระยะเวลาต่อเนื่อง "
    "โดยไม่ฝ่าฝืนกฎข้อใดข้อหนึ่งจากทั้ง 11 ข้อข้างต้น ยศจะไม่ได้มาจากการขอหรือการซื้อ "
    "แต่ได้มาจากความประพฤติที่สม่ำเสมอและระยะเวลาสะสมสิทธิ์ที่ได้รับ ดังนี้\n\n"
    "✅ อยู่ครบ 1 สัปดาห์ สามารถส่งรูปภาพในห้องแชทได้\n"
    "✅ อยู่ครบ 1 เดือน สามารถเข้าร่วมช่องเสียง/โทรคุยกันได้\n"
    "(พูดง่ายๆ คือ อยู่นานๆ แล้วไม่ทำตัวแย่ ยศจะมาหาเอง)\n\n"
    "**หากครบกำหนดแล้วยังไม่ได้รับยศ**: สมาชิกที่มั่นใจว่าตนเองอยู่ในเซิร์ฟเวอร์ครบตามระยะเวลาที่กำหนดแล้ว "
    "แต่ยังไม่ได้รับยศ สามารถทักข้อความส่วนตัว (DM) หาผู้ดูแลระบบ เพื่อแจ้งตรวจสอบได้\n\n"
    "🚨 ห้ามโกหกเรื่องระยะเวลาที่อยู่ในเซิร์ฟเวอร์โดยเด็ดขาด ผู้ดูแลระบบสามารถตรวจสอบวันเข้าร่วมจริงได้เสมอ "
    "หากพบว่าจงใจให้ข้อมูลเท็จเพื่อเร่งขอยศ จะถือเป็นความผิดร้ายแรง และมีโทษรุนแรงกว่าการฝ่าฝืนกฎข้อทั่วไป\n\n"
    "📩 มีปัญหาอะไร DM หาผู้ดูแลได้เลย อย่าเพิ่งเปิดศึกในห้องแชต ผู้ดูแลจะช่วยดูให้ 🗿\n"
    "โปรดกด ✅ ใน Discord ถือว่าคุณได้รับข้อเสนอแล้วและเอายศ Beluga ตัวน้อย"
)


@bot.event
async def on_ready():
  print(f'🗿 บอท {bot.user.name} พร้อมป่วนสมาชิกใหม่แล้ว!')
  await bot.change_presence(activity=discord.Game(name='รอต้อนรับเหยื่อใหม่ 🗿'))


def get_welcome_channel(guild):
  """หาห้องที่จะส่งข้อความต้อนรับ (ล็อกเฉพาะห้องที่ตั้งชื่อไว้เท่านั้น)"""
  for ch in guild.text_channels:
    if ch.name == WELCOME_CHANNEL_NAME:
      return ch
  # ถ้าไม่เจอห้องชื่อนี้ในเซิร์ฟ จะไม่ส่งข้อความไปที่ไหนเลย
  return None


@bot.event
async def on_raw_reaction_add(payload):
  # ข้ามถ้าเป็นบอทกดเอง หรือไม่มีข้อมูลสมาชิก
  if payload.member is None or payload.member.bot:
    return

  channel = bot.get_channel(payload.channel_id)
  guild = bot.get_guild(payload.guild_id)
  if guild is None:
    return

  # --- ระบบเดิม: กด ✅ ในห้องต้อนรับ/กฏ📜 รับยศ Beluga ตัวน้อย ---
  if getattr(channel, 'name', None) in RULES_REACT_CHANNELS and str(payload.emoji) == RULES_REACT_EMOJI:
    role = discord.utils.get(guild.roles, name=RULES_REACT_ROLE_NAME)
    if role is None:
      print(f'⚠️ ไม่พบยศชื่อ "{RULES_REACT_ROLE_NAME}" ในเซิร์ฟ')
      return
    member = payload.member
    if role in member.roles:
      return
    try:
      await member.add_roles(role)
      await channel.send(f'🗿✅🎊 {who_text(member)} กด ✅ รับกฎแล้ว ยินดีด้วย ได้ยศ **{RULES_REACT_ROLE_NAME}** ไปเลย! 🐣💫')
    except discord.Forbidden:
      print(f'⚠️ แจกยศ "{RULES_REACT_ROLE_NAME}" ให้ {member} ไม่ได้ เพราะบอทไม่มีสิทธิ์ Manage Roles หรือยศบอทอยู่ต่ำกว่ายศนี้')
    except discord.HTTPException as e:
      print(f'⚠️ แจกยศให้ {member} ไม่สำเร็จ: {e}')
    return

  # --- ระบบใหม่: กด 🎤 / 👍 ในห้อง "รับยศต่างๆ" รับยศตามเงื่อนไขวันที่อยู่เซิร์ฟ ---
  if getattr(channel, 'name', None) == ROLE_CLAIM_CHANNEL_NAME and str(payload.emoji) in ROLE_CLAIM_MAP:
    role_name, min_days = ROLE_CLAIM_MAP[str(payload.emoji)]
    member = payload.member

    role = discord.utils.get(guild.roles, name=role_name)
    if role is None:
      print(f'⚠️ ไม่พบยศชื่อ "{role_name}" ในเซิร์ฟ')
      return

    if role in member.roles:
      return  # มียศนี้อยู่แล้ว ไม่ต้องทำอะไรต่อ

    joined_at = member.joined_at
    days_in_server = (discord.utils.utcnow() - joined_at).days if joined_at else 0

    if days_in_server < min_days:
      # ยังไม่ครบเงื่อนไข → ลบรีแอคชั่นทิ้ง กันคนเกรียนมากดก่อนเวลา
      try:
        msg = await channel.fetch_message(payload.message_id)
        await msg.remove_reaction(payload.emoji, member)
      except (discord.Forbidden, discord.HTTPException):
        pass
      remaining = min_days - days_in_server
      try:
        await member.send(
            f'🗿 ยังไม่ครบเงื่อนไขรับยศ **{role_name}** นะ ต้องอยู่ในเซิร์ฟ Beluga ให้ครบ {min_days} วัน'
            f' ตอนนี้อยู่มาแล้ว {days_in_server} วัน เหลืออีก {remaining} วันครับ ใจเย็นๆ นะจ๊ะ'
        )
      except discord.Forbidden:
        pass  # เปิด DM ไม่ได้ก็ปล่อยผ่าน ไม่ต้องแจ้งอะไรในห้อง กันโพสต์รก
      return

    try:
      await member.add_roles(role)
      await channel.send(f'🎉📅✨ {who_text(member)} อยู่ครบ {min_days} วันแล้ว ได้รับยศ **{role_name}** เรียบร้อย! 🏅🎊')
    except discord.Forbidden:
      print(f'⚠️ แจกยศ "{role_name}" ให้ {member} ไม่ได้ เพราะบอทไม่มีสิทธิ์ Manage Roles หรือยศบอทอยู่ต่ำกว่ายศนี้')
    except discord.HTTPException as e:
      print(f'⚠️ แจกยศให้ {member} ไม่สำเร็จ: {e}')


async def grant_pioneer_role_if_eligible(member, channel):
  """แจกยศผู้บุกเบิกให้ 20 คนแรกที่เข้าเซิร์ฟช่วงกิจกรรม (นับจากยศจริงในเซิร์ฟ กันข้อมูลหายตอน redeploy)"""
  today = datetime.date.today()
  if not (PIONEER_EVENT_START <= today <= PIONEER_EVENT_END):
    return  # นอกช่วงกิจกรรม ไม่แจก

  role = discord.utils.get(member.guild.roles, name=PIONEER_ROLE_NAME)
  if role is None:
    print(f'⚠️ ไม่พบยศชื่อ "{PIONEER_ROLE_NAME}" ในเซิร์ฟ (ข้ามการแจกยศผู้บุกเบิก)')
    return

  current_holders = len(role.members)  # นับจากคนที่มียศนี้จริงๆ ตอนนี้ (รวมที่แจกมือไปก่อนหน้าด้วย)
  if current_holders >= PIONEER_LIMIT:
    return  # ครบ 20 คนแล้ว ไม่แจกเพิ่ม

  try:
    await member.add_roles(role)
    position = current_holders + 1
    if channel is not None:
      await channel.send(
          f'🏆🎖️✨ ยินดีด้วย! {who_text(member)} คือผู้บุกเบิกคนที่ **{position}/{PIONEER_LIMIT}** ของเซิร์ฟนี้ 🚀🎉'
          f' ได้รับยศ **{PIONEER_ROLE_NAME}** ฟรีทันที 🎉'
      )
  except discord.Forbidden:
    print(
        f'⚠️ แจกยศ "{PIONEER_ROLE_NAME}" ให้ {member} ไม่ได้'
        ' เพราะบอทไม่มีสิทธิ์ Manage Roles หรือยศบอทอยู่ต่ำกว่ายศนี้'
    )
  except discord.HTTPException as e:
    print(f'⚠️ แจกยศผู้บุกเบิกให้ {member} ไม่สำเร็จ: {e}')


# --- แบนเนอร์ต้อนรับ (GIF/รูป) — ใส่ URL ที่ได้จากการอัปโหลดรูปลงห้อง Discord แล้ว Copy Link มาแปะตรงนี้ ---
WELCOME_BANNER_URLS = [
    "https://cdn.discordapp.com/attachments/1537605943485923378/1540957099310190612/IMG_6356.gif",
    "https://cdn.discordapp.com/attachments/1537605943485923378/1540957099616370688/IMG_6355.gif",
    "https://cdn.discordapp.com/attachments/1537605943485923378/1540957099960311878/IMG_6354.gif",
    "https://cdn.discordapp.com/attachments/1537605943485923378/1540957100375678996/IMG_6352.gif",
]


def who_text(member):
  """สร้างข้อความเรียกชื่อสมาชิก: ทั้ง mention (ปิ้งแจ้งเตือนจริง) + ชื่อที่แสดงเป็นตัวหนังสือกำกับไว้
  กันปัญหา mention ขึ้นเป็นเลขไอดีดิบๆ ตอนสมาชิกเพิ่งเข้าเซิร์ฟใหม่ๆ (Discord ยังไม่ resolve ชื่อให้ทันที)"""
  return f'{member.mention} (**{member.display_name}**)'


@bot.event
async def on_member_join(member):
  # --- แจกยศให้สมาชิกใหม่อัตโนมัติ ---
  role = discord.utils.get(member.guild.roles, name=NEW_MEMBER_ROLE_NAME)
  if role is not None:
    try:
      await member.add_roles(role)
    except discord.Forbidden:
      print(
          f'⚠️ แจกยศ "{NEW_MEMBER_ROLE_NAME}" ให้ {member} ไม่ได้'
          ' เพราะบอทไม่มีสิทธิ์ Manage Roles หรือยศบอทอยู่ต่ำกว่ายศนี้'
      )
    except discord.HTTPException as e:
      print(f'⚠️ แจกยศให้ {member} ไม่สำเร็จ: {e}')
  else:
    print(f'⚠️ ไม่พบยศชื่อ "{NEW_MEMBER_ROLE_NAME}" ในเซิร์ฟ')

  channel = get_welcome_channel(member.guild)

  # --- เช็คและแจกยศผู้บุกเบิก (20 คนแรกของกิจกรรม) ---
  await grant_pioneer_role_if_eligible(member, channel)

  if channel is None:
    return

  who = who_text(member)

  welcome_messages = [
      # กวนล้วนๆ (ของเดิม)
      f'🗿😏 อ้าวเฮ้ย {who} เข้ามาทำไมอ่ะ ที่นี่ไม่มีอะไรดีให้หรอกนะ 🚪',
      f'🗿🎉✨ ยินดีต้อนรับ {who} เข้าสู่เซิร์ฟที่พังที่สุดในจักรวาล 💥',
      f'🗿👀 {who} มาแล้ว! เตรียมตัวโดนแกล้งได้เลยจ้า 😈🔥',
      f'🗿⏳ เอ้า สมาชิกใหม่ {who} ดูท่าทางแล้วอยู่ได้ไม่เกิน 3 วันแน่นอน 📉',
      f'🗿😱 {who} เข้ามาแบบไม่มีใครเชิญเลยนะ กล้ามาก 💀',
      f'🗿⛓️ ยินดีต้อนรับสู่คุกที่ไม่มีทางออก {who} 😈🔒',
      f'🗿🤔 {who} หวังว่าจะทนคนในนี้ได้นะ กูก็ไม่ค่อยมั่นใจเท่าไหร่ 😅',
      f'🗿🃏 อุ๊ยตายวายป่วง มีคนใหม่ {who} เข้ามาสมัครเป็นตัวตลกคนต่อไป 🎪',
      f'🗿❓ {who} มาแล้วจ้า... ใครก็ได้บอกมันหน่อยว่าที่นี่ไม่ปกติ 🚨',
      # จริงใจแต่กวนตีน (ของใหม่)
      f'🗿💖 ยินดีต้อนรับนะ {who} จริงๆ นะ ไม่ได้กวน... โอเคกวนนิดหน่อย แต่ดีใจที่มึงมาจริงๆ 🥹',
      f'🗿✨ เฮ้ {who} เข้ามาแล้วนะ บอกตรงๆ ว่าดีใจ 😊 (แต่ก็แอบสงสัยว่ามึงมาถูกที่รึเปล่า 🤨)',
      f'🗿🌟 {who} มาถึงแล้ว! เซิร์ฟนี้อาจดูป่วนๆ แต่ทุกคนที่นี่ยินดีต้อนรับมึงจริงๆ นะ 🤗 (กวนได้ แต่ใจดีเสมอ 💕)',
      f'🗿👨‍👩‍👧‍👦 ต้อนรับ {who} เข้าสู่ครอบครัวสุดกวนของเรา พูดตรงๆ คือดีใจที่มึงเลือกมาอยู่ที่นี่ 🎊',
      f'🗿😆 {who} เข้ามาแล้วเหรอ... งั้นเตรียมโดนแกล้งได้เลย 🤣 (ล้อเล่นนะ ยินดีต้อนรับจริงๆ ครับ 🙏)',
      f'🗿💬 ไม่รู้จะพูดจริงจังยังไงดี งั้นพูดแบบกวนๆ ก็ได้: ยินดีที่ได้รู้จัก {who} หวังว่าจะสนุกกับที่นี่นะ 🎈🌈',
  ]

  event_nudges = [
      '🎉📢 อ้อ ไปดูห้อง #กิจกรรม🎉 ด้วยนะ พลาดแล้วจะมานั่งเสียใจทีหลัง 😭',
      '🎉🎁 ปล. มีกิจกรรมเปิดตัวอยู่ที่ห้อง #กิจกรรม🎉 ใครไม่ไปดูถือว่าพลาดของฟรี ✨',
      '🎉👀 แนะนำให้รีบไปแอบดูห้อง #กิจกรรม🎉 ก่อนใคร เดี๋ยวของหมด ⏰',
      '🎉💡 เออ เกือบลืม ไปส่องห้อง #กิจกรรม🎉 หน่อย มีของฟรีให้ลุ้นด้วยนะ 🎰 (จริงจังนะครั้งนี้)',
      '🎉🎈 ห้อง #กิจกรรม🎉 มีอะไรลุ้นอยู่ ไปดูซะ ไม่งั้นเดี๋ยวมาถามทีหลังว่าทำไมไม่มีใครบอก 🤷',
  ]

  role_nudges = [
      '🐣📜 อ้อ ตอนนี้มึงยังพูดในเซิร์ฟไม่ได้นะ ไปกด ✅ ในห้อง #กฏ📜 ซะ จะได้ยศ "Beluga ตัวน้อย" 🐥 แล้วค่อยมาคุยกับกูได้',
      '🐣🤐 เป็นใบ้อยู่แบบนี้ไปอีกนานนะถ้าไม่ไปรับยศ "Beluga ตัวน้อย" ที่ห้อง #กฏ📜 รีบไปกด ✅ ซะ ⏳',
      '🐣🔇 ยศตอนนี้พูดไม่ได้นะจ๊ะ ไปที่ห้อง #กฏ📜 กด ✅ รับยศ "Beluga ตัวน้อย" ก่อน 🐥 แล้วค่อยมากวนกับกูต่อ 😎',
      '🐣😢 เสียดายนะ มึงยังแชทไม่ได้เพราะไม่มียศ ไปห้อง #กฏ📜 กด ✅ รับ "Beluga ตัวน้อย" ซะเร็วๆ นี่ ⚡',
      '🐣🏃 แนะนำให้รีบไปห้อง #กฏ📜 กด ✅ รับยศ "Beluga ตัวน้อย" ไม่งั้นได้แต่ยืนมองคนอื่นคุยกันไปอีกนาน 👀💤',
  ]

  embed = discord.Embed(
      description='✨🎊 ' + random.choice(welcome_messages) + '\n\n' + random.choice(event_nudges) + '\n\n' + random.choice(role_nudges) + ' 🌈',
      color=discord.Color.dark_grey(),
  )
  embed.set_thumbnail(url=member.display_avatar.url)
  if WELCOME_BANNER_URLS:
    embed.set_image(url=random.choice(WELCOME_BANNER_URLS))
  embed.set_footer(text=f'🐳 สมาชิกคนที่ {member.guild.member_count} ของเซิร์ฟนี้ ✨')

  await channel.send(embed=embed)


@bot.event
async def on_member_remove(member):
  channel = get_welcome_channel(member.guild)
  if channel is None:
    return

  goodbye_messages = [
      f'🗿 {member.name} หนีไปแล้ว... เข้าใจนะ ที่นี่มันทนไม่ได้จริง',
      f'🗿 อีกคนออกไปแล้ว {member.name} ไปดีมาดีนะ (ไม่ต้องกลับมาก็ได้)',
      f'🗿 {member.name} ออกจากเซิร์ฟไปแล้ว บอกได้เลยว่า... ไม่มีใครเสียใจ',
      f'🗿 เซิร์ฟนี้เพิ่งเสียสมาชิกไป 1 คน คือ {member.name} ไว้อาลัย 3 วิ',
      f'🗿 {member.name} หายไปแล้ว คงทนคนกวนในนี้ไม่ได้สินะ 😂',
  ]

  await channel.send(random.choice(goodbye_messages))


# --- คำสั่งทดสอบข้อความต้อนรับโดยไม่ต้องมีคนเข้าจริง ---
@bot.command()
async def ทดสอบต้อนรับ(ctx):
  await on_member_join(ctx.author)


@bot.command()
async def เหลือผู้บุกเบิก(ctx):
  """เช็คว่ายศผู้บุกเบิกเหลือกี่ที่"""
  role = discord.utils.get(ctx.guild.roles, name=PIONEER_ROLE_NAME)
  if role is None:
    await ctx.send(f'⚠️ ไม่พบยศชื่อ "{PIONEER_ROLE_NAME}" ในเซิร์ฟ')
    return
  current_holders = len(role.members)
  remaining = max(0, PIONEER_LIMIT - current_holders)
  today = datetime.date.today()
  if today > PIONEER_EVENT_END:
    await ctx.send(f'⌛ กิจกรรมผู้บุกเบิกจบไปแล้ว มีคนได้ยศนี้ไปทั้งหมด {current_holders}/{PIONEER_LIMIT} คน')
  elif today < PIONEER_EVENT_START:
    await ctx.send(f'📅 กิจกรรมผู้บุกเบิกยังไม่เริ่ม (เริ่ม {PIONEER_EVENT_START.strftime("%d/%m/%Y")})')
  else:
    await ctx.send(f'🏆 ยศผู้บุกเบิกเหลืออีก **{remaining}/{PIONEER_LIMIT}** ที่ รีบชวนเพื่อนเข้ามาก่อนหมด!')


@bot.command(name='กฎ', aliases=['กฏ', 'rules'])
async def show_rules(ctx):
  """แสดงกฎทั้งหมดของเซิร์ฟเวอร์"""
  embed1 = discord.Embed(
      title='📜 กฎของเซิร์ฟเวอร์ Beluga',
      description=SERVER_RULES_TEXT,
      color=discord.Color.dark_grey(),
  )
  embed2 = discord.Embed(
      title='🏅 ยศและลำดับขั้น',
      description=SERVER_RANK_TEXT,
      color=discord.Color.dark_grey(),
  )
  try:
    await ctx.send(embeds=[embed1, embed2])
  except discord.Forbidden:
    await ctx.send('⚠️ บอทไม่มีสิทธิ์ส่งข้อความ/Embed ในห้องนี้ครับ')
  except discord.HTTPException as e:
    print(f'⚠️ ส่งกฎไม่สำเร็จ: {e}')
    try:
      await ctx.send('⚠️ ส่งกฎไม่สำเร็จ ลองใช้คำสั่งอีกครั้ง')
    except discord.HTTPException:
      pass


@bot.event
async def on_message(message):
  # ไม่ตอบข้อความของบอทตัวเอง
  if message.author.bot:
    return

  # อนุญาตให้พิมพ์ "กฎ" หรือ "กฏ" ตรง ๆ ในห้องกฎได้ โดยไม่ต้องใส่ !
  if (message.channel.name in {'กฏ📜', 'กฎ📜'}
      and message.content.strip() in {'กฎ', 'กฏ', 'rules', '!กฎ', '!กฏ', '!rules'}):
    ctx = await bot.get_context(message)
    await show_rules.callback(ctx)
    return

  # ต้องมีบรรทัดนี้ ไม่งั้นคำสั่ง @bot.command ทั้งหมดจะไม่ทำงาน
  await bot.process_commands(message)


@bot.event
async def on_command_error(ctx, error):
  # แจ้งสาเหตุที่คำสั่งไม่ทำงาน แทนการเงียบ
  if isinstance(error, commands.CommandNotFound):
    return
  if isinstance(error, commands.MissingPermissions):
    await ctx.send('⚠️ คุณไม่มีสิทธิ์ใช้คำสั่งนี้ครับ')
    return
  print(f'⚠️ Command error [{getattr(ctx.command, "name", "unknown")}]: {error!r}')
  try:
    await ctx.send(f'⚠️ คำสั่งทำงานไม่สำเร็จ: `{type(error).__name__}`')
  except discord.HTTPException:
    pass


# เปิดเว็บเซิร์ฟเวอร์เล็กๆ ไว้ให้ Render เห็นว่า service เปิด port อยู่
keep_alive()

# รันบอทด้วย Token จาก Environment Variable (อย่า hardcode token ในไฟล์!)
token = os.environ.get('DISCORD_TOKEN')
if not token:
  raise RuntimeError(
      'ไม่พบ DISCORD_TOKEN — กรุณาตั้งค่า Environment Variable ชื่อ'
      ' DISCORD_TOKEN ก่อนรันบอท (เช่นใน Render Environment tab)'
  )

bot.run(token)
