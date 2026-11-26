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

# Apple 晶片的 Mac 一律以原生 arm64 執行 Python。
# 通用版（universal2）Python 會跟著「啟動它的程式」選架構：終端機若勾了「使用 Rosetta 打開」、
# 或從 Intel 模式的程式啟動，就會變成 Intel 模式，macOS 26 起會跳「即將結束支援 Intel 架構」，
# 之後的 macOS 拿掉 Rosetta 就開不起來。用 arch -arm64 明確指定就不受影響。
IS_APPLE_SILICON=0
if [[ "$(sysctl -n hw.optional.arm64 2>/dev/null)" == "1" ]]; then IS_APPLE_SILICON=1; fi
USE_ROSETTA=0   # 只有在這台 Mac 找不到 Apple 晶片版 Python 時才會設成 1（暫時相容）

run_py() {
    if [[ $IS_APPLE_SILICON -eq 1 && $USE_ROSETTA -eq 0 ]]; then
        arch -arm64 "$@"
    else
        "$@"
    fi
}

python_ok() {
    run_py "$1" -c 'import sys, tkinter; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null
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
    local rebuild=0
    if [[ ! -x "$PYTHON_BIN" ]]; then
        rebuild=1
        write_log "找不到虛擬環境，正在建立（第一次約需 1～2 分鐘，請勿關閉視窗）..."
    elif [[ $IS_APPLE_SILICON -eq 1 ]] && ! arch -arm64 "$PYTHON_BIN" -c 'pass' 2>/dev/null; then
        # 現有 venv 是用 Intel 版 Python 建的，在 Apple 晶片上只能靠 Rosetta 跑
        if [[ -n "$(find_python || true)" ]]; then
            rebuild=1
            write_log "目前的虛擬環境是 Intel 版 Python，改用 Apple 晶片版重建（約需 1～2 分鐘，請勿關閉視窗）..."
        else
            USE_ROSETTA=1
            write_log "⚠️ 這台 Mac 只有 Intel 版 Python，暫時以 Rosetta 相容模式執行。"
            write_log "   未來的 macOS 將不再支援，請依 README 在終端機貼上安裝指令重新安裝（會自動安裝 Apple 晶片版 Python）。"
        fi
    fi
    if [[ $rebuild -eq 1 ]]; then
        SYS_PY="$(find_python || true)"
        if [[ -z "$SYS_PY" && $IS_APPLE_SILICON -eq 1 ]]; then
            # 沒有 Apple 晶片版，退而求其次找 Intel 版，至少先能開
            USE_ROSETTA=1
            SYS_PY="$(find_python || true)"
            if [[ -n "$SYS_PY" ]]; then
                write_log "⚠️ 這台 Mac 只找到 Intel 版 Python，暫時以 Rosetta 相容模式執行；請依 README 重新執行安裝指令。"
            fi
        fi
        if [[ -z "$SYS_PY" ]]; then
            write_log "找不到 Python 3.10 以上（含 tkinter）。請依 README 在終端機貼上安裝指令重新安裝，它會自動安裝 Python。"
            return 1
        fi
        write_log "SYS_PY=$SYS_PY ($("$SYS_PY" --version 2>&1))"
        # --clear：venv 裡的 python 是指向建立它那台電腦的絕對路徑符號連結，
        # 整個資料夾複製到別台 Mac 後會斷掉；不清空就重建會報 No such file or directory
        if ! run_py "$SYS_PY" -m venv --clear "$VENV_DIR" >> "$LOG" 2>&1; then
            write_log "建立虛擬環境失敗。"
            return 1
        fi
    fi
    if ! run_py "$PYTHON_BIN" -m pip --version >> "$LOG" 2>&1; then
        write_log "虛擬環境內沒有 pip，補裝中..."
        run_py "$PYTHON_BIN" -m ensurepip --upgrade >> "$LOG" 2>&1 || true
    fi
    local import_check="import customtkinter, requests, yaml, pypdf, certifi"
    if ! run_py "$PYTHON_BIN" -c "$import_check" >> "$LOG" 2>&1; then
        write_log "缺少必要套件，正在安裝（需要網路連線）..."
        if ! run_py "$PYTHON_BIN" -m pip install --quiet --upgrade -r "$SCRIPT_DIR/requirements.txt" >> "$LOG" 2>&1; then
            write_log "套件安裝失敗，請確認網路連線後再試。"
            return 1
        fi
        # 套件「已安裝」卻仍載入失敗，通常是之前在 Intel 模式下裝到 Intel 版的編譯檔，強制重裝成本機架構
        if ! run_py "$PYTHON_BIN" -c "$import_check" >> "$LOG" 2>&1; then
            write_log "套件架構不符，重新安裝中..."
            if ! run_py "$PYTHON_BIN" -m pip install --quiet --force-reinstall -r "$SCRIPT_DIR/requirements.txt" >> "$LOG" 2>&1 \
               || ! run_py "$PYTHON_BIN" -c "$import_check" >> "$LOG" 2>&1; then
                write_log "套件重新安裝後仍無法載入，請依 README 重新執行安裝指令。"
                return 1
            fi
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

write_log "ARCH=$(run_py "$PYTHON_BIN" -c 'import platform; print(platform.machine())' 2>&1)（Apple 晶片=$IS_APPLE_SILICON，Rosetta 相容模式=$USE_ROSETTA）"

START_TS="$(date +%s)"
run_py "$PYTHON_BIN" app.py >> "$LOG" 2>&1
STATUS=$?
END_TS="$(date +%s)"
DURATION=$((END_TS - START_TS))
if [[ $STATUS -ne 0 || $DURATION -lt 3 ]]; then
    fail_and_wait "黑貓工具啟動後立刻結束。"
else
    osascript -e 'tell application "Terminal" to close (every window whose name contains "啟動黑貓工具")' &
fi
