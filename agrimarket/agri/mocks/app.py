"""三个 mock 市场的 Flask 应用。

A 华东果菜：分页 HTML 表格，单位 元/公斤
B 城南农贸：数据藏在页面 JS 变量里（不执行 JS 拿不到），单位 元/斤
C 北环批发：每日 Excel 报价单下载，箱/件计价
"""
from __future__ import annotations

import io
import json
from datetime import date, datetime, timedelta

from flask import Flask, Response, abort, request
from openpyxl import Workbook

from ..config import WINDOW_START
from ..mockdata import MARKET_C_PACKING, is_open, quotes_for

PAGE_STYLE = """
<style>
body{font-family:"PingFang SC",sans-serif;margin:24px;color:#222}
h1{font-size:20px} table{border-collapse:collapse;margin-top:12px}
th,td{border:1px solid #999;padding:6px 12px;font-size:14px}
th{background:#f2f2f2} .pager a{margin-right:10px}
.notice{background:#fff4e0;border:1px solid #e0b860;padding:12px;display:inline-block}
a{color:#0a58ca}
</style>
"""


def _parse_date() -> date:
    raw = request.args.get("date")
    if raw:
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            abort(400, "日期格式应为 YYYY-MM-DD")
    return date.today()


def _closed_page(title: str, d: date, reason: str) -> str:
    return f"<html><head><meta charset='utf-8'><title>{title}</title>{PAGE_STYLE}</head>" \
        f"<body><h1>{title}</h1><div class='notice'>{d.isoformat()} {reason}，本日休市。</div></body></html>"


def _no_data_page(title: str, d: date) -> str:
    return f"<html><head><meta charset='utf-8'><title>{title}</title>{PAGE_STYLE}</head>" \
        f"<body><h1>{title}</h1><div class='notice'>{d.isoformat()} 暂无报价数据。</div></body></html>"


# ---------------------------------------------------------------- 市场 A：分页表格
def create_market_a() -> Flask:
    app = Flask("mock_market_a")
    PAGE_SIZE = 5

    @app.get("/")
    def home():
        return (
            f"<html><head><meta charset='utf-8'>{PAGE_STYLE}</head><body>"
            f"<h1>华东果菜批发市场 · 行情公示</h1>"
            f"<p>数据单位：元/公斤。<a href='/quotes?date={date.today().isoformat()}'>查看今日行情</a></p>"
            f"</body></html>"
        )

    @app.get("/quotes")
    def quotes():
        d = _parse_date()
        if not is_open("A", d):
            if d < WINDOW_START or d > date.today():
                return _no_data_page("华东果菜批发市场", d), 200
            return _closed_page("华东果菜批发市场", d, "休市"), 200
        rows = quotes_for("A", d)
        total = len(rows)
        pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        page = max(1, min(pages, request.args.get("page", default=1, type=int)))
        chunk = rows[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
        trs = "".join(
            f"<tr><td>{q.item_name}</td><td>{q.origin}</td><td>{q.grade}</td>"
            f"<td>{q.raw_price:.2f}</td><td>{q.raw_unit}</td></tr>"
            for q in chunk
        )
        links = []
        for p in range(1, pages + 1):
            label = f"[{p}]" if p == page else str(p)
            links.append(f"<a href='/quotes?date={d.isoformat()}&page={p}'>{label}</a>")
        return (
            f"<html><head><meta charset='utf-8'><title>华东果菜 {d} 行情</title>{PAGE_STYLE}</head>"
            f"<body><h1>华东果菜批发市场 · {d.isoformat()} 行情</h1>"
            f"<p>共 {total} 条，第 {page}/{pages} 页</p>"
            f"<table><thead><tr><th>品名</th><th>产地</th><th>等级</th>"
            f"<th>均价</th><th>计价单位</th></tr></thead><tbody>{trs}</tbody></table>"
            f"<div class='pager'>{''.join(links)}</div></body></html>"
        )

    return app


# ---------------------------------------------------------------- 市场 B：JS 变量
def create_market_b() -> Flask:
    app = Flask("mock_market_b")

    @app.get("/")
    def home():
        return (
            f"<html><head><meta charset='utf-8'>{PAGE_STYLE}</head><body>"
            f"<h1>城南农贸批发市场 · 今日菜价</h1>"
            f"<p><a href='/quotes?date={date.today().isoformat()}'>进入行情看板</a></p>"
            f"</body></html>"
        )

    @app.get("/quotes")
    def quotes():
        d = _parse_date()
        if not is_open("B", d):
            if d < WINDOW_START or d > date.today():
                return _no_data_page("城南农贸批发市场", d), 200
            return _closed_page("城南农贸批发市场", d, "休市"), 200
        payload = {
            "market": "城南农贸批发市场",
            "date": d.isoformat(),
            "unit": "元/斤",
            "rows": [q.to_dict() for q in quotes_for("B", d)],
        }
        data_json = json.dumps(payload, ensure_ascii=False)
        # 页面 body 为空，数据只存在 JS 变量里，由前端脚本渲染 —— 必须上 Playwright
        render_js = (
            "const d=window.__PRICE_DATA__;"
            "const head='<tr><th>品名</th><th>产地</th><th>等级</th><th>价格</th><th>单位</th></tr>';"
            "const body=d.rows.map(r=>'<tr><td>'+r.item_name+'</td><td>'+r.origin+'</td>'+"
            "'<td>'+r.grade+'</td><td>'+r.raw_price.toFixed(2)+'</td><td>'+r.raw_unit+'</td></tr>').join('');"
            "document.getElementById('board').innerHTML="
            "'<p>计价单位：'+d.unit+'</p><table><thead>'+head+'</thead><tbody>'+body+'</tbody></table>';"
        )
        return (
            f"<html><head><meta charset='utf-8'><title>城南农贸 {d} 行情看板</title>{PAGE_STYLE}</head>"
            f"<body><h1>城南农贸批发市场 · 行情看板</h1><div id='board'>加载中...</div>"
            f"<script>window.__PRICE_DATA__ = {data_json};</script>"
            f"<script>{render_js}</script></body></html>"
        )

    return app


# ---------------------------------------------------------------- 市场 C：Excel 报价单
def create_market_c() -> Flask:
    app = Flask("mock_market_c")

    @app.get("/")
    def home():
        d = date.today()
        avail = is_open("C", d)
        link = (
            f"<a href='/download?date={d.isoformat()}'>下载今日报价单（.xlsx）</a>"
            if avail else f"<span class='notice'>{d.isoformat()} 休市，无报价单</span>"
        )
        # 给采集器一个最近 5 天的清单
        items = []
        cur = d
        for _ in range(7):
            if is_open("C", cur):
                items.append(
                    f"<li>{cur.isoformat()} <a href='/download?date={cur.isoformat()}'>报价单下载</a></li>"
                )
            cur -= timedelta(days=1)
        return (
            f"<html><head><meta charset='utf-8'>{PAGE_STYLE}</head><body>"
            f"<h1>北环批发市场 · 每日报价单</h1><p>{link}</p>"
            f"<h3>近期报价单</h3><ul>{''.join(items)}</ul></body></html>"
        )

    @app.get("/download")
    def download():
        d = _parse_date()
        if not is_open("C", d):
            return _closed_page("北环批发市场", d, "休市"), 404
        rows = quotes_for("C", d)

        wb = Workbook()
        ws = wb.active
        ws.title = "报价单"
        ws.append(["北环批发市场行情报价单"])
        ws.append(["报价日期", d.isoformat()])
        ws.append([])
        ws.append(["序号", "品名", "产地", "等级", "包装", "报价", "计价单位"])
        for i, q in enumerate(rows, start=1):
            pack_unit, spec_kg = MARKET_C_PACKING[q.variety]
            ws.append([i, q.item_name, q.origin, q.grade, f"{spec_kg:g}公斤/{pack_unit}",
                       q.raw_price, q.raw_unit])
        ws.append([])
        ws.append(["备注：报价为整箱/整件价，规格见包装列。"])

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        fname = f"beihuan_{d.isoformat()}.xlsx"
        return Response(
            buf.getvalue(),
            headers={
                "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "Content-Disposition": f"attachment; filename={fname}",
            },
        )

    return app


APPS = {
    "A": create_market_a,
    "B": create_market_b,
    "C": create_market_c,
}
