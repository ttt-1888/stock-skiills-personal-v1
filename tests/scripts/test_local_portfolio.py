import json
from types import SimpleNamespace
from unittest.mock import patch

from scripts import local_portfolio
from src.core.portfolio.portfolio_io import load_portfolio, save_portfolio


def test_buy_without_confirmation_only_prints_preview(tmp_path, capsys):
    csv_path = tmp_path / "portfolio.csv"
    args = SimpleNamespace(
        csv=str(csv_path),
        history_dir=str(tmp_path / "history"),
        symbol="7203.T",
        shares=10,
        price=2850.0,
        currency="JPY",
        date="2026-01-15",
        memo="test memo",
        confirm=False,
    )

    local_portfolio._buy(args)

    assert not csv_path.exists()
    assert not (tmp_path / "history").exists()
    assert "プレビュー" in capsys.readouterr().out


def test_confirmed_buy_saves_locally_without_external_sync(tmp_path):
    csv_path = tmp_path / "portfolio.csv"
    history_dir = tmp_path / "history"
    args = SimpleNamespace(
        csv=str(csv_path),
        history_dir=str(history_dir),
        symbol="7203.T",
        shares=10,
        price=2850.0,
        currency="JPY",
        date="2026-01-15",
        memo="test memo",
        confirm=True,
    )

    with patch(
        "src.data.history.save_trade._dual_write_graph",
        side_effect=AssertionError("external sync must not run"),
    ) as graph_write:
        local_portfolio._buy(args)

    assert load_portfolio(str(csv_path))[0]["shares"] == 10
    trade_files = list((history_dir / "trade").glob("*.json"))
    assert len(trade_files) == 1
    assert json.loads(trade_files[0].read_text(encoding="utf-8"))["memo"] == "test memo"
    graph_write.assert_not_called()


def test_confirmed_sell_saves_locally_without_external_sync(tmp_path):
    csv_path = tmp_path / "portfolio.csv"
    history_dir = tmp_path / "history"
    save_portfolio(
        [{
            "symbol": "AAPL",
            "shares": 8,
            "cost_price": 150.0,
            "cost_currency": "USD",
            "purchase_date": "2025-01-01",
            "memo": "",
        }],
        str(csv_path),
    )
    args = SimpleNamespace(
        csv=str(csv_path),
        history_dir=str(history_dir),
        symbol="AAPL",
        shares=3,
        price=180.0,
        date="2026-01-15",
        confirm=True,
    )

    with patch(
        "src.data.history.save_trade._dual_write_graph",
        side_effect=AssertionError("external sync must not run"),
    ) as graph_write:
        local_portfolio._sell(args)

    assert load_portfolio(str(csv_path))[0]["shares"] == 5
    trade_files = list((history_dir / "trade").glob("*.json"))
    assert len(trade_files) == 1
    trade = json.loads(trade_files[0].read_text(encoding="utf-8"))
    assert trade["realized_pnl"] == 90.0
    graph_write.assert_not_called()


def test_stress_test_forwards_local_only_and_history_dir(tmp_path):
    args = SimpleNamespace(
        symbols="7203.T,AAPL",
        weights="0.6,0.4",
        scenario="トリプル安",
        base_shock=-0.3,
        history_dir=str(tmp_path / "history"),
    )
    with patch("scripts.local_portfolio.subprocess.run") as run:
        local_portfolio._stress_test(args)

    command = run.call_args.args[0]
    assert "--local-only" in command
    assert "--history-dir" in command
    assert args.history_dir in command
    assert "--weights" in command
