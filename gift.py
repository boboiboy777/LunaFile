"""Public Premium gift creation and channel claim handlers."""
from __future__ import annotations

import secrets

_RUNTIME_NAMES = (
    "InlineKeyboardButton", "InlineKeyboardMarkup", "MIDTRANS_SERVER_KEY",
    "NUMBER_PURCHASE_CHANNEL_ID", "PREMIUM_PACKAGES", "ParseMode", "REQUIRED_CHANNEL_ID",
    "_reject_blocked_user", "_tab_keyboard", "admin_panel", "html_escape", "log",
)


def configure(runtime_globals):
    """Bind bot services and configuration from the application entry point."""
    missing = [name for name in _RUNTIME_NAMES if name not in runtime_globals]
    if missing:
        raise RuntimeError(f"gift.py missing runtime dependencies: {', '.join(missing)}")
    globals().update({name: runtime_globals[name] for name in _RUNTIME_NAMES})


def _gift_price(days: int) -> int:
    """Price custom gift durations using the cheapest combination of current packages."""
    prices = tuple((int(package_days), int(price)) for package_days, price in PREMIUM_PACKAGES.items())
    best = [0] + [10**18] * days
    for target in range(1, days + 1):
        best[target] = min(best[target - package_days] + price
                           for package_days, price in prices if package_days <= target)
    return int(best[days])


async def _show_gift_confirmation(message, user_id: int, days: int, users: int = 1) -> None:
    if not 1 <= days <= 1000 or not 1 <= users <= 1000:
        await message.reply_text("Durasi dan jumlah penerima harus masing-masing 1–1000.")
        return
    price_per_user = _gift_price(days)
    amount_idr = price_per_user * users
    balance = admin_panel.number_wallet_balance(user_id)
    lines = [f"🎁 Gift Premium {days} hari untuk {users} pengguna",
             f"Harga per pengguna: Rp{price_per_user:,}", f"Total: Rp{amount_idr:,}", f"Saldo: Rp{balance:,}",
             "Gift akan disiarkan di channel transaksi dan dapat diklaim oleh sejumlah pengguna tersebut."]
    buttons = []
    if balance >= amount_idr:
        buttons.append([InlineKeyboardButton("✅ Buat gift", callback_data=f"gift:create:{days}:{users}")])
    elif MIDTRANS_SERVER_KEY:
        lines.append(f"Saldo kurang Rp{amount_idr - balance:,}. Top up Saldo terlebih dahulu.")
        buttons.append([InlineKeyboardButton("➕ Top up Saldo", callback_data="wallet:home")])
    else:
        lines.append(f"Saldo kurang Rp{amount_idr - balance:,}; top up QRIS belum dikonfigurasi.")
    buttons.append([InlineKeyboardButton("Batal", callback_data="gift:cancel")])
    await message.reply_text("\n".join(lines), reply_markup=_tab_keyboard(buttons))


async def gift_command(update, context) -> None:
    if await _reject_blocked_user(update):
        return
    user = update.effective_user
    if not user:
        return
    if context.args:
        if len(context.args) not in {1, 2} or not all(arg.isdigit() for arg in context.args):
            await update.effective_message.reply_text("Gunakan /gift <hari> [jumlah_pengguna], contoh: /gift 1 3.")
            return
        days = int(context.args[0])
        users = int(context.args[1]) if len(context.args) == 2 else 1
        await _show_gift_confirmation(update.effective_message, user.id, days, users)
        return
    context.user_data["premium_gift_waiting_days"] = True
    await update.effective_message.reply_text(
        "Kirim durasi dan jumlah penerima, contoh: 1 3 (Premium 1 hari untuk 3 pengguna).\n"
        "Nilai masing-masing 1–1000. Gunakan /batal untuk membatalkan.")


async def handle_pending_text(update, context) -> bool:
    if not context.user_data.get("premium_gift_waiting_days"):
        return False
    raw = (update.message.text or "").strip()
    parts = raw.split()
    if len(parts) not in {1, 2} or not all(part.isdigit() for part in parts):
        await update.message.reply_text("Kirim format hari jumlah_pengguna, contoh: 1 3. Coba lagi atau gunakan /batal.")
        return True
    days = int(parts[0])
    users = int(parts[1]) if len(parts) == 2 else 1
    if not 1 <= days <= 1000 or not 1 <= users <= 1000:
        await update.message.reply_text("Durasi dan jumlah penerima harus masing-masing 1–1000. Coba lagi atau /batal.")
        return True
    context.user_data.pop("premium_gift_waiting_days", None)
    await _show_gift_confirmation(update.message, update.effective_user.id, days, users)
    return True


def _gift_post_text(gifter_id: int, days: int, max_uses: int, used_count: int) -> str:
    remaining = max_uses - used_count
    heading = "🎁 <b>GIFT PREMIUM TERSEDIA</b>" if remaining else "🎉 <b>GIFT PREMIUM SUDAH HABIS</b>"
    lines = [heading, "————————————–––––——––•",
             f'• Pemberi: <a href="tg://user?id={gifter_id}">Pengguna</a>',
             f"• Durasi: Premium {days} hari per pengguna",
             f"• Klaim: {used_count}/{max_uses} pengguna",
             f"• Tersedia: {remaining} klaim"]
    if remaining:
        lines.extend(["", "Tekan tombol di bawah untuk mengklaim. Gift hanya bisa diklaim di channel transaksi."])
    return "\n".join(lines)


def _gift_claim_markup(code: str, remaining: int) -> InlineKeyboardMarkup | None:
    if remaining <= 0:
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton("🎁 Klaim Premium", callback_data=f"gift:claim:{code}")]])


def _is_transaction_channel(message) -> bool:
    if not message or not message.chat:
        return False
    target = str(NUMBER_PURCHASE_CHANNEL_ID or REQUIRED_CHANNEL_ID).strip()
    if not target:
        return False
    if str(message.chat.id) == target:
        return True
    return target.startswith("@") and (message.chat.username or "").casefold() == target[1:].casefold()


async def gift_callback(update, context) -> None:
    query, user = update.callback_query, update.effective_user
    if not query or not user:
        return
    if await _reject_blocked_user(update):
        await query.answer("Akses bot sedang dibatasi.", show_alert=True)
        return
    parts = (query.data or "").split(":")
    if len(parts) == 2 and parts[1] == "start":
        context.user_data["premium_gift_waiting_days"] = True
        await query.answer()
        await query.message.reply_text(
            "Kirim durasi dan jumlah penerima, contoh: 1 3 (Premium 1 hari untuk 3 pengguna).\n"
            "Nilai masing-masing 1–1000. Gunakan /batal untuk membatalkan.")
        return
    if len(parts) == 2 and parts[1] == "cancel":
        await query.answer("Gift dibatalkan.")
        await query.edit_message_reply_markup(reply_markup=None)
        return
    action = parts[1] if len(parts) > 1 else ""
    if action == "create":
        if len(parts) != 4 or not parts[2].isdigit() or not parts[3].isdigit():
            await query.answer("Tombol gift tidak valid.", show_alert=True)
            return
        days, users = int(parts[2]), int(parts[3])
        if not 1 <= days <= 1000 or not 1 <= users <= 1000:
            await query.answer("Durasi dan jumlah penerima harus 1–1000.", show_alert=True)
            return
        amount_idr = _gift_price(days) * users
        code = secrets.token_hex(10).upper()
        created, balance = admin_panel.create_premium_gift(code, user.id, days, users, amount_idr)
        if not created:
            buttons = []
            if MIDTRANS_SERVER_KEY:
                buttons.append([InlineKeyboardButton("➕ Top up Saldo", callback_data="wallet:home")])
            buttons.append([InlineKeyboardButton("Batal", callback_data="gift:cancel")])
            await query.answer("Saldo tidak cukup.", show_alert=True)
            await query.edit_message_text(
                f"Saldo Anda Rp{balance:,}; gift {days} hari untuk {users} pengguna berharga Rp{amount_idr:,}.",
                reply_markup=_tab_keyboard(buttons))
            return
        text = _gift_post_text(user.id, days, users, 0)
        markup = _gift_claim_markup(code, users)
        try:
            await context.bot.send_message(
                chat_id=NUMBER_PURCHASE_CHANNEL_ID or REQUIRED_CHANNEL_ID,
                text=text, reply_markup=markup, parse_mode=ParseMode.HTML)
            if not admin_panel.activate_premium_gift(code):
                raise RuntimeError("Gift tidak dapat diaktifkan setelah disiarkan")
        except Exception:
            admin_panel.cancel_premium_gift(code)
            log.exception("Gagal menyiarkan gift Premium ke channel transaksi")
            await query.answer("Gift gagal disiarkan; Saldo dikembalikan.", show_alert=True)
            await query.edit_message_text("Gift gagal disiarkan. Saldo Anda sudah dikembalikan.")
            return
        await query.answer("Gift berhasil disiarkan di channel transaksi.")
        await query.edit_message_text(
            f"✅ Gift Premium {days} hari untuk {users} pengguna disiarkan di channel transaksi.\n"
            f"Total: Rp{amount_idr:,}\nSaldo tersisa: Rp{balance:,}.",
            reply_markup=_tab_keyboard([[InlineKeyboardButton("⭐ Beli Premium", callback_data="nav:premium")]]))
        return
    if action != "claim":
        await query.answer("Tombol gift tidak valid.", show_alert=True)
        return
    if len(parts) != 3:
        await query.answer("Tombol gift tidak valid.", show_alert=True)
        return
    if not _is_transaction_channel(query.message):
        await query.answer("Gift hanya dapat diklaim dari channel transaksi.", show_alert=True)
        return
    state, days, gifter_id, used_count, max_uses, expires_at = admin_panel.claim_premium_gift(parts[2], user.id)
    if state != "ok":
        messages = {
            "self_claim": "Pemberi tidak dapat mengklaim gift sendiri.",
            "claimed": "Gift ini sudah diklaim.",
            "already_claimed": "Anda sudah mengklaim gift ini.",
            "unavailable": "Gift belum tersedia.",
            "invalid": "Gift tidak ditemukan.",
        }
        await query.answer(messages.get(state, "Gift tidak dapat diklaim."), show_alert=True)
        return
    remaining = max_uses - used_count
    await query.answer(f"Premium {days} hari berhasil diklaim! Sisa klaim: {remaining}.")
    claim_text = _gift_post_text(gifter_id, days, max_uses, used_count)
    try:
        await query.edit_message_text(claim_text, parse_mode=ParseMode.HTML,
                                      reply_markup=_gift_claim_markup(parts[2], remaining))
    except Exception:
        log.exception("Gagal memperbarui pengumuman gift yang diklaim")
    try:
        await context.bot.send_message(
            chat_id=user.id, text=f"✅ Anda mengklaim gift Premium {days} hari. Masa aktif ditambahkan ke akun Anda sampai {expires_at} UTC.")
    except Exception:
        log.warning("Tidak dapat mengirim DM konfirmasi gift ke pengguna %s", user.id)
    try:
        await context.bot.send_message(
            chat_id=gifter_id,
            text=f"🎁 Gift Premium {days} hari diklaim oleh pengguna {user.id} ({used_count}/{max_uses}). "
                 f"Sisa klaim: {remaining}.")
    except Exception:
        log.warning("Tidak dapat mengirim pemberitahuan klaim gift ke pemberi %s", gifter_id)
