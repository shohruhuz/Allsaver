import os, asyncio, logging, time
from aiogram import Bot, Dispatcher, types, executor
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from motor.motor_asyncio import AsyncIOMotorClient
from aiohttp import web
import yt_dlp

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

# --- PROGRESS BAR ---
def get_progress_bar(current, total):
    percentage = current / total
    completed = int(percentage * 10)
    bar = "🔹" * completed + "🔸" * (10 - completed)
    return f"{bar} {percentage*100:.1f}%"

async def edit_status(message, text, last_update_time):
    if time.time() - last_update_time[0] < 2.5:
        return
    try:
        await message.edit_text(text)
        last_update_time[0] = time.time()
    except:
        pass

# --- YUKLASH FUNKSIYASI (360p HARD-SET) ---
async def download_media(url, mode, status_msg):
    if not os.path.exists('downloads'): os.makedirs('downloads')
    last_update_time = [time.time()]
    
    def progress_hook(d):
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('estimated_total_bytes')
            if total:
                p_bar = get_progress_bar(d['downloaded_bytes'], total)
                speed = d.get('_speed_str', '0KB/s')
                text = f"🚀 <b>Yuklanmoqda (360p)...</b>\n\n{p_bar}\n\n⚡️ Tezlik: {speed}"
                asyncio.run_coroutine_threadsafe(edit_status(status_msg, text, last_update_time), asyncio.get_event_loop())

    # FAQAT 360p yoki undan past sifatni tanlaydi
    ydl_opts = {
        'outtmpl': f'downloads/%(id)s.%(ext)s',
        'progress_hooks': [progress_hook],
        'max_filesize': 80 * 1024 * 1024,
        'quiet': True,
    }
    
    if mode == "mp3":
        ydl_opts['format'] = 'bestaudio/best'
        ydl_opts['postprocessors'] = [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '128'}]
    else:
        # Eng yaxshi video lekin balandligi 360dan oshmasin
        ydl_opts['format'] = 'bestvideo[height<=360]+bestaudio/best[height<=360]/best[height<=360]'
        ydl_opts['merge_output_format'] = 'mp4'

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))
            return ydl.prepare_filename(info).replace(".webm", ".mp4").replace(".mkv", ".mp4").replace(".m4a", ".mp3")
    except Exception as e:
        logging.error(f"Xatolik: {e}")
        return "error"

# --- HANDLERLAR ---
@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await users_col.update_one({"user_id": message.from_id}, {"$set": {"user_id": message.from_id}}, upsert=True)
    await message.answer("👋 <b>Xush kelibsiz!</b>\nMen videolarni <b>360p</b> sifatda yuklab beraman.\n\n📩 Havolani yuboring!")

@dp.message_handler(regexp=r'(https?://[^\s]+)')
async def handle_url(message: types.Message):
    # Majburiy obuna tekshiruvi (avvalgi mantiq)
    channels = await channels_col.find().to_list(length=10)
    for ch in channels:
        try:
            member = await bot.get_chat_member(chat_id=ch['ch_id'], user_id=message.from_id)
            if member.status == 'left':
                kb = InlineKeyboardMarkup().add(InlineKeyboardButton("A'zo bo'lish", url=ch['url']))
                return await message.answer("⚠️ Botdan foydalanish uchun kanallarga obuna bo'ling!", reply_markup=kb)
        except: continue

    kb = InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("🎬 Video (360p)", callback_data="dl_360"),
        InlineKeyboardButton("🎵 Audio (MP3)", callback_data="dl_mp3")
    )
    await message.reply("⚙️ <b>Formatni tanlang:</b>", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('dl_'))
async def dl_callback(call: CallbackQuery):
    mode = call.data.replace("dl_", "")
    url = call.message.reply_to_message.text
    msg = await call.message.edit_text("🛰 <b>Server aniqlanmoqda...</b>")
    
    path = await download_media(url, mode, msg)
    
    if path == "error":
        await msg.edit_text("❌ <b>Yuklab bo'lmadi.</b>\nHajm juda katta yoki video topilmadi.")
        return

    await msg.edit_text("📤 <b>Telegramga yuborilmoqda...</b>")
    try:
        with open(path, 'rb') as f:
            if mode == "mp3": await call.message.answer_audio(f, caption="@Allsaver")
            else: await call.message.answer_video(f, caption="@Allsaver")
        await msg.delete()
    except:
        await msg.edit_text("❌ Yuborishda xatolik.")
    finally:
        if path and os.path.exists(path): os.remove(path)

# --- ADMIN PANEL & WEB SERVER (O'zgarmagan) ---
# ... (Yuqoridagi kod bilan bir xil) ...

async def web_h(r): return web.Response(text="Bot Active")
async def on_start(dp):
    app = web.Application(); app.router.add_get("/", web_h)
    runner = web.AppRunner(app); await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get("PORT", 10000)))
    asyncio.create_task(site.start())

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True, on_startup=on_start)
