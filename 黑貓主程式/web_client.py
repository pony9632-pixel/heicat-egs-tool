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
        html = self._req(f"{BASE}/Login.aspx")
        tokens = self._tokens(html)
        captcha_bytes = b""
        # Find captcha image src (various patterns)
        for pat in [r'src="([^"]*[Cc]aptcha[^"]*)"',
                    r'src="([^"]*[Vv]alidat[^"]*\.(?:jpg|gif|png|aspx)[^"]*)"']:
            m = re.search(pat, html, re.I)
            if m:
                src = m.group(1)
                img_url = src if src.startswith("http") else f"{BASE}/{src.lstrip('/')}"
                try: captcha_bytes = self._get_bytes(img_url)
                except Exception: pass
                break
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

    def query_payment(self, start_date: str, end_date: str, account: str) -> list[dict]:
        """Query and parse payment detail table."""
        html = self._req(f"{BASE}/SudaPaymentDetail.aspx?TimeOut=N")
        if "Login.aspx" in html or "txtUserID" in html:
            raise RuntimeError("session_expired")
        tokens = self._tokens(html)
        post = urllib.parse.urlencode({
            **tokens,
            "__EVENTTARGET": "", "__EVENTARGUMENT": "", "__LASTFOCUS": "",
            "txtDateS": start_date, "txtDateE": end_date,
            "UC_UserList1$ddlUserList": account, "btnSearch": "搜尋",
        }, encoding="utf-8").encode("utf-8")
        html = self._req(f"{BASE}/SudaPaymentDetail.aspx?TimeOut=N", post)
        return _parse_table(html)


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
