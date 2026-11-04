#!/bin/bash
# STUDIO A 黑貓宅急便工具 — 一鍵安裝腳本
# 使用方式：curl -fsSL https://raw.githubusercontent.com/pony9632-pixel/heicat-egs-tool/main/install.sh | bash

set -euo pipefail

TMP_ZIP=""
TMP_DIR=""
TMP_PKG_DIR=""
cleanup() {
    # 用 if 而非 && 短路：變數為空時 && 會回傳 1，配合 set -e 讓整個安裝以失敗狀態結束
    if [[ -n "$TMP_ZIP" ]]; then rm -f "$TMP_ZIP"; fi
    if [[ -n "$TMP_DIR" ]]; then rm -rf "$TMP_DIR"; fi
    if [[ -n "$TMP_PKG_DIR" ]]; then rm -rf "$TMP_PKG_DIR"; fi
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

# ── 2. 確認 Python 3.10 以上（含 tkinter）；沒有就自動下載官方安裝檔 ──────────
PYTHON_PKG_VERSION="3.14.10"
PYTHON_PKG_URL="https://www.python.org/ftp/python/$PYTHON_PKG_VERSION/python-$PYTHON_PKG_VERSION-macos11.pkg"

python_ok() {
    "$1" -c 'import sys, tkinter; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null
}

# 依序找：python.org 官方版（新到舊）→ Homebrew → PATH 上的 python3。
# /usr/bin/python3 是 Xcode 的殼，沒裝 Command Line Tools 時一執行就跳安裝視窗，
# 所以放最後、且只在已裝 CLT 時才試。
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

echo "🔍 檢查 Python 3（需 3.10 以上並含 tkinter）..."
PYTHON_BIN="$(find_python || true)"
if [[ -z "$PYTHON_BIN" ]]; then
    echo "⚠️  找不到符合的 Python，自動下載官方安裝檔 Python ${PYTHON_PKG_VERSION}（約 70 MB）..."
    TMP_PKG_DIR="$(mktemp -d -t heicat_py)"
    PKG="$TMP_PKG_DIR/python-$PYTHON_PKG_VERSION.pkg"
    curl -fL --progress-bar -o "$PKG" "$PYTHON_PKG_URL"
    if ! pkgutil --check-signature "$PKG" 2>/dev/null | grep -q "Developer ID Installer: Python Software Foundation"; then
        echo "❌ 下載的 Python 安裝檔簽章驗證失敗，為安全起見中止。請手動到 https://www.python.org/downloads/ 安裝。"
        exit 1
    fi
    echo ""
    echo "📦 即將開啟 Python 安裝程式，請依畫面一路按「繼續」→「安裝」（會要求輸入電腦密碼），"
    echo "   安裝完成按「關閉」後，這裡會自動接著安裝黑貓工具。"
    echo ""
    open -W "$PKG"
    PYTHON_BIN="$(find_python || true)"
    if [[ -z "$PYTHON_BIN" ]]; then
        echo ""
        echo "❌ Python 安裝未完成或被取消。請再執行一次安裝程式，或手動安裝：https://www.python.org/downloads/"
        exit 1
    fi
    # 官方版 Python 的 CA 憑證要另外裝，否則 urllib 驗證 HTTPS 會失敗
    CERT_CMD="/Applications/Python ${PYTHON_PKG_VERSION%.*}/Install Certificates.command"
    if [[ -x "$CERT_CMD" ]]; then
        "$CERT_CMD" >/dev/null 2>&1 || true
    fi
fi
# 變數一律用 ${} 包住：macOS 內建 bash 3.2 在 zh_TW.UTF-8 locale 下，
# $VAR 後面直接接全形字會把該字的第一個 byte 併進變數名，變成 unbound variable
echo "✅ $("${PYTHON_BIN}" --version) 已就緒（${PYTHON_BIN}）"
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
import urllib.request, urllib.error, zipfile, os, shutil, ssl, sys, tempfile

zipball_url = '$ZIPBALL_URL'
install_dir = '$INSTALL_DIR'

# 用 tempfile 產生不可預測的暫存路徑，避免 /tmp 固定檔名遭預先佔用或符號連結攻擊
_fd, tmp_zip = tempfile.mkstemp(prefix='heicat_install_', suffix='.zip')
os.close(_fd)
tmp_dir = tempfile.mkdtemp(prefix='heicat_dir_')

# 下載：先用完整憑證驗證；bootstrap 階段沒有 certifi，部分 Python
# 安裝缺 CA 憑證會驗證失敗，此時才退回不驗證並警告
req = urllib.request.Request(zipball_url, headers={'User-Agent': 'heicat-install'})
try:
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, context=ctx, timeout=60) as r, open(tmp_zip, 'wb') as f:
        shutil.copyfileobj(r, f)
except urllib.error.URLError as e:
    if not isinstance(getattr(e, 'reason', None), ssl.SSLCertVerificationError):
        raise
    print('⚠️  此 Python 缺少 CA 憑證，改用不驗證連線下載（安裝後程式會改用 certifi 驗證）', file=sys.stderr)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(zipball_url, headers={'User-Agent': 'heicat-install'})
    with urllib.request.urlopen(req, context=ctx, timeout=60) as r, open(tmp_zip, 'wb') as f:
        shutil.copyfileobj(r, f)

# 解壓（tmp_dir 已由 mkdtemp 建立）
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
# --clear：舊 venv 若是從別台 Mac 複製來的，符號連結已斷，不清空會重建失敗
"$PYTHON_BIN" -m venv --clear "$VENV_DIR"
VENV_PYTHON="$VENV_DIR/bin/python3"
if ! "$VENV_PYTHON" -m pip --version &>/dev/null; then
    echo "🔧 venv 內沒有 pip，補裝中..."
    "$VENV_PYTHON" -m ensurepip --upgrade
fi

REQ_FILE="$INSTALL_DIR/黑貓主程式/requirements.txt"
if [[ -f "$REQ_FILE" ]]; then
    "$VENV_PYTHON" -m pip install --quiet --upgrade -r "$REQ_FILE"
else
    "$VENV_PYTHON" -m pip install --quiet --upgrade pyyaml "pypdf>=4.0" "requests>=2.31" customtkinter
fi
echo "✅ 套件安裝完成"

# 啟動腳本直接用 zip 內的版本（會自行偵測並重建 venv），只需補上執行權限
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
