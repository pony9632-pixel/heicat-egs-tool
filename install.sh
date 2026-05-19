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

# ── 2. 確認 Python 3（沒有就自動安裝）────────────────────────────────────────
echo "🔍 檢查 Python 3..."
if ! command -v python3 &>/dev/null; then
    echo "⚠️  找不到 Python 3，嘗試自動安裝..."
    echo ""

    if ! command -v brew &>/dev/null; then
        echo "📦 先安裝 Homebrew（macOS 套件管理器）..."
        echo "   （過程中可能會要求輸入你的電腦登入密碼，這是正常的）"
        echo ""
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

        # Apple Silicon (M1/M2/M3) 的 Homebrew 裝在 /opt/homebrew
        if [[ -f /opt/homebrew/bin/brew ]]; then
            eval "$(/opt/homebrew/bin/brew shellenv)"
        fi
        echo ""
        echo "✅ Homebrew 安裝完成"
    else
        echo "✅ Homebrew 已存在"
    fi

    echo ""
    echo "📦 安裝 Python 3..."
    brew install python3
    echo ""

    # 再確認一次
    if ! command -v python3 &>/dev/null; then
        echo "❌ Python 3 安裝後仍無法偵測，請重新開啟終端機後再執行一次安裝指令。"
        exit 1
    fi
fi
echo "✅ $(python3 --version) 已就緒"
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
python3 -c "
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

# 設定執行權限
chmod +x "$INSTALL_DIR/黑貓主程式/啟動黑貓工具.command"

# ── 6. 安裝 Python 套件 ───────────────────────────────────────────────────────
echo "📦 安裝 Python 套件..."
python3 -m pip install --quiet --upgrade pyyaml "pypdf>=4.0" "requests>=2.31"
echo "✅ 套件安裝完成"
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
