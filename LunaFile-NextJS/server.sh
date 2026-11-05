#!/data/data/com.termux/files/usr/bin/sh
set -eu
DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PID_FILE="$DIR/server.pid"
LOG_FILE="$DIR/server.log"
is_running(){ [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; }
case "${1:-status}" in
  start)
    if is_running; then echo "Next.js sudah berjalan (PID $(cat "$PID_FILE"))."; exit 0; fi
    [ -f "$DIR/.env" ] || { echo ".env belum ada. Salin .env.example ke .env dan isi konfigurasi." >&2; exit 1; }
    [ -d "$DIR/node_modules/next" ] || { echo "Dependensi belum dipasang. Jalankan npm install." >&2; exit 1; }
    [ -d "$DIR/.next" ] || { echo "Build belum tersedia. Jalankan npm run build." >&2; exit 1; }
    cd "$DIR"
    HOSTNAME="${HOSTNAME:-127.0.0.1}" nohup ./node_modules/.bin/next start --hostname "${HOSTNAME:-127.0.0.1}" >>"$LOG_FILE" 2>&1 </dev/null &
    echo $! >"$PID_FILE"
    sleep 2
    if is_running; then echo "Next.js berjalan (PID $(cat "$PID_FILE")). Log: $LOG_FILE"; else rm -f "$PID_FILE"; echo "Next.js gagal mulai; cek $LOG_FILE." >&2; exit 1; fi
    ;;
  stop)
    if ! is_running; then rm -f "$PID_FILE"; echo "Next.js tidak berjalan."; exit 0; fi
    pid=$(cat "$PID_FILE"); kill "$pid" 2>/dev/null || true
    i=0; while kill -0 "$pid" 2>/dev/null && [ "$i" -lt 10 ]; do sleep 1; i=$((i+1)); done
    if kill -0 "$pid" 2>/dev/null; then echo "Proses belum berhenti; cek $LOG_FILE." >&2; exit 1; fi
    rm -f "$PID_FILE"; echo "Next.js dihentikan."
    ;;
  status) if is_running; then echo "Next.js berjalan (PID $(cat "$PID_FILE")). Log: $LOG_FILE"; else echo "Next.js tidak berjalan."; exit 1; fi ;;
  logs) tail -n 50 -f "$LOG_FILE" ;;
  *) echo "Pemakaian: $0 {start|stop|status|logs}" >&2; exit 2 ;;
esac
