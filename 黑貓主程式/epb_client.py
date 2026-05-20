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


def _run_remote(sql: str, timeout: int = 180) -> tuple[list, list]:
    _compile_java()
    # Java read timeout = Python timeout − 5s buffer (避免 Python 先 kill 沒拿到 Java 訊息)
    java_read_ms = max(30000, (timeout - 5) * 1000)
    proc = subprocess.run(
        [
            JAVA,
            "-Dsun.net.client.defaultConnectTimeout=5000",
            f"-Dsun.net.client.defaultReadTimeout={java_read_ms}",
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

    # 1. 欄位 — 試多種 schema view（PostgreSQL 風 / Oracle 風）
    schema_attempts = [
        ("user_tab_columns",
         "select table_name, column_name, data_type from user_tab_columns "
         "where lower(table_name) in ('storedtl','storemas') "
         "order by table_name, column_id"),
        ("all_tab_columns",
         "select table_name, column_name, data_type from all_tab_columns "
         "where lower(table_name) in ('storedtl','storemas') "
         "order by table_name, column_id"),
        ("information_schema",
         "select table_name, column_name, data_type from information_schema.columns "
         "where lower(table_name) in ('storedtl','storemas') "
         "order by table_name, ordinal_position"),
    ]
    for name, sql in schema_attempts:
        try:
            h, rows = _run_remote(sql, timeout=60)
            if rows:
                results.append(f"=== columns from {name} ({len(rows)} rows) ===")
                results.append("\t".join(h))
                for r in rows:
                    results.append("\t".join(r))
                break
            else:
                results.append(f"[{name}] 查無資料")
        except Exception as exc:
            results.append(f"[{name}] 失敗：{str(exc)[:120]}")

    # 2. MOVE_FLG / SRC_CODE 分佈 — 限近 90 天，避免全表掃描
    flg_sql = f"""
select move_flg, src_code, count(*) as cnt
from storedtl
where org_id = {_q(ORG_ID)}
  and doc_date >= sysdate - 90
group by move_flg, src_code
order by cnt desc
"""
    try:
        h, rows = _run_remote(flg_sql, timeout=180)
        results.append("\n=== move_flg / src_code 分佈（近 90 天）===")
        results.append("\t".join(h))
        for r in rows:
            results.append("\t".join(r))
    except Exception as exc:
        results.append(f"[FLAG 查詢失敗] {str(exc)[:160]}")

    # 3. 樣本 — 限近 30 天前 5 筆
    sample_sql = f"""
select *
from (
  select *
  from storedtl
  where org_id = {_q(ORG_ID)}
    and doc_date >= sysdate - 30
  order by doc_date desc, src_doc_id desc
)
where rownum <= 5
"""
    try:
        h, rows = _run_remote(sample_sql, timeout=180)
        results.append("\n=== storedtl 樣本（近 30 天，前 5 筆）===")
        results.append("\t".join(h))
        for r in rows:
            results.append("\t".join(r))
    except Exception as exc:
        results.append(f"[樣本查詢失敗] {str(exc)[:160]}")

    return "\n".join(results)


def explore_pending_transfers(src_store_id: str = "") -> str:
    """
    第二輪探查：找出「待出貨」對應的表頭表 + 狀態碼。

    1. storedtl.status_flg / store_status_flg 分佈（近 90 天，限 SRC_CODE=INVTRNTN 標準調撥）
    2. 試找 INVTRN 表頭表：invtrnn / invtrntn / invtrnhd / invtrntnhd
    3. 抓一筆有 TO_STORE_ID 的真實調撥樣本

    用法：
        python3 -c "import epb_client; print(epb_client.explore_pending_transfers('004'))"
        # 傳入本門市代碼，沒傳就不過濾 store_id
    """
    results = []
    store_filter = (f"and store_id = {_q(src_store_id)}" if src_store_id else "")

    # 1. status_flg 分佈（限定標準調撥 INVTRNTN）
    s_sql = f"""
select status_flg, store_status_flg, move_flg, count(*) as cnt
from storedtl
where org_id = {_q(ORG_ID)}
  and src_code = 'INVTRNTN'
  and doc_date >= sysdate - 90
  {store_filter}
group by status_flg, store_status_flg, move_flg
order by cnt desc
"""
    try:
        h, rows = _run_remote(s_sql, timeout=180)
        results.append(f"=== storedtl status 分佈（SRC_CODE=INVTRNTN，{src_store_id or '全店'}，近 90 天）===")
        results.append("\t".join(h))
        for r in rows:
            results.append("\t".join(r))
    except Exception as exc:
        results.append(f"[status 查詢失敗] {str(exc)[:160]}")

    # 2. 找 INVTRN 表頭表 — 試多個候選表名
    candidates = ["invtrnn", "invtrntn", "invtrnhd", "invtrntnhd", "invtrn_h", "invtrnhead"]
    found = []
    for tname in candidates:
        try:
            h, rows = _run_remote(
                f"select count(*) from {tname} where org_id = {_q(ORG_ID)} and rownum <= 1",
                timeout=30)
            if rows:
                found.append(tname)
        except Exception:
            pass
    results.append(f"\n=== INVTRN 表頭表存在偵測 ===\n找到：{found if found else '(無)'}")

    # 對找到的表跑欄位 + status 分佈
    for tname in found:
        try:
            h, rows = _run_remote(
                f"select column_name, data_type from user_tab_columns "
                f"where table_name = upper({_q(tname)}) order by column_id", timeout=60)
            results.append(f"\n--- {tname} 欄位（{len(rows)} 個）---")
            for r in rows:
                results.append("\t".join(r))
        except Exception as exc:
            results.append(f"[{tname} 欄位] 失敗：{str(exc)[:120]}")

        try:
            h, rows = _run_remote(
                f"select status_flg, count(*) as cnt from {tname} "
                f"where org_id = {_q(ORG_ID)} group by status_flg order by cnt desc",
                timeout=120)
            results.append(f"\n--- {tname}.status_flg 分佈 ---")
            results.append("\t".join(h))
            for r in rows:
                results.append("\t".join(r))
        except Exception as exc:
            results.append(f"[{tname} status] 失敗：{str(exc)[:120]}")

    # 3. 真實調撥樣本（TO_STORE_ID 不為空）
    sample_sql = f"""
select *
from (
  select doc_id, doc_date, status_flg, store_status_flg, move_flg,
         store_id, to_store_id, src_code, src_doc_id, stk_id, stk_name, stk_qty
  from storedtl
  where org_id = {_q(ORG_ID)}
    and src_code in ('INVTRNTN','INVTRNN','INVTRNIN')
    and to_store_id is not null
    and to_store_id <> ' '
    and doc_date >= sysdate - 30
    {store_filter}
  order by doc_date desc, src_doc_id desc
)
where rownum <= 5
"""
    try:
        h, rows = _run_remote(sample_sql, timeout=180)
        results.append(f"\n=== 真實調撥樣本（TO_STORE_ID 非空，近 30 天，前 5 筆）===")
        results.append("\t".join(h))
        for r in rows:
            results.append("\t".join(r))
    except Exception as exc:
        results.append(f"[樣本查詢失敗] {str(exc)[:160]}")

    return "\n".join(results)


def explore_stores_and_tables() -> str:
    """
    第三輪探查：
    1. 列出所有 active 門市（讓使用者確認本店代碼）
    2. 列出 user_tables 中含 TRAN/INVTR 的表名（找真正的調撥表）
    3. 不過濾 store_id，找 5 筆 TO_STORE_ID 非空的調撥樣本
    4. storedtl 最新 5 筆紀錄（不過濾任何條件）

    用法：
        python3 -c "import epb_client; print(epb_client.explore_stores_and_tables())"
    """
    results = []

    # 1. 門市清單
    s_sql = f"""
select store_id, name, status_flg, address1, phone
from storemas
where org_id = {_q(ORG_ID)}
  and status_flg = 'A'
order by store_id
"""
    try:
        h, rows = _run_remote(s_sql, timeout=120)
        results.append(f"=== Active 門市清單（{len(rows)} 間）===")
        results.append("\t".join(h))
        for r in rows:
            results.append("\t".join(r))
    except Exception as exc:
        results.append(f"[門市清單] 失敗：{str(exc)[:160]}")

    # 2. 找含 TRAN/INVTR/TRANSFER/OUT/SHIP 的表名
    t_sql = """
select table_name
from user_tables
where upper(table_name) like '%TRAN%'
   or upper(table_name) like '%INVTR%'
   or upper(table_name) like '%TRANSFER%'
   or upper(table_name) like '%MOVE%'
   or upper(table_name) like '%INVOUT%'
   or upper(table_name) like '%INVIN%'
   or upper(table_name) like '%SHIP%'
order by table_name
"""
    candidate_tables = []
    try:
        h, rows = _run_remote(t_sql, timeout=60)
        results.append(f"\n=== user_tables 含 TRAN/INVTR/MOVE/SHIP 等的表（{len(rows)} 個）===")
        for r in rows:
            results.append("\t".join(r))
            candidate_tables.append(r[0].lower())
    except Exception as exc:
        results.append(f"[表名查詢] 失敗：{str(exc)[:160]}")

    # 2b. 對每張候選表跑 STATUS_FLG 分佈（前提：表內有 STATUS_FLG + STORE_ID 欄位）
    if candidate_tables:
        col_sql = f"""
select lower(table_name) as tname,
       max(case when column_name = 'STATUS_FLG'  then 'Y' end) as has_status,
       max(case when column_name = 'STORE_ID'    then 'Y' end) as has_store,
       max(case when column_name = 'TO_STORE_ID' then 'Y' end) as has_to_store,
       max(case when column_name = 'DOC_ID'      then 'Y' end) as has_doc_id,
       count(*) as col_count
from user_tab_columns
where lower(table_name) in ({','.join(_q(t) for t in candidate_tables)})
group by lower(table_name)
order by tname
"""
        try:
            h, rows = _run_remote(col_sql, timeout=60)
            results.append(f"\n=== 候選表欄位特徵（is_status/is_store/is_to_store/is_doc_id）===")
            results.append("\t".join(h))
            for r in rows:
                results.append("\t".join(r))
            # 對「同時有 STATUS_FLG + STORE_ID + TO_STORE_ID」的表跑 status 分佈
            for r in rows:
                tname = r[0]
                has_status, has_store, has_to_store = r[1], r[2], r[3]
                if has_status == 'Y' and has_store == 'Y' and has_to_store == 'Y':
                    try:
                        h2, rs2 = _run_remote(
                            f"select status_flg, count(*) as cnt "
                            f"from {tname} where org_id = {_q(ORG_ID)} "
                            f"group by status_flg order by cnt desc",
                            timeout=120)
                        results.append(f"\n--- {tname}.status_flg 分佈 ---")
                        results.append("\t".join(h2))
                        for rr in rs2:
                            results.append("\t".join(rr))
                    except Exception as exc:
                        results.append(f"[{tname} status] 失敗：{str(exc)[:120]}")
        except Exception as exc:
            results.append(f"[欄位特徵查詢] 失敗：{str(exc)[:160]}")

    # 3. storedtl 找 TO_STORE_ID 非空的（全店，不過濾 SRC_CODE）
    x_sql = f"""
select *
from (
  select src_code, src_doc_id, doc_date, status_flg, store_status_flg,
         move_flg, store_id, to_store_id, stk_id, stk_qty
  from storedtl
  where org_id = {_q(ORG_ID)}
    and to_store_id is not null
    and trim(to_store_id) <> ''
    and doc_date >= sysdate - 30
  order by doc_date desc, src_doc_id desc
)
where rownum <= 10
"""
    try:
        h, rows = _run_remote(x_sql, timeout=180)
        results.append(f"\n=== storedtl TO_STORE_ID 非空樣本（全店、近 30 天、前 10 筆）===")
        results.append("\t".join(h))
        for r in rows:
            results.append("\t".join(r))
    except Exception as exc:
        results.append(f"[樣本] 失敗：{str(exc)[:160]}")

    # 4. SRC_CODE 分佈（限有 TO_STORE_ID 的）— 找出真正的調撥 SRC_CODE
    sc_sql = f"""
select src_code, move_flg, count(*) as cnt
from storedtl
where org_id = {_q(ORG_ID)}
  and to_store_id is not null
  and trim(to_store_id) <> ''
  and doc_date >= sysdate - 90
group by src_code, move_flg
order by cnt desc
"""
    try:
        h, rows = _run_remote(sc_sql, timeout=180)
        results.append(f"\n=== 有 TO_STORE_ID 的 SRC_CODE 分佈（近 90 天）===")
        results.append("\t".join(h))
        for r in rows:
            results.append("\t".join(r))
    except Exception as exc:
        results.append(f"[SRC_CODE 分佈] 失敗：{str(exc)[:160]}")

    return "\n".join(results)


def explore_invtrntmas(src_store_id: str = "") -> str:
    """
    第四輪探查 — 鎖定 INVTRNTMAS（主要門市間調撥表頭）。

    1. 列出 INVTRNTMAS 全部欄位（找實際的 fr/to store 欄位名稱）
    2. INVTRNTMAS.status_flg 分佈（找「已確認/待出貨」對應的碼）
    3. INVTRNTLINE 全部欄位
    4. 抓 5 筆最新調撥單（可選依出庫店過濾，若給定 src_store_id 會在 SQL 試
       FR_STORE_ID / OUT_STORE_ID / STORE_ID / SRC_STORE_ID 等常見命名）

    用法：
        python3 -c "import epb_client; print(epb_client.explore_invtrntmas('SA004'))"
        # 不過濾傳 '' 即可
    """
    results = []

    for tname in ("invtrntmas", "invtrntline"):
        try:
            h, rows = _run_remote(
                f"select column_name, data_type from user_tab_columns "
                f"where table_name = upper({_q(tname)}) order by column_id", timeout=60)
            results.append(f"=== {tname} 全部欄位（{len(rows)} 個）===")
            for r in rows:
                results.append("\t".join(r))
        except Exception as exc:
            results.append(f"[{tname} 欄位] 失敗：{str(exc)[:160]}")
        results.append("")

    # INVTRNTMAS status_flg 分佈
    try:
        h, rows = _run_remote(
            f"select status_flg, count(*) as cnt from invtrntmas "
            f"where org_id = {_q(ORG_ID)} group by status_flg order by cnt desc",
            timeout=180)
        results.append("=== invtrntmas.status_flg 分佈（全部）===")
        results.append("\t".join(h))
        for r in rows:
            results.append("\t".join(r))
    except Exception as exc:
        results.append(f"[status_flg 分佈] 失敗：{str(exc)[:160]}")

    # 抓 5 筆最新調撥單表頭（全欄位）
    try:
        h, rows = _run_remote(
            f"select * from (select * from invtrntmas where org_id = {_q(ORG_ID)} "
            f"order by doc_date desc, doc_id desc) where rownum <= 5",
            timeout=180)
        results.append("\n=== invtrntmas 最新 5 筆樣本 ===")
        results.append("\t".join(h))
        for r in rows:
            results.append("\t".join(r))
    except Exception as exc:
        results.append(f"[invtrntmas 樣本] 失敗：{str(exc)[:160]}")

    # 抓對應的 invtrntline（最新 5 筆 doc_id 的明細）
    try:
        sub_sql = f"""
select line.*
from invtrntline line
where line.org_id = {_q(ORG_ID)}
  and (line.invtrnt_rec_key, line.line_no) in (
    select rec_key, 1 from (
      select rec_key from invtrntmas where org_id = {_q(ORG_ID)}
      order by doc_date desc, doc_id desc
    ) where rownum <= 5
  )
"""
        h, rows = _run_remote(sub_sql, timeout=180)
        results.append("\n=== invtrntline 對應明細（最新 5 張單，line_no=1）===")
        results.append("\t".join(h))
        for r in rows:
            results.append("\t".join(r))
    except Exception as exc:
        # 退而求其次：直接抓任意 5 筆 line
        try:
            h, rows = _run_remote(
                f"select * from (select * from invtrntline where org_id = {_q(ORG_ID)} "
                f"order by rec_key desc) where rownum <= 5",
                timeout=180)
            results.append("\n=== invtrntline 最新 5 筆樣本（無關聯查詢）===")
            results.append("\t".join(h))
            for r in rows:
                results.append("\t".join(r))
        except Exception as exc2:
            results.append(f"[invtrntline 樣本] 失敗：{str(exc2)[:160]}")

    return "\n".join(results)


def explore_status_samples() -> str:
    """
    第五輪 — 抓 STATUS_FLG = 'A' 和 'B' 的調撥單樣本各 5 筆，
    方便對照 EPB 介面看哪個對應「已確認、待出貨」。

    用法：
        python3 -c "import epb_client; print(epb_client.explore_status_samples())"
    """
    results = []

    for flg in ("A", "B"):
        # 表頭樣本
        try:
            h, rows = _run_remote(f"""
select * from (
  select doc_id, doc_date, status_flg, store_id1, store_id2, total_qty,
         post_date, invtrn_flg, print_flg, address1, phone, remark,
         create_date, lastupdate
  from invtrntmas
  where org_id = {_q(ORG_ID)} and status_flg = {_q(flg)}
  order by doc_date desc, doc_id desc
) where rownum <= 5
""", timeout=120)
            results.append(f"=== STATUS_FLG = '{flg}' 表頭樣本（前 5 筆）===")
            results.append("\t".join(h))
            for r in rows:
                results.append("\t".join(r))
        except Exception as exc:
            results.append(f"[{flg} 表頭樣本] 失敗：{str(exc)[:160]}")
        results.append("")

        # 對應明細（用正確的 JOIN：line.mas_rec_key = mas.rec_key）
        try:
            h, rows = _run_remote(f"""
select * from (
  select m.doc_id, m.status_flg, m.store_id1, m.store_id2,
         l.line_no, l.stk_id, l.name, l.stk_qty
  from invtrntmas m
  join invtrntline l on l.mas_rec_key = m.rec_key
  where m.org_id = {_q(ORG_ID)} and m.status_flg = {_q(flg)}
  order by m.doc_date desc, m.doc_id desc, l.line_no
) where rownum <= 10
""", timeout=120)
            results.append(f"--- STATUS_FLG = '{flg}' 對應明細（前 10 行）---")
            results.append("\t".join(h))
            for r in rows:
                results.append("\t".join(r))
        except Exception as exc:
            results.append(f"[{flg} 明細樣本] 失敗：{str(exc)[:160]}")
        results.append("")

    # 額外：你那台機是哪個門市？看最近一週本機 ip 對應的 user 出過什麼單
    # （略，因為這需要登入資訊）

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
