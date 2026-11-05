"""Local, password-protected usage dashboard for the Telegram bot."""
from __future__ import annotations

import base64
import html
import hmac
import os
import sqlite3
import threading
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("ADMIN_DB_PATH", str(APP_DIR / "admin_stats.sqlite3")))
HOST = os.getenv("ADMIN_HOST", "127.0.0.1")
PORT = int(os.getenv("ADMIN_PORT", "8787"))


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT NOT NULL DEFAULT '', display_name TEXT NOT NULL DEFAULT '',
        first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, starts INTEGER NOT NULL DEFAULT 0,
        messages INTEGER NOT NULL DEFAULT 0, files INTEGER NOT NULL DEFAULT 0,
        files_success INTEGER NOT NULL DEFAULT 0, files_failed INTEGER NOT NULL DEFAULT 0,
        ai_calls INTEGER NOT NULL DEFAULT 0,
        ai_failed INTEGER NOT NULL DEFAULT 0, input_tokens INTEGER NOT NULL DEFAULT 0,
        output_tokens INTEGER NOT NULL DEFAULT 0, total_tokens INTEGER NOT NULL DEFAULT 0,
        reported_token_calls INTEGER NOT NULL DEFAULT 0)""")
    db.execute("""CREATE TABLE IF NOT EXISTS ai_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, created_at TEXT NOT NULL,
        model TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', input_tokens INTEGER NOT NULL DEFAULT 0,
        output_tokens INTEGER NOT NULL DEFAULT 0, total_tokens INTEGER NOT NULL DEFAULT 0,
        usage_reported INTEGER NOT NULL DEFAULT 0)""")
    # Migrate databases created before file outcome counters were added.
    columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
    if "files_success" not in columns:
        db.execute("ALTER TABLE users ADD COLUMN files_success INTEGER NOT NULL DEFAULT 0")
    if "files_failed" not in columns:
        db.execute("ALTER TABLE users ADD COLUMN files_failed INTEGER NOT NULL DEFAULT 0")
    db.execute("CREATE TABLE IF NOT EXISTS blocked_users (user_id INTEGER PRIMARY KEY, blocked_at TEXT NOT NULL)")
    db.execute("""CREATE TABLE IF NOT EXISTS airdrop_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        url TEXT NOT NULL,
        created_by INTEGER NOT NULL,
        created_at TEXT NOT NULL
    )""")
    db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('maintenance','0')")
    db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('number_purchase_visible','0')")
    db.execute("CREATE TABLE IF NOT EXISTS monthly_usage (user_id INTEGER NOT NULL, month TEXT NOT NULL, calls INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(user_id,month))")
    db.execute("CREATE TABLE IF NOT EXISTS daily_usage (user_id INTEGER NOT NULL, day TEXT NOT NULL, calls INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(user_id,day))")
    db.execute("CREATE TABLE IF NOT EXISTS premium_users (user_id INTEGER PRIMARY KEY, expires_at TEXT NOT NULL)")
    db.execute("""CREATE TABLE IF NOT EXISTS redeem_codes (
        code TEXT PRIMARY KEY, plan_days INTEGER NOT NULL, max_uses INTEGER NOT NULL,
        used_count INTEGER NOT NULL DEFAULT 0, created_by INTEGER NOT NULL, created_at TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS redeem_claims (
        code TEXT NOT NULL, user_id INTEGER NOT NULL, redeemed_at TEXT NOT NULL,
        PRIMARY KEY(code,user_id))""")
    db.execute("""CREATE TABLE IF NOT EXISTS payments (
        order_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, amount_idr INTEGER NOT NULL,
        plan_days INTEGER NOT NULL DEFAULT 30, purpose TEXT NOT NULL DEFAULT 'premium',
        status TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL)""")
    payment_columns = {row[1] for row in db.execute("PRAGMA table_info(payments)")}
    if "plan_days" not in payment_columns:
        db.execute("ALTER TABLE payments ADD COLUMN plan_days INTEGER NOT NULL DEFAULT 30")
    if "purpose" not in payment_columns:
        db.execute("ALTER TABLE payments ADD COLUMN purpose TEXT NOT NULL DEFAULT 'premium'")
    if "paid_at" not in payment_columns:
        db.execute("ALTER TABLE payments ADD COLUMN paid_at TEXT")
    if "channel_announced" not in payment_columns:
        db.execute("ALTER TABLE payments ADD COLUMN channel_announced INTEGER NOT NULL DEFAULT 0")
        db.execute("UPDATE payments SET channel_announced=1 WHERE status='paid'")
    db.execute("CREATE TABLE IF NOT EXISTS number_wallets (user_id INTEGER PRIMARY KEY, balance_idr INTEGER NOT NULL DEFAULT 0)")
    db.execute("""CREATE TABLE IF NOT EXISTS number_orders (
        order_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, price_idr INTEGER NOT NULL,
        status TEXT NOT NULL, created_at TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS telekos_webhook_deliveries (
        delivery_id TEXT PRIMARY KEY, received_at TEXT NOT NULL)""")
    db.commit()
    return db


def _name(user: Any) -> str:
    return " ".join(x for x in (getattr(user, "first_name", None), getattr(user, "last_name", None)) if x)


def record_event(user: Any, event: str) -> None:
    if user is None:
        return
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    field = {"start": "starts", "message": "messages", "file": "files"}.get(event)
    with _connect() as db:
        db.execute("""INSERT INTO users(user_id,username,display_name,first_seen,last_seen)
            VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,
            display_name=excluded.display_name,last_seen=excluded.last_seen""",
            (user.id, getattr(user, "username", None) or "", _name(user), now, now))
        if field:
            db.execute(f"UPDATE users SET {field}={field}+1 WHERE user_id=?", (user.id,))


def begin_ai_request(user: Any, model: str) -> int | None:
    if user is None:
        return None
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect() as db:
        db.execute("""INSERT INTO users(user_id,username,display_name,first_seen,last_seen,ai_calls)
            VALUES(?,?,?,?,?,1) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,
            display_name=excluded.display_name,last_seen=excluded.last_seen,ai_calls=users.ai_calls+1""",
            (user.id, getattr(user, "username", None) or "", _name(user), now, now))
        cur = db.execute("INSERT INTO ai_requests(user_id,created_at,model) VALUES(?,?,?)", (user.id, now, model))
        return int(cur.lastrowid)


def finish_ai_request(request_id: int | None, status: str, usage: dict[str, Any] | None = None) -> None:
    if request_id is None:
        return
    usage = usage or {}
    def count(*keys: str) -> int:
        for key in keys:
            value = usage.get(key)
            if isinstance(value, (int, float)) and value >= 0:
                return int(value)
        return 0
    inp = count("prompt_tokens", "input_tokens")
    out = count("completion_tokens", "output_tokens")
    total = count("total_tokens") or inp + out
    reported = int(any(k in usage for k in ("prompt_tokens", "input_tokens", "completion_tokens", "output_tokens", "total_tokens")))
    with _connect() as db:
        row = db.execute("SELECT user_id FROM ai_requests WHERE id=?", (request_id,)).fetchone()
        if row is None:
            return
        db.execute("UPDATE ai_requests SET status=?,input_tokens=?,output_tokens=?,total_tokens=?,usage_reported=? WHERE id=?",
                   (status, inp, out, total, reported, request_id))
        db.execute("""UPDATE users SET ai_failed=ai_failed+?,input_tokens=input_tokens+?,
            output_tokens=output_tokens+?,total_tokens=total_tokens+?,reported_token_calls=reported_token_calls+?
            WHERE user_id=?""", (int(status != "ok"), inp, out, total, reported, row["user_id"]))


def _render_page() -> bytes:
    with _connect() as db:
        totals = db.execute("""SELECT COUNT(*) users,COALESCE(SUM(ai_calls),0) calls,
            COALESCE(SUM(ai_failed),0) failed,COALESCE(SUM(input_tokens),0) input_tokens,
            COALESCE(SUM(output_tokens),0) output_tokens,COALESCE(SUM(total_tokens),0) total_tokens,
            COALESCE(SUM(reported_token_calls),0) reported FROM users""").fetchone()
        active = db.execute("SELECT COUNT(*) FROM users WHERE substr(last_seen,1,10)=?", (date.today().isoformat(),)).fetchone()[0]
        users = db.execute("SELECT * FROM users ORDER BY last_seen DESC LIMIT 200").fetchall()
        requests = db.execute("""SELECT r.*,u.username,u.display_name FROM ai_requests r
            LEFT JOIN users u USING(user_id) ORDER BY r.id DESC LIMIT 20""").fetchall()
    esc = lambda v: html.escape(str(v if v is not None else ""))
    metrics = [("Pengguna", totals["users"]), ("Aktif hari ini", active), ("Panggilan AI", totals["calls"]),
               ("Gagal", totals["failed"]), ("Token input", totals["input_tokens"]),
               ("Token output", totals["output_tokens"]), ("Total token", totals["total_tokens"]),
               ("Usage dilaporkan API", totals["reported"])]
    cards = "".join('<div class="card"><span>'+esc(k)+'</span><strong>'+f'{int(v):,}'+'</strong></div>' for k,v in metrics)
    user_rows = "".join('<tr><td>'+esc(u["display_name"] or "—")+(' <small>@'+esc(u["username"])+'</small>' if u["username"] else '')+
        '</td><td><code>'+esc(u["user_id"])+'</code></td><td>'+esc(u["last_seen"].replace("T"," "))+
        '</td><td>'+str(u["files"])+'</td><td>'+str(u["ai_calls"])+'</td><td>'+f'{u["total_tokens"]:,}'+
        (' <small>API</small>' if u["reported_token_calls"] else ' <small>belum dilaporkan</small>')+'</td></tr>' for u in users)
    request_rows = "".join('<tr><td>'+esc(r["created_at"].replace("T"," "))+'</td><td>'+esc(r["display_name"] or r["user_id"])+
        '</td><td>'+esc(r["model"])+'</td><td>'+esc(r["status"])+'</td><td>'+f'{r["input_tokens"]:,} / {r["output_tokens"]:,}'+
        (' <small>API</small>' if r["usage_reported"] else ' <small>n/a</small>')+'</td></tr>' for r in requests)
    style = "body{margin:0;background:#0b1020;color:#edf2ff;font:15px system-ui}main{max-width:1200px;margin:auto;padding:28px 18px}p,small{color:#9aa9c3}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin:24px 0}.card,.box{background:#141c30;border:1px solid #27334d;border-radius:12px;padding:16px}.card span{display:block;color:#9aa9c3;font-size:13px}.card strong{display:block;font-size:25px;margin-top:6px}.box{margin:20px 0;overflow:hidden}h2{font-size:18px}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;min-width:680px}th,td{text-align:left;padding:10px;border-bottom:1px solid #27334d;white-space:nowrap}th{color:#9aa9c3;font-size:12px}code{color:#77aaff}.note{font-size:13px}"
    page = ('<!doctype html><html lang="id"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="refresh" content="30"><title>Admin Bot</title><style>'+style+'</style><main><h1>Admin panel</h1>'
        '<p>Statistik bot Telegram · diperbarui otomatis setiap 30 detik</p><section class="grid">'+cards+'</section>'
        '<section class="box"><h2>Pengguna</h2><div class="scroll"><table><thead><tr><th>Nama</th><th>ID Telegram</th><th>Terakhir aktif (UTC)</th><th>File</th><th>Panggilan AI</th><th>Total token</th></tr></thead><tbody>'+
        (user_rows or '<tr><td colspan="6">Belum ada aktivitas.</td></tr>')+'</tbody></table></div></section>'
        '<section class="box"><h2>Panggilan AI terbaru</h2><div class="scroll"><table><thead><tr><th>Waktu (UTC)</th><th>Pengguna</th><th>Model</th><th>Status</th><th>Input / output token</th></tr></thead><tbody>'+
        (request_rows or '<tr><td colspan="5">Belum ada panggilan.</td></tr>')+'</tbody></table></div>'
        '<p class="note">Token diambil dari field usage yang dikembalikan API. Jika API tidak menyertakannya, angka 0 bukan estimasi. Isi file dan pesan pengguna tidak disimpan.</p></section></main></html>')
    return page.encode("utf-8")


class _Handler(BaseHTTPRequestHandler):
    server_version = "BotAdmin/1.0"
    def log_message(self, fmt: str, *args: Any) -> None:
        return
    def do_GET(self) -> None:
        if self.path not in ("/", "/index.html"):
            self.send_error(404); return
        password = os.getenv("ADMIN_PASSWORD", "")
        if not password:
            self.send_error(503, "ADMIN_PASSWORD belum diatur"); return
        authorized = False
        header = self.headers.get("Authorization", "")
        if header.startswith("Basic "):
            try:
                decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
                username, _, supplied = decoded.partition(":")
                authorized = username == "admin" and hmac.compare_digest(supplied, password)
            except (ValueError, UnicodeDecodeError):
                pass
        if not authorized:
            self.send_response(401); self.send_header("WWW-Authenticate", 'Basic realm="Admin Bot"')
            self.send_header("Cache-Control", "no-store"); self.end_headers(); return
        body = _render_page()
        self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body))); self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff"); self.send_header("X-Frame-Options", "DENY")
        self.end_headers(); self.wfile.write(body)


def start_admin_panel() -> None:
    from logging import getLogger
    logger = getLogger("file_reader_bot")
    if not os.getenv("ADMIN_PASSWORD"):
        logger.warning("Panel admin nonaktif: ADMIN_PASSWORD belum diatur."); return
    try:
        server = ThreadingHTTPServer((HOST, PORT), _Handler)
    except OSError as exc:
        logger.error("Panel admin tidak dapat dimulai pada %s:%s: %s", HOST, PORT, exc)
        return
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, name="admin-panel", daemon=True).start()
    logger.info("Panel admin tersedia pada http://%s:%s", HOST, PORT)


def get_admin_summary() -> dict[str, Any]:
    """Return aggregate counts for the Telegram admin menu."""
    with _connect() as db:
        row = db.execute("""SELECT COUNT(*) users,COALESCE(SUM(ai_calls),0) calls,
            COALESCE(SUM(ai_failed),0) failed,COALESCE(SUM(input_tokens),0) input_tokens,
            COALESCE(SUM(output_tokens),0) output_tokens,COALESCE(SUM(total_tokens),0) total_tokens,
            COALESCE(SUM(reported_token_calls),0) reported FROM users""").fetchone()
        active = db.execute("SELECT COUNT(*) FROM users WHERE substr(last_seen,1,10)=?", (date.today().isoformat(),)).fetchone()[0]
        recent = db.execute("""SELECT r.*,u.username,u.display_name FROM ai_requests r
            LEFT JOIN users u USING(user_id) ORDER BY r.id DESC LIMIT 5""").fetchall()
    result = dict(row)
    result["active_today"] = active
    result["recent"] = [dict(r) for r in recent]
    return result


def get_admin_user_ids() -> list[int]:
    """Return Telegram user IDs that have interacted with the bot."""
    with _connect() as db:
        rows = db.execute("SELECT user_id FROM users ORDER BY user_id").fetchall()
    return [int(row[0]) for row in rows]


def get_admin_users(limit: int = 8, offset: int = 0) -> tuple[int, list[dict[str, Any]]]:
    with _connect() as db:
        count = int(db.execute("SELECT COUNT(*) FROM users").fetchone()[0])
        rows = db.execute("SELECT * FROM users ORDER BY last_seen DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
    return count, [dict(row) for row in rows]


def get_admin_user(user_id: int) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    with _connect() as db:
        user = db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        recent = db.execute("SELECT * FROM ai_requests WHERE user_id=? ORDER BY id DESC LIMIT 5", (user_id,)).fetchall()
    return (dict(user) if user else None), [dict(row) for row in recent]


def is_user_blocked(user_id: int) -> bool:
    with _connect() as db:
        return db.execute("SELECT 1 FROM blocked_users WHERE user_id=?", (user_id,)).fetchone() is not None


def set_user_blocked(user_id: int, blocked: bool) -> None:
    with _connect() as db:
        if blocked:
            db.execute("INSERT OR IGNORE INTO blocked_users(user_id,blocked_at) VALUES(?,?)",
                       (user_id, datetime.now(timezone.utc).isoformat(timespec="seconds")))
        else:
            db.execute("DELETE FROM blocked_users WHERE user_id=?", (user_id,))
        db.execute("DELETE FROM monthly_usage WHERE user_id=?", (user_id,))
        db.execute("DELETE FROM daily_usage WHERE user_id=?", (user_id,))
        db.execute("DELETE FROM premium_users WHERE user_id=?", (user_id,))


def delete_admin_user(user_id: int) -> None:
    with _connect() as db:
        db.execute("DELETE FROM ai_requests WHERE user_id=?", (user_id,))
        db.execute("DELETE FROM users WHERE user_id=?", (user_id,))
        db.execute("DELETE FROM blocked_users WHERE user_id=?", (user_id,))



def record_file_result(user: Any, success: bool) -> None:
    if user is None:
        return
    column = "files_success" if success else "files_failed"
    with _connect() as db:
        db.execute(f"UPDATE users SET {column}={column}+1 WHERE user_id=?", (user.id,))


def create_airdrop_task(title: str, description: str, url: str, created_by: int) -> int:
    title = title.strip()
    description = description.strip()
    url = url.strip()
    if not title or len(title) > 80:
        raise ValueError("Nama garapan harus berisi 1–80 karakter.")
    if not description or len(description) > 500:
        raise ValueError("Deskripsi garapan harus berisi 1–500 karakter.")
    if not url or len(url) > 500:
        raise ValueError("Tautan garapan harus berisi 1–500 karakter.")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect() as db:
        cur = db.execute(
            "INSERT INTO airdrop_tasks(title,description,url,created_by,created_at) VALUES(?,?,?,?,?)",
            (title, description, url, created_by, now),
        )
        return int(cur.lastrowid)


def list_airdrop_tasks(limit: int = 5, offset: int = 0) -> list[dict[str, Any]]:
    with _connect() as db:
        rows = db.execute(
            "SELECT id,title,description,url,created_at FROM airdrop_tasks ORDER BY id DESC LIMIT ? OFFSET ?",
            (max(1, min(int(limit), 20)), max(0, int(offset))),
        ).fetchall()
    return [dict(row) for row in rows]


def count_airdrop_tasks() -> int:
    with _connect() as db:
        return int(db.execute("SELECT COUNT(*) FROM airdrop_tasks").fetchone()[0])


def get_airdrop_task(task_id: int) -> dict[str, Any] | None:
    with _connect() as db:
        row = db.execute(
            "SELECT id,title,description,url,created_at FROM airdrop_tasks WHERE id=?",
            (task_id,),
        ).fetchone()
    return dict(row) if row else None


def delete_airdrop_task(task_id: int) -> bool:
    with _connect() as db:
        cur = db.execute("DELETE FROM airdrop_tasks WHERE id=?", (task_id,))
        return cur.rowcount == 1


def get_file_count(user_id: int) -> int:
    with _connect() as db:
        row = db.execute("SELECT files_success FROM users WHERE user_id=?", (user_id,)).fetchone()
    return int(row[0]) if row else 0


def get_user_dashboard(user_id: int) -> dict[str, Any] | None:
    with _connect() as db:
        row = db.execute(
            "SELECT user_id,username,display_name,first_seen,files_success,files_failed FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def is_maintenance_enabled() -> bool:
    with _connect() as db:
        row = db.execute("SELECT value FROM settings WHERE key='maintenance'").fetchone()
    return bool(row and row["value"] == "1")


def set_maintenance_enabled(enabled: bool) -> None:
    with _connect() as db:
        db.execute("INSERT INTO settings(key,value) VALUES('maintenance',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   ("1" if enabled else "0",))


def is_number_purchase_visible() -> bool:
    with _connect() as db:
        row = db.execute("SELECT value FROM settings WHERE key='number_purchase_visible'").fetchone()
    return not row or row["value"] == "1"


def set_number_purchase_visible(visible: bool) -> None:
    with _connect() as db:
        db.execute("INSERT INTO settings(key,value) VALUES('number_purchase_visible',?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   ("1" if visible else "0",))


def use_ai_quota(user_id: int, free_daily_limit: int, premium_monthly_limit: int) -> tuple[bool, str, int, int]:
    """Consume one AI call: Free quota resets daily; Premium quota resets monthly."""
    now = datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    month = now.strftime("%Y-%m")
    with _connect() as db:
        premium = db.execute("SELECT expires_at FROM premium_users WHERE user_id=?", (user_id,)).fetchone()
        is_premium = bool(premium and premium["expires_at"] > now.isoformat(timespec="seconds"))
        if is_premium:
            plan, limit, table, period, period_key = "Premium", premium_monthly_limit, "monthly_usage", "month", month
        else:
            plan, limit, table, period, period_key = "Gratis", free_daily_limit, "daily_usage", "day", day
        db.execute(f"INSERT OR IGNORE INTO {table}(user_id,{period},calls) VALUES(?,?,0)", (user_id, period_key))
        cur = db.execute(f"UPDATE {table} SET calls=calls+1 WHERE user_id=? AND {period}=? AND calls<?",
                         (user_id, period_key, limit))
        used = int(db.execute(f"SELECT calls FROM {table} WHERE user_id=? AND {period}=?",
                              (user_id, period_key)).fetchone()[0])
        return cur.rowcount == 1, plan, used, limit


def get_user_plan(user_id: int, free_daily_limit: int, premium_monthly_limit: int) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    month = now.strftime("%Y-%m")
    with _connect() as db:
        premium = db.execute("SELECT expires_at FROM premium_users WHERE user_id=?", (user_id,)).fetchone()
        active = bool(premium and premium["expires_at"] > now.isoformat(timespec="seconds"))
        if active:
            used = db.execute("SELECT calls FROM monthly_usage WHERE user_id=? AND month=?", (user_id, month)).fetchone()
            limit, quota_period = premium_monthly_limit, "bulan ini"
        else:
            used = db.execute("SELECT calls FROM daily_usage WHERE user_id=? AND day=?", (user_id, day)).fetchone()
            limit, quota_period = free_daily_limit, "hari ini"
    return {"plan": "Premium" if active else "Gratis", "used": int(used[0]) if used else 0,
            "limit": limit, "quota_period": quota_period,
            "expires_at": premium["expires_at"] if active else None,
            "premium_expires_at": premium["expires_at"] if premium else None}


def create_redeem_code(code: str, days: int, max_uses: int, created_by: int) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect() as db:
        db.execute("INSERT INTO redeem_codes(code,plan_days,max_uses,created_by,created_at) VALUES(?,?,?,?,?)",
                   (code.upper(), days, max_uses, created_by, now))


def list_redeem_codes(limit: int = 8) -> list[dict[str, Any]]:
    with _connect() as db:
        rows = db.execute("SELECT code,plan_days,max_uses,used_count,created_at FROM redeem_codes ORDER BY created_at DESC LIMIT ?",
                           (limit,)).fetchall()
    return [dict(row) for row in rows]


def redeem_code(code: str, user_id: int) -> tuple[str, int, int, int]:
    """Atomically claim a code and extend Premium; return status, days, used, max uses."""
    now = datetime.now(timezone.utc)
    stamp = now.isoformat(timespec="seconds")
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM redeem_codes WHERE code=?", (code.upper(),)).fetchone()
        if not row:
            return "invalid", 0, 0, 0
        if db.execute("SELECT 1 FROM redeem_claims WHERE code=? AND user_id=?", (code.upper(), user_id)).fetchone():
            return "already_used", int(row["plan_days"]), int(row["used_count"]), int(row["max_uses"])
        if row["used_count"] >= row["max_uses"]:
            return "exhausted", int(row["plan_days"]), int(row["used_count"]), int(row["max_uses"])
        premium = db.execute("SELECT expires_at FROM premium_users WHERE user_id=?", (user_id,)).fetchone()
        base = datetime.fromisoformat(premium["expires_at"]) if premium and premium["expires_at"] > stamp else now
        expires = (base + timedelta(days=int(row["plan_days"]))).isoformat(timespec="seconds")
        db.execute("INSERT INTO redeem_claims(code,user_id,redeemed_at) VALUES(?,?,?)", (code.upper(), user_id, stamp))
        db.execute("UPDATE redeem_codes SET used_count=used_count+1 WHERE code=?", (code.upper(),))
        db.execute("INSERT INTO premium_users(user_id,expires_at) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET expires_at=excluded.expires_at",
                   (user_id, expires))
        return "ok", int(row["plan_days"]), int(row["used_count"]) + 1, int(row["max_uses"])


def grant_premium(user_id: int, days: int = 30) -> str:
    now = datetime.now(timezone.utc)
    with _connect() as db:
        row = db.execute("SELECT expires_at FROM premium_users WHERE user_id=?", (user_id,)).fetchone()
        base = datetime.fromisoformat(row["expires_at"]) if row and row["expires_at"] > now.isoformat(timespec="seconds") else now
        expires = (base + timedelta(days=days)).isoformat(timespec="seconds")
        db.execute("INSERT INTO premium_users(user_id,expires_at) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET expires_at=excluded.expires_at",
                   (user_id, expires))
    return expires


def revoke_premium(user_id: int) -> None:
    with _connect() as db:
        db.execute("DELETE FROM premium_users WHERE user_id=?", (user_id,))


def create_payment(order_id: str, user_id: int, amount_idr: int, plan_days: int, expires_at: str,
                   purpose: str = "premium") -> None:
    with _connect() as db:
        db.execute("INSERT INTO payments(order_id,user_id,amount_idr,plan_days,purpose,status,created_at,expires_at) VALUES(?,?,?,?,?, 'pending',?,?)",
                   (order_id, user_id, amount_idr, plan_days, purpose,
                    datetime.now(timezone.utc).isoformat(timespec="seconds"), expires_at))


def get_payment(order_id: str) -> dict[str, Any] | None:
    with _connect() as db:
        row = db.execute("SELECT * FROM payments WHERE order_id=?", (order_id,)).fetchone()
    return dict(row) if row else None


def mark_payment_status(order_id: str, status: str) -> None:
    with _connect() as db:
        db.execute("UPDATE payments SET status=? WHERE order_id=? AND status='pending'", (status, order_id))


def claim_payment_channel_announcement(order_id: str) -> bool:
    """Claim the one-time channel announcement for a settled payment."""
    with _connect() as db:
        cursor = db.execute(
            "UPDATE payments SET channel_announced=1 WHERE order_id=? AND status='paid' AND channel_announced=0",
            (order_id,))
        return cursor.rowcount == 1


def release_payment_channel_announcement(order_id: str) -> None:
    """Allow a failed channel announcement to be retried later."""
    with _connect() as db:
        db.execute("UPDATE payments SET channel_announced=0 WHERE order_id=? AND status='paid'", (order_id,))


def settle_payment(order_id: str, user_id: int, amount_idr: int) -> bool:
    """Idempotently mark a verified payment paid and grant Premium in one DB transaction."""
    now = datetime.now(timezone.utc)
    with _connect() as db:
        payment = db.execute("SELECT * FROM payments WHERE order_id=?", (order_id,)).fetchone()
        if not payment or payment["user_id"] != user_id or payment["amount_idr"] != amount_idr:
            return False
        if payment["status"] == "paid":
            return True
        if payment["status"] != "pending" or payment["expires_at"] <= now.isoformat(timespec="seconds"):
            return False
        if payment["purpose"] == "numbers_topup":
            db.execute("UPDATE payments SET status='paid', paid_at=? WHERE order_id=? AND status='pending'",
                       (now.isoformat(timespec="seconds"), order_id))
            db.execute("INSERT INTO number_wallets(user_id,balance_idr) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET balance_idr=number_wallets.balance_idr+excluded.balance_idr",
                       (user_id, amount_idr))
            return True
        premium = db.execute("SELECT expires_at FROM premium_users WHERE user_id=?", (user_id,)).fetchone()
        base = datetime.fromisoformat(premium["expires_at"]) if premium and premium["expires_at"] > now.isoformat(timespec="seconds") else now
        expires = (base + timedelta(days=payment["plan_days"])).isoformat(timespec="seconds")
        db.execute("UPDATE payments SET status='paid', paid_at=? WHERE order_id=? AND status='pending'",
                   (now.isoformat(timespec="seconds"), order_id))
        db.execute("INSERT INTO premium_users(user_id,expires_at) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET expires_at=excluded.expires_at",
                   (user_id, expires))
        return True


def number_wallet_balance(user_id: int) -> int:
    with _connect() as db:
        row = db.execute("SELECT balance_idr FROM number_wallets WHERE user_id=?", (user_id,)).fetchone()
    return int(row["balance_idr"]) if row else 0


def debit_number_wallet(user_id: int, amount_idr: int, order: dict[str, Any]) -> bool:
    """Charge an order once, after Telekos confirms it was created."""
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute("SELECT user_id FROM number_orders WHERE order_id=?", (order["id"],)).fetchone()
        if existing:
            return existing["user_id"] == user_id
        wallet = db.execute("SELECT balance_idr FROM number_wallets WHERE user_id=?", (user_id,)).fetchone()
        if not wallet or int(wallet["balance_idr"]) < amount_idr:
            return False
        db.execute("UPDATE number_wallets SET balance_idr=balance_idr-? WHERE user_id=?", (amount_idr, user_id))
        db.execute("INSERT INTO number_orders(order_id,user_id,price_idr,status,created_at) VALUES(?,?,?,?,?)",
                   (order["id"], user_id, amount_idr, str(order.get("status", "waiting")),
                    datetime.now(timezone.utc).isoformat(timespec="seconds")))
        return True


def get_number_order_owner(order_id: str) -> int | None:
    with _connect() as db:
        row = db.execute("SELECT user_id FROM number_orders WHERE order_id=?", (order_id,)).fetchone()
    return int(row["user_id"]) if row else None


def claim_telekos_webhook_delivery(delivery_id: str) -> bool:
    """Claim a Telekos delivery id once so retries do not send duplicate OTPs."""
    with _connect() as db:
        cursor = db.execute("INSERT OR IGNORE INTO telekos_webhook_deliveries(delivery_id,received_at) VALUES(?,?)",
                            (delivery_id, datetime.now(timezone.utc).isoformat(timespec="seconds")))
        return cursor.rowcount == 1


def release_telekos_webhook_delivery(delivery_id: str) -> None:
    with _connect() as db:
        db.execute("DELETE FROM telekos_webhook_deliveries WHERE delivery_id=?", (delivery_id,))


def get_number_order(order_id: str, user_id: int) -> dict[str, Any] | None:
    with _connect() as db:
        row = db.execute("SELECT * FROM number_orders WHERE order_id=? AND user_id=?", (order_id, user_id)).fetchone()
    return dict(row) if row else None


def update_number_order_status(order_id: str, status: str) -> None:
    with _connect() as db:
        db.execute("UPDATE number_orders SET status=? WHERE order_id=?", (status, order_id))


def refund_number_order(order_id: str, user_id: int) -> bool:
    """Credit a cancelled order once; call only after verifying with Telekos."""
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT price_idr,status FROM number_orders WHERE order_id=? AND user_id=?", (order_id, user_id)).fetchone()
        if not row:
            return False
        if row["status"] == "cancelled":
            return True
        db.execute("UPDATE number_orders SET status='cancelled' WHERE order_id=?", (order_id,))
        db.execute("INSERT INTO number_wallets(user_id,balance_idr) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET balance_idr=number_wallets.balance_idr+excluded.balance_idr",
                   (user_id, int(row["price_idr"])))
        return True
