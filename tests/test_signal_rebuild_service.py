"""signals 重建服务测试。"""

from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace

from src.config.settings_reader import AppConfig, EtfItem
from src.service import signal_rebuild_service as svc


@dataclass
class _Indicator:
    code: str
    date: date
    data: dict


@dataclass
class _Quote:
    code: str
    date: date
    close: float


def _config() -> AppConfig:
    return AppConfig(
        etf_list=[EtfItem(symbol="AAA", name="AAA")],
        db_url="postgresql://unused",
        strategy_type="multi_indicator_scoring",
        strategy_params={},
    )


class _Strategy:
    def generate(self, df):
        return df[["code", "date"]].assign(
            signal=["BUY", "HOLD"],
            strategy_version="test",
            signal_meta=[{"score": 80}, {"score": 0}],
        )


def test_rebuild_signals_dry_run_does_not_delete_or_save(monkeypatch):
    calls = []
    monkeypatch.setattr(svc, "create_strategy", lambda _config: _Strategy())
    monkeypatch.setattr(
        svc.indicators_repo,
        "find_by_code_between",
        lambda code, start, end: [
            _Indicator(code, date(2026, 1, 1), {"ma20": 1}),
            _Indicator(code, date(2026, 1, 2), {"ma20": 1}),
        ],
    )
    monkeypatch.setattr(
        svc.quote_repo,
        "find_by_code_in_range",
        lambda code, start, end: [
            _Quote(code, date(2026, 1, 1), 1.0),
            _Quote(code, date(2026, 1, 2), 1.0),
        ],
    )
    monkeypatch.setattr(svc.signals_repo, "count_by_codes_between", lambda codes, start, end: 9)
    monkeypatch.setattr(svc.advice_repo, "count_by_codes_between", lambda codes, start, end: 3)
    monkeypatch.setattr(svc.signals_repo, "delete_by_codes_between", lambda *args: calls.append("delete"))
    monkeypatch.setattr(svc.signals_repo, "save_batch", lambda records: calls.append("save"))

    result = svc.rebuild_signals(
        _config(),
        start=date(2026, 1, 1),
        end=date(2026, 1, 2),
        dry_run=True,
    )

    assert result.before_signals == 9
    assert result.saved_signals == 2
    assert dict(result.signal_counts) == {"BUY": 1, "HOLD": 1}
    assert calls == []


def test_rebuild_signals_execute_deletes_then_saves(monkeypatch):
    calls = []
    monkeypatch.setattr(svc, "create_strategy", lambda _config: _Strategy())
    monkeypatch.setattr(
        svc.indicators_repo,
        "find_by_code_between",
        lambda code, start, end: [
            _Indicator(code, date(2026, 1, 1), {"ma20": 1}),
            _Indicator(code, date(2026, 1, 2), {"ma20": 1}),
        ],
    )
    monkeypatch.setattr(
        svc.quote_repo,
        "find_by_code_in_range",
        lambda code, start, end: [
            _Quote(code, date(2026, 1, 1), 1.0),
            _Quote(code, date(2026, 1, 2), 1.0),
        ],
    )
    monkeypatch.setattr(svc.signals_repo, "count_by_codes_between", lambda codes, start, end: 9)
    monkeypatch.setattr(svc.advice_repo, "count_by_codes_between", lambda codes, start, end: 3)
    monkeypatch.setattr(
        svc.signals_repo,
        "delete_by_codes_between",
        lambda codes, start, end: calls.append(("delete_signals", codes, start, end)) or 9,
    )
    monkeypatch.setattr(
        svc.signals_repo,
        "save_batch",
        lambda records: calls.append(("save_signals", len(records))),
    )
    monkeypatch.setattr(svc.advice_repo, "delete_by_codes_between", lambda *args: 0)

    result = svc.rebuild_signals(
        _config(),
        start=date(2026, 1, 1),
        end=date(2026, 1, 2),
        dry_run=False,
        rebuild_latest_advice=False,
    )

    assert result.deleted_signals == 9
    assert result.saved_signals == 2
    assert calls == [
        ("delete_signals", ["AAA"], date(2026, 1, 1), date(2026, 1, 2)),
        ("save_signals", 2),
    ]
