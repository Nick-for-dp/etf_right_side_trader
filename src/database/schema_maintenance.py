"""Small schema compatibility helpers for existing local databases."""

from sqlalchemy import text
from sqlalchemy.engine import Engine


def ensure_operation_advice_columns(engine: Engine) -> None:
    """Add P0 advice-explanation columns to existing PostgreSQL databases."""
    statements = [
        "ALTER TABLE IF EXISTS operation_advice ADD COLUMN IF NOT EXISTS target_position_ratio NUMERIC(6, 4)",
        "ALTER TABLE IF EXISTS operation_advice ADD COLUMN IF NOT EXISTS target_budget_ratio NUMERIC(6, 4)",
        "ALTER TABLE IF EXISTS operation_advice ADD COLUMN IF NOT EXISTS entry_add_step INTEGER",
        "ALTER TABLE IF EXISTS operation_advice ADD COLUMN IF NOT EXISTS score NUMERIC(10, 4)",
        "ALTER TABLE IF EXISTS operation_advice ADD COLUMN IF NOT EXISTS market_state VARCHAR(20)",
        "ALTER TABLE IF EXISTS operation_advice ADD COLUMN IF NOT EXISTS stop_loss_profile VARCHAR(20)",
        "ALTER TABLE IF EXISTS operation_advice ADD COLUMN IF NOT EXISTS blocked_reason VARCHAR(80)",
        "ALTER TABLE IF EXISTS operation_advice ADD COLUMN IF NOT EXISTS advice_meta JSONB NOT NULL DEFAULT '{}'::jsonb",
    ]
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))
