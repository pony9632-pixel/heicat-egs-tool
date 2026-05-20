#!/bin/bash
# 黑貓 EGS 工具 — 一鍵發版腳本
# 用法：./release.sh 1.6.2 "版本說明（可省略）"
set -e

VERSION=$1
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

echo ""
echo "🎉 v$VERSION 發布完成！"
echo "   Release 頁面：https://github.com/pony9632-pixel/heicat-egs-tool/releases/tag/v$VERSION"
