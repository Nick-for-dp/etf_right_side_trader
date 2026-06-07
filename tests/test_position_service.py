"""Position service cost-basis tests."""

from datetime import date

import src.service.position_service as svc
from src.models import Position


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
