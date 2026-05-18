#!/bin/bash
# STUDIO A 黑貓宅急便工具 — 一鍵安裝腳本
# 使用方式：curl -fsSL https://raw.githubusercontent.com/pony9632-pixel/heicat-egs-tool/main/install.sh | bash

set -euo pipefail

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

# ── 2. 確認 Python 3 ─────────────────────────────────────────────────────────
echo "🔍 檢查 Python 3..."
if ! command -v python3 &>/dev/null; then
    echo ""
    echo "❌ 找不到 Python 3，請先完成以下步驟再重新執行安裝："
    echo ""
    echo "   1. 前往 https://www.python.org/downloads/"
    echo "   2. 下載並安裝 Python 3（一路按 Continue / Install 即可）"
    echo "   3. 安裝完成後，回到終端機重新貼上安裝指令"
    echo ""
    open "https://www.python.org/downloads/" 2>/dev/null || true
    exit 1
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

# ── 4. 下載 ──────────────────────────────────────────────────────────────────
echo "📥 下載中（請稍候）..."
TMP_ZIP=$(mktemp /tmp/heicat_XXXXXX.zip)
curl -fsSL -L "$ZIPBALL_URL" -o "$TMP_ZIP"
echo "✅ 下載完成"
echo ""

# ── 5. 解壓縮並安裝 ───────────────────────────────────────────────────────────
echo "📂 安裝中..."
TMP_DIR=$(mktemp -d /tmp/heicat_dir_XXXXXX)
unzip -q "$TMP_ZIP" -d "$TMP_DIR"

# GitHub zip 會多一層前綴資料夾（如 pony9632-pixel-heicat-egs-tool-abc1234/）
EXTRACTED_DIR=$(ls -d "$TMP_DIR"/*/ | head -1)

if [[ -d "$INSTALL_DIR" ]]; then
    echo "⚠️  偵測到已安裝的舊版本，更新程式中（你的設定與通訊錄不受影響）..."
    rm -rf "$INSTALL_DIR/黑貓主程式"
    cp -r "${EXTRACTED_DIR}黑貓主程式" "$INSTALL_DIR/"
else
    mkdir -p "$INSTALL_DIR"
    cp -r "${EXTRACTED_DIR}黑貓主程式" "$INSTALL_DIR/"
fi

# 設定執行權限
chmod +x "$INSTALL_DIR/黑貓主程式/啟動黑貓工具.command"
echo "✅ 程式已安裝至：$INSTALL_DIR"
echo ""

# ── 6. 安裝 Python 套件 ───────────────────────────────────────────────────────
echo "📦 安裝 Python 套件..."
python3 -m pip install --quiet --upgrade pyyaml "pypdf>=4.0" "requests>=2.31"
echo "✅ 套件安裝完成"
echo ""

# ── 7. 清理暫存 ───────────────────────────────────────────────────────────────
rm -f "$TMP_ZIP"
rm -rf "$TMP_DIR"

# ── 8. 完成 ──────────────────────────────────────────────────────────────────
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
