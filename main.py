import os, asyncio, logging, time, aiohttp, re
from aiogram import Bot, Dispatcher, types, executor
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from motor.motor_asyncio import AsyncIOMotorClient
from aiohttp import web

# --- SOZLAMALAR ---
API_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', 0))
MONGO_URL = os.getenv('MONGO_URL')

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN, parse_mode="HTML")
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

cluster = AsyncIOMotorClient(MONGO_URL)
db = cluster["downloader_bot"]
users_col = db["users"]
channels_col = db["channels"]

class AdminStates(StatesGroup):
    waiting_for_ad = State()
    waiting_for_channel = State()

# --- YUKLASH MANTIQI (API FALLBACK) ---

async def get_cobalt_url(url, is_audio=False):
    """Cobalt API orqali yuklash linkini olish"""
    instances = [
        "https://api.cobalt.tools/api/json",
        "https://cobalt-api.kwiat.xyz/api/json",
        "https://api.cobalt.red/api/json"
    ]
    payload = {
        "url": url,
        "vQuality": "360",
        "isAudioOnly": is_audio,
        "filenameStyle": "pretty"
    }
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    
    async with aiohttp.ClientSession() as session:
        for api in instances:
            try:
                async with session.post(api, json=payload, headers=headers, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("url"): return data["url"]
            except: continue
    return None

async def get_piped_url(url):
    """YouTube uchun zaxira API (Piped)"""
    try:
        video_id_match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11}).*", url)
        if not video_id_match: return None
        video_id = video_id_match.group(1)
        
        api_url = f"https://pipedapi.kavin.rocks/streams/{video_id}"
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # 360p formatini qidirish
                    streams = data.get("videoStreams", [])
                    for s in streams:
                        if s.get("quality") == "360p": return s["url"]
                    if streams: return streams[0]["url"]
    except: return None
    return None

# --- HANDLERLAR ---

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await users_col.update_one({"user_id": message.from_id}, {"$set": {"user_id": message.from_id}}, upsert=True)
    await message.answer("👋 <b>Xush kelibsiz!</b>\n\nMen YouTube, Instagram va TikTok-dan videolarni 360p sifatda yuklayman.\n📩 Havolani yuboring!")

@dp.message_handler(regexp=r'(https?://[^\s]+)')
async def handle_url(message: types.Message):
    # Majburiy obuna
    channels = await channels_col.find().to_list(length=10)
    for ch in channels:
        try:
            m = await bot.get_chat_member(ch['ch_id'], message.from_id)
            if m.status == 'left':
                kb = InlineKeyboardMarkup().add(InlineKeyboardButton("A'zo bo'lish", url=ch['url']))
                return await message.answer("⚠️ Botdan foydalanish uchun kanalga a'zo bo'ling!", reply_markup=kb)
        except: continue

    kb = InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("🎬 Video (360p)", callback_data="dl_vid"),
        InlineKeyboardButton("🎵 Audio (MP3)", callback_data="dl_aud")
    )
    await message.reply("⚙️ <b>Tanlang:</b>", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('dl_'))
async def dl_callback(call: CallbackQuery):
    is_audio = call.data == "dl_aud"
    url = call.message.reply_to_message.text
    status = await call.message.edit_text("🛰 <b>Qidirilmoqda...</b>")
    
    # 1-urinish: Cobalt
    final_url = await get_cobalt_url(url, is_audio)
    
    # 2-urinish: Piped (faqat YouTube video bo'lsa)
    if not final_url and not is_audio and ("youtube" in url or "youtu.be" in url):
        await status.edit_text("🔄 <b>Zaxira serveriga ulanmoqda...</b>")
        final_url = await get_piped_url(url)

    if not final_url:
        return await status.edit_text("❌ <b>Xatolik!</b>\nVideo topilmadi yoki API hozirda band.")

    await status.edit_text("📤 <b>Yuborilmoqda...</b>")
    try:
        if is_audio:
            await bot.send_audio(call.from_user.id, final_url, caption="@ZarraVideoBot")
        else:
            await bot.send_video(call.from_user.id, final_url, caption="@ZarraVideoBot")
        await status.delete()
    except Exception as e:
        await status.edit_text(f"❌ <b>Xato:</b> Fayl hajmi juda katta yoki havola muddati o'tgan.")

# --- ADMIN PANEL ---

@dp.message_handler(commands=['admin'], user_id=ADMIN_ID)
async def admin(message: types.Message):
    kb = InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("📊 Stat", callback_data="a_stat"),
        InlineKeyboardButton("📢 Reklama", callback_data="a_msg"),
        InlineKeyboardButton("➕ Kanal", callback_data="a_add")
    )
    await message.answer("<b>Admin Panel:</b>", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == "a_stat", user_id=ADMIN_ID)
async def a_stat(call: CallbackQuery):
    count = await users_col.count_documents({})
    await call.message.answer(f"👤 Foydalanuvchilar: {count} ta")

@dp.callback_query_handler(lambda c: c.data == "a_msg", user_id=ADMIN_ID)
async def ad_start(call: CallbackQuery):
    await call.message.answer("Reklama yuboring:")
    await AdminStates.waiting_for_ad.set()

@dp.message_handler(state=AdminStates.waiting_for_ad, content_types=types.ContentTypes.ANY, user_id=ADMIN_ID)
async def ad_send(message: types.Message, state: FSMContext):
    users = await users_col.find().to_list(length=None)
    sent = 0
    for u in users:
        try:
            await message.copy_to(u['user_id'])
            sent += 1
            await asyncio.sleep(0.05)
        except: continue
    await state.finish()
    await message.answer(f"✅ {sent} ta foydalanuvchiga yuborildi.")

@dp.callback_query_handler(lambda c: c.data == "a_add", user_id=ADMIN_ID)
async def ch_start(call: CallbackQuery):
    await call.message.answer("ID va Link yuboring (Namuna: -100123 https://t.me/kanal):")
    await AdminStates.waiting_for_channel.set()

@dp.message_handler(state=AdminStates.waiting_for_channel, user_id=ADMIN_ID)
async def ch_save(message: types.Message, state: FSMContext):
    try:
        cid, url = message.text.split()
        await channels_col.insert_one({"ch_id": cid, "url": url})
        await state.finish()
        await message.answer("✅ Kanal qo'shildi!")
    except: await message.answer("Xato format!")

# --- WEB SERVER ---
async def web_h(r): return web.Response(text="Bot Active")
async def on_start(dp):
    app = web.Application(); app.router.add_get("/", web_h)
    runner = web.AppRunner(app); await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get("PORT", 10000)))
    asyncio.create_task(site.start())

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True, on_startup=on_start)
