"""服务端生成的 SVG 折线图（无外网依赖，内网也能用）。"""
from __future__ import annotations

PALETTE = ["#2563eb", "#dc2626", "#16a34a", "#d97706", "#7c3aed", "#0891b2", "#db2777", "#65a30d"]


def line_chart(series: dict[str, list[tuple[str, float]]], *, width: int = 860,
               height: int = 340, title: str = "", y_label: str = "元/公斤") -> str:
    """series: {系列名: [(日期str, 值), ...]}，各系列日期轴取并集。"""
    all_dates = sorted({d for pts in series.values() for d, _ in pts})
    if not all_dates:
        return "<div class='empty'>所选区间暂无数据</div>"

    values = [v for pts in series.values() for _, v in pts]
    vmin, vmax = min(values), max(values)
    if vmax == vmin:
        vmax = vmin + 1
    pad = (vmax - vmin) * 0.08
    vmin, vmax = max(0, vmin - pad), vmax + pad

    ml, mr, mt, mb = 64, 150, 36, 46
    plot_w, plot_h = width - ml - mr, height - mt - mb

    def x_pos(i: int) -> float:
        if len(all_dates) == 1:
            return ml + plot_w / 2
        return ml + plot_w * i / (len(all_dates) - 1)

    def y_pos(v: float) -> float:
        return mt + plot_h * (1 - (v - vmin) / (vmax - vmin))

    parts = [f"<svg viewBox='0 0 {width} {height}' class='chart' role='img'>"]
    if title:
        parts.append(f"<text x='{ml}' y='20' class='chart-title'>{title}</text>")

    # 网格 + Y 轴刻度（5 条）
    for gi in range(5):
        val = vmin + (vmax - vmin) * gi / 4
        y = y_pos(val)
        parts.append(f"<line x1='{ml}' y1='{y:.1f}' x2='{ml+plot_w}' y2='{y:.1f}' class='grid'/>")
        parts.append(f"<text x='{ml-8}' y='{y+4:.1f}' text-anchor='end' class='axis'>{val:.2f}</text>")
    parts.append(f"<text x='16' y='{mt-12}' class='axis'>{y_label}</text>")

    # X 轴日期标签（最多 8 个，避免挤）
    step = max(1, len(all_dates) // 8)
    for i, d in enumerate(all_dates):
        if i % step == 0 or i == len(all_dates) - 1:
            x = x_pos(i)
            parts.append(f"<text x='{x:.1f}' y='{height-14}' text-anchor='middle' class='axis'>{d[5:]}</text>")

    # 各系列折线
    for si, (name, pts) in enumerate(series.items()):
        color = PALETTE[si % len(PALETTE)]
        point_map = {d: v for d, v in pts}
        coords = [(x_pos(all_dates.index(d)), y_pos(v)) for d, v in sorted(point_map.items())]
        if not coords:
            continue
        path = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
        parts.append(f"<path d='{path}' fill='none' stroke='{color}' stroke-width='2'/>")
        for x, y in coords:
            parts.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='3' fill='{color}'>"
                         f"<title>{name} {all_dates[min(range(len(all_dates)), key=lambda i: abs(x_pos(i)-x))]} 值见走势</title></circle>")

    # 图例
    ly = mt + 6
    for si, name in enumerate(series):
        color = PALETTE[si % len(PALETTE)]
        parts.append(f"<rect x='{ml+plot_w+16}' y='{ly+si*24}' width='14' height='4' fill='{color}'/>")
        parts.append(f"<text x='{ml+plot_w+36}' y='{ly+si*24+5}' class='legend'>{name}</text>")

    parts.append("</svg>")
    return "".join(parts)
