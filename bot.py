import os
import re
import yt_dlp
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# ====================== التوكن ======================
TOKEN = "8602702415:AAGljdvPI8JwYqNqpQylpCNo3GVmhQ1-nOQ"

# ====================== الإعدادات ======================
TEMP_DIR = "downloads"
os.makedirs(TEMP_DIR, exist_ok=True)

# إعدادات yt-dlp
YDL_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'socket_timeout': 30,
    'retries': 3,
}

def format_duration(seconds):
    if not seconds:
        return "00:00"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    if minutes >= 60:
        hours = minutes // 60
        minutes = minutes % 60
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"

def format_number(num):
    if not num:
        return "0"
    if num >= 1_000_000:
        return f"{num/1_000_000:.1f}M"
    elif num >= 1_000:
        return f"{num/1_000:.1f}K"
    return str(num)

async def search_youtube(query):
    search_opts = {
        **YDL_OPTS,
        'extract_flat': 'in_playlist',
        'playlistend': 8,
    }
    search_url = f"ytsearch8:{query}"
    
    try:
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(search_opts) as ydl:
            info = await loop.run_in_executor(None, lambda: ydl.extract_info(search_url, download=False))
            results = []
            for entry in info.get('entries', []):
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
        print(f"بحث خطأ: {e}")
        return []

async def download_audio(url):
    opts = {
        **YDL_OPTS,
        'format': 'bestaudio/best',
        'outtmpl': f'{TEMP_DIR}/%(title)s_%(id)s.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '128',
        }],
    }
    try:
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))
            filename = ydl.prepare_filename(info)
            filename = filename.rsplit('.', 1)[0] + '.mp3'
            return filename, info.get('title', 'بدون عنوان')[:80]
    except Exception as e:
        return None, str(e)

async def download_video(url):
    opts = {
        **YDL_OPTS,
        'format': 'best[height<=480]',
        'outtmpl': f'{TEMP_DIR}/%(title)s_%(id)s.%(ext)s',
    }
    try:
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))
            filename = ydl.prepare_filename(info)
            return filename, info.get('title', 'بدون عنوان')[:80]
    except Exception as e:
        return None, str(e)

def detect_platform(url):
    platforms = {
        'youtube': r'(youtube\.com|youtu\.be)',
        'tiktok': r'tiktok\.com',
        'instagram': r'instagram\.com',
        'twitter': r'twitter\.com|x\.com',
        'facebook': r'facebook\.com',
    }
    for platform, pattern in platforms.items():
        if re.search(pattern, url, re.IGNORECASE):
            return platform
    return None

# ====================== أوامر البوت ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔍 بحث في يوتيوب", callback_data="search")],
        [InlineKeyboardButton("📥 تحميل من رابط", callback_data="download_url")],
    ]
    await update.message.reply_text(
        "🎬 *بوت التحميل*\n\n"
        "🔍 بحث في يوتيوب\n"
        "📥 تحميل: TikTok, Instagram, Twitter, Facebook",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    if context.user_data.get('search_mode'):
        context.user_data['search_mode'] = False
        await update.message.reply_text("🔍 *جاري البحث...*", parse_mode="Markdown")
        
        results = await search_youtube(text)
        
        if results:
            keyboard = [
                [InlineKeyboardButton(
                    f"{i+1}. {r['title']} [{r['duration_str']}]",
                    callback_data=f"dl|{r['url']}"
                )]
                for i, r in enumerate(results)
            ]
            await update.message.reply_text(
                f"📋 *نتائج:* `{text}`",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("❌ لا نتائج")
        return
    
    if re.match(r'https?://', text):
        platform = detect_platform(text)
        if platform:
            keyboard = [
                [InlineKeyboardButton("🎥 فيديو", callback_data=f"video|{text}")],
                [InlineKeyboardButton("🎵 صوت MP3", callback_data=f"audio|{text}")],
            ]
            await update.message.reply_text(
                f"✅ *{platform.upper()}*",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("❌ منصة غير مدعومة")
    else:
        await update.message.reply_text("❓ أرسل رابط")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "search":
        context.user_data['search_mode'] = True
        await query.edit_message_text("🔍 *أرسل كلمة البحث:*", parse_mode="Markdown")
    
    elif data == "download_url":
        await query.edit_message_text("📎 *أرسل رابط التحميل:*", parse_mode="Markdown")
    
    elif data.startswith("dl|"):
        url = data.split("|", 1)[1]
        keyboard = [
            [InlineKeyboardButton("🎥 فيديو", callback_data=f"video|{url}")],
            [InlineKeyboardButton("🎵 صوت", callback_data=f"audio|{url}")],
        ]
        await query.edit_message_text(
            "✅ *اختر نوع التحميل:*",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    
    elif data.startswith("video|"):
        url = data.split("|", 1)[1]
        await query.edit_message_text("🎬 *جاري التحميل...*", parse_mode="Markdown")
        
        filename, title = await download_video(url)
        if filename and os.path.exists(filename) and os.path.getsize(filename) > 0:
            try:
                with open(filename, 'rb') as f:
                    await query.message.reply_video(video=f, caption=f"✅ {title[:100]}")
                os.remove(filename)
            except Exception as e:
                await query.message.reply_text(f"❌ خطأ: {str(e)[:100]}")
        else:
            await query.message.reply_text(f"❌ فشل: {title}")
    
    elif data.startswith("audio|"):
        url = data.split("|", 1)[1]
        await query.edit_message_text("🎵 *جاري التحميل...*", parse_mode="Markdown")
        
        filename, title = await download_audio(url)
        if filename and os.path.exists(filename) and os.path.getsize(filename) > 0:
            try:
                with open(filename, 'rb') as f:
                    await query.message.reply_audio(audio=f, title=title[:50])
                os.remove(filename)
            except Exception as e:
                await query.message.reply_text(f"❌ خطأ: {str(e)[:100]}")
        else:
            await query.message.reply_text(f"❌ فشل: {title}")

# ====================== تشغيل البوت (بدون connect_timeout) ======================
def main():
    # تبسيط التشغيل - بدون connect_timeout
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🚀 البوت يعمل...")
    app.run_polling()

if __name__ == "__main__":
    main()
