#!/usr/bin/env python3
"""
黑貓（統一速達）EGS 桌面工具
執行：python3 app.py
"""

import base64
import csv
import io
import json
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

import yaml

from api_client import SudaClient, save_pdf, default_shipment_date, default_delivery_date
from order import generate_template, load_orders, create_orders, TEMPLATE_FIELDS

CONFIG_PATH = "config.yaml"
OUTPUT_DIR  = str(Path(__file__).parent.parent / "黑貓單號")

VERSION     = "1.1.6"
GITHUB_REPO = "pony9632-pixel/heicat-egs-tool"

SPEC_OPTIONS   = {"0001  60cm": "0001", "0002  90cm": "0002", "0003 120cm": "0003", "0004 150cm": "0004"}
THERMO_OPTIONS = {"0001 常溫": "0001", "0002 冷藏": "0002", "0003 冷凍": "0003"}
DTIME_OPTIONS  = {"01 不指定": "01", "02 上午 08-12": "02", "03 下午 12-17": "03", "04 晚上 17-20": "04"}
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

TEAL   = "#007B7F"
WHITE  = "#FFFFFF"
LIGHT  = "#F0F7F7"
BORDER = "#CCDDDD"
BTN_FG = "#FFFFFF"
RED    = "#CC3333"
GREEN  = "#2E7D32"


# ─── helpers ──────────────────────────────────────────────────────────────────

def load_cfg() -> dict:
    if Path(CONFIG_PATH).exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def save_cfg(cfg: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)


CONTACTS_PATH = "contacts.json"

def load_contacts() -> list[dict]:
    if Path(CONTACTS_PATH).exists():
        with open(CONTACTS_PATH, encoding="utf-8") as f:
            return json.load(f)
    return []

def save_contacts(contacts: list[dict]):
    with open(CONTACTS_PATH, "w", encoding="utf-8") as f:
        json.dump(contacts, f, ensure_ascii=False, indent=2)



def make_client(cfg: dict) -> SudaClient:
    return SudaClient(
        customer_id=str(cfg.get("username", "")),
        customer_token=cfg.get("api_token", ""),
    )


# ─── main window ──────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("黑貓宅急便 企業建單工具")
        self.resizable(True, True)
        self.configure(bg=WHITE)
        # 依螢幕高度決定視窗大小，盡量顯示完整內容
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        win_w, win_h = min(980, sw - 40), min(sh - 80, 920)
        self.geometry(f"{win_w}x{win_h}")
        self.minsize(860, 800)

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TNotebook",        background=WHITE, borderwidth=0)
        style.configure("TNotebook.Tab",    background=LIGHT, foreground="#333",
                        padding=[14, 6], font=("Arial", 11))
        style.map("TNotebook.Tab",
                  background=[("selected", TEAL)],
                  foreground=[("selected", WHITE)])
        style.configure("TFrame",           background=WHITE)
        style.configure("TLabel",           background=WHITE, font=("Arial", 11))
        style.configure("TEntry",           font=("Arial", 11))
        style.configure("TCombobox",        font=("Arial", 11))
        style.configure("Treeview",         font=("Arial", 10), rowheight=24)
        style.configure("Treeview.Heading", font=("Arial", 10, "bold"))
        style.configure("Green.TButton",    background=TEAL,  foreground=BTN_FG,
                        font=("Arial", 11, "bold"), padding=[10, 6])
        style.map("Green.TButton",
                  background=[("active", "#005F63")])
        style.configure("Red.TButton",      background=RED,   foreground=BTN_FG,
                        font=("Arial", 11, "bold"), padding=[10, 6])

        # header
        self._hdr = tk.Frame(self, bg=TEAL, height=50)
        self._hdr.pack(fill="x")
        tk.Label(self._hdr, text="  🐱  黑貓宅急便 企業建單工具",
                 bg=TEAL, fg=WHITE, font=("Arial", 14, "bold")).pack(side="left", pady=8)
        tk.Label(self._hdr, text=f"v{VERSION}",
                 bg=TEAL, fg="#B2DFDB", font=("Arial", 10)).pack(side="left", pady=8, padx=(6, 0))
        self._update_status = tk.Label(self._hdr, text="🔍 檢查更新中...",
                 bg=TEAL, fg="#B2DFDB", font=("Arial", 10))
        self._update_status.pack(side="right", pady=8, padx=12)

        # update banner (hidden until a new version is found)
        self._update_bar = tk.Frame(self, bg="#E65100")
        self._update_lbl = tk.Label(
            self._update_bar, text="", bg="#E65100", fg=WHITE,
            font=("Arial", 11, "bold"), cursor="hand2", pady=6)
        self._update_lbl.pack(side="left", padx=14)
        self._update_lbl.bind("<Button-1>", lambda e: self._do_update())
        self._new_version = ""
        self._zipball_url = ""
        self._html_url    = ""

        # macOS copy-paste fix
        # 用 ::tk::mac::* 覆寫系統層級指令，英文和注音輸入法模式下均有效
        import time as _time
        _last_t = [0.0]

        def _fw():
            return self.focus_get()

        def _do_paste():
            w = _fw()
            if not w: return
            try:
                clip = w.clipboard_get()
                try: w.delete("sel.first", "sel.last")
                except Exception: pass
                w.insert("insert", clip)
            except Exception: pass

        def _do_copy():
            w = _fw()
            if not w: return
            try:
                text = w.selection_get()
                w.clipboard_clear()
                w.clipboard_append(text)
            except Exception: pass

        def _do_cut():
            w = _fw()
            if not w: return
            try:
                text = w.selection_get()
                w.clipboard_clear()
                w.clipboard_append(text)
                w.delete("sel.first", "sel.last")
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

        # 系統層（注音模式也能觸發）
        self.tk.createcommand("::tk::mac::Paste",     _do_paste)
        self.tk.createcommand("::tk::mac::Copy",      _do_copy)
        self.tk.createcommand("::tk::mac::Cut",       _do_cut)
        self.tk.createcommand("::tk::mac::SelectAll", _do_select_all)

        # 一般按鍵層（英文模式備援）— 用時間戳防止與系統層重複觸發
        def _guarded(fn):
            def handler(e):
                now = _time.time()
                if now - _last_t[0] < 0.05:
                    return "break"
                _last_t[0] = now
                fn()
                return "break"
            return handler

        for _cls in ("Entry", "TEntry", "Text"):
            self.bind_class(_cls, "<Command-c>", _guarded(_do_copy))
            self.bind_class(_cls, "<Command-v>", _guarded(_do_paste))
            self.bind_class(_cls, "<Command-x>", _guarded(_do_cut))
            self.bind_class(_cls, "<Command-a>", _guarded(_do_select_all))

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=10)

        self.tab_single   = SingleOrderTab(nb, self)
        self.tab_batch    = BatchOrderTab(nb, self)
        self.tab_contacts = ContactsTab(nb, self)
        self.tab_cfg      = ConfigTab(nb, self)

        nb.add(self.tab_single,   text="  單筆建單  ")
        nb.add(self.tab_batch,    text="  批次建單  ")
        nb.add(self.tab_contacts, text="  通訊錄  ")
        nb.add(self.tab_cfg,      text="  設定  ")

        threading.Thread(target=self._check_update, daemon=True).start()

    # ── auto-update ──────────────────────────────────────────────────────────

    def _check_update(self):
        try:
            import urllib.request as _req, ssl
            _ctx = ssl.create_default_context()
            _ctx.check_hostname = False
            _ctx.verify_mode = ssl.CERT_NONE
            url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
            request = _req.Request(url, headers={"User-Agent": "heicat-egs-tool"})
            with _req.urlopen(request, context=_ctx, timeout=5) as r:
                data = json.loads(r.read())
            tag = data.get("tag_name", "").lstrip("v")
            if not tag:
                return
            current = tuple(int(x) for x in VERSION.split("."))
            latest  = tuple(int(x) for x in tag.split("."))
            if latest > current:
                zipball = data.get("zipball_url", "")
                html    = data.get("html_url", "")
                self.after(0, lambda t=tag, z=zipball, h=html:
                           self._show_update_banner(t, z, h))
            else:
                self.after(0, lambda: self._update_status.config(
                    text="✓ 已是最新版"))
                self.after(4000, lambda: self._update_status.config(text=""))
        except Exception:
            self.after(0, lambda: self._update_status.config(text=""))

    def _show_update_banner(self, new_version: str, zipball_url: str, html_url: str):
        self._new_version = new_version
        self._zipball_url = zipball_url
        self._html_url    = html_url
        # 啟動時直接彈出詢問視窗
        if messagebox.askyesno(
                "🔔 發現新版本",
                f"發現新版本 v{new_version}！\n\n"
                "• config.yaml 與 contacts.json 會保留\n"
                "• 更新完成後程式自動重新啟動\n\n"
                "要立即更新嗎？",
                default="yes"):
            self._run_update()
        else:
            # 選擇稍後，保留頂部 banner 提醒
            self._update_lbl.config(
                text=f"🔔  發現新版本 v{new_version}！點此一鍵更新  →")
            self._update_bar.pack(fill="x", after=self._hdr)

    def _do_update(self):
        if not self._zipball_url:
            return
        if not messagebox.askyesno(
                "確認更新",
                f"確定要更新到 v{self._new_version}？\n\n"
                "• config.yaml 與 contacts.json 會保留\n"
                "• 更新完成後程式自動重新啟動"):
            return
        self._run_update()

    def _run_update(self):
        self._update_lbl.config(text="⏳  下載更新中，請稍候...")
        self._update_lbl.unbind("<Button-1>")
        self._update_bar.pack(fill="x", after=self._hdr)

        def run():
            try:
                import ssl, shutil, tempfile, os
                import urllib.request as _req

                ssl_ctx = ssl.create_default_context()
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = ssl.CERT_NONE
                req = _req.Request(self._zipball_url,
                                   headers={"User-Agent": "heicat-egs-tool"})
                with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
                    temp_zip = f.name
                with _req.urlopen(req, context=ssl_ctx, timeout=60) as resp:
                    with open(temp_zip, "wb") as f:
                        shutil.copyfileobj(resp, f)

                self.after(0, lambda: self._update_lbl.config(text="⏳  解壓縮並套用更新..."))

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

                os.unlink(temp_zip)
                self.after(0, self._restart_app)

            except Exception as ex:
                err = str(ex)
                self.after(0, lambda m=err: self._update_lbl.config(
                    text=f"✗ 更新失敗：{m}  （點此手動下載）"))
                self.after(0, lambda: self._update_lbl.bind(
                    "<Button-1>",
                    lambda e: __import__("webbrowser").open(self._html_url)))

        threading.Thread(target=run, daemon=True).start()

    def _restart_app(self):
        import os, sys
        messagebox.showinfo("更新完成",
                            f"已更新至 v{self._new_version}，程式即將重新啟動。")
        os.execv(sys.executable, [sys.executable, str(Path(__file__))])


# ─── config tab ───────────────────────────────────────────────────────────────

class ConfigTab(ttk.Frame):
    FIELDS = [
        ("客戶代號",                    "username"),
        ("API 授權碼",                  "api_token"),
        ("寄件人姓名",                  "sender.name"),
        ("寄件人電話（市話）",           "sender.tel"),
        ("寄件人手機（可空）",           "sender.mobile"),
        ("寄件人郵遞區號（6 碼）",       "sender.zipcode"),
        ("寄件人地址",                  "sender.address"),
    ]
    PRODUCT_TYPE_FIELD = "sender.product_type_id"

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.vars = {}
        self._build()
        self._load()

    def _build(self):
        frm = ttk.Frame(self, padding=20)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)

        tk.Label(frm, text="API 連線設定", font=("Arial", 13, "bold"),
                 background=WHITE, foreground=TEAL).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 14))

        for i, (label, key) in enumerate(self.FIELDS, start=1):
            tk.Label(frm, text=label, background=WHITE,
                     font=("Arial", 11)).grid(row=i, column=0, sticky="ne", padx=(0, 10), pady=5)
            v = tk.StringVar()
            self.vars[key] = v
            e = ttk.Entry(frm, textvariable=v, width=46,
                          show="*" if key == "api_token" else "")
            e.grid(row=i, column=1, sticky="ew", pady=5)

        # ProductTypeId dropdown
        pt_row = len(self.FIELDS) + 1
        tk.Label(frm, text="品名類別\n（ProductTypeId）", background=WHITE,
                 font=("Arial", 11)).grid(row=pt_row, column=0, sticky="ne", padx=(0, 10), pady=5)
        self.pt_var = tk.StringVar()
        self.vars[self.PRODUCT_TYPE_FIELD] = self.pt_var
        pt_cb = ttk.Combobox(frm, textvariable=self.pt_var,
                             values=list(PRODUCT_TYPE_OPTIONS.keys()),
                             state="readonly", width=44)
        pt_cb.grid(row=pt_row, column=1, sticky="ew", pady=5)

        row = pt_row + 1
        btn_frame = tk.Frame(frm, background=WHITE)
        btn_frame.grid(row=row, column=0, columnspan=2, pady=18, sticky="w")
        ttk.Button(btn_frame, text="儲存設定", style="Green.TButton",
                   command=self._save).pack(side="left", padx=(0, 10))
        ttk.Button(btn_frame, text="測試連線", command=self._test).pack(side="left")

        # ProductTypeId hint
        hint = tk.Label(frm,
            text="💡 品名類別會印在託運單上，請選擇最符合你出貨商品的分類。",
            background="#F0F7F7", foreground=TEAL, font=("Arial", 10),
            justify="left", relief="flat", padx=8, pady=6)
        hint.grid(row=row + 1, column=0, columnspan=2, sticky="ew", pady=(0, 6))

        self.status = tk.Label(frm, text="", background=WHITE, font=("Arial", 11))
        self.status.grid(row=row + 2, column=0, columnspan=2, sticky="w")

    def _load(self):
        cfg = load_cfg()
        sender = cfg.get("sender") or {}
        _code_to_label = {v: k for k, v in PRODUCT_TYPE_OPTIONS.items()}
        for key, var in self.vars.items():
            if "." in key:
                _, field = key.split(".", 1)
                val = sender.get(field, "")
            else:
                val = cfg.get(key, "")
            if key == self.PRODUCT_TYPE_FIELD:
                val = _code_to_label.get(str(val), val)  # code → label
            var.set(val)

    def _save(self):
        cfg = load_cfg()
        sender = cfg.get("sender") or {}
        for key, var in self.vars.items():
            val = var.get()
            if key == self.PRODUCT_TYPE_FIELD:
                val = PRODUCT_TYPE_OPTIONS.get(val, val)  # label → code
            if "." in key:
                _, field = key.split(".", 1)
                sender[field] = val
            else:
                cfg[key] = val
        cfg["sender"] = sender
        save_cfg(cfg)
        self.status.config(text="✓ 已儲存", foreground=GREEN)
        self.after(2000, lambda: self.status.config(text=""))

    def _test(self):
        self._save()
        cfg = load_cfg()
        client = make_client(cfg)
        self.status.config(text="測試中...", foreground="#888")
        def run():
            try:
                resp = client.print_obt([])
                if "SrvTranId" in resp:
                    self.after(0, lambda: self.status.config(
                        text="✓ 連線成功！API 授權碼有效", foreground=GREEN))
                else:
                    self.after(0, lambda: self.status.config(
                        text=f"✗ 意外回應：{resp}", foreground=RED))
            except Exception as ex:
                self.after(0, lambda: self.status.config(
                    text=f"✗ 錯誤：{ex}", foreground=RED))
        threading.Thread(target=run, daemon=True).start()

    def get_cfg(self):
        return load_cfg()


# ─── single order tab ─────────────────────────────────────────────────────────

class SingleOrderTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._build()

    def _build(self):
        canvas = tk.Canvas(self, bg=WHITE, highlightthickness=0)
        vsb = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self.inner = ttk.Frame(canvas, padding=20)
        win = canvas.create_window((0, 0), window=self.inner, anchor="nw")

        def on_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(win, width=canvas.winfo_width())
        self.inner.bind("<Configure>", on_configure)
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))

        frm = self.inner
        frm.columnconfigure(1, weight=1)
        frm.columnconfigure(3, weight=1)

        tk.Label(frm, text="建立單筆寄件單", font=("Arial", 13, "bold"),
                 background=WHITE, foreground=TEAL).grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 14))

        self.fields = {}

        def row(r, label, key, col=0, width=28, **kw):
            tk.Label(frm, text=label, background=WHITE).grid(
                row=r, column=col*2, sticky="ne", padx=(0, 8), pady=5)
            v = tk.StringVar(value=kw.get("default", ""))
            self.fields[key] = v
            if "options" in kw:
                cb = ttk.Combobox(frm, textvariable=v, values=kw["options"],
                                  state="readonly", width=width)
                cb.grid(row=r, column=col*2+1, sticky="ew", pady=5,
                        padx=(0, 20 if col == 0 else 0))
            else:
                e = ttk.Entry(frm, textvariable=v, width=width)
                e.grid(row=r, column=col*2+1, sticky="ew", pady=5,
                       padx=(0, 20 if col == 0 else 0))

        row(1, "訂單號碼 *",      "order_id",          col=0)
        row(1, "貨品名稱",         "product_name",      col=1, default="一般物品")
        row(2, "收件人姓名 *",     "recipient_name",    col=0)
        row(2, "收件人電話 *",     "recipient_phone",   col=1)
        row(3, "收件人手機",       "recipient_mobile",  col=0)
        row(3, "收件人地址 *",     "recipient_address", col=1, width=36)
        row(4, "尺寸",             "spec",              col=0,
            options=list(SPEC_OPTIONS.keys()), default="0001  60cm")
        row(4, "溫層",             "thermosphere",      col=1,
            options=list(THERMO_OPTIONS.keys()), default="0001 常溫")
        row(5, "出貨日 YYYYMMDD",  "shipment_date",     col=0, default=default_shipment_date())
        row(5, "配送日 YYYYMMDD",  "delivery_date",     col=1, default=default_delivery_date())
        row(6, "配送時段",         "delivery_time",     col=0,
            options=list(DTIME_OPTIONS.keys()), default="01 不指定")
        row(6, "備註",             "notes",             col=1)

        # 付款設定區塊
        sep = ttk.Separator(frm, orient="horizontal")
        sep.grid(row=7, column=0, columnspan=4, sticky="ew", pady=8)

        tk.Label(frm, text="付款設定", font=("Arial", 11, "bold"),
                 background=WHITE, foreground=TEAL).grid(
            row=8, column=0, columnspan=4, sticky="w", pady=(0, 4))

        row(9, "運費付款方式", "is_freight", col=0,
            options=["N 寄件人付", "Y 收件人付（運費到付）"], default="N 寄件人付", width=24)
        row(9, "代收貨款（貨到付款）", "is_collection", col=1,
            options=["N 不代收", "Y 代收（貨到付款）"], default="N 不代收", width=22)
        row(10, "代收金額（元）", "collection_amount", col=0, default="0")

        # contact shortcut buttons (above the submit row)
        contact_row = tk.Frame(frm, background=WHITE)
        contact_row.grid(row=11, column=0, columnspan=4, pady=(4, 0), sticky="w")
        ttk.Button(contact_row, text="📋 從通訊錄選擇",
                   command=self._pick_contact).pack(side="left", padx=(0, 8))
        ttk.Button(contact_row, text="💾 存入通訊錄",
                   command=self._save_to_contacts).pack(side="left")

        btn_row = tk.Frame(frm, background=WHITE)
        btn_row.grid(row=12, column=0, columnspan=4, pady=(8, 10), sticky="w")
        ttk.Button(btn_row, text="建立寄件單", style="Green.TButton",
                   command=self._submit).pack(side="left", padx=(0, 10))
        ttk.Button(btn_row, text="清除",
                   command=self._clear).pack(side="left")

        self.result_var = tk.StringVar()
        self.result_lbl = tk.Label(frm, textvariable=self.result_var,
                                   background=WHITE, font=("Arial", 11),
                                   wraplength=700, justify="left")
        self.result_lbl.grid(row=13, column=0, columnspan=4, sticky="w")

    def _get_values(self) -> dict:
        out = {}
        for k, v in self.fields.items():
            val = v.get()
            if k == "thermosphere":
                val = THERMO_OPTIONS.get(val, val)
            elif k == "delivery_time":
                val = DTIME_OPTIONS.get(val, val)
            elif k == "spec":
                val = SPEC_OPTIONS.get(val, val)
            elif k in ("is_collection", "is_freight"):
                val = "Y" if val.startswith("Y") else "N"
            out[k] = val
        return out

    def _clear(self):
        defaults = {
            "order_id": "", "product_name": "一般物品",
            "recipient_name": "", "recipient_phone": "", "recipient_mobile": "",
            "recipient_address": "", "spec": "0001  60cm",
            "thermosphere": "0001 常溫", "delivery_time": "01 不指定",
            "shipment_date": default_shipment_date(),
            "delivery_date": default_delivery_date(),
            "is_freight": "N 寄件人付", "is_collection": "N 不代收",
            "collection_amount": "0", "notes": "",
        }
        for k, v in defaults.items():
            if k in self.fields:
                self.fields[k].set(v)
        self.result_var.set("")

    def _pick_contact(self):
        def on_select(contact: dict):
            self.fields["recipient_name"].set(contact.get("name", ""))
            self.fields["recipient_phone"].set(contact.get("phone", ""))
            self.fields["recipient_mobile"].set(contact.get("mobile", ""))
            self.fields["recipient_address"].set(contact.get("address", ""))
        ContactPickerDialog(self, on_select)

    def _save_to_contacts(self):
        name    = self.fields["recipient_name"].get().strip()
        phone   = self.fields["recipient_phone"].get().strip()
        mobile  = self.fields["recipient_mobile"].get().strip()
        address = self.fields["recipient_address"].get().strip()
        if not name:
            messagebox.showwarning("缺少姓名", "請先填寫收件人姓名。")
            return
        contact = {"name": name, "phone": phone, "mobile": mobile,
                   "address": address, "notes": ""}
        contacts = load_contacts()
        existing = next((i for i, c in enumerate(contacts) if c.get("name") == name), None)
        if existing is not None:
            if not messagebox.askyesno("已存在", f"「{name}」已在通訊錄中，要覆蓋嗎？"):
                return
            contacts[existing] = contact
        else:
            contacts.append(contact)
            contacts.sort(key=lambda c: c.get("name", ""))
        save_contacts(contacts)
        if hasattr(self.app, "tab_contacts"):
            self.app.tab_contacts._refresh()
        messagebox.showinfo("已儲存", f"「{name}」已存入通訊錄。")

    def _submit(self):
        values = self._get_values()
        required = {"order_id": "訂單號碼", "recipient_name": "收件人姓名",
                    "recipient_address": "收件人地址", "recipient_phone": "收件人電話"}
        for k, label in required.items():
            if not values.get(k):
                messagebox.showwarning("缺少必填欄位", f"請填寫「{label}」")
                return

        cfg = load_cfg()
        sender = cfg.get("sender") or {}
        if not sender.get("name"):
            messagebox.showwarning("寄件人資料未設定", "請先到「設定」頁填寫寄件人資料。")
            return

        self.result_var.set("建單中，請稍候...")
        self.result_lbl.config(foreground="#888")

        def run():
            try:
                client = make_client(cfg)
                Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
                results = create_orders(client, [values], sender, output_dir=OUTPUT_DIR)
                r = results[0]
                if r["success"]:
                    msg = f"✓ 建單成功！OBT：{r['obt_number']}"
                    if r["pdf_path"]:
                        msg += f"\nPDF 已儲存：{Path(r['pdf_path']).resolve()}"
                        import subprocess
                        subprocess.run(["open", r["pdf_path"]])
                    self.after(0, lambda: self.result_lbl.config(foreground=GREEN))
                else:
                    raw = r['message']
                    if "E009" in raw:
                        raw += "\n→ 請至「設定」頁重新選擇「品名類別」"
                    msg = f"✗ 建單失敗：{raw}"
                    self.after(0, lambda: self.result_lbl.config(foreground=RED))
                self.after(0, lambda: self.result_var.set(msg))
            except Exception as ex:
                err = f"✗ 錯誤：{ex}"
                self.after(0, lambda m=err: self.result_var.set(m))
                self.after(0, lambda: self.result_lbl.config(foreground=RED))

        threading.Thread(target=run, daemon=True).start()


# ─── batch order tab ──────────────────────────────────────────────────────────

class BatchOrderTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.orders = []
        self._build()

    def _build(self):
        frm = ttk.Frame(self, padding=20)
        frm.pack(fill="both", expand=True)

        tk.Label(frm, text="批次建立寄件單", font=("Arial", 13, "bold"),
                 background=WHITE, foreground=TEAL).pack(anchor="w", pady=(0, 12))

        btn_row = tk.Frame(frm, background=WHITE)
        btn_row.pack(anchor="w", pady=(0, 10))
        ttk.Button(btn_row, text="產生 CSV 範本",
                   command=self._gen_template).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="載入 CSV",
                   command=self._load_csv).pack(side="left", padx=(0, 8))
        self.file_lbl = tk.Label(btn_row, text="未選擇檔案",
                                 background=WHITE, foreground="#888", font=("Arial", 10))
        self.file_lbl.pack(side="left")

        # treeview
        cols = ["order_id", "recipient_name", "recipient_phone", "recipient_address", "spec"]
        col_labels = {"order_id": "訂單號", "recipient_name": "收件人",
                      "recipient_phone": "電話", "recipient_address": "地址", "spec": "尺寸"}
        self.tree = ttk.Treeview(frm, columns=cols, show="headings", height=12)
        for c in cols:
            self.tree.heading(c, text=col_labels[c])
            self.tree.column(c, width=140 if c == "recipient_address" else 100)
        vsb = ttk.Scrollbar(frm, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="left", fill="y")

        right = tk.Frame(frm, background=WHITE, padx=12)
        right.pack(side="left", fill="y")

        ttk.Button(right, text="全部建單", style="Green.TButton",
                   command=self._submit_all).pack(fill="x", pady=(0, 8))
        ttk.Button(right, text="清除列表",
                   command=self._clear).pack(fill="x")

        self.log = scrolledtext.ScrolledText(right, width=32, height=20,
                                              font=("Courier", 10), state="disabled",
                                              bg=LIGHT, relief="flat")
        self.log.pack(fill="both", expand=True, pady=(12, 0))

    def _log(self, msg: str, color: str = "black"):
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
        if not path:
            return
        try:
            self.orders = load_orders(path)
        except Exception as ex:
            messagebox.showerror("讀取失敗", str(ex))
            return

        self.file_lbl.config(text=Path(path).name, foreground=TEAL)
        for item in self.tree.get_children():
            self.tree.delete(item)
        for o in self.orders:
            self.tree.insert("", "end", values=[
                o.get("order_id", ""), o.get("recipient_name", ""),
                o.get("recipient_phone", ""), o.get("recipient_address", ""),
                o.get("spec", "0060"),
            ])
        self._log(f"載入 {len(self.orders)} 筆訂單")

    def _clear(self):
        self.orders = []
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.file_lbl.config(text="未選擇檔案", foreground="#888")

    def _submit_all(self):
        if not self.orders:
            messagebox.showwarning("沒有訂單", "請先載入 CSV 檔案。")
            return
        cfg = load_cfg()
        sender = cfg.get("sender") or {}
        if not sender.get("name"):
            messagebox.showwarning("寄件人資料未設定", "請先到「設定」頁填寫寄件人資料。")
            return

        Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
        output_dir = filedialog.askdirectory(title="選擇 PDF 儲存目錄",
                                             initialdir=OUTPUT_DIR)
        if not output_dir:
            return

        self._log(f"開始建單，共 {len(self.orders)} 筆...")

        def run():
            client = make_client(cfg)
            for i, order in enumerate(self.orders, 1):
                from order import _csv_row_to_api_order
                api_order = _csv_row_to_api_order(order, sender)
                resp = client.print_obt([api_order])
                oid = order.get("order_id", f"#{i}")
                if resp.get("IsOK") == "Y":
                    data = resp.get("Data") or {}
                    if isinstance(data, list) and data:
                        data = data[0]
                    obt = data.get("OBTNumber", "")
                    pdf = data.get("PDF", "")
                    if pdf:
                        pdf_path = str(Path(output_dir) / f"{oid}_{obt}.pdf")
                        save_pdf(pdf, pdf_path)
                        self.after(0, lambda o=oid, n=obt: self._log(f"✓ {o}  OBT:{n}", GREEN))
                    else:
                        self.after(0, lambda o=oid: self._log(f"✓ {o}  (無PDF)", GREEN))
                else:
                    msg = resp.get("Message", "")[:60]
                    self.after(0, lambda o=oid, m=msg: self._log(f"✗ {o}: {m}", RED))

            import subprocess
            self.after(0, lambda: self._log("── 完成 ──"))
            self.after(0, lambda d=output_dir: subprocess.run(["open", d]))

        threading.Thread(target=run, daemon=True).start()


# ─── contacts tab ─────────────────────────────────────────────────────────────

CONTACT_COLS = ["name", "phone", "mobile", "address", "notes"]
CONTACT_LABELS = {"name": "姓名", "phone": "電話", "mobile": "手機", "address": "地址", "notes": "備註"}

class ContactsTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._build()
        self._refresh()

    def _build(self):
        frm = ttk.Frame(self, padding=20)
        frm.pack(fill="both", expand=True)

        tk.Label(frm, text="通訊錄", font=("Arial", 13, "bold"),
                 background=WHITE, foreground=TEAL).pack(anchor="w", pady=(0, 10))

        # search bar
        search_row = tk.Frame(frm, background=WHITE)
        search_row.pack(fill="x", pady=(0, 8))
        tk.Label(search_row, text="搜尋：", background=WHITE).pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._refresh())
        ttk.Entry(search_row, textvariable=self.search_var, width=30).pack(side="left", padx=(4, 0))

        # treeview
        tree_frame = tk.Frame(frm, background=WHITE)
        tree_frame.pack(fill="both", expand=True)

        cols = ["name", "phone", "mobile", "address", "notes"]
        col_w  = {"name": 100, "phone": 110, "mobile": 110, "address": 240, "notes": 120}
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=14,
                                 selectmode="browse")
        for c in cols:
            self.tree.heading(c, text=CONTACT_LABELS[c])
            self.tree.column(c, width=col_w[c])
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="left", fill="y")
        self.tree.bind("<Double-1>", lambda e: self._edit_selected())

        # buttons
        btn_row = tk.Frame(frm, background=WHITE)
        btn_row.pack(fill="x", pady=(10, 0))
        ttk.Button(btn_row, text="＋ 新增聯絡人", style="Green.TButton",
                   command=self._add).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="✎ 編輯",
                   command=self._edit_selected).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="✕ 刪除", style="Red.TButton",
                   command=self._delete_selected).pack(side="left")

    def _refresh(self):
        keyword = self.search_var.get().lower()
        for item in self.tree.get_children():
            self.tree.delete(item)
        for c in load_contacts():
            if keyword and not any(keyword in str(v).lower() for v in c.values()):
                continue
            self.tree.insert("", "end", values=[c.get(k, "") for k in CONTACT_COLS])

    def _add(self):
        ContactDialog(self, None, self._on_save)

    def _edit_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("請選擇", "請先點選要編輯的聯絡人。")
            return
        vals = self.tree.item(sel[0])["values"]
        contact = dict(zip(CONTACT_COLS, vals))
        ContactDialog(self, contact, self._on_save)

    def _delete_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        vals = self.tree.item(sel[0])["values"]
        name = vals[0]
        if not messagebox.askyesno("確認刪除", f"確定刪除「{name}」？"):
            return
        contacts = [c for c in load_contacts() if c.get("name") != name or
                    c.get("phone") != str(vals[1])]
        save_contacts(contacts)
        self._refresh()

    def _on_save(self, contact: dict, original_name: str = None):
        contacts = load_contacts()
        if original_name:
            contacts = [c for c in contacts if not (
                c.get("name") == original_name)]
        contacts.append(contact)
        contacts.sort(key=lambda c: c.get("name", ""))
        save_contacts(contacts)
        self._refresh()


class ContactDialog(tk.Toplevel):
    def __init__(self, parent, contact: dict | None, on_save):
        super().__init__(parent)
        self.title("新增聯絡人" if contact is None else "編輯聯絡人")
        self.resizable(False, False)
        self.configure(bg=WHITE)
        self.grab_set()
        self.on_save = on_save
        self.original_name = contact["name"] if contact else None
        self.vars = {}
        self._build(contact or {})

    def _build(self, contact):
        frm = tk.Frame(self, bg=WHITE, padx=24, pady=20)
        frm.pack()
        frm.columnconfigure(1, weight=1)

        for i, (key, label) in enumerate(CONTACT_LABELS.items()):
            tk.Label(frm, text=label, background=WHITE, width=6,
                     anchor="e").grid(row=i, column=0, padx=(0, 10), pady=6, sticky="e")
            v = tk.StringVar(value=contact.get(key, ""))
            self.vars[key] = v
            w = 36 if key == "address" else 26
            ttk.Entry(frm, textvariable=v, width=w).grid(row=i, column=1, sticky="ew", pady=6)

        btn_row = tk.Frame(frm, bg=WHITE)
        btn_row.grid(row=len(CONTACT_LABELS), column=0, columnspan=2, pady=(16, 0))
        ttk.Button(btn_row, text="儲存", style="Green.TButton",
                   command=self._save).pack(side="left", padx=(0, 10))
        ttk.Button(btn_row, text="取消", command=self.destroy).pack(side="left")

    def _save(self):
        contact = {k: v.get().strip() for k, v in self.vars.items()}
        if not contact.get("name"):
            messagebox.showwarning("必填", "姓名為必填欄位。", parent=self)
            return
        self.on_save(contact, self.original_name)
        self.destroy()


class ContactPickerDialog(tk.Toplevel):
    """從通訊錄選擇一筆，回傳 contact dict。"""
    def __init__(self, parent, on_select):
        super().__init__(parent)
        self.title("選擇收件人")
        self.geometry("640x420")
        self.configure(bg=WHITE)
        self.grab_set()
        self.on_select = on_select
        self._build()

    def _build(self):
        frm = tk.Frame(self, bg=WHITE, padx=16, pady=16)
        frm.pack(fill="both", expand=True)

        search_row = tk.Frame(frm, bg=WHITE)
        search_row.pack(fill="x", pady=(0, 8))
        tk.Label(search_row, text="搜尋：", background=WHITE).pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._refresh())
        ttk.Entry(search_row, textvariable=self.search_var, width=30).pack(side="left", padx=4)

        cols = ["name", "phone", "mobile", "address"]
        col_w = {"name": 100, "phone": 110, "mobile": 110, "address": 240}
        self.tree = ttk.Treeview(frm, columns=cols, show="headings", height=12,
                                 selectmode="browse")
        for c in cols:
            self.tree.heading(c, text=CONTACT_LABELS[c])
            self.tree.column(c, width=col_w[c])
        vsb = ttk.Scrollbar(frm, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="left", fill="y")
        self.tree.bind("<Double-1>", lambda e: self._pick())

        btn_row = tk.Frame(self, bg=WHITE, pady=10)
        btn_row.pack()
        ttk.Button(btn_row, text="選擇", style="Green.TButton",
                   command=self._pick).pack(side="left", padx=(0, 10))
        ttk.Button(btn_row, text="取消", command=self.destroy).pack(side="left")
        self._refresh()

    def _refresh(self):
        keyword = self.search_var.get().lower()
        for item in self.tree.get_children():
            self.tree.delete(item)
        for c in load_contacts():
            if keyword and not any(keyword in str(v).lower() for v in c.values()):
                continue
            self.tree.insert("", "end", values=[c.get(k, "") for k in ["name","phone","mobile","address"]])

    def _pick(self):
        sel = self.tree.selection()
        if not sel:
            return
        vals = self.tree.item(sel[0])["values"]
        contact = dict(zip(["name","phone","mobile","address"], vals))
        self.on_select(contact)
        self.destroy()


# ─── entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = App()
    app.mainloop()
