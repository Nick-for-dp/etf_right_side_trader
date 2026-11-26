#!/usr/bin/env python
"""止损后再入场消融实验 — 在 v2.4 新基线基础上运行。

用法:
    uv run python src/backtest/run_reentry_ablation.py

输出:
    src/backtest/reentry_ablation_report.md

实验集 (reentry-rules):
    baseline_v2_4_segment_stop  → 新基线（无止后再入场过滤）
    reentry_cooldown_10        → 冷静10日
    reentry_cooldown_20        → 冷静20日
    reentry_score_60           → score>=60
    reentry_score_65           → score>=65
    reentry_price_reclaim      → 价格修复
    reentry_trend_repair       → 趋势修复
    reentry_composite          → 复合修复
"""

import json
import sys
import os
from datetime import date, timedelta

# 脚本在 src/backtest/，项目根目录是 ../../
_project_root = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.backtest.ablation_config import get_ablation_experiments
from src.backtest.ablation_report import format_ablation_report, run_ablation_backtest
from src.config import load_config
from src.database import init_engine, dispose_engine
from src.service.calendar_service import TradingCalendarService


def main():
    config = load_config()
    engine = init_engine(config.db_url)

    calendar = TradingCalendarService()
    end = date.fromisoformat(calendar.get_previous_trading_day())
    codes = [e.symbol for e in config.etf_list]

    # ── 双窗口回测 ──
    windows = [
        ("2016-2026全量", date(2016, 1, 1), end),
        ("2024-2026近期", date(2024, 1, 1), end),
    ]

    all_results = []
    for label, start, w_end in windows:
        print(f"\n  === 回测窗口: {label} ({start} ~ {w_end}) ===")
        result = run_ablation_backtest(
            codes=codes,
            start=start,
            end=w_end,
            capital=100_000.0,
            cost_ratio=0.0005,
            slippage=0.0001,
            position_limit=0.3,
            experiments=None,
            matrix="reentry-rules",
        )
        result["meta"]["window"] = label
        all_results.append(result)

        baseline_name = result["meta"].get("baseline_name", "baseline_v2_4_segment_stop")
        report_text = format_ablation_report(result, baseline_name)
        print(report_text)

    # ── 生成 markdown 报告 ──
    md = build_markdown_report(all_results, config, codes, end)
    report_path = os.path.join(os.path.dirname(__file__), "reentry_ablation_report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"\n  报告已保存: {report_path}")

    dispose_engine()


def build_markdown_report(all_results, config, codes, end):
    lines = []
    lines.append("# 止损后再入场消融实验报告")
    lines.append("")
    lines.append(f"> 生成日期: {date.today().isoformat()}")
    lines.append(f"> 回测截止: {end}")
    lines.append(f"> ETF 数量: {len(codes)}")
    lines.append("")

    lines.append("## 实验说明")
    lines.append("")
    lines.append("在 **v2.4 新基线**（70/15/15阶梯建仓加仓 + 90日最大持有 + 分市场/分波动止损 profile）")
    lines.append("基础上，增加 7 种止损后再入场过滤规则，评估各规则对收益、回撤和胜率的影响。")
    lines.append("")
    lines.append("### 基线配置")
    lines.append("")
    lines.append("| 参数 | 值 |")
    lines.append("|---|---|")
    lines.append("| 建仓策略 | 70/15/15 阶梯（70% 建仓，两次 15% 加仓） |")
    lines.append("| 止损策略 | settings.yaml 分市场/分波动止损 profile |")
    lines.append("| 最大持有 | 90 个自然日 |")
    lines.append("| 仓位上限 | 30% |")
    lines.append("| 初始资金 | 100,000 元 |")
    lines.append("| 交易成本 | 佣金 0.0005 + 滑点 0.0001 |")
    lines.append("")

    lines.append("### 待测再入场规则")
    lines.append("")
    lines.append("| 实验 | 冷却期 | Score门槛 | 价格修复 | 趋势修复 | ADX | MACD |")
    lines.append("|---|---|---|---|---|---|---|")
    lines.append("| baseline-v2.4 | — | — | — | — | — | — |")
    lines.append("| 冷静10日 | 10日 | — | — | — | — | — |")
    lines.append("| 冷静20日 | 20日 | — | — | — | — | — |")
    lines.append("| score>=60 | — | ≥60 | — | — | — | — |")
    lines.append("| score>=65 | — | ≥65 | — | — | — | — |")
    lines.append("| 价格修复 | — | — | 站上MA20+高于止损价0.5ATR | — | — | — |")
    lines.append("| 趋势修复 | — | — | 站上MA20 | MA20>MA60 | ≥20 | DIF>DEA |")
    lines.append("| 复合修复 | 10日 | ≥60 | 站上MA20+高于止损价0.5ATR | — | ≥20 | DIF>DEA |")
    lines.append("")

    for result in all_results:
        window = result["meta"].get("window", "")
        lines.append(f"---")
        lines.append("")
        lines.append(f"## 窗口: {window}")
        lines.append("")
        lines.append("```")
        baseline_name = result["meta"].get("baseline_name", "baseline_v2_4_segment_stop")
        report_text = format_ablation_report(result, baseline_name)
        lines.append(report_text)
        lines.append("```")
        lines.append("")

        versions = result.get("versions", {})
        baseline = versions.get(baseline_name)
        if baseline is None:
            continue
        baseline_summary = baseline["summary"]

        # 再入场专项指标
        lines.append("### 再入场专项指标")
        lines.append("")
        lines.append("| 实验 | 再入场尝试 | 通过 | 拦截 | 执行 | 平仓 | 盈利 | 亏损(止损) | 再入场总盈亏 |")
        lines.append("|---|---|---|---|---|---|---|---|---|")

        for name, item in versions.items():
            exp = item.get("experiment", {})
            label = exp.get("label") or name
            stats = item.get("stats", {})
            reentry_attempts = stats.get("reentry_attempts", 0)
            reentry_allowed = stats.get("reentry_allowed", 0)
            reentry_blocked = stats.get("reentry_blocked", 0)
            reentry_executed = stats.get("reentry_executed", 0)
            reentry_closed = stats.get("reentry_closed", 0)
            reentry_wins = stats.get("reentry_wins", 0)
            reentry_stop_loss = stats.get("reentry_stop_loss_exit", 0)
            reentry_pnl = stats.get("reentry_pnl_total", 0.0)

            lines.append(
                f"| {label} | {reentry_attempts} | {reentry_allowed} "
                f"| {reentry_blocked} | {reentry_executed} | {reentry_closed} "
                f"| {reentry_wins} | {reentry_stop_loss} | {reentry_pnl:+,.0f} |"
            )
        lines.append("")

        # 相对 Baseline 改善率
        lines.append("### 相对 Baseline 改善率")
        lines.append("")
        lines.append("| 实验 | Δ年化 | Δ回撤 | Δ胜率 | ΔCalmar | ΔSharpe | 采纳判断 |")
        lines.append("|---|---|---|---|---|---|---|")

        for name, item in versions.items():
            if name == baseline_name:
                continue
            summary = item["summary"]
            exp = item.get("experiment", {})
            label = exp.get("label") or name

            def parse_pct_val(text):
                if text is None or text == "N/A":
                    return None
                t = str(text).strip().rstrip("%")
                try:
                    return float(t) / 100 if "%" in str(text) else float(t)
                except ValueError:
                    return None

            def delta_str(v, b, lower_is_better=False):
                cv = parse_pct_val(v)
                bv = parse_pct_val(b)
                if cv is None or bv is None:
                    return "N/A"
                d = (bv - cv) if lower_is_better else (cv - bv)
                return f"{d * 100:+.2f}%"

            ar_d = delta_str(summary.get("annual_return"),
                             baseline_summary.get("annual_return"), lower_is_better=False)
            dd_d = delta_str(summary.get("max_drawdown"),
                             baseline_summary.get("max_drawdown"), lower_is_better=True)
            wr_d = delta_str(summary.get("win_rate"),
                             baseline_summary.get("win_rate"), lower_is_better=False)

            calmar = summary.get("calmar", "N/A")
            sharpe = summary.get("sharpe", "N/A")

            ar_val = parse_pct_val(summary.get("annual_return"))
            dd_val = parse_pct_val(summary.get("max_drawdown"))
            wr_val = parse_pct_val(summary.get("win_rate"))
            ba_ar = parse_pct_val(baseline_summary.get("annual_return"))
            ba_dd = parse_pct_val(baseline_summary.get("max_drawdown"))
            ba_wr = parse_pct_val(baseline_summary.get("win_rate"))

            judgement_parts = []
            if ar_val is not None and ba_ar is not None:
                ar_rel = (ar_val - ba_ar) / ba_ar if ba_ar != 0 else 0
                if ar_rel >= 0.05:
                    judgement_parts.append("✅ 年化+5%")
            if dd_val is not None and ba_dd is not None and ba_dd != 0:
                dd_rel = (dd_val - ba_dd) / abs(ba_dd)
                if dd_rel <= -0.05:
                    judgement_parts.append("✅ 回撤-5%")
            if wr_val is not None and ba_wr is not None:
                wr_abs = wr_val - ba_wr
                if wr_abs >= 0.03:
                    judgement_parts.append("✅ 胜率+3pct")
            if not judgement_parts:
                judgement_parts.append("⏳ 未达采纳阈值")

            lines.append(
                f"| {label} | {ar_d} | {dd_d} | {wr_d} "
                f"| {calmar} | {sharpe} | {'; '.join(judgement_parts)} |"
            )
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 结论与建议")
    lines.append("")
    lines.append("> 本报告由 `src/backtest/run_reentry_ablation.py` 自动生成。")
    lines.append("> 基于实验结果，决定是否将某个再入场过滤规则纳入生产代码。")

    return "\n".join(lines)


if __name__ == "__main__":
    main()
