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

python_ok() {
    "$1" -c 'import sys, tkinter; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null
}

# 與 install.sh 相同的偵測順序：python.org 官方版（新到舊）→ Homebrew → PATH 上的 python3；
# /usr/bin/python3 沒裝 Command Line Tools 時一執行就跳視窗，所以最後才試。
find_python() {
    local c
    for c in $(ls -d /Library/Frameworks/Python.framework/Versions/3.*/bin/python3 2>/dev/null | sort -rV) \
             /opt/homebrew/bin/python3 /usr/local/bin/python3; do
        if [[ -x "$c" ]] && python_ok "$c"; then echo "$c"; return 0; fi
    done
    c="$(command -v python3 2>/dev/null || true)"
    if [[ -n "$c" ]]; then
        if [[ "$c" != /usr/bin/python3 ]] || xcode-select -p &>/dev/null; then
            if python_ok "$c"; then echo "$c"; return 0; fi
        fi
    fi
    return 1
}

# 虛擬環境不存在（直接複製資料夾、沒跑安裝程式、或 venv 被刪）就自動重建，
# 不退回系統 python3——系統 Python 通常沒裝 customtkinter，啟動一定失敗。
ensure_env() {
    if [[ ! -x "$PYTHON_BIN" ]]; then
        write_log "找不到虛擬環境，正在建立（第一次約需 1～2 分鐘，請勿關閉視窗）..."
        SYS_PY="$(find_python || true)"
        if [[ -z "$SYS_PY" ]]; then
            write_log "找不到 Python 3.10 以上（含 tkinter）。請到 GitHub Release 頁面下載 install-heicat-tool.zip，解開後執行裡面的 .command，它會自動安裝 Python。"
            return 1
        fi
        write_log "SYS_PY=$SYS_PY ($("$SYS_PY" --version 2>&1))"
        if ! "$SYS_PY" -m venv "$VENV_DIR" >> "$LOG" 2>&1; then
            write_log "建立虛擬環境失敗。"
            return 1
        fi
    fi
    if ! "$PYTHON_BIN" -m pip --version >> "$LOG" 2>&1; then
        write_log "虛擬環境內沒有 pip，補裝中..."
        "$PYTHON_BIN" -m ensurepip --upgrade >> "$LOG" 2>&1 || true
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
