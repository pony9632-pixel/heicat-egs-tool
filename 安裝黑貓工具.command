#!/bin/bash
# STUDIO A 黑貓宅急便工具 — 雙擊安裝
# 下載後雙擊即可，內部執行與 README 相同的 install.sh
INSTALL_URL="https://raw.githubusercontent.com/pony9632-pixel/heicat-egs-tool/main/install.sh"

clear
if curl -fsSL "$INSTALL_URL" | bash; then
    echo ""
    echo "安裝完成，可以關閉這個視窗。"
else
    echo ""
    echo "❌ 安裝失敗，請把這個畫面截圖傳給維護者。"
fi
echo "按 Enter 關閉視窗。"
read
