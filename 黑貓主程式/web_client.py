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
        with self._opener.open(req, timeout=8) as r:
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

    def get_obt_detail(self, obt: str, start_date: str, end_date: str, account: str) -> dict:
        """
        Find the OBT's detail page link in the payment list, follow it, and parse
        電子訂單明細. The detail page loads inside an iframe; we fetch it directly.
        Returns dict with recipient_name, recipient_address, sender_name, etc.
        Returns empty dict on failure.
        """
        post_url = f"{BASE}/SudaPaymentDetail.aspx?TimeOut=N"

        # Step 1 — GET the base form then POST the search
        try:
            list_html = self._payment_page_html()
        except Exception:
            return {}
        tokens = self._tokens(list_html)

        # Resolve account dropdown
        m = re.search(r'<select[^>]*name="UC_UserList1\$ddlUserList"[^>]*>(.*?)</select>',
                      list_html, re.S | re.I)
        if m:
            vals = re.findall(r'<option[^>]*value="([^"]*)"', m.group(1), re.I)
            if vals and account not in vals:
                account = vals[0]

        btn_m = (re.search(r'<input[^>]*name="btnSearch"[^>]*value="([^"]*)"', list_html, re.I)
              or re.search(r'<input[^>]*value="([^"]*)"[^>]*name="btnSearch"', list_html, re.I))
        btn_val = btn_m.group(1) if btn_m else "搜尋"

        keep = {"txtDateS": start_date, "txtDateE": end_date,
                "UC_UserList1$ddlUserList": account}
        search_post = urllib.parse.urlencode({
            **tokens, "__EVENTTARGET": "", "__EVENTARGUMENT": "", "__LASTFOCUS": "",
            **keep, "btnSearch": btn_val,
        }, encoding="utf-8").encode("utf-8")
        try:
            cur_html = self._req(post_url, search_post)
        except Exception:
            return {}

        # Step 2 — paginate to find the page that contains the OBT link
        detail_url = None
        for page_num in range(1, 50):
            detail_url = self._find_obt_link(cur_html, obt)
            if detail_url:
                break
            # Next page
            next_arg = f"Page${page_num + 1}"
            pg_links = re.findall(r"__doPostBack\('([^']+)','(Page\$\d+)'\)", cur_html)
            target = next((t for t, a in pg_links if a == next_arg), None)
            if not target:
                return {}
            page_tokens = self._tokens(cur_html)
            page_post = urllib.parse.urlencode({
                **page_tokens,
                "__EVENTTARGET": target, "__EVENTARGUMENT": next_arg,
                "__LASTFOCUS": "", **keep,
            }, encoding="utf-8").encode("utf-8")
            try:
                cur_html = self._req(post_url, page_post)
            except Exception:
                return {}

        if not detail_url:
            return {}

        # Step 3 — GET the detail page (it loads inside an iframe, but the URL is real)
        try:
            detail_html = self._req(detail_url)
        except Exception:
            return {}

        return self._parse_obt_detail(detail_html)

    @staticmethod
    def _find_obt_link(html: str, obt: str) -> str | None:
        """
        Find the href of the link whose visible text is the OBT number.
        The link is typically an <a href="...">580033357192</a> inside the table.
        Returns an absolute URL or None.
        """
        # Match <a href="...">OBT</a> — text may have surrounding whitespace
        obt_esc = re.escape(obt)
        m = re.search(rf'<a\s[^>]*href="([^"]+)"[^>]*>\s*{obt_esc}\s*</a>', html, re.I)
        if not m:
            # Also try: href before or after; and javascript: onclick patterns
            m = re.search(rf'href="([^"]*[Oo][Bb][Tt][^"]*{obt_esc}[^"]*)"', html, re.I)
        if not m:
            return None
        href = m.group(1).strip()
        if href.lower().startswith("javascript"):
            # Try to extract a URL from javascript: window.open('...') or similar
            url_m = re.search(r"['\"]([^'\"]+\.aspx[^'\"]*)['\"]", href, re.I)
            if url_m:
                href = url_m.group(1)
            else:
                return None
        if href.startswith("http"):
            return href
        # Relative path — resolve against BASE
        if href.startswith("/"):
            base_root = re.match(r"https?://[^/]+", BASE)
            return (base_root.group(0) if base_root else "") + href
        return f"{BASE}/{href.lstrip('./')}"

    @staticmethod
    def _parse_obt_detail(html: str) -> dict:
        """Parse 電子訂單明細 fields from the detail panel HTML."""
        def _span(sid: str) -> str:
            # Try with display:none (unmasked) first
            m = re.search(rf'id="{sid}"[^>]*style="[^"]*display\s*:\s*none[^"]*"[^>]*>([^<]+)<',
                          html, re.I)
            if not m:
                m = re.search(rf'id="{sid}"[^>]*>([^<]+)<', html, re.I)
            return m.group(1).strip().replace("\xa0", "") if m else ""

        def _after_label(label: str) -> str:
            # Match label cell then grab next td value
            m = re.search(
                rf'{re.escape(label)}[^<]*</td>\s*(?:<td[^>]*>\s*)*([^<{{}}]+?)\s*</td>',
                html, re.S | re.I)
            return m.group(1).strip().replace("\xa0", "") if m else ""

        rec_name = _span("LBLOUTPUT_RECNAME") or _span("LBLOUTPUT_MASKRECNAME")

        return {
            "recipient_name":    rec_name,
            "recipient_address": _after_label("收件人地址"),
            "recipient_zip":     _after_label("郵遞區號"),
            "sender_name":       _after_label("寄件人姓名"),
            "sender_address":    _after_label("寄件人地址"),
            "product_name":      _after_label("物件名稱"),
            "pickup_date":       _after_label("集貨日期"),
            "order_date":        _after_label("訂單日期"),
            "notes":             _after_label("備註"),
        }

    def _obt_export_html(self) -> str:
        """
        Navigate to 線上印單 → 匯出託運單資料 page.
        Tries several known FuncNo values and the navigation link text.
        Raises RuntimeError on failure.
        """
        # Try common FuncNo values for the OBT export / list page
        # FuncNo=167 = SudaPaymentDetail (fee query)
        # FuncNo=101~199 = 物流 functions — try candidates
        candidates_func = ["101", "102", "103", "104", "105", "110", "115", "120",
                           "150", "160", "161", "162", "163", "164", "165", "166",
                           "168", "170", "175", "180"]
        # Also try known direct page names
        candidates_url  = [
            f"{BASE}/SudaOBTQuery.aspx",
            f"{BASE}/SudaOBTExport.aspx",
            f"{BASE}/SudaObtList.aspx",
            f"{BASE}/OBTQuery.aspx",
            f"{BASE}/ExportOBT.aspx",
        ]

        # First: scan nav HTML for the menu item text
        try:
            nav_html = self._req(f"{BASE}/SudaPaymentDetail.aspx?TimeOut=N")
            # Look for any href near "匯出託運單" text
            m = re.search(r'href="([^"]+)"[^>]*>[^<]*匯出託運單[^<]*<', nav_html, re.I | re.S)
            if not m:
                # Try the pattern FuncNo=xxx inside onClick / href attributes
                for fn_m in re.finditer(r'FuncNo=(\d+)', nav_html):
                    candidates_func.insert(0, fn_m.group(1))  # prepend found FuncNos
            if m:
                href = m.group(1).strip()
                url = href if href.startswith("http") else f"{BASE}/{href.lstrip('/')}"
                html = self._req(url)
                if "匯出" in html or "託運單" in html:
                    return html
        except Exception:
            pass

        # Try FuncNo redirects
        for fn in dict.fromkeys(candidates_func):  # deduplicated, order preserved
            try:
                html = self._req(f"{BASE}/RedirectFunc.aspx?FuncNo={fn}")
                if "Login.aspx" in html or "txtUserID" in html:
                    continue
                if ("匯出" in html or "ExportOBT" in html.lower()) and "託運單" in html:
                    return html
            except Exception:
                continue

        # Try direct URLs
        for url in candidates_url:
            try:
                html = self._req(url)
                if "Login.aspx" in html or "txtUserID" in html:
                    continue
                if "託運單" in html:
                    return html
            except Exception:
                continue

        raise RuntimeError("找不到匯出託運單資料頁面，請確認已登入且帳號有此功能權限。")

    def query_obt_list(self, start_date: str, end_date: str) -> list[dict]:
        """
        Query 匯出託運單資料 (線上印單) to get OBT list with FULL recipient info.
        start_date / end_date: YYYYMMDD (will be converted to YYYY/MM/DD for the form).
        Returns list of dicts:
          obt, order_id, shipment_date, cod_amount, product_name,
          recipient_name, phone_last3, mobile_last3, recipient_address,
          thermosphere, spec, notes
        Returns [] on any error.
        """
        # Convert YYYYMMDD → YYYY/MM/DD
        def _fmt(d: str) -> str:
            return f"{d[:4]}/{d[4:6]}/{d[6:]}" if len(d) == 8 else d

        try:
            page_html = self._obt_export_html()
        except Exception:
            return []

        tokens = self._tokens(page_html)
        if not tokens:
            return []

        # Find search button value
        btn_m = (re.search(r'<input[^>]*name="btnQuery"[^>]*value="([^"]*)"', page_html, re.I)
              or re.search(r'<input[^>]*value="([^"]*)"[^>]*name="btnQuery"', page_html, re.I)
              or re.search(r'<input[^>]*type="submit"[^>]*value="([^"]*)"', page_html, re.I))
        btn_name  = "btnQuery"
        btn_value = btn_m.group(1) if btn_m else "查詢"

        # Find date field names from the form
        ds_m = re.search(r'<input[^>]*name="([^"]*[Dd]ate[Ss][^"]*)"', page_html, re.I) \
            or re.search(r'<input[^>]*name="([^"]*[Ss]tart[^"]*)"', page_html, re.I) \
            or re.search(r'<input[^>]*name="(txt[Ss][^"]*)"', page_html, re.I)
        de_m = re.search(r'<input[^>]*name="([^"]*[Dd]ate[Ee][^"]*)"', page_html, re.I) \
            or re.search(r'<input[^>]*name="([^"]*[Ee]nd[^"]*)"', page_html, re.I) \
            or re.search(r'<input[^>]*name="(txt[Ee][^"]*)"', page_html, re.I)

        start_field = ds_m.group(1) if ds_m else "txtDateS"
        end_field   = de_m.group(1) if de_m else "txtDateE"

        # Find the page's own URL from a form action, or reuse the redirect URL
        action_m = re.search(r'<form[^>]+action="([^"]*)"', page_html, re.I)
        if action_m:
            action = action_m.group(1).strip()
            form_url = action if action.startswith("http") else f"{BASE}/{action.lstrip('/')}"
        else:
            form_url = f"{BASE}/SudaOBTQuery.aspx"

        post_data = urllib.parse.urlencode({
            **tokens,
            "__EVENTTARGET": "", "__EVENTARGUMENT": "", "__LASTFOCUS": "",
            start_field: _fmt(start_date),
            end_field:   _fmt(end_date),
            btn_name:    btn_value,
        }, encoding="utf-8").encode("utf-8")

        try:
            result_html = self._req(form_url, post_data)
        except Exception:
            return []

        return _parse_obt_table(result_html)

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
        """Query and parse payment detail table, following all pages."""
        html = self._payment_page_html()
        tokens = self._tokens(html)

        # Auto-resolve account
        m = re.search(r'<select[^>]*name="UC_UserList1\$ddlUserList"[^>]*>(.*?)</select>',
                      html, re.S | re.I)
        dropdown_vals = []
        if m:
            dropdown_vals = re.findall(r'<option[^>]*value="([^"]*)"[^>]*>', m.group(1), re.I)
        if dropdown_vals and account not in dropdown_vals:
            account = dropdown_vals[0]

        btn_val_m = re.search(r'<input[^>]*name="btnSearch"[^>]*value="([^"]*)"', html, re.I)
        if not btn_val_m:
            btn_val_m = re.search(r'<input[^>]*value="([^"]*)"[^>]*name="btnSearch"', html, re.I)
        btn_val = btn_val_m.group(1) if btn_val_m else "搜尋"

        post_url = f"{BASE}/SudaPaymentDetail.aspx?TimeOut=N"
        # Fields to keep between pagination POSTs
        keep = {"txtDateS": start_date, "txtDateE": end_date,
                "UC_UserList1$ddlUserList": account}

        # --- Page 1 ---
        page1_post = urllib.parse.urlencode({
            **tokens,
            "__EVENTTARGET": "", "__EVENTARGUMENT": "", "__LASTFOCUS": "",
            **keep, "btnSearch": btn_val,
        }, encoding="utf-8").encode("utf-8")
        cur_html = self._req(post_url, page1_post)
        all_rows = _parse_table(cur_html)

        # --- Additional pages via ASP.NET __doPostBack pagination ---
        for page_num in range(2, 50):  # safety cap at 50 pages
            next_arg = f"Page${page_num}"
            links = re.findall(r"__doPostBack\('([^']+)','(Page\$\d+)'\)", cur_html)
            target = next((t for t, a in links if a == next_arg), None)
            if not target:
                break  # no more pages
            try:
                page_tokens = self._tokens(cur_html)
                page_post = urllib.parse.urlencode({
                    **page_tokens,
                    "__EVENTTARGET": target, "__EVENTARGUMENT": next_arg,
                    "__LASTFOCUS": "", **keep,
                }, encoding="utf-8").encode("utf-8")
                cur_html = self._req(post_url, page_post)
                new_rows = _parse_table(cur_html)
                if not new_rows:
                    break
                all_rows.extend(new_rows)
            except Exception:
                break  # network error on this page — return what we have

        return all_rows


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


# Column mapping for 匯出託運單資料 (線上印單) table
# Columns from screenshot: 出貨日, 訂單編號, 託運單號, 代收金額, 物品名稱,
#   收件人姓名, 電話後三碼, 手機後三碼, 收件人地址, 溫層, 規格, 備註
_OBT_LIST_HEADER_KEYS = {
    "出貨日":    "shipment_date",
    "訂單編號":  "order_id",
    "託運單號":  "obt",
    "代收金額":  "cod_amount",
    "物品名稱":  "product_name",
    "收件人姓名":"recipient_name",
    "電話後三碼":"phone_last3",
    "手機後三碼":"mobile_last3",
    "收件人地址":"recipient_address",
    "溫層":      "thermosphere",
    "規格":      "spec",
    "備註":      "notes",
}

def _parse_obt_table(html: str) -> list[dict]:
    """Parse 匯出託運單資料 table — dynamic header detection."""
    p = _TP(); p.feed(html)
    out = []; col_keys = []
    for row in p.rows:
        if not row: continue
        cells = [c.replace("\xa0", "").strip() for c in row]
        # Detect header row
        if not col_keys:
            joined = " ".join(cells)
            if "託運單號" in joined or "收件人姓名" in joined or "出貨日" in joined:
                col_keys = [_OBT_LIST_HEADER_KEYS.get(c, c) for c in cells]
            continue
        # Skip all-empty rows or rows shorter than 3
        if all(c == "" for c in cells) or len(cells) < 3:
            continue
        rec = {col_keys[i]: cells[i] for i in range(min(len(col_keys), len(cells)))}
        if rec.get("obt") or rec.get("shipment_date"):
            out.append(rec)
    return out
