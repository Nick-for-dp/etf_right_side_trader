"""既有本机数据库的幂等 schema 迁移。

不引入 alembic：所有变更写成 ADD COLUMN IF NOT EXISTS / DROP COLUMN IF EXISTS
一类的幂等语句，init / 每日流程 / dashboard 启动时调用一次即可。

对应 v2026-final：
- operation_advice 的解释性列
- positions 的 first_entry_date / add_count
- quote 删除 nav / premium_rate
- indicators.data 删除 odds_* 键
"""

from sqlalchemy import text
from sqlalchemy.engine import Engine


def ensure_schema(engine: Engine) -> None:
    """执行全部幂等迁移。"""
    statements = [
        # operation_advice 解释性列
        "ALTER TABLE IF EXISTS operation_advice ADD COLUMN IF NOT EXISTS target_position_ratio NUMERIC(6, 4)",
        "ALTER TABLE IF EXISTS operation_advice ADD COLUMN IF NOT EXISTS target_budget_ratio NUMERIC(6, 4)",
        "ALTER TABLE IF EXISTS operation_advice ADD COLUMN IF NOT EXISTS entry_add_step INTEGER",
        "ALTER TABLE IF EXISTS operation_advice ADD COLUMN IF NOT EXISTS score NUMERIC(10, 4)",
        "ALTER TABLE IF EXISTS operation_advice ADD COLUMN IF NOT EXISTS market_state VARCHAR(20)",
        "ALTER TABLE IF EXISTS operation_advice ADD COLUMN IF NOT EXISTS stop_loss_profile VARCHAR(20)",
        "ALTER TABLE IF EXISTS operation_advice ADD COLUMN IF NOT EXISTS blocked_reason VARCHAR(80)",
        "ALTER TABLE IF EXISTS operation_advice ADD COLUMN IF NOT EXISTS advice_meta JSONB NOT NULL DEFAULT '{}'::jsonb",

        # positions：首次建仓日 / 加仓次数
        "ALTER TABLE IF EXISTS positions ADD COLUMN IF NOT EXISTS first_entry_date DATE",
        "ALTER TABLE IF EXISTS positions ADD COLUMN IF NOT EXISTS add_count INTEGER NOT NULL DEFAULT 0",
        "UPDATE positions SET first_entry_date = entry_date WHERE first_entry_date IS NULL",

        # quote：删除 NAV 与溢价率
        "ALTER TABLE IF EXISTS quote DROP COLUMN IF EXISTS nav",
        "ALTER TABLE IF EXISTS quote DROP COLUMN IF EXISTS premium_rate",
    ]
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))


def purge_indicator_odds_keys(engine: Engine) -> int:
    """删除 indicators.data 中的 odds_* 键，返回受影响行数。"""
    with engine.begin() as conn:
        result = conn.execute(text(
            """
            UPDATE indicators
            SET data = COALESCE(
                (SELECT jsonb_object_agg(key, value)
                 FROM jsonb_each(data)
                 WHERE key NOT LIKE 'odds_%'),
                '{}'::jsonb
            )
            WHERE EXISTS (
                SELECT 1 FROM jsonb_each(data) WHERE key LIKE 'odds_%'
            )
            """
        ))
        return result.rowcount


# 兼容旧调用点
ensure_operation_advice_columns = ensure_schema
