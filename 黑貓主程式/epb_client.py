"""
EPB 調撥查詢模組 — 連線 EPBrowser ERP，讀取本門市待出貨調撥單。

只讀不寫。需在可連到 192.168.1.177:8080 的內網機器上使用。

使用前請先呼叫 epb_available() 確認環境，或執行 explore_transfer_schema()
確認 STATUS_FLG / MOVE_FLG 實際碼值（locked in shell.jar，無法靜態確認）。
"""

import csv
import os
import socket
import subprocess
from pathlib import Path

_DIR = Path(__file__).resolve().parent

JAVA = "/Library/Java/JavaVirtualMachines/jdk1.8.0_251.jdk/Contents/Home/jre/bin/java"
JAVAC = "/Library/Java/JavaVirtualMachines/jdk1.8.0_251.jdk/Contents/Home/bin/javac"
JAVA_CP = f"{_DIR}:/Library/EPBrowser/EPB/Shell/lib/*:/Library/EPBrowser/EPB/Shell/shell.jar"

EPB_HOST = "192.168.1.177"
EPB_PORT = 8080
ORG_ID = "01"


def epb_available() -> bool:
    """True 只有在 JDK 1.8、EPBrowser lib、SOAP endpoint 三者都可用時才回傳。"""
    if not Path(JAVA).exists():
        return False
    if not Path("/Library/EPBrowser/EPB/Shell/shell.jar").exists():
        return False
    try:
        with socket.create_connection((EPB_HOST, EPB_PORT), timeout=3):
            pass
    except OSError:
        return False
    return True


def _compile_java() -> None:
    source = _DIR / "EPBReportQuery.java"
    target = _DIR / "EPBReportQuery.class"
    if target.exists() and target.stat().st_mtime >= source.stat().st_mtime:
        return
    proc = subprocess.run(
        [JAVAC, "-cp", JAVA_CP, str(source)],
        cwd=str(_DIR), text=True, capture_output=True, timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"EPBReportQuery 編譯失敗：{proc.stderr.strip() or proc.stdout.strip()}")


def _run_remote(sql: str, timeout: int = 60) -> tuple[list, list]:
    _compile_java()
    proc = subprocess.run(
        [
            JAVA,
            "-Dsun.net.client.defaultConnectTimeout=5000",
            "-Dsun.net.client.defaultReadTimeout=30000",
            "-cp", JAVA_CP,
            "EPBReportQuery", sql,
        ],
        cwd=str(_DIR), text=True, capture_output=True, timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip() or "EPB 查詢失敗（無錯誤訊息）")
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    if not lines:
        return [], []
    reader = csv.reader(lines, delimiter="\t")
    rows = list(reader)
    return rows[0], rows[1:]


def _q(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def explore_transfer_schema() -> str:
    """
    步驟 1.5 探查用。在內網機執行，印出 storedtl/storemas 欄位與
    近期 MOVE_FLG 碼值分佈，供確認「待出貨」的正確過濾條件。

    用法：
        python3 -c "import epb_client; print(epb_client.explore_transfer_schema())"
    """
    results = []

    col_sql = """
select column_name, data_type
from information_schema.columns
where table_name in ('storedtl', 'storemas')
order by table_name, ordinal_position
"""
    try:
        h, rows = _run_remote(col_sql, timeout=30)
        results.append("=== storedtl / storemas columns ===")
        for r in rows:
            results.append("\t".join(r))
    except Exception as exc:
        results.append(f"[欄位查詢失敗] {exc}")

    flg_sql = f"""
select move_flg, src_code, count(*) as cnt
from storedtl
where org_id = {_q(ORG_ID)}
group by move_flg, src_code
order by cnt desc
"""
    try:
        h, rows = _run_remote(flg_sql, timeout=30)
        results.append("\n=== storedtl move_flg / src_code distribution ===")
        results.append("\t".join(h))
        for r in rows:
            results.append("\t".join(r))
    except Exception as exc:
        results.append(f"[FLAG 查詢失敗] {exc}")

    sample_sql = f"""
select *
from (
  select *
  from storedtl
  where org_id = {_q(ORG_ID)}
  order by doc_date desc, src_doc_id desc
)
where rownum <= 5
"""
    try:
        h, rows = _run_remote(sample_sql, timeout=30)
        results.append("\n=== storedtl sample (5 rows) ===")
        results.append("\t".join(h))
        for r in rows:
            results.append("\t".join(r))
    except Exception as exc:
        results.append(f"[樣本查詢失敗] {exc}")

    return "\n".join(results)


def query_pending_transfers(src_store_id: str) -> list[dict]:
    """
    回傳「出庫門市 = src_store_id、尚未建過黑貓單」的調撥單清單。

    ⚠️  MOVE_FLG = 'A' 是依 storedtl 欄位說明推測的「待出貨」碼值。
    在正式使用前請先跑 explore_transfer_schema() 確認實際碼值。

    回傳格式（每筆一個 dict）：
      doc_id       : 調撥單號 (SRC_DOC_ID)
      src_store_id : 出庫門市代碼
      to_store_id  : 入庫門市代碼
      to_store_name: 入庫門市名稱
      doc_date     : 單據日期（字串）
      item_count   : 品項數量
      total_qty    : 總數量
      move_flg     : MOVE_FLG 原始值（供除錯）
    """
    sql = f"""
select
  d.src_doc_id,
  d.store_id,
  d.to_store_id,
  coalesce(sm.name, d.to_store_id) as to_store_name,
  max(cast(d.doc_date as varchar(20))) as doc_date,
  sum(d.stk_qty) as total_qty,
  count(*) as item_count,
  d.move_flg
from storedtl d
left join storemas sm
  on sm.store_id = d.to_store_id
  and sm.org_id = {_q(ORG_ID)}
where d.org_id = {_q(ORG_ID)}
  and d.store_id = {_q(src_store_id)}
  and d.move_flg = 'A'
group by d.src_doc_id, d.store_id, d.to_store_id, sm.name, d.move_flg
order by max(d.doc_date) desc, d.src_doc_id desc
"""
    headers, rows = _run_remote(sql)
    header_map = {h.upper(): i for i, h in enumerate(headers)}

    def get(row, col):
        i = header_map.get(col.upper())
        return row[i].strip() if i is not None and i < len(row) else ""

    result = []
    for row in rows:
        result.append({
            "doc_id":        get(row, "SRC_DOC_ID"),
            "src_store_id":  get(row, "STORE_ID"),
            "to_store_id":   get(row, "TO_STORE_ID"),
            "to_store_name": get(row, "TO_STORE_NAME"),
            "doc_date":      get(row, "DOC_DATE")[:10],
            "item_count":    get(row, "ITEM_COUNT"),
            "total_qty":     get(row, "TOTAL_QTY"),
            "move_flg":      get(row, "MOVE_FLG"),
        })
    return result


def query_transfer_items(doc_id: str) -> list[dict]:
    """回傳單一調撥單的品項明細（STK_ID, STK_NAME, STK_QTY）。"""
    sql = f"""
select stk_id, stk_name, stk_qty
from storedtl
where org_id = {_q(ORG_ID)}
  and src_doc_id = {_q(doc_id)}
order by stk_id
"""
    headers, rows = _run_remote(sql)
    header_map = {h.upper(): i for i, h in enumerate(headers)}

    def get(row, col):
        i = header_map.get(col.upper())
        return row[i].strip() if i is not None and i < len(row) else ""

    return [
        {
            "stk_id":   get(row, "STK_ID"),
            "stk_name": get(row, "STK_NAME"),
            "stk_qty":  get(row, "STK_QTY"),
        }
        for row in rows
    ]
