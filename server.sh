#!/data/data/com.termux/files/usr/bin/sh
# Process supervisor for the Telegram bot on Termux.
set -eu
APP_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PID_FILE="$APP_DIR/server.pid"
LOG_FILE="$APP_DIR/server.log"
RUNNER="$APP_DIR/.server-runner.sh"
is_running() {
    [ -f "$PID_FILE" ] || return 1
    pid=$(cat "$PID_FILE" 2>/dev/null || true)
    case "$pid" in ''|*[!0-9]*) return 1 ;; esac
    kill -0 "$pid" 2>/dev/null
}
case "${1:-status}" in
  start)
    if is_running; then echo "Bot sudah berjalan (PID $(cat "$PID_FILE"))."; exit 0; fi
    if [ ! -f "$APP_DIR/.env" ]; then echo "File .env belum ada." >&2; exit 1; fi
    if ! grep -Eq '^TELEGRAM_BOT_TOKEN=.+$' "$APP_DIR/.env" || ! grep -Eq '^APINEX_API_KEY=.+$' "$APP_DIR/.env"; then
      echo "TELEGRAM_BOT_TOKEN atau APINEX_API_KEY belum terisi di .env." >&2; exit 1
    fi
    cat > "$RUNNER" <<'RUNNER_EOF'
#!/data/data/com.termux/files/usr/bin/sh
set -u
APP_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$APP_DIR" || exit 1
child=
cleanup() {
  trap - TERM INT HUP
  if [ -n "$child" ]; then kill "$child" 2>/dev/null || true; wait "$child" 2>/dev/null || true; fi
  command -v termux-wake-unlock >/dev/null 2>&1 && termux-wake-unlock >/dev/null 2>&1 || true
  rm -f "$APP_DIR/server.pid" "$APP_DIR/.server-runner.sh"
  exit 0
}
trap cleanup TERM INT HUP
command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock >/dev/null 2>&1 || true
while :; do
  if [ -x "$APP_DIR/.venv/bin/python" ]; then "$APP_DIR/.venv/bin/python" "$APP_DIR/bot.py" &
  else python "$APP_DIR/bot.py" & fi
  child=$!
  wait "$child"
  result=$?
  child=
  echo "$(date '+%Y-%m-%d %H:%M:%S') bot exited (status $result); restarting in 5 seconds" >&2
  sleep 5 &
  child=$!
  wait "$child" || true
  child=
done
RUNNER_EOF
    chmod 700 "$RUNNER"
    nohup setsid "$RUNNER" >> "$LOG_FILE" 2>&1 </dev/null &
    pid=$!
    printf '%s\n' "$pid" > "$PID_FILE"
    sleep 1
    if is_running; then echo "Bot dijalankan di latar (PID $pid). Log: $LOG_FILE"
    else rm -f "$PID_FILE"; echo "Bot gagal mulai. Periksa $LOG_FILE." >&2; exit 1; fi
    ;;
  stop)
    if ! is_running; then rm -f "$PID_FILE" "$RUNNER"; echo "Bot tidak sedang berjalan."; exit 0; fi
    pid=$(cat "$PID_FILE")
    kill "$pid"
    i=0
    while kill -0 "$pid" 2>/dev/null && [ "$i" -lt 10 ]; do sleep 1; i=$((i + 1)); done
    if kill -0 "$pid" 2>/dev/null; then echo "Proses belum berhenti; cek $LOG_FILE." >&2; exit 1; fi
    rm -f "$PID_FILE" "$RUNNER"
    echo "Bot dihentikan."
    ;;
  status)
    if is_running; then echo "Bot berjalan (PID $(cat "$PID_FILE")). Log: $LOG_FILE"
    else rm -f "$PID_FILE"; echo "Bot tidak berjalan."; exit 1; fi
    ;;
  logs) tail -n 50 -f "$LOG_FILE" ;;
  *) echo "Pemakaian: $0 {start|stop|status|logs}" >&2; exit 2 ;;
esac
