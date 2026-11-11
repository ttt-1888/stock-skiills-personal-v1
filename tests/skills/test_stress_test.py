"""Tests for stress-test skill argument parsing (KIK-518)."""

import argparse
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add skill script directory to path
_SKILL_SCRIPTS = Path(__file__).resolve().parent.parent.parent / ".claude" / "skills" / "stress-test" / "scripts"
if str(_SKILL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SKILL_SCRIPTS))


class TestStressTestArgParsing:
    """Test argument parsing for the stress-test skill."""

    def test_portfolio_required(self):
        """--portfolio is required."""
        from run_stress_test import main

        with pytest.raises(SystemExit):
            with patch("sys.argv", ["run_stress_test.py"]):
                main()

    def test_parse_basic_args(self):
        """Parse basic --portfolio argument."""
        parser = argparse.ArgumentParser()
        parser.add_argument("--portfolio", required=True)
        parser.add_argument("--weights", default=None)
        parser.add_argument("--scenario", default=None)
        parser.add_argument("--base-shock", type=float, default=-0.20)

        args = parser.parse_args(["--portfolio", "7203.T,AAPL"])
        assert args.portfolio == "7203.T,AAPL"
        assert args.weights is None
        assert args.scenario is None
        assert args.base_shock == -0.20

    def test_parse_with_weights(self):
        """Parse --weights argument."""
        parser = argparse.ArgumentParser()
        parser.add_argument("--portfolio", required=True)
        parser.add_argument("--weights", default=None)
        parser.add_argument("--scenario", default=None)
        parser.add_argument("--base-shock", type=float, default=-0.20)

        args = parser.parse_args(["--portfolio", "7203.T,AAPL", "--weights", "0.6,0.4"])
        assert args.weights == "0.6,0.4"

    def test_parse_with_scenario(self):
        """Parse --scenario argument."""
        parser = argparse.ArgumentParser()
        parser.add_argument("--portfolio", required=True)
        parser.add_argument("--weights", default=None)
        parser.add_argument("--scenario", default=None)
        parser.add_argument("--base-shock", type=float, default=-0.20)

        args = parser.parse_args(["--portfolio", "7203.T", "--scenario", "トリプル安"])
        assert args.scenario == "トリプル安"

    def test_parse_custom_shock(self):
        """Parse --base-shock argument."""
        parser = argparse.ArgumentParser()
        parser.add_argument("--portfolio", required=True)
        parser.add_argument("--weights", default=None)
        parser.add_argument("--scenario", default=None)
        parser.add_argument("--base-shock", type=float, default=-0.20)

        args = parser.parse_args(["--portfolio", "7203.T", "--base-shock", "-0.30"])
        assert args.base_shock == pytest.approx(-0.30)


class TestLoadPortfolio:
    """Test load_portfolio with mocked yahoo_client."""

    def test_load_single_stock(self, stock_info_data, mock_yahoo_client):
        from run_stress_test import load_portfolio

        mock_yahoo_client.get_stock_info.return_value = stock_info_data
        mock_yahoo_client.get_price_history.return_value = None

        result = load_portfolio(["7203.T"], [1.0])
        assert len(result) == 1
        assert result[0]["weight"] == 1.0

    def test_load_skips_failed_symbols(self, mock_yahoo_client):
        from run_stress_test import load_portfolio

        mock_yahoo_client.get_stock_info.return_value = None
        mock_yahoo_client.get_price_history.return_value = None

        result = load_portfolio(["INVALID"], [1.0])
        assert len(result) == 0

    def test_load_multiple_stocks(self, stock_info_data, mock_yahoo_client):
        from run_stress_test import load_portfolio

        # Return data for first call, None for second
        mock_yahoo_client.get_stock_info.side_effect = [stock_info_data, stock_info_data]
        mock_yahoo_client.get_price_history.return_value = None

        result = load_portfolio(["7203.T", "AAPL"], [0.6, 0.4])
        assert len(result) == 2
        assert result[0]["weight"] == 0.6
        assert result[1]["weight"] == 0.4


def test_local_only_skips_context_suggestions_and_raw_data(monkeypatch, capsys, tmp_path):
    import run_stress_test as stress_test

    def unexpected_call(*args, **kwargs):
        pytest.fail("AI context and suggestions must be skipped in local-only mode")

    concentration = {
        "sector_hhi": 1.0,
        "region_hhi": 1.0,
        "currency_hhi": 1.0,
        "max_hhi_axis": "sector",
        "max_hhi": 1.0,
        "concentration_multiplier": 1.0,
        "risk_level": "危険な集中",
        "sector_breakdown": {},
        "region_breakdown": {},
        "currency_breakdown": {},
    }
    saved = {}
    monkeypatch.setattr(stress_test, "print_context", unexpected_call)
    monkeypatch.setattr(stress_test, "print_suggestions", unexpected_call)
    monkeypatch.setattr(
        stress_test,
        "load_portfolio",
        lambda symbols, weights: [{"symbol": "7203.T", "weight": 1.0}],
    )
    monkeypatch.setattr(stress_test, "analyze_concentration", lambda *args: concentration)
    monkeypatch.setattr(stress_test, "analyze_stock_sensitivity", None)
    monkeypatch.setattr(stress_test, "_fallback_print_portfolio_summary", lambda *args: None)
    monkeypatch.setattr(stress_test, "_fallback_print_concentration", lambda *args: None)
    monkeypatch.setattr(stress_test, "_fallback_print_shock_sensitivity", lambda *args: None)
    monkeypatch.setattr(stress_test, "resolve_scenario", None)
    monkeypatch.setattr(stress_test, "analyze_portfolio_scenario", None)
    monkeypatch.setattr(stress_test, "compute_correlation_matrix", None)
    monkeypatch.setattr(stress_test, "compute_var", None)
    monkeypatch.setattr(stress_test, "generate_recommendations", None)
    monkeypatch.setattr(stress_test, "format_full_stress_report", None)
    monkeypatch.setattr(stress_test, "HAS_HISTORY", True)

    def save_locally(**kwargs):
        saved.update(kwargs)

    monkeypatch.setattr(stress_test, "_save_stress_test", save_locally)
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_stress_test.py",
            "--portfolio",
            "7203.T",
            "--local-only",
            "--history-dir",
            str(tmp_path),
        ],
    )

    stress_test.main()

    output = capsys.readouterr().out
    assert "分析用生データ (JSON)" not in output
    assert "Claude" not in output
    assert saved["sync_external"] is False
    assert saved["base_dir"] == str(tmp_path)
