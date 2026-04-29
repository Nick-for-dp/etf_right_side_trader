"""策略信号业务模型。

Example:
    Signal(code="588000", date=date(2026,4,25), signal="BUY",
           strategy_version="1.0",
           signal_meta={"trend": "up", "cross": "golden", "ma20": 1.234, "ma60": 1.198})
"""

from datetime import date

from pydantic import BaseModel


class Signal(BaseModel):
    """单日策略信号。

    signal:            最终信号 — BUY / SELL / HOLD
    strategy_version:  产生此信号的策略版本号
    signal_meta:       策略决策依据，内容随版本变化。
                       MVP:    {"trend", "cross", "ma20", "ma60"}
                       v1.1:   {"macd_confirmed", ...}
                       v2.0:   {"score", "breakdown", ...}
    """
    code: str
    date: date
    signal: str
    strategy_version: str = ""
    signal_meta: dict = {}

    def to_orm(self):
        """转换为 ORM 对象。"""
        from src.database.schema.signals import SignalOrm
        return SignalOrm(
            code=self.code,
            date=self.date,
            signal=self.signal,
            strategy_version=self.strategy_version,
            signal_meta=self.signal_meta,
        )
