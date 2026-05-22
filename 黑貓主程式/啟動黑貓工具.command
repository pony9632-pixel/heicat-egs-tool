#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_ROOT="$(dirname "$SCRIPT_DIR")"
PYTHON_BIN="$APP_ROOT/venv/bin/python3"
if [[ ! -x "$PYTHON_BIN" ]]; then
    PYTHON_BIN="python3"
fi
LOG="$APP_ROOT/啟動錯誤.log"
cd "$SCRIPT_DIR"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 啟動黑貓工具" > "$LOG"
"$PYTHON_BIN" app.py >> "$LOG" 2>&1
STATUS=$?
if [[ $STATUS -ne 0 ]]; then
    echo ""
    echo "黑貓工具啟動失敗，錯誤紀錄已寫入：$LOG"
    echo ""
    cat "$LOG"
    echo ""
    echo "請把這個畫面或啟動錯誤.log 傳給維護者。"
    echo "按 Enter 關閉視窗。"
    read
fi
