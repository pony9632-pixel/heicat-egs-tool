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
    spec               尺寸：0060/0080/0100/0120/0140/0160（預設 0060）
    thermosphere       溫層：0001 常溫 / 0002 冷藏 / 0003 冷凍（預設 0001）
    delivery_time      配送時段：01 不指定 / 02 上午 / 03 下午 / 04 晚上（預設 01）
    shipment_date      出貨日 YYYYMMDD（預設今天）
    delivery_date      指定配送日 YYYYMMDD（預設明天）
    product_name       貨品名稱（預設「一般物品」）
    is_collection      代收貨款 Y/N（預設 N）
    collection_amount  代收金額（is_collection=Y 時填）
    notes              備註
"""

import csv
import sys
from pathlib import Path

from api_client import SudaClient, save_pdf, default_shipment_date, default_delivery_date


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
            "delivery_time": "01",
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

    is_collection = row.get("is_collection") or "N"
    if is_collection.startswith("Y"):
        is_collection = "Y"
    else:
        is_collection = "N"

    return {
        "OBTNumber": "",
        "OrderId": row["order_id"],
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
        "DeliveryTime": row.get("delivery_time") or "01",
        "IsFreight": "Y" if str(row.get("is_freight", "N")).upper().startswith("Y") else "N",
        "IsCollection": is_collection,
        "IsSwipe": "N",
        "IsDeclare": "N",
        "ProductTypeId": FIXED_PRODUCT_TYPE_ID,
        "ProductName": row.get("product_name") or "一般物品",
        "Remark": row.get("notes") or "",
        "CollectionAmount": row.get("collection_amount") or "0",
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
                "message": resp.get("Message", "未知錯誤"),
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
