"""airdrop feature handlers and helpers."""
from __future__ import annotations

from urllib.parse import urlparse

_RUNTIME_NAMES = (
    "AIRDROP_PAGE_SIZE", "InlineKeyboardButton", "InlineKeyboardMarkup",
    "_admin_keyboard", "_is_admin", "_reject_blocked_user", "admin_panel",
)

def configure(runtime_globals):
    """Bind application services and configuration from the bot entry point."""
    missing = [name for name in _RUNTIME_NAMES if name not in runtime_globals]
    if missing:
        raise RuntimeError(f"airdrop.py missing runtime dependencies: {', '.join(missing)}")
    globals().update({name: runtime_globals[name] for name in _RUNTIME_NAMES})

def _build_admin_airdrop_page(page: int = 0) -> tuple[str, InlineKeyboardMarkup]:
    total = admin_panel.count_airdrop_tasks()
    pages = max(1, (total + AIRDROP_PAGE_SIZE - 1) // AIRDROP_PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    tasks = admin_panel.list_airdrop_tasks(AIRDROP_PAGE_SIZE, page * AIRDROP_PAGE_SIZE)
    lines = ["🪂 GARAPAN AIRDROP ADMIN", f"Jumlah garapan: {total}", ""]
    rows: list[list[InlineKeyboardButton]] = []
    if tasks:
        for task in tasks:
            lines.extend([f"{task['title']}", task["description"], ""])
            rows.append([
                InlineKeyboardButton("🔗 Buka", url=task["url"]),
                InlineKeyboardButton("🗑 Hapus", callback_data=f"admin:airdrop:delete:{task['id']}"),
            ])
    else:
        lines.append("Belum ada garapan. Tambahkan nama, deskripsi, dan tautan HTTPS.")
    rows.append([InlineKeyboardButton("➕ Tambah garapan", callback_data="admin:airdrop:add")])
    navigation = []
    if page > 0:
        navigation.append(InlineKeyboardButton("‹ Sebelumnya", callback_data=f"admin:airdrop:page:{page-1}"))
    if page + 1 < pages:
        navigation.append(InlineKeyboardButton("Berikutnya ›", callback_data=f"admin:airdrop:page:{page+1}"))
    if navigation:
        rows.append(navigation)
    rows.append([InlineKeyboardButton("🏠 Menu admin", callback_data="admin:home")])
    return "\n".join(lines), InlineKeyboardMarkup(rows)

async def handle_admin_callback(query: Any, context: Any, parts: list[str]) -> bool:
    """Handle the admin-side airdrop list, add, and delete actions."""
    if parts[:2] != ["admin", "airdrop"]:
        return False
    if len(parts) == 2:
        text, keyboard = _build_admin_airdrop_page()
        await query.edit_message_text(text, reply_markup=keyboard)
        return True
    if len(parts) == 3 and parts[2] == "add":
        for key in ("redeem_setup", "broadcast_setup", "broadcast_draft", "premium_setup_target"):
            context.user_data.pop(key, None)
        context.user_data["airdrop_setup"] = {"step": "title"}
        await query.edit_message_text(
            "Kirim nama garapan airdrop (maksimum 80 karakter).\n\nGunakan /batal untuk membatalkan.",
            reply_markup=_admin_keyboard())
        return True
    if len(parts) == 4 and parts[2] == "page":
        try:
            page = max(0, int(parts[3]))
        except ValueError:
            page = 0
        text, keyboard = _build_admin_airdrop_page(page)
        await query.edit_message_text(text, reply_markup=keyboard)
        return True
    if len(parts) == 4 and parts[2] in ("delete", "confirmdelete", "canceldelete"):
        try:
            task_id = int(parts[3])
        except ValueError:
            await query.edit_message_text("ID garapan tidak valid.", reply_markup=_admin_keyboard())
            return True
        if parts[2] == "delete":
            task = admin_panel.get_airdrop_task(task_id)
            if not task:
                await query.edit_message_text(
                    "Garapan tidak ditemukan.", reply_markup=_build_admin_airdrop_page()[1])
                return True
            await query.edit_message_text(
                f"Hapus garapan ini?\n\n{task['title']}\n{task['description']}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🗑 Ya, hapus", callback_data=f"admin:airdrop:confirmdelete:{task_id}")],
                    [InlineKeyboardButton("Batal", callback_data=f"admin:airdrop:canceldelete:{task_id}")],
                ]),
            )
            return True
        if parts[2] == "confirmdelete":
            deleted = admin_panel.delete_airdrop_task(task_id)
            text, keyboard = _build_admin_airdrop_page()
            notice = "Garapan dihapus.\n\n" if deleted else "Garapan tidak ditemukan.\n\n"
            await query.edit_message_text(notice + text, reply_markup=keyboard)
            return True
        text, keyboard = _build_admin_airdrop_page()
        await query.edit_message_text(text, reply_markup=keyboard)
        return True
    return False

def _build_user_airdrop_page(page: int = 0) -> tuple[str, InlineKeyboardMarkup]:
    total = admin_panel.count_airdrop_tasks()
    pages = max(1, (total + AIRDROP_PAGE_SIZE - 1) // AIRDROP_PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    tasks = admin_panel.list_airdrop_tasks(AIRDROP_PAGE_SIZE, page * AIRDROP_PAGE_SIZE)
    lines = ["🪂 GARAPAN AIRDROP", ""]
    rows: list[list[InlineKeyboardButton]] = []
    if tasks:
        for task in tasks:
            lines.extend([f"{task['title']}", task["description"], ""])
            rows.append([InlineKeyboardButton(f"🚀 Buka {task['title'][:45]}", url=task["url"])])
        lines.append(f"Halaman {page + 1}/{pages}")
    else:
        lines.append("Belum ada garapan airdrop yang tersedia.")
    navigation = []
    if page > 0:
        navigation.append(InlineKeyboardButton("‹ Sebelumnya", callback_data=f"airdrop:page:{page-1}"))
    if page + 1 < pages:
        navigation.append(InlineKeyboardButton("Berikutnya ›", callback_data=f"airdrop:page:{page+1}"))
    if navigation:
        rows.append(navigation)
    rows.append([InlineKeyboardButton("🏠 Menu awal", callback_data="nav:home")])
    return "\n".join(lines), InlineKeyboardMarkup(rows)

async def show_airdrop_page(message: Any, page: int = 0) -> None:
    text, keyboard = _build_user_airdrop_page(page)
    await message.reply_text(text, reply_markup=keyboard)

async def airdrop_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _reject_blocked_user(update):
        return
    await show_airdrop_page(update.effective_message)

async def airdrop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    if await _reject_blocked_user(update):
        await query.answer("Akses bot sedang dibatasi.", show_alert=True)
        return
    try:
        page = max(0, int((query.data or "").split(":")[2]))
    except (IndexError, ValueError):
        page = 0
    text, keyboard = _build_user_airdrop_page(page)
    await query.answer()
    await query.edit_message_text(text, reply_markup=keyboard)

def _valid_airdrop_url(value: str) -> bool:
    if not value or len(value) > 500 or any(char.isspace() for char in value):
        return False
    try:
        parsed = urlparse(value)
        return bool(parsed.scheme == "https" and parsed.hostname and "." in parsed.hostname
                    and parsed.username is None and parsed.password is None)
    except ValueError:
        return False

async def _handle_airdrop_setup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    setup = context.user_data.get("airdrop_setup")
    if not setup:
        return False
    if not _is_admin(update):
        context.user_data.pop("airdrop_setup", None)
        return True
    value = (update.effective_message.text or "").strip()
    step = setup.get("step")
    if step == "title":
        if not 1 <= len(value) <= 80:
            await update.effective_message.reply_text("Nama garapan harus 1–80 karakter. Kirim nama yang valid atau /batal.")
            return True
        setup["title"] = value
        setup["step"] = "description"
        await update.effective_message.reply_text("Kirim deskripsi garapan (1–300 karakter), atau /batal untuk membatalkan.")
        return True
    if step == "description":
        if not 1 <= len(value) <= 300:
            await update.effective_message.reply_text("Deskripsi harus 1–300 karakter. Kirim deskripsi yang valid atau /batal.")
            return True
        setup["description"] = value
        setup["step"] = "url"
        await update.effective_message.reply_text("Kirim tautan HTTPS garapan. Contoh: https://example.com/airdrop")
        return True
    if step == "url":
        if not _valid_airdrop_url(value):
            await update.effective_message.reply_text("Tautan harus berupa URL HTTPS yang valid. Coba lagi atau kirim /batal.")
            return True
        task_id = admin_panel.create_airdrop_task(
            setup["title"], setup["description"], value, update.effective_user.id
        )
        title = setup["title"]
        context.user_data.pop("airdrop_setup", None)
        text, keyboard = _build_admin_airdrop_page()
        await update.effective_message.reply_text(f"✅ Garapan #{task_id} berhasil ditambahkan: {title}\n\n{text}", reply_markup=keyboard)
        return True
    context.user_data.pop("airdrop_setup", None)
    await update.effective_message.reply_text("Proses penambahan garapan direset. Mulai lagi dari panel admin.", reply_markup=_admin_keyboard())
    return True
