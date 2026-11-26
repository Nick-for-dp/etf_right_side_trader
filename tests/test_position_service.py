"""Position service cost-basis tests."""

from datetime import date
from decimal import Decimal

import src.service.position_service as svc
from src.models import Position, TradeAction


def _patch_position_repo(monkeypatch, initial: Position | None = None) -> dict:
    state = {"position": initial, "deleted": None}

    def find_by_code(_code: str) -> Position | None:
        return state["position"]

    def save(pos: Position) -> Position:
        if pos.id is None:
            pos = pos.model_copy(update={"id": 1})
        state["position"] = pos
        return pos

    def delete_by_id(position_id: int) -> None:
        state["deleted"] = position_id
        state["position"] = None

    monkeypatch.setattr(svc.positions_repo, "find_by_code", find_by_code)
    monkeypatch.setattr(svc.positions_repo, "save", save)
    monkeypatch.setattr(svc.positions_repo, "delete_by_id", delete_by_id)
    return state


def test_add_recalculates_weighted_average_cost(monkeypatch):
    _patch_position_repo(monkeypatch)

    first = svc.PositionService.add("588000", 1.0, 1000, date(2026, 1, 1))
    second = svc.PositionService.add("588000", 1.2, 1000, date(2026, 1, 2))

    assert first.cost == 1.0
    assert second.cost == 1.1
    assert second.shares == 2000


def test_reduce_after_profit_lowers_remaining_break_even_cost(monkeypatch):
    _patch_position_repo(
        monkeypatch,
        Position(id=1, code="588000", cost=1.0, shares=1000, entry_date=date(2026, 1, 1)),
    )

    result = svc.PositionService.reduce("588000", 500, 1.2)

    assert result is not None
    assert result.shares == 500
    assert result.cost == 0.8


def test_reduce_after_loss_raises_remaining_break_even_cost(monkeypatch):
    _patch_position_repo(
        monkeypatch,
        Position(id=1, code="588000", cost=1.0, shares=1000, entry_date=date(2026, 1, 1)),
    )

    result = svc.PositionService.reduce("588000", 500, 0.8)

    assert result is not None
    assert result.shares == 500
    assert result.cost == 1.2


def test_reduce_all_shares_clears_position(monkeypatch):
    state = _patch_position_repo(
        monkeypatch,
        Position(id=7, code="588000", cost=1.0, shares=1000, entry_date=date(2026, 1, 1)),
    )

    result = svc.PositionService.reduce("588000", 1000, 1.1)

    assert result is None
    assert state["position"] is None
    assert state["deleted"] == 7


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
        self.added_positions = []
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
            self.added_positions.append(obj)
            self.position = obj

    def flush(self):
        if self.position is not None and self.position.id is None:
            self.position.id = 1

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True

    def delete(self, obj):
        self.position = None


def test_execute_buy_writes_position_and_trade_in_one_transaction(monkeypatch):
    fake_session = _FakeSession()
    monkeypatch.setattr(svc, "get_session", lambda: fake_session)

    position, action = svc.PositionService.execute_buy(
        "588000",
        price=1.0,
        shares=1000,
        trade_date=date(2026, 1, 1),
    )

    assert position.code == "588000"
    assert position.cost == 1.0
    assert position.shares == 1000
    assert action == TradeAction.BUY
    assert len(fake_session.added_positions) == 1
    assert len(fake_session.added_trades) == 1
    assert fake_session.commits == 1
    assert fake_session.rollbacks == 0
    assert fake_session.closed is True


def test_execute_buy_rolls_back_when_trade_record_fails(monkeypatch):
    fake_session = _FakeSession(fail_on_trade=True)
    monkeypatch.setattr(svc, "get_session", lambda: fake_session)

    try:
        svc.PositionService.execute_buy(
            "588000",
            price=1.0,
            shares=1000,
            trade_date=date(2026, 1, 1),
        )
    except RuntimeError as exc:
        assert str(exc) == "trade insert failed"
    else:
        raise AssertionError("expected RuntimeError")

    assert fake_session.commits == 0
    assert fake_session.rollbacks == 1
    assert fake_session.closed is True


def test_execute_sell_reduces_position_and_records_trade(monkeypatch):
    existing = svc.PositionOrm(
        id=7,
        code="588000",
        cost=Decimal("1.0"),
        shares=1000,
        entry_date=date(2026, 1, 1),
    )
    fake_session = _FakeSession(position=existing)
    monkeypatch.setattr(svc, "get_session", lambda: fake_session)

    position, action = svc.PositionService.execute_sell(
        "588000",
        price=1.2,
        shares=500,
        trade_date=date(2026, 1, 10),
    )

    assert position is not None
    assert position.shares == 500
    assert position.cost == 0.8
    assert action == TradeAction.REDUCE
    assert len(fake_session.added_trades) == 1
    assert fake_session.commits == 1
