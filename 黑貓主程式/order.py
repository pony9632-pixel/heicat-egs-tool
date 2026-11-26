"""
建立寄件單（託運單）模組 — 使用 EGS API (PrintOBT)

CSV 欄位說明：
  必填：
    recipient_name     收件人姓名
    recipient_phone    收件人電話（市話或手機擇一即可，兩欄都填更好）
    recipient_mobile   收件人手機
    recipient_address  收件地址
    order_id           客戶自訂訂單號（不可重複）

  選填（有預設值）：
    spec               尺寸：0001 60cm / 0002 90cm / 0003 120cm / 0004 150cm（預設 0001）
    thermosphere       溫層：0001 常溫 / 0002 冷藏 / 0003 冷凍（預設 0001）
    delivery_time      配送時段：01 13 時前 / 02 14–18 時 / 04 不指定（預設 04；其他值一律當不指定）
    shipment_date      出貨日 YYYYMMDD（預設今天）
    delivery_date      指定配送日 YYYYMMDD（預設明天）
    product_name       貨品名稱（預設「一般物品」）
    is_collection      代收貨款 Y/N（預設 N）
    collection_amount  代收金額（is_collection=Y 時填）
    notes              備註
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

from datetime import date, datetime

from api_client import (SudaClient, save_pdf, default_shipment_date, default_delivery_date,
                        explain_error)


TEMPLATE_FIELDS = [
    "order_id",
    "recipient_name",
    "recipient_phone",
    "recipient_mobile",
    "recipient_address",
    "spec",
    "thermosphere",
    "delivery_time",
    "shipment_date",
    "delivery_date",
    "product_name",
    "is_freight",
    "is_collection",
    "collection_amount",
    "notes",
]

REQUIRED_FIELDS = {"order_id", "recipient_name", "recipient_address"}
FIXED_PRODUCT_TYPE_ID = "0006"
# 印單 API 規格書的希望配達時間代碼：01=13 時前、02=14–18 時、04=不指定
VALID_DELIVERY_TIMES = {"01", "02", "04"}
DEFAULT_DELIVERY_TIME = "04"

# ─── 送出前檢查（規則逐條對應印單 API 規格書 2.2.1 與附錄三錯誤代碼）──────────
VALID_SPECS         = {"0001", "0002", "0003", "0004"}   # 60 / 90 / 120 / 150 cm
VALID_THERMOSPHERES = {"0001", "0002", "0003"}           # 常溫 / 冷藏 / 冷凍
ORDER_ID_FORBIDDEN  = "/_@|\\"                            # E001：OrderId 不允許的符號
# ProductName 不允許含有的字串（規格書 2.2.1 第 33 項）
PRODUCT_NAME_FORBIDDEN = (
    "文件", "標單", "明信片", "郵簡", "信函", "資料", "發票", "訴訟文件", "公文",
    "身分證明文件", "報名表", "申請書", "帳單", "訂單", "報價單", "繳費單",
    "通知單", "保險單", "文書",
)
MAX_COLLECTION_AMOUNT = 100000


def _parse_ymd(value: str):
    try:
        return datetime.strptime(value, "%Y%m%d").date() if len(value) == 8 else None
    except ValueError:
        return None


def _is_yes(value) -> bool:
    return str(value or "").strip().upper().startswith("Y")


def validate_order(row: dict, today: date | None = None) -> list[str]:
    """
    送出前檢查一筆訂單，回傳問題清單（空清單 = 可以送）。
    只擋規格書明載會被黑貓退件的情況，省掉一次來回並給出看得懂的原因；
    沒把握的（電話格式、姓名符號、地址是否可配送）不擋，交給黑貓判斷。
    """
    today = today or date.today()
    g = lambda k: str(row.get(k) or "").strip()
    errs: list[str] = []

    oid = g("order_id")
    if not oid:
        errs.append("缺少訂單編號。")
    else:
        if any(ch.isspace() for ch in str(row.get("order_id") or "").strip()):
            errs.append("訂單編號不能有空白。")
        bad = sorted({ch for ch in oid if ch in ORDER_ID_FORBIDDEN})
        if bad:
            errs.append(f"訂單編號不能有這些符號：{' '.join(bad)}")
        if len(oid) > 35:
            errs.append(f"訂單編號最多 35 個字（目前 {len(oid)}）。")

    name = g("recipient_name")
    if not name:
        errs.append("缺少收件人姓名。")
    elif len(name) > 30:
        errs.append(f"收件人姓名最多 30 個字（目前 {len(name)}）。")

    addr = g("recipient_address")
    if not addr:
        errs.append("缺少收件人地址。")
    elif len(addr) > 120:
        errs.append(f"收件人地址最多 120 個字（目前 {len(addr)}）。")

    if not g("recipient_phone") and not g("recipient_mobile"):
        errs.append("收件人電話與手機至少要填一個。")

    spec   = g("spec") or "0001"
    thermo = g("thermosphere") or "0001"
    if spec not in VALID_SPECS:
        errs.append(f"尺寸代碼「{spec}」不正確，請用 0001（60cm）／0002（90cm）／0003（120cm）／0004（150cm）。")
    if thermo not in VALID_THERMOSPHERES:
        errs.append(f"溫層代碼「{thermo}」不正確，請用 0001 常溫／0002 冷藏／0003 冷凍。")
    if thermo in ("0002", "0003") and spec == "0004":
        errs.append("冷藏／冷凍不能寄 150 cm，請改小一級尺寸或改常溫。")

    product = g("product_name") or "一般物品"
    if len(product) > 20:
        errs.append(f"貨品名稱最多 20 個字（目前 {len(product)}）。")
    hit = next((w for w in PRODUCT_NAME_FORBIDDEN if w in product), None)
    if hit:
        errs.append(f"貨品名稱不能含有「{hit}」（黑貓不收文件類物品名稱），請改用實際品名。")

    notes = g("notes")
    if len(notes) > 100:
        errs.append(f"備註最多 100 個字（目前 {len(notes)}）。")

    ship_s = g("shipment_date") or default_shipment_date()
    deli_s = g("delivery_date") or default_delivery_date()
    ship, deli = _parse_ymd(ship_s), _parse_ymd(deli_s)
    if ship is None:
        errs.append(f"出貨日「{ship_s}」不是正確的日期（格式 YYYYMMDD）。")
    if deli is None:
        errs.append(f"配達日「{deli_s}」不是正確的日期（格式 YYYYMMDD）。")
    if deli is not None:
        if deli < today:
            errs.append("配達日不能是過去的日期。")
        if deli.weekday() == 6:
            errs.append("配達日不能是星期日（黑貓週日不配送）。")
    if ship is not None and deli is not None:
        if deli <= ship:
            errs.append("配達日必須晚於出貨日（最快是出貨日的隔天）。")
        elif (deli - ship).days > 7:
            errs.append("配達日不能超過出貨日 7 天。")

    if _is_yes(row.get("is_collection")):
        if _is_yes(row.get("is_freight")):
            errs.append("「到付」與「代收貨款」不能同時選。")
        amt_s = g("collection_amount").replace(",", "")
        if not amt_s.isdigit() or not (1 <= int(amt_s) <= MAX_COLLECTION_AMOUNT):
            errs.append("代收金額要是 1～100,000 的整數。")

    return errs


def generate_template(path: str = "orders_template.csv") -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=TEMPLATE_FIELDS)
        writer.writeheader()
        writer.writerow({
            "order_id": "ORD-001",
            "recipient_name": "王小明",
            "recipient_phone": "0212345678",
            "recipient_mobile": "0912345678",
            "recipient_address": "台北市信義區市府路1號",
            "spec": "0001",
            "thermosphere": "0001",
            "delivery_time": "04",
            "shipment_date": default_shipment_date(),
            "delivery_date": default_delivery_date(),
            "product_name": "一般物品",
            "is_freight": "N",
            "is_collection": "N",
            "collection_amount": "0",
            "notes": "",
        })
    print(f"[Template] 已產生範本：{path}")


def load_orders(path: str) -> list[dict]:
    orders = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, start=2):
            missing = REQUIRED_FIELDS - set(k for k, v in row.items() if v.strip())
            if missing:
                print(f"[CSV] 第 {i} 列缺少必填欄位 {missing}，略過。", file=sys.stderr)
                continue
            orders.append({k: v.strip() for k, v in row.items()})
    return orders


def _csv_row_to_api_order(row: dict, sender: dict) -> dict:
    # SenderZipCode must be >= 6 chars; pad with zeros if shorter
    zipcode = str(sender.get("zipcode", "")).strip()
    zipcode = zipcode.ljust(6, "0")

    # SenderMobile: optional; leave empty if not a mobile number
    sender_mobile = str(sender.get("mobile", "")).strip()
    if sender_mobile and not sender_mobile.startswith("09"):
        sender_mobile = ""  # landline not accepted as mobile

    # 空白或規格書沒有的代碼（如舊版的 03）一律送「不指定」，不把無效值丟給 API
    delivery_time = str(row.get("delivery_time") or "").strip()
    if delivery_time not in VALID_DELIVERY_TIMES:
        delivery_time = DEFAULT_DELIVERY_TIME

    is_collection = row.get("is_collection") or "N"
    if is_collection.startswith("Y"):
        is_collection = "Y"
    else:
        is_collection = "N"

    # 沒有代收時金額一律送 0（否則黑貓回 E037）；有代收時去掉千分位逗號
    collection_amount = "0"
    if is_collection == "Y":
        collection_amount = str(row.get("collection_amount") or "0").strip().replace(",", "") or "0"

    return {
        "OBTNumber": "",
        "OrderId": str(row["order_id"]).strip(),
        "Thermosphere": row.get("thermosphere") or "0001",
        "Spec": row.get("spec") or "0001",
        "ReceiptLocation": "01",
        "RecipientName": row["recipient_name"],
        "RecipientTel": row.get("recipient_phone") or row.get("recipient_mobile", ""),
        "RecipientMobile": row.get("recipient_mobile") or "",
        "RecipientAddress": row["recipient_address"],
        "SenderName": sender["name"],
        "SenderTel": sender["tel"],
        "SenderMobile": sender_mobile,
        "SenderZipCode": zipcode,
        "SenderAddress": sender["address"],
        "ShipmentDate": row.get("shipment_date") or default_shipment_date(),
        "DeliveryDate": row.get("delivery_date") or default_delivery_date(),
        "DeliveryTime": delivery_time,
        "IsFreight": "Y" if str(row.get("is_freight", "N")).upper().startswith("Y") else "N",
        "IsCollection": is_collection,
        "IsSwipe": "N",
        "IsDeclare": "N",
        "ProductTypeId": FIXED_PRODUCT_TYPE_ID,
        "ProductName": row.get("product_name") or "一般物品",
        # 備註欄位名是 Memo（規格書 String(100)）；送 Remark 會被 API 靜默忽略、託運單印不出備註
        "Memo": row.get("notes") or "",
        "CollectionAmount": collection_amount,
    }


def create_orders(client: SudaClient, orders: list[dict], sender: dict, output_dir: str = ".") -> list[dict]:
    """
    批次建立寄件單。
    每筆成功時儲存 PDF 至 output_dir，並回傳結果清單。
    """
    results = []
    for i, row in enumerate(orders, start=1):
        order_id = row["order_id"]
        print(f"[Create] ({i}/{len(orders)}) 訂單 {order_id} - {row['recipient_name']}")

        problems = validate_order(row)
        if problems:
            # 不送出，直接回報；避免黑貓退件後才知道原因
            results.append({
                "order_id": order_id,
                "success": False,
                "obt_number": "",
                "pdf_path": "",
                "message": "資料檢查未通過：" + " ".join(problems),
            })
            continue

        api_order = _csv_row_to_api_order(row, sender)
        resp = client.print_obt([api_order])

        if resp.get("IsOK") == "Y":
            data = resp.get("Data") or {}
            # PrintOBT response: Data.Orders[0].OBTNumber + Data.FileNo
            orders_list = data.get("Orders") or []
            obt_number = orders_list[0].get("OBTNumber", "") if orders_list else ""
            file_no = data.get("FileNo", "")

            pdf_path = ""
            if file_no:
                try:
                    pdf_bytes = client.download_obt(file_no)
                    pdf_path = str(Path(output_dir) / f"{order_id}_{obt_number}.pdf")
                    with open(pdf_path, "wb") as f:
                        f.write(pdf_bytes)
                    print(f"[PDF] 已儲存：{pdf_path}")
                except Exception as e:
                    print(f"[WARN] PDF 下載失敗：{e}", file=sys.stderr)

            results.append({
                "order_id": order_id,
                "success": True,
                "obt_number": obt_number,
                "file_no": file_no,
                "pdf_path": pdf_path,
                "message": "成功",
            })
        else:
            results.append({
                "order_id": order_id,
                "success": False,
                "obt_number": "",
                "pdf_path": "",
                "message": explain_error(resp.get("Message", "未知錯誤")),
            })

    return results


def print_create_results(results: list[dict]) -> None:
    ok = sum(1 for r in results if r["success"])
    fail = len(results) - ok
    print(f"\n建單結果：{ok} 成功，{fail} 失敗")
    for r in results:
        icon = "✓" if r["success"] else "✗"
        obt = f"  OBT: {r['obt_number']}" if r["obt_number"] else ""
        print(f"  {icon} {r['order_id']}{obt}  {r['message']}")
