#!/usr/bin/env python
"""低波动ETF参数消融实验。

低波动组特点：趋势温和、波动小、信号少、年化偏低(6.21%)。
目标：降低BUY阈值、放松正子信号要求，增加有效信号。

用法:
    uv run python src/ds_backtest/volatility_tuning/05_low_vol_ablation.py
"""

import sys
import os
from datetime import date

import yaml

_project_root = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.backtest.ablation_config import (
    AblationExperimentConfig,
    BUDGET_RULE_70_15_15_LADDER,
    MONTHLY_QUARTER_90D,
    STOP_LOSS_FIXED_8,
)
from src.backtest.portfolio_backtest import PortfolioBacktest
from src.config import load_config
from src.database import init_engine, dispose_engine
from src.service.calendar_service import TradingCalendarService
from src.service.signal_rebuild_service import rebuild_signals


SETTINGS_PATH = os.path.join(_project_root, "settings.yaml")
OUT_DIR = os.path.dirname(__file__)

LOW_VOL_CODES = [
    "159326", "510150", "159996", "516970",
    "159825", "159611", "561360", "513100",
]

# 低波动实验：放松默认策略的参数
EXPERIMENTS = [
    ("baseline", "基线(默认)", None),

    # 降低BUY阈值（更敏感）
    ("lv_buy_45", "BUY=45", {"buy_threshold": 45, "sell_threshold": -50, "min_positive": 2}),
    ("lv_buy_40", "BUY=40", {"buy_threshold": 40, "sell_threshold": -50, "min_positive": 2}),

    # 降低正子信号要求（>50即入场）
    ("lv_pos_1", "BUY=50/正子≥1", {"buy_threshold": 50, "sell_threshold": -50, "min_positive": 1}),
    ("lv_pos_1_buy45", "BUY=45/正子≥1", {"buy_threshold": 45, "sell_threshold": -50, "min_positive": 1}),

    # 放宽卖出（让利润跑）
    ("lv_sell_45", "BUY=50/SELL=-45", {"buy_threshold": 50, "sell_threshold": -45, "min_positive": 2}),

    # 综合宽松
    ("lv_relaxed", "BUY=45/SELL=-45/正子≥1",
     {"buy_threshold": 45, "sell_threshold": -45, "min_positive": 1}),
]

WINDOWS = [
    ("2016-2026", date(2016, 1, 1)),
    ("2024-2026", date(2024, 1, 1)),
]


def main():
    with open(SETTINGS_PATH, encoding="utf-8") as f:
        orig = yaml.safe_load(f)

    # 确保profiles存在
    profiles = orig.setdefault("strategy", {}).setdefault("params", {}).setdefault(
        "volatility_signal_profiles", {}
    )

    config = load_config()
    init_engine(config.db_url)
    calendar = TradingCalendarService()
    end = date.fromisoformat(calendar.get_previous_trading_day())

    all_results = []

    for exp_name, exp_label, params in EXPERIMENTS:
        print(f"\n{'='*70}")
        print(f"  [{exp_name}] {exp_label}")
        print(f"{'='*70}")

        # 设置低波动profile
        if params is None:
            lv = profiles.setdefault("low_vol", {})
            lv["enabled"] = False
        else:
            profiles["low_vol"] = {
                "enabled": True,
                "kind": "relaxed_default",
                "params": dict(params),
            }
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            yaml.dump(orig, f, default_flow_style=False, allow_unicode=True)

        config2 = load_config()
        result = rebuild_signals(
            config2, date(2016, 1, 1), end,
            codes=LOW_VOL_CODES, dry_run=False, rebuild_latest_advice=False,
        )
        print(f"  信号: 删除{result.deleted_signals}条, 写入{result.saved_signals}条")

        for window_label, start in WINDOWS:
            bt = PortfolioBacktest(
                calendar=calendar, initial_capital=100_000,
                cost_ratio=0.0005, slippage=0.0001, position_limit=0.3,
                cooldown_days=config2.strategy_params.get("cooldown_days", 5),
                market_regime_params=config2.market_regime_params,
                code_regime_groups={e.symbol: e.regime_group for e in config2.etf_list},
                code_stop_loss_profiles={e.symbol: e.stop_loss_profile for e in config2.etf_list},
                code_volatility_groups={e.symbol: e.volatility_group for e in config2.etf_list},
            )
            exp_cfg = AblationExperimentConfig(
                name=exp_name, label=exp_label,
                max_holding_days=90, cycle_profile=MONTHLY_QUARTER_90D,
                entry_add_budget_rule=BUDGET_RULE_70_15_15_LADDER,
                stop_loss_rule=STOP_LOSS_FIXED_8,
                use_config_stop_loss_profiles=True,
            )
            result_bt = bt.run_experiments(
                codes=LOW_VOL_CODES, start=start, end=end, experiments=[exp_cfg],
            )
            vd = result_bt.get("versions", {}).get(exp_name, {})
            s = vd.get("summary", {})
            st = vd.get("stats", {})
            row = {
                "exp_name": exp_name, "exp_label": exp_label, "window": window_label,
                "annual_return": s.get("annual_return", "N/A"),
                "max_drawdown": s.get("max_drawdown", "N/A"),
                "calmar": s.get("calmar", "N/A"),
                "sharpe": s.get("sharpe", "N/A"),
                "win_rate": s.get("win_rate", "N/A"),
                "profit_factor": s.get("profit_factor", "N/A"),
                "total_trades": int(s.get("total_trades", 0) or 0),
                "stop_loss": int(st.get("stop_loss_triggered", 0) or 0),
            }
            all_results.append(row)
            print(f"  [{window_label}] 年化={row['annual_return']:>8s}  "
                  f"回撤={row['max_drawdown']:>8s}  胜率={row['win_rate']:>8s}  "
                  f"交易={row['total_trades']:>3d}  止损={row['stop_loss']:>2d}")

    # 恢复
    profiles["low_vol"] = {"enabled": False}
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        yaml.dump(orig, f, default_flow_style=False, allow_unicode=True)
    config3 = load_config()
    rebuild_signals(config3, date(2016, 1, 1), end,
                    codes=LOW_VOL_CODES, dry_run=False, rebuild_latest_advice=False)
    dispose_engine()

    # 报告
    _save_report(all_results)


def _save_report(all_results):
    lines = [
        "# 低波动ETF参数消融实验报告",
        f"> 低波动组: {len(LOW_VOL_CODES)}只ETF",
        "> 基线: baseline-v2.4 默认策略参数",
        "",
    ]

    for w in ["2016-2026", "2024-2026"]:
        rows = [r for r in all_results if r["window"] == w]
        bl = next((r for r in rows if r["exp_name"] == "baseline"), None)
        if not bl: continue

        lines.append(f"## 窗口: {w}")
        lines.append("")
        lines.append(f"基线: {bl['annual_return']} / {bl['max_drawdown']} / {bl['win_rate']}  "
                      f"交易={bl['total_trades']}  止损={bl['stop_loss']}")
        lines.append("")
        lines.append("| 实验 | 年化 | Δ年化 | 回撤 | Δ回撤 | 胜率 | Δ胜率 | PF | 交易 | 止损 | 判断 |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|")

        for r in rows:
            if r["exp_name"] == "baseline":
                continue
            def p(v):
                if v is None or v == "N/A": return None
                t = str(v).strip().rstrip("%")
                try: return float(t) / 100 if "%" in str(v) else float(t)
                except: return None

            def d(v, b, lo=False):
                if v is None or b is None: return "N/A"
                return f"{(b - v) if lo else (v - b) * 100:+.2f}%"

            ar, dd, wr = p(r["annual_return"]), p(r["max_drawdown"]), p(r["win_rate"])
            ba_ar, ba_dd, ba_wr = p(bl["annual_return"]), p(bl["max_drawdown"]), p(bl["win_rate"])
            ok = []
            if ar and ba_ar and ba_ar != 0 and (ar - ba_ar) / abs(ba_ar) >= 0.05: ok.append("年化+5%")
            if dd and ba_dd and ba_dd != 0 and (dd - ba_dd) / abs(ba_dd) <= -0.05: ok.append("回撤-5%")
            if wr is not None and ba_wr is not None and wr - ba_wr >= 0.03: ok.append("胜率+3pct")

            lines.append(
                f"| {r['exp_label'][:22]:22s} | {r['annual_return']:>8s} | {d(ar, ba_ar):>8s} "
                f"| {r['max_drawdown']:>8s} | {d(dd, ba_dd, True):>8s} | {r['win_rate']:>8s} "
                f"| {d(wr, ba_wr):>8s} | {r['profit_factor']:>8s} | {r['total_trades']:>3d} "
                f"| {r['stop_loss']:>2d} | {';'.join(ok) if ok else '—'}"
            )
        lines.append("")

    out_path = os.path.join(OUT_DIR, "low_vol_ablation_report.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n报告: {out_path}")


if __name__ == "__main__":
    main()
