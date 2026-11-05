"""invite feature handlers and helpers."""
from __future__ import annotations

_RUNTIME_NAMES = ("_reject_blocked_user", "_tab_keyboard", "admin_panel", "re")

def configure(runtime_globals):
    """Bind application services and configuration from the bot entry point."""
    missing = [name for name in _RUNTIME_NAMES if name not in runtime_globals]
    if missing:
        raise RuntimeError(f"invite.py missing runtime dependencies: {', '.join(missing)}")
    globals().update({name: runtime_globals[name] for name in _RUNTIME_NAMES})

def capture_referral_start(message_text: str, context: Any) -> None:
    """Keep a referral payload while the membership gate is being completed."""
    match = re.match(r"^/start(?:@\w+)?\s+(ref_\d+)(?:\s|$)", message_text or "")
    if match:
        context.user_data["pending_referral"] = match.group(1)

def process_start_referral(context: Any, user: Any) -> bool:
    """Apply a valid referral payload once when a user starts the bot."""
    payload = context.args[0] if context.args else context.user_data.pop("pending_referral", None)
    context.user_data.pop("pending_referral", None)
    match = re.fullmatch(r"ref_(\d+)", payload or "")
    return admin_panel.register_referral(int(match.group(1)), user.id) if match else False

async def _invite_text(bot: Any, user_id: int) -> str:
    bot_info = await bot.get_me()
    if not bot_info.username:
        return "Tautan undangan belum tersedia. Hubungi admin bot."
    summary = admin_panel.get_referral_summary(user_id)
    link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"
    return (
        "👥 Undang teman ke LunaFile\n\n"
        f"Tautan undangan Anda:\n{link}\n\n"
        "Teman baru yang mulai memakai bot melalui tautan ini mendapat saldo nomor Rp200. "
        "Anda mendapat komisi saldo 1% dari setiap pembelian nomor teman yang berhasil.\n\n"
        f"Teman diundang: {summary['invited']}\n"
        f"Bonus saldo untuk teman: Rp{summary['signup_rewards']:,}\n"
        f"Komisi pembelian nomor: Rp{summary['commission']:,}"
    )

async def invite_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _reject_blocked_user(update):
        return
    user = update.effective_user
    if not user:
        return
    admin_panel.record_event(user, "message")
    await update.effective_message.reply_text(await _invite_text(context.bot, user.id),
                                              reply_markup=_tab_keyboard())
