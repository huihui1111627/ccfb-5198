# 农批行情采集系统

面向农产品供应链的多批发市场行情采集与归一平台。三个形态各异的 mock 市场站 +
采集层（httpx / Playwright / openpyxl）+ SQLite 存储 + Flask 网页控制台。

## 功能对照

| 需求 | 实现 |
| --- | --- |
| 每天定时采集，漏日期可补 | APScheduler 每日 cron；「采集任务」页支持立即采集与按天回看补采，休市日自动跳过并留痕，成功日默认不重采（可强制） |
| 品名归一（大白菜=黄芽白） | `variety_aliases` 别名表按市场维护，未识别品名进待处理清单，页面一键映射 |
| 斤/公斤/箱/件 → 元每公斤 | `agri/units.py`：斤固定 ×2；**箱/件按「市场+品种」在 `package_specs` 配每包净重，逐品种换算，缺规格直接报错隔离，绝不瞎猜** |
| 价格突变标异常、人工确认 | 同市场同品种环比上一开市日，涨跌幅超阈值（默认 30%，可调）入异常表，支持确认/忽略/备注，重采自动重算 |
| 走势与市场间对比 | 服务端 SVG 折线图（无外网依赖）、区间均价/极值对比表、最新横向价 |
| 导出 Excel | 双工作表：行情明细（含原始价/单位与归一价）+ 市场均价对比 |
| 节假日休市 | 内置 2026 法定节假日 + 每市场额外闭市日，设置页可自定义增删 |

## 三个 mock 市场

| 代码 | 市场 | 站点形态 | 计价单位 | 采集方式 |
| --- | --- | --- | --- | --- |
| A | 华东果菜批发市场 | 分页 HTML 表格（每页 5 条） | 元/公斤 | httpx + BeautifulSoup 翻页 |
| B | 城南农贸批发市场 | 数据藏在 `window.__PRICE_DATA__` JS 变量，必须执行 JS | 元/斤 | Playwright + Chromium |
| C | 北环批发市场 | 每日 Excel 报价单下载 | 元/箱、元/件（按品种不同规格） | httpx 下载 + openpyxl 解析 |

mock 数据用 SHA-256 做确定性生成：同 (市场,日期,品种) 任意进程结果一致，
三个站口径互通；内置约 3% 的突变埋点供异常检测命中。

## 目录结构

```
agrimarket/
├── agri/
│   ├── config.py            # 路径/端口/日期窗口（环境变量可覆盖）
│   ├── calendar.py          # 法定节假日 + 市场额外闭市
│   ├── mockdata.py          # 确定性 mock 行情生成
│   ├── db.py                # SQLite 连接与建表
│   ├── units.py             # ★ 单位归一（箱/件按品种规格）
│   ├── seed.py              # 市场/品种/别名/箱规/设置初始化
│   ├── mocks/               # 三个 mock Flask 站
│   ├── collectors/          # 三种采集器 + 工厂
│   ├── services/            # 映射、异常、采集编排、走势、导出、调度
│   └── web/                 # 控制台（Flask + Jinja + 服务端 SVG）
├── tests/                   # 39 个 pytest 用例
├── run_all.sh               # 一键起 mock 站 + 控制台
└── requirements.txt
```

## 快速开始

```bash
pip install -r requirements.txt
python -m playwright install chromium   # 已装可跳过

# 方式一：一键启动（mock 站 8601-8603 + 控制台 8610）
./run_all.sh

# 方式二：分开启动
python -m agri.cli mocks          # 终端 1
python -m agri.cli web            # 终端 2，浏览器开 http://127.0.0.1:8610
```

控制台六个页面：仪表盘 / 采集任务 / 品种映射 / 行情数据 / 异常价格 / 设置。

## 常用 CLI

```bash
python -m agri.cli init                       # 初始化库与基础数据
python -m agri.cli collect                    # 立即采集今天（全市场）
python -m agri.cli collect --market C --date 2026-11-10
python -m agri.cli backfill --days 30         # 补采近 30 天（跳过已成功/休市）
python -m agri.cli backfill --market A --force
python -m agri.cli scheduler                  # 只跑定时调度进程
python -m agri.cli web --no-scheduler
```

## 试一遍完整流程

```bash
AGRI_TODAY=2026-11-13 python -m agri.cli backfill --days 73
# → 全窗口约 1600+ 条行情、80 条左右待确认异常，国庆等休市日以 closed 留痕
```

然后到「异常价格」页确认几条，「行情数据」页看走势/对比并导出 Excel，
「品种映射」页可看 C 市场六个品种各自不同的箱/件规格。

## 单位换算设计（重点）

- 公斤直读；斤 = 公斤价 ÷ 2（即 斤价 × 2）；
- 箱/件：`归一价 = 整包价 ÷ 每包净重(kg)`，净重来自 `package_specs`，
  唯一键是 `(市场, 品种)`——苹果 15kg/箱、茄子 8kg/箱、大白菜 20kg/件 各配各的；
- 采到箱/件价但查不到规格时，该条进未映射队列并在采集任务里标注「缺包装规格」，
  配好规格后补采即可，系统不会用一个全局常数兜底。

## 测试

```bash
python -m pytest              # 39 passed，含真实 Playwright 浏览器用例
```

用临时库（`tmp_path`）和测试端口（8701-8703），不污染 `data/agri.db`。
覆盖：单位换算七种情形、别名映射、异常阈值/重算、三个采集器端到端、
休市跳过、补采幂等、缺规格隔离、Web 全部路由与导出。

## 关键环境变量

| 变量 | 作用 |
| --- | --- |
| `AGRI_DB` | SQLite 文件路径，默认 `data/agri.db` |
| `AGRI_DATA_DIR` | 数据目录 |
| `AGRI_TODAY` | 覆盖“今天”（演示固定窗口/测试用） |
| `AGRI_MARKET_A_URL` 等 | 覆盖市场地址（测试用） |
| `AGRI_WEB_PORT` | 控制台端口，默认 8610 |
