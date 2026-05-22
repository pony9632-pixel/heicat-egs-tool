#!/bin/bash
# STUDIO A 黑貓宅急便工具 — 一鍵安裝腳本
# 使用方式：curl -fsSL https://raw.githubusercontent.com/pony9632-pixel/heicat-egs-tool/main/install.sh | bash

set -euo pipefail

TMP_ZIP=""
TMP_DIR=""
cleanup() {
    [[ -n "$TMP_ZIP" ]] && rm -f "$TMP_ZIP"
    [[ -n "$TMP_DIR" ]] && rm -rf "$TMP_DIR"
}
trap cleanup EXIT

REPO="pony9632-pixel/heicat-egs-tool"
INSTALL_DIR="$HOME/Desktop/黑貓宅急便工具"
GITHUB_API="https://api.github.com/repos/$REPO/releases/latest"

echo ""
echo "============================================"
echo "  STUDIO A 黑貓宅急便工具 — 安裝程式"
echo "============================================"
echo ""

# ── 1. 確認 macOS ────────────────────────────────────────────────────────────
if [[ "$(uname)" != "Darwin" ]]; then
    echo "❌ 此工具僅支援 macOS，無法繼續安裝。"
    exit 1
fi

# ── 2. 確認 Python 3.10 以上 ─────────────────────────────────────────────────
echo "🔍 檢查 Python 3..."

python_ok() {
    command -v python3 &>/dev/null && python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null
}

if ! python_ok; then
    echo ""
    echo "❌ 找不到 Python 3.10 以上版本。"
    echo ""
    echo "   請先安裝 Python，步驟如下："
    echo ""
    echo "   1. 開啟瀏覽器，前往：https://www.python.org/downloads/"
    echo "   2. 點「Download Python 3.x.x」下載安裝檔"
    echo "   3. 執行安裝，全部選預設，一路按「繼續」即可"
    echo "   4. 安裝完成後，重新開啟終端機（Terminal）"
    echo "   5. 再次執行這個安裝指令"
    echo ""
    exit 1
fi
PYTHON_BIN="$(command -v python3)"
echo "✅ $("$PYTHON_BIN" --version) 已就緒"
echo ""

# ── 2b. 確認 tkinter 可用 ─────────────────────────────────────────────────────
echo "🔍 檢查 tkinter（GUI 模組）..."
if ! "$PYTHON_BIN" -c "import tkinter" &>/dev/null; then
    echo ""
    echo "❌ Python 缺少 tkinter 模組（GUI 所需）。"
    echo ""
    echo "   請重新安裝 Python（官網版本內建 tkinter）："
    echo ""
    echo "   1. 前往：https://www.python.org/downloads/"
    echo "   2. 下載並安裝最新版 Python 3.x"
    echo "   3. 安裝完成後重新開啟終端機，再執行這個安裝指令"
    echo ""
    exit 1
fi
echo "✅ tkinter 可用"
echo ""

# ── 3. 取得最新版本資訊 ───────────────────────────────────────────────────────
echo "📡 查詢最新版本..."
API_RESPONSE=$(curl -fsSL "$GITHUB_API" 2>/dev/null || true)

LATEST_TAG=$(echo "$API_RESPONSE" | grep '"tag_name"' | head -1 | cut -d '"' -f 4)
ZIPBALL_URL=$(echo "$API_RESPONSE" | grep '"zipball_url"' | head -1 | cut -d '"' -f 4)

if [[ -z "$ZIPBALL_URL" ]]; then
    # 若無 Release，改用 main branch zip
    ZIPBALL_URL="https://github.com/$REPO/archive/refs/heads/main.zip"
    LATEST_TAG="main"
fi
echo "✅ 版本：${LATEST_TAG}"
echo ""

# ── 4 + 5. 下載、解壓、安裝（全部用 Python，避開 unzip 中文路徑問題）─────────
echo "📥 下載並安裝中（請稍候）..."
"$PYTHON_BIN" -c "
import urllib.request, zipfile, os, shutil, ssl, sys

zipball_url = '$ZIPBALL_URL'
install_dir = '$INSTALL_DIR'

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

tmp_zip = '/tmp/heicat_install_$$.zip'
tmp_dir = '/tmp/heicat_dir_$$'

# 下載
req = urllib.request.Request(zipball_url, headers={'User-Agent': 'heicat-install'})
with urllib.request.urlopen(req, context=ctx, timeout=60) as r, open(tmp_zip, 'wb') as f:
    shutil.copyfileobj(r, f)

# 解壓
if os.path.exists(tmp_dir):
    shutil.rmtree(tmp_dir)
os.makedirs(tmp_dir)
with zipfile.ZipFile(tmp_zip, 'r') as z:
    z.extractall(tmp_dir)

# 找到 GitHub zip 多一層的前綴資料夾
top = next(p for p in os.scandir(tmp_dir) if p.is_dir())
src = os.path.join(top.path, '黑貓主程式')

# 安裝
if os.path.isdir(install_dir):
    dst = os.path.join(install_dir, '黑貓主程式')
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
else:
    os.makedirs(install_dir, exist_ok=True)
    shutil.copytree(src, os.path.join(install_dir, '黑貓主程式'))

# 清理
os.unlink(tmp_zip)
shutil.rmtree(tmp_dir)
print('installed')
"
echo "✅ 程式已安裝至：$INSTALL_DIR"
echo ""

# ── 6. 建立 venv 並安裝套件 ──────────────────────────────────────────────────
echo "📦 建立虛擬環境並安裝套件..."
VENV_DIR="$INSTALL_DIR/venv"
"$PYTHON_BIN" -m venv "$VENV_DIR"
VENV_PYTHON="$VENV_DIR/bin/python3"

REQ_FILE="$INSTALL_DIR/黑貓主程式/requirements.txt"
if [[ -f "$REQ_FILE" ]]; then
    "$VENV_PYTHON" -m pip install --quiet --upgrade -r "$REQ_FILE"
else
    "$VENV_PYTHON" -m pip install --quiet --upgrade pyyaml "pypdf>=4.0" "requests>=2.31" customtkinter
fi
echo "✅ 套件安裝完成"

# 設定啟動腳本，使用 venv 內的 Python
cat > "$INSTALL_DIR/黑貓主程式/啟動黑貓工具.command" <<EOF
#!/bin/bash
SCRIPT_DIR="\$(cd "\$(dirname "\$0")" && pwd)"
APP_ROOT="\$(dirname "\$SCRIPT_DIR")"
PYTHON_BIN="\$APP_ROOT/venv/bin/python3"
if [[ ! -x "\$PYTHON_BIN" ]]; then
    PYTHON_BIN="python3"
fi
LOG="\$APP_ROOT/啟動診斷.log"
DESKTOP_LOG="\$HOME/Desktop/黑貓啟動診斷.log"
START_TS="\$(date +%s)"

write_log() {
    echo "\$1" | tee -a "\$LOG" "\$DESKTOP_LOG"
}

mkdir -p "\$APP_ROOT" "\$HOME/Desktop"
: > "\$LOG"
: > "\$DESKTOP_LOG"
cd "\$SCRIPT_DIR"
write_log "[\$(date '+%Y-%m-%d %H:%M:%S')] 啟動黑貓工具 launcher=v2.5.9"
write_log "SCRIPT_DIR=\$SCRIPT_DIR"
write_log "APP_ROOT=\$APP_ROOT"
write_log "PYTHON_BIN=\$PYTHON_BIN"
"\$PYTHON_BIN" app.py >> "\$LOG" 2>&1
STATUS=\$?
cat "\$LOG" > "\$DESKTOP_LOG"
END_TS="\$(date +%s)"
DURATION=\$((END_TS - START_TS))
if [[ \$STATUS -ne 0 || \$DURATION -lt 3 ]]; then
    echo ""
    echo "黑貓工具啟動後立刻結束，診斷紀錄已寫入："
    echo "  \$LOG"
    echo "  \$DESKTOP_LOG"
    echo ""
    cat "\$LOG"
    echo ""
    echo "請把這個畫面或「黑貓啟動診斷.log」傳給維護者。"
    echo "按 Enter 關閉視窗。"
    read
else
    osascript -e 'tell application "Terminal" to close (every window whose name contains "啟動黑貓工具")' &
fi
EOF
chmod +x "$INSTALL_DIR/黑貓主程式/啟動黑貓工具.command"
echo ""

# ── 7. 完成 ──────────────────────────────────────────────────────────────────
echo "============================================"
echo "  ✅ 安裝完成！"
echo "============================================"
echo ""
echo "接下來的步驟："
echo ""
echo "  1. 桌面 → 黑貓宅急便工具 → 黑貓主程式"
echo "  2. 雙擊「啟動黑貓工具.command」"
echo "  3. 第一次使用：切到「設定」分頁"
echo "     填入黑貓業務給你的「客戶代號」與「API 授權碼」"
echo "     按「儲存設定」→「測試 API 連線」確認 ● 連線正常"
echo ""
echo "  ⚠️  第一次雙擊若出現「無法打開，因為來自未識別的開發者」："
echo "     系統設定 → 隱私權與安全性 → 找到被封鎖的項目 → 點「仍要打開」"
echo ""

# 開啟 Finder 到安裝資料夾
open "$INSTALL_DIR/黑貓主程式" 2>/dev/null || true
