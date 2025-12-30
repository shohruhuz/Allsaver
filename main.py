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

# --- ANIMATSIYALI PROGRESS BAR ---
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

# --- YUKLASH FUNKSIYASI ---
async def download_media(url, mode, status_msg, quality="720"):
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

    quality_chain = ["720", "480", "360"]
    start_idx = quality_chain.index(quality) if quality in quality_chain else 0

    for q in quality_chain[start_idx:]:
        ydl_opts = {
            'outtmpl': 'downloads/%(id)s.%(ext)s',
            'progress_hooks': [progress_hook],
            'quiet': True,
            'noplaylist': True,
            'no_warnings': True,
        }

        if mode == "mp3":
            # MP3: ffmpeg talab qiladi. Agar yo'q bo'lsa, m4a qaytariladi
            ydl_opts['format'] = 'bestaudio[ext=m4a][filesize<20M]/bestaudio[filesize<20M]'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '128',
            }]
        else:
            # Video: muxlangan, 50MB dan kichik
            ydl_opts['format'] = f'best[height<={q}][filesize<50M]/best[height<={q}]/best[filesize<50M]'

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                loop = asyncio.get_event_loop()
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))
                filename = ydl.prepare_filename(info)

                if mode == "mp3":
                    mp3_file = os.path.splitext(filename)[0] + '.mp3'
                    if os.path.exists(mp3_file):
                        return mp3_file
                    elif os.path.exists(filename):
                        return filename  # m4a yoki boshqa audio
                    else:
                        continue
                else:
                    if os.path.exists(filename):
                        return filename
                    else:
                        continue

        except Exception as e:
            logging.error(f"Yuklashda xato ({q}p): {e}")
            if "File is larger than" in str(e) and q != "360":
                continue
            return "error"

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
        "— Video: maksimal 50MB\n"
        "— Audio: maksimal 20MB\n"
        "— Avtomatik sifat tanlovi\n\n"
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

    kb = InlineKeyboardMarkup(row_width=2)
    url = message.text
    if "youtube.com" in url or "youtu.be" in url:
        kb.add(
            InlineKeyboardButton("720p 🎥", callback_data="dl_720"),
            InlineKeyboardButton("MP3 🎵", callback_data="dl_mp3")
        )
    else:
        kb.add(InlineKeyboardButton("📥 Yuklash", callback_data="dl_best"))
    
    await message.reply("⚙️ <b>Hajm tekshirilmoqda. Formatni tanlang:</b>", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('dl_'))
async def dl_callback(call: CallbackQuery):
    q = call.data.replace("dl_", "")
    if not call.message.reply_to_message:
        return await call.answer("Havola topilmadi!", show_alert=True)
    
    url = call.message.reply_to_message.text
    msg = await call.message.edit_text("🛰 <b>Serverga ulanmoqda...</b>")
    
    path = await download_media(url, q, msg, q if q.isdigit() else "720")
    
    if path == "error":
        await msg.edit_text(
            "❌ <b>Ushbu videoni yuklab bo'lmaydi.</b>\n"
            "Ehtimol, hajmi 50MB (video) yoki 20MB (audio) dan ortiq, "
            "yoki platforma yuklashga ruxsat bermaydi."
        )
        return

    await msg.edit_text("📤 <b>Telegramga yuborilmoqda...</b>")
    try:
        with open(path, 'rb') as f:
            if q == "mp3":
                if path.endswith('.mp3'):
                    await call.message.answer_audio(f, caption="@Allsaver")
                else:
                    # m4a, ogg kabi formatlar
                    await call.message.answer_voice(f, caption="@Allsaver")
            else:
                await call.message.answer_video(f, caption="@Allsaver")
        await msg.delete()
    except Exception as e:
        logging.error(f"Yuborishda xato: {e}")
        await msg.edit_text("❌ Yuborishda xatolik yuz berdi.")
    finally:
        if path and os.path.exists(path):
            os.remove(path)

# --- ADMIN PANEL ---
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

# --- WEB SERVER (Render uchun) ---
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
