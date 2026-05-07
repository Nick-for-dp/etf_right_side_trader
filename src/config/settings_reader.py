"""读取 settings.yaml 和 .env，校验后返回 AppConfig。"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv


_VALID_STRATEGY_TYPES = {"ma_cross", "ma_cross_macd"}
_VALID_DB_DRIVERS = {"postgresql", "mysql"}


@dataclass
class EtfItem:
    """ETF 配置项。"""

    symbol: str
    name: str = ""
    category: str = "broad"


@dataclass
class AppConfig:
    """应用配置，聚合所有运行期参数。"""

    etf_list: list[EtfItem]
    db_url: str
    strategy_type: str
    strategy_params: dict = field(default_factory=dict)
    risk_rules: list[dict] = field(default_factory=list)
    lookback_days: int = 400
    scheduler_run_time: str = "07:00"
    scheduler_timezone: str = "Asia/Shanghai"


# ── 校验 ──

def _validate_etf_list(raw: list) -> list[EtfItem]:
    """校验并转换 ETF 配置列表。"""
    if not raw:
        raise ValueError("etf_list 不能为空")
    items = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"etf_list[{i}] 需为 dict")
        if "symbol" not in item:
            raise ValueError(f"etf_list[{i}] 缺少必填字段 symbol")
        items.append(EtfItem(
            symbol=str(item["symbol"]),
            name=item.get("name", ""),
            category=item.get("category", "broad"),
        ))
    return items


def _build_db_url(driver: str) -> str:
    """从环境变量构建数据库连接 URL。"""
    env_vars = ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"]
    vals = {}
    for v in env_vars:
        vals[v] = os.getenv(v, "")
        if not vals[v]:
            raise ValueError(f".env 缺少必填变量: {v}")
    return f"{driver}://{vals['DB_USER']}:{vals['DB_PASSWORD']}@{vals['DB_HOST']}:{vals['DB_PORT']}/{vals['DB_NAME']}"


def _validate_strategy(raw: dict) -> tuple[str, dict]:
    """校验策略配置，返回 (策略类型, 参数字典)。"""
    stype = raw.get("type", "")
    if stype not in _VALID_STRATEGY_TYPES:
        raise ValueError(f"strategy.type 无效: {stype}，仅支持 {_VALID_STRATEGY_TYPES}")
    params = raw.get("params", {})
    if stype in ("ma_cross", "ma_cross_macd"):
        ms = params.get("ma_short", 20)
        ml = params.get("ma_long", 60)
        if not (isinstance(ms, int) and isinstance(ml, int) and 0 < ms < ml):
            raise ValueError(f"{stype} 需 0 < ma_short < ma_long，实际: {ms}, {ml}")
        params = {"ma_short": ms, "ma_long": ml}
    return stype, params


def _validate_risk_rules(raw: list) -> list[dict]:
    """校验风控规则列表。"""
    rules = []
    for i, rule in enumerate(raw):
        if not isinstance(rule, dict):
            raise ValueError(f"risk_control.rules[{i}] 需为 dict")
        rtype = rule.get("type", "")
        rparams = rule.get("params", {})
        if not rtype:
            raise ValueError(f"risk_control.rules[{i}] 缺少 type")
        if rtype == "stop_loss":
            threshold = rparams.get("threshold")
            if not isinstance(threshold, (int, float)) or threshold >= 0:
                raise ValueError(f"stop_loss.threshold 需 < 0，实际: {threshold}")
        if rtype == "trailing_stop":
            profit = rparams.get("profit_threshold")
            drawdown = rparams.get("drawdown_threshold")
            if not isinstance(profit, (int, float)) or profit <= 0:
                raise ValueError(
                    f"trailing_stop.profit_threshold 需 > 0，实际: {profit}"
                )
            if not isinstance(drawdown, (int, float)) or drawdown <= 0:
                raise ValueError(
                    f"trailing_stop.drawdown_threshold 需 > 0，实际: {drawdown}"
                )
        rules.append({"type": rtype, "params": rparams})
    return rules


def _validate_lookback_days(raw: dict) -> int:
    """校验回看天数配置。"""
    val = raw.get("lookback_days", 120)
    if not isinstance(val, int) or val < 60:
        raise ValueError(f"data.lookback_days 需 ≥ 60，实际: {val}")
    return val


def _validate_scheduler(raw: dict) -> tuple[str, str]:
    """校验调度器配置，返回 (执行时间, 时区)。"""
    run_time = raw.get("run_time", "07:00")
    timezone = raw.get("timezone", "Asia/Shanghai")
    if not re.fullmatch(r"\d{2}:\d{2}", str(run_time)):
        raise ValueError(f"scheduler.run_time 格式需为 HH:MM，实际: {run_time}")
    return str(run_time), str(timezone)


# ── 主入口 ──

def load_config(path: str | Path = "settings.yaml") -> AppConfig:
    """加载 settings.yaml + .env，校验后返回 AppConfig。

    Args:
        path: 配置文件路径，默认 "settings.yaml"

    Returns:
        校验通过的 AppConfig 实例

    Example:
        >>> config = load_config()
        >>> print(config.strategy_type)
        'ma_cross'
    """

    load_dotenv(override=False)

    yaml_path = Path(path)
    if not yaml_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {yaml_path.resolve()}")

    with open(yaml_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    database = raw.get("database", {})
    driver = database.get("driver", "postgresql")
    if driver not in _VALID_DB_DRIVERS:
        raise ValueError(f"database.driver 无效: {driver}，仅支持 {_VALID_DB_DRIVERS}")

    stype, sparams = _validate_strategy(raw.get("strategy", {}))
    run_time, timezone = _validate_scheduler(raw.get("scheduler", {}))

    return AppConfig(
        etf_list=_validate_etf_list(raw.get("etf_list", [])),
        db_url=_build_db_url(driver),
        strategy_type=stype,
        strategy_params=sparams,
        risk_rules=_validate_risk_rules(raw.get("risk_control", {}).get("rules", [])),
        lookback_days=_validate_lookback_days(raw.get("data", {})),
        scheduler_run_time=run_time,
        scheduler_timezone=timezone,
    )


if __name__ == "__main__":
    config = load_config()
    print(config)
