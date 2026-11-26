"""
統一速達（黑貓）EGS API 客戶端

API base: https://api.suda.com.tw/api/Egs/{endpoint}

已確認可用端點：
  PrintOBT    - 建立並列印託運單（PDF）
  CancelOBT   - 取消託運單
  DownloadOBT - 下載已建立的 PDF 檔案
  OBTStatus   - 查詢託運單貨態（依規格書實作，尚未以正式帳號實測）

欄位代碼參考：
  Thermosphere  0001=常溫  0002=冷藏  0003=冷凍
  Spec          0001=60cm  0002=90cm  0003=120cm  0004=150cm
  ReceiptLocation  01=宅配
  DeliveryTime  01=13 時前  02=14-18 時  04=不指定
  PrintType     01=PDF
  PrintOBTType  01=標準
"""

from __future__ import annotations

import ssl
import json
import time
import urllib.request
import urllib.error
from datetime import date, timedelta

from sslctx import verified_context, insecure_context


API_BASE = "https://api.suda.com.tw/api/Egs"

# OBTStatus（查詢託運單貨態）單次請求的單號上限
OBT_STATUS_MAX_PER_CALL = 10

# 建單逾時（秒）。規格書要求「連線逾時時間請設定最少 120 秒」；
# 實測伺服器光回一個參數錯誤就可能超過 15 秒，太短會把「其實已建成」誤判成失敗。
PRINT_TIMEOUT = 130

# 取消託運單逾時（秒）。黑貓後台處理註銷常要 100 秒以上才回。
CANCEL_TIMEOUT = 300


class ApiTimeoutError(RuntimeError):
    """請求已送出但在逾時內沒收到回應 —— 伺服器可能已經處理完成。"""

_ssl_ctx = verified_context()
_ssl_fallback_used = False


def _open(req: urllib.request.Request, timeout: int):
    """urlopen，預設完整憑證驗證；api.suda.com.tw 實際驗證失敗時
    退回不驗證（僅此主機、僅此程序內），並印出警告。"""
    global _ssl_ctx, _ssl_fallback_used
    try:
        return urllib.request.urlopen(req, context=_ssl_ctx, timeout=timeout)
    except urllib.error.URLError as e:
        if not _ssl_fallback_used and isinstance(e.reason, ssl.SSLCertVerificationError):
            print(f"[WARN] api.suda.com.tw 憑證驗證失敗（{e.reason}），改用不驗證連線", flush=True)
            _ssl_ctx = insecure_context()
            _ssl_fallback_used = True
            return urllib.request.urlopen(req, context=_ssl_ctx, timeout=timeout)
        raise


def _post(endpoint: str, payload: dict, timeout: int = 15, retry: int = 0) -> dict:
    """POST JSON。retry 只對連線層錯誤（URLError，請求未送達）重試，
    建單/取消這類非冪等呼叫一律 retry=0，避免重複建單。
    請求送出後等不到回應會丟 ApiTimeoutError（不重試：伺服器可能已處理）。"""
    url = f"{API_BASE}/{endpoint}"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    for attempt in range(retry + 1):
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with _open(req, timeout=timeout) as r:
                body = r.read().decode("utf-8")
                return json.loads(body)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            try:
                return json.loads(body)
            except Exception:
                raise RuntimeError(f"HTTP {e.code}：伺服器拒絕請求。{('回應：' + body[:200]) if body.strip() else '（無回應內容）'}")
        except urllib.error.URLError as e:
            if attempt < retry:
                time.sleep(1 + attempt * 2)
                continue
            raise RuntimeError(f"無法連線黑貓 API：{e.reason}")
        except TimeoutError:
            # 讀取回應階段逾時（socket.timeout 是 TimeoutError 的別名）：請求已送達
            raise ApiTimeoutError(
                f"黑貓 API 超過 {timeout} 秒沒有回應（{endpoint}）。"
                "伺服器可能已經處理完成，請先確認結果再重試。")


class SudaClient:
    def __init__(self, customer_id: str, customer_token: str):
        self.customer_id = customer_id
        self.customer_token = customer_token

    def _auth(self) -> dict:
        return {
            "CustomerId": self.customer_id,
            "CustomerToken": self.customer_token,
        }

    def print_obt(self, orders: list[dict], print_type: str = "01", print_obt_type: str = "01",
                  timeout: int = PRINT_TIMEOUT) -> dict:
        """
        建立並列印託運單。
        成功時 Data 為 PDF base64 字串。

        orders 欄位：
          OBTNumber        (空字串 = 系統自動產生)
          OrderId          客戶自訂訂單號
          Thermosphere     溫層代碼 (0001/0002/0003)
          Spec             尺寸代碼 (0001/0002/0003/0004 = 60/90/120/150 cm)
          ReceiptLocation  收件方式 (01=宅配)
          RecipientName    收件人
          RecipientTel     收件人電話
          RecipientMobile  收件人手機
          RecipientAddress 收件地址
          SenderName       寄件人
          SenderTel        寄件人電話
          SenderMobile     寄件人手機
          SenderZipCode    寄件郵遞區號（6碼，含縣市代碼）
          SenderAddress    寄件地址
          ShipmentDate     出貨日 YYYYMMDD
          DeliveryDate     配送日 YYYYMMDD
          DeliveryTime     配送時段代碼 (01/02/04)
          IsFreight        到付 Y/N
          IsCollection     代收 Y/N
          IsSwipe          刷卡 Y/N
          IsDeclare        申報 Y/N
          ProductTypeId    產品類型ID (需向黑貓確認)
          ProductName      貨品名稱
        """
        payload = {
            **self._auth(),
            "PrintType": print_type,
            "PrintOBTType": print_obt_type,
            "Orders": orders,
        }
        try:
            return _post("PrintOBT", payload, timeout=timeout)
        except ApiTimeoutError:
            if not orders:      # 連線測試送的是空訂單，沒有單會被建立
                raise
            raise ApiTimeoutError(
                f"黑貓 API 超過 {timeout} 秒沒有回應，這張單「可能已經建立成功」。"
                "請先到「貨運查詢」按「同步 14 天紀錄」或到契客專區確認，"
                "確定沒有這張單再重新建單，以免重複。")

    def cancel_obt(self, obt_numbers, cancel_type: str = "01") -> dict:
        """
        取消託運單。
        cancel_type: 01=取消

        這支 API 不在公開的契客版規格書裡，以下是 2026-11-26 用假帳號實測伺服器
        欄位驗證得到的結果（欄位驗證在帳號驗證之前，1 秒內就回）：
          - 必要欄位只有 CancelType 與 OBTNumber（字串）；缺了回 E001「欄位是必要項」
          - CancelType 只接受 "01"（"02"、"99" 回「資料不正確」，長度須為 2）
          - OBTNumbers 陣列不被接受（仍回 OBTNumber 是必要項）；OBTKind 不需要
        所以這裡送的格式是對的。帳號驗證通過後，黑貓後台實際處理註銷很慢，
        舊筆記實測 100+ 秒才回，因此逾時設 CANCEL_TIMEOUT，呼叫端不可以卡住畫面。
        已知的失敗回應：E079 已列印不可註銷、E080 查無訂單資料（可能已取消）。
        """
        # 接受 list 或 str，內部一律轉為單一字串呼叫
        if isinstance(obt_numbers, (list, tuple)):
            if not obt_numbers:
                raise ValueError("obt_numbers 不可為空")
            obt = str(obt_numbers[0]).strip()
        else:
            obt = str(obt_numbers).strip()
        payload = {
            **self._auth(),
            "CancelType": cancel_type,
            "OBTNumber": obt,
        }
        return _post("CancelOBT", payload, timeout=CANCEL_TIMEOUT)

    def download_obt(self, file_no: str) -> bytes:
        """
        下載已建立的 PDF，直接回傳 PDF 二進位資料。
        file_no 來自 PrintOBT 成功回應的 FileNo 欄位。
        下載為冪等操作，連線層錯誤重試 2 次。
        """
        payload = json.dumps({**self._auth(), "FileNo": file_no},
                             ensure_ascii=False).encode("utf-8")
        url = f"{API_BASE}/DownloadOBT"
        for attempt in range(3):
            req = urllib.request.Request(
                url, data=payload,
                headers={"Content-Type": "application/json; charset=utf-8"},
                method="POST",
            )
            try:
                with _open(req, timeout=15) as r:
                    return r.read()
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"下載 PDF 失敗（HTTP {e.code}）。{('回應：' + body[:200]) if body.strip() else ''}")
            except urllib.error.URLError as e:
                if attempt < 2:
                    time.sleep(1 + attempt * 2)
                    continue
                raise RuntimeError(f"下載 PDF 失敗，無法連線：{e.reason}")

    def obt_status(self, obt_numbers) -> dict:
        """
        查詢託運單貨態（OBTStatus），回傳原始回應 dict。

        規格書限制（呼叫端要自己遵守，這裡只擋筆數）：
          - 一次最多 OBT_STATUS_MAX_PER_CALL 筆
          - 相同單號 2 小時內只能查一次
          - 同時最多 3 個查詢、每日上限 3,000 次

        成功：IsOK="Y"，Data.OBTs 只含「已有貨態」的單號，每筆有
              OBTNumber / StatusId / StatusName / StationName / CreateDateTime / StatusList。
        全部都沒貨態或被限流：IsOK="N"、Data=None，原因在 Message。
        查詢為冪等操作，連線層錯誤重試 1 次。
        """
        if isinstance(obt_numbers, str):
            obt_numbers = [obt_numbers]
        nums = [str(o).strip() for o in obt_numbers if str(o).strip()]
        if not nums:
            raise ValueError("obt_numbers 不可為空")
        if len(nums) > OBT_STATUS_MAX_PER_CALL:
            raise ValueError(f"OBTStatus 一次最多查 {OBT_STATUS_MAX_PER_CALL} 筆")
        payload = {**self._auth(), "OBTNumbers": nums}
        return _post("OBTStatus", payload, timeout=60, retry=1)

    def query_freight(self, start_date: str, end_date: str) -> dict:
        """
        查詢客戶交易明細（運費）。
        start_date / end_date: YYYYMMDD
        依序嘗試已知的端點與欄位格式，回傳第一個成功的結果。
        """
        auth = self._auth()
        # 嘗試順序：端點名稱 × 日期欄位格式
        candidates = [
            ("CustomerTransactionDetail", {"StartDate": start_date, "EndDate": end_date}),
            ("CustomerTransactionDetail", {"BeginDate": start_date, "EndDate": end_date}),
            ("QueryFreight",              {"StartDate": start_date, "EndDate": end_date}),
            ("QueryTransaction",          {"StartDate": start_date, "EndDate": end_date}),
            ("FreightDetail",             {"StartDate": start_date, "EndDate": end_date}),
        ]
        last_err = None
        for endpoint, extra in candidates:
            try:
                resp = _post(endpoint, {**auth, **extra}, retry=2)
                # 成功：回傳時附上使用的端點名稱供除錯
                resp["_endpoint_used"] = endpoint
                return resp
            except RuntimeError as e:
                last_err = (endpoint, str(e))
                # 404 = 端點不存在，繼續試下一個
                # 500 = 端點存在但格式錯誤，也繼續試
                continue
        raise RuntimeError(
            f"所有端點均失敗，最後嘗試：{last_err[0]}\n錯誤：{last_err[1]}"
        )


# ─── 錯誤代碼 → 該怎麼處理 ───────────────────────────────────────────────────
# 黑貓回的 Message 本身已是中文（例：「執行失敗 -> E009-契客資料不正確。」），
# 這裡只補上「接下來該做什麼」。代碼依印單 API 規格書附錄三。
ERROR_HINTS = {
    "E009": "黑貓不接受目前的契客資料。請到「設定」頁確認客戶代號無誤，按一次「儲存設定」後再試。",
    "E010": "黑貓暫時無法驗證帳號，請稍後再試。",
    "E011": "合約已失效，請聯絡黑貓業務或簽約營業所。",
    "E013": "目前的網路 IP 不在黑貓允許名單內，請換回公司網路，或請黑貓業務開通。",
    "E015": "API 授權碼不正確，請到契客專區「取得印單 API 授權碼」重新複製，貼到「設定」頁。",
    "E016": "API 授權碼格式不對（可能多貼了空白或換行），請到「設定」頁重新貼上。",
    "E019": "訂單編號不能有空白，請移除後再試。",
    "E020": "冷藏／冷凍不能寄 150 cm，請改小一級尺寸或改常溫。",
    "E026": "收件人姓名含有不允許的符號（例如表情符號、特殊標點），請改用一般文字。",
    "E027": "收件人電話與手機至少要填一個。",
    "E028": "寄件人電話與手機至少要填一個，請到「設定」頁補上。",
    "E029": "這個地址黑貓不配送（例如部分離島或偏遠地區）。",
    "E032": "指定的配達日黑貓不配送（週日或國定假日），請改其他日期。",
    "E033": "「到付」與「代收貨款」不能同時選。",
    "E035": "代收金額要在 1～100,000 元之間。",
    "E036": "代收金額要在 1～20,000 元之間。",
    "E037": "沒有選代收貨款時，代收金額必須是 0。",
    "E044": "品名類別不正確，請到「設定」頁按一次「儲存設定」再試。",
    "E045": "收件地區當天配送量已滿，請改其他配達日。",
    "E053": "收件人地址黑貓無法辨識，請確認縣市、區、路名、門牌都有寫且沒有錯字。",
    "E055": "收件人地址所在地區黑貓不配送。",
    "E056": "寄件人地址黑貓無法辨識，請到「設定」頁確認寄件地址。",
    "E057": "寄件人郵遞區號與地址對不上，請到「設定」頁確認 6 碼郵遞區號。",
    "E058": "寄件人地址所在地區黑貓不提供服務，請到「設定」頁確認寄件地址。",
    "E067": "黑貓系統發生錯誤，請稍後再試；持續發生請聯絡黑貓。",
    "E079": "這張單黑貓不允許用 API 取消（已列印）。需要作廢請到契客專區處理，或聯絡黑貓營業所。",
    "E080": "黑貓查不到這張單（可能已取消或單號有誤），無法取消。",
    "E084": "同一時間送出太多請求，請等一下再試。",
    "E085": "呼叫太頻繁，請依訊息上的時間稍候再試。",
    "E086": "今天的呼叫次數已達上限，請明天再試。",
    "E087": "同一張單 2 小時內只能查一次貨態，請稍後再查。",
    "E088": "配達日不能是過去的日期。",
    "E089": "配達日不能早於出貨日。",
    "E090": "配達日不能和出貨日同一天，最快是出貨日的隔天。",
    "E091": "配達日不能超過出貨日 7 天。",
}


def explain_error(message) -> str:
    """在黑貓回的錯誤訊息後面補上處理方式；沒有對應提示就原樣回傳。"""
    import re
    text = str(message or "").strip()
    for code in re.findall(r"E\d{3}", text):
        hint = ERROR_HINTS.get(code)
        if hint:
            return f"{text}\n→ {hint}"
    return text


def save_pdf(base64_data: str, path: str) -> None:
    import base64, os
    # 先寫暫存檔再 rename，避免寫到一半中斷留下毀損的 PDF
    tmp = f"{path}.tmp"
    with open(tmp, "wb") as f:
        f.write(base64.b64decode(base64_data))
    os.replace(tmp, path)
    print(f"[PDF] 已儲存：{path}")


def _skip_sunday(d: date) -> date:
    if d.weekday() == 6:  # 0=Mon … 6=Sun
        d += timedelta(days=1)
    return d


def default_shipment_date() -> str:
    return _skip_sunday(date.today()).strftime("%Y%m%d")


def default_delivery_date() -> str:
    ship = _skip_sunday(date.today())
    return _skip_sunday(ship + timedelta(days=1)).strftime("%Y%m%d")
