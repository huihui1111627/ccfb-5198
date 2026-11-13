"""Excel 导出。"""
from __future__ import annotations

import io
import sqlite3

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill("solid", fgColor="D9E1F2")
HEADER_FONT = Font(bold=True)


def _style_sheet(ws, widths: list[int]) -> None:
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for cell in ws[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center")


def export_quotes(conn: sqlite3.Connection, start: str, end: str,
                  market_code: str | None = None, variety_code: str | None = None) -> bytes:
    sql = (
        "SELECT q.quote_date, m.name AS market_name, v.name AS variety_name, v.category, "
        "q.raw_name, q.raw_price, q.raw_unit, q.price_per_kg, q.origin, q.grade "
        "FROM quotes q JOIN markets m ON m.code=q.market_code "
        "JOIN varieties v ON v.code=q.variety_code WHERE q.quote_date BETWEEN ? AND ?"
    )
    params: list = [start, end]
    if market_code:
        sql += " AND q.market_code=?"
        params.append(market_code)
    if variety_code:
        sql += " AND q.variety_code=?"
        params.append(variety_code)
    sql += " ORDER BY q.quote_date, q.market_code, v.name"
    rows = conn.execute(sql, params).fetchall()

    wb = Workbook()
    ws = wb.active
    ws.title = "行情明细"
    headers = ["日期", "市场", "标准品种", "品类", "市场品名", "原始价",
               "原始单位", "归一价(元/公斤)", "产地", "等级"]
    ws.append(headers)
    for r in rows:
        ws.append(list(r))
    _style_sheet(ws, [12, 18, 12, 10, 14, 10, 10, 16, 12, 8])

    # 第二张表：区间市场均价对比
    ws2 = wb.create_sheet("市场均价对比")
    ws2.append(["标准品种", "市场", "均价(元/公斤)", "最低价", "最高价", "样本数"])
    agg = conn.execute(
        "SELECT v.name AS variety_name, m.name AS market_name, "
        "ROUND(AVG(q.price_per_kg),2), ROUND(MIN(q.price_per_kg),2), "
        "ROUND(MAX(q.price_per_kg),2), COUNT(*) "
        "FROM quotes q JOIN markets m ON m.code=q.market_code "
        "JOIN varieties v ON v.code=q.variety_code WHERE q.quote_date BETWEEN ? AND ?"
        + (" AND q.market_code=?" if market_code else "")
        + (" AND q.variety_code=?" if variety_code else "")
        + " GROUP BY q.variety_code, q.market_code ORDER BY v.name, AVG(q.price_per_kg)",
        params,
    ).fetchall()
    for r in agg:
        ws2.append(list(r))
    _style_sheet(ws2, [14, 18, 14, 10, 10, 8])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
