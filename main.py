import os, asyncio, logging, time, aiohttp
from aiogram import Bot, Dispatcher, types, executor
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.contrib.fsm_storage.memory import MemoryStorage
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

# --- COBALT API FUNKSIYASI ---
async def fetch_from_cobalt(url, is_audio=False):
    api_url = "https://api.cobalt.tools/api/json"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    # 360p va kerakli sozlamalar
    payload = {
        "url": url,
        "vQuality": "360",
        "isAudioOnly": is_audio,
        "filenameStyle": "pretty"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, json=payload, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("url")
                return None
    except Exception as e:
        logging.error(f"API Error: {e}")
        return None

# --- HANDLERLAR ---
@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await users_col.update_one({"user_id": message.from_id}, {"$set": {"user_id": message.from_id}}, upsert=True)
    await message.answer("✨ <b>Assalomu alaykum!</b>\n\nMen YouTube, Instagram va TikTok-dan videolarni 360p sifatda yuklab beraman.\n\n📩 Havolani yuboring!")

@dp.message_handler(regexp=r'(https?://[^\s]+)')
async def handle_url(message: types.Message):
    # Majburiy obunani tekshirish (ixtiyoriy)
    channels = await channels_col.find().to_list(length=10)
    for ch in channels:
        try:
            member = await bot.get_chat_member(chat_id=ch['ch_id'], user_id=message.from_id)
            if member.status == 'left':
                kb = InlineKeyboardMarkup().add(InlineKeyboardButton("A'zo bo'lish", url=ch['url']))
                return await message.answer("⚠️ Botdan foydalanish uchun kanallarga obuna bo'ling!", reply_markup=kb)
        except: continue

    kb = InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("🎬 Video (360p)", callback_data="cb_vid"),
        InlineKeyboardButton("🎵 Audio (MP3)", callback_data="cb_aud")
    )
    await message.reply("⚙️ <b>Qanday formatda yuklaymiz?</b>", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('cb_'))
async def cb_callback(call: CallbackQuery):
    is_audio = call.data == "cb_aud"
    url = call.message.reply_to_message.text
    
    # Animatsiyali status
    status_msg = await call.message.edit_text("🛰 <b>API-ga so'rov yuborilmoqda...</b>")
    await asyncio.sleep(1)
    await status_msg.edit_text("🔹🔸🔹 <b>Video tayyorlanmoqda...</b>")
    
    download_url = await fetch_from_cobalt(url, is_audio)
    
    if not download_url:
        await status_msg.edit_text("❌ <b>Xatolik yuz berdi.</b>\nBu havola qo'llab-quvvatlanmaydi yoki API band.")
        return

    await status_msg.edit_text("📤 <b>Telegramga yuborilmoqda...</b>")
    
    try:
        # Link orqali yuborish (Telegram o'zi yuklab oladi)
        if is_audio:
            await call.message.answer_audio(download_url, caption="@Allsaver")
        else:
            await call.message.answer_video(download_url, caption="@Allsaver")
        await status_msg.delete()
    except Exception as e:
        logging.error(f"Send error: {e}")
        await status_msg.edit_text("❌ <b>Telegram yuborishni rad etdi.</b>\nVideo hajmi juda katta bo'lishi mumkin.")

# --- WEB SERVER (Render uchun) ---
async def web_h(r): return web.Response(text="Active")
async def on_start(dp):
    app = web.Application(); app.router.add_get("/", web_h)
    runner = web.AppRunner(app); await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get("PORT", 10000)))
    asyncio.create_task(site.start())

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True, on_startup=on_start)
