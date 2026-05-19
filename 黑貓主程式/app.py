#!/usr/bin/env python3
"""
黑貓宅急便 企業建單工具 — Tidewater
執行：python3 app.py
"""

import base64
import csv
import io
import json
import re
import subprocess
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

import yaml

from api_client import SudaClient, save_pdf, default_shipment_date, default_delivery_date, _skip_sunday
from web_client import TakkyubinWebClient
from order import generate_template, load_orders, create_orders, TEMPLATE_FIELDS, _csv_row_to_api_order

CONFIG_PATH   = "config.yaml"
CONTACTS_PATH         = "contacts.json"
DEFAULT_CONTACTS_PATH = "default_contacts.json"
OUTPUT_DIR    = str(Path(__file__).parent.parent / "黑貓單號")
TRACKING_PATH = str(Path(__file__).parent / "tracking.json")


def _append_build_log(msg: str):
    """將建單結果 append 到 黑貓單號/build_log.txt"""
    import datetime
    log_path = Path(OUTPUT_DIR) / "build_log.txt"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as _f:
        _f.write(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")


VERSION     = "1.7.9"
GITHUB_REPO = "pony9632-pixel/heicat-egs-tool"

# ─── Pro palette ─────────────────────────────────────────────────────────────
PAPER   = "#F4F1EA"   # warm cream
PAPER2  = "#EFEBE3"
CARD    = "#FFFFFF"
INK     = "#15171C"
INK2    = "#3B404B"
INK3    = "#5F6573"
MUTED   = "#8E94A1"
MUTED2  = "#B5BAC4"
HAIR    = "#E3DFD5"
HAIR2   = "#EDE9DF"
HAIR3   = "#F4F0E6"
ACCENT  = "#D8352B"
ACCENT2 = "#FAEAE9"   # ~7% tint of accent
OK      = "#1F7A4D"
OK2     = "#E4F2EA"
WARN    = "#A0681A"
WARN2   = "#FAEFD6"
ERR     = "#B5342A"
ERR2    = "#FBE5E2"
INFO    = "#2469A8"
INFO2   = "#E1EEF8"
RAIL    = "#F0ECE2"
RAIL2   = "#E6E1D5"

import platform
_IS_MAC = platform.system() == "Darwin"
FONT_FAMILY = "Helvetica Neue" if _IS_MAC else "Helvetica"
MONO_FAMILY = "Menlo" if _IS_MAC else "Courier"

# 字體縮放：從 config.yaml 讀 font_scale，預設 1.0；變更後重啟生效
FONT_SCALE_OPTIONS = {"小": 0.85, "標準": 1.0, "大": 1.15, "特大": 1.30}

def _load_font_scale():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as _f:
            v = (yaml.safe_load(_f) or {}).get("font_scale", 1.0)
        return max(0.7, min(2.0, float(v or 1.0)))
    except Exception:
        return 1.0

_FS = _load_font_scale()
def _sz(n: int) -> int:
    return max(7, int(round(n * _FS)))

F_NORM   = (FONT_FAMILY, _sz(12))
F_SMALL  = (FONT_FAMILY, _sz(11))
F_TINY   = (FONT_FAMILY, _sz(10))
F_BOLD   = (FONT_FAMILY, _sz(12), "bold")
F_TITLE  = (FONT_FAMILY, _sz(18), "bold")
F_KICKER = (FONT_FAMILY, _sz(10), "bold")
F_LABEL  = (FONT_FAMILY, _sz(10))
F_MONO   = (MONO_FAMILY, _sz(11))
F_NAV    = (FONT_FAMILY, _sz(12))


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
    if Path(CONFIG_PATH).exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}

def save_cfg(cfg: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)

def load_contacts() -> list[dict]:
    if Path(CONTACTS_PATH).exists():
        with open(CONTACTS_PATH, encoding="utf-8") as f:
            return json.load(f)
    # 首次安裝：從預設通訊錄初始化
    if Path(DEFAULT_CONTACTS_PATH).exists():
        with open(DEFAULT_CONTACTS_PATH, encoding="utf-8") as f:
            defaults = json.load(f)
        save_contacts(defaults)
        return defaults
    return []

def save_contacts(contacts: list[dict]):
    with open(CONTACTS_PATH, "w", encoding="utf-8") as f:
        json.dump(contacts, f, ensure_ascii=False, indent=2)

def load_tracking() -> list[dict]:
    if Path(TRACKING_PATH).exists():
        with open(TRACKING_PATH, encoding="utf-8") as f:
            return json.load(f)
    return []

def save_tracking(records: list[dict]):
    with open(TRACKING_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

def append_tracking(obt_number: str, recipient_name: str, order_id: str):
    """Add a new tracking record; auto-prune records older than 14 days."""
    import datetime
    records = load_tracking()
    records.append({
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "obt_number": obt_number,
        "recipient_name": recipient_name,
        "order_id": order_id,
    })
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=14)).isoformat()
    records = [r for r in records if r.get("created_at", "") >= cutoff]
    save_tracking(records)

def make_client(cfg: dict) -> SudaClient:
    return SudaClient(
        customer_id=str(cfg.get("username", "")),
        customer_token=cfg.get("api_token", ""),
    )


# ─── primitives ──────────────────────────────────────────────────────────────

class TwButton(tk.Frame):
    """Tidewater button — flat, with hover. variant: primary | default | ghost | danger"""
    def __init__(self, master, text, command=None, variant="default", width=None, **kw):
        bg = kw.pop("bg", None) or _frame_bg(master)
        super().__init__(master, bg=bg)
        self.command = command
        self.variant = variant
        self._enabled = True
        self._configure_colors()
        self.lbl = tk.Label(self, text=text, bg=self._bg, fg=self._fg,
                            font=F_BOLD, padx=14, pady=8, cursor="hand2",
                            width=width)
        if variant == "default":
            self.lbl.configure(highlightbackground=HAIR, highlightthickness=1)
        self.lbl.pack(fill="both", expand=True)
        self.lbl.bind("<Enter>",   lambda e: self._enabled and self.lbl.configure(bg=self._bg_hover, fg=self._fg_hover))
        self.lbl.bind("<Leave>",   lambda e: self._enabled and self.lbl.configure(bg=self._bg, fg=self._fg))
        self.lbl.bind("<Button-1>",lambda e: self._enabled and command and command())

    def _configure_colors(self):
        v = self.variant
        if v == "primary":
            self._bg, self._fg = INK, "#FFFFFF"
            self._bg_hover, self._fg_hover = "#0D1420", "#FFFFFF"
        elif v == "ghost":
            self._bg, self._fg = _frame_bg(self.master), INK2
            self._bg_hover, self._fg_hover = HAIR2, INK
        elif v == "danger":
            self._bg, self._fg = CARD, ERR
            self._bg_hover, self._fg_hover = "#FFE9E5", ERR
        elif v == "accent":
            self._bg, self._fg = ACCENT2, ACCENT
            self._bg_hover, self._fg_hover = "#FFE2D0", ACCENT
        else:  # default
            self._bg, self._fg = CARD, INK
            self._bg_hover, self._fg_hover = HAIR2, INK

    def set_text(self, t): self.lbl.configure(text=t)


def _frame_bg(widget):
    try:
        return widget.cget("bg")
    except tk.TclError:
        try:
            return widget.cget("background")
        except tk.TclError:
            return PAPER


class Card(tk.Frame):
    """White card with hairline border and inner padding."""
    def __init__(self, master, padding=20, **kw):
        super().__init__(master, bg=HAIR, highlightthickness=0, **kw)
        self.inner = tk.Frame(self, bg=CARD)
        self.inner.pack(fill="both", expand=True, padx=1, pady=1)
        self._pad = padding
        # padding sub-frame
        self.body = tk.Frame(self.inner, bg=CARD)
        self.body.pack(fill="both", expand=True, padx=padding, pady=padding)


class Kicker(tk.Label):
    """Uppercase eyebrow label."""
    def __init__(self, master, text, color=MUTED, **kw):
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


def _bind_mousewheel_on_hover(hover_widget, canvas):
    """游標在 hover_widget 範圍內時把 wheel 綁到 canvas，離開時解綁。
    用 bounding-box 判斷，避免移入子元件觸發 Leave 而中斷捲動。"""
    def _on_wheel(e):
        canvas.yview_scroll(int(-1 * (e.delta / 3)), "units")
    def _on_enter(_):
        canvas.bind_all("<MouseWheel>", _on_wheel)
    def _on_leave(e):
        try:
            wx = hover_widget.winfo_rootx()
            wy = hover_widget.winfo_rooty()
            ww = hover_widget.winfo_width()
            wh = hover_widget.winfo_height()
            if wx <= e.x_root < wx + ww and wy <= e.y_root < wy + wh:
                return  # 還在元件範圍內（只是移進子元件），不解綁
        except Exception:
            pass
        canvas.unbind_all("<MouseWheel>")
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
        import sys
        just_updated = "--just-updated" in sys.argv
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
                current = tuple(int(x) for x in VERSION.split("."))
                latest  = tuple(int(x) for x in tag.split("."))
                if latest > current:
                    if just_updated:
                        # 剛更新過卻仍偵測到更新 → Release 版本與 VERSION 不符，防止死循環
                        self.after(0, self._init_ui)
                        return
                    zipball = data.get("zipball_url", "")
                    html    = data.get("html_url", "")
                    self.after(0, lambda t=tag, z=zipball, h=html:
                               self._do_startup_update(t, z, h))
                    return
        except Exception:
            pass
        self.after(0, self._init_ui)

    def _do_startup_update(self, new_version, zipball_url, html_url):
        self._splash_lbl.config(text=f"發現新版本 v{new_version}，自動更新中…")

        def run():
            try:
                import ssl, shutil, tempfile, os
                import urllib.request as _req

                ssl_ctx = ssl.create_default_context()
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = ssl.CERT_NONE
                req = _req.Request(zipball_url, headers={"User-Agent": "heicat-egs-tool"})
                with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
                    temp_zip = f.name
                with _req.urlopen(req, context=ssl_ctx, timeout=60) as resp:
                    with open(temp_zip, "wb") as f:
                        shutil.copyfileobj(resp, f)

                self.after(0, lambda: self._splash_lbl.config(text="解壓縮並套用更新…"))

                import zipfile
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
                            # GitHub zipball 不帶執行權限，.command 雙擊會失效
                            if dst.suffix == ".command":
                                os.chmod(str(dst), 0o755)

                os.unlink(temp_zip)
                self.after(0, self._restart_app)
            except Exception:
                self.after(0, self._init_ui)

        threading.Thread(target=run, daemon=True).start()

    def _restart_app(self):
        import os, sys
        args = [sys.executable, str(Path(__file__)), "--just-updated"]
        os.execv(sys.executable, args)

    # ── build full UI ────────────────────────────────────────────────────────

    def _init_ui(self):
        self._splash.destroy()

        # ttk style for entries / combos
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Tw.TEntry",
            fieldbackground=CARD, background=CARD, foreground=INK,
            bordercolor=HAIR, lightcolor=HAIR, darkcolor=HAIR,
            padding=8, relief="flat")
        style.map("Tw.TEntry", bordercolor=[("focus", INK)])

        style.configure("Tw.TCombobox",
            fieldbackground=CARD, background=CARD, foreground=INK,
            bordercolor=HAIR, lightcolor=HAIR, darkcolor=HAIR,
            arrowcolor=MUTED, selectbackground=CARD, selectforeground=INK,
            padding=6, relief="flat")
        style.map("Tw.TCombobox",
                  bordercolor=[("focus", INK)],
                  fieldbackground=[("readonly", CARD)],
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

        # ── Window chrome — macOS traffic lights + centred title ──────────────
        chrome = tk.Frame(self, bg=RAIL, height=36)
        chrome.pack(fill="x")
        chrome.pack_propagate(False)
        # traffic lights (decorative — real ones are in native title bar area)
        lights = tk.Frame(chrome, bg=RAIL)
        lights.place(x=12, rely=0.5, anchor="w")
        for col in ("#FF5F57", "#FEBC2E", "#28C840"):
            c_dot = tk.Canvas(lights, width=12, height=12, bg=RAIL,
                              highlightthickness=0)
            c_dot.create_oval(1, 1, 11, 11, fill=col, outline="")
            c_dot.pack(side="left", padx=3)
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

        self.views = {
            "single":      SingleOrderView(self.content_host, self),
            "print_queue": PrintQueueView(self.content_host, self),
            "batch":       BatchOrderView(self.content_host, self),
            "tracking":    TrackingView(self.content_host, self),
            "freight":     FreightView(self.content_host, self),
            "contacts":    ContactsView(self.content_host, self),
            "settings":    ConfigView(self.content_host, self),
        }
        for v in self.views.values():
            v.place(relx=0, rely=0, relwidth=1, relheight=1)

        self.show_view("single")
        self.bind_all("<Command-1>", lambda e: self.show_view("single"))
        self.bind_all("<Command-2>", lambda e: self.show_view("print_queue"))
        self.bind_all("<Command-3>", lambda e: self.show_view("batch"))
        self.bind_all("<Command-4>", lambda e: self.show_view("tracking"))
        self.bind_all("<Command-5>", lambda e: self.show_view("freight"))
        self.bind_all("<Command-6>", lambda e: self.show_view("contacts"))
        self.bind_all("<Command-7>", lambda e: self.show_view("settings"))

    def show_view(self, name):
        v = self.views.get(name)
        if not v: return
        v.lift()
        if hasattr(v, "on_show"): v.on_show()
        self.sidebar.set_active(name)
        if hasattr(self, "_topbar"): self._topbar.set_view(name)
        # 切換頁面時立刻把 MouseWheel 綁到該頁的主 canvas，
        # 讓使用者在視窗任何地方都能捲動
        if hasattr(v, "_scroll_canvas"):
            c = v._scroll_canvas
            self.bind_all("<MouseWheel>",
                          lambda e, _c=c: _c.yview_scroll(int(-1 * (e.delta / 3)), "units"))
        else:
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
        def _keycode_guard(e):
            kc = e.keycode
            # 英文模式 keycode 直接命中；注音模式 Tk 認不出 keysym，會把硬體 keycode 塞到最高 byte
            fn = _KC.get(kc) or _KC.get((kc >> 24) & 0xFF)
            if fn is None: return
            now = _time.time()
            if now - _last_t[0] < 0.05: return "break"
            _last_t[0] = now; fn(); return "break"
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
    ("single",      "建立寄件單",   "1", "📤"),
    ("print_queue", "待列印貨運單", "2", "🖨"),
    ("batch",       "批次建單",     "3", "☰"),
    ("tracking",    "貨運查詢",     "4", "⊙"),
    ("freight",     "費用查詢",     "5", "💳"),
    ("contacts",    "通訊錄",       "6", "⊞"),
    ("settings",    "設定",         "7", "⚙"),
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
        srch_inner = tk.Frame(srch, bg=CARD,
                              highlightbackground=HAIR, highlightthickness=1)
        srch_inner.pack(fill="x", ipady=5, ipadx=8)
        tk.Label(srch_inner, text="🔍", bg=CARD, fg=MUTED,
                 font=(FONT_FAMILY, _sz(10))).pack(side="left", padx=(6, 4))
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
            self._items[key].pack(fill="x", pady=1)

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

        wrap = tk.Frame(self.sender_card, bg=CARD,
                        highlightbackground=HAIR, highlightthickness=1)
        wrap.pack(fill="x")
        wrap.columnconfigure(0, weight=1)
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

    def refresh_sender(self):
        self._render_sender()

    def update_badge(self, key: str, n: int):
        if key in self._items:
            self._items[key].set_badge(n)


class NavItem(tk.Frame):
    def __init__(self, master, label, kbd, icon, on_click):
        super().__init__(master, bg=RAIL)
        self._active = False
        self._on_click = on_click
        self.inner = tk.Frame(self, bg=RAIL)
        self.inner.pack(fill="x")
        # icon
        self.icn = tk.Label(self.inner, text=icon,
                            font=(FONT_FAMILY, _sz(12)), bg=RAIL, fg=MUTED,
                            width=2, padx=2, pady=7)
        self.icn.pack(side="left", padx=(6, 0))
        self.lbl = tk.Label(self.inner, text=label, font=F_NAV,
                            bg=RAIL, fg=INK2, anchor="w", pady=7)
        self.lbl.pack(side="left", fill="x", expand=True, padx=4)
        self.kbd = tk.Label(self.inner, text=f"⌘{kbd}",
                            font=(MONO_FAMILY, _sz(9)),
                            bg=RAIL, fg=MUTED2, padx=8)
        self.kbd.pack(side="right")
        # badge (hidden by default, shown when count > 0)
        self.badge_lbl = tk.Label(self.inner, text="",
                                  font=(MONO_FAMILY, _sz(9), "bold"),
                                  bg=ACCENT, fg="#FFFFFF",
                                  padx=5, pady=1, relief="flat", borderwidth=0)
        for w in (self.inner, self.icn, self.lbl, self.kbd):
            w.bind("<Button-1>", lambda e: self._on_click())
            w.bind("<Enter>", self._hover)
            w.bind("<Leave>", self._unhover)
            w.configure(cursor="hand2")
        self.badge_lbl.bind("<Button-1>", lambda e: self._on_click())
        self.badge_lbl.configure(cursor="hand2")

    def set_badge(self, n: int):
        if n > 0:
            self.badge_lbl.configure(text=str(n))
            if not self.badge_lbl.winfo_ismapped():
                self.badge_lbl.pack(side="right", before=self.kbd, padx=(0, 4))
        else:
            self.badge_lbl.pack_forget()

    def _all(self): return (self.inner, self.icn, self.lbl, self.kbd)

    def _hover(self, e):
        if self._active: return
        for w in self._all():
            w.configure(bg=HAIR2)

    def _unhover(self, e):
        if self._active: return
        for w in self._all():
            w.configure(bg=RAIL)

    def set_active(self, on):
        self._active = on
        bg  = CARD if on else RAIL
        fg  = INK  if on else INK2
        ifg = ACCENT if on else MUTED
        for w in self._all():
            w.configure(bg=bg)
        self.lbl.configure(fg=fg,
                           font=(FONT_FAMILY, _sz(12), "bold") if on else F_NAV)
        self.icn.configure(fg=ifg)
        self.kbd.configure(fg=MUTED2)


# ─── top bar ─────────────────────────────────────────────────────────────────

_VIEW_NAMES = {
    "single":      "建立寄件單",
    "print_queue": "待列印貨運單",
    "batch":       "批次建單",
    "tracking":    "貨運查詢",
    "freight":     "費用查詢",
    "contacts":    "通訊錄",
    "settings":    "設定",
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
        self._cat_btns = {}
        self._cat_map = {
            "門市調撥": "Y 收件人付（運費到付）",
            "客人":     "N 寄件人付",
            "廠商":     "Y 收件人付（運費到付）",
        }
        self._build()

    def _build(self):
        # scrollable region for the form (since on small screens it may overflow)
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

        # mouse wheel — 只在游標進入時綁定，避免和其他分頁的 canvas 互相搶
        self._scroll_canvas = canvas
        _bind_mousewheel_on_hover(self, canvas)

        wrap = tk.Frame(body, bg=PAPER)
        wrap.pack(fill="both", expand=True, padx=28, pady=24)

        # header
        head = tk.Frame(wrap, bg=PAPER)
        head.pack(fill="x", pady=(0, 18))
        SectionHeader(head, "新建寄件單", "建立單筆寄件").pack(side="left")
        ba = tk.Frame(head, bg=PAPER); ba.pack(side="right")
        TwButton(ba, "清除", variant="ghost", command=self._clear).pack(side="left", padx=4)
        TwButton(ba, "從剪貼板帶入", variant="default",
                 command=self._paste_recipient_from_clipboard).pack(side="left", padx=4)
        TwButton(ba, "從通訊錄", variant="default", command=self._pick_contact).pack(side="left", padx=4)

        # recipient card
        rc = Card(wrap, padding=22); rc.pack(fill="x", pady=(0, 14))
        Kicker(rc.body, "收件人資料").pack(anchor="w", pady=(0, 12))
        grid1 = tk.Frame(rc.body, bg=CARD); grid1.pack(fill="x")
        grid1.columnconfigure(0, weight=1); grid1.columnconfigure(1, weight=2)
        self._field(grid1, 0, 0, "姓名", "recipient_name", required=True)
        self._field(grid1, 0, 1, "地址", "recipient_address", required=True)
        self.after(100, lambda: self._attach_autocomplete("recipient_name"))
        grid2 = tk.Frame(rc.body, bg=CARD); grid2.pack(fill="x", pady=(12, 0))
        grid2.columnconfigure(0, weight=1); grid2.columnconfigure(1, weight=1)
        self._field(grid2, 0, 0, "電話", "recipient_phone", required=True, hint="市話")
        self._field(grid2, 0, 1, "手機", "recipient_mobile", hint="可空")
        action = tk.Frame(rc.body, bg=CARD); action.pack(fill="x", pady=(12, 0))
        TwButton(action, "＋ 存入通訊錄", variant="accent",
                 command=self._save_to_contacts).pack(side="left")

        # recipient category quick-select
        self._cat_var = tk.StringVar(value="")
        cat_row = tk.Frame(rc.body, bg=CARD); cat_row.pack(fill="x", pady=(10, 0))
        field_label(cat_row, "收件人分類", hint="自動帶入備註與付款方式").pack(anchor="w", pady=(0, 6))
        cat_container = tk.Frame(cat_row, bg=HAIR); cat_container.pack(fill="x")
        for i, lbl in enumerate(self._cat_map):
            btn = tk.Label(cat_container, text=lbl, font=F_BOLD, padx=14, pady=9,
                           cursor="hand2", bg=CARD, fg=INK)
            btn.pack(side="left", fill="x", expand=True, padx=(1 if i > 0 else 0, 0))
            self._cat_btns[lbl] = btn
            btn.bind("<Button-1>", lambda e, l=lbl: self._select_category(l))
            btn.bind("<Enter>", lambda e, b=btn: b.cget("bg") != INK and b.configure(bg=HAIR2))
            btn.bind("<Leave>", lambda e, b=btn: b.cget("bg") != INK and b.configure(bg=CARD))

        # parcel card
        pc = Card(wrap, padding=22); pc.pack(fill="x", pady=(0, 14))
        pc_hdr = tk.Frame(pc.body, bg=CARD); pc_hdr.pack(fill="x")
        Kicker(pc_hdr, "包裹明細").pack(side="left")
        self._pkg_toggle_lbl = tk.Label(pc_hdr, text="▸ 展開",
            font=F_SMALL, bg=CARD, fg=ACCENT, cursor="hand2")
        self._pkg_toggle_lbl.pack(side="right")
        self._pkg_toggle_lbl.bind("<Button-1>", lambda _: self._toggle_pkg_detail())
        self._pkg_expanded = False

        gp1 = tk.Frame(pc.body, bg=CARD); gp1.pack(fill="x", pady=(12, 0))
        gp1.columnconfigure(0, weight=2); gp1.columnconfigure(1, weight=2)
        self._field(gp1, 0, 0, "訂單編號", "order_id", required=True)
        self._field(gp1, 0, 1, "貨品名稱", "product_name", default="一般物品")

        self._pkg_detail = tk.Frame(pc.body, bg=CARD)
        # 預設收合，不 pack

        gp2 = tk.Frame(self._pkg_detail, bg=CARD); gp2.pack(fill="x", pady=(12, 0))
        gp2.columnconfigure(0, weight=1); gp2.columnconfigure(1, weight=1)
        self._combo_field(gp2, 0, 0, "尺寸", "spec",
                          list(SPEC_OPTIONS.keys()), default="0001  60 cm")
        self._combo_field(gp2, 0, 1, "溫層", "thermosphere",
                          list(THERMO_OPTIONS.keys()), default="0001 常溫")

        gp3 = tk.Frame(self._pkg_detail, bg=CARD); gp3.pack(fill="x", pady=(12, 0))
        gp3.columnconfigure(0, weight=1); gp3.columnconfigure(1, weight=1); gp3.columnconfigure(2, weight=1)
        self._field(gp3, 0, 0, "出貨日 YYYYMMDD", "shipment_date",
                    default=default_shipment_date(), mono=True)
        self._field(gp3, 0, 1, "配送日 YYYYMMDD", "delivery_date",
                    default=default_delivery_date(), mono=True)
        self._combo_field(gp3, 0, 2, "配送時段", "delivery_time",
                          list(DTIME_OPTIONS.keys()), default="01 不指定")

        # 快速日期按鈕（出貨日）
        def _quick_ship(offset):
            from datetime import date, timedelta
            d = _skip_sunday(date.today() + timedelta(days=offset))
            self.fields["shipment_date"].set(d.strftime("%Y%m%d"))
        sbtn_row = tk.Frame(gp3, bg=CARD)
        sbtn_row.grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(2, 0))
        for _lbl, _off in [("今天", 0), ("明天", 1), ("後天", 2)]:
            tk.Label(sbtn_row, text=_lbl, font=F_TINY, bg=CARD, fg=ACCENT,
                     cursor="hand2").pack(side="left", padx=(0, 6))
        for w, off in zip(sbtn_row.winfo_children(), [0, 1, 2]):
            w.bind("<Button-1>", lambda _, o=off: _quick_ship(o))

        # 快速日期按鈕（配送日）
        def _quick_deliv(offset):
            from datetime import date, timedelta
            d = _skip_sunday(date.today() + timedelta(days=offset))
            self.fields["delivery_date"].set(d.strftime("%Y%m%d"))
        dbtn_row = tk.Frame(gp3, bg=CARD)
        dbtn_row.grid(row=1, column=1, sticky="w", padx=(0, 8), pady=(2, 0))
        for _lbl, _off in [("今天", 0), ("明天", 1), ("後天", 2)]:
            tk.Label(dbtn_row, text=_lbl, font=F_TINY, bg=CARD, fg=ACCENT,
                     cursor="hand2").pack(side="left", padx=(0, 6))
        for w, off in zip(dbtn_row.winfo_children(), [0, 1, 2]):
            w.bind("<Button-1>", lambda _, o=off: _quick_deliv(o))

        # payment card
        pmc = Card(wrap, padding=22); pmc.pack(fill="x", pady=(0, 14))
        Kicker(pmc.body, "付款設定").pack(anchor="w", pady=(0, 12))
        gpay = tk.Frame(pmc.body, bg=CARD); gpay.pack(fill="x")
        gpay.columnconfigure(0, weight=1); gpay.columnconfigure(1, weight=1)
        self._toggle_group(gpay, 0, 0, "運費付款方式", "is_freight",
                           ["N 寄件人付", "Y 收件人付（運費到付）"], default="N 寄件人付")

        # 代收金額 — 僅在選擇代收時顯示
        gpay_cod = tk.Frame(pmc.body, bg=CARD)
        gpay_cod.columnconfigure(0, weight=1)
        self._field(gpay_cod, 0, 0, "代收金額", "collection_amount", default="0", mono=True)

        # 備註 — 永遠顯示
        gpay_notes = tk.Frame(pmc.body, bg=CARD)
        gpay_notes.columnconfigure(0, weight=1)
        self._field(gpay_notes, 0, 0, "備註", "notes", hint="選填")
        gpay_notes.pack(fill="x", pady=(12, 0))

        def _on_collection_change(val):
            if val.startswith("Y"):
                gpay_cod.pack(fill="x", pady=(12, 0), before=gpay_notes)
            else:
                gpay_cod.pack_forget()

        self._toggle_group(gpay, 0, 1, "代收貨款", "is_collection",
                           ["N 不代收", "Y 代收（貨到付款）"], default="N 不代收",
                           on_change=_on_collection_change)

        # submit
        sbtn = tk.Frame(wrap, bg=PAPER); sbtn.pack(fill="x", pady=(4, 0))
        TwButton(sbtn, "建立寄件單  →", variant="primary",
                 command=self._submit, width=20).pack(side="left")
        self._next_btn = TwButton(sbtn, "建立下一筆  →", variant="ghost",
                                  command=self._clear_for_next)
        self._go_print_btn = TwButton(sbtn, "前往待列印貨運單  →", variant="ghost",
                                      command=lambda: self.app.show_view("print_queue"))
        # both buttons initially hidden; shown after first successful submit

        self.result_var = tk.StringVar()
        self.result_lbl = tk.Label(wrap, textvariable=self.result_var,
            bg=PAPER, fg=INK2, font=F_SMALL, wraplength=820, justify="left")
        self.result_lbl.pack(fill="x", pady=(14, 0))

        # (staging display moved to 待列印貨運單 view)

    def _field(self, parent, r, c, label, key, required=False, default="", mono=False, hint=None):
        cell = tk.Frame(parent, bg=_frame_bg(parent))
        cell.grid(row=r*2, column=c, sticky="ew", padx=(0 if c == 0 else 12, 0))
        field_label(cell, label, required=required, hint=hint).pack(fill="x", pady=(0, 6))
        v = tk.StringVar(value=default)
        self.fields[key] = v
        e = ttk.Entry(cell, textvariable=v, style="Tw.TEntry",
                      font=F_MONO if mono else F_NORM)
        e.pack(fill="x")
        self._field_widgets[key] = e

    def _combo_field(self, parent, r, c, label, key, options, default=""):
        cell = tk.Frame(parent, bg=_frame_bg(parent))
        cell.grid(row=r*2, column=c, sticky="ew", padx=(0 if c == 0 else 12, 0))
        field_label(cell, label).pack(fill="x", pady=(0, 6))
        v = tk.StringVar(value=default)
        self.fields[key] = v
        cb = ttk.Combobox(cell, textvariable=v, values=options,
                          state="readonly", style="Tw.TCombobox", font=F_NORM)
        cb.pack(fill="x")

    def _toggle_group(self, parent, r, c, label, key, options, default="", on_change=None):
        """Segmented toggle button group. options = list of display strings (e.g. 'N 寄件人付')."""
        cell = tk.Frame(parent, bg=_frame_bg(parent))
        cell.grid(row=r*2, column=c, sticky="ew", padx=(0 if c == 0 else 12, 0))
        field_label(cell, label).pack(fill="x", pady=(0, 6))

        v = tk.StringVar(value=default)
        self.fields[key] = v

        container = tk.Frame(cell, bg=HAIR)
        container.pack(fill="x")

        btn_map = {}

        def _refresh(*_):
            val = v.get()
            for bval, btn in btn_map.items():
                if bval == val:
                    btn.configure(bg=INK, fg="#FFFFFF")
                else:
                    btn.configure(bg=CARD, fg=INK)
            if on_change:
                on_change(val)

        for i, opt in enumerate(options):
            display = opt[2:] if len(opt) > 2 else opt
            btn = tk.Label(container, text=display, font=F_BOLD, padx=14, pady=9,
                           cursor="hand2", bg=CARD, fg=INK)
            btn.pack(side="left", fill="x", expand=True, padx=(1 if i > 0 else 0, 0))
            btn_map[opt] = btn
            btn.bind("<Button-1>", lambda e, val=opt: v.set(val))
            btn.bind("<Enter>", lambda e, b=btn: b.cget("bg") != INK and b.configure(bg=HAIR2))
            btn.bind("<Leave>", lambda e, b=btn: b.cget("bg") != INK and b.configure(bg=CARD))

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
        for lbl, btn in self._cat_btns.items():
            btn.configure(bg=INK if lbl == label else CARD,
                          fg="#FFFFFF" if lbl == label else INK)
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
            for btn in self._cat_btns.values():
                btn.configure(bg=CARD, fg=INK)

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
        cat = self._cat_var.get() if self._cat_var else ""
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
            self._pkg_toggle_lbl.configure(text="▸ 展開")
            self._pkg_expanded = False
        else:
            self._pkg_detail.pack(fill="x")
            self._pkg_toggle_lbl.configure(text="▾ 收合")
            self._pkg_expanded = True

    def _submit(self):
        from datetime import datetime as _dt
        values = self._get_values()
        required = {"order_id": "訂單號碼", "recipient_name": "收件人姓名",
                    "recipient_address": "收件人地址", "recipient_phone": "收件人電話"}
        for k, label in required.items():
            if not values.get(k):
                messagebox.showwarning("缺少必填欄位", f"請填寫「{label}」"); return

        # S2：電話格式寬鬆檢查（不擋送出，只警告）
        phone = values.get("recipient_phone", "")
        if phone and len(re.sub(r"\D", "", phone)) < 8:
            messagebox.showwarning("電話格式可能有誤",
                f"收件人電話「{phone}」數字不足 8 碼，請確認後再送出。\n（仍可繼續送出）")

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
                Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
                results = create_orders(client, [values], sender, output_dir=OUTPUT_DIR)
                r = results[0]
                if r["success"]:
                    msg = f"✓ 建單成功！OBT：{r['obt_number']}"
                    _append_build_log(f"✓ OBT:{r['obt_number']} 收件人:{values.get('recipient_name','')} 訂單:{values.get('order_id','')}")
                    append_tracking(r['obt_number'], values.get('recipient_name',''), values.get('order_id',''))
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
    def __init__(self, master, app):
        super().__init__(master, bg=PAPER)
        self.app = app
        self.orders = []
        self.output_dir = OUTPUT_DIR
        self._build()

    def _build(self):
        # outer canvas so the whole batch view scrolls
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

        # header
        head = tk.Frame(wrap, bg=PAPER); head.pack(fill="x", pady=(0, 16))
        SectionHeader(head, "CSV 匯入", "批次建單").pack(side="left")
        ba = tk.Frame(head, bg=PAPER); ba.pack(side="right")
        TwButton(ba, "產生 CSV 範本", variant="default",
                 command=self._gen_template).pack(side="left", padx=4)
        TwButton(ba, "載入 CSV", variant="primary",
                 command=self._load_csv).pack(side="left", padx=4)

        # stats strip
        self.stats_row = tk.Frame(wrap, bg=PAPER)
        self.stats_row.pack(fill="x", pady=(0, 14))
        self._render_stats()

        # file pill
        self.file_lbl = tk.Label(wrap, text="尚未載入 CSV 檔案",
            font=F_TINY, bg=PAPER, fg=MUTED, anchor="w")
        self.file_lbl.pack(fill="x", pady=(0, 8))

        # table card
        tcard = Card(wrap, padding=0); tcard.pack(fill="both", expand=True)
        cols = ["order_id", "recipient_name", "recipient_phone", "recipient_address", "spec", "thermo"]
        labels = {"order_id": "訂單號", "recipient_name": "收件人",
                  "recipient_phone": "電話", "recipient_address": "地址",
                  "spec": "尺寸", "thermo": "溫層"}
        widths = {"order_id": 180, "recipient_name": 100, "recipient_phone": 130,
                  "recipient_address": 280, "spec": 70, "thermo": 70}
        self.tree = ttk.Treeview(tcard.body, columns=cols, show="headings",
                                 style="Tw.Treeview", height=14)
        for c in cols:
            self.tree.heading(c, text=labels[c])
            self.tree.column(c, width=widths[c], anchor="w")
        vsb = ttk.Scrollbar(tcard.body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # footer
        ft = tk.Frame(wrap, bg=PAPER); ft.pack(fill="x", pady=(14, 0))
        self.dir_lbl = tk.Label(ft, text=f"PDF 儲存目錄： {self.output_dir}",
            font=F_TINY, bg=PAPER, fg=MUTED, anchor="w")
        self.dir_lbl.pack(side="left")
        TwButton(ft, "變更目錄", variant="ghost",
                 command=self._pick_dir).pack(side="left", padx=8)

        fa = tk.Frame(ft, bg=PAPER); fa.pack(side="right")
        TwButton(fa, "清除列表", variant="ghost", command=self._clear).pack(side="left", padx=4)
        TwButton(fa, "全部建單  →", variant="primary",
                 command=self._submit_all, width=14).pack(side="left", padx=4)

        # log card
        self.progress_lbl = tk.Label(wrap, text="", font=F_SMALL, bg=PAPER, fg=MUTED, anchor="w")
        self.progress_lbl.pack(fill="x", pady=(14, 2))
        self.log = scrolledtext.ScrolledText(wrap, height=6, font=F_MONO,
            bg=CARD, fg=INK2, relief="flat", state="disabled",
            highlightbackground=HAIR, highlightthickness=1)
        self.log.pack(fill="x")

    def _render_stats(self):
        for w in self.stats_row.winfo_children(): w.destroy()
        ok_n   = sum(1 for o in self.orders
                    if all((o.get(k) or "").strip()
                           for k in ("recipient_name", "recipient_phone", "recipient_address")))
        warn_n = len(self.orders) - ok_n
        stats = [
            ("已載入", str(len(self.orders)), "筆", INK),
            ("有效",   str(ok_n),             "筆", OK),
            ("警示",   str(warn_n),           "筆", WARN if warn_n else MUTED),
            ("輸出目錄", Path(self.output_dir).name or "—", "", INK),
        ]
        for i, (l, v, u, c) in enumerate(stats):
            sc = Card(self.stats_row, padding=14)
            sc.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 8, 0))
            self.stats_row.columnconfigure(i, weight=1)
            Kicker(sc.body, l).pack(anchor="w")
            tk.Label(sc.body, text=v, font=(MONO_FAMILY, _sz(20), "bold"),
                     bg=CARD, fg=c).pack(anchor="w", pady=(2, 0))
            if u:
                tk.Label(sc.body, text=u, font=F_TINY, bg=CARD, fg=MUTED).pack(anchor="w")

    def _log(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

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

    def _load_csv(self):
        path = filedialog.askopenfilename(
            title="選擇訂單 CSV",
            filetypes=[("CSV", "*.csv"), ("All", "*.*")],
        )
        if not path: return
        try:
            self.orders = load_orders(path)
        except Exception as ex:
            messagebox.showerror("讀取失敗", str(ex)); return

        self.file_lbl.config(text=f"已載入  {Path(path).name}  ·  {len(self.orders)} 筆",
                             fg=INK2)
        for item in self.tree.get_children(): self.tree.delete(item)
        for o in self.orders:
            self.tree.insert("", "end", values=[
                o.get("order_id", ""), o.get("recipient_name", ""),
                o.get("recipient_phone", ""), o.get("recipient_address", ""),
                o.get("spec", "0002"),
                {"0001":"常溫","0002":"冷藏","0003":"冷凍"}.get(o.get("thermosphere",""), "—"),
            ])
        self._render_stats()
        self._log(f"載入 {len(self.orders)} 筆訂單")

    def _clear(self):
        self.orders = []
        for item in self.tree.get_children(): self.tree.delete(item)
        self.file_lbl.config(text="尚未載入 CSV 檔案", fg=MUTED)
        self._render_stats()

    def _pick_dir(self):
        d = filedialog.askdirectory(title="選擇 PDF 儲存目錄", initialdir=self.output_dir)
        if d:
            self.output_dir = d
            self.dir_lbl.config(text=f"PDF 儲存目錄： {self.output_dir}")
            self._render_stats()

    def _submit_all(self):
        if not self.orders:
            messagebox.showwarning("沒有訂單", "請先載入 CSV 檔案。"); return
        cfg = load_cfg()
        sender = cfg.get("sender") or {}
        if not sender.get("name"):
            messagebox.showwarning("寄件人資料未設定", "請先到「設定」頁填寫寄件人資料。"); return

        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        total = len(self.orders)
        self._log(f"開始建單，共 {total} 筆…")
        self.after(0, lambda: self.progress_lbl.config(text=f"建單中 0 / {total} 筆…", fg=MUTED))

        def run():
            client = make_client(cfg)
            for i, order in enumerate(self.orders, 1):
                oid = order.get("order_id", f"#{i}")
                try:
                    api_order = _csv_row_to_api_order(order, sender)
                    resp = client.print_obt([api_order])
                    if resp.get("IsOK") == "Y":
                        data = resp.get("Data") or {}
                        if isinstance(data, list) and data: data = data[0]
                        obt = data.get("OBTNumber", "")
                        pdf = data.get("PDF", "")
                        if pdf:
                            pdf_path = str(Path(self.output_dir) / f"{oid}_{obt}.pdf")
                            save_pdf(pdf, pdf_path)
                            self.after(0, lambda o=oid, n=obt: self._log(f"✓ {o}  OBT:{n}"))
                            _append_build_log(f"✓ OBT:{obt} 訂單:{oid}")
                            append_tracking(obt, order.get("recipient_name", ""), oid)
                        else:
                            self.after(0, lambda o=oid: self._log(f"✓ {o}  (無PDF)"))
                            _append_build_log(f"✓ 無PDF 訂單:{oid}")
                    else:
                        msg = resp.get("Message", "")[:60]
                        self.after(0, lambda o=oid, m=msg: self._log(f"✗ {o}: {m}"))
                        _append_build_log(f"✗ 訂單:{oid} {msg}")
                except Exception as ex:
                    self.after(0, lambda o=oid, e=str(ex): self._log(f"✗ {o}: {e}"))
                    _append_build_log(f"✗ 訂單:{oid} 例外:{str(ex)[:80]}")
                self.after(0, lambda _i=i, _t=total: self.progress_lbl.config(
                    text=f"建單中 {_i} / {_t} 筆…", fg=MUTED))

            import subprocess
            self.after(0, lambda: self._log("── 完成 ──"))
            self.after(0, lambda _t=total: self.progress_lbl.config(
                text=f"✓ 完成 {_t} 筆", fg=OK))
            self.after(0, lambda d=self.output_dir: subprocess.run(["open", d]))

        threading.Thread(target=run, daemon=True).start()


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

class TrackingView(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg=PAPER)
        self.app = app
        self._records = []
        self._filter = "all"   # all / progress / ok / err
        self._status_labels: dict[str, tk.Label] = {}
        self._filter_btns: dict[str, tk.Label] = {}
        self._count_lbls: dict[str, tk.Label] = {}
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
        TwButton(ba, "重新整理", variant="ghost", command=self.refresh).pack(side="left", padx=4)
        TwButton(ba, "清除兩週前紀錄", variant="ghost", command=self._prune).pack(side="left", padx=4)

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
        self._result_count.pack(side="right", padx=14)
        Hairline(tcard.body).pack(fill="x")

        # column header
        hdr = tk.Frame(tcard.body, bg=PAPER2)
        hdr.pack(fill="x")
        cols = [("建單時間", 17), ("收件人", 16), ("貨運單號", 16),
                ("訂單編號", 14), ("配送狀態", 14), ("", 0)]
        for txt, w in cols:
            tk.Label(hdr, text=txt, font=F_KICKER, bg=PAPER2, fg=MUTED,
                     width=w if w else 1, anchor="w", padx=10, pady=8).pack(side="left")
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
        if status in ("—", "查詢中…"): return "neutral"
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

    def refresh(self):
        import datetime
        records = load_tracking()
        cutoff = (datetime.datetime.now() - datetime.timedelta(days=14)).isoformat()
        records = [r for r in records if r.get("created_at", "") >= cutoff]
        records.sort(key=lambda r: r.get("created_at", ""), reverse=True)
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
                 if filt == "all" or self._status_tone(r.get("status","—")) == filt]

        self._result_count.config(text=f"顯示 {len(shown)} 筆")

        if not shown:
            msg = "尚無建單紀錄\n（建立寄件單後會自動顯示在這裡）" if filt == "all" else "此分類沒有資料"
            tk.Label(self._list_body, text=msg,
                     bg=CARD, fg=MUTED, font=F_SMALL, justify="center").pack(pady=60)
            return

        for i, r in enumerate(shown):
            self._make_row(r, i < len(shown) - 1)
        tk.Frame(self._list_body, bg=CARD, height=12).pack()

    def _make_row(self, r: dict, divider=True):
        obt     = r.get("obt_number", "—")
        name    = r.get("recipient_name", "—")
        oid     = r.get("order_id", "—")
        created = r.get("created_at", "")[:16].replace("T", " ")
        status  = r.get("status", "—")
        queried = r.get("queried_at", "")

        s_fg = _status_fg(status)

        row = tk.Frame(self._list_body, bg=CARD)
        row.pack(fill="x")
        inner = tk.Frame(row, bg=CARD)
        inner.pack(fill="x", padx=4, pady=10)

        tk.Label(inner, text=created,   font=F_TINY, bg=CARD, fg=MUTED, width=17, anchor="w").pack(side="left", padx=(8, 0))
        tk.Label(inner, text=name,      font=F_NORM, bg=CARD, fg=INK,   width=16, anchor="w").pack(side="left", padx=(8, 0))
        tk.Label(inner, text=obt,       font=F_MONO, bg=CARD, fg=INK,   width=16, anchor="w").pack(side="left", padx=(8, 0))
        tk.Label(inner, text=oid[:14],  font=F_TINY, bg=CARD, fg=INK2,  width=14, anchor="w").pack(side="left", padx=(8, 0))

        # status pill
        stone = self._status_tone(status)
        pill_bg = {
            "ok": OK2, "err": ERR2, "progress": WARN2, "neutral": HAIR3,
        }.get(stone, HAIR3)
        pill_fg = {
            "ok": OK, "err": ERR, "progress": WARN, "neutral": MUTED,
        }.get(stone, MUTED)
        slbl = tk.Label(inner, text=f"● {status}", font=F_TINY, bg=pill_bg, fg=pill_fg,
                        padx=7, pady=3, width=14, anchor="w")
        slbl.pack(side="left", padx=(8, 0))
        self._status_labels[obt] = slbl

        if queried:
            slbl.bind("<Enter>", lambda e, t=queried: slbl.config(text=f"查詢 {t[11:16]}"))
            slbl.bind("<Leave>", lambda e, s=status: slbl.config(text=f"● {s}"))

        btns = tk.Frame(inner, bg=CARD)
        btns.pack(side="right", padx=(4, 8))
        TwButton(btns, "查詢", variant="ghost",
                 command=lambda _obt=obt: self._query_one(_obt)).pack(side="left", padx=(0, 4))
        TwButton(btns, "複製", variant="ghost",
                 command=lambda _obt=obt: self._copy(_obt)).pack(side="left", padx=(0, 4))
        TwButton(btns, "刪除", variant="ghost",
                 command=lambda _obt=obt: self._delete_one(_obt)).pack(side="left")

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

    def _delete_one(self, obt: str):
        if not messagebox.askyesno("確認刪除", f"確定要刪除單號 {obt} 的紀錄嗎？", parent=self):
            return
        records = load_tracking()
        records = [r for r in records if r.get("obt_number") != obt]
        save_tracking(records)
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

    def _query_all(self):
        obts = [r.get("obt_number") for r in self._records if r.get("obt_number")]
        for obt in obts:
            lbl = self._status_labels.get(obt)
            if lbl and lbl.winfo_exists():
                lbl.config(text="● 查詢中…", bg=HAIR3, fg=MUTED)

        def run():
            for obt in obts:
                result = _fetch_obt_status(obt)
                self.after(0, lambda _o=obt, _r=result: self._set_status(_o, _r))

        threading.Thread(target=run, daemon=True).start()

    def _copy(self, text: str):
        self.clipboard_clear()
        self.clipboard_append(text)

    def _prune(self):
        import datetime
        records = load_tracking()
        cutoff = (datetime.datetime.now() - datetime.timedelta(days=14)).isoformat()
        kept = [r for r in records if r.get("created_at", "") >= cutoff]
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
        out = Path(OUTPUT_DIR) / f"combined_{int(time.time())}.pdf"
        Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
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
            tag = tk.Label(body, text=c["notes"][:8], font=F_TINY,
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
        contacts = [c for c in load_contacts() if c.get("name") not in names]
        save_contacts(contacts)
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
        contacts = [c for c in load_contacts() if c.get("name") != name]
        save_contacts(contacts)
        self._selected = None
        self.refresh()

    def _on_save(self, contact, original_name=None):
        if not contact.get("category"):
            contact["category"] = self._active_tab
        contacts = load_contacts()
        if original_name:
            contacts = [c for c in contacts if c.get("name") != original_name]
        contacts.append(contact)
        contacts.sort(key=lambda c: c.get("name", ""))
        save_contacts(contacts)
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
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=["name", "phone", "mobile", "address", "notes"])
            writer.writeheader()
            for c in contacts:
                writer.writerow({k: c.get(k, "") for k in ["name", "phone", "mobile", "address", "notes"]})
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
        existing = load_contacts()
        ans = messagebox.askyesnocancel(
            "匯入方式",
            f"CSV 內有 {len(new_contacts)} 筆聯絡人。\n\n"
            f"選「是」：附加到現有 {len(existing)} 筆\n"
            f"選「否」：全部取代\n"
            f"取消：中止",
        )
        if ans is None: return
        if ans:
            existing_names = {c.get("name") for c in existing}
            merged = existing + [c for c in new_contacts if c.get("name") not in existing_names]
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
            e = ttk.Entry(cell, textvariable=v, style="Tw.TEntry",
                          font=F_MONO,
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
                ttk.Entry(cell, textvariable=v, style="Tw.TEntry",
                          font=F_NORM).pack(fill="x")
            else:
                cell = tk.Frame(sg, bg=CARD)
                cell.grid(row=r, column=c, sticky="ew",
                          padx=(0 if c == 0 else 12, 0), pady=(0 if r == 0 else 12, 0))
                req = field in ("name", "tel", "zipcode")
                field_label(cell, label, required=req).pack(fill="x", pady=(0, 6))
                v = tk.StringVar(); self.vars[key] = v
                ttk.Entry(cell, textvariable=v, style="Tw.TEntry",
                          font=F_MONO if field in ("tel","mobile","zipcode") else F_NORM).pack(fill="x")

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
        TwButton(wc.body, "儲存登入資訊", variant="primary",
                 command=self._save).pack(anchor="w", pady=(12, 0))

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
        paths = [
            ("PDF 輸出目錄", "~/黑貓單號"),
            ("設定檔",       "./config.yaml"),
            ("通訊錄資料",   "./contacts.json"),
            ("建單紀錄",     "./tracking.json"),
            ("建單日誌",     "~/黑貓單號/build_log.txt"),
        ]
        for i, (k, v) in enumerate(paths):
            pr = tk.Frame(pc.body, bg=HAIR3)
            pr.pack(fill="x", pady=(0 if i == 0 else 4, 0))
            inner = tk.Frame(pr, bg=HAIR3); inner.pack(fill="x", padx=12, pady=8)
            tk.Label(inner, text=k, font=F_TINY, bg=HAIR3, fg=MUTED, width=12, anchor="w").pack(side="left")
            tk.Label(inner, text=v, font=F_MONO, bg=HAIR3, fg=INK).pack(side="left", padx=(8, 0))

        # status text
        self.status = tk.Label(wrap, text="", bg=PAPER, font=F_SMALL, anchor="w")
        self.status.pack(fill="x", pady=(8, 0))

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


# ─── freight fee view ────────────────────────────────────────────────────────

class FreightView(tk.Frame):
    """運費明細查詢 — 透過契客專區網頁查詢交易明細"""

    def __init__(self, master, app):
        super().__init__(master, bg=PAPER)
        self.app = app
        self._results: list[dict] = []
        self._mode = "send"
        self._web: TakkyubinWebClient | None = None
        self._build()

    def _build(self):
        from datetime import date as _d, timedelta as _td
        wrap = tk.Frame(self, bg=PAPER)
        wrap.pack(fill="both", expand=True, padx=28, pady=24)

        # ── header ────────────────────────────────────────────────────────────
        head = tk.Frame(wrap, bg=PAPER); head.pack(fill="x", pady=(0, 16))
        SectionHeader(head, "費用查詢", "運費明細查詢").pack(side="left")

        # ── query card ────────────────────────────────────────────────────────
        qc = Card(wrap, padding=20); qc.pack(fill="x", pady=(0, 14))

        # mode tabs
        tabs_row = tk.Frame(qc.body, bg=CARD); tabs_row.pack(fill="x", pady=(0, 14))
        self._mode_btns = {}
        for mid, mlabel in [("send", "我的寄件費用"), ("recv", "到付收件費用")]:
            btn = tk.Label(tabs_row, text=mlabel,
                           font=(FONT_FAMILY, _sz(12), "bold"),
                           bg=ACCENT if mid == "send" else HAIR3,
                           fg="#FFFFFF" if mid == "send" else INK2,
                           padx=14, pady=6, cursor="hand2", relief="flat")
            btn.pack(side="left", padx=(0, 6))
            btn.bind("<Button-1>", lambda e, m=mid: self._set_mode(m))
            self._mode_btns[mid] = btn

        # date row
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

        # ── results card ─────────────────────────────────────────────────────
        rcard = Card(wrap, padding=0); rcard.pack(fill="both", expand=True)
        self._summary_lbl = tk.Label(rcard.body, text="尚無查詢資料",
                                     font=F_SMALL, bg=PAPER2, fg=MUTED,
                                     pady=10, anchor="w", padx=16)
        self._summary_lbl.pack(fill="x")
        Hairline(rcard.body).pack(fill="x")
        hdr = tk.Frame(rcard.body, bg=PAPER2); hdr.pack(fill="x")
        for txt, w in [("集貨日期",12),("集貨所",10),("配完日期",12),("配完所",10),
                       ("訂單編號",14),("託運單號",16),("運費(元)",8),("附加服務金",9),("類型",10)]:
            tk.Label(hdr, text=txt, font=F_KICKER, bg=PAPER2, fg=MUTED,
                     width=w, anchor="w", padx=8, pady=8).pack(side="left")
        Hairline(rcard.body).pack(fill="x")
        lf = tk.Frame(rcard.body, bg=CARD); lf.pack(fill="both", expand=True)
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
        _bind_mousewheel_on_hover(self._list_body, canvas)
        _bind_mousewheel_on_hover(canvas, canvas)

    # ── internals ──────────────────────────────────────────────────────────────

    def _set_mode(self, mode: str):
        self._mode = mode
        for mid, btn in self._mode_btns.items():
            sel = mid == mode
            btn.configure(bg=ACCENT if sel else HAIR3, fg="#FFFFFF" if sel else INK2)
        self._render_rows()

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

        # Check session
        need_login = (self._web is None) or (not self._web.is_logged_in())
        if need_login:
            self._do_login(username, password, account, start, end)
        else:
            self._do_query(account, start, end)

    def _do_login(self, username: str, password: str,
                  account: str, start: str, end: str):
        """Show CAPTCHA dialog then login in background."""
        self._status_lbl.config(text="正在載入驗證碼…", fg=MUTED)
        self._web = TakkyubinWebClient()

        def fetch():
            try:
                tokens, img_bytes = self._web.get_login_page()
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

        tk.Label(f, text="請輸入驗證碼後登入", font=(FONT_FAMILY, _sz(13), "bold"),
                 bg=PAPER, fg=INK).pack(pady=(0, 12))

        if img_bytes:
            try:
                img = tk.PhotoImage(data=img_bytes)
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
                    ok = self._web.login(username, password, code, tokens)
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
                  font=(FONT_FAMILY, _sz(12)), bg=ACCENT, fg="#FFFFFF",
                  relief="flat", padx=16, pady=6, cursor="hand2").pack(side="left", padx=(0,8))
        tk.Button(btn_row, text="取消", command=dlg.destroy,
                  font=(FONT_FAMILY, _sz(12)), bg=HAIR3, fg=INK2,
                  relief="flat", padx=16, pady=6, cursor="hand2").pack(side="left")
        e.bind("<Return>", lambda _: _submit())

    def _do_query(self, account: str, start: str, end: str):
        self._status_lbl.config(text="查詢中…", fg=MUTED)
        self._results = []
        self._render_rows()
        self._summary_lbl.config(text="查詢中…", fg=MUTED)

        def run():
            try:
                data = self._web.query_payment(start, end, account)
                self.after(0, lambda: self._on_result(data, start, end))
            except RuntimeError as ex:
                if "session_expired" in str(ex):
                    self._web = None
                    self.after(0, lambda: self._status_lbl.config(
                        text="工作階段已過期，請重新查詢", fg=WARN))
                else:
                    self.after(0, lambda msg=str(ex): self._on_error(msg))
            except Exception as ex:
                self.after(0, lambda msg=str(ex): self._on_error(msg))
        import threading; threading.Thread(target=run, daemon=True).start()

    def _on_result(self, data: list, start: str, end: str):
        self._results = data
        n = len(data)
        try:
            total = sum(int(r.get("freight","0") or 0) for r in data)
        except Exception: total = 0
        s = f"{start[:4]}/{start[4:6]}/{start[6:]}"
        e_str = f"{end[:4]}/{end[4:6]}/{end[6:]}"
        self._summary_lbl.config(
            text=f"  {s} ～ {e_str}   共 {n} 筆，運費計 {total:,} 元", fg=INK)
        self._status_lbl.config(text=f"✓ 查詢完成，共 {n} 筆", fg=OK)
        self._render_rows()

    def _on_error(self, msg: str):
        self._status_lbl.config(text="✗ 查詢失敗，詳見下方", fg=ERR)
        self._summary_lbl.config(text="—", fg=MUTED)
        for w in self._list_body.winfo_children(): w.destroy()
        tk.Frame(self._list_body, bg=CARD, height=32).pack()
        tk.Label(self._list_body, text="查詢失敗",
                 font=(FONT_FAMILY, _sz(14), "bold"), bg=CARD, fg=INK).pack()
        tk.Label(self._list_body,
                 text="請確認網路連線，或重新登入後再試。",
                 font=F_SMALL, bg=CARD, fg=INK3, justify="center").pack(pady=(8, 12))
        err_frame = tk.Frame(self._list_body, bg=HAIR3, padx=16, pady=12)
        err_frame.pack(fill="x", padx=32, pady=(0, 16))
        err_box = tk.Text(err_frame, height=4, font=(MONO_FAMILY, _sz(10)),
                          bg=HAIR3, fg=INK2, relief="flat", wrap="word", bd=0)
        err_box.insert("1.0", msg); err_box.configure(state="disabled"); err_box.pack(fill="x")
        btn_row = tk.Frame(self._list_body, bg=CARD); btn_row.pack(pady=(0, 24))
        TwButton(btn_row, "重新登入查詢", variant="primary",
                 command=self._query).pack(side="left", padx=(0,8))

    def _render_rows(self):
        for w in self._list_body.winfo_children(): w.destroy()
        if self._mode == "send":
            rows = [r for r in self._results
                    if r.get("shipment_type","") not in ("到付",) and
                       r.get("is_cash","") != "Y"]
        else:
            rows = [r for r in self._results
                    if r.get("shipment_type","") == "到付" or r.get("is_cash","") == "Y"]
        # If can't distinguish, show all
        if not rows and self._results:
            rows = self._results
        if not rows:
            tk.Label(self._list_body,
                     text="尚無資料" if not self._results else "此分類無資料",
                     bg=CARD, fg=MUTED, font=F_SMALL, justify="center").pack(pady=60)
            return
        for i, r in enumerate(rows):
            row = tk.Frame(self._list_body, bg=CARD); row.pack(fill="x")
            inner = tk.Frame(row, bg=CARD); inner.pack(fill="x", padx=4, pady=8)
            try: fee_s = f"{int(r.get('freight','0') or 0):,}"
            except Exception: fee_s = r.get("freight","—")
            try: add_s = f"{int(r.get('add_fee','0') or 0):,}"
            except Exception: add_s = r.get("add_fee","—")
            tags = []
            if r.get("is_cash") == "Y": tags.append("收現")
            if r.get("is_return") == "Y": tags.append("退貨")
            if r.get("is_same_day") == "Y": tags.append("當配")
            type_s = r.get("shipment_type","") or ("、".join(tags) if tags else "—")
            col_data = [
                (r.get("pickup_date","—"),   12, F_MONO, INK2),
                (r.get("pickup_place","—"),  10, F_NORM, INK),
                (r.get("delivery_date","—"), 12, F_MONO, INK2),
                (r.get("delivery_place","—"),10, F_NORM, INK),
                (r.get("order_id","—"),      14, F_MONO, INK),
                (r.get("obt","—"),           16, F_MONO, MUTED),
                (fee_s,                       8, F_MONO, INK),
                (add_s,                       9, F_MONO, MUTED),
                (type_s,                     10, F_NORM, INK3),
            ]
            for text, w, font, fg in col_data:
                tk.Label(inner, text=str(text), font=font, bg=CARD, fg=fg,
                         width=w, anchor="w", padx=8).pack(side="left")
            if i < len(rows)-1: Hairline(self._list_body).pack(fill="x")
        tk.Frame(self._list_body, bg=CARD, height=12).pack()


# ─── dialogs ─────────────────────────────────────────────────────────────────

CONTACT_FIELDS = [("name", "姓名 *"), ("phone", "電話"),
                   ("mobile", "手機"), ("address", "地址"), ("notes", "備註")]

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
                 bg=PAPER, fg=INK).pack(anchor="w", pady=(0, 16))

        grid = tk.Frame(wrap, bg=PAPER)
        grid.pack(fill="x")
        for i, (key, label) in enumerate(CONTACT_FIELDS):
            field_label(grid, label.replace(" *", ""),
                        required=("*" in label)).grid(row=i*2, column=0, sticky="w", pady=(8 if i else 0, 4))
            v = tk.StringVar(value=contact.get(key, ""))
            self.vars[key] = v
            ttk.Entry(grid, textvariable=v, style="Tw.TEntry",
                      font=F_MONO if key in ("phone","mobile") else F_NORM,
                      width=36).grid(row=i*2+1, column=0, sticky="ew")

        # Category
        tk.Label(wrap, text="分類", font=F_LABEL, bg=PAPER, fg=MUTED).pack(anchor="w", pady=(12, 4))
        cat_frame = tk.Frame(wrap, bg=PAPER)
        cat_frame.pack(anchor="w")
        self.vars["category"] = tk.StringVar(value=contact.get("category", "門市"))
        for cat in ("門市", "廠商"):
            tk.Radiobutton(cat_frame, text=cat, variable=self.vars["category"],
                           value=cat, bg=PAPER, activebackground=PAPER,
                           font=F_NORM, fg=INK).pack(side="left", padx=(0, 16))

        ba = tk.Frame(wrap, bg=PAPER); ba.pack(fill="x", pady=(20, 0))
        TwButton(ba, "儲存", variant="primary", command=self._save).pack(side="left", padx=(0, 8))
        TwButton(ba, "取消", variant="ghost", command=self.destroy).pack(side="left")

    def _save(self):
        contact = {k: v.get().strip() for k, v in self.vars.items()}
        if not contact.get("name"):
            messagebox.showwarning("必填", "姓名為必填欄位。", parent=self); return
        self.on_save(contact, self.original_name)
        self.destroy()


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


# ─── entry ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = App()
    app.mainloop()
