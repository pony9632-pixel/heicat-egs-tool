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
from order import generate_template, load_orders, create_orders, TEMPLATE_FIELDS, _csv_row_to_api_order

CONFIG_PATH   = "config.yaml"
CONTACTS_PATH         = "contacts.json"
DEFAULT_CONTACTS_PATH = "default_contacts.json"
OUTPUT_DIR    = str(Path(__file__).parent.parent / "黑貓單號")


def _append_build_log(msg: str):
    """將建單結果 append 到 黑貓單號/build_log.txt"""
    import datetime
    log_path = Path(OUTPUT_DIR) / "build_log.txt"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as _f:
        _f.write(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")


VERSION     = "1.6.0"
GITHUB_REPO = "pony9632-pixel/heicat-egs-tool"

# ─── Tidewater palette ───────────────────────────────────────────────────────
PAPER   = "#FBF9F4"
CARD    = "#FFFFFF"
INK     = "#1B2330"
INK2    = "#4A5462"
MUTED   = "#8A95A6"
HAIR    = "#E8E2D6"
HAIR2   = "#F1ECE0"
ACCENT  = "#C2552C"
ACCENT2 = "#FFF1E9"
OK      = "#2F7A4E"
WARN    = "#B07A1F"
ERR     = "#B3382A"
RAIL    = "#F4EFE3"

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
        os.execv(sys.executable, [sys.executable, str(Path(__file__))])

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

        # title bar (custom, soft)
        hdr = tk.Frame(self, bg=RAIL, height=44)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="STUDIO A 黑貓宅急便工具",
                 bg=RAIL, fg=INK2, font=F_BOLD).pack(side="left", padx=16)
        tk.Label(hdr, text=f"v{VERSION}",
                 bg=RAIL, fg=MUTED, font=F_TINY).pack(side="right", padx=16)

        # body — sidebar + content
        body = tk.Frame(self, bg=PAPER)
        body.pack(fill="both", expand=True)

        self.sidebar = Sidebar(body, self)
        self.sidebar.pack(side="left", fill="y")

        Hairline(body, horizontal=False, color=HAIR).pack(side="left", fill="y")

        self.content_host = tk.Frame(body, bg=PAPER)
        self.content_host.pack(side="left", fill="both", expand=True)

        self.views = {
            "single":   SingleOrderView(self.content_host, self),
            "batch":    BatchOrderView(self.content_host, self),
            "contacts": ContactsView(self.content_host, self),
            "settings": ConfigView(self.content_host, self),
        }
        for v in self.views.values():
            v.place(relx=0, rely=0, relwidth=1, relheight=1)

        self.show_view("single")
        self.bind_all("<Command-1>", lambda e: self.show_view("single"))
        self.bind_all("<Command-2>", lambda e: self.show_view("batch"))
        self.bind_all("<Command-3>", lambda e: self.show_view("contacts"))
        self.bind_all("<Command-4>", lambda e: self.show_view("settings"))

    def show_view(self, name):
        v = self.views.get(name)
        if not v: return
        v.lift()
        if hasattr(v, "on_show"): v.on_show()
        self.sidebar.set_active(name)
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


# ─── sidebar ─────────────────────────────────────────────────────────────────

class Sidebar(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg=RAIL, width=220)
        self.pack_propagate(False)
        self.app = app
        self._items = {}

        # brand
        brand = tk.Frame(self, bg=RAIL)
        brand.pack(fill="x", padx=18, pady=(20, 16))
        m = tk.Canvas(brand, width=28, height=28, bg=RAIL, highlightthickness=0)
        m.create_rectangle(4, 4, 26, 26, fill=INK, outline=INK)
        m.create_rectangle(9, 11, 21, 19, outline="#FFFFFF", width=2)
        m.pack(side="left", padx=(0, 10))
        info = tk.Frame(brand, bg=RAIL)
        info.pack(side="left")
        tk.Label(info, text="STUDIO A", font=F_BOLD, bg=RAIL, fg=INK).pack(anchor="w")
        tk.Label(info, text="黑貓宅急便工具", font=F_TINY, bg=RAIL, fg=MUTED).pack(anchor="w")

        # nav items
        nav = tk.Frame(self, bg=RAIL)
        nav.pack(fill="x", padx=10, pady=4)
        for key, label, kbd in [
            ("single",   "建立寄件單", "1"),
            ("batch",    "批次建單",   "2"),
            ("contacts", "通訊錄",     "3"),
            ("settings", "設定",       "4"),
        ]:
            self._items[key] = NavItem(nav, label, kbd, lambda k=key: self.app.show_view(k))
            self._items[key].pack(fill="x", pady=1)

        # spacer
        tk.Frame(self, bg=RAIL).pack(fill="both", expand=True)

        # sender preview card
        self.sender_card = tk.Frame(self, bg=RAIL)
        self.sender_card.pack(fill="x", padx=12, pady=12)
        self._render_sender()

    def _render_sender(self):
        for w in self.sender_card.winfo_children():
            w.destroy()
        cfg = load_cfg()
        sender = cfg.get("sender") or {}
        wrap = tk.Frame(self.sender_card, bg=CARD, highlightbackground=HAIR, highlightthickness=1)
        wrap.pack(fill="x")
        inner = tk.Frame(wrap, bg=CARD)
        inner.pack(fill="x", padx=12, pady=12)
        Kicker(inner, "寄件人").pack(anchor="w")
        tk.Label(inner, text=sender.get("name") or "（未設定）",
                 font=F_BOLD, bg=CARD, fg=INK, wraplength=170, justify="left").pack(anchor="w", pady=(6, 2))
        addr = sender.get("address") or "請至設定頁填寫"
        tk.Label(inner, text=addr, font=F_TINY, bg=CARD, fg=INK2,
                 wraplength=170, justify="left").pack(anchor="w")
        # status pill
        has_token = bool(cfg.get("api_token") and cfg.get("username"))
        s = tk.Frame(inner, bg=CARD); s.pack(anchor="w", pady=(8, 0))
        tk.Label(s, text="●", font=F_TINY, bg=CARD,
                 fg=OK if has_token else WARN).pack(side="left")
        tk.Label(s, text="API 已設定" if has_token else "尚未設定 API",
                 font=F_TINY, bg=CARD, fg=OK if has_token else WARN).pack(side="left", padx=(4, 0))

    def set_active(self, key):
        for k, item in self._items.items():
            item.set_active(k == key)

    def refresh_sender(self):
        self._render_sender()


class NavItem(tk.Frame):
    def __init__(self, master, label, kbd, on_click):
        super().__init__(master, bg=RAIL)
        self._active = False
        self._on_click = on_click
        self.inner = tk.Frame(self, bg=RAIL)
        self.inner.pack(fill="x", padx=0)
        self.lbl = tk.Label(self.inner, text=label, font=F_NAV,
                            bg=RAIL, fg=INK2, anchor="w", padx=12, pady=8)
        self.lbl.pack(side="left", fill="x", expand=True)
        self.kbd = tk.Label(self.inner, text=f"⌘{kbd}", font=F_TINY,
                            bg=RAIL, fg=MUTED, padx=10)
        self.kbd.pack(side="right")
        for w in (self.inner, self.lbl, self.kbd):
            w.bind("<Button-1>", lambda e: self._on_click())
            w.bind("<Enter>", self._hover)
            w.bind("<Leave>", self._unhover)
            w.configure(cursor="hand2")

    def _hover(self, e):
        if self._active: return
        for w in (self.inner, self.lbl, self.kbd):
            w.configure(bg=HAIR2)

    def _unhover(self, e):
        if self._active: return
        for w in (self.inner, self.lbl, self.kbd):
            w.configure(bg=RAIL)

    def set_active(self, on):
        self._active = on
        bg = CARD if on else RAIL
        fg = INK if on else INK2
        kbd_bg = HAIR2 if on else RAIL
        for w in (self.inner, self.lbl, self.kbd):
            w.configure(bg=bg)
        self.lbl.configure(fg=fg, font=(FONT_FAMILY, _sz(12), "bold") if on else F_NAV)
        self.kbd.configure(bg=kbd_bg, fg=MUTED)


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
        self._staging = []   # list of {order_id, name, obt, pdf_path, var}
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
            self._vars["shipment_date"].set(d.strftime("%Y%m%d"))
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
            self._vars["delivery_date"].set(d.strftime("%Y%m%d"))
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

        self.result_var = tk.StringVar()
        self.result_lbl = tk.Label(wrap, textvariable=self.result_var,
            bg=PAPER, fg=INK2, font=F_SMALL, wraplength=820, justify="left")
        self.result_lbl.pack(fill="x", pady=(14, 0))

        # staging card — hidden until first order is created
        self._staging_card = Card(wrap, padding=18)
        sc = self._staging_card.body
        sh = tk.Frame(sc, bg=CARD); sh.pack(fill="x", pady=(0, 10))
        Kicker(sh, "待列印清單").pack(side="left")
        sg_btns = tk.Frame(sh, bg=CARD); sg_btns.pack(side="right")
        TwButton(sg_btns, "全選", variant="ghost",
                 command=self._select_all_staging).pack(side="left", padx=(0, 4))
        TwButton(sg_btns, "清除全部", variant="ghost",
                 command=self._clear_staging).pack(side="left")
        self._staging_list_frame = tk.Frame(sc, bg=CARD)
        self._staging_list_frame.pack(fill="x")
        sf = tk.Frame(sc, bg=CARD); sf.pack(fill="x", pady=(12, 0))
        self._print_btn = TwButton(sf, "列印選取 (0)", variant="primary",
                                   command=self._print_selected)
        self._print_btn.pack(side="right")

    def _field(self, parent, r, c, label, key, required=False, default="", mono=False, hint=None):
        cell = tk.Frame(parent, bg=_frame_bg(parent))
        cell.grid(row=r*2, column=c, sticky="ew", padx=(0 if c == 0 else 12, 0))
        field_label(cell, label, required=required, hint=hint).pack(fill="x", pady=(0, 6))
        v = tk.StringVar(value=default)
        self.fields[key] = v
        e = ttk.Entry(cell, textvariable=v, style="Tw.TEntry",
                      font=F_MONO if mono else F_NORM)
        e.pack(fill="x")

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
        var = tk.BooleanVar(value=False)
        var.trace_add("write", lambda *_: self._update_print_btn())
        self._staging.append({"order_id": order_id, "name": name,
                               "obt": obt, "pdf_path": pdf_path, "var": var})
        self._refresh_staging_ui()

    def _refresh_staging_ui(self) -> None:
        for w in self._staging_list_frame.winfo_children():
            w.destroy()
        if not self._staging:
            self._staging_card.pack_forget()
            return
        if not self._staging_card.winfo_ismapped():
            self._staging_card.pack(fill="x", pady=(14, 0))
        for item in self._staging:
            row = tk.Frame(self._staging_list_frame, bg=CARD)
            row.pack(fill="x", pady=(0, 4))
            tk.Checkbutton(row, variable=item["var"], bg=CARD,
                           activebackground=CARD, cursor="hand2").pack(side="left")
            tk.Label(row, text=item["order_id"], font=F_MONO, bg=CARD,
                     fg=INK, width=16, anchor="w").pack(side="left", padx=(4, 8))
            tk.Label(row, text=item["name"], font=F_NORM, bg=CARD,
                     fg=INK, width=10, anchor="w").pack(side="left", padx=(0, 8))
            tk.Label(row, text=item["obt"], font=F_MONO, bg=CARD,
                     fg=MUTED, anchor="w").pack(side="left")
        self._update_print_btn()

    def _update_print_btn(self) -> None:
        if not self._print_btn:
            return
        n = sum(1 for item in self._staging if item["var"].get())
        self._print_btn.set_text(f"列印選取 ({n})")

    def _select_all_staging(self) -> None:
        for item in self._staging:
            item["var"].set(True)

    def _clear_staging(self) -> None:
        self._staging.clear()
        self._refresh_staging_ui()

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

    def _print_selected(self) -> None:
        selected = [item for item in self._staging if item["var"].get()]
        if not selected:
            messagebox.showwarning("未選取", "請先勾選要列印的單據。")
            return
        try:
            if len(selected) == 1:
                out_path = selected[0]["pdf_path"]
            else:
                out_path = self._merge_labels_multi([i["pdf_path"] for i in selected])
            subprocess.run(["open", out_path])
            for item in selected:
                self._staging.remove(item)
            self._refresh_staging_ui()
        except Exception as ex:
            messagebox.showerror("列印失敗", str(ex))

    def _merge_labels_multi(self, paths: list) -> str:
        """每兩筆合成一頁 A4：第一筆在上半，第二筆平移到下半。奇數筆最後一頁留空白下半。"""
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
                    if r["pdf_path"]:
                        self._normalize_pdf_rotation(r["pdf_path"])
                        self.after(0, lambda obt=r["obt_number"], nm=values["recipient_name"],
                                          oid=values["order_id"], pp=r["pdf_path"]:
                                   self._add_to_staging(obt, nm, oid, pp))
                        self.after(50, self._clear_order_fields)
                        msg += "\nPDF 已加入待列印清單，選取後按「列印選取」輸出。"
                    self.after(0, lambda: self.result_lbl.configure(fg=OK))
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
        wrap = tk.Frame(self, bg=PAPER)
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
        self.tree = ttk.Treeview(tcard.inner, columns=cols, show="headings",
                                 style="Tw.Treeview", height=14)
        for c in cols:
            self.tree.heading(c, text=labels[c])
            self.tree.column(c, width=widths[c], anchor="w")
        vsb = ttk.Scrollbar(tcard.inner, orient="vertical", command=self.tree.yview)
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
        wrap.pack(fill="x", expand=False, padx=28, pady=24)

        head = tk.Frame(wrap, bg=PAPER); head.pack(fill="x", pady=(0, 16))
        SectionHeader(head, "通訊錄", "收件人管理").pack(side="left")
        ba = tk.Frame(head, bg=PAPER); ba.pack(side="right")
        TwButton(ba, "匯出 CSV", variant="ghost",
                 command=self._export_csv).pack(side="left", padx=4)
        TwButton(ba, "匯入 CSV", variant="ghost",
                 command=self._import_csv).pack(side="left", padx=4)
        self._del_sel_btn = TwButton(ba, "刪除選取 (0)", variant="danger",
                                      command=self._delete_checked)
        # _del_sel_btn is shown/hidden dynamically via _update_del_btn()
        self._add_btn = TwButton(ba, "＋ 新增聯絡人", variant="primary",
                                  command=self._add)
        self._add_btn.pack(side="left", padx=4)

        # split: list (left) + detail (right)
        split = tk.Frame(wrap, bg=PAPER); split.pack(fill="x", expand=False)
        split.columnconfigure(0, weight=2); split.columnconfigure(1, weight=1)

        # left list
        lcard = Card(split, padding=0)
        lcard.grid(row=0, column=0, sticky="nsew", padx=(0, 14))

        # tab bar
        tab_bar = tk.Frame(lcard.inner, bg=CARD)
        tab_bar.pack(fill="x")
        self._tab_btns = {}
        for _cat in ("門市", "廠商"):
            _btn = tk.Label(tab_bar, text=f"{_cat}通訊錄", font=F_SMALL,
                            bg=CARD, fg=ACCENT if _cat == "門市" else MUTED,
                            cursor="hand2", padx=16, pady=10)
            _btn.pack(side="left")
            _btn.bind("<Button-1>", lambda _, c=_cat: self._switch_tab(c))
            self._tab_btns[_cat] = _btn
        Hairline(lcard.inner).pack(fill="x")

        # search bar
        sbar = tk.Frame(lcard.inner, bg=CARD, height=44)
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
        Hairline(lcard.inner).pack(fill="x")

        # list
        list_holder = tk.Frame(lcard.inner, bg=CARD)
        list_holder.pack(fill="x")
        self.list_canvas = tk.Canvas(list_holder, bg=CARD, highlightthickness=0, height=420)
        self.list_canvas.pack(side="left", fill="x", expand=False)
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

        Hairline(apc.body).pack(fill="x", pady=(16, 0))
        mz_cell = tk.Frame(apc.body, bg=CARD); mz_cell.pack(fill="x", pady=(12, 0))
        self.maximized_var = tk.BooleanVar()
        tk.Checkbutton(
            mz_cell, text="預設全視窗開啟（下次啟動生效）",
            variable=self.maximized_var,
            font=F_NORM, bg=CARD, fg=INK,
            activebackground=CARD, activeforeground=INK,
            selectcolor=CARD, relief="flat",
            command=self._save_maximized,
        ).pack(anchor="w")

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
