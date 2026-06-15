"""操作建议业务模型。

Example:
    OperationAdvice(code="588000", date=date(2026,4,25), position_id=1,
                    cost=1.2000, pnl_pct=0.0375, signal="HOLD",
                    advice="继续持有", signal_source="trend")
"""

from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class OperationAdvice(BaseModel):
    """单日操作建议，由信号与持仓交叉生成。

    signal_source: 建议来源 — "trend"（技术信号）或 "stop_loss"（止损触发）
    advice:        中文操作描述 — 建仓/加仓/持有/清仓/观望
    """
    code: str
    date: date
    signal: str
    advice: str
    position_id: int | None = None
    cost: float | None = None
    pnl_pct: float | None = None
    signal_source: str = ""
    target_position_ratio: float | None = None
    target_budget_ratio: float | None = None
    entry_add_step: int | None = None
    score: float | None = None
    market_state: str | None = None
    stop_loss_profile: str | None = None
    blocked_reason: str | None = None
    advice_meta: dict[str, Any] = Field(default_factory=dict)

    def to_orm(self):
        """转换为 ORM 对象。"""
        from src.database.schema.operation_advice import OperationAdviceOrm
        return OperationAdviceOrm(
            code=self.code,
            date=self.date,
            position_id=self.position_id,
            cost=Decimal(str(self.cost)) if self.cost is not None else None,
            pnl_pct=Decimal(str(self.pnl_pct)) if self.pnl_pct is not None else None,
            signal=self.signal,
            advice=self.advice,
            signal_source=self.signal_source,
            target_position_ratio=(
                Decimal(str(self.target_position_ratio))
                if self.target_position_ratio is not None else None
            ),
            target_budget_ratio=(
                Decimal(str(self.target_budget_ratio))
                if self.target_budget_ratio is not None else None
            ),
            entry_add_step=self.entry_add_step,
            score=Decimal(str(self.score)) if self.score is not None else None,
            market_state=self.market_state,
            stop_loss_profile=self.stop_loss_profile,
            blocked_reason=self.blocked_reason,
            advice_meta=self.advice_meta,
        )
