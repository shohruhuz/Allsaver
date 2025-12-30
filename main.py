import os, asyncio, logging
from aiogram import Bot, Dispatcher, types, executor
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from motor.motor_asyncio import AsyncIOMotorClient
from aiohttp import web
import yt_dlp
from shazamio import Shazam

# --- SOZLAMALAR ---
API_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', 0))
MONGO_URL = os.getenv('MONGO_URL')

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN, parse_mode="HTML")
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# --- MONGODB ---
cluster = AsyncIOMotorClient(MONGO_URL)
db = cluster["downloader_bot"]
users_col = db["users"]
channels_col = db["channels"]

class AdminStates(StatesGroup):
    waiting_for_ad = State()
    waiting_for_channel = State()

# --- YUKLASH FUNKSIYASI ---
async def download_media(url, mode, quality="720"):
    if not os.path.exists('downloads'): os.makedirs('downloads')
    ydl_opts = {
        'outtmpl': f'downloads/%(id)s.%(ext)s',
        'quiet': True,
        'noplaylist': True,
    }
    if mode == "mp3":
        ydl_opts['format'] = 'bestaudio/best'
        ydl_opts['postprocessors'] = [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '192'}]
    else:
        ydl_opts['format'] = f'bestvideo[height<={quality}]+bestaudio/best/best[height<={quality}]'
        ydl_opts['merge_output_format'] = 'mp4'

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))
        return ydl.prepare_filename(info).replace(".webm", ".mp4").replace(".m4a", ".mp3").replace(".mkv", ".mp4")

# --- MAJBURIY OBUNA ---
async def check_sub(user_id):
    channels = await channels_col.find().to_list(length=10)
    for ch in channels:
        try:
            member = await bot.get_chat_member(chat_id=ch['ch_id'], user_id=user_id)
            if member.status == 'left': return False
        except: continue
    return True

# --- HANDLERLAR ---
@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await users_col.update_one({"user_id": message.from_id}, {"$set": {"user_id": message.from_id}}, upsert=True)
    await message.answer("Salom! Video havolasini yuboring.")

@dp.message_handler(commands=['admin'], user_id=ADMIN_ID)
async def admin(message: types.Message):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("📊 Stat", callback_data="a_stat"),
           InlineKeyboardButton("📢 Reklama", callback_data="a_msg"),
           InlineKeyboardButton("➕ Kanal", callback_data="a_add"),
           InlineKeyboardButton("➖ Tozalash", callback_data="a_clr"))
    await message.answer("Admin Panel:", reply_markup=kb)

@dp.message_handler(regexp=r'(https?://[^\s]+)')
async def handle_url(message: types.Message):
    if not await check_sub(message.from_id):
        channels = await channels_col.find().to_list(length=10)
        kb = InlineKeyboardMarkup(row_width=1)
        for ch in channels: kb.add(InlineKeyboardButton("A'zo bo'lish", url=ch['url']))
        return await message.answer("Obuna bo'ling!", reply_markup=kb)

    url = message.text
    kb = InlineKeyboardMarkup(row_width=2)
    if "youtube" in url or "youtu.be" in url:
        kb.add(InlineKeyboardButton("720p 🎥", callback_data=f"dl_720_{url}"),
               InlineKeyboardButton("480p 🎥", callback_data=f"dl_480_{url}"),
               InlineKeyboardButton("MP3 🎵", callback_data=f"dl_mp3_{url}"))
    else:
        kb.add(InlineKeyboardButton("📥 Yuklash", callback_data=f"dl_best_{url}"))
    kb.add(InlineKeyboardButton("🔍 Shazam", callback_data=f"shz_{url}"))
    await message.answer("Tanlang:", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('dl_'))
async def dl_callback(call: CallbackQuery):
    _, q, url = call.data.split("_", 2)
    msg = await call.message.edit_text("⏳ Yuklanmoqda...")
    path = None
    try:
        path = await download_media(url, q, q if q.isdigit() else "720")
        with open(path, 'rb') as f:
            if q == "mp3": await call.message.answer_audio(f)
            else: await call.message.answer_video(f)
        await msg.delete()
    except: await call.message.answer("Xato!")
    finally:
        if path and os.path.exists(path): os.remove(path)

@dp.callback_query_handler(lambda c: c.data == "a_msg", user_id=ADMIN_ID)
async def ad_start(call: CallbackQuery):
    await call.message.answer("Reklama yuboring:")
    await AdminStates.waiting_for_ad.set()

@dp.message_handler(state=AdminStates.waiting_for_ad, content_types=types.ContentTypes.ANY, user_id=ADMIN_ID)
async def ad_send(message: types.Message, state: FSMContext):
    users = await users_col.find().to_list(length=None)
    for u in users:
        try: 
            await message.copy_to(u['user_id'])
            await asyncio.sleep(0.05)
        except: continue
    await state.finish()
    await message.answer("Tayyor!")

@dp.callback_query_handler(lambda c: c.data == "a_add", user_id=ADMIN_ID)
async def ch_start(call: CallbackQuery):
    await call.message.answer("Format: -100xxx https://t.me/url")
    await AdminStates.waiting_for_channel.set()

@dp.message_handler(state=AdminStates.waiting_for_channel, user_id=ADMIN_ID)
async def ch_save(message: types.Message, state: FSMContext):
    d = message.text.split()
    await channels_col.insert_one({"ch_id": d[0], "url": d[1]})
    await state.finish()
    await message.answer("Qo'shildi!")

# --- RENDER WEB SERVER ---
async def web_h(r): return web.Response(text="Running")
async def on_start(dp):
    app = web.Application()
    app.router.add_get("/", web_h)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get("PORT", 10000)))
    asyncio.create_task(site.start())

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True, on_startup=on_start)
