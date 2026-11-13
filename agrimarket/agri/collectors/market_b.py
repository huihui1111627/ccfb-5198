"""市场 B：数据藏在 window.__PRICE_DATA__ 里，必须用 Playwright 执行 JS 才能拿到。"""
from __future__ import annotations

from datetime import date

from .base import BaseCollector, CollectorError, MarketClosed, RawQuote


class MarketBCollector(BaseCollector):
    def open(self) -> None:
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        self._page = self._browser.new_page()

    def close(self) -> None:
        if hasattr(self, "_browser"):
            self._browser.close()
        if hasattr(self, "_pw"):
            self._pw.stop()

    def fetch(self, d: date) -> list[RawQuote]:
        if not hasattr(self, "_page"):
            self.open()
        try:
            self._page.goto(
                f"{self.base_url}/quotes?date={d.isoformat()}",
                wait_until="networkidle",
                timeout=20000,
            )
        except Exception as exc:  # playwright 的异常体系较杂，统一收口
            raise CollectorError(f"市场B页面加载失败: {exc}") from exc

        notice = self._page.locator(".notice").count()
        if notice and not self._page.locator("table").count():
            text = self._page.locator(".notice").first.inner_text()
            if "休市" in text:
                raise MarketClosed(text.strip())
            raise CollectorError(f"市场B无数据: {text.strip()}")

        data = self._page.evaluate("window.__PRICE_DATA__")
        if not data or not data.get("rows"):
            raise CollectorError("市场B JS 变量 __PRICE_DATA__ 为空")

        unit = data.get("unit", "元/斤")
        out = []
        for row in data["rows"]:
            try:
                out.append(
                    RawQuote(
                        item_name=row["item_name"],
                        raw_price=float(row["raw_price"]),
                        raw_unit=row.get("raw_unit") or unit,
                        origin=row.get("origin", ""),
                        grade=row.get("grade", ""),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise CollectorError(f"市场B行数据格式异常: {row!r}") from exc
        return out
