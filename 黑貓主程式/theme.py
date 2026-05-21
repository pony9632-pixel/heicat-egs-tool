"""v3 Cool Glass 色彩 token — LIGHT / DARK 兩套，app.py 直接 import 使用。"""

LIGHT = {
    # 背景層次
    "PAPER":   "#EEF1F5",
    "PAPER2":  "#E5E9EF",
    "CARD":    "#FFFFFF",
    "RAIL":    "#E9EDF3",
    "RAIL2":   "#DBE0E8",
    # 文字
    "INK":     "#15171C",
    "INK2":    "#3A4150",
    "INK3":    "#5F6878",
    "MUTED":   "#8B94A4",
    "MUTED2":  "#B8BFC9",
    # 分隔線
    "HAIR":    "#DCE1EA",
    "HAIR2":   "#E7EBF2",
    "HAIR3":   "#F1F4F8",
    # 品牌（鎖定）
    "ACCENT":  "#D8352B",
    "ACCENT2": "#FBE7E5",
    # 語意色
    "OK":      "#1F7A52",
    "OK2":     "#DCEFE3",
    "WARN":    "#9B6919",
    "WARN2":   "#FBEED9",
    "ERR":     "#B5342A",
    "ERR2":    "#FBE0DD",
    "INFO":    "#2A6FD4",
    "INFO2":   "#DEE9F8",
    # Input
    "INPUT_BG":     "#F4F6FA",
    "INPUT_BORDER": "#DCE1EA",
}

DARK = {
    "PAPER":   "#16181C",
    "PAPER2":  "#1E2127",
    "CARD":    "#252830",
    "RAIL":    "#1A1D22",
    "RAIL2":   "#20242B",
    "INK":     "#EEF1F5",
    "INK2":    "#C8CDD8",
    "INK3":    "#8B94A4",
    "MUTED":   "#5F6878",
    "MUTED2":  "#3A4150",
    "HAIR":    "#363A42",
    "HAIR2":   "#2E3239",
    "HAIR3":   "#262A31",
    "ACCENT":  "#E8453B",
    "ACCENT2": "#3D1E1C",
    "OK":      "#2A9968",
    "OK2":     "#1A3D2E",
    "WARN":    "#C4842A",
    "WARN2":   "#3D2E12",
    "ERR":     "#E8453B",
    "ERR2":    "#3D1E1C",
    "INFO":    "#4A8FE8",
    "INFO2":   "#1A2E4A",
    "INPUT_BG":     "#1E2127",
    "INPUT_BORDER": "#363A42",
}

current = LIGHT
