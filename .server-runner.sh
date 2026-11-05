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
