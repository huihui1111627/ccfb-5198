"""市场 A：httpx 抓分页 HTML 表格，BeautifulSoup 解析。"""
from __future__ import annotations

from datetime import date

import httpx
from bs4 import BeautifulSoup

from .base import BaseCollector, CollectorError, MarketClosed, RawQuote


class MarketACollector(BaseCollector):
    def fetch(self, d: date) -> list[RawQuote]:
        out: list[RawQuote] = []
        page = 1
        unit = "元/公斤"
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            while True:
                try:
                    resp = client.get(
                        f"{self.base_url}/quotes",
                        params={"date": d.isoformat(), "page": page},
                    )
                    resp.raise_for_status()
                except httpx.HTTPError as exc:
                    raise CollectorError(f"市场A请求失败: {exc}") from exc

                soup = BeautifulSoup(resp.text, "lxml")
                if soup.select_one(".notice") and not soup.select_one("table"):
                    text = soup.select_one(".notice").get_text(strip=True)
                    if "休市" in text:
                        raise MarketClosed(text)
                    raise CollectorError(f"市场A无数据: {text}")

                table = soup.select_one("table")
                if table is None:
                    raise CollectorError("市场A页面未找到行情表格")

                header = [th.get_text(strip=True) for th in table.select("thead th")]
                if header:
                    for h in header:
                        if "单位" in h:
                            idx_unit = header.index(h)
                            break
                    else:
                        idx_unit = 4
                else:
                    idx_unit = 4

                rows = table.select("tbody tr")
                if not rows:
                    break
                for tr in rows:
                    tds = [td.get_text(strip=True) for td in tr.select("td")]
                    if len(tds) < 5:
                        continue
                    item_name, origin, grade, price, raw_unit = tds[0], tds[1], tds[2], tds[3], tds[idx_unit]
                    try:
                        raw_price = float(price)
                    except ValueError as exc:
                        raise CollectorError(f"市场A价格无法解析: {price!r}") from exc
                    unit = raw_unit or unit
                    out.append(RawQuote(item_name, raw_price, unit, origin, grade))

                # 翻页：没有下一页链接即结束
                pager_links = [a.get_text(strip=True) for a in soup.select(".pager a")]
                if f"{page + 1}" not in pager_links:
                    break
                page += 1

        if not out:
            raise CollectorError("市场A解析结果为空")
        return out
