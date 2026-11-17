import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

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


def test_default_data_path_is_outside_project_workspace():
    args = local_portfolio.build_parser().parse_args(["list"])

    assert local_portfolio.PROJECT_ROOT not in Path(args.csv).parents


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


def test_buy_rolls_back_trade_history_when_portfolio_write_fails(tmp_path):
    history_dir = tmp_path / "history"
    args = SimpleNamespace(
        csv=str(tmp_path / "portfolio.csv"),
        history_dir=str(history_dir),
        symbol="7203.T",
        shares=10,
        price=2850.0,
        currency="JPY",
        date="2026-01-15",
        memo="synthetic memo",
        confirm=True,
    )

    with patch(
        "scripts.local_portfolio.add_position",
        side_effect=OSError("synthetic write failure"),
    ), pytest.raises(OSError, match="synthetic write failure"):
        local_portfolio._buy(args)

    assert list((history_dir / "trade").glob("*.json")) == []


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


def test_backup_and_restore_round_trip_synthetic_data(tmp_path):
    csv_path = tmp_path / "portfolio.csv"
    history_dir = tmp_path / "history"
    notes_dir = tmp_path / "notes"
    save_portfolio(
        [{
            "symbol": "7203.T",
            "shares": 3,
            "cost_price": 100.0,
            "cost_currency": "JPY",
            "purchase_date": "2026-01-01",
            "memo": "synthetic",
        }],
        str(csv_path),
    )
    (history_dir / "trade").mkdir(parents=True)
    (history_dir / "trade" / "synthetic.json").write_text(
        '{"memo": "synthetic"}', encoding="utf-8"
    )
    (notes_dir).mkdir()
    (notes_dir / "synthetic.json").write_text(
        '{"content": "synthetic"}', encoding="utf-8"
    )
    backup_path = tmp_path / "backup.zip"
    args = SimpleNamespace(
        csv=str(csv_path),
        history_dir=str(history_dir),
        notes_dir=str(notes_dir),
        output=str(backup_path),
    )

    local_portfolio._backup(args)
    csv_path.write_text("changed", encoding="utf-8")
    (history_dir / "trade" / "synthetic.json").unlink()
    (notes_dir / "synthetic.json").unlink()
    restore_args = SimpleNamespace(
        csv=str(csv_path),
        history_dir=str(history_dir),
        notes_dir=str(notes_dir),
        backup=str(backup_path),
        confirm=True,
    )

    local_portfolio._restore(restore_args)

    assert load_portfolio(str(csv_path))[0]["memo"] == "synthetic"
    assert json.loads(
        (history_dir / "trade" / "synthetic.json").read_text(encoding="utf-8")
    )["memo"] == "synthetic"
    assert json.loads(
        (notes_dir / "synthetic.json").read_text(encoding="utf-8")
    )["content"] == "synthetic"


def test_backup_removes_temporary_archive_when_finalization_fails(tmp_path):
    output = tmp_path / "backup.zip"
    args = SimpleNamespace(
        csv=str(tmp_path / "portfolio.csv"),
        history_dir=str(tmp_path / "history"),
        notes_dir=str(tmp_path / "notes"),
        output=str(output),
    )

    with patch(
        "scripts.local_portfolio.os.replace",
        side_effect=OSError("synthetic replace failure"),
    ), pytest.raises(OSError, match="synthetic replace failure"):
        local_portfolio._backup(args)

    assert not output.exists()
    assert list(tmp_path.glob(".backup.zip.*.tmp")) == []


def test_backup_excludes_temporary_archive_inside_source_directory(tmp_path):
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    (history_dir / "synthetic.json").write_text(
        '{"memo": "synthetic"}', encoding="utf-8"
    )
    output = history_dir / "backup.zip"
    args = SimpleNamespace(
        csv=str(tmp_path / "portfolio.csv"),
        history_dir=str(history_dir),
        notes_dir=str(tmp_path / "notes"),
        output=str(output),
    )

    local_portfolio._backup(args)

    from zipfile import ZipFile

    with ZipFile(output) as archive:
        assert set(archive.namelist()) == {"history/synthetic.json", "manifest.json"}


def test_restore_rejects_path_traversal(tmp_path):
    from zipfile import ZipFile

    backup_path = tmp_path / "malicious.zip"
    with ZipFile(backup_path, "w") as archive:
        archive.writestr("manifest.json", '{"version": 1, "files": ["history/../outside"]}')
        archive.writestr("history/../outside", "synthetic")
    args = SimpleNamespace(
        csv=str(tmp_path / "portfolio.csv"),
        history_dir=str(tmp_path / "history"),
        notes_dir=str(tmp_path / "notes"),
        backup=str(backup_path),
        confirm=True,
    )

    with pytest.raises(ValueError, match="不正なバックアップ内パス"):
        local_portfolio._restore(args)


def test_restore_rejects_non_object_manifest(tmp_path):
    from zipfile import ZipFile

    backup_path = tmp_path / "invalid-manifest.zip"
    with ZipFile(backup_path, "w") as archive:
        archive.writestr("manifest.json", "[]")
    args = SimpleNamespace(
        csv=str(tmp_path / "portfolio.csv"),
        history_dir=str(tmp_path / "history"),
        notes_dir=str(tmp_path / "notes"),
        backup=str(backup_path),
        confirm=True,
    )

    with pytest.raises(ValueError, match="バックアップ形式が不正"):
        local_portfolio._restore(args)


def test_restore_rejects_symlink_in_target_path(tmp_path, monkeypatch):
    from zipfile import ZipFile

    backup_path = tmp_path / "symlink-target.zip"
    with ZipFile(backup_path, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps({"version": 1, "files": ["notes/linked/note.json"]}),
        )
        archive.writestr("notes/linked/note.json", "synthetic")
    notes_dir = tmp_path / "notes"
    notes_dir.mkdir()
    linked_dir = notes_dir / "linked"
    original_is_symlink = Path.is_symlink

    def is_symlink(path):
        return path == linked_dir or original_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", is_symlink)
    args = SimpleNamespace(
        csv=str(tmp_path / "portfolio.csv"),
        history_dir=str(tmp_path / "history"),
        notes_dir=str(notes_dir),
        backup=str(backup_path),
        confirm=True,
    )

    with pytest.raises(ValueError, match="復元先にシンボリックリンク"):
        local_portfolio._restore(args)


def test_restore_rejects_symlinked_ancestor_of_target_root(tmp_path, monkeypatch):
    from zipfile import ZipFile

    backup_path = tmp_path / "symlink-ancestor.zip"
    with ZipFile(backup_path, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps({"version": 1, "files": ["notes/note.json"]}),
        )
        archive.writestr("notes/note.json", "synthetic")
    notes_dir = tmp_path / "notes"
    notes_dir.mkdir()
    original_is_symlink = Path.is_symlink
    symlinked_ancestor = tmp_path

    def is_symlink(path):
        return path == symlinked_ancestor or original_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", is_symlink)
    args = SimpleNamespace(
        csv=str(tmp_path / "portfolio.csv"),
        history_dir=str(tmp_path / "history"),
        notes_dir=str(notes_dir),
        backup=str(backup_path),
        confirm=True,
    )

    with pytest.raises(ValueError, match="復元先にシンボリックリンク"):
        local_portfolio._restore(args)
