#!/bin/bash
# 黑貓 EGS 工具 — 一鍵發版腳本
# 用法：./release.sh 1.6.2 "版本說明（可省略）"
set -e

VERSION=${1#v}   # 去掉開頭的 v，統一存純數字版號 x.y.z
NOTES=${2:-""}

if [ -z "$VERSION" ]; then
  echo "❌ 請提供版本號，例如：./release.sh 1.6.2"
  exit 1
fi

APP_PY="黑貓主程式/app.py"

# 1. 確認 git 工作目錄乾淨（排除 config.yaml / contacts.json）
DIRTY=$(git status --porcelain | grep -v "config.yaml" | grep -v "contacts.json" | grep -v "^??" || true)
if [ -n "$DIRTY" ]; then
  echo "❌ 工作目錄有未提交的修改，請先 commit 或 stash："
  echo "$DIRTY"
  exit 1
fi

# 2. 更新 app.py 裡的 VERSION 字串
sed -i '' "s/^VERSION     = \".*\"/VERSION     = \"$VERSION\"/" "$APP_PY"
echo "✓ VERSION → $VERSION"

# 3. 確認語法正確
python3 -c "import ast; ast.parse(open('$APP_PY').read())" || { echo "❌ 語法錯誤，中止"; exit 1; }
echo "✓ 語法檢查通過"

# 4. Commit + Push
git add "$APP_PY"
git commit -m "release: v$VERSION"
git push origin HEAD:main
echo "✓ 推送完成"

# 5. 建立 GitHub Release
if [ -n "$NOTES" ]; then
  gh release create "v$VERSION" --title "v$VERSION — $NOTES" --notes "$NOTES"
else
  gh release create "v$VERSION" --title "v$VERSION" --generate-notes
fi

# 6. 若有打包好的 .app zip（dist/*.zip），連同 SHA-256 一起上傳，
#    讓自動更新可以驗證下載檔完整性（找不到 .sha256 的舊版 release 會略過驗證）
for ZIP in dist/*.zip; do
  [ -e "$ZIP" ] || continue
  shasum -a 256 "$ZIP" | awk '{print $1}' > "$ZIP.sha256"
  gh release upload "v$VERSION" "$ZIP" "$ZIP.sha256"
  echo "✓ 已上傳 $(basename "$ZIP") 與 SHA-256"
done

echo ""
echo "🎉 v$VERSION 發布完成！"
echo "   Release 頁面：https://github.com/pony9632-pixel/heicat-egs-tool/releases/tag/v$VERSION"
