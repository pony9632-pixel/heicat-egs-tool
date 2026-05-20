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

# ── 2. 確認 Python 3.10 以上（沒有或太舊就自動安裝）────────────────────────
echo "🔍 檢查 Python 3..."

python_ok() {
    command -v python3 &>/dev/null && python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null
}

ensure_homebrew() {
    if ! command -v brew &>/dev/null; then
        echo "📦 先安裝 Homebrew（macOS 套件管理器）..."
        echo "   （過程中可能會要求輸入你的電腦登入密碼，這是正常的）"
        echo ""
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    else
        echo "✅ Homebrew 已存在"
    fi

    # Apple Silicon (M1/M2/M3) 的 Homebrew 裝在 /opt/homebrew；Intel 常見於 /usr/local
    if [[ -f /opt/homebrew/bin/brew ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [[ -f /usr/local/bin/brew ]]; then
        eval "$(/usr/local/bin/brew shellenv)"
    fi
}

if ! python_ok; then
    echo "⚠️  需要 Python 3.10 以上，嘗試自動安裝/更新..."
    echo ""

    ensure_homebrew

    echo ""
    echo "📦 安裝 Python 3..."
    brew install python3
    brew upgrade python3 || true
    echo ""

    # 再確認一次
    if ! python_ok; then
        echo "❌ Python 3.10 以上安裝後仍無法偵測，請重新開啟終端機後再執行一次安裝指令。"
        exit 1
    fi
fi
PYTHON_BIN="$(command -v python3)"
echo "✅ $("$PYTHON_BIN" --version) 已就緒"
echo ""

# ── 2b. 確認 tkinter 可用（Homebrew Python 預設不含，需另裝 python-tk）──────
echo "🔍 檢查 tkinter（GUI 模組）..."
if ! "$PYTHON_BIN" -c "import tkinter" &>/dev/null; then
    echo "⚠️  Python 缺少 tkinter，自動安裝..."
    PY_VER=$("$PYTHON_BIN" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    ensure_homebrew
    if brew install "python-tk@$PY_VER" 2>/dev/null; then
        echo "✅ python-tk@$PY_VER 已安裝"
    elif brew install python-tk 2>/dev/null; then
        echo "✅ python-tk 已安裝"
    else
        echo "❌ python-tk 自動安裝失敗，請手動執行："
        echo "      brew install python-tk@$PY_VER"
        exit 1
    fi
    # 再確認
    if ! "$PYTHON_BIN" -c "import tkinter" &>/dev/null; then
        echo "❌ tkinter 安裝後仍無法載入，請重開終端機後再試。"
        exit 1
    fi
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

# 設定執行權限，並固定使用本次安裝檢查通過的 Python
cat > "$INSTALL_DIR/黑貓主程式/啟動黑貓工具.command" <<EOF
#!/bin/bash
cd "\$(dirname "\$0")"
"$PYTHON_BIN" app.py
EOF
chmod +x "$INSTALL_DIR/黑貓主程式/啟動黑貓工具.command"

# ── 6. 安裝 Python 套件 ───────────────────────────────────────────────────────
echo "📦 安裝 Python 套件..."
REQ_FILE="$INSTALL_DIR/黑貓主程式/requirements.txt"
if [[ -f "$REQ_FILE" ]]; then
    "$PYTHON_BIN" -m pip install --quiet --upgrade -r "$REQ_FILE"
else
    # fallback：requirements.txt 不在時硬編碼套件名
    "$PYTHON_BIN" -m pip install --quiet --upgrade pyyaml "pypdf>=4.0" "requests>=2.31"
fi
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
