#!/usr/bin/env python3
"""
黑貓宅急便 企業建單工具 — Tidewater
執行：python3 app.py
"""

from __future__ import annotations

import base64
import csv
import io
import json
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as _tkfont, messagebox, scrolledtext, ttk
import customtkinter as ctk

import yaml
from theme import LIGHT as T
import tokens as TOK

from api_client import SudaClient, save_pdf, default_shipment_date, default_delivery_date, _skip_sunday
from web_client import TakkyubinWebClient
from order import generate_template, load_orders, create_orders, TEMPLATE_FIELDS, _csv_row_to_api_order

# ─── 資料庫路徑系統 ──────────────────────────────────────────────────────────
# .datapath  放在程式旁（不同步）：只記錄「資料庫資料夾在哪」
# 黑貓資料庫/ 可以放在雲端硬碟（iCloud / Dropbox 等），跨裝置共用

_DATAPATH_FILE    = Path(__file__).parent / ".datapath"
_DEFAULT_DATA_DIR = (
    Path.home() / "Library" / "Application Support" / "黑貓宅急便工具"
    if getattr(sys, "frozen", False)
    else Path.home() / "黑貓資料庫"
)
_APP_DIR          = Path(__file__).parent   # 程式目錄（舊檔案位置）

def get_data_dir() -> Path:
    """Return the current 黑貓資料庫 folder path."""
    try:
        p = _DATAPATH_FILE.read_text(encoding="utf-8").strip()
        if p:
            return Path(p)
    except Exception:
        pass
    return _DEFAULT_DATA_DIR

def set_data_dir(new_path: str):
    """Save a new data folder path and create it if needed."""
    Path(new_path).mkdir(parents=True, exist_ok=True)
    _DATAPATH_FILE.write_text(new_path, encoding="utf-8")

def _ensure_data_dir():
    """On first run: create the data folder and migrate old files next to the app."""
    data_dir = get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    # migrate files that used to sit next to the app
    old_files = [
        "config.yaml", "contacts.json", "default_contacts.json",
        "tracking.json", "deleted_obts.json", "epb_transfer_log.json",
    ]
    for name in old_files:
        old = _APP_DIR / name
        new = data_dir / name
        if old.exists() and not new.exists():
            old.rename(new)

# paths — all relative to get_data_dir(), evaluated at call time
def _cfg_path()              -> Path: return get_data_dir() / "config.yaml"
def _contacts_path()         -> Path: return get_data_dir() / "contacts.json"
def _default_contacts_path() -> Path:
    """預設通訊錄隨 app 出貨，不放 data dir，確保每次更新都覆蓋到最新版。"""
    if getattr(sys, "frozen", False):          # PyInstaller 打包版
        return Path(sys.executable).parent / "default_contacts.json"
    return Path(__file__).parent / "default_contacts.json"  # 開發 / 源碼模式
def _tracking_path()         -> Path: return get_data_dir() / "tracking.json"
def _deleted_path()          -> Path: return get_data_dir() / "deleted_obts.json"
def _epb_log_path()          -> Path: return get_data_dir() / "epb_transfer_log.json"

_DEFAULT_OUTPUT_DIR = str(Path.home() / "黑貓單號")

def get_output_dir() -> str:
    """Return the PDF output directory, preferring the user-configured path."""
    try:
        cfg = load_cfg()
        p = (cfg.get("output_dir") or "").strip()
        if p:
            return p
    except Exception:
        pass
    return _DEFAULT_OUTPUT_DIR

def _append_build_log(msg: str):
    pass


VERSION     = "2.4.6"
GITHUB_REPO = "pony9632-pixel/heicat-egs-tool"

# ─── Cool Glass palette (Tahoe-inspired) ────────────────────────────────────
PAPER   = "#EEF1F5"   # 主背景（冷灰藍）
PAPER2  = "#E5E9EF"   # 次背景
CARD    = "#FFFFFF"   # 卡片
INK     = "#15171C"   # 主文字（品牌鎖定）
INK2    = "#3A4150"   # 次要文字
INK3    = "#5F6878"   # 輔助文字
MUTED   = "#8B94A4"   # 弱化／提示
MUTED2  = "#B8BFC9"
HAIR    = "#DCE1EA"   # 主分隔線
HAIR2   = "#E7EBF2"   # 次分隔線
HAIR3   = "#F1F4F8"   # 極淡
ACCENT  = "#D8352B"   # STUDIO A 品牌紅（鎖定）
ACCENT2 = "#FBE7E5"   # 淺紅底
OK      = "#1F7A52"
OK2     = "#DCEFE3"
WARN    = "#9B6919"
WARN2   = "#FBEED9"
ERR     = "#B5342A"
ERR2    = "#FBE0DD"
INFO    = "#2A6FD4"
INFO2   = "#DEE9F8"
RAIL    = "#E9EDF3"   # Sidebar 底
RAIL2   = "#DBE0E8"   # Sidebar hover
INPUT_BG     = "#F4F6FA"   # Field / Select 背景
INPUT_BORDER = "#DCE1EA"   # Field border
SUMMARY_BG   = "#F4F6FA"   # strip / chip 底色
SEG_BG       = "#E2E7EE"   # Segment 容器底色

import platform
_IS_MAC = platform.system() == "Darwin"
FONT_FAMILY = "Helvetica Neue" if _IS_MAC else "Helvetica"
MONO_FAMILY = "Menlo" if _IS_MAC else "Courier"

# 字體縮放：從 config.yaml 讀 font_scale，預設 1.0；變更後重啟生效
FONT_SCALE_OPTIONS = {"小": 0.85, "標準": 1.0, "大": 1.15, "特大": 1.30}

def _load_font_scale():
    try:
        p = _cfg_path()
        if not p.exists():
            return 1.0
        with open(p, encoding="utf-8") as _f:
            v = (yaml.safe_load(_f) or {}).get("font_scale", 1.0)
        return max(0.7, min(2.0, float(v or 1.0)))
    except Exception:
        return 1.0

_FS = _load_font_scale()
def _sz(n: int) -> int:
    return max(7, int(round(n * _FS)))

F_NORM   = (FONT_FAMILY, _sz(13))
F_SMALL  = (FONT_FAMILY, _sz(12))
F_TINY   = (FONT_FAMILY, _sz(11))
F_BOLD   = (FONT_FAMILY, _sz(13), "bold")
F_TITLE  = (FONT_FAMILY, _sz(18), "bold")
F_KICKER = (FONT_FAMILY, _sz(11), "bold")
F_LABEL  = (FONT_FAMILY, _sz(11))
F_MONO   = (MONO_FAMILY, _sz(11))
F_NAV    = (FONT_FAMILY, _sz(13))


SPEC_OPTIONS   = {"0001  60 cm": "0001", "0002  90 cm": "0002", "0003 120 cm": "0003", "0004 150 cm": "0004"}
THERMO_OPTIONS = {"0001 常溫": "0001", "0002 冷藏": "0002", "0003 冷凍": "0003"}
DTIME_OPTIONS  = {"01 不指定": "01", "02 上午 08–12": "02", "03 下午 12–17": "03", "04 晚上 17–20": "04"}
PRODUCT_TYPE_OPTIONS = {
    "0001 一般食品":       "0001",
    "0002 名特產/甜點":    "0002",
    "0003 酒/油/醋/醬":    "0003",
    "0004 穀物蔬果":       "0004",
    "0005 水產/肉品":      "0005",
    "0006 3C":             "0006",
    "0007 家電":           "0007",
    "0008 服飾配件":       "0008",
    "0009 生活用品":       "0009",
    "0010 美容彩妝":       "0010",
    "0011 保健食品":       "0011",
    "0012 醫療相關用品":   "0012",
    "0013 寵物用品飼料":   "0013",
    "0014 印刷品":         "0014",
    "0015 其他":           "0015",
}
FIXED_PRODUCT_TYPE_LABEL = "0006 3C"
FIXED_PRODUCT_TYPE_ID    = "0006"


# ─── persistence helpers ─────────────────────────────────────────────────────

def load_cfg() -> dict:
    p = _cfg_path()
    if p.exists():
        with open(p, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}

def save_cfg(cfg: dict):
    p = _cfg_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)


# ─── EPB feature gate ───────────────────────────────────────────────────────
# 進階功能（EPB 調撥）門檻：授權門市用隱藏快捷鍵 ⌘+⌥+E 輸入密碼解鎖。
# 此 hash 為 SHA-256(密碼)；公開 repo 的軟鎖、防隨手翻看而已。
_EPB_PASSWORD_HASH = "1b0d96aeffd87463093049c2063a65e03154712d8438ac4dde6f5749cd811046"


def _is_epb_unlocked() -> bool:
    return bool(load_cfg().get("epb_unlocked", False))


def _try_unlock_epb(password: str) -> bool:
    import hashlib
    if not password:
        return False
    if hashlib.sha256(password.encode("utf-8")).hexdigest() == _EPB_PASSWORD_HASH:
        cfg = load_cfg()
        cfg["epb_unlocked"] = True
        save_cfg(cfg)
        return True
    return False


def _lock_epb():
    cfg = load_cfg()
    cfg["epb_unlocked"] = False
    save_cfg(cfg)


def load_contacts() -> list[dict]:
    """回傳 default_contacts（門市預設）+ contacts（使用者新增）合併清單。"""
    result: list[dict] = []
    dp = _default_contacts_path()
    if dp.exists():
        try:
            with open(dp, encoding="utf-8") as f:
                result.extend(json.load(f))
        except Exception:
            pass
    p = _contacts_path()
    if p.exists():
        try:
            with open(p, encoding="utf-8") as f:
                result.extend(json.load(f))
        except Exception:
            pass
    return result

def load_custom_contacts() -> list[dict]:
    """只回傳使用者自行新增的聯絡人（contacts.json）。"""
    p = _contacts_path()
    if p.exists():
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_contacts(contacts: list[dict]):
    """只儲存使用者自行新增的聯絡人（不覆蓋 default_contacts）。"""
    p = _contacts_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(contacts, f, ensure_ascii=False, indent=2)

def load_tracking() -> list[dict]:
    p = _tracking_path()
    if p.exists():
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return []

def save_tracking(records: list[dict]):
    p = _tracking_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

def load_deleted_obts() -> set:
    p = _deleted_path()
    if p.exists():
        with open(p, encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def add_deleted_obt(obt: str):
    obts = load_deleted_obts()
    obts.add(obt)
    p = _deleted_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(sorted(obts), f, ensure_ascii=False, indent=2)


def _cleanup_epb_log_for_obt(obt: str) -> int:
    """從 epb_transfer_log.json 移除指定 OBT 對應的 entry，回傳移除筆數。"""
    if not obt:
        return 0
    path = _epb_log_path()
    if not path.exists():
        return 0
    try:
        log = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    keys = [k for k, v in (log or {}).items() if v.get("obt_number") == obt]
    if not keys:
        return 0
    for k in keys:
        del log[k]
    path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(keys)


def _normalize_created_at(ca: str) -> str:
    """把 created_at 標準化為 ISO 風格字串，方便排序與比較。
    支援格式：
      - ISO  '2026-05-22T00:25:30'  → 原樣
      - 斜線 '2026/05/22'            → '2026-05-22'
      - 數字 '20260522'              → '2026-05-22'
    """
    if not ca:
        return ""
    if len(ca) >= 10 and ca[4] == "/" and ca[7] == "/":
        return ca[:4] + "-" + ca[5:7] + "-" + ca[8:]
    if len(ca) >= 8 and ca[:8].isdigit():
        return f"{ca[:4]}-{ca[4:6]}-{ca[6:8]}" + ca[8:]
    return ca


def append_tracking(obt_number: str, recipient_name: str, order_id: str,
                    sender_name: str = ""):
    """Add a new tracking record; auto-prune records older than 14 days.

    sender_name 為本地寄件人名稱（用 cfg["sender"]["name"]），記下後
    `_sync_from_web` 不會用碼頭回傳的公司戶名覆蓋掉。
    """
    import datetime
    records = load_tracking()
    records.append({
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "obt_number": obt_number,
        "recipient_name": recipient_name,
        "order_id": order_id,
        "sender_name": sender_name,
    })
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=14)).isoformat()
    records = [r for r in records
               if _normalize_created_at(r.get("created_at", "")) >= cutoff]
    save_tracking(records)

def make_client(cfg: dict) -> SudaClient:
    return SudaClient(
        customer_id=str(cfg.get("username", "")),
        customer_token=cfg.get("api_token", ""),
    )


# ─── primitives ──────────────────────────────────────────────────────────────

class TwButton(ctk.CTkButton):
    """Pill button (CustomTkinter). variant: primary | default | ghost | danger | accent"""

    _VCFG: dict = {}  # populated after color constants are defined (see below)

    def __init__(self, master, text, command=None, variant="default", **kw):
        kw.pop("bg", None)
        kw.pop("width", None)
        self.variant = variant
        cfg = dict(self._VCFG.get(variant, self._VCFG["default"]))
        cfg["text_color_disabled"] = MUTED
        super().__init__(master, text=text, command=command,
                         corner_radius=999,
                         font=(FONT_FAMILY, _sz(13), "bold"),
                         height=36,
                         **cfg, **kw)

    def set_text(self, t):
        self.configure(text=t)

    def set_enabled(self, enabled: bool):
        self.configure(state="normal" if enabled else "disabled")


def _frame_bg(widget):
    if isinstance(widget, ctk.CTkBaseClass):
        col = widget.cget("fg_color")
        return col[0] if isinstance(col, (list, tuple)) else col
    try:
        return widget.cget("bg")
    except tk.TclError:
        try:
            return widget.cget("background")
        except tk.TclError:
            return PAPER


# Populate TwButton variant config after color constants are defined
TwButton._VCFG = {
    "primary": dict(fg_color=INK,     hover_color="#2A3142",  text_color="#FFFFFF", border_width=0),
    "ghost":   dict(fg_color="transparent", hover_color=RAIL, text_color=INK2,      border_width=0),
    "danger":  dict(fg_color=CARD,    hover_color=ERR2,       text_color=ERR,       border_color="#F2D6D3", border_width=1),
    "accent":  dict(fg_color=ACCENT2, hover_color="#F5D3D0",  text_color=ACCENT,    border_width=0),
    "default": dict(fg_color=CARD,    hover_color="#F4F6FA",  text_color=INK,       border_color=HAIR,      border_width=1),
}


class Card(ctk.CTkFrame):
    """White card with true r=14 rounded corners and hairline border (CTkFrame)."""
    def __init__(self, master, padding=20, **kw):
        for _k in ("highlightthickness", "highlightbackground", "relief", "bd", "bg"):
            kw.pop(_k, None)
        super().__init__(master,
                         fg_color=CARD,
                         corner_radius=16,
                         border_width=1,
                         border_color=HAIR,
                         **kw)
        self.inner = self
        self._pad = padding
        self.body = tk.Frame(self, bg=CARD)
        self.body.pack(fill="both", expand=True, padx=padding, pady=padding)


class Segment(tk.Frame):
    """Pill-style single-select segmented control.

    Selected pill = white (CARD) floating on SEG_BG container.
    """

    def __init__(self, parent, options: list, selected: str = "",
                 on_change=None, height: int = 30, button_width=None, **kw):
        bg = _frame_bg(parent)
        super().__init__(parent, bg=bg, **kw)
        self._opts = list(options)
        self._val = selected if selected in options else ""
        self._on_change = on_change
        self._btns: dict = {}
        container_radius = min(12, max(8, height // 2))
        button_radius = min(12, max(8, height // 2))

        self._container = ctk.CTkFrame(
            self, fg_color=SEG_BG, corner_radius=container_radius,
            border_width=1, border_color=HAIR,
        )
        self._container.pack()

        for opt in options:
            btn_kw = {}
            if button_width is not None:
                btn_kw["width"] = button_width
            btn = ctk.CTkButton(
                self._container, text=opt,
                font=(FONT_FAMILY, _sz(12), "normal"),
                fg_color=SEG_BG, hover_color="#D8DDE5",
                text_color=INK3, border_width=0,
                corner_radius=button_radius, height=height,
                command=lambda o=opt: self._select(o),
                **btn_kw,
            )
            btn.pack(side="left", padx=3, pady=3)
            self._btns[opt] = btn

        self._refresh()

    def _select(self, opt: str):
        self._val = opt
        self._refresh()
        if self._on_change:
            self._on_change(opt)

    def _refresh(self):
        for opt, btn in self._btns.items():
            sel = (opt == self._val)
            btn.configure(
                fg_color=CARD if sel else SEG_BG,
                text_color=INK if sel else INK3,
                font=(FONT_FAMILY, _sz(12), "bold" if sel else "normal"),
                border_width=1 if sel else 0,
                border_color=HAIR,
            )

    def get(self) -> str:
        return self._val

    def set(self, val: str):
        self._val = val if val in self._btns else ""
        self._refresh()


class FieldEntry(tk.Frame):
    """Entry with INPUT_BG + ACCENT focus double-ring. No layout shift.

    Rest:  1px INPUT_BORDER + invisible 3px glow space
    Focus: 1px ACCENT ring  + visible  3px ACCENT2 outer glow
    """

    _FORWARD_EVENTS = frozenset({
        "<FocusIn>", "<FocusOut>", "<Escape>", "<Return>",
        "<Key>", "<KeyPress>", "<KeyRelease>",
    })

    def __init__(self, parent, textvariable=None, mono=False, show="", **kw):
        self._bg = _frame_bg(parent)
        super().__init__(parent, bg=self._bg)
        v = textvariable or tk.StringVar()

        # Border frame: 1px ring shown via inner's padx=1,pady=1 gap
        self._border = tk.Frame(self, bg=INPUT_BORDER)
        self._border.pack(fill="x")

        # Content area: INPUT_BG, 1px gap shows border bg as thin ring
        self._inner = tk.Frame(self._border, bg=INPUT_BG, height=34)
        self._inner.pack(fill="x", padx=1, pady=1)
        self._inner.pack_propagate(False)

        font = F_MONO if mono else F_NORM
        self._entry = tk.Entry(
            self._inner,
            textvariable=v,
            font=font,
            bg=INPUT_BG,
            fg=INK,
            insertbackground=INK,
            relief="flat",
            highlightthickness=0,
            bd=0,
            show=show,
        )
        self._entry.pack(fill="both", expand=True, padx=11, pady=0)
        self._entry.bind("<FocusIn>",  self._on_focus_in)
        self._entry.bind("<FocusOut>", self._on_focus_out)

    def _on_focus_in(self, _=None):
        self._border.configure(bg=INK3)

    def _on_focus_out(self, _=None):
        self._border.configure(bg=INPUT_BORDER)

    def bind(self, sequence=None, func=None, add=None):
        if sequence in self._FORWARD_EVENTS:
            return self._entry.bind(sequence, func, add)
        return super().bind(sequence, func, add)

    def get(self):
        return self._entry.get()

    def focus_set(self):
        self._entry.focus_set()

    def focus(self):
        self._entry.focus()


class Kicker(tk.Label):
    """Uppercase eyebrow label."""
    def __init__(self, master, text, color=ACCENT, **kw):
        super().__init__(master, text=text.upper(), font=F_KICKER,
                         fg=color, bg=_frame_bg(master), **kw)


class Hairline(tk.Frame):
    def __init__(self, master, horizontal=True, color=HAIR2, **kw):
        if horizontal:
            super().__init__(master, height=1, bg=color, **kw)
        else:
            super().__init__(master, width=1, bg=color, **kw)


def field_label(master, text, required=False, hint=None):
    """Returns a frame containing a small uppercase label (+ optional hint)."""
    f = tk.Frame(master, bg=_frame_bg(master))
    inner = tk.Frame(f, bg=_frame_bg(master))
    inner.pack(fill="x")
    tk.Label(inner, text=text, font=F_LABEL, fg=INK2,
             bg=_frame_bg(master)).pack(side="left")
    if required:
        tk.Label(inner, text=" *", font=F_LABEL, fg=ACCENT,
                 bg=_frame_bg(master)).pack(side="left")
    if hint:
        tk.Label(inner, text=hint, font=F_TINY, fg=MUTED,
                 bg=_frame_bg(master)).pack(side="right")
    return f


def _wheel_units(event) -> int:
    """
    把跨平台 MouseWheel.delta 轉成 yview_scroll 需要的「行數」。
    - Windows / X11：delta 是 ±120 的倍數 → 除 120
    - macOS（含 trackpad）：delta 是 ±1~5 的小整數 → 直接用、不除
    保證符號正確且絕對值至少為 1（避免 int 截斷成 0 害事件被吞）。
    """
    d = event.delta
    if abs(d) >= 120:
        units = int(-d / 120)
    else:
        units = int(-d)
    if units == 0:
        units = -1 if d > 0 else 1
    return units


def _bind_mousewheel_on_hover(hover_widget, canvas):
    """游標在 hover_widget 範圍內時把 wheel 綁到 canvas；離開時還原為
    App._active_view_canvas（若有）以避免殺掉外層綁定。"""
    def _on_wheel(e):
        canvas.yview_scroll(_wheel_units(e), "units")
    def _on_enter(_):
        hover_widget.winfo_toplevel().bind_all("<MouseWheel>", _on_wheel)
    def _on_leave(e):
        try:
            wx = hover_widget.winfo_rootx()
            wy = hover_widget.winfo_rooty()
            ww = hover_widget.winfo_width()
            wh = hover_widget.winfo_height()
            if wx <= e.x_root < wx + ww and wy <= e.y_root < wy + wh:
                return  # 還在元件範圍內（只是移進子元件），不切換
        except Exception:
            pass
        # 離開內層 → 還原外層 view 的綁定，而不是 unbind_all（不然主畫面也滾不動）
        top = hover_widget.winfo_toplevel()
        outer = getattr(top, "_active_view_canvas", None)
        if outer is not None:
            top.bind_all(
                "<MouseWheel>",
                lambda e, _c=outer: _c.yview_scroll(_wheel_units(e), "units"))
        else:
            top.unbind_all("<MouseWheel>")
    hover_widget.bind("<Enter>", _on_enter)
    hover_widget.bind("<Leave>", _on_leave)


# ─── main window ─────────────────────────────────────────────────────────────

def _ensure_launcher_executable():
    """每次啟動都檢查 啟動黑貓工具.command 是否可執行，避免自動更新或解壓導致權限消失。"""
    import stat, os
    launcher = Path(__file__).parent / "啟動黑貓工具.command"
    try:
        if launcher.exists():
            mode = launcher.stat().st_mode
            if not (mode & stat.S_IXUSR):
                os.chmod(str(launcher), mode | 0o755)
    except Exception:
        pass


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        _ensure_launcher_executable()
        self.title("黑貓宅急便 企業建單工具")
        self.configure(bg=PAPER)
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        win_w, win_h = min(1180, sw - 40), min(sh - 80, 880)
        self.geometry(f"{win_w}x{win_h}")
        self.minsize(1000, 720)
        if load_cfg().get("start_maximized", False):
            self.after(200, lambda: self.state("zoomed"))

        # splash
        self._splash = tk.Frame(self, bg=PAPER)
        self._splash.pack(fill="both", expand=True)
        tk.Frame(self._splash, bg=PAPER, height=200).pack()
        # brand mark
        mark = tk.Frame(self._splash, bg=PAPER)
        mark.pack()
        m = tk.Canvas(mark, width=44, height=44, bg=PAPER, highlightthickness=0)
        m.create_rectangle(8, 8, 36, 36, fill=INK, outline=INK)
        m.create_rectangle(14, 17, 30, 28, outline="#FFFFFF", width=2)
        m.pack(side="left", padx=(0, 12))
        info = tk.Frame(mark, bg=PAPER)
        info.pack(side="left")
        tk.Label(info, text="STUDIO A", font=(FONT_FAMILY, _sz(22), "bold"),
                 bg=PAPER, fg=INK).pack(anchor="w")
        tk.Label(info, text="黑貓宅急便工具", font=F_SMALL,
                 bg=PAPER, fg=MUTED).pack(anchor="w")

        self._splash_lbl = tk.Label(self._splash, text="確認版本中…",
                 bg=PAPER, fg=MUTED, font=F_SMALL)
        self._splash_lbl.pack(pady=24)

        threading.Thread(target=self._startup_check, daemon=True).start()

    # ── startup version check ────────────────────────────────────────────────

    def _startup_check(self):
        if not load_cfg().get("check_updates", True):
            self.after(0, self._init_ui)
            return
        just_updated = "--just-updated" in sys.argv
        frozen = getattr(sys, "frozen", False)
        try:
            import urllib.request as _req, ssl
            _ctx = ssl.create_default_context()
            _ctx.check_hostname = False
            _ctx.verify_mode = ssl.CERT_NONE
            url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
            req = _req.Request(url, headers={"User-Agent": "heicat-egs-tool"})
            with _req.urlopen(req, context=_ctx, timeout=5) as r:
                data = json.loads(r.read())
            tag = data.get("tag_name", "").lstrip("v")
            if tag:
                current = tuple(int(x) for x in VERSION.lstrip("v").split("."))
                latest  = tuple(int(x) for x in tag.split("."))
                if latest > current:
                    if just_updated:
                        # 剛更新過卻仍偵測到更新 → Release 版本與 VERSION 不符，防止死循環
                        self.after(0, self._init_ui)
                        return
                    html = data.get("html_url", "")
                    if frozen:
                        # frozen .app：找第一個 .zip asset（GitHub 會去掉中文字）
                        assets = data.get("assets", [])
                        asset = next(
                            (a for a in assets if a["name"].endswith(".zip")),
                            None,
                        )
                        if not asset:
                            self.after(0, self._init_ui)
                            return
                        download_url = asset["browser_download_url"]
                    else:
                        download_url = data.get("zipball_url", "")
                    self.after(0, lambda t=tag, u=download_url, h=html, fr=frozen:
                               self._do_startup_update(t, u, h, frozen=fr))
                    return
        except Exception:
            pass
        self.after(0, self._init_ui)

    def _do_startup_update(self, new_version, download_url, html_url, frozen=False):
        self._splash_lbl.config(text=f"發現新版本 v{new_version}，自動更新中…")

        def run():
            try:
                import ssl, shutil, tempfile, os, zipfile
                import urllib.request as _req

                ssl_ctx = ssl.create_default_context()
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = ssl.CERT_NONE
                req = _req.Request(download_url, headers={"User-Agent": "heicat-egs-tool"})
                with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
                    temp_zip = f.name
                with _req.urlopen(req, context=ssl_ctx, timeout=120) as resp:
                    with open(temp_zip, "wb") as f:
                        shutil.copyfileobj(resp, f)

                self.after(0, lambda: self._splash_lbl.config(text="解壓縮並套用更新…"))

                if frozen:
                    # frozen .app：覆蓋整個 .app bundle
                    app_bundle = Path(sys.executable).parent.parent.parent
                    with tempfile.TemporaryDirectory() as tmpdir:
                        with zipfile.ZipFile(temp_zip, "r") as z:
                            z.extractall(tmpdir)
                        new_app = next(
                            p for p in Path(tmpdir).rglob("*.app") if p.is_dir()
                        )
                        # 先備份再替換（確保同一 volume，可以原子 rename）
                        backup = app_bundle.with_suffix(".app.bak")
                        if backup.exists():
                            shutil.rmtree(str(backup))
                        shutil.copytree(str(new_app), str(app_bundle.with_suffix(".app.new")))
                        app_bundle.rename(backup)
                        app_bundle.with_suffix(".app.new").rename(app_bundle)
                        shutil.rmtree(str(backup), ignore_errors=True)
                    # 清除 quarantine，避免 macOS Gatekeeper 擋住更新後的 .app
                    subprocess.run(
                        ["xattr", "-dr", "com.apple.quarantine", str(app_bundle)],
                        capture_output=True,
                    )
                else:
                    # 源碼模式：覆蓋程式目錄，保留用戶資料
                    dst_root = Path(__file__).parent.parent
                    preserve = {
                        str(dst_root / "黑貓主程式" / "config.yaml"),
                        str(dst_root / "黑貓主程式" / "contacts.json"),
                    }
                    with tempfile.TemporaryDirectory() as tmpdir:
                        with zipfile.ZipFile(temp_zip, "r") as z:
                            z.extractall(tmpdir)
                        top = next(p for p in Path(tmpdir).iterdir() if p.is_dir())
                        for src in top.rglob("*"):
                            rel = src.relative_to(top)
                            dst = dst_root / rel
                            if src.is_dir():
                                dst.mkdir(parents=True, exist_ok=True)
                            elif str(dst) not in preserve:
                                dst.parent.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(str(src), str(dst))
                                if dst.suffix == ".command":
                                    os.chmod(str(dst), 0o755)

                os.unlink(temp_zip)
                self.after(0, self._restart_app)
            except Exception:
                self.after(0, self._init_ui)

        threading.Thread(target=run, daemon=True).start()

    def _restart_app(self):
        import os
        if getattr(sys, "frozen", False):
            # frozen .app：用 open 啟動更新後的 bundle，然後結束自身
            app_bundle = str(Path(sys.executable).parent.parent.parent)
            subprocess.Popen(["open", "-n", "-a", app_bundle, "--args", "--just-updated"])
            sys.exit(0)
        else:
            args = [sys.executable, str(Path(__file__)), "--just-updated"]
            os.execv(sys.executable, args)

    # ── build full UI ────────────────────────────────────────────────────────

    def _init_ui(self):
        self._splash.destroy()

        # ttk style for entries / combos
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Tw.TEntry",
            fieldbackground=INPUT_BG, background=INPUT_BG, foreground=INK,
            bordercolor=INPUT_BORDER, lightcolor=INPUT_BORDER, darkcolor=INPUT_BORDER,
            padding=8, relief="flat")
        style.map("Tw.TEntry", bordercolor=[("focus", ACCENT)])

        style.configure("Tw.TCombobox",
            fieldbackground=INPUT_BG, background=INPUT_BG, foreground=INK,
            bordercolor=INPUT_BORDER, lightcolor=INPUT_BORDER, darkcolor=INPUT_BORDER,
            arrowcolor=MUTED, selectbackground=INPUT_BG, selectforeground=INK,
            padding=6, relief="flat")
        style.map("Tw.TCombobox",
                  bordercolor=[("focus", ACCENT)],
                  fieldbackground=[("readonly", INPUT_BG)],
                  foreground=[("readonly", INK)])

        style.configure("Tw.Treeview",
            background=CARD, fieldbackground=CARD, foreground=INK,
            bordercolor=HAIR, rowheight=32, font=F_SMALL)
        style.configure("Tw.Treeview.Heading",
            background=PAPER, foreground=MUTED, font=F_KICKER,
            relief="flat", borderwidth=0, padding=(8, 8))
        style.map("Tw.Treeview.Heading", background=[("active", PAPER)])
        style.map("Tw.Treeview",
            background=[("selected", ACCENT2)],
            foreground=[("selected", INK)])

        style.configure("Tw.Vertical.TScrollbar",
            background="#2C2C2C", troughcolor="#E8E3D8", bordercolor=PAPER,
            arrowcolor="#2C2C2C", lightcolor="#2C2C2C", darkcolor="#1A1A1A",
            gripcount=0, relief="flat")
        style.map("Tw.Vertical.TScrollbar",
            background=[("active", "#111111"), ("pressed", "#000000")])

        # mac copy/paste
        self._install_mac_clipboard()

        # ── Window chrome — centred title bar ────────────────────────────────
        chrome = tk.Frame(self, bg=RAIL, height=36)
        chrome.pack(fill="x")
        chrome.pack_propagate(False)
        tk.Label(chrome, text="STUDIO A · 黑貓宅急便工具",
                 bg=RAIL, fg=INK2, font=(FONT_FAMILY, _sz(11), "bold")).place(
                 relx=0.5, rely=0.5, anchor="center")

        # ── Body — sidebar + right column ────────────────────────────────────
        body = tk.Frame(self, bg=PAPER)
        body.pack(fill="both", expand=True)

        self.sidebar = Sidebar(body, self)
        self.sidebar.pack(side="left", fill="y")

        tk.Frame(body, bg=HAIR, width=1).pack(side="left", fill="y")

        right = tk.Frame(body, bg=PAPER)
        right.pack(side="left", fill="both", expand=True)

        # ── TopBar ────────────────────────────────────────────────────────────
        self._topbar = TopBar(right, self)
        self._topbar.pack(fill="x")
        tk.Frame(right, bg=HAIR2, height=1).pack(fill="x")

        self.content_host = tk.Frame(right, bg=PAPER)
        self.content_host.pack(fill="both", expand=True)

        self._staging = []   # app-level staging list shared across views
        self._web: TakkyubinWebClient | None = None  # shared web session

        self.views = {
            "single":       SingleOrderView(self.content_host, self),
            "print_queue":  PrintQueueView(self.content_host, self),
            "batch":        BatchOrderView(self.content_host, self),
            "tracking":     TrackingView(self.content_host, self),
            "freight":      FreightView(self.content_host, self),
            "contacts":     ContactsView(self.content_host, self),
            "epb_transfer": EpbTransferView(self.content_host, self),
            "settings":     ConfigView(self.content_host, self),
        }
        for v in self.views.values():
            v.place(relx=0, rely=0, relwidth=1, relheight=1)

        self.show_view("single")
        # ⌘1~8 導覽捷徑改由 _keycode_guard 處理（支援注音 IME）
        # 隱藏快捷鍵：EPB 進階功能解鎖／鎖定入口（不顯示在任何 UI 上）
        self.bind_all("<Command-Option-e>", lambda e: self._open_epb_unlock_dialog())
        self.bind_all("<Command-Option-E>", lambda e: self._open_epb_unlock_dialog())

    def _open_epb_unlock_dialog(self):
        EpbUnlockDialog(self, on_change=self._on_epb_lock_change)

    def _on_epb_lock_change(self, unlocked: bool):
        """解鎖／鎖定狀態變更後，同步側邊欄入口；鎖定時若在 EPB 分頁則跳回單筆。"""
        if unlocked:
            self.sidebar.show_epb_nav()
        else:
            self.sidebar.hide_epb_nav()
            if getattr(self._topbar, "_current", None) == "epb_transfer":
                self.show_view("single")

    def show_view(self, name):
        # EPB 進階功能未解鎖時，⌘8 / sidebar 點擊靜默 no-op
        if name == "epb_transfer" and not _is_epb_unlocked():
            return
        v = self.views.get(name)
        if not v: return
        v.lift()
        if hasattr(v, "on_show"): v.on_show()
        self.sidebar.set_active(name)
        if hasattr(self, "_topbar"): self._topbar.set_view(name)
        # 切換頁面時立刻把 MouseWheel 綁到該頁的主 canvas，
        # 讓使用者在視窗任何地方都能捲動。同時記錄到 _active_view_canvas，
        # 讓子區域 hover Leave 時能還原而不是 unbind 全砍。
        if hasattr(v, "_scroll_canvas"):
            c = v._scroll_canvas
            self._active_view_canvas = c
            self.bind_all("<MouseWheel>",
                          lambda e, _c=c: _c.yview_scroll(_wheel_units(e), "units"))
        else:
            self._active_view_canvas = None
            self.unbind_all("<MouseWheel>")

    # ── macOS clipboard fix (preserved from original) ─────────────────────────

    def _install_mac_clipboard(self):
        import time as _time
        _last_t   = [0.0]
        _last_inp = [None]

        def _on_focus_in(e):
            if hasattr(e.widget, "insert") and hasattr(e.widget, "clipboard_get"):
                _last_inp[0] = e.widget
        self.bind_all("<FocusIn>", _on_focus_in, add="+")

        def _fw():
            w = self.focus_get()
            if w and hasattr(w, "insert") and hasattr(w, "clipboard_get"):
                return w
            return _last_inp[0]

        import subprocess as _sp

        def _pb_paste():
            try:
                return _sp.run(["pbpaste"], capture_output=True, timeout=2).stdout.decode("utf-8", errors="replace")
            except Exception:
                return ""

        def _pb_copy(text):
            try:
                _sp.run(["pbcopy"], input=text.encode("utf-8"), timeout=2)
            except Exception:
                pass

        def _do_paste():
            clip = _pb_paste()
            if not clip: return
            w = _fw()
            if not w: return
            try:
                pos = int(w.index("insert"))
                txt = w.get()
                try:
                    s = int(w.index("sel.first"))
                    e = int(w.index("sel.last"))
                    new, new_pos = txt[:s] + clip + txt[e:], s + len(clip)
                except Exception:
                    new, new_pos = txt[:pos] + clip + txt[pos:], pos + len(clip)
                varname = w.cget("textvariable")
                if varname:
                    self.tk.call("set", varname, new)
                else:
                    w.delete(0, "end")
                    w.insert(0, new)
                w.icursor(new_pos)
                return
            except Exception:
                pass
            try:
                self.clipboard_clear(); self.clipboard_append(clip)
                w.event_generate("<<Paste>>"); return
            except Exception: pass
            try: w.delete("sel.first", "sel.last")
            except Exception: pass
            try: w.insert("insert", clip)
            except Exception: pass

        def _do_copy():
            w = _fw()
            if not w: return
            try: _pb_copy(w.selection_get())
            except Exception: pass

        def _do_cut():
            w = _fw()
            if not w: return
            try:
                _pb_copy(w.selection_get()); w.delete("sel.first", "sel.last")
            except Exception: pass

        def _do_select_all():
            w = _fw()
            if not w: return
            try:
                if hasattr(w, "select_range"):
                    w.select_range(0, "end")
                else:
                    w.tag_add("sel", "1.0", "end")
            except Exception: pass

        self.tk.createcommand("::tk::mac::Paste",     lambda: self.after(0, _do_paste))
        self.tk.createcommand("::tk::mac::Copy",      lambda: self.after(0, _do_copy))
        self.tk.createcommand("::tk::mac::Cut",       lambda: self.after(0, _do_cut))
        self.tk.createcommand("::tk::mac::SelectAll", lambda: self.after(0, _do_select_all))

        def _guarded(fn):
            def handler(e):
                now = _time.time()
                if now - _last_t[0] < 0.05: return "break"
                _last_t[0] = now; fn(); return "break"
            return handler

        for _cls in ("Entry", "TEntry", "Text"):
            self.bind_class(_cls, "<Command-c>", _guarded(_do_copy))
            self.bind_class(_cls, "<Command-v>", _guarded(_do_paste))
            self.bind_class(_cls, "<Command-x>", _guarded(_do_cut))
            self.bind_class(_cls, "<Command-a>", _guarded(_do_select_all))

        _KC = {9: _do_paste, 8: _do_copy, 7: _do_cut, 0: _do_select_all}
        # macOS Carbon virtual keycodes for 1-8（注音模式下 keysym 失效，只能靠 keycode）
        # 注意：5 的 keycode=23，6 的 keycode=22（非連續，為 Mac 鍵盤硬體排列）
        _NAV_KC = {
            18: "single",       # 1
            19: "batch",        # 2
            20: "epb_transfer", # 3
            21: "print_queue",  # 4
            23: "tracking",     # 5
            22: "freight",      # 6
            26: "contacts",     # 7
            28: "settings",     # 8
        }
        def _keycode_guard(e):
            kc = e.keycode
            # 英文模式 keycode 直接命中；注音模式 Tk 認不出 keysym，會把硬體 keycode 塞到最高 byte
            raw = kc if kc < 0x1000000 else (kc >> 24) & 0xFF
            fn = _KC.get(kc) or _KC.get(raw)
            if fn is not None:
                now = _time.time()
                if now - _last_t[0] < 0.05: return "break"
                _last_t[0] = now; fn(); return "break"
            # ⌘1~8 導覽捷徑（keycode 方式，穿透注音 IME）
            view = _NAV_KC.get(raw)
            if view:
                self.show_view(view)
                return "break"
        self.bind_all("<Command-KeyPress>", _keycode_guard, add="+")
        def _keycode_guard_state(e):
            if not (e.state & 8): return
            return _keycode_guard(e)
        self.bind_all("<KeyPress>", _keycode_guard_state, add="+")

        def _show_ctx(event):
            w = event.widget
            _last_inp[0] = w
            ctx = tk.Menu(self, tearoff=0)
            ctx.add_command(label="剪下    ⌘X", command=_do_cut)
            ctx.add_command(label="複製    ⌘C", command=_do_copy)
            ctx.add_command(label="貼上    ⌘V", command=_do_paste)
            ctx.add_separator()
            ctx.add_command(label="全選    ⌘A", command=_do_select_all)
            ctx.tk_popup(event.x_root, event.y_root)

        for _cls in ("Entry", "TEntry", "Text"):
            self.bind_class(_cls, "<Button-2>",         _show_ctx)
            self.bind_class(_cls, "<Control-Button-1>", _show_ctx)


# ─── logo helper ─────────────────────────────────────────────────────────────

_LOGO_B64 = (
    "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" +
    "a9Ydd97hum4YhnRHfMEoYpR7NYOooMmeBY3YU7RfdYkz9KEERyrEQRKnW8IwDLPSHHHc+C0tg1SNkKo+HXDA/tqF" +
    "BACVSvmC8y/QAd9RGAWBTxzjmWeeef31vC4OIv7iF784/7zzoyhau3btPvvss3DhQtq5HyxbduSRR1JVImJQU6dO" +
    "pTomRx991N133611pbRzQUBP6hPy008/vfTSS6lGhVa+Tj7pJKpN6HleGBCGJElRt6KZMKldVuoknZk4irNnCjOc" +
    "JEkG5GEcx0CFoz3Pk01ae1fqDDakDhjB8jWvaIXWz5AVIQzDW265hZKQdDWe7t27n3322UuWLNEUorNzS15ESaXX" +
    "5Tz44J/GjRs3ceLE73znO1RAlfSmFStWjBkzRid61Ov1s84664QTTjjxxBNvuulGQgBUFOyUXkikA/yXLl16ySWX" +
    "9OzZ04za3G233R5++OGCFcR04ena0VsPJ2g2RaSGh4ItyKdZT+sFZQuQVU30PM/LizFpW1Cx5GBBwxRC1M1a2Gam" +
    "RhhSnRzq0McfrzznnLMr5bJZnMd13QkTJjz99NNUn4XKkdAx63letdpJXdfqUhRFSRIHQbBp06ZXX31VV8WlAW/c" +
    "sJHudaNBiUREYehnFDaKornz5k6c+P2WlooJt3369Jk2bdrmzZuzEm/5XQh5PEccNdQfD8OwoJHpANCG3J6GUgWG" +
    "LYjR6ZfmXiFC5uc0U5ksxqF4DRap6fkzmeJu3LVauIGLqK1CpBjNxYsXT58+/eGHH6bYbB2lM2jXXY8/4YSjjjpq" +
    "//337969u7ZIR1EkksRxXVpsepeO3KcfSeVGiFK5RBdVU7Fs+pHA999dtOjpp59+6qmnli1bRhkfdF94r169pk6d" +
    "ev755+20085kitA5GoUhfEULAt24lj2g79NFureRZzf1NpSFklIyHXNJm4sxVimXmZGvyjmvlCuUTUbPWJZFVRCo" +
    "ha5o15nyURQBoG05pXKJ1II0zdxx3FIJFYZRWHJL3OJLly69//77H3roofXr15vLAAADBw488MADx4wZc9BBo3Yd" +
    "NKi1pbVItZUQ0jFSlHXmu2nAiaLooxUrFi1e/OKLL77yyivLly9vcGnsvPNOU6acfvrppw8cOJAAgLgDbXldAJfK" +
    "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" +
    "tfIAAAAASUVORK5CYII="
)

def _load_logo(px: int = 36):
    """Return a tk.PhotoImage of logo.png at px×px. Uses embedded base64 data."""
    import base64
    try:
        raw = base64.b64decode(_LOGO_B64)
        img = tk.PhotoImage(data=_LOGO_B64)
        factor = max(1, img.width() // px)
        return img.subsample(factor, factor) if factor > 1 else img
    except Exception:
        pass
    try:
        from PIL import Image, ImageTk
        import io
        raw = base64.b64decode(_LOGO_B64)
        pil = Image.open(io.BytesIO(raw)).resize((px, px), Image.LANCZOS)
        return ImageTk.PhotoImage(pil)
    except Exception:
        return None


# ─── sidebar ─────────────────────────────────────────────────────────────────

_NAV_ITEMS = [
    ("single",        "建立寄件單",   "1", "📤"),
    ("batch",         "多筆建單",     "2", "☰"),
    ("epb_transfer",  "EPB 調撥",     "3", "📦"),
    ("print_queue",   "待列印貨運單", "4", "🖨"),
    ("tracking",      "貨運查詢",     "5", "⊙"),
    ("freight",       "費用查詢",     "6", "💳"),
    ("contacts",      "通訊錄",       "7", "⊞"),
    ("settings",      "設定",         "8", "⚙"),
]

class Sidebar(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg=RAIL, width=234)
        self.pack_propagate(False)
        self.app = app
        self._items = {}

        # ── brand ──────────────────────────────────────────────────────────
        brand = tk.Frame(self, bg=RAIL)
        brand.pack(fill="x", padx=16, pady=(18, 14))
        tk.Frame(brand, bg=RAIL, width=1).pack(side="left")  # spacer

        # Logo circle
        self._logo_img = _load_logo(32)
        logo_c = tk.Canvas(brand, width=40, height=40, bg=RAIL, highlightthickness=0)
        logo_c.pack(side="left", padx=(0, 10))
        logo_c.create_oval(1, 1, 39, 39, fill=CARD, outline=HAIR, width=1)
        if self._logo_img:
            logo_c.create_image(20, 20, image=self._logo_img)
        else:
            logo_c.create_rectangle(12, 12, 28, 28, fill=INK, outline=INK)

        info = tk.Frame(brand, bg=RAIL)
        info.pack(side="left")
        tk.Label(info, text="STUDIO A",
                 font=(FONT_FAMILY, _sz(12), "bold"),
                 bg=RAIL, fg=INK).pack(anchor="w")
        tk.Label(info, text="黑貓宅急便工具",
                 font=(FONT_FAMILY, _sz(9)),
                 bg=RAIL, fg=INK3).pack(anchor="w")

        tk.Frame(self, bg=HAIR2, height=1).pack(fill="x")

        # ── ⌘K search placeholder ─────────────────────────────────────────
        srch = tk.Frame(self, bg=RAIL)
        srch.pack(fill="x", padx=12, pady=(10, 6))
        srch_inner = ctk.CTkFrame(srch, fg_color=CARD, corner_radius=8,
                                  border_width=1, border_color=HAIR)
        srch_inner.pack(fill="x")
        tk.Label(srch_inner, text="🔍", bg=CARD, fg=MUTED,
                 font=(FONT_FAMILY, _sz(10))).pack(side="left", padx=(6, 4), pady=6)
        tk.Label(srch_inner, text="快速指令…", bg=CARD, fg=MUTED,
                 font=(FONT_FAMILY, _sz(11)), anchor="w").pack(side="left", fill="x", expand=True)
        tk.Label(srch_inner, text="⌘K", bg=CARD, fg=MUTED2,
                 font=(MONO_FAMILY, _sz(9))).pack(side="right", padx=(0, 6))

        # ── nav ────────────────────────────────────────────────────────────
        nav = tk.Frame(self, bg=RAIL)
        nav.pack(fill="x", padx=8, pady=4)
        for key, label, kbd, icon in _NAV_ITEMS:
            self._items[key] = NavItem(nav, label, kbd, icon,
                                       lambda k=key: self.app.show_view(k))
            # EPB 進階功能：未解鎖時建好 widget 但不 pack（解鎖後可即時顯示）
            if key == "epb_transfer" and not _is_epb_unlocked():
                continue
            self._items[key].pack(fill="x", pady=1)

        # 契客專區登入按鈕（設定下方）
        self._web_login_btn = tk.Label(
            nav, text="🔐 驗證碼確認（契客專區）",
            font=(FONT_FAMILY, _sz(11)), bg=RAIL2, fg=INK2,
            cursor="hand2", padx=12, pady=7, anchor="w",
            relief="flat")
        self._web_login_btn.pack(fill="x", pady=(6, 1))
        self._web_login_btn.bind("<Button-1>", lambda e: self._do_web_login())
        self._web_login_btn.bind("<Enter>",
            lambda e: self._web_login_btn.config(bg=RAIL, fg=INK))
        self._web_login_btn.bind("<Leave>",
            lambda e: self._web_login_btn.config(bg=RAIL2, fg=INK2))

        # spacer
        tk.Frame(self, bg=RAIL).pack(fill="both", expand=True)

        # ── sender card ────────────────────────────────────────────────────
        self.sender_card = tk.Frame(self, bg=RAIL)
        self.sender_card.pack(fill="x", padx=10, pady=10)
        self._render_sender()

        # version line
        ver_row = tk.Frame(self, bg=RAIL)
        ver_row.pack(fill="x", padx=16, pady=(0, 10))
        tk.Label(ver_row, text=f"v{VERSION}",
                 font=(MONO_FAMILY, _sz(9)), bg=RAIL, fg=MUTED).pack(side="left")

    def _render_sender(self):
        for w in self.sender_card.winfo_children():
            w.destroy()
        cfg = load_cfg()
        sender = cfg.get("sender") or {}
        has_token = bool(cfg.get("api_token") and cfg.get("username"))

        wrap = ctk.CTkFrame(self.sender_card, fg_color=CARD, corner_radius=10,
                            border_width=1, border_color=HAIR)
        wrap.pack(fill="x")
        inner = tk.Frame(wrap, bg=CARD)
        inner.pack(fill="x", padx=12, pady=10)

        # header row
        hrow = tk.Frame(inner, bg=CARD)
        hrow.pack(fill="x", pady=(0, 6))
        Kicker(hrow, "寄件人").pack(side="left")
        # status pill
        pill = tk.Frame(hrow, bg=OK2)
        pill.pack(side="right")
        tk.Label(pill, text=f"● {'已連線' if has_token else '未設定'}",
                 font=(FONT_FAMILY, _sz(9), "bold"),
                 bg=OK2 if has_token else WARN2,
                 fg=OK if has_token else WARN,
                 padx=6, pady=2).pack()
        pill.configure(bg=OK2 if has_token else WARN2)

        tk.Label(inner,
                 text=sender.get("name") or "（未設定）",
                 font=(FONT_FAMILY, _sz(12), "bold"),
                 bg=CARD, fg=INK, wraplength=180, justify="left",
                 anchor="w").pack(fill="x", pady=(0, 2))
        tk.Label(inner,
                 text=sender.get("address") or "請至設定頁填寫",
                 font=(FONT_FAMILY, _sz(9)),
                 bg=CARD, fg=INK3, wraplength=180, justify="left",
                 anchor="w").pack(fill="x")

    def set_active(self, key):
        for k, item in self._items.items():
            item.set_active(k == key)

    def show_epb_nav(self):
        """解鎖後即時把 EPB 入口插回 nav（位於設定上方）。"""
        item = self._items.get("epb_transfer")
        settings = self._items.get("settings")
        if item is None:
            return
        if settings is not None:
            item.pack(fill="x", pady=1, before=settings)
        else:
            item.pack(fill="x", pady=1)

    def hide_epb_nav(self):
        """鎖定時把 EPB 入口從 nav 抽掉。"""
        item = self._items.get("epb_transfer")
        if item is not None:
            item.pack_forget()

    def refresh_sender(self):
        self._render_sender()

    def _do_web_login(self):
        cfg = load_cfg()
        username = cfg.get("web_username","").strip()
        password = cfg.get("web_password","").strip()
        if not username or not password:
            messagebox.showwarning("尚未設定",
                "請先到「設定」頁填入客戶代號與密碼後儲存，再登入。")
            return
        self._web_login_btn.config(text="⏳ 載入驗證碼中…", fg=MUTED)
        self.app._web = TakkyubinWebClient()

        def fetch():
            try:
                tokens, img_bytes = self.app._web.get_login_page()
                self.after(0, lambda: self._show_web_captcha(tokens, img_bytes, username, password))
            except Exception as ex:
                self.app._web = None
                self.after(0, lambda: self._web_login_btn.config(
                    text="🔐 驗證碼確認（契客專區）", fg=INK2))
        import threading; threading.Thread(target=fetch, daemon=True).start()

    def _show_web_captcha(self, tokens, img_bytes, username, password):
        self._web_login_btn.config(text="🔐 驗證碼確認（契客專區）", fg=INK2)
        dlg = tk.Toplevel(self)
        dlg.title("驗證碼登入")
        dlg.resizable(False, False)
        dlg.grab_set()
        f = tk.Frame(dlg, bg=PAPER, padx=24, pady=20); f.pack()
        dlg.update_idletasks()
        sw, sh = dlg.winfo_screenwidth(), dlg.winfo_screenheight()
        w, h   = dlg.winfo_reqwidth(), dlg.winfo_reqheight()
        dlg.geometry(f"+{(sw-w)//2}+{(sh-h)//2}")

        tk.Label(f, text="請輸入驗證碼後登入",
                 font=(FONT_FAMILY, _sz(13), "bold"), bg=PAPER, fg=INK).pack(pady=(0, 12))
        if img_bytes:
            try:
                import base64 as _b64
                img = tk.PhotoImage(data=_b64.b64encode(img_bytes).decode())
                tk.Label(f, image=img, bg=PAPER).pack(pady=(0, 8))
                dlg._img = img
            except Exception:
                tk.Label(f, text="（無法顯示驗證碼圖片）",
                         bg=PAPER, fg=MUTED, font=F_SMALL).pack(pady=(0, 8))
        cap_var = tk.StringVar()
        e = tk.Entry(f, textvariable=cap_var, font=(MONO_FAMILY, _sz(14)),
                     width=10, justify="center", relief="flat",
                     bg=HAIR3, fg=INK, insertbackground=INK,
                     highlightthickness=1, highlightbackground=HAIR)
        e.pack(ipady=6, pady=(0, 14)); e.focus_set()
        msg_lbl = tk.Label(f, text="", font=F_SMALL, bg=PAPER, fg=ERR); msg_lbl.pack()

        def _submit():
            code = cap_var.get().strip()
            if not code:
                msg_lbl.config(text="請輸入驗證碼"); return
            msg_lbl.config(text="登入中…", fg=MUTED); dlg.update()
            def do_login():
                try:
                    ok = self.app._web.login(username, password, code, tokens)
                    if ok:
                        self.after(0, dlg.destroy)
                        self.after(0, lambda: self._web_login_btn.config(
                            text="✓ 已登入契客專區", fg=OK))
                    else:
                        self.app._web = None
                        self.after(0, lambda: msg_lbl.config(
                            text="登入失敗，請確認帳號密碼與驗證碼", fg=ERR))
                except Exception as ex:
                    self.app._web = None
                    self.after(0, lambda: msg_lbl.config(text=f"錯誤：{ex}", fg=ERR))
            import threading; threading.Thread(target=do_login, daemon=True).start()

        btn_row = tk.Frame(f, bg=PAPER); btn_row.pack(pady=(8, 0))
        tk.Button(btn_row, text="確認登入", command=_submit,
                  font=(FONT_FAMILY, _sz(12), "bold"), bg=HAIR3, fg=INK,
                  relief="flat", padx=16, pady=6, cursor="hand2").pack(side="left", padx=(0,8))
        tk.Button(btn_row, text="取消", command=dlg.destroy,
                  font=(FONT_FAMILY, _sz(12)), bg=HAIR3, fg=INK2,
                  relief="flat", padx=16, pady=6, cursor="hand2").pack(side="left")
        e.bind("<Return>", lambda _: _submit())

    def update_badge(self, key: str, n: int):
        if key in self._items:
            self._items[key].set_badge(n)


class NavItem(tk.Frame):
    """Sidebar nav row. Active state shows a white pill floating on the RAIL bg."""
    def __init__(self, master, label, kbd, icon, on_click):
        # outer frame stays RAIL — provides the 4px horizontal "pill margin"
        super().__init__(master, bg=RAIL, padx=6, pady=2)
        self._active = False
        self._on_click = on_click
        # inner pill: HAIR border when active, RAIL otherwise
        self._pill_border = tk.Frame(self, bg=RAIL)
        self._pill_border.pack(fill="x")
        self.inner = tk.Frame(self._pill_border, bg=RAIL)
        self.inner.pack(fill="x", padx=1, pady=1)
        # icon
        self.icn = tk.Label(self.inner, text=icon,
                            font=(FONT_FAMILY, _sz(13)), bg=RAIL, fg=MUTED,
                            width=2, padx=2, pady=6)
        self.icn.pack(side="left", padx=(6, 0))
        self.lbl = tk.Label(self.inner, text=label, font=F_NAV,
                            bg=RAIL, fg=INK2, anchor="w", pady=6)
        self.lbl.pack(side="left", fill="x", expand=True, padx=4)
        self.kbd = tk.Label(self.inner, text=f"⌘{kbd}",
                            font=(MONO_FAMILY, _sz(10)),
                            bg=RAIL, fg=MUTED, padx=8)
        self.kbd.pack(side="right")
        # badge (hidden by default, shown when count > 0)
        self.badge_lbl = tk.Label(self.inner, text="",
                                  font=(MONO_FAMILY, _sz(10), "bold"),
                                  bg=ACCENT, fg="#FFFFFF",
                                  padx=5, pady=1, relief="flat", borderwidth=0)
        for w in (self._pill_border, self.inner, self.icn, self.lbl, self.kbd):
            w.bind("<Button-1>", lambda e: self._on_click())
            w.bind("<Enter>", self._hover)
            w.bind("<Leave>", self._unhover)
            w.configure(cursor="hand2")
        self.bind("<Button-1>", lambda e: self._on_click())
        self.bind("<Enter>", self._hover)
        self.bind("<Leave>", self._unhover)
        self.configure(cursor="hand2")
        self.badge_lbl.bind("<Button-1>", lambda e: self._on_click())
        self.badge_lbl.configure(cursor="hand2")

    def set_badge(self, n: int):
        if n > 0:
            self.badge_lbl.configure(text=str(n))
            if not self.badge_lbl.winfo_ismapped():
                self.badge_lbl.pack(side="right", before=self.kbd, padx=(0, 4))
        else:
            self.badge_lbl.pack_forget()

    def _all(self): return (self._pill_border, self.inner, self.icn, self.lbl, self.kbd)

    def _hover(self, e):
        if self._active: return
        for w in self._all():
            w.configure(bg=RAIL2)

    def _unhover(self, e):
        if self._active: return
        for w in self._all():
            w.configure(bg=RAIL)

    def set_active(self, on):
        self._active = on
        if on:
            # white pill floating: HAIR border frame + CARD inner
            self._pill_border.configure(bg=HAIR)
            self.inner.configure(bg=CARD)
            self.icn.configure(bg=CARD, fg=ACCENT)
            self.lbl.configure(bg=CARD, fg=INK,
                               font=(FONT_FAMILY, _sz(13), "bold"))
            self.kbd.configure(bg=CARD, fg=MUTED)
        else:
            for w in self._all():
                w.configure(bg=RAIL)
            self.lbl.configure(fg=INK2, font=F_NAV)
            self.icn.configure(fg=MUTED)
            self.kbd.configure(fg=MUTED)


# ─── top bar ─────────────────────────────────────────────────────────────────

_VIEW_NAMES = {
    "single":       "建立寄件單",
    "print_queue":  "待列印貨運單",
    "batch":        "多筆建單",
    "tracking":     "貨運查詢",
    "freight":      "費用查詢",
    "contacts":     "通訊錄",
    "epb_transfer": "EPB 調撥",
    "settings":     "設定",
}

class TopBar(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg=PAPER, height=52)
        self.pack_propagate(False)
        self.app = app
        self._current = "single"

        # breadcrumb
        bc = tk.Frame(self, bg=PAPER)
        bc.pack(side="left", padx=22, fill="y")
        tk.Label(bc, text="黑貓宅急便工具",
                 font=(FONT_FAMILY, _sz(11)), bg=PAPER, fg=MUTED).pack(side="left")
        tk.Label(bc, text=" ›", font=(FONT_FAMILY, _sz(11)), bg=PAPER, fg=MUTED2).pack(side="left")
        self._bc_lbl = tk.Label(bc, text="建立寄件單",
                                font=(FONT_FAMILY, _sz(11), "bold"),
                                bg=PAPER, fg=INK)
        self._bc_lbl.pack(side="left", padx=(4, 0))

        # right cluster
        right = tk.Frame(self, bg=PAPER)
        right.pack(side="right", padx=18, fill="y")

        # 新增寄件單 button
        TwButton(right, "＋ 新增寄件單", variant="default",
                 command=lambda: self.app.show_view("single")).pack(
                 side="right", padx=(8, 0))

        # divider
        tk.Frame(right, bg=HAIR, width=1, height=20).pack(side="right", padx=10)

        # API status
        self._api_dot = tk.Label(right, text="●",
                                 font=(FONT_FAMILY, _sz(10)), bg=PAPER, fg=MUTED)
        self._api_dot.pack(side="right")
        self._api_lbl = tk.Label(right, text="API",
                                 font=(FONT_FAMILY, _sz(10)), bg=PAPER, fg=MUTED)
        self._api_lbl.pack(side="right", padx=(0, 4))

        # clock
        self._clk = tk.Label(right, text="",
                             font=(MONO_FAMILY, _sz(10)), bg=PAPER, fg=MUTED)
        self._clk.pack(side="right", padx=(0, 10))
        self._tick()

        # divider
        tk.Frame(right, bg=HAIR, width=1, height=20).pack(side="right", padx=10)

        self._refresh_api_status()

    def _tick(self):
        import datetime
        now = datetime.datetime.now()
        self._clk.config(text=now.strftime("%Y-%m-%d  %H:%M"))
        self.after(30000, self._tick)

    def _refresh_api_status(self):
        cfg = load_cfg()
        has = bool(cfg.get("api_token") and cfg.get("username"))
        self._api_dot.config(fg=OK if has else WARN)
        self._api_lbl.config(text="已連線" if has else "未設定",
                             fg=INK2 if has else WARN)

    def set_view(self, name):
        self._current = name
        self._bc_lbl.config(text=_VIEW_NAMES.get(name, name))
        self._refresh_api_status()


# ─── section header ──────────────────────────────────────────────────────────

class SectionHeader(tk.Frame):
    def __init__(self, master, kicker, title, **kw):
        super().__init__(master, bg=_frame_bg(master))
        Kicker(self, kicker, color=ACCENT).pack(anchor="w")
        tk.Label(self, text=title, font=F_TITLE,
                 bg=_frame_bg(master), fg=INK).pack(anchor="w", pady=(2, 0))


# ─── single order view ──────────────────────────────────────────────────────

class SingleOrderView(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg=PAPER)
        self.app = app
        self.fields = {}
        self._field_widgets = {}
        self._ac_popup = None
        self._print_btn = None
        self._staging_card = None
        self._staging_list_frame = None
        self._cat_var = None
        self._cat_seg = None
        self._cat_map = {
            "門市": "Y 收件人付（運費到付）",
            "廠商": "Y 收件人付（運費到付）",
            "個人": "N 寄件人付",
            "其他": "N 寄件人付",
        }
        self._build()

    def _build(self):
        # ─── scrollable canvas ────────────────────────────────────────────────
        canvas = tk.Canvas(self, bg=PAPER, highlightthickness=0)
        vsb = ttk.Scrollbar(self, orient="vertical", command=canvas.yview,
                            style="Tw.Vertical.TScrollbar")
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        body = tk.Frame(canvas, bg=PAPER)
        win = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))
        self._scroll_canvas = canvas
        _bind_mousewheel_on_hover(self, canvas)

        wrap = tk.Frame(body, bg=PAPER)
        wrap.pack(fill="both", expand=True, padx=28, pady=24)

        # ─── page header ──────────────────────────────────────────────────────
        head = tk.Frame(wrap, bg=PAPER); head.pack(fill="x", pady=(0, 14))
        head_left = tk.Frame(head, bg=PAPER); head_left.pack(side="left")
        Kicker(head_left, "建立寄件單").pack(anchor="w")
        tk.Label(head_left, text="新增單筆寄件",
                 font=(FONT_FAMILY, _sz(24), "bold"),
                 bg=PAPER, fg=INK).pack(anchor="w", pady=(2, 0))
        tk.Label(head_left, text="填寫收件人資料後即可建立貨運單，並自動加入待列印佇列",
                 font=F_SMALL, bg=PAPER, fg=INK3).pack(anchor="w", pady=(4, 0))
        # service type: fixed to 宅配 (segment hidden)
        self._svc_var = tk.StringVar(value="宅配")

        # ─── sender strip ─────────────────────────────────────────────────────
        self._sender_strip_frame = ctk.CTkFrame(
            wrap, fg_color=SUMMARY_BG, corner_radius=12,
            border_width=1, border_color=HAIR2)
        self._sender_strip_frame.pack(fill="x", pady=(0, 14))
        self._refresh_sender_strip()

        # ─── recipient card ───────────────────────────────────────────────────
        rc = Card(wrap, padding=18); rc.pack(fill="x", pady=(0, 14))

        rc_hdr = tk.Frame(rc.body, bg=CARD); rc_hdr.pack(fill="x", pady=(0, 14))
        Kicker(rc_hdr, "收件人").pack(side="left")
        lnk = tk.Frame(rc_hdr, bg=CARD); lnk.pack(side="right")
        _clr_lbl = tk.Label(lnk, text="清空",
                            font=(FONT_FAMILY, _sz(11), "bold"),
                            fg=MUTED, bg=CARD, cursor="hand2")
        _clr_lbl.pack(side="right")
        _clr_lbl.bind("<Button-1>", lambda e: self._clear())
        _pick_lbl = tk.Label(lnk, text="從通訊錄選擇 →",
                             font=(FONT_FAMILY, _sz(11), "bold"),
                             fg=INFO, bg=CARD, cursor="hand2")
        _pick_lbl.pack(side="right", padx=(0, 14))
        _pick_lbl.bind("<Button-1>", lambda e: self._pick_contact())

        # row 1: 姓名, 手機, 市話
        g1 = tk.Frame(rc.body, bg=CARD); g1.pack(fill="x")
        g1.columnconfigure(0, weight=14)
        g1.columnconfigure(1, weight=10)
        g1.columnconfigure(2, weight=10)
        self._field(g1, 0, 0, "姓名 / 公司名稱", "recipient_name", required=True)
        self._field(g1, 0, 1, "手機", "recipient_mobile")
        self._field(g1, 0, 2, "市話", "recipient_phone")
        self.after(100, lambda: self._attach_autocomplete("recipient_name"))

        # row 2: 收件地址（全寬）
        g2 = tk.Frame(rc.body, bg=CARD); g2.pack(fill="x", pady=(12, 0))
        g2.columnconfigure(0, weight=1)
        self._field(g2, 0, 0, "收件地址", "recipient_address", required=True)

        # divider + category row
        Hairline(rc.body).pack(fill="x", pady=(18, 14))
        choice_row = tk.Frame(rc.body, bg=CARD); choice_row.pack(fill="x")
        choice_row.columnconfigure(0, weight=3)
        choice_row.columnconfigure(1, weight=2)

        cat_group = tk.Frame(choice_row, bg=CARD)
        cat_group.grid(row=0, column=0, sticky="w")
        tk.Label(cat_group, text="收件人分類",
                 font=(FONT_FAMILY, _sz(12), "bold"),
                 bg=CARD, fg=INK2).pack(anchor="w")
        tk.Label(cat_group, text="會切換運費付款方式",
                 font=(FONT_FAMILY, _sz(10)), bg=CARD, fg=MUTED).pack(anchor="w", pady=(2, 0))
        self._cat_var = tk.StringVar(value="")
        cat_controls = tk.Frame(cat_group, bg=CARD)
        cat_controls.pack(anchor="w", pady=(8, 0))
        self._cat_seg = Segment(cat_controls, options=list(self._cat_map.keys()),
                                on_change=self._select_category, height=32,
                                button_width=88)
        self._cat_seg.pack(side="left")

        freight_group = tk.Frame(choice_row, bg=CARD)
        freight_group.grid(row=0, column=1, sticky="e")
        tk.Label(freight_group, text="付款設定",
                 font=(FONT_FAMILY, _sz(12), "bold"),
                 bg=CARD, fg=INK2).pack(anchor="w")
        tk.Label(freight_group, text="依收件人分類自動切換",
                 font=(FONT_FAMILY, _sz(10)), bg=CARD, fg=MUTED).pack(anchor="w", pady=(2, 0))
        freight_controls = tk.Frame(freight_group, bg=CARD)
        freight_controls.pack(anchor="w", pady=(8, 0))
        self._toggle_group(freight_controls, 0, 0, "", "is_freight",
                           ["N 寄件人付", "Y 收件人付（運費到付）"],
                           default="N 寄件人付", button_width=124)

        # ─── 進階選項（全寬）────────────────────────────────────────────────────
        adv = Card(wrap, padding=0); adv.pack(fill="x", pady=(0, 14))
        adv_hdr = tk.Frame(adv.body, bg=CARD)
        adv_hdr.pack(fill="x", padx=18, pady=14)
        tbox = ctk.CTkFrame(adv_hdr, fg_color=SUMMARY_BG, corner_radius=6,
                             border_width=1, border_color=HAIR, width=22, height=22)
        tbox.pack(side="left"); tbox.pack_propagate(False)
        self._pkg_toggle_lbl = tk.Label(tbox, text="›",
                                        font=(FONT_FAMILY, _sz(14)),
                                        bg=SUMMARY_BG, fg=INK2, cursor="hand2")
        self._pkg_toggle_lbl.pack(expand=True)
        self._pkg_toggle_lbl.bind("<Button-1>", lambda _: self._toggle_pkg_detail())
        tbox.bind("<Button-1>", lambda _: self._toggle_pkg_detail())
        adv_info = tk.Frame(adv_hdr, bg=CARD, cursor="hand2")
        adv_info.pack(side="left", padx=(10, 0))
        adv_title = tk.Label(adv_info, text="進階選項",
                             font=(FONT_FAMILY, _sz(13), "bold"),
                             bg=CARD, fg=INK, cursor="hand2")
        adv_title.pack(anchor="w")
        adv_subtitle = tk.Label(adv_info, text="尺寸 · 溫層 · 日期",
                                font=(FONT_FAMILY, _sz(10)),
                                bg=CARD, fg=MUTED, cursor="hand2")
        adv_subtitle.pack(anchor="w", pady=(2, 0))
        for _w in (adv_info, adv_title, adv_subtitle):
            _w.bind("<Button-1>", lambda _: self._toggle_pkg_detail())
        self._adv_dates_header = tk.Frame(adv_hdr, bg=CARD)
        self._adv_dates_header.pack(side="right", padx=(20, 10), anchor="center")
        self._adv_dates_header.columnconfigure(0, weight=1)
        self._adv_dates_header.columnconfigure(1, weight=1)
        self._bound_field(self._adv_dates_header, 0, 0, "出貨日 YYYYMMDD", "shipment_date",
                          default=default_shipment_date(), mono=True)
        self._bound_field(self._adv_dates_header, 0, 1, "配送日 YYYYMMDD", "delivery_date",
                          default=default_delivery_date(), mono=True)
        self._pkg_expanded = False
        self._pkg_detail = tk.Frame(adv.body, bg=CARD)

        # advanced fields (inside _pkg_detail, hidden by default)
        adv_g1 = tk.Frame(self._pkg_detail, bg=CARD)
        adv_g1.pack(fill="x", padx=18, pady=(0, 12))
        adv_g1.columnconfigure(0, weight=1); adv_g1.columnconfigure(1, weight=1)
        self._combo_field(adv_g1, 0, 0, "尺寸", "spec",
                          list(SPEC_OPTIONS.keys()), default="0001  60 cm")
        self._combo_field(adv_g1, 0, 1, "配送時段", "delivery_time",
                          list(DTIME_OPTIONS.keys()), default="01 不指定")
        adv_g2 = tk.Frame(self._pkg_detail, bg=CARD)
        adv_g2.pack(fill="x", padx=18, pady=(0, 12))
        adv_g2.columnconfigure(0, weight=1)
        self._locked_field(adv_g2, 0, 0, "溫層", "thermosphere",
                           default="0001 常溫")
        adv_dates_detail = tk.Frame(self._pkg_detail, bg=CARD)
        adv_dates_detail.pack(fill="x", padx=18, pady=(0, 12))
        adv_dates_detail.columnconfigure(0, weight=1)
        adv_dates_detail.columnconfigure(1, weight=1)
        self._bound_field(adv_dates_detail, 0, 0, "出貨日 YYYYMMDD", "shipment_date",
                          default=default_shipment_date(), mono=True)
        self._bound_field(adv_dates_detail, 0, 1, "配送日 YYYYMMDD", "delivery_date",
                          default=default_delivery_date(), mono=True)
        adv_g3 = tk.Frame(self._pkg_detail, bg=CARD)
        adv_g3.pack(fill="x", padx=18, pady=(0, 12))
        adv_g3.columnconfigure(0, weight=1); adv_g3.columnconfigure(1, weight=1)
        tk.Label(adv_g3, text="日期快速設定",
                 font=(FONT_FAMILY, _sz(11), "bold"),
                 bg=CARD, fg=INK2).grid(row=0, column=0, sticky="w")
        def _quick_ship(offset):
            from datetime import date, timedelta
            d = _skip_sunday(date.today() + timedelta(days=offset))
            self.fields["shipment_date"].set(d.strftime("%Y%m%d"))
        _sbtn_row = tk.Frame(adv_g3, bg=CARD)
        _sbtn_row.grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(2, 0))
        for _lbl, _off in [("今天", 0), ("明天", 1), ("後天", 2)]:
            tk.Label(_sbtn_row, text=_lbl, font=F_TINY, bg=CARD, fg=ACCENT,
                     cursor="hand2").pack(side="left", padx=(0, 6))
        for _w, _off in zip(_sbtn_row.winfo_children(), [0, 1, 2]):
            _w.bind("<Button-1>", lambda _, o=_off: _quick_ship(o))
        def _quick_deliv(offset):
            from datetime import date, timedelta
            d = _skip_sunday(date.today() + timedelta(days=offset))
            self.fields["delivery_date"].set(d.strftime("%Y%m%d"))
        _dbtn_row = tk.Frame(adv_g3, bg=CARD)
        _dbtn_row.grid(row=1, column=1, sticky="w", padx=(0, 8), pady=(2, 0))
        for _lbl, _off in [("今天", 0), ("明天", 1), ("後天", 2)]:
            tk.Label(_dbtn_row, text=_lbl, font=F_TINY, bg=CARD, fg=ACCENT,
                     cursor="hand2").pack(side="left", padx=(0, 6))
        for _w, _off in zip(_dbtn_row.winfo_children(), [0, 1, 2]):
            _w.bind("<Button-1>", lambda _, o=_off: _quick_deliv(o))

        # 代收 toggle (in advanced)
        adv_pay = tk.Frame(self._pkg_detail, bg=CARD)
        adv_pay.pack(fill="x", padx=18, pady=(0, 14))
        adv_pay.columnconfigure(0, weight=1)
        self._toggle_group(adv_pay, 0, 0, "代收貨款", "is_collection",
                           ["N 不代收", "Y 代收（貨到付款）"], default="N 不代收",
                           on_change=self._on_collection_change)
        self._gpay_cod = tk.Frame(self._pkg_detail, bg=CARD)
        self._gpay_cod.columnconfigure(0, weight=1)
        self._field(self._gpay_cod, 0, 0, "代收金額", "collection_amount",
                    default="0", mono=True)

        # ─── 訂單編號 + 備註（全寬）─────────────────────────────────────────────
        ord_c = Card(wrap, padding=18); ord_c.pack(fill="x", pady=(0, 14))
        ord_g = tk.Frame(ord_c.body, bg=CARD); ord_g.pack(fill="x")
        ord_g.columnconfigure(0, weight=2)
        ord_g.columnconfigure(1, weight=3)
        ord_g.columnconfigure(2, weight=5)
        self._field(ord_g, 0, 0, "訂單編號", "order_id", required=True, mono=True)
        self._field(ord_g, 0, 1, "貨品名稱", "product_name", default="一般物品")
        self._field(ord_g, 0, 2, "備註", "notes", hint="會印在託運單上")

        # ─── action bar ───────────────────────────────────────────────────────
        ab = ctk.CTkFrame(wrap, fg_color=CARD, corner_radius=14,
                          border_width=1, border_color=HAIR2)
        ab.pack(fill="x", pady=(4, 0))
        ab_inner = tk.Frame(ab, bg=CARD); ab_inner.pack(fill="x", padx=18, pady=12)
        tk.Label(ab_inner, text="● 填寫收件人資料後即可建單",
                 font=F_SMALL, bg=CARD, fg=INK3).pack(side="left")
        TwButton(ab_inner, "建立寄件單  →", variant="primary",
                 command=self._submit).pack(side="right", padx=(8, 0))
        TwButton(ab_inner, "從剪貼板帶入", variant="default",
                 command=self._paste_recipient_from_clipboard).pack(side="right", padx=(4, 0))
        TwButton(ab_inner, "存入通訊錄", variant="ghost",
                 command=self._save_to_contacts).pack(side="right", padx=(4, 0))
        self._next_btn = TwButton(ab_inner, "建立下一筆  →", variant="ghost",
                                  command=self._clear_for_next)
        self._go_print_btn = TwButton(ab_inner, "前往待列印  →", variant="ghost",
                                      command=lambda: self.app.show_view("print_queue"))
        # both hidden initially; shown after first successful submit

        self.result_var = tk.StringVar()
        self.result_lbl = tk.Label(wrap, textvariable=self.result_var,
            bg=PAPER, fg=INK2, font=F_SMALL, wraplength=820, justify="left")
        self.result_lbl.pack(fill="x", pady=(10, 0))

    def _select_svc(self, svc: str):
        self._svc_var.set(svc)

    def _refresh_sender_strip(self):
        for w in self._sender_strip_frame.winfo_children():
            w.destroy()
        cfg = load_cfg()
        sender = cfg.get("sender") or {}
        name = sender.get("name") or "（未設定）"
        addr = sender.get("address") or ""
        phone = sender.get("phone") or ""
        row = tk.Frame(self._sender_strip_frame, bg=SUMMARY_BG)
        row.pack(fill="x", padx=14, pady=10)
        tk.Label(row, text="寄件人",
                 font=(FONT_FAMILY, _sz(10), "bold"),
                 fg=MUTED, bg=SUMMARY_BG).pack(side="left")
        tk.Frame(row, bg=HAIR, width=1, height=14).pack(side="left", padx=10)
        av = tk.Label(row, text=(name[:2] if name else "SA"),
                      font=(FONT_FAMILY, _sz(9), "bold"),
                      bg=ACCENT2, fg=ACCENT, width=3, pady=2)
        av.pack(side="left", padx=(0, 8))
        tk.Label(row, text=name,
                 font=(FONT_FAMILY, _sz(12), "bold"),
                 fg=INK, bg=SUMMARY_BG).pack(side="left")
        if phone or addr:
            tk.Label(row, text=f"· {phone}  {addr}",
                     font=(FONT_FAMILY, _sz(11)), fg=INK3, bg=SUMMARY_BG).pack(side="left", padx=(8, 0))
        tk.Label(row, text="切換 →",
                 font=(FONT_FAMILY, _sz(11), "bold"),
                 fg=INFO, bg=SUMMARY_BG, cursor="hand2").pack(side="right")
        tk.Label(row, text="預設",
                 font=(FONT_FAMILY, _sz(10), "bold"),
                 fg=OK, bg=SUMMARY_BG).pack(side="right", padx=(0, 10))

    def _on_collection_change(self, val: str):
        if not hasattr(self, '_gpay_cod'):
            return
        if val.startswith("Y"):
            self._gpay_cod.pack(fill="x", padx=18, pady=(0, 12))
        else:
            self._gpay_cod.pack_forget()

    def _field(self, parent, r, c, label, key, required=False, default="", mono=False, hint=None):
        cell = tk.Frame(parent, bg=_frame_bg(parent))
        cell.grid(row=r*2, column=c, sticky="ew", padx=(0 if c == 0 else 12, 0))
        field_label(cell, label, required=required, hint=hint).pack(fill="x", pady=(0, 6))
        v = tk.StringVar(value=default)
        self.fields[key] = v
        fe = FieldEntry(cell, textvariable=v, mono=mono)
        fe.pack(fill="x")
        self._field_widgets[key] = fe

    def _bound_field(self, parent, r, c, label, key, required=False, default="", mono=False, hint=None):
        cell = tk.Frame(parent, bg=_frame_bg(parent))
        cell.grid(row=r*2, column=c, sticky="ew", padx=(0 if c == 0 else 12, 0))
        field_label(cell, label, required=required, hint=hint).pack(fill="x", pady=(0, 6))
        v = self.fields.get(key)
        if v is None:
            v = tk.StringVar(value=default)
            self.fields[key] = v
        fe = FieldEntry(cell, textvariable=v, mono=mono)
        fe.pack(fill="x")
        self._field_widgets[key] = fe

    def _combo_field(self, parent, r, c, label, key, options, default=""):
        cell = tk.Frame(parent, bg=_frame_bg(parent))
        cell.grid(row=r*2, column=c, sticky="ew", padx=(0 if c == 0 else 12, 0))
        field_label(cell, label).pack(fill="x", pady=(0, 6))
        v = tk.StringVar(value=default)
        self.fields[key] = v
        cb = ttk.Combobox(cell, textvariable=v, values=options,
                          state="readonly", style="Tw.TCombobox", font=F_NORM)
        cb.pack(fill="x")

    def _locked_field(self, parent, r, c, label, key, default=""):
        cell = tk.Frame(parent, bg=_frame_bg(parent))
        cell.grid(row=r*2, column=c, sticky="ew", padx=(0 if c == 0 else 12, 0))
        field_label(cell, label).pack(fill="x", pady=(0, 6))
        v = tk.StringVar(value=default)
        self.fields[key] = v
        box = tk.Frame(cell, bg=INPUT_BORDER)
        box.pack(fill="x")
        inner = tk.Frame(box, bg=INPUT_BG, height=34)
        inner.pack(fill="x", padx=1, pady=1)
        inner.pack_propagate(False)
        tk.Label(inner, textvariable=v, font=F_NORM, bg=INPUT_BG, fg=MUTED,
                 anchor="w").pack(fill="both", expand=True, padx=11)

    def _toggle_group(self, parent, r, c, label, key, options, default="", on_change=None,
                      button_width=None):
        """Segmented toggle button group using CTkButton pills."""
        cell = tk.Frame(parent, bg=_frame_bg(parent))
        cell.grid(row=r*2, column=c, sticky="ew", padx=(0 if c == 0 else 12, 0))
        if label:
            field_label(cell, label).pack(fill="x", pady=(0, 6))

        v = tk.StringVar(value=default)
        self.fields[key] = v

        radius = 12
        container = ctk.CTkFrame(cell, fg_color=SEG_BG, corner_radius=radius,
                                 border_width=1, border_color=HAIR)
        container.pack()

        btn_map = {}

        def _refresh(*_):
            val = v.get()
            for bval, btn in btn_map.items():
                sel = (bval == val)
                btn.configure(
                    fg_color=CARD if sel else SEG_BG,
                    text_color=INK if sel else INK3,
                    font=(FONT_FAMILY, _sz(13), "bold" if sel else "normal"),
                    border_width=1 if sel else 0,
                    border_color=HAIR,
                    hover_color=HAIR2 if sel else "#D8DDE5",
                )
            if on_change:
                on_change(val)

        for opt in options:
            display = opt[2:] if len(opt) > 2 else opt
            btn_kw = {}
            if button_width is not None:
                btn_kw["width"] = button_width
            btn = ctk.CTkButton(
                container, text=display,
                font=(FONT_FAMILY, _sz(13), "normal"),
                fg_color=SEG_BG, hover_color="#D8DDE5", text_color=INK3,
                corner_radius=radius, height=38, border_width=0,
                command=lambda o=opt: v.set(o),
                **btn_kw,
            )
            btn.pack(side="left", padx=3, pady=3)
            btn_map[opt] = btn

        v.trace_add("write", _refresh)
        _refresh()

    def _get_values(self) -> dict:
        out = {}
        for k, v in self.fields.items():
            val = v.get()
            if k == "thermosphere":   val = THERMO_OPTIONS.get(val, val)
            elif k == "delivery_time": val = DTIME_OPTIONS.get(val, val)
            elif k == "spec":          val = SPEC_OPTIONS.get(val, val)
            elif k in ("is_collection", "is_freight"):
                val = "Y" if val.startswith("Y") else "N"
            out[k] = val
        return out

    def _select_category(self, label: str) -> None:
        self._cat_var.set(label)
        self.fields["notes"].set(label)
        self.fields["is_freight"].set(self._cat_map[label])

    def _clear(self):
        defaults = {
            "order_id": "", "product_name": "一般物品",
            "recipient_name": "", "recipient_phone": "", "recipient_mobile": "",
            "recipient_address": "", "spec": "0001  60 cm",
            "thermosphere": "0001 常溫", "delivery_time": "01 不指定",
            "shipment_date": default_shipment_date(),
            "delivery_date": default_delivery_date(),
            "is_freight": "N 寄件人付", "is_collection": "N 不代收",
            "collection_amount": "0", "notes": "",
        }
        for k, v in defaults.items():
            if k in self.fields: self.fields[k].set(v)
        self.result_var.set("")
        if self._cat_var:
            self._cat_var.set("")
            if hasattr(self, "_cat_seg"):
                self._cat_seg.set("")

    def _pick_contact(self):
        def on_select(contact):
            self.fields["recipient_name"].set(contact.get("name", ""))
            self.fields["recipient_phone"].set(contact.get("phone", ""))
            self.fields["recipient_mobile"].set(contact.get("mobile", ""))
            self.fields["recipient_address"].set(contact.get("address", ""))
        ContactPickerDialog(self, on_select)

    def _paste_recipient_from_clipboard(self):
        text = self._read_clipboard_text()
        if not text.strip():
            messagebox.showwarning("剪貼板是空的", "請先複製包含收件人資料的文字。")
            return

        parsed = self._parse_clipboard_recipient(text)
        to_fill = {k: v for k, v in parsed.items() if v}
        if not to_fill:
            messagebox.showwarning(
                "無法辨識收件人資料",
                "剪貼板內容中找不到可辨識的姓名、電話或地址。\n\n"
                "例如：\n王小明\n0912345678\n台北市信義區市府路1號"
            )
            return

        field_map = {"name": "recipient_name", "phone": "recipient_phone", "address": "recipient_address"}
        will_overwrite = any(
            self.fields[field_map[k]].get().strip()
            for k in to_fill if k in field_map
        )
        if will_overwrite:
            ok = messagebox.askyesno(
                "覆蓋收件人資料",
                "目前收件人欄位已有資料，要用剪貼板內容覆蓋嗎？"
            )
            if not ok:
                return

        filled_parts = []
        if to_fill.get("name"):
            self.fields["recipient_name"].set(to_fill["name"])
            filled_parts.append(to_fill["name"])
        if to_fill.get("phone"):
            self.fields["recipient_phone"].set(to_fill["phone"])
            self.fields["recipient_mobile"].set("")
            filled_parts.append(to_fill["phone"])
        if to_fill.get("address"):
            self.fields["recipient_address"].set(to_fill["address"])
            filled_parts.append(to_fill["address"])
        self.result_var.set("已從剪貼板帶入：" + "／".join(filled_parts))

    # ── staging area ─────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_pdf_rotation(path: str) -> None:
        try:
            from pypdf import PdfReader, PdfWriter
            reader = PdfReader(path)
            writer = PdfWriter()
            for page in reader.pages:
                page.transfer_rotation_to_content()
                writer.add_page(page)
            with open(path, "wb") as f:
                writer.write(f)
        except Exception:
            pass

    def _add_to_staging(self, obt: str, name: str, order_id: str, pdf_path: str) -> None:
        import datetime
        self.app._staging.append({
            "order_id": order_id,
            "name": name,
            "obt": obt,
            "pdf_path": pdf_path,
            "created_at": datetime.datetime.now().strftime("%H:%M"),
        })
        if "print_queue" in self.app.views:
            self.app.views["print_queue"].refresh()
        self.app.sidebar.update_badge("print_queue", len(self.app._staging))

    def _clear_for_next(self) -> None:
        self._clear_order_fields()
        self.result_var.set("")
        self._next_btn.pack_forget()
        self._go_print_btn.pack_forget()

    def _clear_order_fields(self) -> None:
        """建單成功後清除收件人資料與訂單號，保留包裹規格與付款設定。"""
        for key in ("recipient_name", "recipient_phone", "recipient_mobile",
                    "recipient_address", "order_id"):
            if key in self.fields:
                self.fields[key].set("")
        cat = (self._cat_seg.get() if self._cat_seg else
               self._cat_var.get() if self._cat_var else "")
        if cat:
            self.fields["notes"].set(cat)
            self.fields["is_freight"].set(self._cat_map[cat])
        else:
            self.fields["notes"].set("")

    def _read_clipboard_text(self):
        try:
            return self.clipboard_get()
        except Exception:
            pass
        if _IS_MAC:
            try:
                import subprocess as _sp
                return _sp.run(
                    ["pbpaste"], capture_output=True, timeout=2
                ).stdout.decode("utf-8", errors="replace")
            except Exception:
                pass
        return ""

    def _parse_clipboard_recipient(self, text):
        raw = text.replace("\u3000", " ").replace("：", ":")
        raw = re.sub(r"[\u200b-\u200f\ufeff]", "", raw)
        raw = raw.replace("\r\n", "\n").replace("\r", "\n")
        lines = [ln.strip(" \t,，;；") for ln in raw.split("\n") if ln.strip()]

        parsed = {"name": "", "phone": "", "address": ""}
        label_to_key = {
            "收件人姓名": "name", "收件姓名": "name", "收件人": "name",
            "姓名": "name", "名字": "name", "客戶姓名": "name",
            "收件人電話": "phone", "收件電話": "phone", "電話": "phone",
            "手機": "phone", "行動電話": "phone", "聯絡電話": "phone", "連絡電話": "phone",
            "收件人地址": "address", "收件地址": "address", "地址": "address",
            "住址": "address", "配送地址": "address",
        }
        label_names = sorted(label_to_key, key=len, reverse=True)
        label_alt = "|".join(re.escape(x) for x in label_names)
        inline_label_re = re.compile(
            rf"({label_alt})\s*:\s*(.*?)(?=\s*(?:{label_alt})\s*:|$)",
            flags=re.I | re.S,
        )
        for m in inline_label_re.finditer(raw):
            key = label_to_key.get(m.group(1))
            val = m.group(2).strip(" \t\n,，;；")
            if key and val:
                parsed[key] = self._normalize_phone(val) if key == "phone" else val

        line_label_re = re.compile(rf"^({label_alt})\s*:\s*(.+)$", flags=re.I)
        leftovers = []

        for line in lines:
            m = line_label_re.match(line)
            if m:
                key = label_to_key.get(m.group(1))
                val = m.group(2).strip(" \t,，;；")
                if key and val and not parsed[key]:
                    parsed[key] = self._normalize_phone(val) if key == "phone" else val
            else:
                leftovers.append(line)

        if not parsed["phone"]:
            phone_match = self._find_phone(raw)
            if phone_match:
                parsed["phone"] = self._normalize_phone(phone_match.group(0))

        unlabeled_lines = []
        for line in leftovers:
            without_phone = self._remove_phone_text(line).strip(" \t,，;；")
            if without_phone:
                unlabeled_lines.append(without_phone)

        if not parsed["address"]:
            parsed["address"] = self._guess_address(unlabeled_lines, raw)

        if not parsed["name"]:
            parsed["name"] = self._guess_name(unlabeled_lines, parsed["address"])

        return {k: v.strip() for k, v in parsed.items()}

    def _find_phone(self, text):
        phone_re = re.compile(r"(?:\+?886[-\s]?)?0?\d[\d\s\-()]{7,16}\d")
        for m in phone_re.finditer(text):
            digits = re.sub(r"\D", "", m.group(0))
            if digits.startswith("886"):
                digits = "0" + digits[3:]
            if 9 <= len(digits) <= 10 and digits.startswith("0"):
                return m
        return None

    def _remove_phone_text(self, text):
        m = self._find_phone(text)
        if not m:
            return text
        return (text[:m.start()] + " " + text[m.end():]).strip()

    def _normalize_phone(self, value):
        digits = re.sub(r"\D", "", value or "")
        if digits.startswith("886"):
            digits = "0" + digits[3:]
        return digits

    def _guess_address(self, lines, full_text):
        address_keywords = "縣市區鄉鎮村里路街大道段巷弄號樓室"
        for line in reversed(lines):
            m = self._find_address_start(line)
            if m:
                return line[m.start():].strip(" \t,，;；")
            if any(ch in line for ch in address_keywords) and len(line) >= 6:
                return line

        compact = self._remove_phone_text(full_text.replace("\n", " ")).strip()
        m = self._find_address_start(compact)
        if m:
            return compact[m.start():].strip(" \t,，;；")
        return ""

    def _find_address_start(self, text):
        start_re = re.compile(
            r"新北市|桃園市|高雄市|基隆市|新竹市|嘉義市|(?:台|臺)?(?:北|中|南|東)市|"
            r"(?:新竹|苗栗|彰化|南投|雲林|嘉義|屏東|宜蘭|花蓮|台東|臺東|澎湖|金門|連江)縣"
        )
        return start_re.search(text)

    def _guess_name(self, lines, address):
        for line in lines:
            if address and line == address:
                continue
            candidate = line
            if address and address in candidate:
                candidate = candidate.replace(address, "").strip(" \t,，;；")
            candidate = self._remove_phone_text(candidate).strip(" \t,，;；")
            if candidate and len(candidate) <= 20:
                return candidate
        return ""

    def _attach_autocomplete(self, key):
        """姓名欄即時搜尋通訊錄，下拉選取後自動填入電話和地址。"""
        var = self.fields.get(key)
        entry = self._field_widgets.get(key)
        if not var or not entry:
            return

        def _close():
            if self._ac_popup and self._ac_popup.winfo_exists():
                self._ac_popup.destroy()
            self._ac_popup = None

        def _fill(contact):
            var.set(contact.get("name", ""))
            self.fields["recipient_phone"].set(contact.get("phone", "") or "")
            self.fields["recipient_mobile"].set(contact.get("mobile", "") or "")
            self.fields["recipient_address"].set(contact.get("address", "") or "")
            _close()

        def _open(matches):
            _close()
            popup = tk.Toplevel(self)
            popup.overrideredirect(True)
            popup.configure(bg=HAIR)
            self._ac_popup = popup

            entry.update_idletasks()
            x = entry.winfo_rootx()
            y = entry.winfo_rooty() + entry.winfo_height() + 2
            w = max(entry.winfo_width(), 320)

            outer = tk.Frame(popup, bg=CARD,
                             highlightbackground=HAIR, highlightthickness=1)
            outer.pack(fill="both", expand=True)

            for c in matches:
                name = c.get("name", "")
                addr = (c.get("address") or "")
                phone = (c.get("phone") or c.get("mobile") or "")

                row = tk.Frame(outer, bg=CARD, cursor="hand2")
                row.pack(fill="x")
                inner = tk.Frame(row, bg=CARD)
                inner.pack(fill="x", padx=14, pady=(8, 4))
                nl = tk.Label(inner, text=name, font=F_BOLD, bg=CARD, fg=INK, anchor="w")
                nl.pack(fill="x")
                sub_parts = [p for p in [phone, addr[:40] if addr else ""] if p]
                sub = tk.Label(inner, text="  ".join(sub_parts),
                               font=F_TINY, bg=CARD, fg=MUTED, anchor="w")
                sub.pack(fill="x", pady=(0, 4))
                Hairline(outer).pack(fill="x")

                all_w = [row, inner, nl, sub]

                def _enter(_e, _ws=all_w):
                    for _w in _ws: _w.configure(bg=ACCENT2)
                def _leave(_e, _ws=all_w, _row=row):
                    try:
                        rx = _row.winfo_rootx(); ry = _row.winfo_rooty()
                        if rx <= _e.x_root < rx + _row.winfo_width() and \
                           ry <= _e.y_root < ry + _row.winfo_height():
                            return
                    except Exception:
                        pass
                    for _w in _ws: _w.configure(bg=CARD)

                for _w in all_w:
                    _w.bind("<Button-1>", lambda _e, _c=c: _fill(_c))
                    _w.bind("<Enter>", _enter)
                    _w.bind("<Leave>", _leave)

            row_h = 68
            popup.geometry(f"{w}x{len(matches) * row_h}+{x}+{y}")
            popup.lift()

        def _on_change(*_):
            text = var.get().strip()
            if len(text) < 1:
                _close()
                return
            matches = [c for c in load_contacts()
                       if text.lower() in (c.get("name") or "").lower()][:3]
            if matches:
                _open(matches)
            else:
                _close()

        var.trace_add("write", _on_change)
        entry.bind("<FocusOut>", lambda _: self.after(200, _close))
        entry.bind("<Escape>", lambda _: _close())

    def _save_to_contacts(self):
        name = self.fields["recipient_name"].get().strip()
        phone = self.fields["recipient_phone"].get().strip()
        mobile = self.fields["recipient_mobile"].get().strip()
        address = self.fields["recipient_address"].get().strip()
        if not name:
            messagebox.showwarning("缺少姓名", "請先填寫收件人姓名。"); return
        contact = {"name": name, "phone": phone, "mobile": mobile,
                   "address": address, "notes": ""}
        contacts = load_contacts()
        existing = next((i for i, c in enumerate(contacts) if c.get("name") == name), None)
        if existing is not None:
            if not messagebox.askyesno("已存在", f"「{name}」已在通訊錄，要覆蓋嗎？"): return
            contacts[existing] = contact
        else:
            contacts.append(contact)
            contacts.sort(key=lambda c: c.get("name", ""))
        save_contacts(contacts)
        if "contacts" in self.app.views:
            self.app.views["contacts"].refresh()
        messagebox.showinfo("已儲存", f"「{name}」已存入通訊錄。")

    def _toggle_pkg_detail(self):
        if self._pkg_expanded:
            self._pkg_detail.pack_forget()
            self._adv_dates_header.pack(side="right", padx=(20, 10), anchor="center")
            self._pkg_toggle_lbl.configure(text="›")
            self._pkg_expanded = False
        else:
            self._adv_dates_header.pack_forget()
            self._pkg_detail.pack(fill="x")
            self._pkg_toggle_lbl.configure(text="‹")
            self._pkg_expanded = True

    def _submit(self):
        from datetime import datetime as _dt
        values = self._get_values()
        required = {"order_id": "訂單號碼", "recipient_name": "收件人姓名",
                    "recipient_address": "收件人地址"}
        for k, label in required.items():
            if not values.get(k):
                messagebox.showwarning("缺少必填欄位", f"請填寫「{label}」"); return

        # 手機 / 市話 至少擇一
        phone = values.get("recipient_phone", "")
        mobile = values.get("recipient_mobile", "")
        if not phone and not mobile:
            messagebox.showwarning("缺少聯絡電話",
                "請至少填寫「手機」或「市話」其中一項。"); return

        # S2：電話格式寬鬆檢查（不擋送出，只警告）
        for label, val in (("手機", mobile), ("市話", phone)):
            if val and len(re.sub(r"\D", "", val)) < 8:
                messagebox.showwarning("電話格式可能有誤",
                    f"{label}「{val}」數字不足 8 碼，請確認後再送出。\n（仍可繼續送出）")
                break

        for key, label in [("shipment_date", "出貨日"), ("delivery_date", "配送日")]:
            val = values.get(key, "")
            if val:
                if len(val) != 8 or not val.isdigit():
                    messagebox.showwarning("日期格式錯誤",
                        f"「{label}」請輸入 YYYYMMDD 格式（8 位數字）。"); return
                try:
                    d = _dt.strptime(val, "%Y%m%d").date()
                    if d.weekday() == 6:
                        messagebox.showwarning("日期錯誤",
                            f"「{label}」不能是星期日（黑貓週日不配送）\n請改選週一至週六。"); return
                except ValueError:
                    messagebox.showwarning("日期格式錯誤",
                        f"「{label}」日期無效，請輸入正確的 YYYYMMDD。"); return

        # D1：出貨日不能晚於配送日
        s_val = values.get("shipment_date", "")
        d_val = values.get("delivery_date", "")
        if s_val and d_val and len(s_val) == 8 and len(d_val) == 8 and s_val.isdigit() and d_val.isdigit():
            if s_val > d_val:
                messagebox.showwarning("日期錯誤",
                    f"出貨日（{s_val}）不能晚於配送日（{d_val}），請重新確認。"); return

        cfg = load_cfg()
        sender = cfg.get("sender") or {}
        if not sender.get("name"):
            messagebox.showwarning("寄件人資料未設定", "請先到「設定」頁填寫寄件人資料。"); return

        self.result_var.set("建單中，請稍候…")
        self.result_lbl.configure(fg=MUTED)

        def run():
            try:
                client = make_client(cfg)
                Path(get_output_dir()).mkdir(parents=True, exist_ok=True)
                results = create_orders(client, [values], sender, output_dir=get_output_dir())
                r = results[0]
                if r["success"]:
                    msg = f"✓ 建單成功！OBT：{r['obt_number']}"
                    _append_build_log(f"✓ OBT:{r['obt_number']} 收件人:{values.get('recipient_name','')} 訂單:{values.get('order_id','')}")
                    append_tracking(r['obt_number'], values.get('recipient_name',''), values.get('order_id',''), sender.get('name',''))
                    if r["pdf_path"]:
                        self._normalize_pdf_rotation(r["pdf_path"])
                        self.after(0, lambda obt=r["obt_number"], nm=values["recipient_name"],
                                          oid=values["order_id"], pp=r["pdf_path"]:
                                   self._add_to_staging(obt, nm, oid, pp))
                        self.after(50, self._clear_order_fields)
                        msg += "\nPDF 已加入待列印清單，選取後按「列印選取」輸出。"
                    self.after(0, lambda: self.result_lbl.configure(fg=OK))
                    self.after(0, lambda: self._next_btn.pack(side="left", padx=(10, 0)))
                    self.after(0, lambda: self._go_print_btn.pack(side="left", padx=(10, 0)))
                else:
                    raw = r['message']
                    if "E009" in raw:
                        raw += "\n→ 品名類別已固定為 0006 3C，請確認版本為 v1.5.1 以上並在「設定」頁儲存設定後重試。"
                    msg = f"✗ 建單失敗：{raw}"
                    _append_build_log(f"✗ 訂單:{values.get('order_id','')} {raw[:80]}")
                    self.after(0, lambda: self.result_lbl.configure(fg=ERR))
                self.after(0, lambda: self.result_var.set(msg))
            except Exception as ex:
                err = f"✗ 錯誤：{ex}"
                self.after(0, lambda m=err: self.result_var.set(m))
                self.after(0, lambda: self.result_lbl.configure(fg=ERR))

        threading.Thread(target=run, daemon=True).start()


# ─── batch view ──────────────────────────────────────────────────────────────

class BatchOrderView(tk.Frame):
    """多筆建單：從通訊錄複選聯絡人，每筆可獨立設定付款 / 尺寸 / 溫層 / 備註，一次建單。"""

    def __init__(self, master, app):
        super().__init__(master, bg=PAPER)
        self.app = app
        self.rows: list[dict] = []   # each: {"data": dict, "card": Card, "widgets": dict}
        self.output_dir = get_output_dir()
        self._build()

    def _build(self):
        canvas = tk.Canvas(self, bg=PAPER, highlightthickness=0)
        vsb = ttk.Scrollbar(self, orient="vertical", command=canvas.yview,
                            style="Tw.Vertical.TScrollbar")
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        self._scroll_canvas = canvas
        _bind_mousewheel_on_hover(self, canvas)
        _bind_mousewheel_on_hover(canvas, canvas)

        wrap = tk.Frame(canvas, bg=PAPER)
        win = canvas.create_window((0, 0), window=wrap, anchor="nw")
        wrap.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))

        wrap.pack(fill="both", expand=True, padx=28, pady=24)

        # ─── header
        head = tk.Frame(wrap, bg=PAPER); head.pack(fill="x", pady=(0, 14))
        SectionHeader(head, "多筆建單", "複選聯絡人，一次建單").pack(side="left")
        ba = tk.Frame(head, bg=PAPER); ba.pack(side="right")
        TwButton(ba, "從 CSV 匯入", variant="ghost",
                 command=self._import_csv).pack(side="left", padx=4)
        TwButton(ba, "產生範本", variant="ghost",
                 command=self._gen_template).pack(side="left", padx=4)

        # ─── global defaults card
        gd = Card(wrap, padding=16); gd.pack(fill="x", pady=(0, 12))
        tk.Label(gd.body, text="全域預設",
                 font=(FONT_FAMILY, _sz(13), "bold"),
                 bg=CARD, fg=INK).pack(anchor="w")
        tk.Label(gd.body, text="新加入的收件人會套用以下預設值；已加入的不會被覆寫。",
                 font=F_TINY, bg=CARD, fg=MUTED).pack(anchor="w", pady=(2, 10))

        grid = tk.Frame(gd.body, bg=CARD); grid.pack(fill="x")
        for i in range(5): grid.columnconfigure(i, weight=1)

        self.default_spec = tk.StringVar(value="0001  60 cm")
        self.default_thermo = tk.StringVar(value="0001 常溫")
        self.default_dtime = tk.StringVar(value="01 不指定")
        self.default_shipment = tk.StringVar(value=default_shipment_date())
        self.default_delivery = tk.StringVar(value=default_delivery_date())

        self._mini_combo(grid, 0, "尺寸", self.default_spec, list(SPEC_OPTIONS.keys()))
        self._mini_locked(grid, 1, "溫層", self.default_thermo)
        self._mini_combo(grid, 2, "配送時段", self.default_dtime, list(DTIME_OPTIONS.keys()))
        self._mini_entry(grid, 3, "出貨日", self.default_shipment)
        self._mini_entry(grid, 4, "配送日", self.default_delivery)

        # ─── action row
        ar = tk.Frame(wrap, bg=PAPER); ar.pack(fill="x", pady=(0, 10))
        TwButton(ar, "+ 新增收件人", variant="primary",
                 command=self._open_picker).pack(side="left")
        TwButton(ar, "清空列表", variant="ghost",
                 command=self._clear_all).pack(side="left", padx=8)
        self.count_lbl = tk.Label(ar, text="已選 0 筆", font=F_SMALL,
                                   bg=PAPER, fg=MUTED, anchor="e")
        self.count_lbl.pack(side="right")

        # ─── rows container
        self.rows_container = tk.Frame(wrap, bg=PAPER)
        self.rows_container.pack(fill="both", expand=True)
        self.empty_lbl = tk.Label(self.rows_container,
            text="尚未加入任何收件人 — 點上方「+ 新增收件人」開始",
            font=F_SMALL, bg=PAPER, fg=MUTED, pady=40)
        self.empty_lbl.pack(fill="x")

        # ─── footer
        ft = tk.Frame(wrap, bg=PAPER); ft.pack(fill="x", pady=(14, 0))
        self.dir_lbl = tk.Label(ft, text=f"PDF 儲存目錄： {self.output_dir}",
            font=F_TINY, bg=PAPER, fg=MUTED, anchor="w")
        self.dir_lbl.pack(side="left")
        TwButton(ft, "變更目錄", variant="ghost",
                 command=self._pick_dir).pack(side="left", padx=8)

        fa = tk.Frame(ft, bg=PAPER); fa.pack(side="right")
        TwButton(fa, "全部建單  →", variant="primary",
                 command=self._submit_all).pack(side="left", padx=4)

        # ─── progress + log
        self.progress_lbl = tk.Label(wrap, text="", font=F_SMALL,
                                      bg=PAPER, fg=MUTED, anchor="w")
        self.progress_lbl.pack(fill="x", pady=(14, 2))
        self.log = scrolledtext.ScrolledText(wrap, height=6, font=F_MONO,
            bg=CARD, fg=INK2, relief="flat", state="disabled",
            highlightbackground=HAIR, highlightthickness=1)
        self.log.pack(fill="x")

    # ─── small helpers for the defaults bar ─────────────────────────────────

    def _mini_combo(self, parent, col, label, var, values):
        cell = tk.Frame(parent, bg=CARD)
        cell.grid(row=0, column=col, sticky="ew",
                  padx=(0 if col == 0 else 8, 0))
        tk.Label(cell, text=label, font=F_TINY,
                 bg=CARD, fg=MUTED).pack(anchor="w", pady=(0, 4))
        ttk.Combobox(cell, textvariable=var, values=values,
                     state="readonly", style="Tw.TCombobox",
                     font=F_NORM).pack(fill="x")

    def _mini_entry(self, parent, col, label, var):
        cell = tk.Frame(parent, bg=CARD)
        cell.grid(row=0, column=col, sticky="ew",
                  padx=(0 if col == 0 else 8, 0))
        tk.Label(cell, text=label, font=F_TINY,
                 bg=CARD, fg=MUTED).pack(anchor="w", pady=(0, 4))
        FieldEntry(cell, textvariable=var, mono=True).pack(fill="x")

    def _mini_locked(self, parent, col, label, var):
        """Locked display in disabled-entry style (matches single-order 溫層)."""
        cell = tk.Frame(parent, bg=CARD)
        cell.grid(row=0, column=col, sticky="ew",
                  padx=(0 if col == 0 else 8, 0))
        tk.Label(cell, text=label, font=F_TINY,
                 bg=CARD, fg=MUTED).pack(anchor="w", pady=(0, 4))
        box = tk.Frame(cell, bg=INPUT_BORDER); box.pack(fill="x")
        inner = tk.Frame(box, bg=INPUT_BG, height=34)
        inner.pack(fill="x", padx=1, pady=1)
        inner.pack_propagate(False)
        tk.Label(inner, textvariable=var, font=F_NORM, bg=INPUT_BG,
                 fg=MUTED, anchor="w").pack(fill="both", expand=True, padx=11)

    # ─── picker integration ─────────────────────────────────────────────────

    def _open_picker(self):
        MultiContactPickerDialog(self.winfo_toplevel(),
                                  on_select=self._add_contacts)

    def _add_contacts(self, picked: list[dict]):
        for c in picked:
            self._add_row(c)
        self._refresh_after_change()

    def _add_row(self, contact: dict):
        cat = (contact.get("category") or "").strip()
        is_freight = "Y" if cat in ("門市", "廠商") else "N"
        spec_code = SPEC_OPTIONS.get(self.default_spec.get(), "0001")
        thermo_code = THERMO_OPTIONS.get(self.default_thermo.get(), "0001")
        dtime_code = DTIME_OPTIONS.get(self.default_dtime.get(), "01")
        shipment = (self.default_shipment.get() or "").strip() or default_shipment_date()
        delivery = (self.default_delivery.get() or "").strip() or default_delivery_date()

        used_ids = {r["data"]["order_id"] for r in self.rows}
        order_id = self._make_order_id(contact, shipment, used_ids)

        data = {
            "order_id": order_id,
            "recipient_name": contact.get("name", ""),
            "recipient_phone": contact.get("phone", ""),
            "recipient_mobile": contact.get("mobile", ""),
            "recipient_address": contact.get("address", ""),
            "spec": spec_code,
            "thermosphere": thermo_code,
            "delivery_time": dtime_code,
            "shipment_date": shipment,
            "delivery_date": delivery,
            "product_name": "一般物品",
            "is_freight": is_freight,
            "is_collection": "N",
            "collection_amount": "0",
            "notes": cat,
            "_contact": contact,
        }
        card = Card(self.rows_container, padding=14)
        card.pack(fill="x", pady=(0, 8))
        row_record = {"data": data, "card": card, "widgets": {}}
        self.rows.append(row_record)
        self._render_row(row_record)

    def _make_order_id(self, contact: dict, shipment_date: str,
                       used_ids: set) -> str:
        code = (contact.get("store_id") or contact.get("brand_id") or "").strip()
        if not code:
            code = f"C{len(self.rows) + 1}"
        base = f"{code}-{shipment_date}"
        oid = base
        n = 2
        while oid in used_ids:
            oid = f"{base}-{n}"
            n += 1
        return oid

    # ─── per-row card render ────────────────────────────────────────────────

    def _label_for(self, kind: str, code: str) -> str:
        table = {"spec": SPEC_OPTIONS, "thermo": THERMO_OPTIONS,
                 "dtime": DTIME_OPTIONS}[kind]
        for label, c in table.items():
            if c == code:
                return label
        return next(iter(table))

    def _render_row(self, row_record: dict):
        card = row_record["card"]
        data = row_record["data"]
        body = card.body
        for w in body.winfo_children():
            w.destroy()
        widgets = {}
        row_record["widgets"] = widgets
        idx = self.rows.index(row_record) + 1
        contact = data.get("_contact", {})

        # ── header line: # + name (code) · category   |   delete
        top = tk.Frame(body, bg=CARD); top.pack(fill="x")
        code = (contact.get("store_id") or contact.get("brand_id") or "").strip()
        head_text = f"#{idx}  {data['recipient_name']}"
        if code:
            head_text += f"  ({code})"
        cat_label = (contact.get("category") or "").strip()
        if cat_label:
            head_text += f"  · {cat_label}"
        tk.Label(top, text=head_text,
                 font=(FONT_FAMILY, _sz(14), "bold"),
                 bg=CARD, fg=INK, anchor="w").pack(side="left")
        TwButton(top, "刪除", variant="ghost",
                 command=lambda r=row_record: self._delete_row(r)).pack(side="right")

        # ── sub line: phone / mobile / address
        sub_parts = []
        if data.get("recipient_phone"):
            sub_parts.append(f"☎ {data['recipient_phone']}")
        if data.get("recipient_mobile"):
            sub_parts.append(f"📱 {data['recipient_mobile']}")
        if data.get("recipient_address"):
            sub_parts.append(f"📍 {data['recipient_address']}")
        tk.Label(body, text="  ·  ".join(sub_parts), font=F_TINY,
                 bg=CARD, fg=MUTED, anchor="w", wraplength=1000,
                 justify="left").pack(fill="x", pady=(2, 10))

        # ── editable grid: order_id | freight | spec | thermo | dtime
        grid = tk.Frame(body, bg=CARD); grid.pack(fill="x")
        for i in range(5):
            grid.columnconfigure(i, weight=1, uniform="r")

        # order_id
        oid_var = tk.StringVar(value=data["order_id"])
        oid_var.trace_add("write",
            lambda *_a, _v=oid_var, _d=data: _d.__setitem__("order_id", _v.get()))
        widgets["order_id"] = oid_var
        self._row_field(grid, 0, "訂單編號", widget="entry",
                        var=oid_var, mono=True)

        # is_freight
        freight_var = tk.StringVar(
            value="到付" if data["is_freight"] == "Y" else "寄件人付")
        freight_var.trace_add("write",
            lambda *_a, _v=freight_var, _d=data:
                _d.__setitem__("is_freight",
                               "Y" if _v.get() == "到付" else "N"))
        widgets["is_freight"] = freight_var
        self._row_field(grid, 1, "付款", widget="combo",
                        var=freight_var, values=["到付", "寄件人付"])

        # spec
        spec_var = tk.StringVar(value=self._label_for("spec", data["spec"]))
        spec_var.trace_add("write",
            lambda *_a, _v=spec_var, _d=data:
                _d.__setitem__("spec",
                               SPEC_OPTIONS.get(_v.get(), _d["spec"])))
        widgets["spec"] = spec_var
        self._row_field(grid, 2, "尺寸", widget="combo",
                        var=spec_var, values=list(SPEC_OPTIONS.keys()))

        # thermo (locked — always 常溫 unless API supports otherwise)
        thermo_var = tk.StringVar(
            value=self._label_for("thermo", data["thermosphere"]))
        widgets["thermo"] = thermo_var
        self._row_field(grid, 3, "溫層", widget="locked", var=thermo_var)

        # delivery_time
        dtime_var = tk.StringVar(
            value=self._label_for("dtime", data["delivery_time"]))
        dtime_var.trace_add("write",
            lambda *_a, _v=dtime_var, _d=data:
                _d.__setitem__("delivery_time",
                               DTIME_OPTIONS.get(_v.get(), _d["delivery_time"])))
        widgets["dtime"] = dtime_var
        self._row_field(grid, 4, "時段", widget="combo",
                        var=dtime_var, values=list(DTIME_OPTIONS.keys()))

        # ── notes (full width)
        nrow = tk.Frame(body, bg=CARD); nrow.pack(fill="x", pady=(10, 0))
        tk.Label(nrow, text="備註", font=F_TINY,
                 bg=CARD, fg=MUTED).pack(anchor="w", pady=(0, 4))
        notes_var = tk.StringVar(value=data["notes"])
        notes_var.trace_add("write",
            lambda *_a, _v=notes_var, _d=data:
                _d.__setitem__("notes", _v.get()))
        widgets["notes"] = notes_var
        FieldEntry(nrow, textvariable=notes_var, mono=False).pack(fill="x")

    def _row_field(self, parent, col, label, widget, var,
                   values=None, mono=False):
        cell = tk.Frame(parent, bg=CARD)
        cell.grid(row=0, column=col, sticky="ew",
                  padx=(0 if col == 0 else 6, 0))
        tk.Label(cell, text=label, font=F_TINY,
                 bg=CARD, fg=MUTED).pack(anchor="w", pady=(0, 4))
        if widget == "combo":
            ttk.Combobox(cell, textvariable=var, values=values,
                         state="readonly", style="Tw.TCombobox",
                         font=F_NORM).pack(fill="x")
        elif widget == "locked":
            box = tk.Frame(cell, bg=INPUT_BORDER); box.pack(fill="x")
            inner = tk.Frame(box, bg=INPUT_BG, height=34)
            inner.pack(fill="x", padx=1, pady=1)
            inner.pack_propagate(False)
            tk.Label(inner, textvariable=var, font=F_NORM, bg=INPUT_BG,
                     fg=MUTED, anchor="w").pack(fill="both", expand=True,
                                                 padx=11)
        else:
            FieldEntry(cell, textvariable=var, mono=mono).pack(fill="x")

    def _delete_row(self, row_record):
        row_record["card"].destroy()
        self.rows.remove(row_record)
        # re-number visible rows
        for r in self.rows:
            self._render_row(r)
        self._refresh_after_change()

    def _clear_all(self):
        if not self.rows:
            return
        if not messagebox.askyesno("確認清空",
                                    "確定要清空所有已加入的收件人？"):
            return
        for r in self.rows:
            r["card"].destroy()
        self.rows = []
        self._refresh_after_change()

    def _refresh_after_change(self):
        n = len(self.rows)
        self.count_lbl.config(text=f"已選 {n} 筆",
                               fg=INK if n else MUTED)
        if n == 0:
            if not self.empty_lbl.winfo_ismapped():
                self.empty_lbl.pack(fill="x")
        else:
            if self.empty_lbl.winfo_ismapped():
                self.empty_lbl.pack_forget()

    # ─── CSV (secondary entry) ──────────────────────────────────────────────

    def _import_csv(self):
        path = filedialog.askopenfilename(
            title="選擇訂單 CSV",
            filetypes=[("CSV", "*.csv"), ("All", "*.*")],
        )
        if not path:
            return
        try:
            orders = load_orders(path)
        except Exception as ex:
            messagebox.showerror("讀取失敗", str(ex)); return
        for o in orders:
            self._add_csv_row(o)
        self._refresh_after_change()
        self._log(f"從 CSV 載入 {len(orders)} 筆 ({Path(path).name})")

    def _add_csv_row(self, csv_row: dict):
        contact = {
            "name": csv_row.get("recipient_name", ""),
            "phone": csv_row.get("recipient_phone", ""),
            "mobile": csv_row.get("recipient_mobile", ""),
            "address": csv_row.get("recipient_address", ""),
            "category": "",
        }
        is_freight = ("Y" if str(csv_row.get("is_freight", "N")).upper()
                      .startswith("Y") else "N")
        data = {
            "order_id": csv_row.get("order_id", "") or self._make_order_id(
                contact,
                (csv_row.get("shipment_date") or default_shipment_date()),
                {r["data"]["order_id"] for r in self.rows}),
            "recipient_name": csv_row.get("recipient_name", ""),
            "recipient_phone": csv_row.get("recipient_phone", ""),
            "recipient_mobile": csv_row.get("recipient_mobile", ""),
            "recipient_address": csv_row.get("recipient_address", ""),
            "spec": csv_row.get("spec") or "0001",
            "thermosphere": csv_row.get("thermosphere") or "0001",
            "delivery_time": csv_row.get("delivery_time") or "01",
            "shipment_date": csv_row.get("shipment_date") or default_shipment_date(),
            "delivery_date": csv_row.get("delivery_date") or default_delivery_date(),
            "product_name": csv_row.get("product_name") or "一般物品",
            "is_freight": is_freight,
            "is_collection": csv_row.get("is_collection") or "N",
            "collection_amount": csv_row.get("collection_amount") or "0",
            "notes": csv_row.get("notes") or "",
            "_contact": contact,
        }
        card = Card(self.rows_container, padding=14)
        card.pack(fill="x", pady=(0, 8))
        row_record = {"data": data, "card": card, "widgets": {}}
        self.rows.append(row_record)
        self._render_row(row_record)

    def _gen_template(self):
        path = filedialog.asksaveasfilename(
            title="儲存 CSV 範本",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile="orders_template.csv",
        )
        if path:
            generate_template(path)
            messagebox.showinfo("完成", f"範本已儲存至：\n{path}")

    # ─── output dir + log + submit ──────────────────────────────────────────

    def _pick_dir(self):
        d = filedialog.askdirectory(title="選擇 PDF 儲存目錄",
                                     initialdir=self.output_dir)
        if d:
            self.output_dir = d
            self.dir_lbl.config(text=f"PDF 儲存目錄： {self.output_dir}")

    def _log(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _submit_all(self):
        if not self.rows:
            messagebox.showwarning("尚未加入",
                                    "請先按「+ 新增收件人」選擇至少一筆。"); return
        cfg = load_cfg()
        sender = cfg.get("sender") or {}
        if not sender.get("name"):
            messagebox.showwarning("寄件人資料未設定",
                                    "請先到「設定」頁填寫寄件人資料。"); return

        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        rows_snapshot = [dict(r["data"]) for r in self.rows]
        total = len(rows_snapshot)
        self._log(f"開始建單，共 {total} 筆…")
        self.after(0, lambda: self.progress_lbl.config(
            text=f"建單中 0 / {total} 筆…", fg=MUTED))

        # Map snapshot index back to live row for selective removal after build
        live_refs = list(self.rows)

        def run():
            import datetime
            client = make_client(cfg)
            success_indices: set[int] = set()
            for i, order in enumerate(rows_snapshot, 1):
                oid = order.get("order_id", f"#{i}")
                try:
                    api_order = _csv_row_to_api_order(order, sender)
                    resp = client.print_obt([api_order])
                    if resp.get("IsOK") == "Y":
                        data = resp.get("Data") or {}
                        if isinstance(data, list) and data: data = data[0]
                        orders_list = data.get("Orders") or []
                        obt = orders_list[0].get("OBTNumber", "") if orders_list else ""
                        file_no = data.get("FileNo", "")
                        if obt:
                            append_tracking(obt,
                                            order.get("recipient_name", ""),
                                            oid,
                                            sender.get("name", ""))
                        pdf_path = ""
                        if file_no:
                            try:
                                pdf_bytes = client.download_obt(file_no)
                                pdf_path = str(Path(self.output_dir) / f"{oid}_{obt}.pdf")
                                with open(pdf_path, "wb") as pf:
                                    pf.write(pdf_bytes)
                                SingleOrderView._normalize_pdf_rotation(pdf_path)
                            except Exception as pex:
                                pdf_path = ""
                                self.after(0, lambda o=oid, e=str(pex):
                                    self._log(f"⚠ {o}  PDF 下載失敗：{e[:60]}"))
                        if pdf_path:
                            self.app._staging.append({
                                "order_id": oid,
                                "name": order.get("recipient_name", ""),
                                "obt": obt,
                                "pdf_path": pdf_path,
                                "created_at": datetime.datetime.now().strftime("%H:%M"),
                            })
                            self.after(0, lambda o=oid, n=obt: self._log(f"✓ {o}  OBT:{n}"))
                            _append_build_log(f"✓ OBT:{obt} 訂單:{oid}")
                        else:
                            self.after(0, lambda o=oid, n=obt: self._log(f"✓ {o}  OBT:{n}  (PDF未存)"))
                            _append_build_log(f"✓ OBT:{obt} 訂單:{oid} (PDF未存)")
                        success_indices.add(i - 1)
                    else:
                        msg = resp.get("Message", "")[:60]
                        self.after(0, lambda o=oid, m=msg: self._log(f"✗ {o}: {m}"))
                        _append_build_log(f"✗ 訂單:{oid} {msg}")
                except Exception as ex:
                    self.after(0, lambda o=oid, e=str(ex): self._log(f"✗ {o}: {e}"))
                    _append_build_log(f"✗ 訂單:{oid} 例外:{str(ex)[:80]}")
                self.after(0, lambda _i=i, _t=total: self.progress_lbl.config(
                    text=f"建單中 {_i} / {_t} 筆…", fg=MUTED))

            self.after(0, lambda: self._post_submit(total, success_indices, live_refs))

        threading.Thread(target=run, daemon=True).start()

    def _post_submit(self, total: int, success_indices: set, live_refs: list):
        # refresh 待列印 + 貨運查詢 + sidebar badge
        if "print_queue" in self.app.views:
            self.app.views["print_queue"].refresh()
        if hasattr(self.app, "sidebar"):
            self.app.sidebar.update_badge("print_queue", len(self.app._staging))
        if "tracking" in self.app.views:
            self.app.views["tracking"].refresh()

        # 移除成功的列（用 snapshot 時保存的 live 參考定位）
        for idx in sorted(success_indices, reverse=True):
            if idx >= len(live_refs):
                continue
            record = live_refs[idx]
            if record in self.rows:
                record["card"].destroy()
                self.rows.remove(record)
        # 重新編號剩餘列
        for r in self.rows:
            self._render_row(r)
        self._refresh_after_change()

        success = len(success_indices)
        if success == total:
            msg = f"✓ 完成 {success} 筆 — 已加入「待列印」與「貨運查詢」"
            self.progress_lbl.config(text=msg, fg=OK)
            self._log(f"── {msg} ──")
        else:
            fail = total - success
            msg = f"完成 {success}/{total}；失敗 {fail} 筆已保留可重試"
            self.progress_lbl.config(text=msg, fg=WARN)
            self._log(f"── {msg} ──")


# ─── t-cat status query ──────────────────────────────────────────────────────

def _status_fg(status: str) -> str:
    """Return foreground colour for a given status string."""
    # 官方貨態一覽表（黑貓宅急便）
    _OK   = {"順利送達"}                           # 已完成，綠色
    _ERR  = {"取消取件", "無效單號", "查無紀錄",
             "無法解析"}                            # 異常，紅色
    _ERR_KW = ("未順利", "失敗", "錯誤")           # 含這些字也算紅色
    if status in _OK:
        return OK
    if status in _ERR or any(k in status for k in _ERR_KW):
        return ERR
    if status in ("—", "查詢中…"):
        return MUTED
    return WARN   # 其餘進行中貨態（已集貨/轉運中/配送中/暫置/調查…）橙色


def _fetch_obt_status(obt: str) -> str:
    """
    向黑貓官網查詢單一 OBT 的最新配送狀態。
    回傳繁體中文狀態字串，查不到或出錯時回傳說明文字。
    """
    import urllib.request, urllib.parse, ssl, re

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    base = "https://www.t-cat.com.tw/inquire/trace.aspx"

    # Step 1: GET — 取得 VIEWSTATE 等 ASP.NET 表單欄位
    try:
        req = urllib.request.Request(base,
            headers={"User-Agent": ua, "Accept-Language": "zh-TW,zh;q=0.9"})
        with urllib.request.urlopen(req, context=ctx, timeout=10) as r:
            html = r.read().decode("utf-8", errors="ignore")
    except Exception as e:
        return f"網路錯誤：{str(e)[:40]}"

    def _find(pattern):
        m = re.search(pattern, html)
        return m.group(1) if m else ""

    vs  = _find(r'id="__VIEWSTATE" value="([^"]+)"')
    vsg = _find(r'id="__VIEWSTATEGENERATOR" value="([^"]+)"')
    evt = _find(r'id="__EVENTVALIDATION" value="([^"]+)"')

    # Step 2: POST — 送出查詢
    payload = urllib.parse.urlencode({
        "__VIEWSTATE": vs,
        "__VIEWSTATEGENERATOR": vsg,
        "__EVENTVALIDATION": evt,
        "ctl00$ContentPlaceHolder1$txtQuery1": obt.strip(),
        "ctl00$ContentPlaceHolder1$btnSend": "確認送出",
    }).encode("utf-8")

    try:
        req2 = urllib.request.Request(base, data=payload, headers={
            "User-Agent": ua,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": base,
            "Accept-Language": "zh-TW,zh;q=0.9",
        })
        with urllib.request.urlopen(req2, context=ctx, timeout=15) as r:
            html2 = r.read().decode("utf-8", errors="ignore")
    except Exception as e:
        return f"查詢失敗：{str(e)[:40]}"

    # 無效單號 → alert('XXXXX 非有效單號 !!')
    inv = re.search(r"alert\('([^']+非有效單號[^']*)'\)", html2)
    if inv:
        return "無效單號"

    # 擷取查詢結果區塊（<!-- 查詢結果1 --> … <!-- 查詢結果2 -->）
    m = re.search(r"<!--\s*查詢結果1\s*-->(.*?)<!--\s*查詢結果2\s*-->", html2, re.DOTALL)
    if not m or not m.group(1).strip():
        return "查無紀錄"

    result_html = m.group(1)
    # 移除 script / style
    result_html = re.sub(r"<script[^>]*>.*?</script>", "", result_html, flags=re.DOTALL)
    result_html = re.sub(r"<style[^>]*>.*?</style>",  "", result_html, flags=re.DOTALL)
    # 純文字
    text = re.sub(r"<[^>]+>", " ", result_html)
    text = re.sub(r"\s+", " ", text).strip()

    if not text:
        return "查無紀錄"

    # 精確比對：找 "{OBT} 目前狀態 {value} 資料登入時間" 格式
    # 擷取到「資料登入」之前的所有文字作為狀態（支援多字狀態）
    m_obt = re.search(
        re.escape(obt.strip()) + r"\s+目前狀態\s+(.+?)\s+資料登入",
        text
    )
    if m_obt:
        return m_obt.group(1).strip()

    # fallback：抓第一個「目前狀態 {value} 資料登入」
    m_st = re.search(r"目前狀態\s+(.+?)\s+資料登入", text)
    if m_st:
        return m_st.group(1).strip()

    return "無法解析"


# ─── tracking view ───────────────────────────────────────────────────────────

_TRK_GCOLS = [
    # (header_text, minsize_px, weight)
    ("配送狀態",   85, 0),
    ("出貨日",     85, 0),
    ("托運單號",  140, 0),
    ("收件人姓名", 150, 2),
    ("寄件人",     130, 2),
    ("備註",      140, 2),
    ("",          120, 0),  # buttons col
]

def _apply_trk_grid(frame):
    for i, (_, mn, w) in enumerate(_TRK_GCOLS):
        frame.columnconfigure(i, minsize=mn, weight=w)

class TrackingView(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg=PAPER)
        self.app = app
        self._records = []
        self._filter = "all"   # all / progress / ok / err
        self._status_labels: dict[str, tk.Label] = {}
        self._filter_btns: dict[str, tk.Label] = {}
        self._count_lbls: dict[str, tk.Label] = {}
        self._last_sync_ts: float = 0   # epoch，用於自動同步冷卻
        self._build()

    def _build(self):
        wrap = tk.Frame(self, bg=PAPER)
        wrap.pack(fill="both", expand=True, padx=28, pady=24)

        # section header
        head = tk.Frame(wrap, bg=PAPER); head.pack(fill="x", pady=(0, 14))
        SectionHeader(head, "貨運查詢", "貨運單號查詢").pack(side="left")
        ba = tk.Frame(head, bg=PAPER); ba.pack(side="right")
        TwButton(ba, "全部查詢狀態", variant="default",
                 command=self._query_all).pack(side="left", padx=4)
        self._sync_btn = TwButton(ba, "同步 14 天紀錄", variant="ghost",
                 command=self._sync_from_web)
        self._sync_btn.pack(side="left", padx=4)
        TwButton(ba, "清除兩週前紀錄", variant="ghost", command=self._prune).pack(side="left", padx=4)

        # sync progress bar (hidden until sync starts)
        self._sync_prog_frame = tk.Frame(wrap, bg=PAPER)
        self._sync_prog_lbl = tk.Label(self._sync_prog_frame, text="", font=F_TINY,
                                       bg=PAPER, fg=MUTED, anchor="w")
        self._sync_prog_lbl.pack(side="left", padx=(0, 10))
        self._sync_prog_bar = ttk.Progressbar(self._sync_prog_frame, orient="horizontal",
                                              mode="determinate", length=200)
        self._sync_prog_bar.pack(side="left")
        # not packed yet — shown only during sync

        # stats row (4 cards)
        self.stats_row = tk.Frame(wrap, bg=PAPER)
        self.stats_row.pack(fill="x", pady=(0, 14))
        for i, (key, label, color) in enumerate([
            ("total",    "近 14 天紀錄", INK),
            ("ok",       "順利送達",     OK),
            ("progress", "配送中",       WARN),
            ("err",      "異常",         ERR),
        ]):
            sc = Card(self.stats_row, padding=14)
            sc.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 8, 0))
            self.stats_row.columnconfigure(i, weight=1)
            krow = tk.Frame(sc.body, bg=CARD); krow.pack(fill="x")
            Kicker(krow, label).pack(side="left")
            if key != "total":
                tk.Label(krow, text="●", font=(FONT_FAMILY, _sz(8)),
                         bg=CARD, fg=color).pack(side="right")
            vrow = tk.Frame(sc.body, bg=CARD); vrow.pack(anchor="w")
            num = tk.Label(vrow, text="0", font=(MONO_FAMILY, _sz(20), "bold"),
                           bg=CARD, fg=color)
            num.pack(side="left")
            tk.Label(vrow, text=" 筆", font=F_TINY, bg=CARD, fg=MUTED).pack(side="left", pady=(4, 0))
            self._count_lbls[key] = num

        # manual add card
        ac = Card(wrap, padding=14); ac.pack(fill="x", pady=(0, 14))
        add_bar = tk.Frame(ac.body, bg=CARD); add_bar.pack(fill="x")
        Kicker(add_bar, "手動新增").pack(side="left", padx=(0, 14))
        self._add_obt_var  = tk.StringVar()
        self._add_name_var = tk.StringVar()
        e_obt = tk.Entry(add_bar, textvariable=self._add_obt_var,
                         font=F_MONO, relief="flat", bg=HAIR3, fg=INK,
                         highlightthickness=1, highlightbackground=HAIR,
                         width=20)
        e_obt.pack(side="left", padx=(0, 8), ipady=5)
        e_name = tk.Entry(add_bar, textvariable=self._add_name_var,
                          font=F_NORM, relief="flat", bg=HAIR3, fg=INK,
                          highlightthickness=1, highlightbackground=HAIR,
                          width=14)
        e_name.pack(side="left", padx=(0, 8), ipady=5)
        TwButton(add_bar, "新增到清單", variant="default",
                 command=self._manual_add).pack(side="left")
        e_obt.bind("<Return>", lambda _: self._manual_add())

        # table card (filter tabs + rows)
        tcard = Card(wrap, padding=0)
        tcard.pack(fill="both", expand=True)

        # filter tab bar
        tab_bar = tk.Frame(tcard.body, bg=CARD)
        tab_bar.pack(fill="x", pady=(0, 0))
        tab_inner = tk.Frame(tab_bar, bg=CARD); tab_inner.pack(side="left", padx=10, pady=10)
        for fid, flabel in [("all","全部"),("progress","配送中"),("ok","順利送達"),("err","異常")]:
            btn = tk.Label(tab_inner, text=flabel, font=(FONT_FAMILY, _sz(11), "bold"),
                           bg=INK if fid == "all" else CARD,
                           fg="#FFFFFF" if fid == "all" else INK2,
                           padx=10, pady=5, cursor="hand2")
            btn.pack(side="left", padx=(0, 4))
            btn.bind("<Button-1>", lambda e, _f=fid: self._set_filter(_f))
            self._filter_btns[fid] = btn
        self._result_count = tk.Label(tab_bar, text="", font=F_TINY, bg=CARD, fg=MUTED)
        self._result_count.pack(side="right", padx=(0, 14))
        refresh_btn = tk.Label(tab_bar, text="↻", font=(FONT_FAMILY, _sz(14)),
                               bg=CARD, fg=MUTED, cursor="hand2", padx=4)
        refresh_btn.pack(side="right", padx=(0, 2))
        refresh_btn.bind("<Button-1>", lambda e: self.refresh())
        refresh_btn.bind("<Enter>", lambda e: refresh_btn.config(fg=INK))
        refresh_btn.bind("<Leave>", lambda e: refresh_btn.config(fg=MUTED))
        self._last_sync_lbl = tk.Label(tab_bar, text="尚未同步", font=F_TINY, bg=CARD, fg=MUTED)
        self._last_sync_lbl.pack(side="right", padx=(0, 4))
        Hairline(tcard.body).pack(fill="x")

        # column header
        hdr = tk.Frame(tcard.body, bg=PAPER2)
        hdr.pack(fill="x", padx=4)
        _apply_trk_grid(hdr)
        for i, (txt, mn, w) in enumerate(_TRK_GCOLS):
            if txt:
                tk.Label(hdr, text=txt, font=F_KICKER, bg=PAPER2, fg=MUTED,
                         anchor="w").grid(row=0, column=i, sticky="ew", padx=(10, 4), pady=8)
        Hairline(tcard.body).pack(fill="x")

        # scrollable list
        lf = tk.Frame(tcard.body, bg=CARD)
        lf.pack(fill="both", expand=True)
        canvas = tk.Canvas(lf, bg=CARD, highlightthickness=0)
        vsb = ttk.Scrollbar(lf, orient="vertical", command=canvas.yview,
                            style="Tw.Vertical.TScrollbar")
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.configure(yscrollcommand=vsb.set)
        self._list_body = tk.Frame(canvas, bg=CARD)
        self._list_win = canvas.create_window((0, 0), window=self._list_body, anchor="nw")
        self._list_body.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
            lambda e: canvas.itemconfig(self._list_win, width=e.width))
        self._scroll_canvas = canvas
        _bind_mousewheel_on_hover(self._list_body, canvas)
        _bind_mousewheel_on_hover(canvas, canvas)
        self.refresh()

    def _status_tone(self, status: str) -> str:
        if _status_fg(status) == OK:  return "ok"
        if _status_fg(status) == ERR: return "err"
        if status in ("—", "查詢中…", "請按查詢確認"): return "neutral"
        return "progress"

    def _set_filter(self, fid: str):
        self._filter = fid
        for k, btn in self._filter_btns.items():
            sel = k == fid
            btn.configure(bg=INK if sel else CARD,
                          fg="#FFFFFF" if sel else INK2)
        self._render_rows()

    def on_show(self):
        self.refresh()
        # 進入頁面自動靜默查詢狀態（距上次查詢超過 5 分鐘才觸發）
        import time as _t
        if (_t.time() - self._last_sync_ts) > 300:
            self._query_all(silent=True)

    def refresh(self):
        import datetime
        records = load_tracking()
        cutoff = (datetime.datetime.now() - datetime.timedelta(days=14)).isoformat()
        records = [r for r in records
                   if _normalize_created_at(r.get("created_at", "")) >= cutoff]
        records.sort(
            key=lambda r: _normalize_created_at(r.get("created_at", "")),
            reverse=True)
        self._records = records

        # update stats cards
        counts = {"total": len(records), "ok": 0, "progress": 0, "err": 0}
        for r in records:
            tone = self._status_tone(r.get("status", "—"))
            if tone in counts: counts[tone] += 1
        for key, lbl in self._count_lbls.items():
            lbl.config(text=str(counts.get(key, 0)))

        self._render_rows()

    def _render_rows(self):
        for w in self._list_body.winfo_children():
            w.destroy()
        self._status_labels.clear()

        filt = self._filter
        shown = [r for r in self._records
                 if (filt == "all" and self._status_tone(r.get("status","—")) != "ok")
                 or (filt != "all" and self._status_tone(r.get("status","—")) == filt)]

        self._result_count.config(text=f"顯示 {len(shown)} 筆")

        if not shown:
            msg = "此分類沒有資料"
            tk.Label(self._list_body, text=msg,
                     bg=CARD, fg=MUTED, font=F_SMALL, justify="center").pack(pady=60)
            return

        for i, r in enumerate(shown):
            self._make_row(r, i < len(shown) - 1)
        tk.Frame(self._list_body, bg=CARD, height=12).pack()

    def _make_row(self, r: dict, divider=True):
        obt     = r.get("obt_number", "—")
        name    = r.get("recipient_name", "—")
        sender  = r.get("sender_name", "")
        snt     = r.get("created_at", "")[:10]   # 出貨日 YYYY/MM/DD 或 YYYY-MM-DD
        status  = r.get("status", "—")
        notes   = r.get("notes", "")
        queried = r.get("queried_at", "")

        row = tk.Frame(self._list_body, bg=CARD)
        row.pack(fill="x")
        inner = tk.Frame(row, bg=CARD)
        inner.pack(fill="x", padx=4, pady=8)
        _apply_trk_grid(inner)

        # status pill
        stone = self._status_tone(status)
        pill_bg = {"ok": OK2, "err": ERR2, "progress": WARN2, "neutral": HAIR3}.get(stone, HAIR3)
        pill_fg = {"ok": OK,  "err": ERR,  "progress": WARN,  "neutral": MUTED}.get(stone, MUTED)
        slbl = tk.Label(inner, text=f"● {status}", font=F_TINY, bg=pill_bg, fg=pill_fg,
                        padx=7, pady=3, anchor="w", width=1)
        slbl.grid(row=0, column=0, sticky="ew", padx=(10, 4), pady=2)
        self._status_labels[obt] = slbl
        if queried:
            slbl.bind("<Enter>", lambda e, t=queried: slbl.config(text=f"查詢 {t[11:16]}"))
            slbl.bind("<Leave>", lambda e, s=status: slbl.config(text=f"● {s}"))

        tk.Label(inner, text=snt,    font=F_TINY, bg=CARD, fg=MUTED, anchor="w").grid(row=0, column=1, sticky="ew", padx=(10, 4), pady=2)
        tk.Label(inner, text=obt,    font=F_MONO, bg=CARD, fg=INK,   anchor="w").grid(row=0, column=2, sticky="ew", padx=(10, 4), pady=2)
        tk.Label(inner, text=name,   font=F_NORM, bg=CARD, fg=INK,   anchor="w").grid(row=0, column=3, sticky="ew", padx=(10, 4), pady=2)
        tk.Label(inner, text=sender, font=F_TINY, bg=CARD, fg=INK2,  anchor="w").grid(row=0, column=4, sticky="ew", padx=(10, 4), pady=2)
        tk.Label(inner, text=notes,  font=F_TINY, bg=CARD, fg=MUTED, anchor="w").grid(row=0, column=5, sticky="ew", padx=(10, 4), pady=2)

        btns = tk.Frame(inner, bg=CARD)
        btns.grid(row=0, column=6, sticky="e", padx=(4, 8), pady=2)
        TwButton(btns, "查詢", variant="ghost",
                 command=lambda _obt=obt: self._query_one(_obt)).pack(side="left", padx=(0, 4))
        TwButton(btns, "複製", variant="ghost",
                 command=lambda _obt=obt: self._copy(_obt)).pack(side="left", padx=(0, 4))
        TwButton(btns, "刪除", variant="ghost",
                 command=lambda _obt=obt: self._delete_one(_obt)).pack(side="left", padx=(0, 8))
        _clbl = tk.Label(btns, text="取消配送", font=(FONT_FAMILY, _sz(9)), fg=ERR, bg=CARD,
                         cursor="hand2")
        _clbl.pack(side="left", padx=(0, 4))
        _clbl.bind("<Button-1>", lambda e, _obt=obt, _n=name: self._cancel_obt(_obt, _n))

        if divider:
            Hairline(self._list_body).pack(fill="x")

    def _manual_add(self):
        obt  = self._add_obt_var.get().strip()
        name = self._add_name_var.get().strip() or "—"
        if not obt:
            messagebox.showwarning("請填寫單號", "請輸入貨運單號後再新增。", parent=self)
            return
        records = load_tracking()
        if any(r.get("obt_number") == obt for r in records):
            messagebox.showinfo("已存在", f"單號 {obt} 已在清單中。", parent=self)
            return
        append_tracking(obt, name, "—")
        self._add_obt_var.set("")
        self._add_name_var.set("")
        self.refresh()

    def _cancel_obt(self, obt: str, name: str):
        """Show confirmation dialog then call CancelOBT API."""
        dlg = tk.Toplevel(self)
        dlg.title("取消宅配單")
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.configure(bg=PAPER)

        f = tk.Frame(dlg, bg=PAPER, padx=32, pady=24); f.pack()
        tk.Label(f, text="確認取消宅配單？", font=(FONT_FAMILY, _sz(14), "bold"),
                 bg=PAPER, fg=INK).pack(pady=(0, 18))

        info = tk.Frame(f, bg=HAIR3, padx=18, pady=14); info.pack(fill="x", pady=(0, 18))
        for label, val in [("宅配單號", obt), ("收件人", name)]:
            row = tk.Frame(info, bg=HAIR3); row.pack(fill="x", pady=3)
            tk.Label(row, text=label, font=F_KICKER, bg=HAIR3, fg=MUTED, width=8, anchor="w").pack(side="left")
            tk.Label(row, text=val,   font=F_MONO,   bg=HAIR3, fg=INK,   anchor="w").pack(side="left")

        msg_lbl = tk.Label(f, text="", font=F_SMALL, bg=PAPER, fg=ERR)
        msg_lbl.pack(pady=(0, 10))

        btn_row = tk.Frame(f, bg=PAPER); btn_row.pack()

        def _do_cancel():
            msg_lbl.config(
                text="取消中…黑貓 API 處理可能需 1~2 分鐘，請耐心等待",
                fg=MUTED)
            for b in btn_row.winfo_children(): b.configure(state="disabled")
            cfg = load_cfg()
            client = make_client(cfg)
            def run():
                try:
                    resp = client.cancel_obt(obt)   # 傳 str（內部已處理）
                    # 黑貓 API 回應格式：{"IsOK":"Y"|"N","Message":"...","Data":...}
                    ok = (resp.get("IsOK") == "Y"
                          or resp.get("IsSuccess")
                          or resp.get("Success")
                          or str(resp.get("ReturnCode","")) == "0000")
                    if ok:
                        _append_build_log(f"✗ 取消 OBT:{obt} 收件人:{name}")
                        records = load_tracking()
                        for r in records:
                            if r.get("obt_number") == obt:
                                r["status"] = "已取消"
                        save_tracking(records)
                        self.after(0, lambda: (dlg.destroy(), self.refresh(),
                            messagebox.showinfo("取消成功", f"宅配單 {obt} 已成功取消。", parent=self)))
                    else:
                        raw = (resp.get("Message")
                               or resp.get("ReturnMessage")
                               or str(resp))
                        self.after(0, lambda m=raw: (
                            msg_lbl.config(text=f"取消失敗：{m[:120]}", fg=ERR),
                            [b.configure(state="normal") for b in btn_row.winfo_children()]))
                except Exception as ex:
                    msg = str(ex)
                    if "timed out" in msg.lower():
                        hint = "API 逾時（>180 秒未回應），請稍後再試或到客樂得手動取消"
                    elif "500" in msg:
                        hint = f"伺服器錯誤：{msg[:120]}"
                    else:
                        hint = msg[:120]
                    self.after(0, lambda h=hint: (
                        msg_lbl.config(text=h, fg=ERR),
                        [b.configure(state="normal") for b in btn_row.winfo_children()]))
            import threading; threading.Thread(target=run, daemon=True).start()

        tk.Button(btn_row, text="確認取消宅配", font=(FONT_FAMILY, _sz(12), "bold"),
                  bg=HAIR3, fg=INK, relief="flat", padx=16, pady=6,
                  cursor="hand2", command=_do_cancel).pack(side="left", padx=(0, 10))
        tk.Button(btn_row, text="返回", font=(FONT_FAMILY, _sz(12)),
                  bg=HAIR3, fg=INK2, relief="flat", padx=16, pady=6,
                  cursor="hand2", command=dlg.destroy).pack(side="left")

    def _delete_one(self, obt: str):
        if not messagebox.askyesno("確認刪除",
                f"確定要刪除單號 {obt} 的紀錄嗎？\n\n刪除後此單號不會再被同步回來。", parent=self):
            return
        records = load_tracking()
        records = [r for r in records if r.get("obt_number") != obt]
        save_tracking(records)
        add_deleted_obt(obt)
        # 同步清 EPB 調撥 log，讓對應調撥單可重建
        _cleanup_epb_log_for_obt(obt)
        self.refresh()

    def _set_status(self, obt: str, status: str):
        import datetime
        lbl = self._status_labels.get(obt)
        if lbl and lbl.winfo_exists():
            stone = self._status_tone(status)
            pill_bg = {"ok": OK2, "err": ERR2, "progress": WARN2, "neutral": HAIR3}.get(stone, HAIR3)
            pill_fg = {"ok": OK, "err": ERR, "progress": WARN, "neutral": MUTED}.get(stone, MUTED)
            lbl.config(text=f"● {status}", bg=pill_bg, fg=pill_fg)

        # persist
        now = datetime.datetime.now().isoformat(timespec="seconds")
        records = load_tracking()
        for rec in records:
            if rec.get("obt_number") == obt:
                rec["status"] = status
                rec["queried_at"] = now
                break
        save_tracking(records)

    def _query_one(self, obt: str):
        lbl = self._status_labels.get(obt)
        if lbl and lbl.winfo_exists():
            lbl.config(text="● 查詢中…", bg=HAIR3, fg=MUTED)

        def run():
            result = _fetch_obt_status(obt)
            self.after(0, lambda: self._set_status(obt, result))

        threading.Thread(target=run, daemon=True).start()

    def _query_all(self, silent: bool = False):
        obts = [r.get("obt_number") for r in self._records
                if r.get("obt_number") and r.get("status") != "順利送達"]
        for obt in obts:
            lbl = self._status_labels.get(obt)
            if lbl and lbl.winfo_exists():
                lbl.config(text="● 查詢中…", bg=HAIR3, fg=MUTED)

        def run():
            for obt in obts:
                result = _fetch_obt_status(obt)
                self.after(0, lambda _o=obt, _r=result: self._set_status(_o, _r))
            import datetime, time as _t
            self._last_sync_ts = _t.time()
            def _done(n=len(obts)):
                import datetime
                now_str = datetime.datetime.now().strftime("%H:%M")
                self._last_sync_lbl.config(text=f"最後更新 {now_str}")
                if not silent:
                    messagebox.showinfo("查詢完成", f"已完成 {n} 筆托運單狀態查詢。")
            self.after(0, _done)

        threading.Thread(target=run, daemon=True).start()

    def _copy(self, text: str):
        self.clipboard_clear()
        self.clipboard_append(text)

    def _sync_from_web(self, silent: bool = False):
        """Pull the last 14 days of OBT records from the web portal and merge into tracking.json."""
        if self.app._web is None:
            if not silent:
                messagebox.showinfo("尚未登入",
                    "請先到「費用查詢」頁完成契客專區登入，再回來同步。")
            return

        import datetime, threading
        today = datetime.date.today()
        start_date = today - datetime.timedelta(days=13)   # 近 14 天（含今天）
        start = start_date.strftime("%Y%m%d")
        end   = today.strftime("%Y%m%d")
        start_label = start_date.strftime("%-m/%-d")
        end_label   = today.strftime("%-m/%-d")

        def _map_pkg_status(ds: str) -> str:
            if "配完" in ds:
                return "順利送達"
            return "請按查詢確認"

        def _show_fetching():
            self._sync_prog_bar.configure(mode="indeterminate", value=0)
            self._sync_prog_bar.start(12)
            self._sync_prog_lbl.configure(text="正在從網站抓取資料…")
            self._sync_prog_frame.pack(fill="x", pady=(0, 10), before=self.stats_row)
            self._sync_btn.configure(state="disabled")

        def _show_detail_progress(total: int):
            self._sync_prog_bar.stop()
            self._sync_prog_bar.configure(mode="determinate", maximum=max(total, 1), value=0)
            self._sync_prog_lbl.configure(text=f"抓取詳細資料 0 / {total} 筆…")

        def _update_progress(done: int, total: int):
            self._sync_prog_bar.configure(value=done)
            self._sync_prog_lbl.configure(text=f"抓取詳細資料 {done} / {total} 筆…")

        def _hide_progress():
            self._sync_prog_bar.stop()
            self._sync_prog_frame.pack_forget()
            self._sync_btn.configure(state="normal")

        def run():
            self.after(0, _show_fetching)

            # ── Phase 1: fetch from both sources ──────────────────────────
            export_rows: list[dict] = []
            pkg_rows:    list[dict] = []

            try:
                export_rows = self.app._web.query_obt_list(start, end)
            except RuntimeError as ex:
                if "session_expired" in str(ex):
                    self.app._web = None
                    self.after(0, _hide_progress)
                    self.after(0, lambda: messagebox.showwarning(
                        "工作階段已過期", "請到「費用查詢」頁重新登入後再同步。"))
                    return
            except Exception:
                pass  # non-fatal; continue with pkg_rows

            try:
                pkg_rows = self.app._web.query_package_list(start, end)
            except RuntimeError as ex:
                if "session_expired" in str(ex):
                    self.app._web = None
                    self.after(0, _hide_progress)
                    self.after(0, lambda: messagebox.showwarning(
                        "工作階段已過期", "請到「費用查詢」頁重新登入後再同步。"))
                    return
            except Exception:
                pass

            # ── Phase 2: merge by OBT ──────────────────────────────────────
            # FuncNo=135 gives: recipient_name, notes, order_id, shipment_date
            # FuncNo=2   gives: delivery_status, shipment_date
            merged: dict[str, dict] = {}

            for r in export_rows:
                obt = r.get("obt", "").strip()
                if not obt:
                    continue
                merged[obt] = {
                    "obt_number":     obt,
                    "order_id":       r.get("order_id", "").strip(),
                    "recipient_name": r.get("recipient_name", "").strip(),
                    "sender_name":    "",
                    "created_at":     r.get("shipment_date", "").strip(),
                    "notes":          r.get("memo", "").strip(),
                    "status":         "請按查詢確認",
                }

            for r in pkg_rows:
                obt = r.get("obt", "").strip()
                if not obt:
                    continue
                ds = r.get("delivery_status", "").strip()
                if obt in merged:
                    merged[obt]["status"] = _map_pkg_status(ds)
                    if not merged[obt]["created_at"]:
                        merged[obt]["created_at"] = r.get("shipment_date", "").strip()
                    if not merged[obt]["order_id"]:
                        merged[obt]["order_id"] = r.get("order_id", "").strip()
                else:
                    merged[obt] = {
                        "obt_number":     obt,
                        "order_id":       r.get("order_id", "").strip(),
                        "recipient_name": "",
                        "sender_name":    "",
                        "created_at":     r.get("shipment_date", "").strip(),
                        "notes":          "",
                        "status":         _map_pkg_status(ds),
                    }

            if not merged:
                self.after(0, _hide_progress)
                self.after(0, lambda: messagebox.showwarning(
                    "同步完成",
                    f"同步範圍：{start_label} ～ {end_label}\n\n"
                    "網站查無資料（可能該期間無建單，或登入已過期）。\n"
                    "請到「費用查詢」頁確認登入狀態後再試一次。"))
                return

            # ── Phase 3: compare with local tracking.json ─────────────────
            existing      = load_tracking()
            existing_obts = {r.get("obt_number", "") for r in existing}
            deleted_obts  = load_deleted_obts()
            existing_map  = {r.get("obt_number", ""): r for r in existing}

            new_obts = [obt for obt in merged
                        if obt not in existing_obts and obt not in deleted_obts]
            # 既有紀錄一律重抓一次 sender_name（強制覆寫過去同步錯誤的值）
            need_sender = [obt for obt in merged
                           if obt not in deleted_obts
                           and obt in existing_map]
            total_detail = len(new_obts) + len(need_sender)
            self.after(0, lambda t=total_detail: _show_detail_progress(t))

            added    = 0
            enriched = 0
            done     = 0

            # new records — fetch TranBillDetail for sender_name + fallbacks
            for obt in new_obts:
                rec = dict(merged[obt])
                try:
                    detail = self.app._web.fetch_obt_detail(obt)
                    rec["sender_name"] = detail.get("sender_name", "")
                    if not rec["recipient_name"]:
                        rec["recipient_name"] = detail.get("recipient_name", "")
                    if not rec["notes"]:
                        rec["notes"] = detail.get("notes", "")
                except Exception:
                    pass
                done += 1
                self.after(0, lambda d=done, t=total_detail: _update_progress(d, t))
                existing.append(rec)
                existing_obts.add(obt)
                added += 1

            # existing records — fill from merged data (no web request)
            for obt, m in merged.items():
                if obt in deleted_obts or obt not in existing_map:
                    continue
                rec = existing_map[obt]
                changed = False
                for field, src in [("recipient_name", "recipient_name"),
                                    ("notes",          "notes"),
                                    ("order_id",       "order_id")]:
                    if not rec.get(field, "").strip() and m.get(src, "").strip():
                        rec[field] = m[src]
                        changed = True
                if changed:
                    enriched += 1

            # existing records — 重抓 TranBillDetail（不覆寫 sender_name，保留建單時的值）
            for obt in need_sender:
                rec = existing_map[obt]
                try:
                    detail = self.app._web.fetch_obt_detail(obt)
                    # sender_name 只來自建單時的輸入（FuncNo=135），不從 TranBillDetail 覆寫
                    # 收件人 / 備註只在空白時補
                    if not rec.get("recipient_name", "").strip():
                        rec["recipient_name"] = detail.get("recipient_name", "")
                    if not rec.get("notes", "").strip():
                        rec["notes"] = detail.get("notes", "")
                except Exception:
                    pass
                done += 1
                self.after(0, lambda d=done, t=total_detail: _update_progress(d, t))

            if added or enriched:
                save_tracking(existing)

            import time as _t
            self._last_sync_ts = _t.time()

            def _finish(n=added, e=enriched, t=len(merged)):
                _hide_progress()
                self.refresh()
                import datetime
                now_str = datetime.datetime.now().strftime("%H:%M")
                self._last_sync_lbl.config(text=f"最後更新 {now_str}")
                if not silent:
                    parts = []
                    if n: parts.append(f"新增 {n} 筆")
                    if e: parts.append(f"補填資料 {e} 筆")
                    detail_line = "、".join(parts) if parts else "皆已是最新紀錄"
                    msg = (f"同步範圍：{start_label} ～ {end_label}\n"
                           f"共抓到 {t} 筆，{detail_line}。\n\n即將自動查詢所有配送狀態…")
                    messagebox.showinfo("同步完成", msg)
                self.after(200, self._query_all)

            self.after(0, _finish)

        threading.Thread(target=run, daemon=True).start()

    def _prune(self):
        import datetime
        records = load_tracking()
        cutoff = (datetime.datetime.now() - datetime.timedelta(days=14)).isoformat()
        kept = [r for r in records
                if _normalize_created_at(r.get("created_at", "")) >= cutoff]
        removed = len(records) - len(kept)
        save_tracking(kept)
        self.refresh()
        if removed:
            messagebox.showinfo("清除完成", f"已刪除 {removed} 筆兩週前的紀錄。")
        else:
            messagebox.showinfo("無需清除", "沒有兩週前的紀錄。")


# ─── print queue view ────────────────────────────────────────────────────────

class PrintQueueView(tk.Frame):
    """Displays all built shipping orders waiting to be printed."""
    def __init__(self, master, app):
        super().__init__(master, bg=PAPER)
        self.app = app
        self._vars: list[tk.BooleanVar] = []
        self._build()

    def _build(self):
        wrap = tk.Frame(self, bg=PAPER)
        wrap.pack(fill="both", expand=True, padx=28, pady=24)

        # header
        head = tk.Frame(wrap, bg=PAPER); head.pack(fill="x", pady=(0, 16))
        SectionHeader(head, "待列印", "待列印貨運單").pack(side="left")
        ba = tk.Frame(head, bg=PAPER); ba.pack(side="right")
        TwButton(ba, "清除已列印", variant="ghost",
                 command=self._clear_all).pack(side="left", padx=4)

        # table card
        tcard = Card(wrap, padding=0)
        tcard.pack(fill="both", expand=True)

        # header row  (use tcard.body, not tcard.inner, to avoid blank expand conflict)
        hdr = tk.Frame(tcard.body, bg=PAPER2)
        hdr.pack(fill="x")
        # checkbox column
        self._all_var = tk.BooleanVar(value=False)
        hdr_chk = tk.Checkbutton(hdr, variable=self._all_var, command=self._toggle_all,
                                  bg=PAPER2, activebackground=PAPER2,
                                  relief="flat", bd=0, highlightthickness=0)
        hdr_chk.pack(side="left", padx=(12, 0))
        for txt, w in [("建單時間", 8), ("訂單編號", 14), ("收件人", 14), ("貨運單號", 16), ("", 0)]:
            tk.Label(hdr, text=txt, font=F_KICKER, bg=PAPER2, fg=MUTED,
                     width=w if w else 1, anchor="w", padx=8, pady=9).pack(side="left")
        Hairline(tcard.body).pack(fill="x")

        # scrollable list
        lf = tk.Frame(tcard.body, bg=CARD)
        lf.pack(fill="both", expand=True)
        canvas = tk.Canvas(lf, bg=CARD, highlightthickness=0)
        vsb = ttk.Scrollbar(lf, orient="vertical", command=canvas.yview,
                            style="Tw.Vertical.TScrollbar")
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.configure(yscrollcommand=vsb.set)
        self._list_body = tk.Frame(canvas, bg=CARD)
        self._list_win = canvas.create_window((0, 0), window=self._list_body, anchor="nw")
        self._list_body.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
            lambda e: canvas.itemconfig(self._list_win, width=e.width))
        self._scroll_canvas = canvas
        _bind_mousewheel_on_hover(self._list_body, canvas)
        _bind_mousewheel_on_hover(canvas, canvas)

        # footer
        ft = tk.Frame(wrap, bg=PAPER); ft.pack(fill="x", pady=(12, 0))
        TwButton(ft, "全選", variant="ghost",
                 command=self._select_all).pack(side="left", padx=(0, 6))
        self._count_lbl = tk.Label(ft, text="共 0 筆", font=F_TINY, bg=PAPER, fg=MUTED)
        self._count_lbl.pack(side="left")
        self._print_btn = TwButton(ft, "列印選取 (0)", variant="primary",
                                   command=self._print_selected)
        self._print_btn.pack(side="right")

        self.refresh()

    def on_show(self):
        self.refresh()

    def refresh(self):
        for w in self._list_body.winfo_children():
            w.destroy()
        self._vars.clear()

        staging = self.app._staging
        self._count_lbl.config(text=f"共 {len(staging)} 筆")
        if hasattr(self.app, "sidebar"):
            self.app.sidebar.update_badge("print_queue", len(staging))

        if not staging:
            tk.Label(self._list_body,
                     text="尚無待列印貨運單\n（建立寄件單後會自動出現在這裡）",
                     bg=CARD, fg=MUTED, font=F_SMALL, justify="center").pack(pady=60)
            self._update_print_btn()
            return

        for i, item in enumerate(staging):
            var = tk.BooleanVar(value=False)
            var.trace_add("write", lambda *_: self._update_print_btn())
            self._vars.append(var)
            self._make_row(item, var, i < len(staging) - 1)

        tk.Frame(self._list_body, bg=CARD, height=12).pack()
        self._update_print_btn()

    def _make_row(self, item: dict, var: tk.BooleanVar, divider: bool):
        row = tk.Frame(self._list_body, bg=CARD)
        row.pack(fill="x")
        inner = tk.Frame(row, bg=CARD)
        inner.pack(fill="x", padx=4, pady=10)

        tk.Checkbutton(inner, variable=var, bg=CARD, activebackground=CARD,
                       cursor="hand2", relief="flat", bd=0,
                       highlightthickness=0).pack(side="left", padx=(8, 4))

        tk.Label(inner, text=item.get("created_at", "—"), font=F_TINY, bg=CARD, fg=MUTED,
                 width=8, anchor="w").pack(side="left", padx=(4, 0))
        tk.Label(inner, text=item.get("order_id", "—"), font=F_MONO, bg=CARD, fg=INK,
                 width=14, anchor="w").pack(side="left", padx=(8, 0))
        tk.Label(inner, text=item.get("name", "—"), font=F_NORM, bg=CARD, fg=INK,
                 width=14, anchor="w").pack(side="left", padx=(8, 0))
        tk.Label(inner, text=item.get("obt", "—"), font=F_MONO, bg=CARD, fg=MUTED,
                 width=16, anchor="w").pack(side="left", padx=(8, 0))

        btns = tk.Frame(inner, bg=CARD)
        btns.pack(side="right", padx=(4, 8))
        TwButton(btns, "開啟 PDF", variant="ghost",
                 command=lambda p=item.get("pdf_path",""):
                     subprocess.run(["open", p]) if p else None).pack(side="left", padx=(0, 4))
        TwButton(btns, "移除", variant="ghost",
                 command=lambda it=item: self._remove(it)).pack(side="left")

        if divider:
            Hairline(self._list_body).pack(fill="x")

    def _update_print_btn(self):
        n = sum(1 for v in self._vars if v.get())
        self._print_btn.set_text(f"列印選取 ({n})")

    def _toggle_all(self):
        on = self._all_var.get()
        for v in self._vars:
            v.set(on)

    def _select_all(self):
        self._all_var.set(True)
        for v in self._vars:
            v.set(True)

    def _remove(self, item: dict):
        try:
            self.app._staging.remove(item)
        except ValueError:
            pass
        self.refresh()

    def _clear_all(self):
        if not self.app._staging:
            return
        if messagebox.askyesno("清除全部", f"確定要清除全部 {len(self.app._staging)} 筆待列印貨運單？"):
            self.app._staging.clear()
            self.refresh()

    def _print_selected(self):
        selected_items = [self.app._staging[i] for i, v in enumerate(self._vars) if v.get()]
        if not selected_items:
            messagebox.showwarning("未選取", "請先勾選要列印的單據。")
            return
        try:
            paths = [it["pdf_path"] for it in selected_items if it.get("pdf_path")]
            if not paths:
                messagebox.showwarning("無 PDF", "選取的貨運單沒有 PDF 檔案。")
                return
            if len(paths) == 1:
                out_path = paths[0]
            else:
                out_path = self._merge_labels_multi(paths)
            subprocess.run(["open", out_path])
            for it in selected_items:
                try: self.app._staging.remove(it)
                except ValueError: pass
            self.refresh()
        except Exception as ex:
            messagebox.showerror("列印失敗", str(ex))

    def _merge_labels_multi(self, paths: list) -> str:
        from pypdf import PdfReader, PdfWriter, Transformation
        writer = PdfWriter()
        for i in range(0, len(paths), 2):
            r1 = PdfReader(paths[i])
            p1 = r1.pages[0]
            w = float(p1.mediabox.width)
            h = float(p1.mediabox.height)
            page = writer.add_blank_page(width=w, height=h)
            page.merge_transformed_page(p1, Transformation())
            if i + 1 < len(paths):
                r2 = PdfReader(paths[i + 1])
                p2 = r2.pages[0]
                page.merge_transformed_page(p2, Transformation().translate(0, -(h / 2)))
        out = Path(get_output_dir()) / f"combined_{int(time.time())}.pdf"
        Path(get_output_dir()).mkdir(parents=True, exist_ok=True)
        with open(out, "wb") as f:
            writer.write(f)
        return str(out)


# ─── contacts view ───────────────────────────────────────────────────────────

class ContactsView(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg=PAPER)
        self.app = app
        self._all = []
        self._filtered = []
        self._selected = None
        self._active_tab = "門市"
        self._checked_names = set()
        self._build()
        self.refresh()

    def _build(self):
        wrap = tk.Frame(self, bg=PAPER)
        wrap.pack(fill="both", expand=True, padx=28, pady=24)

        head = tk.Frame(wrap, bg=PAPER); head.pack(fill="x", pady=(0, 16))
        SectionHeader(head, "通訊錄", "收件人管理").pack(side="left")
        ba = tk.Frame(head, bg=PAPER); ba.pack(side="right")
        TwButton(ba, "匯出 CSV", variant="ghost",
                 command=self._export_csv).pack(side="left", padx=4)
        TwButton(ba, "匯入 CSV", variant="ghost",
                 command=self._import_csv).pack(side="left", padx=4)
        self._del_sel_btn = TwButton(ba, "刪除選取 (0)", variant="danger",
                                      command=self._delete_checked)
        self._add_btn = TwButton(ba, "＋ 新增聯絡人", variant="primary",
                                  command=self._add)
        self._add_btn.pack(side="left", padx=4)

        # split: list (left) + detail (right)
        split = tk.Frame(wrap, bg=PAPER); split.pack(fill="both", expand=True)
        split.columnconfigure(0, weight=2); split.columnconfigure(1, weight=1)
        split.rowconfigure(0, weight=1)

        # left list
        lcard = Card(split, padding=0)
        lcard.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        split.rowconfigure(0, weight=1)

        # tab bar
        tab_bar = tk.Frame(lcard.body, bg=CARD)
        tab_bar.pack(fill="x")
        self._tab_btns = {}
        for _cat in ("門市", "廠商"):
            _btn = tk.Label(tab_bar, text=f"{_cat}通訊錄", font=F_SMALL,
                            bg=CARD, fg=ACCENT if _cat == "門市" else MUTED,
                            cursor="hand2", padx=16, pady=10)
            _btn.pack(side="left")
            _btn.bind("<Button-1>", lambda _, c=_cat: self._switch_tab(c))
            self._tab_btns[_cat] = _btn
        Hairline(lcard.body).pack(fill="x")

        # search bar
        sbar = tk.Frame(lcard.body, bg=CARD, height=44)
        sbar.pack(fill="x")
        tk.Label(sbar, text="🔍", font=F_NORM, bg=CARD, fg=MUTED).pack(side="left", padx=(14, 4), pady=10)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._refilter())
        se = tk.Entry(sbar, textvariable=self.search_var, font=F_NORM,
                      bg=CARD, fg=INK, relief="flat", insertbackground=INK,
                      highlightthickness=0, bd=0)
        se.pack(side="left", fill="x", expand=True, pady=10)
        # × 清除搜尋按鈕（只在搜尋非空時顯示）
        self._search_clear_lbl = tk.Label(sbar, text="×", font=F_NORM, bg=CARD, fg=MUTED,
                                          cursor="hand2")
        self._search_clear_lbl.bind("<Button-1>", lambda _: self.search_var.set(""))
        def _update_clear_btn(*_):
            if self.search_var.get():
                self._search_clear_lbl.pack(side="right", padx=(0, 4))
            else:
                self._search_clear_lbl.pack_forget()
        self.search_var.trace_add("write", _update_clear_btn)
        # 全選 checkbox
        self._all_check_var = tk.BooleanVar(value=False)
        self._all_check = tk.Checkbutton(sbar, variable=self._all_check_var,
                                          command=self._toggle_all,
                                          bg=CARD, activebackground=CARD,
                                          relief="flat", bd=0, highlightthickness=0)
        self._all_check.pack(side="left", padx=(8, 0))
        self.count_lbl = tk.Label(sbar, text="", font=F_TINY, bg=CARD, fg=MUTED)
        self.count_lbl.pack(side="right", padx=14)
        Hairline(lcard.body).pack(fill="x")

        # list
        list_holder = tk.Frame(lcard.body, bg=CARD)
        list_holder.pack(fill="both", expand=True)
        self.list_canvas = tk.Canvas(list_holder, bg=CARD, highlightthickness=0)
        self.list_canvas.pack(side="left", fill="both", expand=True)
        vsb = ttk.Scrollbar(list_holder, orient="vertical",
                             command=self.list_canvas.yview,
                             style="Tw.Vertical.TScrollbar")
        vsb.pack(side="right", fill="y")
        self.list_canvas.configure(yscrollcommand=vsb.set)
        self.list_body = tk.Frame(self.list_canvas, bg=CARD)
        self.list_win = self.list_canvas.create_window((0, 0), window=self.list_body, anchor="nw")
        self.list_body.bind("<Configure>", lambda e:
            self.list_canvas.configure(scrollregion=self.list_canvas.bbox("all")))
        self.list_canvas.bind("<Configure>", lambda e:
            self.list_canvas.itemconfig(self.list_win, width=e.width))
        self._scroll_canvas = self.list_canvas
        _bind_mousewheel_on_hover(list_holder,      self.list_canvas)
        _bind_mousewheel_on_hover(self.list_canvas, self.list_canvas)
        _bind_mousewheel_on_hover(self.list_body,   self.list_canvas)

        # right detail
        self.detail_card = Card(split, padding=20)
        self.detail_card.grid(row=0, column=1, sticky="nsew")

    def refresh(self):
        self._all = load_contacts()
        self._refilter()
        if hasattr(self.app, "sidebar"):
            self.app.sidebar.refresh_sender()

    def _refilter(self):
        kw = self.search_var.get().lower() if hasattr(self, "search_var") else ""
        pool = [c for c in self._all
                if (c.get("category") or "門市") == self._active_tab]
        if kw:
            self._filtered = [c for c in pool
                              if any(kw in str(v).lower() for v in c.values())]
        else:
            self._filtered = list(pool)
        self.count_lbl.config(text=f"{len(self._filtered)} 位")
        self._render_list()
        if self._filtered:
            if self._selected is None or self._selected.get("name") not in {c.get("name") for c in self._filtered}:
                self._selected = self._filtered[0]
        else:
            self._selected = None
        self._render_detail()

    def _render_list(self):
        for w in self.list_body.winfo_children(): w.destroy()
        for c in self._filtered:
            sel = self._selected and c.get("name") == self._selected.get("name")
            self._make_row(c, sel)
        # Update 全選 state
        checked_in_view = self._checked_names & {c.get("name") for c in self._filtered}
        if self._filtered and checked_in_view == {c.get("name") for c in self._filtered}:
            self._all_check_var.set(True)
        else:
            self._all_check_var.set(False)

    def _make_row(self, c, sel):
        name = c.get("name", "")
        checked = name in self._checked_names
        bg = ACCENT2 if sel else CARD
        row = tk.Frame(self.list_body, bg=bg, cursor="hand2")
        row.pack(fill="x")
        body = tk.Frame(row, bg=bg); body.pack(fill="x", padx=14, pady=10)
        # checkbox
        chk_var = tk.BooleanVar(value=checked)
        chk = tk.Checkbutton(body, variable=chk_var, bg=bg, activebackground=bg,
                              relief="flat", bd=0, highlightthickness=0,
                              command=lambda _n=name, _v=chk_var: self._on_row_check(_n, _v.get()))
        chk.pack(side="left", padx=(0, 8))
        # avatar
        av_color = ACCENT if sel else RAIL
        av_fg = "#FFFFFF" if sel else INK2
        av = tk.Label(body, text=(name or "?")[:1],
                      bg=av_color, fg=av_fg, font=F_BOLD, width=2, height=1)
        av.pack(side="left", padx=(0, 12))
        info = tk.Frame(body, bg=bg); info.pack(side="left", fill="x", expand=True)
        tk.Label(info, text=name, font=F_BOLD,
                 bg=bg, fg=INK, anchor="w").pack(fill="x")
        tk.Label(info, text=(c.get("address") or "—"),
                 font=F_TINY, bg=bg, fg=INK2, anchor="w",
                 wraplength=360, justify="left").pack(fill="x")
        if c.get("notes"):
            tag = tk.Label(body, text=c["notes"][:12], font=F_TINY,
                           bg="#FFE9D8", fg=ACCENT, padx=6, pady=2)
            tag.pack(side="right")
        Hairline(self.list_body).pack(fill="x")

        def select(_e=None):
            self._selected = c
            self._render_list(); self._render_detail()
        for w in (row, body, info, av):
            w.bind("<Button-1>", select)
        for child in info.winfo_children():
            child.bind("<Button-1>", select)

    def _on_row_check(self, name, checked):
        if checked:
            self._checked_names.add(name)
        else:
            self._checked_names.discard(name)
        self._update_del_btn()
        # update 全選 state
        if self._filtered and self._checked_names >= {c.get("name") for c in self._filtered}:
            self._all_check_var.set(True)
        else:
            self._all_check_var.set(False)

    def _toggle_all(self):
        if self._all_check_var.get():
            for c in self._filtered:
                self._checked_names.add(c.get("name", ""))
        else:
            for c in self._filtered:
                self._checked_names.discard(c.get("name", ""))
        self._update_del_btn()
        self._render_list()

    def _update_del_btn(self):
        n = len(self._checked_names)
        if n > 0:
            self._del_sel_btn.set_text(f"刪除選取 ({n})")
            if not self._del_sel_btn.winfo_ismapped():
                self._del_sel_btn.pack(side="left", padx=4, before=self._add_btn)
        else:
            self._del_sel_btn.pack_forget()

    def _delete_checked(self):
        names = set(self._checked_names)
        if not names: return
        if not messagebox.askyesno("確認刪除",
                f"確定刪除選取的 {len(names)} 筆聯絡人？\n此動作無法復原。"): return
        custom = load_custom_contacts()
        custom = [c for c in custom if c.get("name") not in names]
        save_contacts(custom)
        self._checked_names.clear()
        self._selected = None
        self._update_del_btn()
        self.refresh()

    def _switch_tab(self, cat):
        self._active_tab = cat
        self._checked_names.clear()
        self._update_del_btn()
        for c, btn in self._tab_btns.items():
            btn.config(fg=ACCENT if c == cat else MUTED,
                       font=(F_SMALL[0], F_SMALL[1], "bold") if c == cat else F_SMALL)
        self._all_check_var.set(False)
        self._refilter()

    def _render_detail(self):
        for w in self.detail_card.body.winfo_children(): w.destroy()
        c = self._selected
        if not c:
            tk.Label(self.detail_card.body, text="（無聯絡人）\n\n點右上「＋ 新增聯絡人」加入第一筆",
                     bg=CARD, fg=MUTED, font=F_SMALL, justify="left").pack(anchor="w")
            return

        head = tk.Frame(self.detail_card.body, bg=CARD); head.pack(fill="x")
        av = tk.Label(head, text=(c.get("name") or "?")[:1],
                      bg=ACCENT, fg="#FFFFFF", font=(FONT_FAMILY, 18, "bold"),
                      width=2, height=1)
        av.pack(side="left", padx=(0, 12))
        info = tk.Frame(head, bg=CARD); info.pack(side="left", fill="x", expand=True)
        tk.Label(info, text=c.get("name", ""), font=F_TITLE,
                 bg=CARD, fg=INK).pack(anchor="w")
        if c.get("notes"):
            tk.Label(info, text=c["notes"], font=F_TINY,
                     bg=CARD, fg=MUTED).pack(anchor="w")

        for field, label in [("phone", "電話"), ("mobile", "手機"),
                              ("address", "地址"), ("notes", "備註")]:
            block = tk.Frame(self.detail_card.body, bg=CARD)
            block.pack(fill="x", pady=(14, 0))
            Kicker(block, label).pack(anchor="w")
            v = c.get(field, "") or "—"
            tk.Label(block, text=v, font=F_MONO if field in ("phone", "mobile") else F_NORM,
                     bg=CARD, fg=INK, wraplength=300, justify="left",
                     anchor="w").pack(fill="x", pady=(4, 0))
            Hairline(self.detail_card.body).pack(fill="x", pady=(12, 0))

        tk.Frame(self.detail_card.body, bg=CARD).pack(fill="both", expand=True)
        btns = tk.Frame(self.detail_card.body, bg=CARD)
        btns.pack(fill="x", pady=(14, 0))
        TwButton(btns, "用此地址建單  →", variant="primary",
                 command=self._send_to_single).pack(fill="x")
        b2 = tk.Frame(self.detail_card.body, bg=CARD)
        b2.pack(fill="x", pady=(8, 0))
        TwButton(b2, "編輯", variant="default", command=self._edit).pack(side="left", expand=True, fill="x", padx=(0, 4))
        TwButton(b2, "刪除", variant="danger",  command=self._delete).pack(side="left", expand=True, fill="x", padx=(4, 0))

    def _send_to_single(self):
        c = self._selected
        if not c: return
        sv = self.app.views.get("single")
        if not sv: return
        sv.fields["recipient_name"].set(c.get("name", ""))
        sv.fields["recipient_phone"].set(c.get("phone", ""))
        sv.fields["recipient_mobile"].set(c.get("mobile", ""))
        sv.fields["recipient_address"].set(c.get("address", ""))
        self.app.show_view("single")

    def _add(self):
        ContactDialog(self, {"category": self._active_tab}, self._on_save)

    def _edit(self):
        if not self._selected: return
        ContactDialog(self, dict(self._selected), self._on_save)

    def _delete(self):
        if not self._selected: return
        name = self._selected.get("name")
        if not messagebox.askyesno("確認刪除", f"確定刪除「{name}」？"): return
        custom = load_custom_contacts()
        custom = [c for c in custom if c.get("name") != name]
        save_contacts(custom)
        self._selected = None
        self.refresh()

    def _on_save(self, contact, original_name=None):
        if not contact.get("category"):
            contact["category"] = self._active_tab
        custom = load_custom_contacts()
        if original_name:
            custom = [c for c in custom if c.get("name") != original_name]
        custom.append(contact)
        custom.sort(key=lambda c: c.get("name", ""))
        save_contacts(custom)
        self._selected = contact
        self.refresh()

    def _export_csv(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV 檔案", "*.csv")],
            title="匯出通訊錄",
            initialfile="通訊錄.csv",
        )
        if not path: return
        contacts = load_contacts()
        # 動態使用 CONTACT_FIELDS（含 store_id / email），順便帶出 category
        keys = [k for k, _ in CONTACT_FIELDS] + ["category"]
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            for c in contacts:
                writer.writerow({k: c.get(k, "") for k in keys})
        messagebox.showinfo("匯出成功", f"已匯出 {len(contacts)} 筆聯絡人。\n\n{path}")

    def _import_csv(self):
        path = filedialog.askopenfilename(
            filetypes=[("CSV 檔案", "*.csv")],
            title="匯入通訊錄",
        )
        if not path: return
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                new_contacts = [dict(r) for r in reader]
        except Exception as ex:
            messagebox.showerror("匯入失敗", str(ex)); return
        if not new_contacts:
            messagebox.showwarning("匯入失敗", "CSV 檔案沒有資料。"); return
        custom = load_custom_contacts()
        ans = messagebox.askyesnocancel(
            "匯入方式",
            f"CSV 內有 {len(new_contacts)} 筆聯絡人。\n\n"
            f"選「是」：附加到自訂聯絡人（目前 {len(custom)} 筆）\n"
            f"選「否」：取代自訂聯絡人（預設門市資料不受影響）\n"
            f"取消：中止",
        )
        if ans is None: return
        if ans:
            existing_names = {c.get("name") for c in custom}
            merged = custom + [c for c in new_contacts if c.get("name") not in existing_names]
            merged.sort(key=lambda c: c.get("name", ""))
            save_contacts(merged)
        else:
            new_contacts.sort(key=lambda c: c.get("name", ""))
            save_contacts(new_contacts)
        self.refresh()
        messagebox.showinfo("匯入成功", f"已匯入 {len(new_contacts)} 筆聯絡人。")


# ─── config view ─────────────────────────────────────────────────────────────

class ConfigView(tk.Frame):
    FIELDS_API = [("客戶代號", "username"), ("API 授權碼", "api_token")]
    FIELDS_SENDER = [
        ("姓名 / 公司名稱", "name"),
        ("市話", "tel"),
        ("手機（可空）", "mobile"),
        ("郵遞區號（6 碼）", "zipcode"),
        ("地址", "address"),
    ]

    def __init__(self, master, app):
        super().__init__(master, bg=PAPER)
        self.app = app
        self.vars = {}
        self._build()
        self._load()

    def _build(self):
        canvas = tk.Canvas(self, bg=PAPER, highlightthickness=0)
        vsb = ttk.Scrollbar(self, orient="vertical", command=canvas.yview,
                            style="Tw.Vertical.TScrollbar")
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        body = tk.Frame(canvas, bg=PAPER)
        win = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))

        self._scroll_canvas = canvas
        _bind_mousewheel_on_hover(self, canvas)

        wrap = tk.Frame(body, bg=PAPER)
        wrap.pack(fill="both", expand=True, padx=28, pady=24)

        SectionHeader(wrap, "帳號", "API 連線與寄件人設定").pack(anchor="w", pady=(0, 18))

        # API card
        ac = Card(wrap, padding=22); ac.pack(fill="x", pady=(0, 14))
        head = tk.Frame(ac.body, bg=CARD); head.pack(fill="x", pady=(0, 14))
        Kicker(head, "EGS API").pack(side="left")
        self.api_status = tk.Label(head, text="● 待測試", font=F_TINY,
                                    bg=CARD, fg=MUTED)
        self.api_status.pack(side="right")

        g = tk.Frame(ac.body, bg=CARD); g.pack(fill="x")
        g.columnconfigure(0, weight=1); g.columnconfigure(1, weight=1)
        for i, (label, key) in enumerate(self.FIELDS_API):
            cell = tk.Frame(g, bg=CARD)
            cell.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 12, 0))
            field_label(cell, label, required=True).pack(fill="x", pady=(0, 6))
            v = tk.StringVar(); self.vars[key] = v
            e = FieldEntry(cell, textvariable=v, mono=True,
                           show="*" if key == "api_token" else "")
            e.pack(fill="x")

        ba = tk.Frame(ac.body, bg=CARD); ba.pack(fill="x", pady=(14, 0))
        TwButton(ba, "測試連線", variant="default", command=self._test).pack(side="left", padx=(0, 8))
        TwButton(ba, "儲存設定", variant="primary", command=self._save).pack(side="left")

        # Sender card
        sc = Card(wrap, padding=22); sc.pack(fill="x", pady=(0, 14))
        Kicker(sc.body, "寄件人資料").pack(anchor="w", pady=(0, 12))
        sg = tk.Frame(sc.body, bg=CARD); sg.pack(fill="x")
        sg.columnconfigure(0, weight=1); sg.columnconfigure(1, weight=1)
        for i, (label, field) in enumerate(self.FIELDS_SENDER):
            key = f"sender.{field}"
            r = i // 2 * 2; c = i % 2
            # full-width for address
            if field == "address":
                cell = tk.Frame(sc.body, bg=CARD)
                cell.pack(fill="x", pady=(12, 0))
                field_label(cell, label, required=True).pack(fill="x", pady=(0, 6))
                v = tk.StringVar(); self.vars[key] = v
                FieldEntry(cell, textvariable=v).pack(fill="x")
            else:
                cell = tk.Frame(sg, bg=CARD)
                cell.grid(row=r, column=c, sticky="ew",
                          padx=(0 if c == 0 else 12, 0), pady=(0 if r == 0 else 12, 0))
                req = field in ("name", "tel", "zipcode")
                field_label(cell, label, required=req).pack(fill="x", pady=(0, 6))
                v = tk.StringVar(); self.vars[key] = v
                FieldEntry(cell, textvariable=v,
                           mono=field in ("tel", "mobile", "zipcode")).pack(fill="x")

        # Product type
        pt_cell = tk.Frame(sc.body, bg=CARD); pt_cell.pack(fill="x", pady=(12, 0))
        field_label(pt_cell, "品名類別", hint="會印在託運單上").pack(fill="x", pady=(0, 6))
        self.pt_var = tk.StringVar(value=FIXED_PRODUCT_TYPE_LABEL)
        self.vars["sender.product_type_id"] = self.pt_var
        ttk.Combobox(pt_cell, textvariable=self.pt_var,
                     values=[FIXED_PRODUCT_TYPE_LABEL],
                     state="disabled", style="Tw.TCombobox", font=F_NORM).pack(fill="x")

        ba2 = tk.Frame(sc.body, bg=CARD); ba2.pack(fill="x", pady=(14, 0))
        TwButton(ba2, "儲存寄件人", variant="primary", command=self._save).pack(side="left")

        # Appearance card
        apc = Card(wrap, padding=22); apc.pack(fill="x", pady=(0, 14))
        Kicker(apc.body, "外觀設定").pack(anchor="w", pady=(0, 12))
        fs_cell = tk.Frame(apc.body, bg=CARD); fs_cell.pack(fill="x")
        field_label(fs_cell, "字體大小", hint="變更後會重新啟動程式").pack(fill="x", pady=(0, 6))
        self.fs_var = tk.StringVar(value="標準")
        ttk.Combobox(fs_cell, textvariable=self.fs_var,
                     values=list(FONT_SCALE_OPTIONS.keys()),
                     state="readonly", style="Tw.TCombobox", font=F_NORM).pack(fill="x")
        ba3 = tk.Frame(apc.body, bg=CARD); ba3.pack(fill="x", pady=(14, 0))
        TwButton(ba3, "套用並重新啟動", variant="primary",
                 command=self._apply_font_scale).pack(side="left")

        self.maximized_var = tk.BooleanVar()

        # ── web login card ────────────────────────────────────────────────────
        wc = Card(wrap, padding=22); wc.pack(fill="x", pady=(0, 14))
        Kicker(wc.body, "契客專區登入").pack(anchor="w", pady=(0, 12))
        wg = tk.Frame(wc.body, bg=CARD); wg.pack(fill="x")
        wg.columnconfigure(0, weight=1); wg.columnconfigure(1, weight=1)
        for ci, (lbl, key) in enumerate([("客戶代號 (帳號)", "web_username"),
                                          ("密碼", "web_password")]):
            cell = tk.Frame(wg, bg=CARD)
            cell.grid(row=0, column=ci, sticky="ew", padx=(0 if ci==0 else 8, 0))
            tk.Label(cell, text=lbl, font=F_TINY, bg=CARD, fg=MUTED).pack(anchor="w", pady=(0,3))
            show = "*" if "password" in key else None
            v = tk.StringVar(); self.vars[key] = v
            e = tk.Entry(cell, textvariable=self.vars[key],
                         font=F_NORM, relief="flat", bg=HAIR3, fg=INK,
                         insertbackground=INK, show=show,
                         highlightthickness=1, highlightbackground=HAIR)
            e.pack(fill="x", ipady=5)
        act_cell = tk.Frame(wc.body, bg=CARD); act_cell.pack(fill="x", pady=(10, 0))
        tk.Label(act_cell, text="客戶帳號（查詢用，通常與客戶代號相同，12碼）",
                 font=F_TINY, bg=CARD, fg=MUTED).pack(anchor="w", pady=(0,3))
        _wact_var = tk.StringVar(); self.vars["web_account"] = _wact_var
        tk.Entry(act_cell, textvariable=self.vars["web_account"],
                 font=(MONO_FAMILY, _sz(11)), relief="flat", bg=HAIR3, fg=INK,
                 insertbackground=INK,
                 highlightthickness=1, highlightbackground=HAIR).pack(fill="x", ipady=5)
        btn_row = tk.Frame(wc.body, bg=CARD); btn_row.pack(anchor="w", fill="x", pady=(12, 0))
        TwButton(btn_row, "儲存登入資訊", variant="primary",
                 command=self._save).pack(side="left", padx=(0, 8))
        self._web_status_lbl = tk.Label(btn_row, text="", font=F_TINY, bg=CARD, fg=MUTED)
        self._web_status_lbl.pack(side="left")
        TwButton(wc.body, "驗證碼確認（登入契客專區）", variant="ghost",
                 command=self._do_web_login).pack(anchor="w", pady=(8, 0))

        # EPB 調撥設定區塊 — 只在解鎖後才建立（避免曝光 EPB 功能存在）
        if _is_epb_unlocked():
            ec = Card(wrap, padding=22); ec.pack(fill="x", pady=(0, 14))
            Kicker(ec.body, "EPB 調撥（限內網調撥作業電腦）").pack(anchor="w", pady=(0, 8))
            tk.Label(ec.body,
                     text="填入本門市在 EPB 的門市代碼（例 SA004、SA009…SA068）；留空則 EPB 調撥分頁顯示停用提示。",
                     font=F_TINY, bg=CARD, fg=MUTED,
                     wraplength=600, justify="left").pack(anchor="w", pady=(0, 10))
            store_cell = tk.Frame(ec.body, bg=CARD); store_cell.pack(fill="x")
            field_label(store_cell, "本門市代碼 (store_id)").pack(fill="x", pady=(0, 6))
            self.vars["store_id"] = tk.StringVar()
            ttk.Entry(store_cell, textvariable=self.vars["store_id"],
                      style="Tw.TEntry", font=F_MONO).pack(fill="x")
            ba_epb = tk.Frame(ec.body, bg=CARD); ba_epb.pack(fill="x", pady=(14, 0))
            TwButton(ba_epb, "儲存", variant="primary",
                     command=self._save).pack(side="left")

            # 不使用黑貓的入庫門市清單
            Hairline(ec.body).pack(fill="x", pady=(18, 14))
            tk.Label(ec.body, text="不使用黑貓的入庫門市",
                     font=F_BOLD, bg=CARD, fg=INK).pack(anchor="w")
            tk.Label(ec.body,
                     text="這些門市的調撥單仍會列在 EPB 分頁，但狀態顯示「🚫 不使用黑貓」、不可勾選；"
                          "例外時可在列表中點該列強制本次使用。\n"
                          "從通訊錄中已填「門市代碼」的條目挑選；用門市代碼比對 EPB 調撥單。",
                     font=F_TINY, bg=CARD, fg=MUTED,
                     wraplength=600, justify="left").pack(anchor="w", pady=(2, 10))

            self._skip_chip_host = tk.Frame(ec.body, bg=CARD)
            self._skip_chip_host.pack(fill="x")
            self._render_skip_chips()

            skip_actions = tk.Frame(ec.body, bg=CARD)
            skip_actions.pack(fill="x", pady=(10, 0))
            TwButton(skip_actions, "新增…", variant="default",
                     command=self._add_skip_stores).pack(side="left")

        # Preferences card (toggles)
        prefc = Card(wrap, padding=0); prefc.pack(fill="x", pady=(0, 14))
        tk.Frame(prefc.inner, bg=CARD, height=1).pack(fill="x")
        pref_head = tk.Frame(prefc.inner, bg=CARD); pref_head.pack(fill="x", padx=20, pady=(14, 8))
        Kicker(pref_head, "偏好").pack(side="left")
        Hairline(prefc.inner).pack(fill="x")
        prefs = [
            ("auto_open_pdf",  "建單成功後自動開啟 PDF",   "使用系統預設 PDF 檢視器"),
            ("check_updates",  "啟動時檢查更新",           f"目前版本 v{VERSION} · GitHub release"),
            ("validate_phone", "批次匯入時驗證電話格式",   "不符會在表格中標示警示"),
            ("start_maximized","預設全視窗開啟",           "下次啟動生效"),
        ]
        self.pref_vars = {}
        for i, (key, label, sub) in enumerate(prefs):
            prow = tk.Frame(prefc.inner, bg=CARD)
            prow.pack(fill="x")
            inner = tk.Frame(prow, bg=CARD); inner.pack(fill="x", padx=20, pady=12)
            info = tk.Frame(inner, bg=CARD); info.pack(side="left", fill="x", expand=True)
            tk.Label(info, text=label, font=F_NORM, bg=CARD, fg=INK, anchor="w").pack(fill="x")
            tk.Label(info, text=sub, font=F_TINY, bg=CARD, fg=MUTED, anchor="w").pack(fill="x")
            v = tk.BooleanVar()
            self.pref_vars[key] = v
            chk = tk.Checkbutton(inner, variable=v, font=F_SMALL,
                                  text="", bg=CARD, activebackground=CARD,
                                  fg=ACCENT, selectcolor=CARD, relief="flat",
                                  bd=0, highlightthickness=0,
                                  command=lambda _k=key, _v=v: self._save_pref(_k, _v.get()))
            chk.pack(side="right")
            if i < len(prefs) - 1:
                Hairline(prefc.inner).pack(fill="x")
        tk.Frame(prefc.inner, bg=CARD, height=4).pack()

        # Paths card
        pc = Card(wrap, padding=22); pc.pack(fill="x", pady=(0, 14))
        Kicker(pc.body, "檔案路徑").pack(anchor="w", pady=(0, 12))

        # 資料庫路徑 row
        pr_db = tk.Frame(pc.body, bg=HAIR3); pr_db.pack(fill="x", pady=(0, 4))
        inn_db = tk.Frame(pr_db, bg=HAIR3); inn_db.pack(fill="x", padx=12, pady=8)
        tk.Label(inn_db, text="資料庫路徑", font=F_TINY, bg=HAIR3, fg=MUTED,
                 width=12, anchor="w").pack(side="left")
        self._db_dir_lbl = tk.Label(inn_db, text=str(get_data_dir()),
                                    font=F_MONO, bg=HAIR3, fg=INK, anchor="w")
        self._db_dir_lbl.pack(side="left", padx=(8, 0), fill="x", expand=True)
        TwButton(inn_db, "Finder", variant="ghost",
                 command=lambda: subprocess.run(["open", str(get_data_dir())])
                 ).pack(side="right", padx=(4, 0))
        TwButton(inn_db, "選擇…", variant="ghost",
                 command=self._pick_data_dir).pack(side="right")

        # PDF output dir row
        pr0 = tk.Frame(pc.body, bg=HAIR3); pr0.pack(fill="x", pady=(0, 4))
        inn0 = tk.Frame(pr0, bg=HAIR3); inn0.pack(fill="x", padx=12, pady=8)
        tk.Label(inn0, text="PDF 輸出目錄", font=F_TINY, bg=HAIR3, fg=MUTED,
                 width=12, anchor="w").pack(side="left")
        self._out_dir_lbl = tk.Label(inn0, text=get_output_dir(),
                                     font=F_MONO, bg=HAIR3, fg=INK, anchor="w")
        self._out_dir_lbl.pack(side="left", padx=(8, 0), fill="x", expand=True)
        TwButton(inn0, "選擇…", variant="ghost",
                 command=self._pick_output_dir).pack(side="right")


        # status text
        self.status = tk.Label(wrap, text="", bg=PAPER, font=F_SMALL, anchor="w")
        self.status.pack(fill="x", pady=(8, 0))

    def _pick_data_dir(self):
        d = filedialog.askdirectory(title="選擇黑貓資料庫資料夾",
                                    initialdir=str(get_data_dir()))
        if not d:
            return
        set_data_dir(d)
        self._db_dir_lbl.config(text=d)
        self.status.config(text=f"✓ 資料庫路徑已更新：{d}　（重新啟動後生效）")
        self.after(5000, lambda: self.status.config(text=""))

    def _pick_output_dir(self):
        current = get_output_dir()
        d = filedialog.askdirectory(title="選擇 PDF 輸出目錄", initialdir=current)
        if not d:
            return
        cfg = load_cfg()
        cfg["output_dir"] = d
        save_cfg(cfg)
        self._out_dir_lbl.config(text=d)
        self.status.config(text=f"✓ PDF 輸出目錄已更新：{d}")
        self.after(3000, lambda: self.status.config(text=""))

    def _load(self):
        cfg = load_cfg()
        sender = cfg.get("sender") or {}
        for key, var in self.vars.items():
            if "." in key:
                _, field = key.split(".", 1)
                val = sender.get(field, "")
            else:
                val = cfg.get(key, "")
            if key == "sender.product_type_id":
                val = FIXED_PRODUCT_TYPE_LABEL
            var.set(val)
        # 字體大小：把目前 config 的值對應回標籤
        try:
            cur_scale = float(cfg.get("font_scale", 1.0) or 1.0)
        except Exception:
            cur_scale = 1.0
        cur_label = next((k for k, v in FONT_SCALE_OPTIONS.items()
                          if abs(v - cur_scale) < 1e-3), "標準")
        self.fs_var.set(cur_label)
        self.maximized_var.set(bool(cfg.get("start_maximized", False)))
        # load pref toggles
        for key, v in self.pref_vars.items():
            v.set(bool(cfg.get(key, key in ("auto_open_pdf", "check_updates"))))

    def _do_web_login(self):
        """Launch CAPTCHA dialog from settings page to login to 契客專區."""
        cfg = load_cfg()
        username = cfg.get("web_username","").strip()
        password = cfg.get("web_password","").strip()
        if not username or not password:
            messagebox.showwarning("尚未設定", "請先填入客戶代號與密碼後儲存，再登入。")
            return

        self._web_status_lbl.config(text="載入驗證碼中…", fg=MUTED)
        self.app._web = TakkyubinWebClient()

        def fetch():
            try:
                tokens, img_bytes = self.app._web.get_login_page()
                self.after(0, lambda: self._show_web_captcha(tokens, img_bytes, username, password))
            except Exception as ex:
                self.app._web = None
                self.after(0, lambda: self._web_status_lbl.config(
                    text=f"✗ 無法載入：{ex}", fg=ERR))
        import threading; threading.Thread(target=fetch, daemon=True).start()

    def _show_web_captcha(self, tokens: dict, img_bytes: bytes,
                          username: str, password: str):
        """Show CAPTCHA dialog; on success set app._web and update status."""
        dlg = tk.Toplevel(self)
        dlg.title("驗證碼登入")
        dlg.resizable(False, False)
        dlg.grab_set()
        f = tk.Frame(dlg, bg=PAPER, padx=24, pady=20); f.pack()
        dlg.update_idletasks()
        sw, sh = dlg.winfo_screenwidth(), dlg.winfo_screenheight()
        w, h   = dlg.winfo_reqwidth(), dlg.winfo_reqheight()
        dlg.geometry(f"+{(sw-w)//2}+{(sh-h)//2}")

        tk.Label(f, text="請輸入驗證碼後登入", font=(FONT_FAMILY, _sz(13), "bold"),
                 bg=PAPER, fg=INK).pack(pady=(0, 12))

        if img_bytes:
            try:
                import base64 as _b64
                img = tk.PhotoImage(data=_b64.b64encode(img_bytes).decode())
                tk.Label(f, image=img, bg=PAPER).pack(pady=(0, 8))
                dlg._img = img
            except Exception:
                tk.Label(f, text="（無法顯示驗證碼圖片）",
                         bg=PAPER, fg=MUTED, font=F_SMALL).pack(pady=(0, 8))
        else:
            tk.Label(f, text="（無法載入驗證碼圖片）",
                     bg=PAPER, fg=MUTED, font=F_SMALL).pack(pady=(0, 8))

        cap_var = tk.StringVar()
        e = tk.Entry(f, textvariable=cap_var, font=(MONO_FAMILY, _sz(14)),
                     width=10, justify="center", relief="flat",
                     bg=HAIR3, fg=INK, insertbackground=INK,
                     highlightthickness=1, highlightbackground=HAIR)
        e.pack(ipady=6, pady=(0, 14)); e.focus_set()

        msg_lbl = tk.Label(f, text="", font=F_SMALL, bg=PAPER, fg=ERR)
        msg_lbl.pack()

        def _submit():
            code = cap_var.get().strip()
            if not code:
                msg_lbl.config(text="請輸入驗證碼"); return
            msg_lbl.config(text="登入中…", fg=MUTED); dlg.update()
            def do_login():
                try:
                    ok = self.app._web.login(username, password, code, tokens)
                    if ok:
                        self.after(0, dlg.destroy)
                        self.after(0, lambda: self._web_status_lbl.config(
                            text="✓ 已登入契客專區", fg=OK))
                    else:
                        self.app._web = None
                        self.after(0, lambda: msg_lbl.config(
                            text="登入失敗，請確認帳號密碼與驗證碼", fg=ERR))
                except Exception as ex:
                    self.app._web = None
                    self.after(0, lambda: msg_lbl.config(text=f"錯誤：{ex}", fg=ERR))
            import threading; threading.Thread(target=do_login, daemon=True).start()

        btn_row = tk.Frame(f, bg=PAPER); btn_row.pack(pady=(8, 0))
        tk.Button(btn_row, text="確認登入", command=_submit,
                  font=(FONT_FAMILY, _sz(12), "bold"), bg=HAIR3, fg=INK,
                  relief="flat", padx=16, pady=6, cursor="hand2").pack(side="left", padx=(0,8))
        tk.Button(btn_row, text="取消", command=dlg.destroy,
                  font=(FONT_FAMILY, _sz(12)), bg=HAIR3, fg=INK2,
                  relief="flat", padx=16, pady=6, cursor="hand2").pack(side="left")
        e.bind("<Return>", lambda _: _submit())

    def _save_pref(self, key: str, val: bool):
        cfg = load_cfg()
        cfg[key] = val
        save_cfg(cfg)
        if key == "start_maximized":
            pass  # applied on next restart

    def _save_maximized(self):
        cfg = load_cfg()
        cfg["start_maximized"] = bool(self.maximized_var.get())
        save_cfg(cfg)

    def _apply_font_scale(self):
        label = self.fs_var.get()
        new_scale = FONT_SCALE_OPTIONS.get(label, 1.0)
        cfg = load_cfg()
        cfg["font_scale"] = new_scale
        save_cfg(cfg)
        if hasattr(self.app, "_restart_app"):
            self.app._restart_app()

    def _save(self):
        cfg = load_cfg()
        sender = cfg.get("sender") or {}
        for key, var in self.vars.items():
            val = var.get()
            if key == "sender.product_type_id":
                val = FIXED_PRODUCT_TYPE_ID
            if "." in key:
                _, field = key.split(".", 1)
                sender[field] = val
            else:
                cfg[key] = val
        cfg["sender"] = sender
        save_cfg(cfg)
        self.status.config(text="✓ 已儲存", fg=OK)
        self.after(2200, lambda: self.status.config(text=""))
        messagebox.showinfo("儲存成功", "設定已儲存。")
        if hasattr(self.app, "sidebar"):
            self.app.sidebar.refresh_sender()

    def _test(self):
        self._save()
        cfg = load_cfg()
        client = make_client(cfg)
        self.api_status.config(text="● 測試中…", fg=MUTED)
        def run():
            try:
                resp = client.print_obt([])
                if "SrvTranId" in resp:
                    self.after(0, lambda: self.api_status.config(text="● 連線正常", fg=OK))
                    self.after(0, lambda: self.status.config(text="✓ 連線成功！API 授權碼有效", fg=OK))
                else:
                    self.after(0, lambda r=resp: self.api_status.config(text="● 失敗", fg=ERR))
                    self.after(0, lambda r=resp: self.status.config(text=f"✗ 意外回應：{r}", fg=ERR))
            except Exception as ex:
                self.after(0, lambda e=ex: self.api_status.config(text="● 錯誤", fg=ERR))
                self.after(0, lambda e=ex: self.status.config(text=f"✗ 錯誤：{e}", fg=ERR))
        threading.Thread(target=run, daemon=True).start()

    # ── EPB 不使用黑貓門市清單管理 ─────────────────────────────────────────
    def _render_skip_chips(self):
        if not hasattr(self, "_skip_chip_host"):
            return
        for w in self._skip_chip_host.winfo_children():
            w.destroy()
        skip_ids = list(load_cfg().get("epb_skip_stores") or [])
        if not skip_ids:
            tk.Label(self._skip_chip_host, text="（無）",
                     font=F_TINY, bg=CARD, fg=MUTED).pack(anchor="w")
            return
        # 從通訊錄解析 store_id → name
        name_map = {}
        for c in load_contacts():
            sid = (c.get("store_id") or "").strip()
            if sid:
                name_map[sid] = c.get("name", "")
        # 流式排版（自動換行）
        row = tk.Frame(self._skip_chip_host, bg=CARD); row.pack(fill="x", anchor="w")
        for sid in skip_ids:
            label = f"{sid} {name_map.get(sid, '')}".strip()
            chip = tk.Frame(row, bg=HAIR3, highlightbackground=HAIR,
                            highlightthickness=1)
            chip.pack(side="left", padx=(0, 6), pady=(0, 6))
            tk.Label(chip, text=label, font=F_TINY, bg=HAIR3, fg=INK2,
                     padx=8, pady=4).pack(side="left")
            x_btn = tk.Label(chip, text="×", font=(FONT_FAMILY, _sz(13), "bold"),
                             bg=HAIR3, fg=MUTED, cursor="hand2", padx=6, pady=2)
            x_btn.pack(side="left")
            x_btn.bind("<Button-1>", lambda e, _s=sid: self._remove_skip_store(_s))
            x_btn.bind("<Enter>", lambda e, w=x_btn: w.configure(fg=ERR))
            x_btn.bind("<Leave>", lambda e, w=x_btn: w.configure(fg=MUTED))

    def _remove_skip_store(self, store_id: str):
        cfg = load_cfg()
        skip_ids = list(cfg.get("epb_skip_stores") or [])
        if store_id in skip_ids:
            skip_ids.remove(store_id)
            cfg["epb_skip_stores"] = skip_ids
            save_cfg(cfg)
            self._render_skip_chips()

    def _add_skip_stores(self):
        # 從通訊錄（有填門市代碼的）挑選
        eligible = [c for c in load_contacts()
                    if (c.get("store_id") or "").strip()]
        if not eligible:
            messagebox.showinfo(
                "通訊錄沒有門市代碼",
                "請先到「通訊錄」分頁，為要設為不使用黑貓的門市填入「門市代碼」。\n"
                "填完後再回來新增。")
            return
        existing = set(load_cfg().get("epb_skip_stores") or [])
        ContactSkipPickerDialog(self, contacts=eligible, existing=existing,
                                on_select=self._on_skip_picked)

    def _on_skip_picked(self, selected_ids: list):
        cfg = load_cfg()
        skip_ids = list(cfg.get("epb_skip_stores") or [])
        for sid in selected_ids:
            if sid and sid not in skip_ids:
                skip_ids.append(sid)
        cfg["epb_skip_stores"] = sorted(skip_ids)
        save_cfg(cfg)
        self._render_skip_chips()


# ─── freight fee view ────────────────────────────────────────────────────────

class FreightView(tk.Frame):
    """運費明細查詢 — 透過契客專區網頁查詢交易明細"""

    def __init__(self, master, app):
        super().__init__(master, bg=PAPER)
        self.app = app
        self._results: list[dict] = []
        self._row_data: dict = {}
        self._mode = "send"
        self._build()

    def _build(self):
        from datetime import date as _d, timedelta as _td
        wrap = tk.Frame(self, bg=PAPER)
        wrap.pack(fill="both", expand=True, padx=28, pady=24)

        # ── header ────────────────────────────────────────────────────────────
        head = tk.Frame(wrap, bg=PAPER); head.pack(fill="x", pady=(0, 16))
        SectionHeader(head, "費用查詢", "我的黑貓費用明細").pack(side="left")

        # ── query card ────────────────────────────────────────────────────────
        qc = Card(wrap, padding=20); qc.pack(fill="x", pady=(0, 10))
        date_row = tk.Frame(qc.body, bg=CARD); date_row.pack(fill="x", pady=(0, 8))
        tk.Label(date_row, text="開始日期", font=F_TINY, bg=CARD, fg=MUTED).pack(side="left")
        self._start_var = tk.StringVar(value=(_d.today() - _td(days=6)).strftime("%Y%m%d"))
        tk.Entry(date_row, textvariable=self._start_var,
                 font=(MONO_FAMILY, _sz(11)), width=10, relief="flat",
                 bg=HAIR3, fg=INK, insertbackground=INK,
                 highlightthickness=1, highlightbackground=HAIR).pack(
                     side="left", padx=(6, 16), ipady=4)
        tk.Label(date_row, text="結束日期", font=F_TINY, bg=CARD, fg=MUTED).pack(side="left")
        self._end_var = tk.StringVar(value=_d.today().strftime("%Y%m%d"))
        tk.Entry(date_row, textvariable=self._end_var,
                 font=(MONO_FAMILY, _sz(11)), width=10, relief="flat",
                 bg=HAIR3, fg=INK, insertbackground=INK,
                 highlightthickness=1, highlightbackground=HAIR).pack(
                     side="left", padx=(6, 16), ipady=4)
        qf = tk.Frame(date_row, bg=CARD); qf.pack(side="left", padx=(0, 14))
        for ql, qd in [("今天", 0), ("近7天", 6), ("近30天", 29)]:
            def _make(d=qd):
                def _fn():
                    from datetime import date as _dd, timedelta as _tt
                    e = _dd.today(); s = e - _tt(days=d)
                    self._start_var.set(s.strftime("%Y%m%d"))
                    self._end_var.set(e.strftime("%Y%m%d"))
                return _fn
            lb = tk.Label(qf, text=ql, font=F_TINY, bg=HAIR3, fg=INK2,
                          padx=8, pady=4, cursor="hand2", relief="flat")
            lb.pack(side="left", padx=(0, 4))
            lb.bind("<Button-1>", lambda e, fn=_make(): fn())
        TwButton(date_row, "查詢", variant="primary", command=self._query).pack(side="left")
        self._status_lbl = tk.Label(qc.body, text="請先在「設定」頁填入契客專區帳號密碼，再點查詢",
                                    font=F_TINY, bg=CARD, fg=MUTED)
        self._status_lbl.pack(anchor="w")

        # ── summary stat cards（6 張，2 列）──────────────────────────────────
        sc_row1 = tk.Frame(wrap, bg=PAPER); sc_row1.pack(fill="x", pady=(0, 8))
        self._stat_my_n    = self._make_stat_card(sc_row1, "我方付費（9開頭）筆數", "—", "筆", col=0)
        self._stat_my_fee  = self._make_stat_card(sc_row1, "我方付費金額",          "—", "元", col=1)
        self._stat_th_n    = self._make_stat_card(sc_row1, "對方到付（5開頭）筆數", "—", "筆", col=2)
        self._stat_th_fee  = self._make_stat_card(sc_row1, "對方到付金額",          "—", "元", col=3)
        for c in range(4): sc_row1.columnconfigure(c, weight=1, uniform="sc1")

        sc_row2 = tk.Frame(wrap, bg=PAPER); sc_row2.pack(fill="x", pady=(0, 10))
        self._stat_total_n   = self._make_stat_card(sc_row2, "合計筆數", "—", "筆", col=0)
        self._stat_total_fee = self._make_stat_card(sc_row2, "合計運費", "—", "元", col=1)
        sc_row2.columnconfigure(0, weight=1, uniform="sc2")
        sc_row2.columnconfigure(1, weight=1, uniform="sc2")

        # ── results table (Treeview) ──────────────────────────────────────────
        rcard = Card(wrap, padding=0); rcard.pack(fill="both", expand=True)
        _COLS = [
            ("pickup_date",   "集貨日期", 140, "center"),
            ("pickup_place",  "集貨所",   160, "w"),
            ("delivery_date", "配完日期", 140, "center"),
            ("delivery_place","配完所",   160, "w"),
            ("order_id",      "訂單編號", 120, "w"),
            ("obt",           "託運單號", 170, "w"),
            ("freight",       "運費(元)", 100, "w"),
        ]
        cols = tuple(c for c,*_ in _COLS)
        tf = tk.Frame(rcard.body, bg=CARD); tf.pack(fill="both", expand=True)
        self._tree = ttk.Treeview(tf, columns=cols, show="headings",
                                  style="Tw.Treeview", selectmode="browse")
        vsb = ttk.Scrollbar(tf, orient="vertical", command=self._tree.yview,
                             style="Tw.Vertical.TScrollbar")
        self._tree.configure(yscrollcommand=vsb.set)
        for cid, label, w, anchor in _COLS:
            self._tree.heading(cid, text=label, anchor=anchor)
            self._tree.column(cid, width=w, minwidth=w, anchor=anchor, stretch=True)
        self._tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        _bind_mousewheel_on_hover(self._tree, self._tree)
        self._tree.bind("<<TreeviewSelect>>", self._on_row_select)

    @staticmethod
    def _make_stat_card(parent, title: str, value: str, unit: str, col: int = 0):
        f = tk.Frame(parent, bg=CARD, padx=16, pady=14,
                     highlightthickness=1, highlightbackground=HAIR)
        f.grid(row=0, column=col, sticky="nsew", padx=(0, 8) if col < 3 else 0)
        tk.Label(f, text=title, font=F_KICKER, bg=CARD, fg=MUTED,
                 wraplength=140, justify="left").pack(anchor="w")
        val_row = tk.Frame(f, bg=CARD); val_row.pack(anchor="w", pady=(4, 0))
        v_lbl = tk.Label(val_row, text=value,
                         font=(FONT_FAMILY, _sz(22), "bold"), bg=CARD, fg=INK)
        v_lbl.pack(side="left")
        tk.Label(val_row, text=f" {unit}", font=F_SMALL, bg=CARD, fg=MUTED).pack(
            side="left", anchor="s", pady=(0, 2))
        return v_lbl

    # ── internals ──────────────────────────────────────────────────────────────

    def _query(self):
        import re
        start = self._start_var.get().strip()
        end   = self._end_var.get().strip()
        for v, lbl in [(start,"開始日期"),(end,"結束日期")]:
            if not re.match(r"^\d{8}$", v):
                messagebox.showwarning("格式錯誤", f"{lbl} 請輸入 YYYYMMDD（8位數字）"); return
        cfg = load_cfg()
        username = cfg.get("web_username","").strip()
        password = cfg.get("web_password","").strip()
        account  = cfg.get("web_account","").strip()
        if not username or not password:
            messagebox.showwarning("尚未設定",
                "請先到「設定」頁填入契客專區的客戶代號與密碼。"); return
        if not account:
            account = username  # fallback

        # If no session, go straight to login. Otherwise query directly —
        # session_expired exception inside query_payment() will trigger re-login.
        if self.app._web is None:
            self._do_login(username, password, account, start, end)
        else:
            self._do_query(account, start, end)

    def _do_login(self, username: str, password: str,
                  account: str, start: str, end: str):
        """Show CAPTCHA dialog then login in background."""
        self._status_lbl.config(text="正在載入驗證碼…", fg=MUTED)
        self.app._web = TakkyubinWebClient()

        def fetch():
            try:
                tokens, img_bytes = self.app._web.get_login_page()
                self.after(0, lambda: self._show_captcha(
                    tokens, img_bytes, username, password, account, start, end))
            except Exception as ex:
                self.after(0, lambda: self._status_lbl.config(
                    text=f"✗ 無法載入登入頁：{ex}", fg=ERR))
        import threading; threading.Thread(target=fetch, daemon=True).start()

    def _show_captcha(self, tokens: dict, img_bytes: bytes,
                      username: str, password: str,
                      account: str, start: str, end: str):
        """Show a small dialog for CAPTCHA input."""
        dlg = tk.Toplevel(self)
        dlg.title("驗證碼登入")
        dlg.resizable(False, False)
        dlg.grab_set()
        f = tk.Frame(dlg, bg=PAPER, padx=24, pady=20); f.pack()
        dlg.update_idletasks()
        sw, sh = dlg.winfo_screenwidth(), dlg.winfo_screenheight()
        w, h   = dlg.winfo_reqwidth(), dlg.winfo_reqheight()
        dlg.geometry(f"+{(sw-w)//2}+{(sh-h)//2}")

        tk.Label(f, text="請輸入驗證碼後登入", font=(FONT_FAMILY, _sz(13), "bold"),
                 bg=PAPER, fg=INK).pack(pady=(0, 12))

        if img_bytes:
            try:
                import base64 as _b64
                img = tk.PhotoImage(data=_b64.b64encode(img_bytes).decode())
                tk.Label(f, image=img, bg=PAPER).pack(pady=(0, 8))
                dlg._img = img  # prevent GC
            except Exception:
                tk.Label(f, text="（無法顯示驗證碼圖片，請查看瀏覽器）",
                         bg=PAPER, fg=MUTED, font=F_SMALL).pack(pady=(0, 8))
        else:
            tk.Label(f, text="（無法載入驗證碼圖片）",
                     bg=PAPER, fg=MUTED, font=F_SMALL).pack(pady=(0, 8))

        cap_var = tk.StringVar()
        e = tk.Entry(f, textvariable=cap_var, font=(MONO_FAMILY, _sz(14)),
                     width=10, justify="center", relief="flat",
                     bg=HAIR3, fg=INK, insertbackground=INK,
                     highlightthickness=1, highlightbackground=HAIR)
        e.pack(ipady=6, pady=(0, 14)); e.focus_set()

        msg_lbl = tk.Label(f, text="", font=F_SMALL, bg=PAPER, fg=ERR)
        msg_lbl.pack()

        def _submit():
            code = cap_var.get().strip()
            if not code:
                msg_lbl.config(text="請輸入驗證碼"); return
            msg_lbl.config(text="登入中…", fg=MUTED)
            dlg.update()
            def do_login():
                try:
                    ok = self.app._web.login(username, password, code, tokens)
                    if ok:
                        self.after(0, dlg.destroy)
                        self.after(0, lambda: self._do_query(account, start, end))
                    else:
                        self.after(0, lambda: msg_lbl.config(
                            text="登入失敗，請確認帳號密碼與驗證碼", fg=ERR))
                except Exception as ex:
                    self.after(0, lambda: msg_lbl.config(text=f"錯誤：{ex}", fg=ERR))
            import threading; threading.Thread(target=do_login, daemon=True).start()

        btn_row = tk.Frame(f, bg=PAPER); btn_row.pack(pady=(8, 0))
        tk.Button(btn_row, text="確認登入", command=_submit,
                  font=(FONT_FAMILY, _sz(12), "bold"), bg=HAIR3, fg=INK,
                  relief="flat", padx=16, pady=6, cursor="hand2").pack(side="left", padx=(0,8))
        tk.Button(btn_row, text="取消", command=dlg.destroy,
                  font=(FONT_FAMILY, _sz(12)), bg=HAIR3, fg=INK2,
                  relief="flat", padx=16, pady=6, cursor="hand2").pack(side="left")
        e.bind("<Return>", lambda _: _submit())

    def _do_query(self, account: str, start: str, end: str):
        self._status_lbl.config(text="查詢中…", fg=MUTED)
        self._results = []
        self._render_rows()

        cfg = load_cfg()
        username = cfg.get("web_username","").strip()
        password = cfg.get("web_password","").strip()

        def run():
            try:
                data = self.app._web.query_payment(start, end, account)
                self.after(0, lambda: self._on_result(data, start, end))
            except RuntimeError as ex:
                if "session_expired" in str(ex):
                    # Session expired — reset and re-login automatically
                    self.app._web = None
                    if username and password:
                        self.after(0, lambda: self._do_login(
                            username, password, account, start, end))
                    else:
                        self.after(0, lambda: self._status_lbl.config(
                            text="工作階段已過期，請重新查詢", fg=WARN))
                else:
                    self.after(0, lambda msg=str(ex): self._on_error(msg))
            except Exception as ex:
                self.after(0, lambda msg=str(ex): self._on_error(msg))
        import threading; threading.Thread(target=run, daemon=True).start()

    def _on_result(self, data: list, start: str, end: str):
        self._results = data
        my_rows = [r for r in data if (r.get("obt","") or "").startswith("9")]
        th_rows = [r for r in data if (r.get("obt","") or "").startswith("5")]
        def _sum(rows):
            try: return sum(int(r.get("freight","0") or 0) for r in rows)
            except Exception: return 0
        self._stat_my_n.config(text=str(len(my_rows)))
        self._stat_my_fee.config(text=f"{_sum(my_rows):,}")
        self._stat_th_n.config(text=str(len(th_rows)))
        self._stat_th_fee.config(text=f"{_sum(th_rows):,}")
        n = len(data)
        self._stat_total_n.config(text=str(n))
        self._stat_total_fee.config(text=f"{_sum(data):,}")
        self._status_lbl.config(text=f"✓ 查詢完成，共 {n} 筆", fg=OK if n > 0 else WARN)
        self._render_rows()

    def _on_error(self, msg: str):
        self._status_lbl.config(text=f"✗ 查詢失敗：{msg[:80]}", fg=ERR)
        for lbl in (self._stat_my_n, self._stat_my_fee, self._stat_th_n, self._stat_th_fee,
                    self._stat_total_n, self._stat_total_fee):
            lbl.config(text="—")
        for item in self._tree.get_children():
            self._tree.delete(item)

    def _render_rows(self):
        for item in self._tree.get_children():
            self._tree.delete(item)
        self._row_data = {}  # iid → full record dict
        for r in self._results:
            try: fee_s = f"{int(r.get('freight','0') or 0):,}"
            except Exception: fee_s = r.get("freight","—") or "—"
            iid = self._tree.insert("", "end", values=(
                r.get("pickup_date","—") or "—",
                r.get("pickup_place","—") or "—",
                r.get("delivery_date","—") or "—",
                r.get("delivery_place","—") or "—",
                r.get("order_id","—") or "—",
                r.get("obt","—") or "—",
                fee_s,
            ))
            self._row_data[iid] = r

    def _on_row_select(self, _event=None):
        sel = self._tree.selection()
        if not sel:
            return
        r = self._row_data.get(sel[0])
        if r:
            self._show_row_detail(r)

    def _show_row_detail(self, r: dict):
        obt       = r.get("obt", "").strip()
        start     = self._start_var.get().strip()
        end       = self._end_var.get().strip()
        cfg       = load_cfg()
        account   = cfg.get("web_account","").strip() or cfg.get("web_username","").strip()

        dlg = tk.Toplevel(self)
        dlg.title("電子訂單明細")
        dlg.configure(bg=PAPER)
        dlg.resizable(False, False)
        dlg.grab_set()

        f = tk.Frame(dlg, bg=PAPER, padx=28, pady=22)
        f.pack()

        tk.Label(f, text="電子訂單明細", font=F_TITLE, bg=PAPER, fg=INK).pack(anchor="w", pady=(0, 16))

        def _row(label, value, mono=False):
            row = tk.Frame(f, bg=PAPER); row.pack(fill="x", pady=4)
            tk.Label(row, text=label, font=F_KICKER, bg=PAPER, fg=MUTED,
                     width=10, anchor="e").pack(side="left")
            tk.Label(row, text=value or "—",
                     font=(MONO_FAMILY, _sz(12)) if mono else F_NORM,
                     bg=PAPER, fg=INK, anchor="w").pack(side="left", padx=(10, 0))

        def _divider():
            tk.Frame(f, bg=HAIR, height=1).pack(fill="x", pady=6)

        _row("託運單號", obt, mono=True)
        _row("訂單編號", r.get("order_id","") or "—", mono=True)
        _divider()
        _row("集貨日期", r.get("pickup_date",""))
        _row("集貨所",   r.get("pickup_place",""))
        _row("配完日期", r.get("delivery_date",""))
        _row("配完所",   r.get("delivery_place",""))
        _divider()
        try:
            fee = f"{int(r.get('freight','0') or 0):,} 元"
        except Exception:
            fee = r.get("freight","—")
        _row("運費", fee)
        _divider()

        # Recipient section — loaded from web asynchronously
        rec_frame = tk.Frame(f, bg=PAPER); rec_frame.pack(fill="x")
        loading_lbl = tk.Label(rec_frame, text="收件人資料讀取中…",
                               font=F_SMALL, bg=PAPER, fg=MUTED)
        loading_lbl.pack(anchor="w", pady=4)

        web_detail = {}  # filled by background thread

        def _fill_recipient(detail: dict):
            loading_lbl.destroy()
            rec_name = detail.get("recipient_name","")
            sender   = detail.get("sender_name","")
            notes    = detail.get("notes","")

            # If web detail failed, fall back to tracking.json
            if not rec_name:
                tracking = load_tracking()
                trk = next((t for t in tracking if t.get("obt_number","") == obt), None)
                rec_name = (trk or {}).get("recipient_name","")

            def _r(label, value, mono=False):
                row = tk.Frame(rec_frame, bg=PAPER); row.pack(fill="x", pady=3)
                tk.Label(row, text=label, font=F_KICKER, bg=PAPER, fg=MUTED,
                         width=10, anchor="e").pack(side="left")
                tk.Label(row, text=value or "—",
                         font=(MONO_FAMILY, _sz(12)) if mono else F_NORM,
                         bg=PAPER, fg=INK, anchor="w", wraplength=320).pack(
                         side="left", padx=(10,0))

            _r("收件人", rec_name or "（無法取得）")
            _r("寄件人", sender)
            if notes:
                _r("備註",   notes)
            if not rec_name:
                tk.Label(rec_frame,
                         text="⚠ 網站未回傳收件人資料（可能需要重新查詢日期範圍）",
                         font=F_TINY, bg=PAPER, fg=MUTED, wraplength=340).pack(
                         anchor="w", pady=(2,0))
            web_detail.update(detail)

        def _fetch():
            detail = {}
            if self.app._web is not None:
                # Strategy 1: query_obt_list (線上印單) — has full recipient info in list form
                try:
                    rows = self.app._web.query_obt_list(start, end)
                    match = next((r for r in rows if r.get("obt","").strip() == obt), None)
                    if match:
                        detail = {
                            "recipient_name":    match.get("recipient_name",""),
                            "recipient_address": match.get("recipient_address",""),
                            "sender_name":       "",
                            "notes":             match.get("notes",""),
                            "product_name":      match.get("product_name",""),
                            "order_date":        match.get("shipment_date",""),
                        }
                except Exception:
                    pass
                # Strategy 2: fall back to per-OBT detail page scrape
                if not detail.get("recipient_name"):
                    try:
                        detail = self.app._web.get_obt_detail(obt, start, end, account)
                    except Exception:
                        pass
            dlg.after(0, lambda d=detail: _fill_recipient(d))

        import threading; threading.Thread(target=_fetch, daemon=True).start()

        tk.Button(f, text="關閉", command=dlg.destroy,
                  font=F_NORM, bg=HAIR3, fg=INK,
                  relief="flat", padx=20, pady=6, cursor="hand2").pack(pady=(14, 0))


# ─── dialogs ─────────────────────────────────────────────────────────────────

CONTACT_FIELDS = [("name", "姓名 *"),
                   ("store_id", "門市代碼"),
                   ("brand_id", "廠商代碼"),
                   ("phone", "電話"), ("mobile", "手機"),
                   ("email", "電子信箱"),
                   ("address", "地址"), ("notes", "備註")]

# 分類專屬欄位：只在對應分類顯示
_CATEGORY_FIELDS = {
    "門市": "store_id",
    "廠商": "brand_id",
}

class ContactDialog(tk.Toplevel):
    def __init__(self, parent, contact, on_save):
        super().__init__(parent)
        self.title("新增聯絡人" if (contact is None or not contact.get("name")) else "編輯聯絡人")
        self.configure(bg=PAPER)
        self.resizable(False, False)
        self.grab_set()
        self.on_save = on_save
        self.original_name = contact.get("name") if contact else None
        self.vars = {}
        self._build(contact or {})

    def _build(self, contact):
        wrap = tk.Frame(self, bg=PAPER, padx=24, pady=20)
        wrap.pack()

        tk.Label(wrap, text="聯絡人資料", font=F_TITLE,
                 bg=PAPER, fg=INK).pack(anchor="w", pady=(0, 12))

        # Category 移到最上面：先選分類，下方代碼欄位才會顯示對應的
        tk.Label(wrap, text="分類", font=F_LABEL, bg=PAPER, fg=MUTED).pack(anchor="w", pady=(0, 4))
        cat_frame = tk.Frame(wrap, bg=PAPER)
        cat_frame.pack(anchor="w", pady=(0, 14))
        self.vars["category"] = tk.StringVar(value=contact.get("category", "門市"))
        for cat in ("門市", "廠商"):
            tk.Radiobutton(cat_frame, text=cat, variable=self.vars["category"],
                           value=cat, bg=PAPER, activebackground=PAPER,
                           font=F_NORM, fg=INK,
                           command=self._on_category_change).pack(side="left", padx=(0, 16))

        # 欄位 grid（記錄 widget refs 以便 hide/show）
        grid = tk.Frame(wrap, bg=PAPER)
        grid.pack(fill="x")
        self._field_widgets = {}
        for i, (key, label) in enumerate(CONTACT_FIELDS):
            lbl = field_label(grid, label.replace(" *", ""),
                              required=("*" in label))
            lbl.grid(row=i*2, column=0, sticky="w", pady=(8 if i else 0, 4))
            v = tk.StringVar(value=contact.get(key, ""))
            self.vars[key] = v
            ent = FieldEntry(grid, textvariable=v,
                             mono=key in ("phone", "mobile", "store_id", "brand_id"))
            ent.grid(row=i*2+1, column=0, sticky="ew")
            self._field_widgets[key] = (lbl, ent)

        # 初始套用分類專屬欄位顯隱
        self._on_category_change()

        ba = tk.Frame(wrap, bg=PAPER); ba.pack(fill="x", pady=(20, 0))
        TwButton(ba, "儲存", variant="primary", command=self._save).pack(side="left", padx=(0, 8))
        TwButton(ba, "取消", variant="ghost", command=self.destroy).pack(side="left")

    def _on_category_change(self):
        """依分類隱藏不相關的代碼欄位（門市↔廠商）。"""
        cat = self.vars["category"].get()
        for cat_name, key in _CATEGORY_FIELDS.items():
            if key not in self._field_widgets:
                continue
            lbl, ent = self._field_widgets[key]
            if cat == cat_name:
                lbl.grid()
                ent.grid()
            else:
                lbl.grid_remove()
                ent.grid_remove()

    def _save(self):
        contact = {k: v.get().strip() for k, v in self.vars.items()}
        if not contact.get("name"):
            messagebox.showwarning("必填", "姓名為必填欄位。", parent=self); return
        self.on_save(contact, self.original_name)
        self.destroy()


class EpbTransferView(tk.Frame):
    """EPB 調撥建單 — 讀取 EPB 待出貨調撥單，批次建立黑貓託運單。"""

    _LOG_PATH = Path(__file__).resolve().parent / "epb_transfer_log.json"

    def __init__(self, master, app):
        super().__init__(master, bg=PAPER)
        self.app = app
        self._transfers: list[dict] = []
        self._checked: set = set()
        self._contact_cache: dict = {}
        self._force_use_takkyu: set = set()  # 本次強制使用黑貓的 doc_id（不持久化）
        self._store_id = ""
        self._build()

    def _build(self):
        # File-system check only — no network call on startup
        try:
            import epb_client as _epb
            _has_env = (
                Path(_epb.JAVA).exists() and
                Path("/Library/EPBrowser/EPB/Shell/shell.jar").exists()
            )
        except Exception:
            _has_env = False

        wrap = tk.Frame(self, bg=PAPER)
        wrap.pack(fill="both", expand=True, padx=28, pady=24)

        head = tk.Frame(wrap, bg=PAPER)
        head.pack(fill="x", pady=(0, 16))
        SectionHeader(head, "EPB 調撥", "匯入調撥單建立黑貓託運單").pack(side="left")

        if not _has_env:
            notice = Card(wrap, padding=24)
            notice.pack(fill="x", pady=(0, 12))
            tk.Label(notice.body, text="⚠  需在可連線 EPB 的內網電腦使用",
                     font=(FONT_FAMILY, _sz(13), "bold"), bg=CARD, fg=WARN).pack(anchor="w")
            tk.Label(notice.body,
                     text="未偵測到 JDK 1.8 + EPBrowser 安裝。\n"
                          "此分頁在一般辦公室電腦上不可用，不影響其他建單功能。",
                     font=F_SMALL, bg=CARD, fg=MUTED, justify="left").pack(anchor="w", pady=(6, 0))
            return

        cfg = load_cfg()
        store_id = str(cfg.get("store_id") or "").strip()
        if not store_id:
            notice = Card(wrap, padding=24)
            notice.pack(fill="x", pady=(0, 12))
            tk.Label(notice.body, text="請先設定門市代碼",
                     font=(FONT_FAMILY, _sz(13), "bold"), bg=CARD, fg=WARN).pack(anchor="w")
            tk.Label(notice.body,
                     text="請至「設定」頁填入本門市 EPB 門市代碼（如 004）後儲存，再回此分頁查詢。",
                     font=F_SMALL, bg=CARD, fg=MUTED).pack(anchor="w", pady=(6, 0))
            TwButton(notice.body, "前往設定", variant="default",
                     command=lambda: self.app.show_view("settings")).pack(anchor="w", pady=(10, 0))
            return

        self._store_id = store_id

        # refresh button (only in active mode)
        self._refresh_btn = TwButton(head, "重新查詢", variant="primary", command=self._refresh)
        self._refresh_btn.pack(side="right")

        # store pill
        pill_row = tk.Frame(wrap, bg=PAPER)
        pill_row.pack(fill="x", pady=(0, 8))
        tk.Label(pill_row, text=f"門市代碼：{store_id}",
                 font=F_TINY, bg=PAPER, fg=MUTED).pack(side="left")

        # table card
        tcard = Card(wrap, padding=0)
        tcard.pack(fill="both", expand=True, pady=(0, 8))
        cols = ["sel", "doc_id", "doc_date", "to_store", "item_count", "status", "action"]
        labels = {"sel": "選取", "doc_id": "調撥單號", "doc_date": "日期",
                  "to_store": "入庫門市", "item_count": "品項",
                  "status": "狀態", "action": "操作"}
        widths = {"sel": 52, "doc_id": 170, "doc_date": 90,
                  "to_store": 180, "item_count": 60, "status": 160, "action": 80}

        self.tree = ttk.Treeview(tcard.body, columns=cols, show="headings",
                                 style="Tw.Treeview", height=12)
        for c in cols:
            self.tree.heading(c, text=labels[c], anchor="center")
            # 所有 cell 內容置中對齊標題
            self.tree.column(c, width=widths[c], anchor="center")
        vsb = ttk.Scrollbar(tcard.body, orient="vertical", command=self.tree.yview,
                            style="Tw.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        _bind_mousewheel_on_hover(self.tree, self.tree)
        self.tree.bind("<Button-1>", self._on_row_click)
        self.tree.tag_configure("built",   foreground=MUTED)
        self.tree.tag_configure("error",   foreground=ERR)
        self.tree.tag_configure("normal",  foreground=INK)
        self.tree.tag_configure("checked", foreground=OK)
        self.tree.tag_configure("skip",    foreground=MUTED2)
        self.tree.tag_configure("force",   foreground=ACCENT)

        # footer
        ft = tk.Frame(wrap, bg=PAPER)
        ft.pack(fill="x", pady=(0, 6))
        self.info_lbl = tk.Label(ft, text="點擊「重新查詢」載入本門市待出貨調撥單",
                                 font=F_TINY, bg=PAPER, fg=MUTED, anchor="w")
        self.info_lbl.pack(side="left")
        self._submit_btn = TwButton(ft, "建立選取託運單  →", variant="primary",
                                    command=self._submit, width=16)
        self._submit_btn.pack(side="right")

        # log area
        self.progress_lbl = tk.Label(wrap, text="", font=F_SMALL, bg=PAPER, fg=MUTED, anchor="w")
        self.progress_lbl.pack(fill="x", pady=(4, 2))
        self.log_box = scrolledtext.ScrolledText(wrap, height=5, font=F_MONO,
            bg=CARD, fg=INK2, relief="flat", state="disabled",
            highlightbackground=HAIR, highlightthickness=1)
        self.log_box.pack(fill="x")

    # ── helpers ────────────────────────────────────────────────────────────────

    def _log(self, msg: str):
        if not hasattr(self, "log_box"):
            return
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _load_epb_log(self) -> dict:
        try:
            return json.loads(self._LOG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_epb_log(self, log: dict):
        self._LOG_PATH.write_text(
            json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")

    def _match_contact(self, to_store_name: str, to_store_id: str = ""):
        """
        在黑貓通訊錄中找對應 contact（純記憶體，無 IO）。
        1. 優先用 to_store_id 比對 contact["store_id"] 精準匹配
        2. 退回名稱子字串比對（向後相容、給沒填門市代碼的通訊錄）
        """
        cache_key = f"{to_store_id}|{to_store_name}"
        if cache_key in self._contact_cache:
            return self._contact_cache[cache_key]
        contacts = load_contacts()
        # 1. 門市代碼精準匹配
        if to_store_id:
            for c in contacts:
                if (c.get("store_id") or "").strip() == to_store_id:
                    self._contact_cache[cache_key] = c
                    return c
        # 2. 名稱子字串 fallback
        name_lower = (to_store_name or "").lower()
        if name_lower:
            for c in contacts:
                c_name = (c.get("name") or "").lower()
                if c_name and (name_lower in c_name or c_name in name_lower):
                    self._contact_cache[cache_key] = c
                    return c
        self._contact_cache[cache_key] = None
        return None

    def _resolve_recipient(self, t: dict):
        """
        取得單張調撥單的收件人資料：
        1. 優先用通訊錄（門市代碼精準匹配，找不到再用名稱）
        2. 找不到時用 EPB storemas（query 時 JOIN 取回）地址 fallback
        3. 都沒有 → 回 None
        """
        to_name = t.get("to_store_name") or t.get("to_store_id", "")
        to_id = t.get("to_store_id", "")
        contact = self._match_contact(to_name, to_id)
        if contact:
            return contact
        epb_addr = (t.get("to_store_address") or "").strip()
        if epb_addr:
            return {
                "name":    to_name,
                "phone":   t.get("to_store_phone", ""),
                "mobile":  "",
                "address": epb_addr,
                "source":  "epb",
            }
        return None

    # ── actions ────────────────────────────────────────────────────────────────

    def _refresh(self):
        import time as _time
        self._contact_cache.clear()
        self._checked.clear()
        self._force_use_takkyu.clear()
        if hasattr(self, "info_lbl"):
            self.info_lbl.config(text="查詢中…", fg=MUTED)
        if hasattr(self, "_refresh_btn"):
            self._refresh_btn.set_enabled(False)

        t0 = _time.time()

        def run():
            try:
                import epb_client as _epb
                transfers = _epb.query_pending_transfers(self._store_id)
                print(f"[EPB] query store={self._store_id} → {len(transfers)} 筆 "
                      f"({_time.time()-t0:.1f}s)", flush=True)
            except Exception as ex:
                err = str(ex)
                print(f"[EPB] query 失敗 ({_time.time()-t0:.1f}s): {err}", flush=True)
                self.after(0, lambda e=err: self._on_refresh_error(e))
                return
            self.after(0, lambda t=transfers: self._populate(t))

        threading.Thread(target=run, daemon=True).start()

    def _on_refresh_error(self, err: str):
        if hasattr(self, "_refresh_btn"):
            self._refresh_btn.set_enabled(True)
        if hasattr(self, "info_lbl"):
            self.info_lbl.config(text=f"查詢失敗：{err[:80]}", fg=ERR)
        self._log(f"[錯誤] EPB 查詢失敗：{err}")

    def _populate(self, transfers: list):
        if hasattr(self, "_refresh_btn"):
            self._refresh_btn.set_enabled(True)
        self._transfers = transfers
        log = self._load_epb_log()

        for item in self.tree.get_children():
            self.tree.delete(item)

        # 只有「OBT 單號非空」才算真正建單成功；空 OBT 代表上次 API 失敗的殘留紀錄
        def _is_built(d_id):
            entry = log.get(d_id)
            return bool(entry and entry.get("obt_number"))
        self._is_built = _is_built  # 給 _on_row_click 取消已建單判定用

        skip_stores = set(load_cfg().get("epb_skip_stores") or [])

        no_contact = 0
        skipped = 0
        for t in transfers:
            doc_id = t["doc_id"]
            to_name = t.get("to_store_name") or t.get("to_store_id", "")
            to_id = t.get("to_store_id", "")
            contact = self._resolve_recipient(t)

            action_str = ""
            if _is_built(doc_id):
                obt = log[doc_id]["obt_number"]
                status_str = f"✅ 已建單 {obt}"
                tag = "built"
                sel_icon = "—"
                action_str = "［ ✕ 取消 ］"
            elif to_id in skip_stores and doc_id not in self._force_use_takkyu:
                status_str = "🚫 不使用黑貓"
                tag = "skip"
                sel_icon = "—"
                skipped += 1
            elif not contact:
                status_str = "⚠ 找不到通訊錄"
                tag = "error"
                sel_icon = "✗"
                no_contact += 1
            else:
                forced = doc_id in self._force_use_takkyu
                sel_icon = "☑" if doc_id in self._checked else "☐"
                if forced:
                    tag = "force"
                    status_str = "⚠ 強制使用黑貓（本次）"
                else:
                    tag = "checked" if doc_id in self._checked else "normal"
                    status_str = "待建單"

            self.tree.insert("", "end", iid=doc_id, tags=(tag,), values=[
                sel_icon, doc_id, t.get("doc_date", ""),
                to_name, t.get("item_count", ""), status_str, action_str,
            ])

        built = sum(1 for t in transfers if _is_built(t["doc_id"]))
        pending = len(transfers) - built
        if hasattr(self, "info_lbl"):
            extras = []
            if skipped:    extras.append(f"🚫 不使用黑貓 {skipped}")
            if no_contact: extras.append(f"⚠ 找不到通訊錄 {no_contact}")
            extra_str = ("  ·  " + "  ·  ".join(extras)) if extras else ""
            self.info_lbl.config(
                text=f"共 {len(transfers)} 筆  ·  已建單 {built}  ·  待建單 {pending}{extra_str}",
                fg=INK2)

    def _on_row_click(self, event):
        if not hasattr(self, "tree"):
            return
        region = self.tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        col_id = self.tree.identify_column(event.x)  # 形如 "#7"
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return

        t_dict = next((t for t in self._transfers if t["doc_id"] == row_id), None)
        if t_dict is None:
            return

        # 計算欄位索引（cols 是 _build 時定義的 list；用 displaycolumns 取目前順序）
        try:
            col_idx = int(col_id.replace("#", "")) - 1
            col_name = self.tree["columns"][col_idx]
        except (ValueError, IndexError):
            col_name = ""

        log = self._load_epb_log()
        log_entry = log.get(row_id)
        is_built = bool(log_entry and log_entry.get("obt_number"))

        # 已建單 + 點到「操作」欄 → 取消
        if is_built:
            if col_name == "action":
                self._cancel_built(row_id)
            return

        # 不使用黑貓門市：點任一格切換 force_use
        skip_stores = set(load_cfg().get("epb_skip_stores") or [])
        if t_dict.get("to_store_id") in skip_stores:
            if row_id in self._force_use_takkyu:
                self._force_use_takkyu.discard(row_id)
                self._checked.discard(row_id)
            else:
                self._force_use_takkyu.add(row_id)
            self._populate(self._transfers)
            return

        # 一般列：toggle 勾選
        if not self._resolve_recipient(t_dict):
            return  # 找不到收件人 — 不可勾
        if row_id in self._checked:
            self._checked.discard(row_id)
        else:
            self._checked.add(row_id)
        self._populate(self._transfers)

    def _cancel_built(self, doc_id: str):
        log = self._load_epb_log()
        entry = log.get(doc_id) or {}
        obt = entry.get("obt_number", "")
        if not messagebox.askyesno(
            "取消已建單",
            f"確定取消調撥單 {doc_id} 的託運單？\n"
            f"OBT {obt} 將從貨運查詢中移除，調撥單可重建。"):
            return
        # 1. epb_transfer_log 移除
        if doc_id in log:
            del log[doc_id]
            self._save_epb_log(log)
        # 2. tracking.json 同步移除對應 OBT
        if obt:
            records = load_tracking()
            records = [r for r in records if r.get("obt_number") != obt]
            save_tracking(records)
        # 3. UI 重繪
        self._populate(self._transfers)
        self._log(f"✕ 已取消 {doc_id} (OBT {obt})")

    def _submit(self):
        if not self._checked:
            messagebox.showwarning("未選取", "請先勾選要建立託運單的調撥單。")
            return
        cfg = load_cfg()
        sender = cfg.get("sender") or {}
        if not sender.get("name"):
            messagebox.showwarning("寄件人未設定", "請先至「設定」頁填寫寄件人資料。")
            return

        to_create = [t for t in self._transfers if t["doc_id"] in self._checked]
        if not to_create:
            return

        Path(get_output_dir()).mkdir(parents=True, exist_ok=True)
        total = len(to_create)
        if hasattr(self, "progress_lbl"):
            self.progress_lbl.config(text=f"建單中 0 / {total} 筆…", fg=MUTED)
        if hasattr(self, "_submit_btn"):
            self._submit_btn.set_enabled(False)
        if hasattr(self, "_refresh_btn"):
            self._refresh_btn.set_enabled(False)

        def run():
            client = make_client(cfg)
            log = self._load_epb_log()

            for i, t in enumerate(to_create, 1):
                doc_id = t["doc_id"]
                to_name = t.get("to_store_name") or t.get("to_store_id", "")
                contact = self._resolve_recipient(t) or {}
                order = {
                    "order_id":          doc_id,
                    "recipient_name":    contact.get("name", to_name),
                    "recipient_phone":   contact.get("phone", ""),
                    "recipient_mobile":  contact.get("mobile", ""),
                    "recipient_address": contact.get("address", ""),
                    "is_freight":        "Y",
                    "notes":             "門市調撥",
                    "product_name":      "一般物品",
                }

                # 用 order.create_orders（正確處理 Data.Orders[0].OBTNumber + FileNo + download_obt）
                try:
                    results = create_orders(client, [order], sender, output_dir=get_output_dir())
                    r = results[0] if results else {"success": False, "message": "API 無回應"}
                except Exception as ex:
                    r = {"success": False, "message": str(ex)}

                if r.get("success") and r.get("obt_number"):
                    obt = r["obt_number"]
                    pdf_path = r.get("pdf_path", "")
                    from datetime import datetime as _dt
                    log[doc_id] = {
                        "obt_number": obt,
                        "order_id":   doc_id,
                        "recipient":  to_name,
                        "created_at": _dt.now().isoformat(timespec="seconds"),
                        "pdf_path":   pdf_path,
                    }
                    self._save_epb_log(log)
                    append_tracking(obt, contact.get("name", to_name), doc_id, sender.get("name", ""))
                    _append_build_log(f"✓ EPB OBT:{obt} 調撥:{doc_id}")
                    self.after(0, lambda d=doc_id, n=obt, p=pdf_path:
                               self._log(f"✓ {d}  OBT:{n}" + (f"  → {Path(p).name}" if p else "")))
                else:
                    if r.get("success") and not r.get("obt_number"):
                        msg = "API 回成功但未取得 OBT 單號（檢查收件人電話/地址）"
                    else:
                        msg = (r.get("message") or "未知錯誤")[:80]
                    _append_build_log(f"✗ EPB 調撥:{doc_id} {msg}")
                    self.after(0, lambda d=doc_id, m=msg: self._log(f"✗ {d}：{m}"))

                self.after(0, lambda _i=i, _t=total: (
                    hasattr(self, "progress_lbl") and
                    self.progress_lbl.config(text=f"建單中 {_i} / {_t} 筆…", fg=MUTED)
                ))

            self.after(0, self._on_submit_done)

        threading.Thread(target=run, daemon=True).start()

    def _on_submit_done(self):
        self._log("── 完成 ──")
        if hasattr(self, "progress_lbl"):
            self.progress_lbl.config(text="✓ 建單完成", fg=OK)
        if hasattr(self, "_submit_btn"):
            self._submit_btn.set_enabled(True)
        if hasattr(self, "_refresh_btn"):
            self._refresh_btn.set_enabled(True)
        self._checked.clear()
        if self._transfers:
            self._populate(self._transfers)
        import subprocess
        subprocess.run(["open", get_output_dir()])


class ContactPickerDialog(tk.Toplevel):
    def __init__(self, parent, on_select):
        super().__init__(parent)
        self.title("選擇收件人")
        self.configure(bg=PAPER)
        self.geometry("580x400")
        self.grab_set()
        self.on_select = on_select
        self._build()

    def _build(self):
        wrap = tk.Frame(self, bg=PAPER, padx=20, pady=20)
        wrap.pack(fill="both", expand=True)

        tk.Label(wrap, text="從通訊錄選擇", font=F_TITLE,
                 bg=PAPER, fg=INK).pack(anchor="w", pady=(0, 12))

        sbar = tk.Frame(wrap, bg=CARD, highlightbackground=HAIR, highlightthickness=1)
        sbar.pack(fill="x", pady=(0, 12))
        tk.Label(sbar, text="🔍", bg=CARD, fg=MUTED, font=F_NORM).pack(side="left", padx=(10, 4), pady=8)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._refresh())
        tk.Entry(sbar, textvariable=self.search_var, font=F_NORM,
                 bg=CARD, fg=INK, relief="flat",
                 highlightthickness=0, bd=0).pack(side="left", fill="x", expand=True, pady=8)

        cols = ["name", "phone", "mobile", "address"]
        w = {"name": 110, "phone": 130, "mobile": 130, "address": 280}
        labels = {"name":"姓名","phone":"電話","mobile":"手機","address":"地址"}
        tcard = tk.Frame(wrap, bg=HAIR); tcard.pack(fill="both", expand=True)
        inner = tk.Frame(tcard, bg=CARD); inner.pack(fill="both", expand=True, padx=1, pady=1)
        self.tree = ttk.Treeview(inner, columns=cols, show="headings",
                                 style="Tw.Treeview", height=10)
        for c in cols:
            self.tree.heading(c, text=labels[c])
            self.tree.column(c, width=w[c], anchor="w")
        vsb = ttk.Scrollbar(inner, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        _bind_mousewheel_on_hover(self.tree, self.tree)
        self.tree.bind("<Double-1>", lambda e: self._pick())

        ba = tk.Frame(wrap, bg=PAPER); ba.pack(fill="x", pady=(12, 0))
        TwButton(ba, "選擇", variant="primary", command=self._pick).pack(side="left", padx=(0, 8))
        TwButton(ba, "取消", variant="ghost", command=self.destroy).pack(side="left")
        self._refresh()

    def _refresh(self):
        keyword = self.search_var.get().lower()
        for item in self.tree.get_children(): self.tree.delete(item)
        for c in load_contacts():
            if keyword and not any(keyword in str(v).lower() for v in c.values()):
                continue
            self.tree.insert("", "end", values=[c.get(k, "") for k in ["name","phone","mobile","address"]])

    def _pick(self):
        sel = self.tree.selection()
        if not sel: return
        vals = self.tree.item(sel[0])["values"]
        contact = dict(zip(["name","phone","mobile","address"], vals))
        self.on_select(contact)
        self.destroy()


class ContactSkipPickerDialog(tk.Toplevel):
    """從通訊錄（已填門市代碼的）挑選，多選後回呼新增到「不使用黑貓門市」清單。"""

    def __init__(self, parent, contacts: list, existing: set, on_select):
        super().__init__(parent)
        self.title("選擇不使用黑貓的入庫門市")
        self.configure(bg=PAPER)
        self.geometry("640x640")
        self.minsize(560, 480)
        self.grab_set()
        self.contacts = contacts
        self.existing = set(existing or [])
        self.on_select = on_select
        self._checked = set()
        self._build()
        self._refresh()

    def _build(self):
        wrap = tk.Frame(self, bg=PAPER, padx=20, pady=20)
        wrap.pack(fill="both", expand=True)

        # 按鈕區先 pack 到底部（保證視窗縮小時不被裁切）
        ba = tk.Frame(wrap, bg=PAPER)
        ba.pack(side="bottom", fill="x", pady=(12, 0))
        TwButton(ba, "加入清單", variant="primary",
                 command=self._confirm).pack(side="left", padx=(0, 8))
        TwButton(ba, "取消", variant="ghost",
                 command=self.destroy).pack(side="left")
        self.status_lbl = tk.Label(wrap, text="", font=F_TINY,
                                    bg=PAPER, fg=MUTED, anchor="w")
        self.status_lbl.pack(side="bottom", fill="x", pady=(8, 0))

        # 標題與說明
        tk.Label(wrap, text="從通訊錄選擇門市（多選）", font=F_TITLE,
                 bg=PAPER, fg=INK).pack(anchor="w", pady=(0, 6))
        tk.Label(wrap,
                 text="僅顯示已填「門市代碼」的通訊錄條目；已加入清單者灰底顯示、不可重複勾。",
                 font=F_TINY, bg=PAPER, fg=MUTED).pack(anchor="w", pady=(0, 10))

        # 搜尋
        sbar = tk.Frame(wrap, bg=CARD, highlightbackground=HAIR, highlightthickness=1)
        sbar.pack(fill="x", pady=(0, 10))
        tk.Label(sbar, text="🔍", bg=CARD, fg=MUTED,
                 font=F_NORM).pack(side="left", padx=(10, 4), pady=8)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._refresh())
        tk.Entry(sbar, textvariable=self.search_var, font=F_NORM,
                 bg=CARD, fg=INK, relief="flat",
                 highlightthickness=0, bd=0).pack(side="left", fill="x", expand=True, pady=8)

        # Treeview — 所有欄位置中（最後 pack，撐滿剩餘空間）
        cols = ["sel", "store_id", "name"]
        labels = {"sel": "選取", "store_id": "門市代碼", "name": "聯絡人名稱"}
        widths = {"sel": 60, "store_id": 140, "name": 380}
        tcard = tk.Frame(wrap, bg=HAIR); tcard.pack(fill="both", expand=True)
        inner = tk.Frame(tcard, bg=CARD); inner.pack(fill="both", expand=True, padx=1, pady=1)
        self.tree = ttk.Treeview(inner, columns=cols, show="headings",
                                 style="Tw.Treeview", height=14)
        for c in cols:
            self.tree.heading(c, text=labels[c], anchor="center")
            self.tree.column(c, width=widths[c], anchor="center")
        vsb = ttk.Scrollbar(inner, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        _bind_mousewheel_on_hover(self.tree, self.tree)
        self.tree.tag_configure("existing", foreground=MUTED2)
        self.tree.tag_configure("checked",  foreground=OK)
        self.tree.tag_configure("normal",   foreground=INK)
        self.tree.bind("<Button-1>", self._on_row_click)

    def _refresh(self):
        keyword = self.search_var.get().lower().strip()
        for item in self.tree.get_children():
            self.tree.delete(item)
        shown = 0
        for c in self.contacts:
            sid = (c.get("store_id") or "").strip()
            name = c.get("name") or ""
            if not sid:
                continue
            if keyword and keyword not in sid.lower() and keyword not in name.lower():
                continue
            if sid in self.existing:
                tag, sel = "existing", "—"
            elif sid in self._checked:
                tag, sel = "checked", "☑"
            else:
                tag, sel = "normal", "☐"
            self.tree.insert("", "end", iid=sid, tags=(tag,),
                             values=[sel, sid, name])
            shown += 1
        self.status_lbl.config(
            text=f"顯示 {shown} 間  ·  已加入清單 {len(self.existing)} 間  ·  待加入 {len(self._checked)} 間",
            fg=MUTED)

    def _on_row_click(self, event):
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return
        if row_id in self.existing:
            return  # 已存在，不可勾
        if row_id in self._checked:
            self._checked.discard(row_id)
        else:
            self._checked.add(row_id)
        self._refresh()

    def _confirm(self):
        if not self._checked:
            messagebox.showinfo("未選取", "請先勾選要加入的門市。", parent=self)
            return
        self.on_select(sorted(self._checked))
        self.destroy()


class MultiContactPickerDialog(tk.Toplevel):
    """多筆建單用：複選通訊錄（門市 / 廠商），回呼完整 contact dict 清單。"""

    def __init__(self, parent, on_select):
        super().__init__(parent)
        self.title("選擇收件人（多選）")
        self.configure(bg=PAPER)
        self.geometry("760x600")
        self.minsize(640, 480)
        self.grab_set()
        self.on_select = on_select
        self._contacts = load_contacts()
        self._checked: list[int] = []  # indices into self._contacts
        self._filter = "全部"  # 全部 / 門市 / 廠商
        self._build()
        self._refresh()

    def _build(self):
        wrap = tk.Frame(self, bg=PAPER, padx=20, pady=20)
        wrap.pack(fill="both", expand=True)

        # 底部按鈕（先 pack 防裁切）
        ba = tk.Frame(wrap, bg=PAPER)
        ba.pack(side="bottom", fill="x", pady=(12, 0))
        TwButton(ba, "加入清單", variant="primary",
                 command=self._confirm).pack(side="left", padx=(0, 8))
        TwButton(ba, "取消", variant="ghost",
                 command=self.destroy).pack(side="left")
        self.status_lbl = tk.Label(ba, text="", font=F_TINY,
                                    bg=PAPER, fg=MUTED, anchor="e")
        self.status_lbl.pack(side="right")

        # 標題
        tk.Label(wrap, text="從通訊錄選擇收件人", font=F_TITLE,
                 bg=PAPER, fg=INK).pack(anchor="w", pady=(0, 4))
        tk.Label(wrap,
                 text="勾選後按「加入清單」帶回多筆建單。同一聯絡人可重複加入（會自動加流水）。",
                 font=F_TINY, bg=PAPER, fg=MUTED).pack(anchor="w", pady=(0, 10))

        # 搜尋 + 類別 filter + 全選/全不選
        ctrl = tk.Frame(wrap, bg=PAPER)
        ctrl.pack(fill="x", pady=(0, 10))

        sbar = tk.Frame(ctrl, bg=CARD, highlightbackground=HAIR, highlightthickness=1)
        sbar.pack(side="left", fill="x", expand=True)
        tk.Label(sbar, text="🔍", bg=CARD, fg=MUTED,
                 font=F_NORM).pack(side="left", padx=(10, 4), pady=8)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._refresh())
        self._search_entry = tk.Entry(sbar, textvariable=self.search_var,
                                       font=F_NORM, bg=CARD, fg=INK,
                                       relief="flat", highlightthickness=0,
                                       bd=0)
        self._search_entry.pack(side="left", fill="x", expand=True, pady=8)
        self.after(50, self._search_entry.focus_set)

        fbar = tk.Frame(ctrl, bg=PAPER)
        fbar.pack(side="left", padx=(10, 0))
        self._filter_seg = Segment(fbar, options=["全部", "門市", "廠商"],
                                   selected="全部",
                                   on_change=self._on_filter_change,
                                   height=30, button_width=56)
        self._filter_seg.pack()

        abar = tk.Frame(ctrl, bg=PAPER)
        abar.pack(side="left", padx=(10, 0))
        TwButton(abar, "全選", variant="ghost",
                 command=self._select_all_visible).pack(side="left", padx=2)
        TwButton(abar, "全不選", variant="ghost",
                 command=self._clear_all).pack(side="left", padx=2)

        # Treeview
        cols = ["sel", "category", "code", "name", "address"]
        labels = {"sel": "選取", "category": "類別", "code": "代碼",
                  "name": "名稱", "address": "地址"}
        widths = {"sel": 50, "category": 60, "code": 100,
                  "name": 200, "address": 320}
        tcard = tk.Frame(wrap, bg=HAIR); tcard.pack(fill="both", expand=True)
        inner = tk.Frame(tcard, bg=CARD); inner.pack(fill="both", expand=True,
                                                       padx=1, pady=1)
        self.tree = ttk.Treeview(inner, columns=cols, show="headings",
                                 style="Tw.Treeview", height=14)
        for c in cols:
            anchor = "center" if c in ("sel", "category", "code") else "w"
            self.tree.heading(c, text=labels[c], anchor=anchor)
            self.tree.column(c, width=widths[c], anchor=anchor)
        vsb = ttk.Scrollbar(inner, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        _bind_mousewheel_on_hover(self.tree, self.tree)
        self.tree.tag_configure("checked", foreground=OK)
        self.tree.tag_configure("normal",  foreground=INK)
        self.tree.bind("<Button-1>", self._on_row_click)
        self.tree.bind("<Double-1>", self._on_row_click)

    def _on_filter_change(self, val: str):
        self._filter = val
        self._refresh()

    def _matches_filter(self, c: dict) -> bool:
        if self._filter == "全部":
            return True
        cat = (c.get("category") or "").strip()
        return cat == self._filter

    def _matches_search(self, c: dict, keyword: str) -> bool:
        if not keyword:
            return True
        haystack = " ".join(str(c.get(k, "")) for k in
                            ("name", "store_id", "brand_id", "phone",
                             "mobile", "address", "notes")).lower()
        return keyword in haystack

    def _refresh(self):
        keyword = self.search_var.get().lower().strip()
        for item in self.tree.get_children():
            self.tree.delete(item)
        shown = 0
        for idx, c in enumerate(self._contacts):
            if not self._matches_filter(c):
                continue
            if not self._matches_search(c, keyword):
                continue
            checked = idx in self._checked
            tag = "checked" if checked else "normal"
            sel = "☑" if checked else "☐"
            code = (c.get("store_id") or c.get("brand_id") or "").strip()
            self.tree.insert("", "end", iid=str(idx), tags=(tag,),
                             values=[sel, c.get("category") or "—",
                                     code, c.get("name", ""),
                                     c.get("address", "")])
            shown += 1
        self.status_lbl.config(
            text=f"顯示 {shown} · 已勾選 {len(self._checked)}",
            fg=MUTED)

    def _on_row_click(self, event):
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return
        idx = int(row_id)
        if idx in self._checked:
            self._checked.remove(idx)
        else:
            self._checked.append(idx)
        self._refresh()

    def _select_all_visible(self):
        keyword = self.search_var.get().lower().strip()
        for idx, c in enumerate(self._contacts):
            if not self._matches_filter(c):
                continue
            if not self._matches_search(c, keyword):
                continue
            if idx not in self._checked:
                self._checked.append(idx)
        self._refresh()

    def _clear_all(self):
        self._checked = []
        self._refresh()

    def _confirm(self):
        if not self._checked:
            messagebox.showinfo("未選取", "請先勾選要加入的收件人。", parent=self)
            return
        picked = [self._contacts[i] for i in self._checked]
        self.on_select(picked)
        self.destroy()


class EpbUnlockDialog(tk.Toplevel):
    """EPB 進階功能解鎖／鎖定對話框（隱藏快捷鍵 ⌘+⌥+E 開啟）。"""

    def __init__(self, parent, on_change):
        super().__init__(parent)
        self.title("進階功能")
        self.configure(bg=PAPER)
        self.resizable(False, False)
        self.grab_set()
        self.on_change = on_change
        self._build()
        # 視窗置中
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        self.geometry(f"+{(sw-w)//2}+{(sh-h)//2}")

    def _build(self):
        wrap = tk.Frame(self, bg=PAPER, padx=28, pady=22)
        wrap.pack()
        unlocked = _is_epb_unlocked()
        if unlocked:
            tk.Label(wrap, text="✓ EPB 調撥功能 已啟用",
                     font=F_TITLE, bg=PAPER, fg=OK).pack(anchor="w")
            tk.Label(wrap, text="如需停用，請按下方「鎖定」。",
                     font=F_SMALL, bg=PAPER, fg=MUTED).pack(
                         anchor="w", pady=(6, 16))
            ba = tk.Frame(wrap, bg=PAPER); ba.pack(fill="x")
            TwButton(ba, "鎖定", variant="danger",
                     command=self._do_lock).pack(side="left", padx=(0, 8))
            TwButton(ba, "關閉", variant="ghost",
                     command=self.destroy).pack(side="left")
        else:
            tk.Label(wrap, text="進階功能解鎖",
                     font=F_TITLE, bg=PAPER, fg=INK).pack(anchor="w")
            tk.Label(wrap, text="請輸入授權密碼以啟用 EPB 調撥功能。",
                     font=F_SMALL, bg=PAPER, fg=MUTED).pack(
                         anchor="w", pady=(6, 12))
            self.pw_var = tk.StringVar()
            entry = ttk.Entry(wrap, textvariable=self.pw_var, show="•",
                              font=F_NORM, width=28, style="Tw.TEntry")
            entry.pack(fill="x", pady=(0, 6))
            entry.focus_set()
            entry.bind("<Return>", lambda e: self._do_unlock())
            self.msg_lbl = tk.Label(wrap, text="", font=F_TINY,
                                     bg=PAPER, fg=ERR)
            self.msg_lbl.pack(anchor="w", pady=(0, 14))
            ba = tk.Frame(wrap, bg=PAPER); ba.pack(fill="x")
            TwButton(ba, "解鎖", variant="primary",
                     command=self._do_unlock).pack(side="left", padx=(0, 8))
            TwButton(ba, "取消", variant="ghost",
                     command=self.destroy).pack(side="left")

    def _do_unlock(self):
        pw = self.pw_var.get().strip()
        if _try_unlock_epb(pw):
            self.on_change(True)
            messagebox.showinfo(
                "解鎖成功",
                "EPB 調撥功能已啟用。\n若已開啟設定頁，請切到別頁再回來，"
                "EPB 設定卡片才會顯示。",
                parent=self)
            self.destroy()
        else:
            self.msg_lbl.config(text="密碼錯誤")
            self.pw_var.set("")

    def _do_lock(self):
        if not messagebox.askyesno(
            "確認鎖定",
            "確定要鎖定 EPB 調撥功能嗎？\n下次需要時要重新輸入密碼解鎖。",
            parent=self):
            return
        _lock_epb()
        self.on_change(False)
        self.destroy()


# ─── entry ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")
    _ensure_data_dir()
    app = App()
    app.mainloop()
