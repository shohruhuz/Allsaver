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

# --- YUKLASH FUNKSIYASI (ffmpeg talab qilmaydi) ---
async def download_media(url, status_msg):
    if not os.path.exists('downloads'):
        os.makedirs('downloads')
    
    last_update_time = [time.time()]
    
    def progress_hook(d):
        if d['status'] == 'downloading':
            total_bytes = d.get('total_bytes') or d.get('estimated_total_bytes')
            if total_bytes:
                p_bar = get_progress_bar(d['downloaded_bytes'], total_bytes)
                speed = d.get('_speed_str', '0KB/s')
                total_str = d.get('_total_bytes_str', 'Noma\'lum')
                text = (
                    f"🚀 <b>Yuklanmoqda...</b>\n\n"
                    f"{p_bar}\n\n"
                    f"⚡️ Tezlik: {speed}\n"
                    f"📦 Jami: {total_str}"
                )
                asyncio.run_coroutine_threadsafe(
                    edit_status(status_msg, text, last_update_time),
                    asyncio.get_event_loop()
                )

    # Birinchi navbatda 50MB dan kichik, so'ngra umuman eng kichigini tanlash
    formats_to_try = [
        'bestvideo[height<=720]+bestaudio/best[height<=720]/best',  # birlashtirish (ffmpeg talab qiladi) — ishlamasa, keyingi
        'best[height<=720][filesize<50M]/best[height<=480][filesize<50M]/best[height<=360][filesize<50M]',
        'best[filesize<50M]/best',  # hajmga qaramasdan, lekin 50MB dan kichik
        'worstvideo+worstaudio/worst',  # oxirgi chora
        'best'  # mutlaq oxirgi
    ]

    for fmt in formats_to_try:
        ydl_opts = {
            'outtmpl': 'downloads/%(id)s.%(ext)s',
            'progress_hooks': [progress_hook],
            'quiet': False,          # ✅ Xatolarni ko'rish uchun
            'no_warnings': False,
            'noplaylist': True,
            'format': fmt,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                loop = asyncio.get_event_loop()
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))
                filename = ydl.prepare_filename(info)

                if os.path.exists(filename):
                    # Agar fayl 50MB dan katta bo'lsa ham, Telegram qabul qilmasa keyinroq xato beradi
                    file_size = os.path.getsize(filename)
                    if file_size > 50 * 1024 * 1024:
                        logging.warning(f"Fayl hajmi 50MB dan ortiq: {file_size / (1024*1024):.1f}MB")
                        # Qabul qilishga harakat qilamiz, lekin Telegram xato qaytarishi mumkin
                    return filename
                else:
                    continue

        except Exception as e:
            logging.error(f"Format {fmt} ishlamadi: {e}")
            continue

    return "error"

# --- MAJBURIY OBUNA ---
async def check_sub(user_id):
    channels = await channels_col.find().to_list(length=10)
    if not channels:
        return True
    for ch in channels:
        try:
            member = await bot.get_chat_member(chat_id=ch['ch_id'], user_id=user_id)
            if member.status == 'left':
                return False
        except:
            continue
    return True

# --- HANDLERLAR ---
@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await users_col.update_one({"user_id": message.from_id}, {"$set": {"user_id": message.from_id}}, upsert=True)
    start_text = (
        "👋 <b>Assalomu alaykum!</b>\n\n"
        "🤖 Men YouTube, Instagram, TikTok, Likee, Pinterest, VK va boshqalardan video yuklovchi botman.\n\n"
        "📌 <b>Imkoniyatlarim:</b>\n"
        "— Video: 50MB gacha (Telegram chegarasi)\n"
        "— Audio: 20MB gacha\n"
        "— Avtomatik format tanlash\n\n"
        "📩 Menga video havolasini yuboring!"
    )
    await message.answer(start_text)

@dp.message_handler(regexp=r'(https?://[^\s]+)')
async def handle_url(message: types.Message):
    if not await check_sub(message.from_id):
        channels = await channels_col.find().to_list(length=10)
        kb = InlineKeyboardMarkup(row_width=1)
        for ch in channels:
            kb.add(InlineKeyboardButton("A'zo bo'lish", url=ch['url']))
        return await message.answer("⚠️ Botdan foydalanish uchun kanallarga obuna bo'ling!", reply_markup=kb)

    url = message.text
    # YouTube uchun alohida tugma kerak emas — avtomatik yuklaydi
    msg = await message.reply("⏳ <b>Yuklanmoqda... Iltimos, kuting.</b>")
    
    path = await download_media(url, msg)
    
    if path == "error":
        await msg.edit_text(
            "❌ <b>Ushbu videoni yuklab bo'lmaydi.</b>\n"
            "Sabablari:\n"
            "— Video yoki audio qo'llab-quvvatlanmaydi,\n"
            "— Platforma yuklashga to'sqinlik qiladi,\n"
            "— Tarmoqda muammo.\n\n"
            "Iltimos, boshqa havolani sinab ko'ring."
        )
        return

    await msg.edit_text("📤 <b>Telegramga yuborilmoqda...</b>")
    try:
        file_size = os.path.getsize(path)
        if file_size > 50 * 1024 * 1024:
            await msg.edit_text("❌ <b>Fayl hajmi 50MB dan ortiq. Telegram qabul qilmaydi.</b>")
        else:
            with open(path, 'rb') as f:
                if path.endswith(('.mp3', '.m4a', '.ogg', '.opus')):
                    await message.answer_audio(f, caption="@Allsaver")
                else:
                    await message.answer_video(f, caption="@Allsaver")
            await msg.delete()
    except Exception as e:
        logging.error(f"Yuborishda xato: {e}")
        await msg.edit_text("❌ Yuborishda xatolik yuz berdi.")
    finally:
        if path and os.path.exists(path):
            os.remove(path)

# --- ADMIN PANEL (o'zgarmagan) ---
@dp.message_handler(commands=['admin'], user_id=ADMIN_ID)
async def admin(message: types.Message):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📊 Stat", callback_data="a_stat"),
        InlineKeyboardButton("📢 Reklama", callback_data="a_msg"),
        InlineKeyboardButton("➕ Kanal", callback_data="a_add")
    )
    await message.answer("<b>Admin Panel:</b>", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == "a_msg", user_id=ADMIN_ID)
async def ad_start(call: CallbackQuery):
    await call.message.answer("Reklama xabarini yuboring:")
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
        except:
            continue
    await state.finish()
    await message.answer(f"✅ Reklama {sent} ta foydalanuvchiga tarqatildi!")

@dp.callback_query_handler(lambda c: c.data == "a_add", user_id=ADMIN_ID)
async def ch_start(call: CallbackQuery):
    await call.message.answer("Kanal ID va Linkini probel bilan yuboring:\nNamuna: <code>-1001234567890 https://t.me/kanal</code>")
    await AdminStates.waiting_for_channel.set()

@dp.message_handler(state=AdminStates.waiting_for_channel, user_id=ADMIN_ID)
async def ch_save(message: types.Message, state: FSMContext):
    parts = message.text.split()
    if len(parts) >= 2:
        ch_id = parts[0]
        url = parts[1]
        await channels_col.insert_one({"ch_id": ch_id, "url": url})
        await state.finish()
        await message.answer("✅ Kanal qo'shildi!")
    else:
        await message.answer("❌ Format xato. Namuna: <code>-1001234567890 https://t.me/kanal</code>")

@dp.callback_query_handler(lambda c: c.data == "a_stat", user_id=ADMIN_ID)
async def a_stat(call: CallbackQuery):
    count = await users_col.count_documents({})
    await call.message.answer(f"👤 Foydalanuvchilar: {count} ta")

# --- WEB SERVER ---
async def web_h(r):
    return web.Response(text="Bot is Active")

async def on_start(dp):
    app = web.Application()
    app.router.add_get("/", web_h)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get("PORT", 10000)))
    asyncio.create_task(site.start())

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True, on_startup=on_start)
