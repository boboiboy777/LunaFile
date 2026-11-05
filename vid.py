"""vid feature handlers and helpers."""
from __future__ import annotations

import tempfile
from urllib.parse import urlparse

_RUNTIME_NAMES = (
    "MAX_VIDEO_DOWNLOAD", "Path", "VIDEO_HOSTS", "YTDLP_COOKIES_FILE",
    "_reject_blocked_user", "asyncio", "log", "os",
)

def configure(runtime_globals):
    """Bind application services and configuration from the bot entry point."""
    missing = [name for name in _RUNTIME_NAMES if name not in runtime_globals]
    if missing:
        raise RuntimeError(f"vid.py missing runtime dependencies: {', '.join(missing)}")
    globals().update({name: runtime_globals[name] for name in _RUNTIME_NAMES})

def _is_video_url(value: str) -> bool:
    try:
        parsed = urlparse(value.strip())
        return parsed.scheme == "https" and (parsed.hostname or "").lower() in VIDEO_HOSTS
    except ValueError:
        return False

async def handle_video_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Route a plain text message containing a supported video URL."""
    value = (update.message.text or "").strip()
    if not _is_video_url(value):
        return False
    context.args = [value]
    await download_video(update, context)
    return True

def _download_video(url: str, folder: str) -> tuple[str, str]:
    """Download one supported social video with yt-dlp."""
    import yt_dlp

    options: dict[str, Any] = {
        "format": "best[filesize<=" + str(MAX_VIDEO_DOWNLOAD) + "]/best[height<=720]/best",
        "outtmpl": os.path.join(folder, "%(title).80s-%(id)s.%(ext)s"),
        "noplaylist": True, "max_filesize": MAX_VIDEO_DOWNLOAD,
        "quiet": True, "no_warnings": True, "restrictfilenames": True,
        "merge_output_format": "mp4",
    }
    if YTDLP_COOKIES_FILE and Path(YTDLP_COOKIES_FILE).is_file():
        options["cookiefile"] = YTDLP_COOKIES_FILE
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        if not os.path.exists(filename) and os.path.exists(os.path.splitext(filename)[0] + ".mp4"):
            filename = os.path.splitext(filename)[0] + ".mp4"
        if not os.path.isfile(filename):
            raise RuntimeError("Berkas hasil unduhan tidak ditemukan.")
        if os.path.getsize(filename) > MAX_VIDEO_DOWNLOAD:
            raise RuntimeError("Video melebihi batas ukuran unggahan bot.")
        return filename, str(info.get("title") or "video")

async def download_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _reject_blocked_user(update):
        return
    message = update.effective_message
    url = " ".join(context.args).strip()
    if not url:
        await message.reply_text("Kirim tautan video setelah perintah, contoh: /download https://youtu.be/...")
        return
    if not _is_video_url(url):
        await message.reply_text("Tautan tidak dikenali. Gunakan tautan HTTPS YouTube, Instagram, TikTok, atau Facebook.")
        return
    status = await message.reply_text("Sedang mengunduh video. Mohon tunggu…")
    try:
        with tempfile.TemporaryDirectory(prefix="aif-video-") as folder:
            filename, title = await asyncio.to_thread(_download_video, url, folder)
            with open(filename, "rb") as video:
                await message.reply_video(video=video, caption=title[:900], supports_streaming=True,
                                          read_timeout=120, write_timeout=120, connect_timeout=30)
        await status.delete()
    except Exception as exc:
        log.info("Unduhan video gagal (%s)", type(exc).__name__)
        details = str(exc)
        if "cookie" in details.lower() or "login" in details.lower() or "private" in details.lower():
            explanation = "Konten ini privat atau memerlukan login. Instagram Story biasanya memerlukan cookie akun yang berhak melihat Story tersebut."
        elif "melebihi" in details.lower() or "file is larger" in details.lower():
            explanation = f"Video melebihi batas {MAX_VIDEO_DOWNLOAD // (1024 * 1024)} MB Telegram."
        else:
            explanation = "Video tidak dapat diunduh. Pastikan tautan publik dan coba lagi nanti."
        await status.edit_text(explanation)
