"""buy feature handlers and helpers."""
from __future__ import annotations

import io
import uuid
from urllib.parse import urlparse

_RUNTIME_NAMES = (
    "FREE_DAILY_AI_LIMIT", "InlineKeyboardButton", "MIDTRANS_API_BASE",
    "MIDTRANS_IS_PRODUCTION", "MIDTRANS_QRIS_ACQUIRER", "MIDTRANS_SERVER_KEY",
    "NUMBER_PURCHASE_CHANNEL_ID", "NUMBER_TOPUP_MIN_IDR", "PREMIUM_MONTHLY_AI_LIMIT",
    "PREMIUM_PACKAGES", "ParseMode", "WIB", "_reject_blocked_user",
    "_send_home_to_user", "_tab_keyboard", "admin_panel", "asyncio", "datetime",
    "html_escape", "httpx", "log", "timedelta", "timezone",
)

def configure(runtime_globals):
    """Bind application services and configuration from the bot entry point."""
    missing = [name for name in _RUNTIME_NAMES if name not in runtime_globals]
    if missing:
        raise RuntimeError(f"buy.py missing runtime dependencies: {', '.join(missing)}")
    globals().update({name: runtime_globals[name] for name in _RUNTIME_NAMES})

async def plans_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _reject_blocked_user(update):
        return
    user = update.effective_user
    if not user:
        return
    plan = admin_panel.get_user_plan(user.id, FREE_DAILY_AI_LIMIT, PREMIUM_MONTHLY_AI_LIMIT)
    premium_note = f"\nStatus Anda: {plan['plan']}."
    if plan["expires_at"]:
        premium_time = datetime.fromisoformat(plan["expires_at"]).strftime("%Y-%m-%d %H:%M:%S")
        premium_note += f" Berlaku sampai {premium_time} UTC."
    payment_ready = bool(MIDTRANS_SERVER_KEY)
    package_lines = [f"• {days} hari — Rp{price:,}" for days, price in PREMIUM_PACKAGES.items()]
    message = ("💎 <b>PREMIUM</b> 💎\n\n"
               "Premium: Unlimited file.\n\n"
               "Pilihan paket (masa aktif ditambahkan ke sisa masa aktif):\n" + "\n".join(package_lines))
    if payment_ready:
        message += "\n\nPilih paket untuk membayar melalui QRIS."
        buttons = [[InlineKeyboardButton(f"{days} hari · Rp{price:,}", callback_data=f"plan:buy:{days}")]
                   for days, price in PREMIUM_PACKAGES.items()]
        keyboard = _tab_keyboard(buttons)
    else:
        message += "\n\nPembelian QRIS belum dikonfigurasi. Hubungi admin bot."
        keyboard = _tab_keyboard()
    await update.effective_message.reply_text(message + premium_note, reply_markup=keyboard, parse_mode=ParseMode.HTML)

def _midtrans_url_is_valid(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    # Midtrans QR action URLs can use either API hostname, including when the
    # charge itself was created against the Sandbox endpoint. The newer
    # generate-qr-code-v2 action can also use the merchants-app host. Reject
    # any other host before sending the Server Key.
    return parsed.scheme == "https" and parsed.hostname in {
        "api.midtrans.com",
        "api.sandbox.midtrans.com",
        "merchants-app.midtrans.com",
        "merchants-app.sbx.midtrans.com",
    }

async def _midtrans_get_status(order_id: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=10)) as client:
        response = await client.get(
            f"{MIDTRANS_API_BASE}/v2/{order_id}/status",
            auth=(MIDTRANS_SERVER_KEY, ""),
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        data = response.json()
    if not isinstance(data, dict):
        raise ValueError("Respons status pembayaran tidak valid")
    return data

def _number_topup_receipt(payment: dict[str, Any]) -> str:
    paid_at = payment.get("paid_at") or payment["created_at"]
    paid_time = datetime.fromisoformat(paid_at).astimezone(WIB)
    return (
        "🧾 <b>Invoice top up</b>\n"
        "✅ Top up berhasil\n"
        f"Nominal: Rp{payment['amount_idr']:,}\n"
        f"Waktu: {paid_time.strftime('%d-%m-%Y %H:%M:%S')} WIB\n"
        f"ID transaksi: <code>{html_escape(str(payment['order_id']))}</code>\n"
        f"Saldo nomor: Rp{admin_panel.number_wallet_balance(payment['user_id']):,}"
    )

async def _send_qris_status(bot: Any, user_id: int, order_id: str, message: str) -> None:
    await bot.send_message(chat_id=user_id, text=message, parse_mode=ParseMode.HTML)
    payment = admin_panel.get_payment(order_id)
    if payment and payment.get("purpose") == "numbers_topup" and payment.get("status") == "paid":
        await _send_home_to_user(bot, user_id)

async def _check_qris_payment(bot: Any, order_id: str, user_id: int) -> tuple[bool, str]:
    payment = admin_panel.get_payment(order_id)
    if not payment or payment["user_id"] != user_id:
        return False, "Transaksi tidak ditemukan."
    if payment["status"] == "paid":
        if payment.get("purpose") == "numbers_topup":
            return True, _number_topup_receipt(payment)
        await _announce_premium_payment_once(bot, payment)
        return True, f"Pembayaran sudah diterima; Premium aktif selama {payment['plan_days']} hari."
    if payment["status"] != "pending":
        return False, f"Status transaksi: {payment['status']}. Buat transaksi baru melalui /paket."
    try:
        status = await _midtrans_get_status(order_id)
    except (httpx.HTTPError, ValueError):
        log.exception("Gagal memeriksa status transaksi Midtrans")
        return False, "Status belum dapat diperiksa. Coba lagi sebentar."
    if (status.get("order_id") != order_id or status.get("payment_type") != "qris"
            or status.get("currency") != "IDR"
            or status.get("fraud_status") not in (None, "accept")):
        log.warning("Respons status Midtrans tidak cocok dengan order QRIS %s", order_id)
        return False, "Data status transaksi tidak cocok. Hubungi admin."
    try:
        paid_amount = int(float(status.get("gross_amount", "0")))
    except (TypeError, ValueError):
        paid_amount = 0
    if paid_amount != payment["amount_idr"]:
        log.warning("Nominal status Midtrans berbeda untuk order %s", order_id)
        return False, "Nominal transaksi tidak cocok. Hubungi admin."
    transaction_status = status.get("transaction_status")
    if transaction_status == "settlement":
        if admin_panel.settle_payment(order_id, user_id, paid_amount):
            settled_payment = admin_panel.get_payment(order_id) or payment
            if payment.get("purpose") == "numbers_topup":
                return True, _number_topup_receipt(settled_payment)
            await _announce_premium_payment_once(bot, settled_payment)
            return True, f"Pembayaran diterima. Premium Anda aktif selama {payment['plan_days']} hari."
        return False, "Transaksi kedaluwarsa atau sudah diproses. Hubungi admin jika dana sudah terpotong."
    if transaction_status in ("expire", "deny", "cancel", "failure"):
        admin_panel.mark_payment_status(order_id, str(transaction_status))
        return False, "QRIS kedaluwarsa atau pembayaran gagal. Buat transaksi baru melalui /paket."
    return False, "Pembayaran masih menunggu. Bot akan memeriksa lagi otomatis; Anda juga bisa menekan tombol cek status."

async def _delete_qris_message(bot: Any, user_id: int, message_id: int | None) -> None:
    if not message_id:
        return
    try:
        await bot.delete_message(chat_id=user_id, message_id=message_id)
    except Exception:
        # Telegram may reject deletion after its time limit or if the message
        # was already removed by the user.
        log.debug("Tidak dapat menghapus pesan QRIS %s untuk pengguna %s", message_id, user_id, exc_info=True)

async def _watch_qris_payment(bot: Any, order_id: str, user_id: int, message_id: int) -> None:
    for _ in range(58):
        await asyncio.sleep(15)
        payment = admin_panel.get_payment(order_id)
        if not payment:
            return
        if payment["status"] == "paid":
            await _delete_qris_message(bot, user_id, message_id)
            return
        if payment["status"] != "pending":
            return
        if payment["expires_at"] <= datetime.now(timezone.utc).isoformat(timespec="seconds"):
            admin_panel.mark_payment_status(order_id, "expire")
            return
        paid, message = await _check_qris_payment(bot, order_id, user_id)
        if paid:
            await _delete_qris_message(bot, user_id, message_id)
            await _send_qris_status(bot, user_id, order_id, message)
            return
        if "kedaluwarsa" in message or "gagal" in message:
            await bot.send_message(chat_id=user_id, text=message, parse_mode=ParseMode.HTML)
            return

async def _create_qris_payment(message: Any, context: ContextTypes.DEFAULT_TYPE, user: Any,
                               purpose: str, plan_days: int, amount_idr: int) -> None:
    if not MIDTRANS_SERVER_KEY:
        await message.reply_text("Pembelian QRIS belum dikonfigurasi. Hubungi admin bot.")
        return
    if purpose == "premium":
        item_id, item_name = f"premium-{plan_days}d", f"Premium {plan_days} hari"
    else:
        item_id, item_name = f"numbers-topup-{amount_idr}", f"Top up saldo nomor Rp{amount_idr:,}"
    order_id = f"{'PREM' if purpose == 'premium' else 'WAL'}-{user.id}-{uuid.uuid4().hex[:16]}"
    expiry = datetime.now(timezone.utc) + timedelta(minutes=15)
    local_expiry = expiry.isoformat(timespec="seconds")
    admin_panel.create_payment(order_id, user.id, amount_idr, plan_days, local_expiry, purpose=purpose)
    payload = {
        "payment_type": "qris",
        "transaction_details": {"order_id": order_id, "gross_amount": amount_idr},
        "item_details": [{"id": item_id, "price": amount_idr,
                          "quantity": 1, "name": item_name}],
        "qris": {"acquirer": MIDTRANS_QRIS_ACQUIRER},
        "custom_expiry": {"expiry_duration": 15, "unit": "minute"},
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=10)) as client:
            response = await client.post(
                f"{MIDTRANS_API_BASE}/v2/charge", json=payload,
                auth=(MIDTRANS_SERVER_KEY, ""), headers={"Accept": "application/json"})
            response.raise_for_status()
            result = response.json()
        action = next((a for a in result.get("actions", [])
                       if a.get("name") == "generate-qr-code-v2"), None)
        if action is None:
            action = next((a for a in result.get("actions", [])
                           if a.get("name") == "generate-qr-code"), None)
        qr_url = action.get("url", "") if action else ""
        if (result.get("order_id") != order_id or result.get("transaction_status") != "pending"
                or not _midtrans_url_is_valid(qr_url)):
            qr_host = urlparse(qr_url).hostname if qr_url else None
            log.error(
                "Respons charge QRIS tidak cocok: order_id_match=%s, status=%s, "
                "action=%s, qr_host=%s",
                result.get("order_id") == order_id,
                result.get("transaction_status"),
                action.get("name") if action else None,
                qr_host,
            )
            raise ValueError("Respons charge QRIS tidak valid")
        async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=10), follow_redirects=False) as client:
            qr_response = await client.get(qr_url, auth=(MIDTRANS_SERVER_KEY, ""))
            qr_response.raise_for_status()
        image = io.BytesIO(qr_response.content)
        image.name = "qris-payment.png"
        payment_buttons = [[InlineKeyboardButton("🔄 Periksa status pembayaran",
                                                 callback_data=f"plan:check:{order_id}")]]
        payment_buttons.append([InlineKeyboardButton("✖️ Batal transaksi",
                                                      callback_data=f"plan:cancel:{order_id}")])
        keyboard = _tab_keyboard(payment_buttons)
        caption = (f"QRIS Premium {plan_days} hari" if purpose == "premium" else "QRIS Top Up Saldo Nomor")
        caption += f"\nNominal: Rp{amount_idr:,}\nBerlaku 15 menit. Setelah membayar, saldo akan diproses otomatis."
        if not MIDTRANS_IS_PRODUCTION:
            caption += (
                f"\n\nURL QR untuk simulator Sandbox:\n{qr_url}"
                "\nSimulator: https://simulator.sandbox.midtrans.com/openapi/qris/index"
            )
        qr_message = await message.reply_photo(photo=image, caption=caption, reply_markup=keyboard)
        asyncio.create_task(_watch_qris_payment(context.bot, order_id, user.id, qr_message.message_id))
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        admin_panel.mark_payment_status(order_id, "error")
        log.exception("Gagal membuat QRIS Midtrans")
        await message.reply_text("QRIS belum dapat dibuat. Coba lagi nanti atau hubungi admin.")

async def _cancel_qris_payment(query: Any, user: Any, order_id: str) -> None:
    payment = admin_panel.get_payment(order_id)
    if (not payment or payment["user_id"] != user.id
            or payment.get("purpose") not in {"premium", "numbers_topup"}):
        await query.message.reply_text("Transaksi QRIS tidak ditemukan.")
        return
    if payment["status"] != "pending":
        paid, message = await _check_qris_payment(query.get_bot(), order_id, user.id)
        if paid:
            await _delete_qris_message(query.get_bot(), user.id, query.message.message_id)
        await _send_qris_status(query.get_bot(), user.id, order_id, message)
        return
    try:
        paid, message = await _check_qris_payment(query.get_bot(), order_id, user.id)
    except (httpx.HTTPError, ValueError):
        await query.get_bot().send_message(chat_id=user.id, text="Status transaksi belum dapat diperiksa. Coba lagi sebentar.")
        return
    payment = admin_panel.get_payment(order_id)
    if paid or not payment or payment["status"] != "pending":
        if paid:
            await _delete_qris_message(query.get_bot(), user.id, query.message.message_id)
        await _send_qris_status(query.get_bot(), user.id, order_id, message)
        return
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=10)) as client:
            response = await client.post(
                f"{MIDTRANS_API_BASE}/v2/{order_id}/cancel",
                auth=(MIDTRANS_SERVER_KEY, ""), headers={"Accept": "application/json"})
            response.raise_for_status()
            result = response.json()
        if result.get("order_id") == order_id and result.get("transaction_status") in {"cancel", "cancelled"}:
            admin_panel.mark_payment_status(order_id, "cancel")
            await _delete_qris_message(query.get_bot(), user.id, query.message.message_id)
            await query.get_bot().send_message(chat_id=user.id, text="✅ Transaksi QRIS berhasil dibatalkan.")
            return
    except (httpx.HTTPError, ValueError, TypeError):
        log.exception("Gagal membatalkan transaksi QRIS top up nomor %s", order_id)
    try:
        paid, message = await _check_qris_payment(query.get_bot(), order_id, user.id)
        payment = admin_panel.get_payment(order_id)
        if paid or not payment or payment["status"] != "pending":
            if paid:
                await _delete_qris_message(query.get_bot(), user.id, query.message.message_id)
            await _send_qris_status(query.get_bot(), user.id, order_id, message)
        else:
            await query.get_bot().send_message(chat_id=user.id, text="Pembatalan belum terkonfirmasi. Coba tekan Batal transaksi lagi.")
    except (httpx.HTTPError, ValueError):
        await query.get_bot().send_message(chat_id=user.id, text="Pembatalan belum terkonfirmasi. Coba periksa status transaksi lagi.")

async def payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return
    if await _reject_blocked_user(update):
        await query.answer("Akses bot sedang dibatasi.", show_alert=True)
        return
    await query.answer()
    parts = (query.data or "").split(":")
    if len(parts) == 3 and parts[1] in {"buy", "topup"}:
        purpose = "premium" if parts[1] == "buy" else "numbers_topup"
        try:
            if purpose == "premium":
                plan_days = int(parts[2])
                amount_idr = PREMIUM_PACKAGES[plan_days]
            else:
                plan_days = 0
                amount_idr = int(parts[2])
                if amount_idr < NUMBER_TOPUP_MIN_IDR:
                    raise ValueError
        except (ValueError, KeyError):
            await query.message.reply_text("Nominal top up minimal Rp3.000.")
            return
        await _create_qris_payment(query.message, context, user, purpose, plan_days, amount_idr)
        return
    if len(parts) == 3 and parts[1] == "cancel":
        await _cancel_qris_payment(query, user, parts[2])
        return
    if len(parts) == 3 and parts[1] == "check":
        order_id = parts[2]
        payment = admin_panel.get_payment(order_id)
        if not payment or payment["user_id"] != user.id:
            await query.message.reply_text("Transaksi tidak ditemukan.")
            return
        paid, message = await _check_qris_payment(context.bot, order_id, user.id)
        if paid:
            await _delete_qris_message(context.bot, user.id, query.message.message_id)
        await _send_qris_status(context.bot, user.id, order_id, message)

async def _announce_premium_payment_once(bot: Any, payment: dict[str, Any]) -> None:
    if not NUMBER_PURCHASE_CHANNEL_ID or payment.get("purpose") != "premium":
        return
    order_id = str(payment["order_id"])
    if not admin_panel.claim_payment_channel_announcement(order_id):
        return
    try:
        paid_at = payment.get("paid_at") or payment["created_at"]
        paid_time = datetime.fromisoformat(paid_at).astimezone(WIB)
        text = (
            "🎉 <b>PEMBELIAN PREMIUM BERHASIL:</b>\n"
            "————————————–––––——––•\n"
            f"• ID Telegram: <a href=\"tg://user?id={int(payment['user_id'])}\">{int(payment['user_id'])}</a>\n"
            f"• Paket: Premium {int(payment['plan_days'])} hari\n"
            f"• Nominal: Rp{int(payment['amount_idr']):,}\n"
            f"• Waktu: {paid_time.strftime('%d/%m/%Y, %H.%M')} WIB"
        )
        await bot.send_message(chat_id=NUMBER_PURCHASE_CHANNEL_ID, text=text, parse_mode=ParseMode.HTML)
    except Exception:
        admin_panel.release_payment_channel_announcement(order_id)
        log.exception("Gagal mengirim pengumuman pembelian Premium ke channel")

async def _announce_admin_premium_grant(bot: Any, user_id: int, days: int) -> None:
    if not NUMBER_PURCHASE_CHANNEL_ID:
        return
    granted_at = datetime.now(WIB)
    text = (
        "🎉 <b>PREMIUM DIBERIKAN ADMIN:</b>\n"
        "————————————–––––——––•\n"
        f"• ID Telegram: <a href=\"tg://user?id={int(user_id)}\">{int(user_id)}</a>\n"
        f"• Premium: {days} hari\n"
        f"• Waktu: {granted_at.strftime('%d/%m/%Y, %H.%M')} WIB"
    )
    try:
        await bot.send_message(chat_id=NUMBER_PURCHASE_CHANNEL_ID, text=text, parse_mode=ParseMode.HTML)
    except Exception:
        log.exception("Gagal mengirim pengumuman Premium dari admin ke channel")

async def _announce_redeem_success(bot: Any, user_id: int, days: int, used: int, maximum: int) -> None:
    if not NUMBER_PURCHASE_CHANNEL_ID:
        return
    purchased_at = datetime.now(WIB)
    text = (
        "🎉 <b>PREMIUM DARI REDEEM BERHASIL:</b>\n"
        "————————————–––––——––•\n"
        f"• ID Telegram: <a href=\"tg://user?id={int(user_id)}\">{int(user_id)}</a>\n"
        f"• Premium: {days} hari\n"
        f"• Pemakaian kode: {used}/{maximum}\n"
        f"• Waktu: {purchased_at.strftime('%d/%m/%Y, %H.%M')} WIB"
    )
    try:
        await bot.send_message(chat_id=NUMBER_PURCHASE_CHANNEL_ID, text=text, parse_mode=ParseMode.HTML)
    except Exception:
        log.exception("Gagal mengirim pengumuman redeem Premium ke channel")
