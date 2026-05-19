"""
統一速達（黑貓）EGS API 客戶端

API base: https://api.suda.com.tw/api/Egs/{endpoint}

已確認可用端點：
  PrintOBT    - 建立並列印託運單（PDF）
  CancelOBT   - 取消託運單
  DownloadOBT - 下載已建立的 PDF 檔案

欄位代碼參考：
  Thermosphere  0001=常溫  0002=冷藏  0003=冷凍
  Spec          0060/0080/0100/0120/0140/0160 (cm)
  ReceiptLocation  01=宅配
  DeliveryTime  01=不指定  02=上午(08-12)  03=下午(12-17)  04=晚上(17-20)
  PrintType     01=PDF
  PrintOBTType  01=標準
"""

import ssl
import json
import urllib.request
import urllib.error
from datetime import date, timedelta


API_BASE = "https://api.suda.com.tw/api/Egs"

# Disable SSL verification for api.suda.com.tw (certificate chain issue)
_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE


def _post(endpoint: str, payload: dict) -> dict:
    url = f"{API_BASE}/{endpoint}"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, context=_ssl_ctx, timeout=15) as r:
            body = r.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            return json.loads(body)
        except Exception:
            raise RuntimeError(f"HTTP {e.code}：伺服器拒絕請求。{('回應：' + body[:200]) if body.strip() else '（無回應內容）'}")


class SudaClient:
    def __init__(self, customer_id: str, customer_token: str):
        self.customer_id = customer_id
        self.customer_token = customer_token

    def _auth(self) -> dict:
        return {
            "CustomerId": self.customer_id,
            "CustomerToken": self.customer_token,
        }

    def print_obt(self, orders: list[dict], print_type: str = "01", print_obt_type: str = "01") -> dict:
        """
        建立並列印託運單。
        成功時 Data 為 PDF base64 字串。

        orders 欄位：
          OBTNumber        (空字串 = 系統自動產生)
          OrderId          客戶自訂訂單號
          Thermosphere     溫層代碼 (0001/0002/0003)
          Spec             尺寸代碼 (0060/0080/0100/0120/0140/0160)
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
          DeliveryTime     配送時段代碼 (01~04)
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
        return _post("PrintOBT", payload)

    def cancel_obt(self, obt_numbers: list[str], cancel_type: str = "01") -> dict:
        """
        取消託運單。
        cancel_type: 01=取消
        """
        payload = {
            **self._auth(),
            "CancelType": cancel_type,
            "OBTNumber": obt_numbers,
        }
        return _post("CancelOBT", payload)

    def download_obt(self, file_no: str) -> bytes:
        """
        下載已建立的 PDF，直接回傳 PDF 二進位資料。
        file_no 來自 PrintOBT 成功回應的 FileNo 欄位。
        """
        import json as _json
        payload = _json.dumps({**self._auth(), "FileNo": file_no},
                              ensure_ascii=False).encode("utf-8")
        url = f"{API_BASE}/DownloadOBT"
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urllib.request.urlopen(req, context=_ssl_ctx, timeout=15) as r:
            return r.read()

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
                resp = _post(endpoint, {**auth, **extra})
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


def save_pdf(base64_data: str, path: str) -> None:
    import base64
    with open(path, "wb") as f:
        f.write(base64.b64decode(base64_data))
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
