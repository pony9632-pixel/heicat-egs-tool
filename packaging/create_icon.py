#!/usr/bin/env python3
"""
產生 icon.icns
執行：python3 packaging/create_icon.py [來源圖片.png]
需要：pip install Pillow

若未指定來源圖片，預設使用 packaging/ 旁的 STUDIOA_macOS_icon_1024.png。
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("請先安裝 Pillow：pip install Pillow")
    sys.exit(1)

OUT_DIR = Path(__file__).parent
ICNS    = OUT_DIR / "icon.icns"
SIZES   = [16, 32, 64, 128, 256, 512, 1024]

# 預設來源圖片（放在 packaging/ 旁即可）
DEFAULT_SRC = OUT_DIR / "STUDIOA_macOS_icon_1024.png"


def main():
    src_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SRC
    if not src_path.exists():
        print(f"❌ 找不到來源圖片：{src_path}")
        print("   用法：python3 packaging/create_icon.py <圖片路徑.png>")
        sys.exit(1)

    img = Image.open(src_path).convert("RGBA")
    print(f"來源：{src_path}（{img.size[0]}×{img.size[1]}）")

    iconset = Path(tempfile.mkdtemp()) / "icon.iconset"
    iconset.mkdir()

    for s in SIZES:
        resized = img.resize((s, s), Image.LANCZOS)
        resized.save(iconset / f"icon_{s}x{s}.png")
        if s <= 512:
            resized.resize((s * 2, s * 2), Image.LANCZOS).save(
                iconset / f"icon_{s}x{s}@2x.png"
            )

    result = subprocess.run(
        ["iconutil", "-c", "icns", str(iconset), "-o", str(ICNS)],
        capture_output=True, text=True,
    )
    shutil.rmtree(iconset.parent)

    if result.returncode != 0:
        print("iconutil 失敗：", result.stderr)
        sys.exit(1)

    print(f"✓ 已產生 {ICNS}（{ICNS.stat().st_size // 1024} KB）")


if __name__ == "__main__":
    main()
