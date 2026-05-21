#!/bin/bash
# 黑貓宅急便工具 — 一鍵打包腳本
# 用法：packaging/build_dmg.sh 2.3.0
# 產出：~/Desktop/黑貓宅急便工具_v2.3.0.dmg
#       packaging/dist/黑貓宅急便工具.app.zip  ← 供 app 自動更新下載
set -euo pipefail

VERSION="${1:-}"
if [ -z "$VERSION" ]; then
    # 從 app.py 讀取版本號
    VERSION=$(grep '^VERSION' 黑貓主程式/app.py | head -1 | grep -o '"[^"]*"' | tr -d '"')
fi
echo "📦 打包版本：$VERSION"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── 1. 確認 PyInstaller ────────────────────────────────────────────────────────
if ! command -v pyinstaller &>/dev/null; then
    echo "❌ 找不到 pyinstaller，請先安裝：pip install pyinstaller"
    exit 1
fi

# ── 2. 產生 icon.icns（若不存在）─────────────────────────────────────────────
ICON="$SCRIPT_DIR/icon.icns"
if [ ! -f "$ICON" ]; then
    echo "🎨 產生 icon.icns..."
    if python3 -c "import PIL" &>/dev/null; then
        python3 "$SCRIPT_DIR/create_icon.py"
    else
        echo "⚠️  Pillow 未安裝，嘗試安裝中..."
        pip3 install --quiet Pillow
        python3 "$SCRIPT_DIR/create_icon.py"
    fi
fi

# ── 3. PyInstaller 打包 ────────────────────────────────────────────────────────
echo "⚙️  執行 PyInstaller..."
cd "$REPO_ROOT"
pyinstaller 黑貓宅急便工具.spec --clean --noconfirm
APP_BUNDLE="$REPO_ROOT/dist/黑貓宅急便工具.app"
if [ ! -d "$APP_BUNDLE" ]; then
    echo "❌ 打包失敗：找不到 dist/黑貓宅急便工具.app"
    exit 1
fi
echo "✓ .app 產生完成"

# ── 3b. 清除 resource fork / 重新 ad-hoc 簽署 ────────────────────────────────
# macOS 的 com.apple.provenance 等 xattr 會讓 codesign 失敗，需逐檔清除
echo "🔏 清除 xattr 並重新簽署..."
find "$APP_BUNDLE" -type f | xargs xattr -c 2>/dev/null || true
find "$APP_BUNDLE" -type d | xargs xattr -c 2>/dev/null || true
codesign -s - --force "$APP_BUNDLE" 2>&1 || true
echo "✓ 簽署完成（ad-hoc）"

# ── 4. 更新 spec 裡的版本號 ───────────────────────────────────────────────────
sed -i '' \
    "s/\"CFBundleShortVersionString\": \".*\"/\"CFBundleShortVersionString\": \"$VERSION\"/" \
    "$REPO_ROOT/黑貓宅急便工具.spec"
sed -i '' \
    "s/\"CFBundleVersion\": \".*\"/\"CFBundleVersion\": \"$VERSION\"/" \
    "$REPO_ROOT/黑貓宅急便工具.spec"

# ── 5. 建立 DMG ───────────────────────────────────────────────────────────────
echo "💿 建立 DMG..."
DMG_NAME="黑貓宅急便工具_v${VERSION}.dmg"
STAGING="$REPO_ROOT/packaging/dmg_staging"
DMG_TMP="$REPO_ROOT/packaging/dist/${DMG_NAME}.tmp.dmg"
DMG_OUT="$REPO_ROOT/packaging/dist/${DMG_NAME}"

mkdir -p "$REPO_ROOT/packaging/dist"
rm -f "$DMG_OUT" "$DMG_TMP"
rm -rf "$STAGING"
mkdir -p "$STAGING"

# 複製 .app 到 staging
cp -R "$APP_BUNDLE" "$STAGING/"
# 建立 Applications 捷徑
ln -s /Applications "$STAGING/Applications"

# 估算大小（MB），多加 10MB 緩衝
APP_SIZE_MB=$(du -sm "$APP_BUNDLE" | awk '{print $1}')
DMG_SIZE_MB=$((APP_SIZE_MB + 20))

hdiutil create -srcfolder "$STAGING" \
    -volname "黑貓宅急便工具" \
    -fs HFS+ \
    -fsargs "-c c=64,a=16,b=16" \
    -format UDRW \
    -size "${DMG_SIZE_MB}m" \
    "$DMG_TMP"

# 轉成壓縮唯讀 DMG
hdiutil convert "$DMG_TMP" -format UDZO -imagekey zlib-level=9 -o "$DMG_OUT"
rm -f "$DMG_TMP"
rm -rf "$STAGING"

echo "✓ DMG：$DMG_OUT"

# ── 6. 產生 .app.zip（供 app 自動更新）────────────────────────────────────────
echo "🗜  產生 app.zip..."
APP_ZIP="$REPO_ROOT/packaging/dist/黑貓宅急便工具.app.zip"
cd "$REPO_ROOT/dist"
zip -r -q "$APP_ZIP" "黑貓宅急便工具.app"
cd "$REPO_ROOT"
echo "✓ app.zip：$APP_ZIP"

# ── 7. 複製 DMG 到桌面 ────────────────────────────────────────────────────────
cp "$DMG_OUT" "$HOME/Desktop/$DMG_NAME"

echo ""
echo "🎉 打包完成！"
echo "   DMG（安裝用）：~/Desktop/$DMG_NAME"
echo "   app.zip（更新用）：$APP_ZIP"
echo ""
echo "發版時請執行："
echo "   gh release upload v$VERSION ~/Desktop/$DMG_NAME"
echo "   gh release upload v$VERSION $APP_ZIP"
