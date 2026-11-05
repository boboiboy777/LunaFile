"""Receive and verify TELEKOS.ID order webhooks."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import html
import json
import logging
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import admin_panel

HOST = os.getenv("TELEKOS_WEBHOOK_HOST", "127.0.0.1")
PORT = int(os.getenv("TELEKOS_WEBHOOK_PORT", "8788"))
PATH = "/webhooks/telekos"
MAX_BODY_BYTES = 1024 * 1024
SIGNATURE_MAX_AGE_SECONDS = 300


def _verify_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    timestamp_match = re.search(r"(?:^|,)\s*t=(\d+)(?:,|$)", signature)
    digest_match = re.search(r"(?:^|,)\s*v1=([0-9a-fA-F]{64})(?:,|$)", signature)
    if not timestamp_match or not digest_match:
        return False
    timestamp = int(timestamp_match.group(1))
    if abs(time.time() - timestamp) > SIGNATURE_MAX_AGE_SECONDS:
        return False
    signed_content = timestamp_match.group(1).encode("ascii") + b"." + raw_body
    expected = hmac.new(secret.encode("utf-8"), signed_content, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, digest_match.group(1).lower())


def _send_telegram(bot: Any, loop: asyncio.AbstractEventLoop, user_id: int, message: str) -> None:
    future = asyncio.run_coroutine_threadsafe(
        bot.send_message(chat_id=user_id, text=message, parse_mode="HTML"), loop)
    future.result(timeout=20)


def _handle_event(event: dict[str, Any], delivery_id: str, bot: Any,
                  loop: asyncio.AbstractEventLoop) -> None:
    event_type = event.get("type")
    data = event.get("data")
    order = data.get("order") if isinstance(data, dict) else None
    if not isinstance(order, dict) or not order.get("id"):
        raise ValueError("Webhook order payload is invalid")
    order_id = str(order["id"])
    user_id = admin_panel.get_number_order_owner(order_id)
    # Ignore valid webhooks for orders created outside this bot.
    if user_id is None:
        return
    if not admin_panel.claim_telekos_webhook_delivery(delivery_id):
        return
    try:
        if event_type == "order.otp":
            admin_panel.update_number_order_status(order_id, str(order.get("status", "received")))
            otps = order.get("otps", [])
            otp = otps[-1] if isinstance(otps, list) and otps else {}
            if isinstance(otp, dict) and otp.get("code"):
                app = order.get("app") if isinstance(order.get("app"), dict) else {}
                country = order.get("country") if isinstance(order.get("country"), dict) else {}
                lines = ["📩 <b>Kode OTP Telekos masuk</b>"]
                if order.get("number"):
                    lines.append(f"Nomor: <code>{html.escape(str(order['number']))}</code>")
                if app.get("name"):
                    lines.append(f"Layanan: {html.escape(str(app['name']))}")
                if country.get("name"):
                    lines.append(f"Negara: {html.escape(str(country['name']))}")
                lines.append(f"Kode OTP: <code>{html.escape(str(otp['code']))}</code>")
                if otp.get("message"):
                    lines.append(f"Pesan: {html.escape(str(otp['message']))}")
                _send_telegram(bot, loop, user_id, "\n".join(lines))
        elif event_type == "order.cancelled":
            admin_panel.refund_number_order(order_id, user_id)
            _send_telegram(bot, loop, user_id,
                           f"Nomor Telekos untuk pesanan <code>{html.escape(order_id)}</code> dibatalkan. Saldo bot sudah dikembalikan.")
        elif event_type == "order.expired":
            admin_panel.refund_number_order(order_id, user_id)
            _send_telegram(bot, loop, user_id,
                           f"Pesanan Telekos <code>{html.escape(order_id)}</code> kedaluwarsa. Saldo bot sudah dikembalikan.")
        elif event_type == "order.completed":
            admin_panel.update_number_order_status(order_id, str(order.get("status", "completed")))
        else:
            # Acknowledge valid future event types without affecting orders.
            pass
    except Exception:
        admin_panel.release_telekos_webhook_delivery(delivery_id)
        raise


def make_handler(bot: Any, loop: asyncio.AbstractEventLoop) -> type[BaseHTTPRequestHandler]:
    class TelekosWebhookHandler(BaseHTTPRequestHandler):
        server_version = "TelekosWebhook/1.0"

        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def _reply(self, status: int, message: bytes = b"") -> None:
            self.send_response(status)
            self.send_header("Content-Length", str(len(message)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if message:
                self.wfile.write(message)

        def do_POST(self) -> None:
            if self.path != PATH:
                self._reply(404)
                return
            secret = os.getenv("TELEKOS_WEBHOOK_SECRET", "")
            if not secret:
                logging.getLogger("file_reader_bot").error("Webhook Telekos nonaktif: secret belum dikonfigurasi")
                self._reply(503)
                return
            try:
                content_length = int(self.headers.get("Content-Length", "-1"))
            except ValueError:
                self._reply(400)
                return
            if content_length < 0 or content_length > MAX_BODY_BYTES:
                self._reply(413)
                return
            raw_body = self.rfile.read(content_length)
            signature = self.headers.get("X-Telekos-Signature", "")
            if not _verify_signature(raw_body, signature, secret):
                self._reply(401)
                return
            delivery_id = self.headers.get("X-Telekos-Delivery", "").strip()
            if not delivery_id or len(delivery_id) > 200:
                self._reply(400)
                return
            try:
                event = json.loads(raw_body)
                if not isinstance(event, dict):
                    raise ValueError("Webhook body is not an object")
                _handle_event(event, delivery_id, bot, loop)
            except Exception:
                logging.getLogger("file_reader_bot").exception("Webhook Telekos gagal diproses")
                self._reply(500)
                return
            self._reply(200)

    return TelekosWebhookHandler


def start_webhook_server(bot: Any, loop: asyncio.AbstractEventLoop) -> ThreadingHTTPServer | None:
    if not os.getenv("TELEKOS_WEBHOOK_SECRET"):
        logging.getLogger("file_reader_bot").warning("Webhook Telekos nonaktif: TELEKOS_WEBHOOK_SECRET belum diatur")
        return None
    server = ThreadingHTTPServer((HOST, PORT), make_handler(bot, loop))
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, name="telekos-webhook", daemon=True).start()
    logging.getLogger("file_reader_bot").info("Webhook Telekos listening pada %s:%s%s", HOST, PORT, PATH)
    return server
