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
from static_ffmpeg import add_paths
add_paths()
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
                except (TimedOut, NetworkError) as e:
                    if attempt == max_retries - 1:
                        raise
                    logger.warning(f"محاولة {attempt + 1} فشلت: {e}. إعادة المحاولة بعد {delay} ثانية...")
                    await asyncio.sleep(delay)
            return None
        return wrapper
    return decorator

# ====================== إعدادات yt-dlp ======================
YDL_OPTS_BASE = {
    'quiet': True,
    'no_warnings': True,
    'socket_timeout': 30,
    'retries': 3,
    'sleep_interval': 1,
    'max_sleep_interval': 5,
}

# جودة الفيديو المختلفة
VIDEO_QUALITIES = {
    '144p': 'worst[height<=144][ext=mp4]',
    '240p': 'best[height<=240][ext=mp4]',
    '360p': 'best[height<=360][ext=mp4]',
    '480p': 'best[height<=480][ext=mp4]',
    '720p': 'best[height<=720][ext=mp4]',
    '1080p': 'best[height<=1080][ext=mp4]',
    '1440p': 'best[height<=1440][ext=mp4]',
    '2160p': 'best[height<=2160][ext=mp4]',
    'أعلى جودة': 'bestvideo+bestaudio/best[ext=mp4]',
}

AUDIO_OPTS = {
    **YDL_OPTS_BASE,
    'format': 'bestaudio/best',
    'outtmpl': f'{TEMP_DIR}/%(title)s_%(id)s.%(ext)s',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192',
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

def get_file_size(size_bytes):
    """تحويل حجم الملف إلى قراءة مفهومة"""
    if size_bytes is None:
        return "غير معروف"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} GB"

# ====================== البحث ======================
async def search_youtube(query):
    search_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': 'in_playlist',
        'playlistend': 10,
        'socket_timeout': 30,
        'retries': 3,
    }
    search_url = f"ytsearch10:{query}"
    
    try:
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(search_opts) as ydl:
            info = await loop.run_in_executor(None, lambda: ydl.extract_info(search_url, download=False))
            results = []
            for entry in info.get('entries', [])[:10]:
                if entry:
                    results.append({
                        'id': entry.get('id', ''),
                        'title': entry.get('title', 'بدون عنوان')[:50],
                        'url': f"https://youtube.com/watch?v={entry.get('id')}",
                        'duration_str': format_duration(entry.get('duration', 0)),
                        'channel': entry.get('uploader', 'مجهول')[:30],
                    })
            return results
    except Exception as e:
        logger.error(f"خطأ في البحث: {e}")
        return []

async def get_video_details(url):
    """جلب تفاصيل الفيديو والجودات المتاحة"""
    opts = {
        'quiet': True,
        'no_warnings': True,
        'socket_timeout': 30,
    }
    
    try:
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False)),
                timeout=30.0
            )
            
            # استخراج الجودات المتاحة
            available_qualities = []
            formats = info.get('formats', [])
            seen_heights = set()
            
            for fmt in formats:
                height = fmt.get('height')
                if height and height not in seen_heights:
                    seen_heights.add(height)
                    format_note = fmt.get('format_note', '')
                    vcodec = fmt.get('vcodec', 'none')
                    if vcodec != 'none':  # فقط الجودات التي تحتوي على فيديو
                        quality_name = f"{height}p"
                        if format_note:
                            quality_name += f" ({format_note})"
                        available_qualities.append({
                            'height': height,
                            'name': quality_name,
                            'format_id': fmt.get('format_id'),
                            'filesize': fmt.get('filesize'),
                            'fps': fmt.get('fps', ''),
                        })
            
            # ترتيب الجودات تنازلياً
            available_qualities.sort(key=lambda x: x['height'], reverse=True)
            
            # اختيار أفضل صورة مصغرة
            thumbnail = info.get('thumbnail', '')
            if 'thumbnails' in info and info['thumbnails']:
                best_thumb = max(info['thumbnails'], key=lambda x: x.get('width', 0))
                thumbnail = best_thumb.get('url', thumbnail)
            
            return {
                'title': info.get('title', 'بدون عنوان')[:100],
                'channel': info.get('uploader', 'مجهول')[:50],
                'duration': format_duration(info.get('duration', 0)),
                'views': format_number(info.get('view_count', 0)),
                'likes': format_number(info.get('like_count', 0)),
                'upload_date': info.get('upload_date', '')[6:8] + '/' + info.get('upload_date', '')[4:6] + '/' + info.get('upload_date', '')[0:4] if info.get('upload_date') else 'غير معروف',
                'description': (info.get('description', '')[:200] + '...') if info.get('description') else 'لا يوجد وصف',
                'thumbnail': thumbnail,
                'available_qualities': available_qualities,
                'formats': formats,
            }
    except asyncio.TimeoutError:
        logger.error("انتهى وقت جلب التفاصيل")
        return None
    except Exception as e:
        logger.error(f"خطأ في التفاصيل: {e}")
        return None

async def download_media_with_quality(url, quality_format=None, is_audio=False):
    """تحميل الفيديو بجودة محددة"""
    if is_audio:
        opts = {
            **AUDIO_OPTS,
            'format': 'bestaudio/best',
        }
    else:
        format_str = quality_format if quality_format else 'best[ext=mp4]'
        opts = {
            **YDL_OPTS_BASE,
            'format': format_str,
            'outtmpl': f'{TEMP_DIR}/%(title)s_%(id)s.%(ext)s',
        }
    
    try:
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True)),
                timeout=90.0
            )
            filename = ydl.prepare_filename(info)
            if is_audio:
                filename = filename.rsplit('.', 1)[0] + '.mp3'
            if os.path.exists(filename) and os.path.getsize(filename) > 0:
                return filename, info.get('title', 'بدون عنوان')[:100]
            return None, "الملف لم يتم إنشاؤه"
    except asyncio.TimeoutError:
        logger.error("انتهى وقت التحميل")
        return None, "انتهى الوقت"
    except Exception as e:
        logger.error(f"خطأ في التحميل: {e}")
        return None, str(e)[:100]

async def get_direct_download_url(url, quality_format=None, is_audio=False):
    """الحصول على رابط مباشر للتحميل"""
    try:
        if is_audio:
            opts = {
                **YDL_OPTS_BASE,
                'format': 'bestaudio/best',
            }
        else:
            format_str = quality_format if quality_format else 'best[ext=mp4]'
            opts = {
                **YDL_OPTS_BASE,
                'format': format_str,
            }
        
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False)),
                timeout=30.0
            )
            
            if is_audio:
                # للصوت، نبحث عن أفضل تنسيق صوتي
                for f in info.get('formats', []):
                    if f.get('acodec') != 'none' and f.get('vcodec') == 'none':
                        return f.get('url'), info.get('title', 'بدون عنوان')
                return None, "لا يوجد رابط صوتي متاح"
            else:
                # للفيديو، نجلب الرابط المباشر
                requested_format = None
                if quality_format:
                    for f in info.get('formats', []):
                        if f.get('format_id') == quality_format or quality_format in f.get('format', ''):
                            requested_format = f
                            break
                
                if requested_format and requested_format.get('url'):
                    return requested_format.get('url'), info.get('title', 'بدون عنوان')
                elif info.get('url'):
                    return info.get('url'), info.get('title', 'بدون عنوان')
                else:
                    return None, "لا يوجد رابط مباشر متاح"
    except Exception as e:
        logger.error(f"خطأ في جلب الرابط المباشر: {e}")
        return None, str(e)[:100]

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
        [InlineKeyboardButton("🎵 تحميل صوت فقط", callback_data="audio_only")],
        [InlineKeyboardButton("❓ المساعدة", callback_data="help")],
    ]
    await update.message.reply_text(
        "🎬 *بوت التحميل الشامل v2.0*\n\n"
        "✨ *المميزات الجديدة:*\n"
        "• عرض جميع جودات الفيديو المتاحة (144p → 4K)\n"
        "• رابط مباشر للتحميل (تنزيل خارجي)\n"
        "• تحميل الصوت بجودة عالية\n\n"
        "📌 *اختر الخدمة التي تريدها:*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *دليل الاستخدام*\n\n"
        "*1️⃣ البحث في يوتيوب:*\n"
        "اضغط بحث ← اكتب الكلمة ← اختر الفيديو ← اختر الجودة\n\n"
        "*2️⃣ التحميل بالرابط:*\n"
        "أرسل رابط يوتيوب/تيك توك/انستغرام\n\n"
        "*3️⃣ خيارات التحميل:*\n"
        "• 🎥 فيديو: اختر الجودة المناسبة\n"
        "• 🎵 صوت MP3: تحميل الصوت فقط\n"
        "• 🔗 رابط مباشر: احصل على رابط للتحميل الخارجي\n\n"
        "*💡 نصيحة:* الجودات العالية تستهلك وقت أطول ومساحة أكبر",
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
                    f"📋 *نتائج البحث عن:* `{text}`\nاختر الفيديو المناسب:",
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
        if platform == 'youtube':
            # ليوتيوب، نعرض خيارات متقدمة
            keyboard = [
                [InlineKeyboardButton("🎥 فيديو بجميع الجودات", callback_data=f"show_qualities|{text}")],
                [InlineKeyboardButton("🎵 صوت MP3 (جودة عالية)", callback_data=f"youtube_audio|{text}")],
                [InlineKeyboardButton("🔗 رابط مباشر للتحميل", callback_data=f"youtube_direct|{text}")],
            ]
            await update.message.reply_text(
                f"✅ *رابط يوتيوب تم التعرف عليه*\nاختر طريقة التحميل:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
        elif platform:
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
        await update.message.reply_text("❓ *أرسل رابط صحيح أو استخدم أزرار البحث*", parse_mode="Markdown")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    try:
        await query.answer()
    except:
        pass
    
    data = query.data
    
    if data == "search_youtube":
        context.user_data['search_mode'] = True
        await query.edit_message_text("🔍 *أرسل كلمة البحث:*", parse_mode="Markdown")
    
    elif data == "download_url":
        await query.edit_message_text("📎 *أرسل رابط التحميل:*\nYouTube, TikTok, Instagram, Twitter, Facebook", parse_mode="Markdown")
    
    elif data == "audio_only":
        await query.edit_message_text("🎵 *أرسل رابط يوتيوب لتحميل الصوت فقط:*", parse_mode="Markdown")
        context.user_data['audio_mode'] = True
    
    elif data == "help":
        await help_command(update, context)
    
    elif data.startswith("show_qualities|"):
        url = data.split("|", 1)[1]
        await query.edit_message_text("⏳ *جلب تفاصيل الفيديو والجودات المتاحة...*", parse_mode="Markdown")
        
        details = await get_video_details(url)
        
        if details and details.get('available_qualities'):
            # بناء قائمة الجودات المتاحة
            qualities_keyboard = []
            for quality in details['available_qualities'][:8]:  # عرض أول 8 جودات
                quality_text = f"🎬 {quality['name']}"
                if quality.get('filesize'):
                    quality_text += f" [{get_file_size(quality['filesize'])}]"
                qualities_keyboard.append([
                    InlineKeyboardButton(quality_text, callback_data=f"video_quality|{url}|{quality['format_id']}|{quality['name']}")
                ])
            
            qualities_keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")])
            
            await query.edit_message_text(
                f"📹 *{details['title'][:60]}*\n\n"
                f"👤 {details['channel']} | ⏱️ {details['duration']}\n"
                f"👁️ {details['views']} | ❤️ {details['likes']}\n\n"
                f"📊 *اختر جودة الفيديو:*",
                reply_markup=InlineKeyboardMarkup(qualities_keyboard),
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text("❌ *لا توجد تفاصيل أو جودات متاحة*", parse_mode="Markdown")
    
    elif data.startswith("video_quality|"):
        parts = data.split("|")
        url = parts[1]
        format_id = parts[2]
        quality_name = parts[3]
        
        keyboard = [
            [InlineKeyboardButton("📥 تحميل عبر تليجرام", callback_data=f"telegram_video_quality|{url}|{format_id}")],
            [InlineKeyboardButton("🔗 رابط مباشر للتحميل", callback_data=f"direct_video_link|{url}|{format_id}")],
            [InlineKeyboardButton("🔙 رجوع للجودات", callback_data=f"show_qualities|{url}")],
        ]
        
        await query.edit_message_text(
            f"🎬 *جودة: {quality_name}*\n\n"
            f"اختر طريقة التحميل المناسبة:\n\n"
            f"• *تحميل عبر تليجرام:* يتم إرسال الفيديو مباشرة للدردشة\n"
            f"• *رابط مباشر:* للحصول على رابط يمكن استخدامه خارجياً",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    
    elif data.startswith("telegram_video_quality|"):
        parts = data.split("|")
        url = parts[1]
        format_id = parts[2]
        
        await query.edit_message_text("🎬 *جاري تحميل الفيديو بالجودة المحددة...*\nقد يستغرق 30-60 ثانية", parse_mode="Markdown")
        
        filename, title = await download_media_with_quality(url, format_id, is_audio=False)
        
        if filename and os.path.exists(filename):
            try:
                with open(filename, 'rb') as f:
                    await query.message.reply_video(video=f, caption=f"✅ *{title[:80]}*", supports_streaming=True)
                os.remove(filename)
                await query.delete_message()
            except Exception as e:
                await query.message.reply_text(f"❌ *خطأ في الرفع:* {str(e)[:80]}", parse_mode="Markdown")
        else:
            await query.message.reply_text(f"❌ *فشل التحميل*\n{title}", parse_mode="Markdown")
    
    elif data.startswith("direct_video_link|"):
        parts = data.split("|")
        url = parts[1]
        format_id = parts[2]
        
        await query.edit_message_text("⏳ *جاري جلب الرابط المباشر...*", parse_mode="Markdown")
        
        direct_url, title = await get_direct_download_url(url, format_id, is_audio=False)
        
        if direct_url:
            await query.edit_message_text(
                f"✅ *تم جلب الرابط المباشر*\n\n"
                f"📹 *{title[:60]}*\n\n"
                f"🔗 *الرابط:*\n`{direct_url}`\n\n"
                f"📌 يمكنك استخدام هذا الرابط للتحميل عبر أي مدير تحميل",
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text(f"❌ *فشل جلب الرابط:* {title}", parse_mode="Markdown")
    
    elif data.startswith("youtube_audio|"):
        url = data.split("|", 1)[1]
        
        keyboard = [
            [InlineKeyboardButton("📥 تحميل عبر تليجرام", callback_data=f"telegram_audio_high|{url}")],
            [InlineKeyboardButton("🔗 رابط مباشر للصوت", callback_data=f"direct_audio_link|{url}")],
        ]
        
        await query.edit_message_text(
            "🎵 *تحميل الصوت فقط*\n\n"
            "اختر طريقة التحميل:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    
    elif data.startswith("telegram_audio_high|"):
        url = data.split("|", 1)[1]
        await query.edit_message_text("🎵 *جاري تحميل الصوت بجودة عالية...*", parse_mode="Markdown")
        
        filename, title = await download_media_with_quality(url, is_audio=True)
        
        if filename and os.path.exists(filename):
            try:
                with open(filename, 'rb') as f:
                    await query.message.reply_audio(audio=f, title=title[:80], performer="YouTube")
                os.remove(filename)
                await query.delete_message()
            except Exception as e:
                await query.message.reply_text(f"❌ *خطأ:* {str(e)[:80]}", parse_mode="Markdown")
        else:
            await query.message.reply_text(f"❌ *فشل التحميل*\n{title}", parse_mode="Markdown")
    
    elif data.startswith("direct_audio_link|"):
        url = data.split("|", 1)[1]
        await query.edit_message_text("⏳ *جاري جلب رابط الصوت المباشر...*", parse_mode="Markdown")
        
        direct_url, title = await get_direct_download_url(url, is_audio=True)
        
        if direct_url:
            await query.edit_message_text(
                f"✅ *رابط الصوت المباشر*\n\n"
                f"🎵 *{title[:60]}*\n\n"
                f"🔗 *الرابط:*\n`{direct_url}`\n\n"
                f"📌 قم بنسخ الرابط وافتحه في المتصفح للتحميل",
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text(f"❌ *فشل جلب الرابط:* {title}", parse_mode="Markdown")
    
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
                f"📝 {details['description'][:150]}\n"
            )
            
            keyboard = [
                [InlineKeyboardButton("🎥 جودات الفيديو", callback_data=f"show_qualities|{url}")],
                [InlineKeyboardButton("🎵 تحميل صوت MP3", callback_data=f"youtube_audio|{url}")],
                [InlineKeyboardButton("🔍 بحث جديد", callback_data="search_youtube")],
            ]
            
            # إضافة الصورة المصغرة
            try:
                if details['thumbnail']:
                    await query.edit_message_media(
                        media=InputMediaPhoto(media=details['thumbnail'], caption=caption),
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                else:
                    await query.edit_message_text(
                        caption,
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
        await query.edit_message_text("🎬 *جاري التحميل (جودة منخفضة)...*", parse_mode="Markdown")
        
        filename, title = await download_media_with_quality(url, 'worst[ext=mp4]', is_audio=False)
        if filename and os.path.exists(filename):
            try:
                with open(filename, 'rb') as f:
                    await query.message.reply_video(video=f, caption=f"✅ {title[:80]}", supports_streaming=True)
                os.remove(filename)
                await query.delete_message()
            except Exception as e:
                await query.message.reply_text(f"❌ *خطأ:* {str(e)[:80]}", parse_mode="Markdown")
        else:
            await query.message.reply_text(f"❌ *فشل التحميل*", parse_mode="Markdown")
    
    elif data.startswith("telegram_audio|"):
        url = data.split("|", 1)[1]
        await query.edit_message_text("🎵 *جاري التحميل...*", parse_mode="Markdown")
        
        filename, title = await download_media_with_quality(url, is_audio=True)
        if filename and os.path.exists(filename):
            try:
                with open(filename, 'rb') as f:
                    await query.message.reply_audio(audio=f, title=title[:50])
                os.remove(filename)
                await query.delete_message()
            except Exception as e:
                await query.message.reply_text(f"❌ *خطأ:* {str(e)[:80]}", parse_mode="Markdown")
        else:
            await query.message.reply_text("❌ *فشل التحميل*", parse_mode="Markdown")
    
    elif data.startswith("youtube_direct|"):
        url = data.split("|", 1)[1]
        await query.edit_message_text("⏳ *جاري جلب روابط التحميل المباشرة...*", parse_mode="Markdown")
        
        details = await get_video_details(url)
        
        if details:
            # عرض روابط مباشرة لأعلى 3 جودات
            top_qualities = details['available_qualities'][:3]
            links_text = f"🔗 *روابط التحميل المباشرة لـ:*\n{details['title'][:50]}\n\n"
            
            for q in top_qualities:
                direct_url, _ = await get_direct_download_url(url, q['format_id'], is_audio=False)
                if direct_url:
                    links_text += f"\n*{q['name']}:*\n`{direct_url}`\n"
            
            # رابط الصوت
            audio_url, _ = await get_direct_download_url(url, is_audio=True)
            if audio_url:
                links_text += f"\n*🎵 صوت MP3:*\n`{audio_url}`\n"
            
            await query.edit_message_text(links_text, parse_mode="Markdown")
        else:
            await query.edit_message_text("❌ *فشل جلب الروابط*", parse_mode="Markdown")
    
    elif data == "back_to_main":
        keyboard = [
            [InlineKeyboardButton("🔍 بحث في يوتيوب", callback_data="search_youtube")],
            [InlineKeyboardButton("📥 تحميل من رابط", callback_data="download_url")],
            [InlineKeyboardButton("🎵 تحميل صوت فقط", callback_data="audio_only")],
            [InlineKeyboardButton("❓ المساعدة", callback_data="help")],
        ]
        await query.edit_message_text(
            "🎬 *البوت الرئيسي*\nاختر الخدمة:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    
    elif data.startswith("direct_link|"):
        url = data.split("|", 1)[1]
        await query.edit_message_text(f"🔗 *الرابط:*\n`{url}`", parse_mode="Markdown")

# ====================== تشغيل البوت ======================
def main():
    app = Application.builder().token(TOKEN).connect_timeout(60).read_timeout(60).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)
    
    print("🚀 البوت يعمل...")
    print("✅ تم إضافة:")
    print("   • جميع جودات الفيديو (144p → 4K)")
    print("   • رابط مباشر للتحميل")
    print("   • تحميل صوت بجودة عالية")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
