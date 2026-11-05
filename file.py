"""file feature handlers and helpers."""
from __future__ import annotations

import io
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

try:
    import msoffcrypto
except ImportError:
    msoffcrypto = None


class FilePasswordRequired(Exception):
    pass


class IncorrectFilePassword(Exception):
    pass


_RUNTIME_NAMES = (
    "AIQuotaExceeded", "FREE_DAILY_AI_LIMIT", "FREE_FILE_LIMIT",
    "MAX_CHARS", "MAX_DOWNLOAD", "PREMIUM_MONTHLY_AI_LIMIT",
    "_reject_blocked_user", "admin_panel", "ask_model", "httpx", "log",
)

def configure(runtime_globals):
    """Bind application services and configuration from the bot entry point."""
    missing = [name for name in _RUNTIME_NAMES if name not in runtime_globals]
    if missing:
        raise RuntimeError(f"file.py missing runtime dependencies: {', '.join(missing)}")
    globals().update({name: runtime_globals[name] for name in _RUNTIME_NAMES})

async def handle_pending_password(update: Any, context: Any) -> bool:
    """Consume a password reply for an encrypted file awaiting extraction."""
    pending_file = context.user_data.get("encrypted_file_pending")
    if not pending_file:
        return False
    password = update.message.text or ""
    if not password:
        await update.message.reply_text("Kirim kata sandi file, atau gunakan /batal untuk membatalkan.")
        return True
    try:
        content = extract_file(pending_file["filename"], pending_file["data"], password=password)
    except IncorrectFilePassword:
        await update.message.reply_text("Kata sandi salah. Coba lagi atau gunakan /batal untuk membatalkan.")
        return True
    except FilePasswordRequired:
        await update.message.reply_text("Format enkripsi file ini belum didukung. Yang didukung: PDF, ZIP, dan dokumen Microsoft Office berpassword.")
        context.user_data.pop("encrypted_file_pending", None)
        return True
    except Exception:
        log.exception("Gagal membuka file yang dilindungi kata sandi")
        await update.message.reply_text("File tidak dapat dibuka dengan kata sandi tersebut.")
        return True
    filename = pending_file["filename"]
    context.user_data.pop("encrypted_file_pending", None)
    context.user_data["last_content"] = content
    context.user_data["last_filename"] = filename
    admin_panel.record_file_result(update.effective_user, True)
    await update.message.reply_text(f"Isi file {filename}:")
    displayed = content or "(Tidak ada teks yang dapat ditampilkan.)"
    for offset in range(0, len(displayed), 3900):
        await update.message.reply_text(displayed[offset:offset + 3900])
    await _respond(update, content, "Jelaskan isi file ini dan rangkum poin-poin pentingnya.")
    return True

def _clip(text: str) -> str:
    text = text.strip()
    return text[:MAX_CHARS] + ("\n\n[Konten dipotong karena batas ukuran.]" if len(text) > MAX_CHARS else "")

def _read_zip_item(archive: zipfile.ZipFile, item: zipfile.ZipInfo, password: bytes | None) -> bytes:
    try:
        return archive.read(item, pwd=password)
    except RuntimeError as exc:
        if "password" in str(exc).lower():
            raise IncorrectFilePassword from exc
        raise

def _extract_zip(data: bytes, apk: bool = False, password: str | None = None) -> str:
    output: list[str] = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        output.append(f"Arsip berisi {len(infos)} file. Daftar isi:\n" + "\n".join(i.filename for i in infos[:250]))
        if any(item.flag_bits & 0x1 for item in infos) and password is None:
            raise FilePasswordRequired("ZIP")
        password_bytes = password.encode("utf-8") if password is not None else None
        if apk:
            output.append("\nCatatan: APK adalah paket aplikasi Android. AndroidManifest.xml dan resources.arsc biasanya berbentuk biner dan tidak dapat dibaca sebagai teks biasa tanpa alat khusus.")
        budget = MAX_CHARS
        for item in infos:
            if budget <= 0:
                break
            name = item.filename.lower()
            if item.is_dir() or item.file_size > 2_000_000:
                continue
            wanted = name.endswith((".txt", ".md", ".json", ".xml", ".html", ".csv", ".properties", ".yml", ".yaml", ".js", ".kt", ".java", ".smali"))
            if apk and name.endswith((".dex", ".so")):
                # Pull readable ASCII strings from executable payloads; this is an inspection aid, not decompilation.
                raw = _read_zip_item(archive, item, password_bytes)
                strings = re.findall(rb"[\x20-\x7e]{6,}", raw)
                value = " ".join(s.decode("ascii", "ignore") for s in strings[:500])
                if value:
                    piece = f"\n\n--- {item.filename} (string terbaca) ---\n{value}"
                else:
                    continue
            elif wanted:
                raw = _read_zip_item(archive, item, password_bytes)
                piece = f"\n\n--- {item.filename} ---\n" + raw.decode("utf-8", "replace")
            else:
                continue
            piece = piece[:budget]
            output.append(piece)
            budget -= len(piece)
    return _clip("".join(output))

def extract_file(filename: str, data: bytes, password: str | None = None) -> str:
    suffix = Path(filename).suffix.lower()
    office_suffixes = {".docx", ".xlsx", ".pptx"}
    if suffix in office_suffixes and data.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
        if msoffcrypto is None:
            raise RuntimeError("Dukungan dekripsi Microsoft Office belum terpasang.")
        if password is None:
            raise FilePasswordRequired("Microsoft Office")
        try:
            office = msoffcrypto.OfficeFile(io.BytesIO(data))
            office.load_key(password=password)
            decrypted = io.BytesIO()
            office.decrypt(decrypted)
        except Exception as exc:
            raise IncorrectFilePassword from exc
        return extract_file(filename, decrypted.getvalue())
    if suffix in {".txt", ".md", ".csv", ".log", ".xml", ".html", ".htm", ".yaml", ".yml", ".ini", ".py", ".js", ".java", ".sql"}:
        return _clip(data.decode("utf-8", "replace"))
    if suffix == ".json":
        try:
            return _clip(json.dumps(json.loads(data.decode("utf-8-sig")), ensure_ascii=False, indent=2))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _clip(data.decode("utf-8", "replace"))
    if suffix == ".pdf":
        if PdfReader is None:
            return "Gagal, Hubungi admin."
        pdf = PdfReader(io.BytesIO(data))
        if pdf.is_encrypted:
            if password is None:
                raise FilePasswordRequired("PDF")
            try:
                if not pdf.decrypt(password):
                    raise IncorrectFilePassword
            except (ValueError, TypeError) as exc:
                raise IncorrectFilePassword from exc
        pages = [f"[Halaman {i + 1}]\n{page.extract_text() or ''}" for i, page in enumerate(pdf.pages)]
        return _clip("\n\n".join(pages) or "PDF ini tidak memiliki teks yang bisa diekstrak (mungkin hasil scan/gambar).")
    if suffix == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if any(item.flag_bits & 0x1 for item in archive.infolist()) and password is None:
                    raise FilePasswordRequired("DOCX")
                password_bytes = password.encode("utf-8") if password is not None else None
                xml = _read_zip_item(archive, archive.getinfo("word/document.xml"), password_bytes)
            root = ET.fromstring(xml)
            paragraphs = []
            for paragraph in root.findall(".//{*}p"):
                text = "".join(node.text or "" for node in paragraph.findall(".//{*}t"))
                if text.strip():
                    paragraphs.append(text)
            return _clip("\n".join(paragraphs) or "DOCX tidak memiliki teks yang bisa diekstrak.")
        except (zipfile.BadZipFile, KeyError, ET.ParseError):
            return "File DOCX tidak valid atau rusak."
    if suffix == ".apk":
        try:
            return _extract_zip(data, apk=True, password=password)
        except zipfile.BadZipFile:
            return "File APK tidak terbaca sebagai arsip ZIP yang valid."
    if suffix in {".zip", ".jar", ".docx", ".xlsx", ".pptx"}:
        try:
            return _extract_zip(data, password=password)
        except zipfile.BadZipFile:
            return "Arsip ZIP tidak valid atau rusak."
    # A useful fallback for unknown formats: show readable UTF-8 content if it exists.
    decoded = data.decode("utf-8", "replace")
    readable = "".join(ch for ch in decoded if ch.isprintable() or ch in "\n\r\t")
    if len(readable.strip()) > 30:
        return _clip(readable)
    return f"Format {suffix or 'tanpa ekstensi'} belum didukung untuk ekstraksi teks. Ukuran file: {len(data):,} byte."

async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _reject_blocked_user(update):
        return
    admin_panel.record_event(update.effective_user, "message")
    content = context.user_data.get("last_content")
    if not content:
        await update.message.reply_text("Kirim file terlebih dahulu.")
        return
    question = " ".join(context.args).strip()
    if not question:
        await update.message.reply_text("Contoh: /ask Apa poin utama dokumen ini?")
        return
    await _respond(update, content, question)

async def _respond(update: Update, content: str, question: str) -> None:
    msg = await update.message.reply_text("Membaca file...")
    try:
        answer = await ask_model(content, question, update.effective_user)
        answer = answer or "Ai tidak mengembalikan jawaban teks."
        # Telegram messages are limited to 4096 characters.
        for start in range(0, len(answer), 4000):
            chunk = answer[start:start + 4000]
            if start == 0:
                await msg.edit_text(chunk)
            else:
                await update.message.reply_text(chunk)
    except AIQuotaExceeded as exc:
        await msg.edit_text(f"Kuota paket {exc.plan} Anda bulan ini sudah habis ({exc.limit} panggilan AI). Hubungi admin untuk berlangganan Premium.")
    except httpx.HTTPStatusError as exc:
        log.warning("AI API HTTP error: %s", exc.response.status_code)
        await msg.edit_text(f"API Apinex mengembalikan HTTP {exc.response.status_code}. Periksa API key, model, dan endpoint.")
    except Exception:
        log.exception("Gagal memproses permintaan")
        await msg.edit_text("Gagal memproses file.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _reject_blocked_user(update):
        return
    user = update.effective_user
    if not user:
        return
    plan = admin_panel.get_user_plan(user.id, FREE_DAILY_AI_LIMIT, PREMIUM_MONTHLY_AI_LIMIT)
    file_count = admin_panel.get_file_count(user.id)
    if plan["plan"] != "Premium" and file_count >= FREE_FILE_LIMIT:
        await update.message.reply_text(
            f"Batas Gratis adalah {FREE_FILE_LIMIT} file. Anda sudah berhasil memproses {file_count} file. "
            "Pilih Premium untuk mengirim file tanpa batas."
        )
        return
    admin_panel.record_event(user, "file")
    doc = update.message.document
    succeeded = False
    waiting_for_password = False
    try:
        if doc.file_size and doc.file_size > MAX_DOWNLOAD:
            await update.message.reply_text(f"File terlalu besar. Batas saat ini {MAX_DOWNLOAD // (1024 * 1024)} MB.")
            return
        status = await update.message.reply_text("Mengunduh dan mengekstrak file...")
        try:
            tg_file = await context.bot.get_file(doc.file_id)
            stream = await tg_file.download_as_bytearray()
            if len(stream) > MAX_DOWNLOAD:
                await status.edit_text("File melewati batas ukuran yang diizinkan.")
                return
            content = extract_file(doc.file_name or "file", bytes(stream))
            context.user_data["last_content"] = content
            context.user_data["last_filename"] = doc.file_name or "file"
            filename = doc.file_name or "file"
            await status.edit_text(f"Isi file {filename}:")
            displayed = content or "(Tidak ada teks yang dapat ditampilkan.)"
            for offset in range(0, len(displayed), 3900):
                await update.message.reply_text(displayed[offset:offset + 3900])
            succeeded = True
            await _respond(update, content, "Jelaskan isi file ini dan rangkum poin-poin pentingnya.")
        except FilePasswordRequired as exc:
            waiting_for_password = True
            context.user_data["encrypted_file_pending"] = {
                "filename": doc.file_name or "file",
                "data": bytes(stream),
            }
            await status.edit_text(
                f"File {doc.file_name or 'ini'} dilindungi kata sandi ({exc}). "
                "Kirim kata sandinya di chat ini agar saya bisa membuka dan menampilkan isinya. "
                "Gunakan /batal untuk membatalkan."
            )
        except Exception:
            log.exception("Gagal menangani dokumen")
            await status.edit_text("Tidak dapat mengunduh atau membaca file. Coba format lain atau file yang lebih kecil.")
    finally:
        if not waiting_for_password:
            admin_panel.record_file_result(user, succeeded)
