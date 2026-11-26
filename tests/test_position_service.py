"""Position service 记账口径测试。

保本价 = 剩余持仓买入成本 / 剩余份额；减仓不改变保本价。
entry_date = 最近一次买入（加仓冷却）；first_entry_date = 本轮首次建仓（持有上限）；
add_count = 本轮已加仓次数，清仓后归零。
"""

from datetime import date
from decimal import Decimal

import src.service.position_service as svc
from src.models import TradeAction


class _FakeQuery:
    def __init__(self, position):
        self.position = position

    def filter(self, *_args):
        return self

    def with_for_update(self):
        return self

    def first(self):
        return self.position


class _FakeSession:
    def __init__(self, position=None, fail_on_trade=False):
        self.position = position
        self.fail_on_trade = fail_on_trade
        self.added_trades = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def query(self, _model):
        return _FakeQuery(self.position)

    def add(self, obj):
        if obj.__class__.__name__ == "TradeRecordOrm":
            if self.fail_on_trade:
                raise RuntimeError("trade insert failed")
            self.added_trades.append(obj)
        else:
            self.position = obj

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True

    def delete(self, obj):
        self.position = None


def _use_session(monkeypatch, session: _FakeSession) -> _FakeSession:
    monkeypatch.setattr(svc, "get_session", lambda: session)
    return session


def _orm(code="588000", cost="1.0", shares=1000, entry=date(2026, 1, 1), add_count=0):
    return svc.PositionOrm(
        id=7, code=code, cost=Decimal(cost), shares=shares,
        entry_date=entry, first_entry_date=entry, add_count=add_count,
    )


def test_first_buy_sets_first_entry_and_zero_add_count(monkeypatch):
    session = _use_session(monkeypatch, _FakeSession())

    position, action = svc.PositionService.execute_buy(
        "588000", price=1.0, shares=1000, trade_date=date(2026, 1, 1),
    )

    assert action == TradeAction.BUY
    assert position.cost == 1.0
    assert position.first_entry_date == date(2026, 1, 1)
    assert position.add_count == 0
    assert len(session.added_trades) == 1
    assert session.commits == 1


def test_add_recalculates_cost_and_counters(monkeypatch):
    session = _use_session(monkeypatch, _FakeSession(position=_orm(cost="1.0", shares=1000)))

    position, action = svc.PositionService.execute_buy(
        "588000", price=1.2, shares=1000, trade_date=date(2026, 1, 2),
    )

    assert action == TradeAction.ADD
    assert position.cost == 1.1
    assert position.shares == 2000
    assert position.entry_date == date(2026, 1, 2)
    assert position.first_entry_date == date(2026, 1, 1)
    assert position.add_count == 1
    assert session.commits == 1


def test_reduce_keeps_cost_basis(monkeypatch):
    session = _use_session(monkeypatch, _FakeSession(position=_orm(cost="1.0", shares=1000)))

    position, action = svc.PositionService.execute_sell(
        "588000", price=1.2, shares=500, trade_date=date(2026, 1, 10),
    )

    assert action == TradeAction.REDUCE
    assert position is not None
    assert position.shares == 500
    assert position.cost == 1.0
    assert len(session.added_trades) == 1


def test_reduce_all_shares_clears_position(monkeypatch):
    session = _use_session(monkeypatch, _FakeSession(position=_orm(shares=1000)))

    position, action = svc.PositionService.execute_sell(
        "588000", price=1.1, shares=1000, trade_date=date(2026, 1, 10),
    )

    assert action == TradeAction.SELL
    assert position is None
    assert session.position is None
    assert len(session.added_trades) == 1


def test_buy_rolls_back_when_trade_record_fails(monkeypatch):
    session = _use_session(monkeypatch, _FakeSession(fail_on_trade=True))

    try:
        svc.PositionService.execute_buy(
            "588000", price=1.0, shares=1000, trade_date=date(2026, 1, 1),
        )
    except RuntimeError as exc:
        assert str(exc) == "trade insert failed"
    else:
        raise AssertionError("expected RuntimeError")

    assert session.commits == 0
    assert session.rollbacks == 1
    assert session.closed is True
