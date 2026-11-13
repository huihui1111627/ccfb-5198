"""网页控制台：仪表盘 / 采集任务 / 品种映射 / 行情数据 / 异常价格 / 设置。"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

from flask import (Flask, Response, flash, redirect, render_template, request,
                   url_for)

from ..config import today
from ..db import get_conn, get_setting, set_setting
from ..services import mapping
from ..services.anomaly import handle as handle_anomaly
from ..services.anomaly import list_anomalies
from ..services.export import export_quotes
from ..services.runner import backfill, collect_all, list_runs, run_market_day
from ..services.scheduler import reload_scheduler
from ..services.trends import latest_prices, market_compare, trend
from .charts import line_chart


def create_app(db_path: str | None = None, start_jobs: bool = True) -> Flask:
    app = Flask(__name__)
    app.secret_key = "agrimarket-local-console"
    app.config["DB_PATH"] = db_path

    def db() -> sqlite3.Connection:
        return get_conn(app.config["DB_PATH"])

    @app.context_processor
    def inject_globals():
        return {"page_today": today()}

    # ------------------------------------------------------------ 仪表盘
    @app.get("/")
    def dashboard():
        with db() as conn:
            totals = {
                "quotes": conn.execute("SELECT COUNT(*) c FROM quotes").fetchone()["c"],
                "varieties": conn.execute("SELECT COUNT(*) c FROM varieties").fetchone()["c"],
                "markets": conn.execute("SELECT COUNT(*) c FROM markets WHERE enabled=1").fetchone()["c"],
                "pending": conn.execute(
                    "SELECT COUNT(*) c FROM anomalies WHERE status='pending'").fetchone()["c"],
                "unmapped": conn.execute("SELECT COUNT(*) c FROM unmapped_quotes").fetchone()["c"],
            }
            latest_day = conn.execute("SELECT MAX(quote_date) d FROM quotes").fetchone()["d"]
            recent_runs = list_runs(conn, limit=8)
            pending_rows = list_anomalies(conn, "pending")[:6]
        return render_template("dashboard.html", totals=totals, latest_day=latest_day,
                               recent_runs=recent_runs, pending_rows=pending_rows)

    # ------------------------------------------------------------ 采集任务
    @app.get("/tasks")
    def tasks():
        with db() as conn:
            markets = conn.execute("SELECT * FROM markets ORDER BY code").fetchall()
            runs = list_runs(conn, limit=80)
            backfill_days = get_setting(conn, "backfill_days", "15")
            sched_enabled = get_setting(conn, "scheduler_enabled", "1")
            sched_hour = get_setting(conn, "scheduler_hour", "18")
            sched_minute = get_setting(conn, "scheduler_minute", "0")
        return render_template("tasks.html", markets=markets, runs=runs,
                               backfill_days=backfill_days,
                               sched=f"{sched_hour}:{str(sched_minute).zfill(2)}",
                               sched_enabled=sched_enabled == "1")

    @app.post("/tasks/collect")
    def tasks_collect():
        market_code = request.form.get("market_code") or None
        raw_date = request.form.get("quote_date", "").strip()
        try:
            target = date.fromisoformat(raw_date) if raw_date else today()
        except ValueError:
            flash("日期格式不正确，已按今天处理", "warn")
            target = today()
        if market_code:
            results = [run_market_day(market_code, target, app.config["DB_PATH"])]
        else:
            results = collect_all(target, app.config["DB_PATH"])
        for r in results:
            flash(f"[{r.market_code}] {r.quote_date} {r.status}：{r.message}",
                  "ok" if r.status == "success" else ("warn" if r.status == "closed" else "err"))
        return redirect(url_for("tasks"))

    @app.post("/tasks/backfill")
    def tasks_backfill():
        market_code = request.form.get("market_code") or None
        force = request.form.get("force") == "1"
        try:
            days = min(60, max(1, int(request.form.get("days", 15))))
        except ValueError:
            days = 15
        results = backfill(market_code, days, app.config["DB_PATH"], force=force)
        if not results:
            flash("窗口内没有需要补采的日期（休市日自动跳过，成功日期默认不重采）", "warn")
        else:
            ok = sum(1 for r in results if r.status == "success")
            closed = sum(1 for r in results if r.status == "closed")
            failed = sum(1 for r in results if r.status == "failed")
            flash(f"补采完成：成功 {ok} 个市场日，休市跳过 {closed}，失败 {failed}",
                  "err" if failed else "ok")
        return redirect(url_for("tasks"))

    # ------------------------------------------------------------ 品种映射
    @app.get("/mapping")
    def mapping_page():
        with db() as conn:
            markets = conn.execute("SELECT * FROM markets ORDER BY code").fetchall()
            varieties = conn.execute("SELECT * FROM varieties ORDER BY category, code").fetchall()
            aliases = mapping.list_aliases(conn)
            unmapped = mapping.list_unmapped(conn)
            specs = conn.execute(
                "SELECT p.*, v.name AS variety_name, m.name AS market_name FROM package_specs p "
                "JOIN varieties v ON v.code=p.variety_code "
                "JOIN markets m ON m.code=p.market_code ORDER BY p.market_code, p.variety_code"
            ).fetchall()
        return render_template("mapping.html", markets=markets, varieties=varieties,
                               aliases=aliases, unmapped=unmapped, specs=specs)

    @app.post("/mapping/alias")
    def mapping_add_alias():
        market_code = request.form["market_code"]
        raw_name = request.form["raw_name"].strip()
        variety_code = request.form["variety_code"]
        if not raw_name:
            flash("原始品名不能为空", "err")
        else:
            with db() as conn:
                mapping.add_alias(conn, market_code, raw_name, variety_code)
            flash(f"已建立映射：{raw_name} → {variety_code}", "ok")
        return redirect(url_for("mapping_page"))

    @app.post("/mapping/alias/<int:alias_id>/delete")
    def mapping_delete_alias(alias_id: int):
        with db() as conn:
            mapping.delete_alias(conn, alias_id)
        flash("别名映射已删除（下次采集到该品名会进入待处理清单）", "warn")
        return redirect(url_for("mapping_page"))

    @app.post("/mapping/spec")
    def mapping_save_spec():
        market_code = request.form["market_code"]
        variety_code = request.form["variety_code"]
        pack_unit = request.form["pack_unit"].strip() or "箱"
        try:
            spec_kg = float(request.form["spec_kg"])
            if spec_kg <= 0:
                raise ValueError
        except ValueError:
            flash("每包净重必须是大于 0 的数字（公斤）", "err")
            return redirect(url_for("mapping_page"))
        with db() as conn:
            conn.execute(
                "INSERT INTO package_specs(market_code,variety_code,pack_unit,spec_kg) "
                "VALUES(?,?,?,?) ON CONFLICT(market_code,variety_code) DO UPDATE SET "
                "pack_unit=excluded.pack_unit, spec_kg=excluded.spec_kg",
                (market_code, variety_code, pack_unit, spec_kg),
            )
        flash(f"已保存包装规格：{market_code} 市场 {variety_code} 每{pack_unit} {spec_kg:g} 公斤", "ok")
        return redirect(url_for("mapping_page"))

    # ------------------------------------------------------------ 行情数据
    @app.get("/quotes")
    def quotes_page():
        end = request.args.get("end") or today().isoformat()
        start = request.args.get("start") or (today() - timedelta(days=14)).isoformat()
        market_code = request.args.get("market_code") or ""
        variety_code = request.args.get("variety_code") or "大白菜"
        try:
            page_no = max(1, int(request.args.get("page", 1)))
        except ValueError:
            page_no = 1

        with db() as conn:
            page_size = int(get_setting(conn, "page_size", "20"))
            markets = conn.execute("SELECT * FROM markets ORDER BY code").fetchall()
            varieties = conn.execute("SELECT * FROM varieties ORDER BY category, code").fetchall()

            where = "q.quote_date BETWEEN ? AND ?"
            params: list = [start, end]
            if market_code:
                where += " AND q.market_code=?"
                params.append(market_code)
            if variety_code:
                where += " AND q.variety_code=?"
                params.append(variety_code)

            total = conn.execute(
                f"SELECT COUNT(*) c FROM quotes q WHERE {where}", params).fetchone()["c"]
            rows = conn.execute(
                f"SELECT q.*, v.name AS variety_name, m.name AS market_name FROM quotes q "
                f"JOIN varieties v ON v.code=q.variety_code "
                f"JOIN markets m ON m.code=q.market_code WHERE {where} "
                f"ORDER BY q.quote_date DESC, q.market_code LIMIT ? OFFSET ?",
                params + [page_size, (page_no - 1) * page_size],
            ).fetchall()

            # 走势图：该品种各市场一条线
            trend_rows = trend(conn, variety_code, start, end, market_code or None)
            series: dict[str, list[tuple[str, float]]] = {}
            for r in trend_rows:
                series.setdefault(r["market_name"], []).append((r["quote_date"], r["price_per_kg"]))
            chart_svg = line_chart(series, title=f"{variety_code} 价格走势（元/公斤）")
            compare = market_compare(conn, variety_code, start, end)
            latest = latest_prices(conn)

        pages = max(1, (total + page_size - 1) // page_size)
        return render_template(
            "quotes.html", rows=rows, markets=markets, varieties=varieties,
            start=start, end=end, market_code=market_code, variety_code=variety_code,
            chart_svg=chart_svg, compare=compare, latest=latest,
            page_no=page_no, pages=pages, total=total,
        )

    @app.get("/quotes/export")
    def quotes_export():
        start = request.args.get("start") or (today() - timedelta(days=14)).isoformat()
        end = request.args.get("end") or today().isoformat()
        market_code = request.args.get("market_code") or None
        variety_code = request.args.get("variety_code") or None
        with db() as conn:
            data = export_quotes(conn, start, end, market_code, variety_code)
        fname = f"agri_quotes_{start}_{end}.xlsx"
        return Response(
            data,
            headers={
                "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "Content-Disposition": f"attachment; filename={fname}",
            },
        )

    # ------------------------------------------------------------ 异常价格
    @app.get("/anomalies")
    def anomalies_page():
        status = request.args.get("status", "pending")
        with db() as conn:
            rows = list_anomalies(conn, status or None)
            threshold = get_setting(conn, "anomaly_pct", "30")
        return render_template("anomalies.html", rows=rows, status=status, threshold=threshold)

    @app.post("/anomalies/<int:anomaly_id>/handle")
    def anomalies_handle(anomaly_id: int):
        action = "confirmed" if request.form.get("action") == "confirm" else "dismissed"
        note = request.form.get("note", "").strip()
        with db() as conn:
            handle_anomaly(conn, anomaly_id, action, note)
        flash("已确认异常" if action == "confirmed" else "已忽略该异常", "ok")
        return redirect(url_for("anomalies_page", status=request.form.get("redirect_status", "pending")))

    # ------------------------------------------------------------ 设置
    @app.get("/settings")
    def settings_page():
        with db() as conn:
            settings = {r["key"]: r["value"] for r in conn.execute("SELECT * FROM settings").fetchall()}
            holidays = conn.execute("SELECT * FROM holidays ORDER BY d").fetchall()
            markets = conn.execute("SELECT * FROM markets ORDER BY code").fetchall()
            varieties = conn.execute("SELECT * FROM varieties ORDER BY code").fetchall()
            specs = conn.execute(
                "SELECT p.*, v.name AS variety_name FROM package_specs p "
                "JOIN varieties v ON v.code=p.variety_code ORDER BY p.market_code, p.variety_code"
            ).fetchall()
        return render_template("settings.html", settings=settings, holidays=holidays,
                               markets=markets, varieties=varieties, specs=specs)

    @app.post("/settings")
    def settings_save():
        keys = ["anomaly_pct", "scheduler_hour", "scheduler_minute",
                "backfill_days", "page_size"]
        with db() as conn:
            for key in keys:
                if key in request.form:
                    set_setting(conn, key, request.form[key].strip())
            set_setting(conn, "scheduler_enabled",
                        "1" if request.form.get("scheduler_enabled") == "1" else "0")
        if start_jobs:
            reload_scheduler(app.config["DB_PATH"])
        flash("设置已保存，定时任务已按新配置重载", "ok")
        return redirect(url_for("settings_page"))

    @app.post("/settings/holiday")
    def settings_add_holiday():
        raw = request.form.get("d", "").strip()
        name = request.form.get("name", "自定义休市").strip() or "自定义休市"
        try:
            d = date.fromisoformat(raw)
        except ValueError:
            flash("休市日期格式不正确", "err")
            return redirect(url_for("settings_page"))
        with db() as conn:
            conn.execute(
                "INSERT INTO holidays(d,name) VALUES(?,?) "
                "ON CONFLICT(d) DO UPDATE SET name=excluded.name",
                (d.isoformat(), name),
            )
        flash(f"已登记休市日 {d.isoformat()}（{name}）", "ok")
        return redirect(url_for("settings_page"))

    @app.post("/settings/holiday/<d>/delete")
    def settings_delete_holiday(d: str):
        with db() as conn:
            conn.execute("DELETE FROM holidays WHERE d=?", (d,))
        flash("休市日已删除", "warn")
        return redirect(url_for("settings_page"))

    @app.post("/settings/spec/<int:spec_id>")
    def settings_update_spec(spec_id: int):
        try:
            spec_kg = float(request.form["spec_kg"])
            pack_unit = request.form.get("pack_unit", "箱").strip() or "箱"
            if spec_kg <= 0:
                raise ValueError
        except ValueError:
            flash("每包净重必须是大于 0 的数字（公斤）", "err")
            return redirect(url_for("settings_page"))
        with db() as conn:
            conn.execute("UPDATE package_specs SET spec_kg=?, pack_unit=? WHERE id=?",
                         (spec_kg, pack_unit, spec_id))
        flash("包装规格已更新，下次采集/补采即按新规格换算", "ok")
        return redirect(url_for("settings_page"))

    @app.template_filter("fmtdate")
    def fmtdate(value: str) -> str:
        try:
            return datetime.strptime(value, "%Y-%m-%d").strftime("%m-%d")
        except (ValueError, TypeError):
            return value

    return app
