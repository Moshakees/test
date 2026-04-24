import os
import re
import yt_dlp
import asyncio
import logging
from functools import wraps
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.error import BadRequest, TimedOut, RetryAfter, NetworkError
from httpx import Timeout

# ====================== إعدادات التسجيل ======================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ====================== التوكن ======================
TOKEN = "8602702415:AAGljdvPI8JwYqNqpQylpCNo3GVmhQ1-nOQ"

# ====================== الإعدادات ======================
TEMP_DIR = "downloads"
os.makedirs(TEMP_DIR, exist_ok=True)

# ====================== دالة إعادة المحاولة ======================
def retry_on_timeout(max_retries=3, delay=2):
    """ديكور لإعادة المحاولة عند حدوث Timeout"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except (TimedOut, NetworkError, ConnectTimeout) as e:
                    if attempt == max_retries - 1:
                        raise
                    logger.warning(f"محاولة {attempt + 1} فشلت: {e}. إعادة المحاولة بعد {delay} ثانية...")
                    await asyncio.sleep(delay)
            return None
        return wrapper
    return decorator

# ====================== إعدادات yt-dlp (مخففة للسرعة) ======================
YDL_OPTS_BASE = {
    'quiet': True,
    'no_warnings': True,
    'socket_timeout': 15,  # تقليل المهلة
    'retries': 2,
    'sleep_interval': 1,
    'max_sleep_interval': 5,
}

VIDEO_OPTS = {
    **YDL_OPTS_BASE,
    'format': 'worst[ext=mp4]',  # أقل جودة للسرعة
    'outtmpl': f'{TEMP_DIR}/%(title)s_%(id)s.%(ext)s',
}

AUDIO_OPTS = {
    **YDL_OPTS_BASE,
    'format': 'worstaudio',
    'outtmpl': f'{TEMP_DIR}/%(title)s_%(id)s.%(ext)s',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '64',  # جودة منخفضة للسرعة
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
        else:
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

# ====================== البحث ======================
async def search_youtube(query):
    search_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': 'in_playlist',
        'playlistend': 8,  # تقليل عدد النتائج
        'socket_timeout': 15,
        'retries': 2,
    }
    search_url = f"ytsearch8:{query}"
    
    try:
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(search_opts) as ydl:
            info = await loop.run_in_executor(None, lambda: ydl.extract_info(search_url, download=False))
            results = []
            for entry in info.get('entries', [])[:8]:
                if entry:
                    results.append({
                        'id': entry.get('id', ''),
                        'title': entry.get('title', 'بدون عنوان')[:40],
                        'url': f"https://youtube.com/watch?v={entry.get('id')}",
                        'duration_str': format_duration(entry.get('duration', 0)),
                        'channel': entry.get('uploader', 'مجهول')[:25],
                    })
            return results
    except Exception as e:
        logger.error(f"خطأ في البحث: {e}")
        return []

async def get_video_details(url):
    opts = {
        'quiet': True,
        'no_warnings': True,
        'socket_timeout': 15,
        'extract_flat': True,  # استخراج سريع فقط
    }
    
    try:
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False)),
                timeout=20.0  # مهلة 20 ثانية
            )
            
            thumbnail = info.get('thumbnail', '')
            if 'thumbnails' in info and info['thumbnails']:
                best_thumb = min(info['thumbnails'], key=lambda x: x.get('width', 1000))  # صورة صغيرة للسرعة
                thumbnail = best_thumb.get('url', thumbnail)
            
            return {
                'title': info.get('title', 'بدون عنوان')[:80],
                'channel': info.get('uploader', 'مجهول')[:40],
                'duration': format_duration(info.get('duration', 0)),
                'views': format_number(info.get('view_count', 0)),
                'likes': format_number(info.get('like_count', 0)),
                'upload_date': info.get('upload_date', '')[6:8] + '/' + info.get('upload_date', '')[4:6] + '/' + info.get('upload_date', '')[0:4] if info.get('upload_date') else 'غير معروف',
                'description': (info.get('description', '')[:150] + '...') if info.get('description') else 'لا يوجد وصف',
                'thumbnail': thumbnail,
            }
    except asyncio.TimeoutError:
        logger.error("انتهى وقت جلب التفاصيل")
        return None
    except Exception as e:
        logger.error(f"خطأ في التفاصيل: {e}")
        return None

async def download_media(url, is_audio=False):
    opts = AUDIO_OPTS if is_audio else VIDEO_OPTS
    try:
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True)),
                timeout=45.0  # مهلة 45 ثانية للتحميل
            )
            filename = ydl.prepare_filename(info)
            if is_audio:
                filename = filename.rsplit('.', 1)[0] + '.mp3'
            if os.path.exists(filename) and os.path.getsize(filename) > 0:
                return filename, info.get('title', 'بدون عنوان')[:80]
            return None, "الملف لم يتم إنشاؤه"
    except asyncio.TimeoutError:
        logger.error("انتهى وقت التحميل")
        return None, "انتهى الوقت"
    except Exception as e:
        logger.error(f"خطأ في التحميل: {e}")
        return None, str(e)[:80]

def detect_platform(url):
    platforms = {
        'youtube': r'(youtube\.com|youtu\.be)',
        'tiktok': r'tiktok\.com',
        'instagram': r'instagram\.com',
        'twitter': r'twitter\.com|x\.com',
        'facebook': r'facebook\.com|fb\.watch',
    }
    for platform, pattern in platforms.items():
        if re.search(pattern, url, re.IGNORECASE):
            return platform
    return None

# ====================== معالج الأخطاء الآمن ======================
async def safe_send_message(update, text, parse_mode="Markdown"):
    """إرسال رسالة بأمان مع معالجة الأخطاء"""
    try:
        await update.effective_message.reply_text(text, parse_mode=parse_mode)
    except Exception as e:
        logger.error(f"فشل إرسال الرسالة: {e}")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الأخطاء الآمن"""
    logger.error(f"حدث خطأ: {context.error}")
    
    try:
        if isinstance(context.error, TimedOut):
            await safe_send_message(update, "⏳ *انتهى الوقت، يرجى المحاولة مرة أخرى*", parse_mode="Markdown")
        elif isinstance(context.error, NetworkError):
            await safe_send_message(update, "🌐 *مشكلة في الاتصال، تأكد من الإنترنت*", parse_mode="Markdown")
        elif isinstance(context.error, BadRequest):
            if "Query is too old" in str(context.error):
                await safe_send_message(update, "⏰ *انتهت صلاحية الزر، ابدأ من جديد*", parse_mode="Markdown")
            else:
                await safe_send_message(update, "❌ *طلب غير صالح*", parse_mode="Markdown")
        else:
            await safe_send_message(update, "❌ *حدث خطأ، حاول مرة أخرى*", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"خطأ في معالج الأخطاء نفسه: {e}")

# ====================== أوامر البوت ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔍 بحث في يوتيوب", callback_data="search_youtube")],
        [InlineKeyboardButton("📥 تحميل من رابط", callback_data="download_url")],
        [InlineKeyboardButton("❓ المساعدة", callback_data="help")],
    ]
    await update.message.reply_text(
        "🎬 *بوت التحميل الشامل*\n\n"
        "🔍 *يوتيوب:* بحث + تفاصيل + صورة\n"
        "📥 *روابط:* TikTok, Instagram, Twitter, Facebook\n\n"
        "⚠️ *ملاحظة:* قد ياخذ 30-45 ثانية حسب سرعة النت",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *الاستخدام*\n\n"
        "1️⃣ *بحث يوتيوب:* اضغط زر البحث ← اكتب الكلمة\n"
        "2️⃣ *تحميل رابط:* اضغط زر التحميل ← أرسل الرابط\n\n"
        "💡 *نصائح للسرعة:*\n"
        "• استخدم نتائج سريع (4G/5G/WiFi قوي)\n"
        "• للملفات الكبيرة، استخدم 'رابط مباشر'\n"
        "• انتظر 30-60 ثانية للتحميل",
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
            keyboard = [
                [InlineKeyboardButton(f"{i+1}. {r['title']} [{r['duration_str']}]", callback_data=f"yt_result|{r['url']}|{i+1}")]
                for i, r in enumerate(results)
            ]
            try:
                await msg.edit_text(
                    f"📋 *نتائج البحث عن:* `{text}`",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown"
                )
            except:
                await msg.delete()
                await update.message.reply_text(
                    f"📋 *نتائج البحث:*\n" + "\n".join([f"{i+1}. {r['title']}" for i, r in enumerate(results)]),
                    parse_mode="Markdown"
                )
        else:
            await msg.edit_text("❌ *لا توجد نتائج*", parse_mode="Markdown")
        return
    
    if re.match(r'https?://', text):
        platform = detect_platform(text)
        if platform:
            keyboard = [
                [InlineKeyboardButton("🎥 فيديو", callback_data=f"telegram_video|{text}")],
                [InlineKeyboardButton("🎵 صوت MP3", callback_data=f"telegram_audio|{text}")],
                [InlineKeyboardButton("🔗 رابط مباشر", callback_data=f"direct_link|{text}")],
            ]
            await update.message.reply_text(
                f"✅ *{platform.upper()}*\nاختر طريقة التحميل:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("❌ *منصة غير مدعومة*", parse_mode="Markdown")
    else:
        await update.message.reply_text("❓ *أرسل رابط صحيح*", parse_mode="Markdown")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    try:
        await query.answer()
    except:
        pass  # نتجاهل خطأ الإجابة
    
    data = query.data
    
    if data == "search_youtube":
        context.user_data['search_mode'] = True
        await query.edit_message_text("🔍 *أرسل كلمة البحث:*", parse_mode="Markdown")
    
    elif data == "download_url":
        await query.edit_message_text("📎 *أرسل رابط التحميل:*\nTikTok, Instagram, Twitter, Facebook", parse_mode="Markdown")
    
    elif data == "help":
        await help_command(update, context)
    
    elif data.startswith("yt_result|"):
        parts = data.split("|")
        url = parts[1]
        index = parts[2] if len(parts) > 2 else "1"
        
        await query.edit_message_text("⏳ *جاري جلب التفاصيل...*", parse_mode="Markdown")
        
        details = await get_video_details(url)
        
        if details:
            caption = (
                f"🎬 *#{index}*\n\n"
                f"📌 *{details['title']}*\n\n"
                f"👤 {details['channel']}\n"
                f"⏱️ {details['duration']}\n"
                f"👁️ {details['views']}\n"
                f"❤️ {details['likes']}\n"
                f"📅 {details['upload_date']}\n\n"
                f"📝 {details['description']}\n"
            )
            
            keyboard = [
                [InlineKeyboardButton("🎥 تحميل فيديو", callback_data=f"telegram_video|{url}")],
                [InlineKeyboardButton("🎵 تحميل صوت", callback_data=f"telegram_audio|{url}")],
                [InlineKeyboardButton("🔗 رابط مباشر", callback_data=f"direct_link|{url}")],
                [InlineKeyboardButton("🔍 بحث جديد", callback_data="search_youtube")],
            ]
            
            try:
                await query.edit_message_caption(
                    caption=caption,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown"
                )
            except:
                await query.edit_message_text(
                    caption,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown"
                )
        else:
            await query.edit_message_text("❌ *فشل جلب التفاصيل*", parse_mode="Markdown")
    
    elif data.startswith("telegram_video|"):
        url = data.split("|", 1)[1]
        await query.edit_message_text("🎬 *جاري التحميل...*", parse_mode="Markdown")
        
        filename, title = await download_media(url, is_audio=False)
        if filename and os.path.exists(filename):
            try:
                with open(filename, 'rb') as f:
                    await query.message.reply_video(video=f, caption=f"✅ {title[:80]}", supports_streaming=True)
                os.remove(filename)
            except Exception as e:
                await query.message.reply_text(f"❌ *خطأ:* {str(e)[:80]}", parse_mode="Markdown")
        else:
            await query.message.reply_text(f"❌ *فشل التحميل*", parse_mode="Markdown")
    
    elif data.startswith("telegram_audio|"):
        url = data.split("|", 1)[1]
        await query.edit_message_text("🎵 *جاري التحميل...*", parse_mode="Markdown")
        
        filename, title = await download_media(url, is_audio=True)
        if filename and os.path.exists(filename):
            try:
                with open(filename, 'rb') as f:
                    await query.message.reply_audio(audio=f, title=title[:50])
                os.remove(filename)
            except Exception as e:
                await query.message.reply_text(f"❌ *خطأ:* {str(e)[:80]}", parse_mode="Markdown")
        else:
            await query.message.reply_text("❌ *فشل التحميل*", parse_mode="Markdown")
    
    elif data.startswith("direct_link|"):
        url = data.split("|", 1)[1]
        await query.edit_message_text(f"🔗 *الرابط:*\n`{url}`", parse_mode="Markdown")

# ====================== تشغيل البوت ======================
def main():
    # إنشاء التطبيق مع إعدادات Timeout أعلى
    app = Application.builder().token(TOKEN).connect_timeout(30).read_timeout(30).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)
    
    print("🚀 البوت يعمل...")
    print("✅ تم تحسين مقاومة الـ Timeout")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
