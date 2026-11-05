"""num feature handlers and helpers."""
from __future__ import annotations

import uuid

_RUNTIME_NAMES = (
    "InlineKeyboardButton", "InlineKeyboardMarkup", "NUMBER_MARKUP_IDR",
    "NUMBER_PURCHASE_CHANNEL_ID", "NUMBER_TOPUP_AMOUNTS", "NUMBER_TOPUP_MIN_IDR",
    "ParseMode", "TELEKOS_API_BASE", "TELEKOS_API_KEY", "WIB",
    "_NUMBER_PURCHASE_LOCK", "_is_admin", "_parse_idr_amount",
    "_reject_blocked_user", "_send_home", "admin_panel", "asyncio", "buy",
    "datetime", "html_escape", "httpx", "log",
)

def configure(runtime_globals):
    """Bind application services and configuration from the bot entry point."""
    missing = [name for name in _RUNTIME_NAMES if name not in runtime_globals]
    if missing:
        raise RuntimeError(f"num.py missing runtime dependencies: {', '.join(missing)}")
    globals().update({name: runtime_globals[name] for name in _RUNTIME_NAMES})

async def handle_pending_text(update: Any, context: Any) -> bool:
    """Consume text replies for country search and custom wallet top ups."""
    if context.user_data.get("number_search_country_waiting"):
        term = (update.message.text or "").strip().casefold()
        if not term:
            await update.message.reply_text("Kata pencarian negara tidak boleh kosong. Kirim nama negara atau kode ISO.")
            return True
        context.user_data.pop("number_search_country_waiting", None)
        countries = context.user_data.get("number_countries", {})
        all_tokens = context.user_data.get("number_country_all_tokens", list(countries))
        matches = [token for token in all_tokens if term in str(countries[token].get("name", "")).casefold()
                   or term in str(countries[token].get("iso", "")).casefold()]
        context.user_data["number_country_tokens"] = matches
        search_message = "Hasil pencarian negara" if matches else f"Negara yang cocok dengan ‘{term}’ tidak ditemukan."
        message_id = context.user_data.pop("number_search_message_id", None)
        chat_id = context.user_data.pop("number_search_chat_id", None)
        if message_id and chat_id:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=message_id, text=search_message,
                reply_markup=_num_nav(_number_page_rows(context.user_data, "countries")))
        else:
            await update.message.reply_text(search_message,
                reply_markup=_num_nav(_number_page_rows(context.user_data, "countries")))
        return True
    if context.user_data.get("number_topup_waiting_amount"):
        amount_idr = _parse_idr_amount(update.message.text or "")
        if amount_idr is None:
            await update.message.reply_text("Nominal tidak valid. Kirim angka, misalnya 900000 atau 900.000.")
            return True
        if amount_idr < NUMBER_TOPUP_MIN_IDR:
            await update.message.reply_text("Minimal top up Saldo adalah Rp3.000. Coba lagi atau gunakan /batal.")
            return True
        context.user_data.pop("number_topup_waiting_amount", None)
        await buy._create_qris_payment(update.effective_message, context, update.effective_user,
                                       "numbers_topup", 0, amount_idr)
        return True
    return False

async def _telekos_request(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    if not TELEKOS_API_KEY:
        raise RuntimeError("TELEKOS_API_KEY belum diatur.")
    headers = {"Authorization": f"Bearer {TELEKOS_API_KEY}", "Accept": "application/json"}
    if "headers" in kwargs:
        headers.update(kwargs.pop("headers"))
    async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=10)) as client:
        response = await client.request(method, f"{TELEKOS_API_BASE}{path}", headers=headers, **kwargs)
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.is_error or (isinstance(body, dict) and body.get("ok") is False):
        error = body.get("error", {}) if isinstance(body, dict) else {}
        code = error.get("code") if isinstance(error, dict) else error
        message = error.get("message", "") if isinstance(error, dict) else ""
        if not message and isinstance(body, dict):
            message = body.get("message", "")
        detail = ": ".join(str(value) for value in (code, message) if value)
        raise RuntimeError(f"Telekos: {detail or f'HTTP {response.status_code}'}")
    if not isinstance(body, dict):
        raise RuntimeError("Respons Telekos tidak valid.")
    data = body.get("data", body)
    if not isinstance(data, (dict, list)):
        raise RuntimeError("Respons Telekos tidak valid.")
    return {"data": data, "meta": body.get("meta", {})}

def _number_list(result: dict[str, Any]) -> list[dict[str, Any]]:
    data = result.get("data", [])
    return data if isinstance(data, list) else []

def _number_object(result: dict[str, Any]) -> dict[str, Any]:
    data = result.get("data", {})
    return data if isinstance(data, dict) else {}

def _format_number_idr(amount: int) -> str:
    return f"{int(amount):,}".replace(",", ".")

def _number_profit_idr(provider_price: int) -> int:
    """Return the configured profit tier for a Telekos base price."""
    price = max(0, int(provider_price))
    if price <= 10_000:
        return NUMBER_MARKUP_IDR
    if price <= 20_000:
        return 2_000
    if price < 30_000:
        return 3_000
    if price < 50_000:
        return 4_500
    if price <= 100_000:
        return 6_000
    if price <= 200_000:
        return 10_000
    # Keep the highest configured tier for prices above Rp400.000 as well.
    return 25_000

def _number_customer_price(provider_price: int) -> int:
    return int(provider_price) + _number_profit_idr(provider_price)

def _number_page_rows(user_data: dict[str, Any], group: str, page: int = 0) -> list[list[InlineKeyboardButton]]:
    configs = {
        "servers": ("number_servers", "number_server_tokens", "server"),
        "apps": ("number_apps", "number_app_tokens", "app"),
        "telegram": ("number_apps", "number_telegram_tokens", "app"),
        "countries": ("number_countries", "number_country_tokens", "country"),
        "services": ("number_services", "number_service_tokens", "service"),
    }
    map_key, token_key, action = configs[group]
    objects = user_data.get(map_key, {})
    tokens = user_data.get(token_key, [])
    page_size = 10
    page_count = max(1, (len(tokens) + page_size - 1) // page_size)
    page = min(max(0, page), page_count - 1)
    rows: list[list[InlineKeyboardButton]] = []
    buttons = []
    for token in tokens[page * page_size:(page + 1) * page_size]:
        item = objects[token]
        if group == "countries":
            label = f"{item.get('flag', '')} {item.get('name', 'Negara')}"
        elif group == "services":
            price = _number_customer_price(int(item.get("price", 0)))
            label = f"Rp {_format_number_idr(price)} • {item.get('stock', 0)} stok"
        elif group == "telegram":
            server_name = item.get("server", {}).get("name", item.get("server", {}).get("id", "Server"))
            app_name = item.get("name", item.get("id", "Telegram"))
            label = f"{server_name} · {app_name}"
        elif group == "apps":
            label = str(item.get('name', item.get('id', 'Aplikasi')))
        else:
            label = str(item.get("name", item.get("id", "Pilihan")))
        buttons.append(InlineKeyboardButton(str(label), callback_data=f"numbers:{action}:{token}"))
    for i in range(0, len(buttons), 2):
        rows.append(buttons[i:i + 2])
    if group == "countries":
        rows.append([InlineKeyboardButton("🔎 Cari negara", callback_data="numbers:search-country"),
                     InlineKeyboardButton("📋 Semua negara", callback_data="numbers:countries-all")])
    if page_count > 1:
        page_buttons = []
        first_page = max(0, min(page - 2, page_count - 5))
        last_page = min(page_count, first_page + 5)
        for page_index in range(first_page, last_page):
            label = f"• {page_index + 1} •" if page_index == page else f"Halaman {page_index + 1}"
            page_buttons.append(InlineKeyboardButton(label, callback_data=f"numbers:page:{group}:{page_index}"))
        rows.append(page_buttons)
    return rows

async def _show_number_categories(target: Any, user_id: int, *, edit: bool = False) -> None:
    message = f"📱 Pilih jenis nomor. Saldo Anda: Rp{admin_panel.number_wallet_balance(user_id):,}"
    rows = [[InlineKeyboardButton("📲 Nomor Telegram", callback_data="numbers:category:telegram")],
            [InlineKeyboardButton("🌐 Layanan Lain", callback_data="numbers:category:other")]]
    if edit:
        await _edit_number_message(target, message, reply_markup=_num_nav(rows))
    else:
        await target.reply_text(message, reply_markup=_num_nav(rows))

async def _show_number_servers(target: Any, user_data: dict[str, Any], user_id: int, *, edit: bool = False) -> None:
    result = await _telekos_request("GET", "/servers")
    servers = [item for item in _number_list(result)
               if item.get("available") and not item.get("maintenance")]
    server_map: dict[str, dict[str, Any]] = {}
    for server in servers:
        server_map[uuid.uuid4().hex[:8]] = server
    user_data["number_servers"] = server_map
    user_data["number_server_tokens"] = list(server_map)
    rows = _number_page_rows(user_data, "servers") if server_map else []
    message = f"🌐 Pilih server untuk layanan lain. Saldo Anda: Rp{admin_panel.number_wallet_balance(user_id):,}"
    user_data.setdefault("number_page_titles", {})["servers"] = message
    if not rows:
        message = "Belum ada server Telekos yang tersedia. Coba lagi nanti."
    if edit:
        await _edit_number_message(target, message, reply_markup=_num_nav(rows))
    else:
        await target.reply_text(message, reply_markup=_num_nav(rows))

async def _show_telegram_numbers(target: Any, user_data: dict[str, Any], user_id: int) -> None:
    result = await _telekos_request("GET", "/servers")
    servers = [item for item in _number_list(result)
               if item.get("available") and not item.get("maintenance")]
    semaphore = asyncio.Semaphore(4)

    async def server_telegram_apps(server: dict[str, Any]) -> list[dict[str, Any]]:
        async with semaphore:
            try:
                response = await _telekos_request("GET", "/apps", params={"server": str(server["id"])})
            except (RuntimeError, httpx.HTTPError) as exc:
                log.warning("Gagal memuat aplikasi Telegram dari server Telekos: %s", exc)
                return []
        apps = [app for app in _number_list(response)
                if "telegram" in f"{app.get('name', '')} {app.get('id', '')}".lower()]
        return [{**app, "server": server} for app in apps]

    app_groups = await asyncio.gather(*(server_telegram_apps(server) for server in servers))
    apps = [app for group in app_groups for app in group]
    app_map = {uuid.uuid4().hex[:8]: app for app in apps}
    user_data["number_apps"] = app_map
    user_data["number_telegram_tokens"] = list(app_map)
    rows = _number_page_rows(user_data, "telegram") if app_map else []
    message = "📲 Pilih server dengan nomor Telegram tersedia:"
    if not rows:
        message = "Layanan nomor Telegram belum tersedia di server Telekos saat ini."
    user_data.setdefault("number_page_titles", {})["telegram"] = message
    await _edit_number_message(target, message, reply_markup=_num_nav(rows))

def _mask_phone_number(number: str) -> str:
    prefix = "+" if number.startswith("+") else ""
    digits = "".join(char for char in number if char.isdigit())
    if len(digits) <= 6:
        return prefix + "*" * max(0, len(digits) - 2) + digits[-2:]
    return prefix + digits[:4] + "*" * (len(digits) - 6) + digits[-2:]

async def _announce_number_purchase(bot: Any, user_id: int, service: dict[str, Any], order: dict[str, Any]) -> None:
    if not NUMBER_PURCHASE_CHANNEL_ID:
        return
    country = service["country"]
    app = country.get("app", {})
    server = country.get("server", {})
    country_name = str(country.get("name", "Negara"))
    flag = str(country.get("flag", "")).strip()
    if flag:
        country_name += f" {flag}"
    purchased_at = datetime.now(WIB)
    text = (
        "🎉 <b>PEMBELIAN NOMOR BERHASIL:</b>\n"
        "————————————–––––——––•\n"
        f"• Layanan Aplikasi: {html_escape(str(app.get('name', app.get('id', 'Aplikasi'))))}\n"
        f"• Negara: {html_escape(country_name)}\n"
        f"• Server: {html_escape(str(server.get('name', server.get('id', 'Server'))))}\n"
        f"• Nomor: <code>{html_escape(_mask_phone_number(str(order['number'])))}</code>\n"
        f"• Waktu: {purchased_at.strftime('%d/%m/%Y, %H.%M')}"
    )
    me = await bot.get_me()
    rows = ([[InlineKeyboardButton("🛒 Beli Nomor", url=f"https://t.me/{me.username}?start=beli_nomor")]]
            if me.username else [])
    await bot.send_message(chat_id=NUMBER_PURCHASE_CHANNEL_ID, text=text, parse_mode=ParseMode.HTML,
                           reply_markup=InlineKeyboardMarkup(rows) if rows else None)

def _num_nav(rows: list[list[InlineKeyboardButton]] | None = None) -> InlineKeyboardMarkup:
    buttons = list(rows or [])
    buttons.append([InlineKeyboardButton("⬅️ Kembali", callback_data="numbers:back")])
    buttons.append([InlineKeyboardButton("💰 Saldo", callback_data="wallet:home")])
    return InlineKeyboardMarkup(buttons)

def _wallet_topup_markup() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(f"Rp{amount:,}", callback_data=f"plan:topup:{amount}")]
            for amount in NUMBER_TOPUP_AMOUNTS]
    rows.append([InlineKeyboardButton("✍️ Input nominal", callback_data="wallet:custom")])
    rows.append([InlineKeyboardButton("⭐ Beli Premium", callback_data="nav:premium")])
    return _num_nav(rows)

async def wallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _reject_blocked_user(update):
        return
    context.user_data["number_nav_stack"] = []
    await update.effective_message.reply_text(
        f"💰 Saldo Anda: Rp{admin_panel.number_wallet_balance(update.effective_user.id):,}\n"
        "Saldo dapat digunakan untuk membeli nomor atau Premium.",
        reply_markup=_wallet_topup_markup())

async def numbers_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _reject_blocked_user(update):
        return
    if not admin_panel.is_number_purchase_visible() and not _is_admin(update):
        await update.effective_message.reply_text("Pembelian nomor sedang disembunyikan oleh admin.")
        return
    if not TELEKOS_API_KEY:
        await update.effective_message.reply_text("Fitur nomor belum dikonfigurasi. Hubungi admin.")
        return
    context.user_data["number_nav_stack"] = []
    try:
        await _show_number_categories(update.effective_message, update.effective_user.id)
    except RuntimeError as exc:
        log.warning("Gagal mengambil negara Telekos: %s", exc)
        await update.effective_message.reply_text(str(exc))
    except (httpx.HTTPError, ValueError, TypeError):
        log.exception("Gagal mengambil negara Telekos")
        await update.effective_message.reply_text("Katalog negara Telekos belum dapat dimuat. Coba lagi nanti.")

async def _edit_number_error(query: Any, message: str) -> None:
    await _edit_number_message(query, message, reply_markup=_num_nav())

async def _edit_number_message(query: Any, text: str, **kwargs: Any) -> None:
    """Edit either a text message or a photo caption used by the home screen."""
    message = getattr(query, "message", None)
    if message and (getattr(message, "photo", None) or getattr(message, "caption", None) is not None):
        await query.edit_message_caption(caption=text, **kwargs)
    else:
        await query.edit_message_text(text, **kwargs)

def _push_number_page(user_data: dict[str, Any], message: Any) -> None:
    if not message:
        return
    caption = getattr(message, "caption", None)
    text = caption if caption is not None else getattr(message, "text", None)
    if text is None:
        return
    stack = user_data.setdefault("number_nav_stack", [])
    stack.append({
        "text": text,
        "is_caption": caption is not None,
        "entities": list(getattr(message, "caption_entities", []) if caption is not None
                          else getattr(message, "entities", [])),
        "reply_markup": getattr(message, "reply_markup", None),
    })
    del stack[:-20]

async def numbers_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query, user = update.callback_query, update.effective_user
    if not query or not user:
        return
    if await _reject_blocked_user(update):
        await query.answer("Akses bot sedang dibatasi.", show_alert=True)
        return
    if not admin_panel.is_number_purchase_visible() and not _is_admin(update):
        await query.answer("Pembelian nomor sedang disembunyikan oleh admin.", show_alert=True)
        return
    await query.answer()
    parts = (query.data or "").split(":")
    if parts == ["numbers", "back"]:
        context.user_data.pop("number_topup_waiting_amount", None)
        stack = context.user_data.setdefault("number_nav_stack", [])
        if stack:
            previous = stack.pop()
            options: dict[str, Any] = {"reply_markup": previous["reply_markup"]}
            entities = previous.get("entities")
            if entities:
                options["caption_entities" if previous["is_caption"] else "entities"] = entities
            if previous["is_caption"]:
                await query.edit_message_caption(caption=previous["text"], **options)
            else:
                await query.edit_message_text(previous["text"], **options)
        else:
            await _send_home(query.message, user)
        return
    if len(parts) == 2 and parts[1] == "start":
        context.user_data["number_nav_stack"] = []
    if len(parts) < 2 or parts[1] not in {"page", "noop"}:
        _push_number_page(context.user_data, query.message)
    if not TELEKOS_API_KEY:
        await _edit_number_message(query,
            "API Telekos belum dikonfigurasi di server. Tambahkan TELEKOS_API_KEY ke file .env, lalu mulai ulang bot.",
            reply_markup=_num_nav())
        return
    try:
        if len(parts) == 2 and parts[1] == "start":
            await _show_number_categories(query, user.id, edit=True)
            return
        if len(parts) == 3 and parts[1] == "category":
            if parts[2] == "telegram":
                await _show_telegram_numbers(query, context.user_data, user.id)
            else:
                await _show_number_servers(query, context.user_data, user.id, edit=True)
            return
        if parts == ["numbers", "search-country"]:
            context.user_data["number_search_country_waiting"] = True
            context.user_data["number_search_message_id"] = query.message.message_id
            context.user_data["number_search_chat_id"] = query.message.chat_id
            await _edit_number_message(query, "🔎 Kirim nama negara atau kode ISO yang ingin dicari:",
                                       reply_markup=_num_nav())
            return
        if parts == ["numbers", "countries-all"]:
            context.user_data["number_country_tokens"] = list(
                context.user_data.get("number_country_all_tokens", []))
            title = context.user_data.get("number_page_titles", {}).get("countries", "Pilih negara:")
            await _edit_number_message(query, title,
                                       reply_markup=_num_nav(_number_page_rows(context.user_data, "countries")))
            return
        if len(parts) == 4 and parts[1] == "page":
            group, page = parts[2], max(0, int(parts[3]))
            title = getattr(query.message, "caption", None) or getattr(query.message, "text", "Pilih layanan:")
            await _edit_number_message(query, title,
                                       reply_markup=_num_nav(_number_page_rows(context.user_data, group, page)))
            return
        if len(parts) == 3 and parts[1] == "server":
            server = context.user_data.get("number_servers", {}).get(parts[2])
            if not server:
                await _edit_number_error(query, "Pilihan server kedaluwarsa. Buka kembali /nomor.")
                return
            server_id = str(server["id"])
            result = await _telekos_request("GET", "/apps", params={"server": server_id})
            app_map: dict[str, dict[str, Any]] = {}
            apps = _number_list(result)
            apps.sort(key=lambda app: 0 if "whatsapp" in
                      f"{app.get('name', '')} {app.get('id', '')}".casefold() else 1)
            for app in apps:
                app_map[uuid.uuid4().hex[:8]] = {**app, "server": server}
            context.user_data["number_apps"] = app_map
            context.user_data["number_app_tokens"] = list(app_map)
            rows = _number_page_rows(context.user_data, "apps") if app_map else []
            message = f"Pilih aplikasi di {server.get('name', server_id)}:"
            if not rows:
                message = "Belum ada aplikasi pada server ini."
            context.user_data.setdefault("number_page_titles", {})["apps"] = message
            await _edit_number_message(query, message, reply_markup=_num_nav(rows))
            return
        if len(parts) == 3 and parts[1] == "app":
            app = context.user_data.get("number_apps", {}).get(parts[2])
            if not app:
                await _edit_number_error(query, "Pilihan aplikasi kedaluwarsa. Buka kembali /nomor.")
                return
            server_id, app_id = str(app["server"]["id"]), str(app["id"])
            result = await _telekos_request("GET", "/countries", params={"server": server_id, "app": app_id})
            country_map: dict[str, dict[str, Any]] = {}
            countries = [country for country in _number_list(result)
                         if int(country.get("stock", 0) or 0) > 0]
            countries.sort(key=lambda item: (
                0 if str(item.get("iso", "")).upper() == "ID" or
                     str(item.get("name", "")).casefold() == "indonesia" else 1,
                str(item.get("name", "")).casefold()))
            for country in countries:
                country_map[uuid.uuid4().hex[:8]] = {**country, "server": app["server"], "app": app}
            context.user_data["number_countries"] = country_map
            context.user_data["number_country_all_tokens"] = list(country_map)
            context.user_data["number_country_tokens"] = list(country_map)
            rows = _number_page_rows(context.user_data, "countries") if country_map else []
            message = f"Pilih negara untuk {app.get('name', app_id)}:"
            if not rows:
                message = f"Belum ada negara dengan stok untuk {app.get('name', app_id)}."
            context.user_data.setdefault("number_page_titles", {})["countries"] = message
            await _edit_number_message(query, message, reply_markup=_num_nav(rows))
            return
        if len(parts) == 3 and parts[1] == "cpage":
            page = max(0, int(parts[2]))
            tokens = context.user_data.get("number_country_tokens", [])
            start = page * 8
            rows = []
            countries = context.user_data.get("number_countries", {})
            for token in tokens[start:start + 8]:
                country = countries[token]
                rows.append([InlineKeyboardButton(
                    f"{country.get('name', 'Negara')} ({str(country.get('iso', '')).upper()})",
                    callback_data=f"numbers:country:{token}")])
            nav = []
            if page > 0:
                nav.append(InlineKeyboardButton("‹ Sebelumnya", callback_data=f"numbers:cpage:{page-1}"))
            if start + 8 < len(tokens):
                nav.append(InlineKeyboardButton("Berikutnya ›", callback_data=f"numbers:cpage:{page+1}"))
            if nav:
                rows.append(nav)
            await _edit_number_message(query, "📱 Pilih negara untuk OTP:", reply_markup=_num_nav(rows))
            return
        if len(parts) == 3 and parts[1] == "country":
            country = context.user_data.get("number_countries", {}).get(parts[2])
            if not country:
                await _edit_number_error(query, "Pilihan negara kedaluwarsa. Buka kembali /nomor.")
                return
            country_id = str(country.get("id"))
            app = country["app"]
            server_id, app_id = str(country["server"]["id"]), str(app["id"])
            result = await _telekos_request("GET", "/prices", params={
                "server": server_id, "app": app_id, "country": country_id, "refresh": "1"})
            offers = _number_list(result)
            service_map: dict[str, dict[str, Any]] = {}
            for offer in offers:
                if int(offer.get("stock", 0) or 0) <= 0:
                    continue
                service_map[uuid.uuid4().hex[:8]] = {**offer, "country": country}
            context.user_data["number_services"] = service_map
            context.user_data["number_service_tokens"] = list(service_map)
            rows = _number_page_rows(context.user_data, "services") if service_map else []
            message = f"Harga untuk {app.get('name', app_id)} di {country.get('name', country_id)}:"
            if not rows:
                message = "Belum ada layanan dengan stok di negara tersebut."
            context.user_data.setdefault("number_page_titles", {})["services"] = message
            await _edit_number_message(query, message, reply_markup=_num_nav(rows))
            return
        if len(parts) == 3 and parts[1] == "service":
            service = context.user_data.get("number_services", {}).get(parts[2])
            if not service:
                await _edit_number_error(query, "Penawaran kedaluwarsa. Buka kembali /nomor untuk memuat harga terbaru.")
                return
            balance = admin_panel.number_wallet_balance(user.id)
            await _edit_number_message(query,
                f"Beli nomor {service['country']['app'].get('name', service['country']['app'].get('id'))} · {service['country'].get('name')}?\nHarga: Rp {_format_number_idr(_number_customer_price(int(service.get('price', 0))))} • {service.get('stock', 0)} stok\nSaldo Anda: Rp{balance:,}",
                reply_markup=_num_nav([[InlineKeyboardButton("✅ Beli nomor", callback_data=f"numbers:buy:{parts[2]}")]]))
            return
        if len(parts) == 3 and parts[1] == "buy":
            token = parts[2]
            service = context.user_data.get("number_services", {}).get(token)
            if not service:
                await _edit_number_error(query, "Penawaran kedaluwarsa. Buka kembali /nomor.")
                return
            created = context.user_data.setdefault("number_created", {})
            if token in created:
                order = created[token]
            else:
                async with _NUMBER_PURCHASE_LOCK:
                    balance = admin_panel.number_wallet_balance(user.id)
                    quoted_price = int(service.get("price", 0))
                    quoted_customer_price = _number_customer_price(quoted_price)
                    if balance < quoted_customer_price:
                        await _edit_number_message(query,
                            f"Saldo kurang. Harga nomor Rp{quoted_customer_price:,}; saldo Anda Rp{balance:,}.",
                            reply_markup=_num_nav([[InlineKeyboardButton("➕ Top up saldo", callback_data="wallet:home")]]))
                        return
                    idempotency_keys = context.user_data.setdefault("number_idempotency", {})
                    idempotency_key = idempotency_keys.setdefault(token, uuid.uuid4().hex)
                    context.user_data["number_pending"] = token
                    try:
                        result = await _telekos_request("POST", "/orders", json={"offer_id": service["offer_id"]},
                                                        headers={"Idempotency-Key": idempotency_key})
                    except (httpx.TimeoutException, httpx.NetworkError):
                        raise RuntimeError("Request order timeout. Coba lagi dari penawaran yang sama agar Telekos memakai kunci idempotensi yang sama.")
                    context.user_data.pop("number_pending", None)
                    payload = _number_object(result)
                    transaction_id = payload.get("id")
                    if not transaction_id or not payload.get("number"):
                        raise RuntimeError("Telekos tidak mengirim ID pesanan atau nomor.")
                    provider_price = int(payload.get("price", quoted_price))
                    order = {"id": str(transaction_id), "number": str(payload["number"]),
                             "price": _number_customer_price(provider_price), "status": payload.get("status", "waiting")}
                    if not admin_panel.debit_number_wallet(user.id, order["price"], order):
                        log.error("Telekos membuat order %s tetapi saldo internal gagal dipotong", transaction_id)
                        await _edit_number_message(query,
                            f"Telekos sudah membuat pesanan {transaction_id}, tetapi saldo bot gagal diperbarui. Hubungi admin.",
                            reply_markup=_num_nav())
                        return
                    created[token] = order
            order_id = order["id"]
            rows = [[InlineKeyboardButton("🔄 Periksa OTP", callback_data=f"numbers:check:{order_id}")]]
            if not order.get("channel_announced"):
                try:
                    await _announce_number_purchase(context.bot, user.id, service, order)
                    order["channel_announced"] = True
                except Exception:
                    log.exception("Gagal mengirim pengumuman pembelian nomor ke channel")
            await _edit_number_message(query,
                f"✅ Nomor berhasil dibeli\nLayanan: {service['country']['app'].get('name', service['country']['app'].get('id'))} · {service['country'].get('name')}\nNomor: <code>{html_escape(order['number'])}</code>\nHarga: Rp{order['price']:,}\nSaldo: Rp{admin_panel.number_wallet_balance(user.id):,}",
                parse_mode=ParseMode.HTML, reply_markup=_num_nav(rows))
            return
        if len(parts) == 3 and parts[1] in {"check", "cancel", "finish"}:
            order_id, action = parts[2], parts[1]
            if not admin_panel.get_number_order(order_id, user.id):
                await _edit_number_message(query, "Pesanan tidak ditemukan.", reply_markup=_num_nav())
                return
            if action == "cancel":
                result = await _telekos_request("POST", f"/orders/{order_id}/cancel")
                payload = _number_object(result)
                if payload.get("status") != "cancelled":
                    raise RuntimeError("Telekos belum mengonfirmasi pembatalan.")
                admin_panel.refund_number_order(order_id, user.id)
                await _edit_number_message(query,
                    f"Nomor dibatalkan. Saldo internal dikembalikan. Saldo sekarang Rp{admin_panel.number_wallet_balance(user.id):,}.",
                    reply_markup=_num_nav())
                return
            if action == "finish":
                result = await _telekos_request("POST", f"/orders/{order_id}/finish")
                payload = _number_object(result)
                admin_panel.update_number_order_status(order_id, str(payload.get("status", "completed")))
                await _edit_number_message(query, f"Pesanan {html_escape(order_id)} selesai.", reply_markup=_num_nav())
                return
            result = await _telekos_request("GET", f"/orders/{order_id}")
            payload = _number_object(result)
            state = str(payload.get("status", "unknown"))
            if state in {"cancelled", "expired"}:
                admin_panel.refund_number_order(order_id, user.id)
            else:
                admin_panel.update_number_order_status(order_id, state)
            lines = [f"Pesanan: {html_escape(order_id)}", f"Status: {html_escape(state)}"]
            if payload.get("number"):
                lines.append(f"Nomor: {html_escape(str(payload['number']))}")
            rows = []
            otps = payload.get("otps", [])
            otp = otps[-1] if isinstance(otps, list) and otps else {}
            if otp.get("code"):
                lines.append(f"Kode OTP: <code>{html_escape(str(otp['code']))}</code>")
                if otp.get("message"):
                    lines.append(f"Pesan: {html_escape(str(otp['message']))}")
                rows.append([InlineKeyboardButton("✅ Selesaikan pesanan", callback_data=f"numbers:finish:{order_id}")])
            elif state == "waiting":
                lines.append("OTP belum masuk. Periksa lagi beberapa saat.")
                rows.append([InlineKeyboardButton("🔄 Periksa OTP lagi", callback_data=f"numbers:check:{order_id}")])
                if payload.get("can_cancel"):
                    rows.append([InlineKeyboardButton("↩️ Batalkan dan refund", callback_data=f"numbers:cancel:{order_id}")])
            elif state in {"cancelled", "expired"}:
                lines.append(f"Saldo telah dikembalikan. Saldo sekarang Rp{admin_panel.number_wallet_balance(user.id):,}.")
            await _edit_number_message(query, "\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=_num_nav(rows))
            return
    except RuntimeError as exc:
        log.warning("Gagal memproses katalog/pesanan Telekos: %s", exc)
        error_message = str(exc)
        if "INSUFFICIENT_BALANCE" in error_message:
            error_message = "PRANK, Admin belum mengisi saldo, harap bersabar dan tunggu sebentar🙏."
        await query.message.reply_text(error_message, reply_markup=_num_nav())
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        log.exception("Gagal memproses katalog/pesanan Telekos")
        await query.message.reply_text("Koneksi ke Telekos belum berhasil. Coba lagi nanti.", reply_markup=_num_nav())

async def wallet_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query, user = update.callback_query, update.effective_user
    if not query or not user:
        return
    if await _reject_blocked_user(update):
        await query.answer("Akses bot sedang dibatasi.", show_alert=True)
        return
    await query.answer()
    _push_number_page(context.user_data, query.message)
    if query.data == "wallet:custom":
        context.user_data["number_topup_waiting_amount"] = True
        await _edit_number_message(
            query,
            "✍️ Kirim nominal top up yang diinginkan. Minimal Rp3.000.\n"
            "Contoh: 900000 atau 900.000\nGunakan /batal untuk membatalkan.",
            reply_markup=_num_nav())
        return
    await _edit_number_message(
        query,
        f"💰 Saldo Anda: Rp{admin_panel.number_wallet_balance(user.id):,}\n"
        "Saldo dapat digunakan untuk membeli nomor atau Premium.\n\nPilih nominal top up QRIS:",
        reply_markup=_wallet_topup_markup())
