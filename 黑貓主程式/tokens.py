"""v3 design tokens — 圓角、間距、字體。"""
import platform

# 圓角
R_PILL  = 999
R_CARD  = 14
R_INPUT = 8
R_NAV   = 10
R_CHIP  = 999
R_AVATAR_SM = 7
R_AVATAR_LG = 11

# 間距
S_XS = 4
S_SM = 8
S_MD = 12
S_LG = 16
S_XL = 20
S_2XL = 28

# 字體
_IS_MAC = platform.system() == "Darwin"
FONT_FAMILY = "Helvetica Neue" if _IS_MAC else "Helvetica"
MONO_FAMILY = "Menlo" if _IS_MAC else "Courier"

# 元件尺寸
BTN_H = 36
NAV_W = 200
TOPBAR_H = 54
