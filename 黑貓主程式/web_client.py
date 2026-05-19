"""
TakkyubinWebClient — 模擬瀏覽器登入統一速達契客專區
並查詢 SudaPaymentDetail（交易明細）。純 Python 標準庫。
"""
import ssl, re, urllib.request, urllib.parse, urllib.error, http.cookiejar
from html.parser import HTMLParser

BASE    = "https://www.takkyubin.com.tw/YMTContract/aspx"
_SSLCTX = ssl.create_default_context()
_SSLCTX.check_hostname = False
_SSLCTX.verify_mode    = ssl.CERT_NONE
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")

class TakkyubinWebClient:
    def __init__(self):
        self._jar    = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._jar),
            urllib.request.HTTPSHandler(context=_SSLCTX),
        )

    def _req(self, url: str, post_data: bytes | None = None) -> str:
        headers = {"User-Agent": _UA,
                   "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                   "Accept-Language": "zh-TW,zh;q=0.9"}
        if post_data:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = urllib.request.Request(url, data=post_data, headers=headers)
        with self._opener.open(req, timeout=20) as r:
            ct = r.headers.get("Content-Type","")
            enc = "utf-8"
            if "charset=" in ct: enc = ct.split("charset=")[-1].strip()
            return r.read().decode(enc, errors="replace")

    def _get_bytes(self, url: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with self._opener.open(req, timeout=10) as r:
            return r.read()

    @staticmethod
    def _tokens(html: str) -> dict:
        t = {}
        for m in re.finditer(r'<input[^>]+name="(__[A-Z_]+)"[^>]+value="([^"]*)"', html, re.I):
            t[m.group(1)] = m.group(2)
        # Also try value before name order
        for m in re.finditer(r'<input[^>]+value="([^"]*)"[^>]+name="(__[A-Z_]+)"', html, re.I):
            t[m.group(2)] = m.group(1)
        return t

    def get_login_page(self) -> tuple[dict, bytes]:
        """Returns (tokens, captcha_image_bytes). captcha_bytes may be empty."""
        import time
        html = self._req(f"{BASE}/Login.aspx")
        tokens = self._tokens(html)
        captcha_bytes = b""
        # JS sets: captcha.src = 'OCR_Validate.aspx?r=' + (new Date()).getTime()
        # Try that known URL first, then fall back to scanning img src attributes
        ts = int(time.time() * 1000)
        candidates = [f"{BASE}/OCR_Validate.aspx?r={ts}"]
        # Also scan for any img src matching captcha-like patterns
        for pat in [r'src=["\']([^"\']*[Cc]aptcha[^"\']*)["\']',
                    r'src=["\']([^"\']*[Vv]alidat[^"\']*\.(?:jpg|gif|png|aspx)[^"\']*)["\']',
                    r'src=["\']([^"\']*OCR[^"\']*)["\']']:
            m = re.search(pat, html, re.I)
            if m:
                src = m.group(1)
                url = src if src.startswith("http") else f"{BASE}/{src.lstrip('/')}"
                if url not in candidates:
                    candidates.append(url)
        for img_url in candidates:
            try:
                captcha_bytes = self._get_bytes(img_url)
                if captcha_bytes:
                    break
            except Exception:
                pass
        return tokens, captcha_bytes

    def login(self, username: str, password: str, captcha: str, tokens: dict) -> bool:
        """POST login. Returns True on success."""
        data = urllib.parse.urlencode({
            **{k: v for k, v in tokens.items()},
            "__EVENTTARGET": "", "__EVENTARGUMENT": "",
            "txtUserID": username, "txtUserPW": password,
            "txtValidate": captcha, "btnSubmit": " 登入 ",
        }, encoding="utf-8").encode("utf-8")
        html = self._req(f"{BASE}/Login.aspx", data)
        bad = ("驗證碼" in html and "不正確" in html) \
           or ("密碼" in html and "錯誤" in html) \
           or "登入失敗" in html or "txtUserID" in html
        ok = "SudaPaymentDetail" in html or "RedirectFunc" in html \
          or "logout" in html.lower() or "歡迎" in html
        return ok and not bad

    def is_logged_in(self) -> bool:
        try:
            html = self._req(f"{BASE}/SudaPaymentDetail.aspx?TimeOut=N")
            return "txtDateS" in html or "btnSearch" in html
        except Exception:
            return False

    def _payment_page_html(self) -> str:
        """GET 交易明細 page, following RedirectFunc if needed."""
        # Try direct URL first
        html = self._req(f"{BASE}/SudaPaymentDetail.aspx?TimeOut=N")
        if "Login.aspx" in html or "txtUserID" in html:
            raise RuntimeError("session_expired")
        # If the page didn't load the form (no btnSearch), try via RedirectFunc
        if "btnSearch" not in html:
            try:
                html = self._req(f"{BASE}/RedirectFunc.aspx?FuncNo=167")
                if "Login.aspx" in html or "txtUserID" in html:
                    raise RuntimeError("session_expired")
            except RuntimeError:
                raise
            except Exception:
                pass
        return html

    def get_account_options(self) -> list[tuple[str,str]]:
        """Return [(value, label), ...] from UC_UserList1$ddlUserList after login."""
        try:
            html = self._payment_page_html()
        except Exception:
            return []
        m = re.search(r'<select[^>]*name="UC_UserList1\$ddlUserList"[^>]*>(.*?)</select>',
                      html, re.S | re.I)
        if not m:
            return []
        opts = re.findall(r'<option[^>]*value="([^"]*)"[^>]*>([^<]*)', m.group(1), re.I)
        return [(v.strip(), lbl.strip()) for v, lbl in opts]

    def query_payment(self, start_date: str, end_date: str, account: str) -> list[dict]:
        """Query and parse payment detail table."""
        html = self._payment_page_html()
        tokens = self._tokens(html)

        # Auto-resolve account: if specified value isn't in dropdown, use first option
        m = re.search(r'<select[^>]*name="UC_UserList1\$ddlUserList"[^>]*>(.*?)</select>',
                      html, re.S | re.I)
        dropdown_vals = []
        if m:
            dropdown_vals = [v for v, _ in
                re.findall(r'<option[^>]*value="([^"]*)"[^>]*>', m.group(1), re.I)]
        if dropdown_vals and account not in dropdown_vals:
            account = dropdown_vals[0]

        # Extract actual btnSearch value from page (may have trailing spaces)
        btn_val_m = re.search(r'<input[^>]*name="btnSearch"[^>]*value="([^"]*)"', html, re.I)
        if not btn_val_m:
            btn_val_m = re.search(r'<input[^>]*value="([^"]*)"[^>]*name="btnSearch"', html, re.I)
        btn_val = btn_val_m.group(1) if btn_val_m else "搜尋"

        post = urllib.parse.urlencode({
            **tokens,
            "__EVENTTARGET": "", "__EVENTARGUMENT": "", "__LASTFOCUS": "",
            "txtDateS": start_date, "txtDateE": end_date,
            "UC_UserList1$ddlUserList": account, "btnSearch": btn_val,
        }, encoding="utf-8").encode("utf-8")

        # POST to the same page URL that served the form
        post_url = f"{BASE}/SudaPaymentDetail.aspx?TimeOut=N"
        result_html = self._req(post_url, post)

        # Save debug files for inspection
        try:
            import tempfile, os
            tmp = tempfile.gettempdir()
            with open(os.path.join(tmp, "heicat_freight_get.html"), "w", encoding="utf-8") as f:
                f.write(html)      # pre-POST page (has actual btnSearch value + dropdown options)
            with open(os.path.join(tmp, "heicat_freight_debug.html"), "w", encoding="utf-8") as f:
                f.write(result_html)   # POST result (should contain the data table)
        except Exception:
            pass

        rows = _parse_table(result_html)
        return rows


_COL_KEYS = ["customer_id","pickup_date","pickup_place","delivery_date","delivery_place",
             "order_id","obt","freight","add_fee","is_cash","is_return",
             "is_same_day","shipment_type","cod_amount","payment_method"]

class _TP(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows=[]; self._r=None; self._c=None
    def handle_starttag(self, tag, attrs):
        if tag=="tr":  self._r=[]
        elif tag in ("td","th"): self._c=""
    def handle_endtag(self, tag):
        if tag=="tr":
            if self._r: self.rows.append(self._r)
            self._r=None
        elif tag in ("td","th"):
            if self._r is not None and self._c is not None:
                self._r.append(self._c.strip())
            self._c=None
    def handle_data(self, data):
        if self._c is not None: self._c += data
    def handle_entityref(self, name):
        if self._c is not None and name=="nbsp": self._c += " "

def _parse_table(html: str) -> list[dict]:
    p = _TP(); p.feed(html)
    out=[]; hf=False
    for row in p.rows:
        if not row: continue
        joined = " ".join(row)
        if "客戶代號" in joined or "集貨日期" in joined:
            hf=True; continue
        if not hf: continue
        if all(c.replace("\xa0","").strip()==""  for c in row): continue
        if len(row) < 7: continue
        rec = {_COL_KEYS[i]: row[i].replace("\xa0","").strip()
               for i in range(min(len(_COL_KEYS), len(row)))}
        out.append(rec)
    return out
