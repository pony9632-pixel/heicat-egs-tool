#!/usr/bin/env python3
"""
黑貓（統一速達）EGS API 自動化工具

Commands:
  test                            測試 API 連線
  create-order -f orders.csv      批次建立寄件單（產生 PDF）
  create-order --template         產生 CSV 範本
  cancel     -n OBT號碼[,...]     取消託運單
  download   --file-no XXXXX      下載已建立的 PDF

Setup:
  pip3 install -r requirements.txt
  編輯 config.yaml 填入帳號、API 授權碼、寄件人資料
"""

import argparse
import json
import sys
from pathlib import Path

import yaml

from api_client import SudaClient, save_pdf
from order import create_orders, load_orders, generate_template, print_create_results


def load_config(path: str = "config.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_args():
    parser = argparse.ArgumentParser(
        description="黑貓 EGS API 工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--config", default="config.yaml", help="設定檔路徑")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("test", help="測試 API 連線與授權碼")

    co = sub.add_parser("create-order", help="批次建立寄件單")
    co_src = co.add_mutually_exclusive_group(required=True)
    co_src.add_argument("-f", "--file", help="訂單 CSV 檔案")
    co_src.add_argument("--template", action="store_true", help="產生空白 CSV 範本後離開")
    co.add_argument("-o", "--output-dir", default=".", help="PDF 儲存目錄（預設當前目錄）")

    ca = sub.add_parser("cancel", help="取消託運單")
    ca.add_argument("-n", "--numbers", required=True, help="OBT 號碼，逗號分隔")

    dl = sub.add_parser("download", help="下載 PDF")
    dl.add_argument("--file-no", required=True, help="PrintOBT 回傳的 FileNo")
    dl.add_argument("-o", "--output", default="obt.pdf", help="儲存路徑")

    return parser.parse_args()


def run(args):
    if args.command == "create-order" and args.template:
        generate_template()
        return

    cfg = load_config(args.config)
    client = SudaClient(
        customer_id=str(cfg["username"]),
        customer_token=cfg["api_token"],
    )
    sender = cfg.get("sender", {})

    if args.command == "test":
        # Send minimal invalid request — API will respond with field errors = connection works
        resp = client.print_obt([])
        if "SrvTranId" in resp:
            print(f"[OK] API 連線正常。SrvTranId: {resp['SrvTranId']}")
            print(f"     訊息：{resp.get('Message','')}")
        else:
            print(f"[FAIL] 意外回應：{resp}", file=sys.stderr)

    elif args.command == "create-order":
        if not sender:
            print("[ERROR] config.yaml 缺少 sender 寄件人設定，請參考 config.yaml 範本。", file=sys.stderr)
            sys.exit(1)
        orders = load_orders(args.file)
        if not orders:
            print("CSV 中沒有有效訂單。", file=sys.stderr)
            return
        Path(args.output_dir).mkdir(parents=True, exist_ok=True)
        results = create_orders(client, orders, sender, output_dir=args.output_dir)
        print_create_results(results)

    elif args.command == "cancel":
        numbers = [n.strip() for n in args.numbers.split(",") if n.strip()]
        resp = client.cancel_obt(numbers)
        if resp.get("IsOK") == "Y":
            print(f"[OK] 取消成功：{numbers}")
        else:
            print(f"[FAIL] {resp.get('Message')}", file=sys.stderr)

    elif args.command == "download":
        pdf_bytes = client.download_obt(args.file_no)
        with open(args.output, "wb") as f:
            f.write(pdf_bytes)
        print(f"[OK] PDF 已儲存：{args.output}")


def main():
    args = parse_args()
    run(args)


if __name__ == "__main__":
    main()
