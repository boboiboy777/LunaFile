"""Callback navigation handlers for the Telegram bot."""
from __future__ import annotations

from typing import Any, Callable

async def handle_navigation(update: Any, context: Any,
                           actions: dict[str, Callable[..., Any]]) -> None:
    """Route ``nav:`` callbacks using page actions supplied by the bot module."""
    query = update.callback_query
    if not query:
        return
    if await actions["reject_blocked_user"](update):
        await query.answer("Akses bot sedang dibatasi.", show_alert=True)
        return

    action = (query.data or "").split(":", 1)[1]
    if action == "home":
        await query.answer()
        actions["record_event"](update.effective_user, "start")
        await actions["send_home"](query.message, update.effective_user)
    elif action == "hide":
        await query.edit_message_reply_markup(reply_markup=None)
        await query.answer("Menu disembunyikan. Ketik /menu untuk menampilkannya lagi.")
    elif action == "dashboard":
        await query.answer()
        text = actions["user_dashboard_text"](update.effective_user)
        await query.message.reply_text(text, reply_markup=actions["tab_keyboard"]())
    elif action == "premium":
        await query.answer()
        await actions["plans_command"](update, context)
    elif action == "help":
        await query.answer()
        await actions["help_command"](update, context)
    elif action == "invite":
        await query.answer()
        text = await actions["invite_text"](context.bot, update.effective_user.id)
        await query.message.reply_text(text, reply_markup=actions["tab_keyboard"]())
    elif action == "file":
        await query.answer()
        await query.message.reply_text(
            "Silakan lampirkan file sebagai dokumen. Setelah terkirim, saya akan membaca dan merangkumnya.",
            reply_markup=actions["tab_keyboard"](),
        )
    elif action == "video":
        await query.answer()
        await query.message.reply_text(
            "Kirim tautan YouTube, Reels/postingan/Story Instagram, TikTok, atau Facebook. Gunakan /download <tautan> juga bisa.",
            reply_markup=actions["tab_keyboard"](),
        )
    elif action == "airdrop":
        await query.answer()
        await actions["show_airdrop_page"](query.message)
