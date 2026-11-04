#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_ROOT="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$APP_ROOT/venv"
PYTHON_BIN="$VENV_DIR/bin/python3"
LOG="$APP_ROOT/啟動診斷.log"
DESKTOP_LOG="$HOME/Desktop/黑貓啟動診斷.log"

write_log() {
    echo "$1" | tee -a "$LOG"
}

fail_and_wait() {
    # 只有啟動異常時才把診斷複製到桌面，方便同事回報；正常啟動不在桌面留檔
    cp "$LOG" "$DESKTOP_LOG" 2>/dev/null
    echo ""
    echo "$1"
    echo "診斷紀錄已寫入："
    echo "  $LOG"
    echo "  $DESKTOP_LOG"
    echo ""
    cat "$LOG"
    echo ""
    echo "請把這個畫面或「黑貓啟動診斷.log」傳給維護者。"
    echo "按 Enter 關閉視窗。"
    read
    exit 1
}

# 虛擬環境不存在（直接複製資料夾、沒跑安裝程式、或 venv 被刪）就自動重建，
# 不退回系統 python3——系統 Python 通常沒裝 customtkinter，啟動一定失敗。
ensure_env() {
    if [[ ! -x "$PYTHON_BIN" ]]; then
        write_log "找不到虛擬環境，正在建立（第一次約需 1～2 分鐘，請勿關閉視窗）..."
        SYS_PY="$(command -v python3 || true)"
        if [[ -z "$SYS_PY" ]] || ! "$SYS_PY" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
            write_log "找不到 Python 3.10 以上版本。請到 https://www.python.org/downloads/ 安裝後再試。"
            return 1
        fi
        if ! "$SYS_PY" -c "import tkinter" 2>/dev/null; then
            write_log "Python 缺少 tkinter（GUI 所需）。請到 https://www.python.org/downloads/ 重新安裝官方版 Python。"
            return 1
        fi
        write_log "SYS_PY=$SYS_PY ($("$SYS_PY" --version 2>&1))"
        if ! "$SYS_PY" -m venv "$VENV_DIR" >> "$LOG" 2>&1; then
            write_log "建立虛擬環境失敗。"
            return 1
        fi
    fi
    if ! "$PYTHON_BIN" -c "import customtkinter, requests, yaml, pypdf, certifi" >> "$LOG" 2>&1; then
        write_log "缺少必要套件，正在安裝（需要網路連線）..."
        if ! "$PYTHON_BIN" -m pip install --quiet --upgrade -r "$SCRIPT_DIR/requirements.txt" >> "$LOG" 2>&1; then
            write_log "套件安裝失敗，請確認網路連線後再試。"
            return 1
        fi
        write_log "套件安裝完成。"
    fi
}

: > "$LOG"
cd "$SCRIPT_DIR"
write_log "[$(date '+%Y-%m-%d %H:%M:%S')] 啟動黑貓工具"
write_log "SCRIPT_DIR=$SCRIPT_DIR"
write_log "APP_ROOT=$APP_ROOT"
write_log "PYTHON_BIN=$PYTHON_BIN"

ensure_env || fail_and_wait "黑貓工具環境準備失敗，無法啟動。"

START_TS="$(date +%s)"
"$PYTHON_BIN" app.py >> "$LOG" 2>&1
STATUS=$?
END_TS="$(date +%s)"
DURATION=$((END_TS - START_TS))
if [[ $STATUS -ne 0 || $DURATION -lt 3 ]]; then
    fail_and_wait "黑貓工具啟動後立刻結束。"
else
    osascript -e 'tell application "Terminal" to close (every window whose name contains "啟動黑貓工具")' &
fi
