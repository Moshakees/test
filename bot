import os
import re
import yt_dlp
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.error import BadRequest, TimedOut, RetryAfter

# ====================== التوكن ======================
TOKEN = "8602702415:AAGljdvPI8JwYqNqpQylpCNo3GVmhQ1-nOQ"  # ضع توكن البوت هنا

# ====================== الإعدادات ======================
TEMP_DIR = "downloads"
os.makedirs(TEMP_DIR, exist_ok=True)

# إعدادات yt-dlp
YDL_OPTS_BASE = {
    'quiet': True,
    'no_warnings': True,
    'socket_timeout': 30,
    'retries': 2,
    'extract_flat': True,
}

VIDEO_OPTS = {
    **YDL_OPTS_BASE,
    'format': 'bestvideo[height<=480]+bestaudio/best[height<=480]',
    'outtmpl': f'{TEMP_DIR}/%(title)s_%(id)s.%(ext)s',
}

AUDIO_OPTS = {
    **YDL_OPTS_BASE,
    'format': 'bestaudio/best',
    'outtmpl': f'{TEMP_DIR}/%(title)s_%(id)s.%(ext)s',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '128',
    }],
}

# ====================== دوال مساعدة ======================
def format_duration(seconds):
    try:
        if not seconds or seconds <= 0:
            return "00:00"
        seconds = int(seconds)
        minutes = seconds // 60
        remaining_seconds = seconds % 60
        hours = minutes // 60
        minutes = minutes % 60
        
        if hours > 0:
            return f"{hours}:{minutes:02d}:{remaining_seconds:02d}"
        return f"{minutes}:{remaining_seconds:02d}"
    except:
        return "00:00"

def format_number(num):
    try:
        if num is None:
            return "0"
        if isinstance(num, float):
            if num.is_integer():
                num = int(num)
            else:
                num = int(num)
        num = int(num)
        if num >= 1_000_000:
            return f"{num/1_000_000:.1f}M"
        elif num >= 1_000:
            return f"{num/1_000:.1f}K"
        return str(num)
    except:
        return "0"

# ====================== البحث في يوتيوب ======================
async def search_youtube(query):
    search_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': 'in_playlist',
        'playlistend': 10,
        'socket_timeout': 20,
    }
    search_url = f"ytsearch10:{query}"
    
    try:
        with yt_dlp.YoutubeDL(search_opts) as ydl:
            info = await asyncio.get_event_loop().run_in_executor(
                None, lambda: ydl.extract_info(search_url, download=False)
            )
            results = []
            for entry in info.get('entries', []):
                if entry:
                    results.append({
                        'id': entry.get('id', ''),
                        'title': entry.get('title', 'بدون عنوان')[:50],
                        'url': f"https://youtube.com/watch?v={entry.get('id')}",
                        'duration_str': format_duration(entry.get('duration', 0)),
                        'duration': entry.get('duration', 0),
                        'channel': entry.get('uploader', 'مجهول')[:30],
                    })
            return results
    except Exception as e:
        print(f"بحث خطأ: {e}")
        return []

# ====================== جلب التفاصيل ======================
async def get_video_details(url):
    opts = {
        'quiet': True,
        'no_warnings': True,
        'socket_timeout': 20,
        'extract_flat': False,
    }
    
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = await asyncio.get_event_loop().run_in_executor(
                None, lambda: ydl.extract_info(url, download=False)
            )
            
            return {
                'title': info.get('title', 'بدون عنوان')[:100],
                'channel': info.get('uploader', 'مجهول')[:50],
                'duration': format_duration(info.get('duration', 0)),
                'views': format_number(info.get('view_count', 0)),
                'likes': format_number(info.get('like_count', 0)),
                'upload_date': info.get('upload_date', 'غير معروف'),
                'description': (info.get('description', '')[:200] + '...') if info.get('description') else 'لا يوجد وصف',
            }
    except Exception as e:
        print(f"تفاصيل خطأ: {e}")
        return None

# ====================== التحميل ======================
async def download_media(url, is_audio=False):
    opts = AUDIO_OPTS if is_audio else VIDEO_OPTS
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = await asyncio.get_event_loop().run_in_executor(
                None, lambda: ydl.extract_info(url, download=True)
            )
            filename = ydl.prepare_filename(info)
            if is_audio:
                filename = filename.rsplit('.', 1)[0] + '.mp3'
            
            if os.path.exists(filename) and os.path.getsize(filename) > 0:
                return filename, info.get('title', 'بدون عنوان')[:100]
            return None, "ملف فارغ"
    except Exception as e:
        return None, str(e)[:100]

# ====================== التعرف على المنصة ======================
def detect_platform(url):
    platforms = {
        'youtube': r'(youtube\.com|youtu\.be)',
        'tiktok': r'tiktok\.com',
        'instagram': r'instagram\.com',
        'twitter': r'twitter\.com|x\.com',
        'facebook': r'facebook\.com|fb\.watch',
        'soundcloud': r'soundcloud\.com',
    }
    for platform, pattern in platforms.items():
        if re.search(pattern, url, re.IGNORECASE):
            return platform
    return None

# ====================== أوامر البوت ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔍 بحث يوتيوب", callback_data="search_youtube")],
        [InlineKeyboardButton("📥 تحميل من رابط", callback_data="download_url")],
        [InlineKeyboardButton("❓ المساعدة", callback_data="help")],
    ]
    await update.message.reply_text(
        "🎬 *بوت التحميل الشامل*\n\n"
        "🔍 بحث في يوتيوب\n"
        "📥 تحميل: TikTok - Instagram - Twitter - Facebook\n\n"
        "اختر الخدمة 👇",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *الاستخدام*\n\n"
        "1️⃣ *بحث يوتيوب*: اضغط 'بحث يوتيوب' ← اكتب الكلمة ← اختر النتيجة\n\n"
        "2️⃣ *تحميل من رابط*: اضغط 'تحميل من رابط' ← أرسل الرابط\n\n"
        "⚠️ التحميل قد يستغرق 30-60 ثانية",
        parse_mode="Markdown"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_data = context.user_data
    
    if user_data.get('search_mode'):
        user_data['search_mode'] = False
        msg = await update.message.reply_text("🔍 *جاري البحث...*", parse_mode="Markdown")
        
        results = await search_youtube(text)
        
        if results:
            keyboard = []
            for i, r in enumerate(results[:10]):
                keyboard.append([InlineKeyboardButton(
                    f"{i+1}. {r['title']} [{r['duration_str']}]",
                    callback_data=f"yt|{r['url']}"
                )])
            
            await msg.edit_text(
                f"📋 *نتائج:* `{text}`",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
        else:
            await msg.edit_text("❌ لا توجد نتائج")
        return
    
    if re.match(r'https?://', text):
        platform = detect_platform(text)
        if platform:
            keyboard = [
                [InlineKeyboardButton("🎥 فيديو", callback_data=f"vid|{text}")],
                [InlineKeyboardButton("🎵 صوت", callback_data=f"aud|{text}")],
                [InlineKeyboardButton("🔗 رابط", callback_data=f"lnk|{text}")],
            ]
            await update.message.reply_text(
                f"✅ `{platform.upper()}`\nاختر:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("❌ منصة غير مدعومة")
    else:
        await update.message.reply_text("❓ أرسل رابط أو استخدم الأزرار")

# ====================== معالجة الأزرار (مع تصحيح الخطأ) ======================
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    # محاولة الرد بسرعة لتجنب انتهاء الصلاحية
    try:
        await query.answer()
    except BadRequest:
        # إذا انتهت الصلاحية، نكمل بدون إجابة
        pass
    
    data = query.data
    
    # بحث يوتيوب
    if data == "search_youtube":
        context.user_data['search_mode'] = True
        try:
            await query.edit_message_text("🔍 *أرسل كلمة البحث:*", parse_mode="Markdown")
        except BadRequest:
            await context.bot.send_message(query.message.chat_id, "🔍 *أرسل كلمة البحث:*", parse_mode="Markdown")
    
    # تحميل من رابط
    elif data == "download_url":
        try:
            await query.edit_message_text("📎 *أرسل رابط التحميل:*", parse_mode="Markdown")
        except BadRequest:
            await context.bot.send_message(query.message.chat_id, "📎 *أرسل رابط التحميل:*", parse_mode="Markdown")
    
    # مساعدة
    elif data == "help":
        try:
            await query.edit_message_text(
                "📖 *الاستخدام*\n\n1️⃣ بحث يوتيوب\n2️⃣ تحميل من رابط\n\n⚠️ التحميل يستغرق دقيقة",
                parse_mode="Markdown"
            )
        except BadRequest:
            await context.bot.send_message(query.message.chat_id, "📖 تم ✅", parse_mode="Markdown")
    
    # نتيجة يوتيوب
    elif data.startswith("yt|"):
        url = data.split("|", 1)[1]
        
        # إرسال رسالة جديدة بدل تعديل القديمة
        msg = await context.bot.send_message(query.message.chat_id, "⏳ *جاري جلب التفاصيل...*", parse_mode="Markdown")
        
        details = await get_video_details(url)
        
        if details:
            text = (
                f"🎬 *تفاصيل الفيديو*\n\n"
                f"📌 *العنوان:*\n{details['title']}\n\n"
                f"👤 *القناة:* {details['channel']}\n"
                f"⏱️ *المدة:* {details['duration']}\n"
                f"👁️ *المشاهدات:* {details['views']}\n"
                f"❤️ *الإعجابات:* {details['likes']}\n"
                f"📅 *النشر:* {details['upload_date']}\n\n"
                f"📝 *الوصف:*\n{details['description']}\n"
            )
            
            keyboard = [
                [InlineKeyboardButton("🎥 تحميل فيديو", callback_data=f"vid|{url}")],
                [InlineKeyboardButton("🎵 تحميل صوت", callback_data=f"aud|{url}")],
                [InlineKeyboardButton("🔍 بحث جديد", callback_data="search_youtube")],
            ]
            
            await msg.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        else:
            await msg.edit_text("❌ فشل جلب التفاصيل")
    
    # تحميل فيديو
    elif data.startswith("vid|"):
        url = data.split("|", 1)[1]
        msg = await context.bot.send_message(query.message.chat_id, "🎬 *جاري التحميل...*\nقد يستغرق دقيقة ⏳", parse_mode="Markdown")
        
        filename, title = await download_media(url, is_audio=False)
        if filename and os.path.exists(filename):
            try:
                with open(filename, 'rb') as f:
                    await context.bot.send_video(
                        chat_id=query.message.chat_id,
                        video=f,
                        caption=f"✅ {title[:100]}",
                        supports_streaming=True
                    )
                os.remove(filename)
                await msg.delete()
            except Exception as e:
                await msg.edit_text(f"❌ خطأ: {str(e)[:100]}")
        else:
            await msg.edit_text(f"❌ فشل التحميل")
    
    # تحميل صوت
    elif data.startswith("aud|"):
        url = data.split("|", 1)[1]
        msg = await context.bot.send_message(query.message.chat_id, "🎵 *جاري التحميل...*\nقد يستغرق دقيقة ⏳", parse_mode="Markdown")
        
        filename, title = await download_media(url, is_audio=True)
        if filename and os.path.exists(filename):
            try:
                with open(filename, 'rb') as f:
                    await context.bot.send_audio(
                        chat_id=query.message.chat_id,
                        audio=f,
                        title=title[:50],
                        performer="بوت التحميل"
                    )
                os.remove(filename)
                await msg.delete()
            except Exception as e:
                await msg.edit_text(f"❌ خطأ: {str(e)[:100]}")
        else:
            await msg.edit_text(f"❌ فشل التحميل")
    
    # رابط مباشر
    elif data.startswith("lnk|"):
        url = data.split("|", 1)[1]
        try:
            await query.edit_message_text(f"🔗 *الرابط:*\n`{url}`", parse_mode="Markdown")
        except BadRequest:
            await context.bot.send_message(query.message.chat_id, f"🔗 *الرابط:*\n`{url}`", parse_mode="Markdown")

# ====================== تشغيل البوت ======================
def main():
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🚀 البوت يعمل...")
    print("✅ تم تصحيح خطأ timeout")
    app.run_polling()

if __name__ == "__main__":
    main()
