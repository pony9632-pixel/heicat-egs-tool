#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_ROOT="$(dirname "$SCRIPT_DIR")"
PYTHON_BIN="$APP_ROOT/venv/bin/python3"
if [[ ! -x "$PYTHON_BIN" ]]; then
    PYTHON_BIN="python3"
fi
LOG="$APP_ROOT/啟動診斷.log"
DESKTOP_LOG="$HOME/Desktop/黑貓啟動診斷.log"
START_TS="$(date +%s)"

write_log() {
    echo "$1" | tee -a "$LOG"
}

: > "$LOG"
cd "$SCRIPT_DIR"
write_log "[$(date '+%Y-%m-%d %H:%M:%S')] 啟動黑貓工具"
write_log "SCRIPT_DIR=$SCRIPT_DIR"
write_log "APP_ROOT=$APP_ROOT"
write_log "PYTHON_BIN=$PYTHON_BIN"
"$PYTHON_BIN" app.py >> "$LOG" 2>&1
STATUS=$?
END_TS="$(date +%s)"
DURATION=$((END_TS - START_TS))
if [[ $STATUS -ne 0 || $DURATION -lt 3 ]]; then
    # 只有啟動異常時才把診斷複製到桌面，方便同事回報；正常啟動不在桌面留檔
    cp "$LOG" "$DESKTOP_LOG" 2>/dev/null
    echo ""
    echo "黑貓工具啟動後立刻結束，診斷紀錄已寫入："
    echo "  $LOG"
    echo "  $DESKTOP_LOG"
    echo ""
    cat "$LOG"
    echo ""
    echo "請把這個畫面或「黑貓啟動診斷.log」傳給維護者。"
    echo "按 Enter 關閉視窗。"
    read
else
    osascript -e 'tell application "Terminal" to close (every window whose name contains "啟動黑貓工具")' &
fi
