"""市场 C：下载每日 Excel 报价单，openpyxl 解析；箱/件价格交给 units 层按规格换算。"""
from __future__ import annotations

import io
from datetime import date

import httpx
from openpyxl import load_workbook

from .base import BaseCollector, CollectorError, MarketClosed, RawQuote


class MarketCCollector(BaseCollector):
    def fetch(self, d: date) -> list[RawQuote]:
        try:
            with httpx.Client(timeout=20, follow_redirects=True) as client:
                resp = client.get(
                    f"{self.base_url}/download", params={"date": d.isoformat()}
                )
                if resp.status_code == 404:
                    if "休市" in resp.text:
                        raise MarketClosed(f"{d.isoformat()} 休市，无报价单")
                    raise CollectorError(f"市场C报价单不存在(404): {d.isoformat()}")
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise CollectorError(f"市场C下载失败: {exc}") from exc

        try:
            wb = load_workbook(io.BytesIO(resp.content), data_only=True, read_only=True)
            ws = wb.active
        except Exception as exc:
            raise CollectorError(f"市场C Excel 无法打开: {exc}") from exc

        out: list[RawQuote] = []
        header_seen = False
        col = {}
        for row in ws.iter_rows(values_only=True):
            cells = [c for c in row if c is not None]
            if not cells:
                continue
            if cells and str(cells[0]).startswith("序号"):
                header_seen = True
                col = {str(name).strip(): i for i, name in enumerate(row) if name is not None}
                continue
            if not header_seen:
                continue
            # 跳过备注、表尾等非数据行：必须同时有品名和数字报价
            name_idx = col.get("品名")
            price_idx = col.get("报价")
            if name_idx is None or price_idx is None:
                continue
            if name_idx >= len(row) or row[name_idx] is None:
                continue
            try:
                raw_price = float(row[price_idx])
            except (TypeError, ValueError):
                continue
            item_name = str(row[name_idx]).strip()
            raw_unit = str(row[col["计价单位"]]).strip()
            origin = str(row[col["产地"]] or "").strip() if "产地" in col else ""
            grade = str(row[col["等级"]] or "").strip() if "等级" in col else ""
            packing = str(row[col["包装"]] or "").strip() if "包装" in col else ""
            out.append(
                RawQuote(item_name, raw_price, raw_unit, origin, grade, extra={"packing": packing})
            )

        if not out:
            raise CollectorError("市场C Excel 解析结果为空")
        return out
