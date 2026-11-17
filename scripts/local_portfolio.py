#!/usr/bin/env python3
"""Run personal portfolio operations directly in a local terminal.

Do not invoke this script through an AI assistant: its output may contain
holdings, transaction details, and investment notes.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.portfolio.portfolio_io import (  # noqa: E402
    add_position,
    load_portfolio,
    sell_position,
)
from src.data import yahoo_client  # noqa: E402
from src.data.private_storage import private_data_dir  # noqa: E402
from src.data.history.save_trade import save_trade  # noqa: E402
from src.output.portfolio_formatter import format_position_list, format_snapshot  # noqa: E402
from src.core.portfolio.portfolio_query import get_snapshot  # noqa: E402

PRIVATE_DATA_DIR = private_data_dir()
DEFAULT_PORTFOLIO_PATH = PRIVATE_DATA_DIR / "portfolio.csv"
DEFAULT_HISTORY_DIR = PRIVATE_DATA_DIR / "history"
DEFAULT_NOTES_DIR = PRIVATE_DATA_DIR / "notes"
DEFAULT_BACKUP_DIR = PRIVATE_DATA_DIR / "backups"
STRESS_TEST_SCRIPT = (
    PROJECT_ROOT
    / ".claude"
    / "skills"
    / "stress-test"
    / "scripts"
    / "run_stress_test.py"
)


def _format_snapshot(snapshot: dict) -> str:
    data = {
        "timestamp": snapshot.get("as_of", ""),
        "positions": [
            {
                "symbol": pos["symbol"],
                "memo": pos.get("memo") or pos.get("name") or "",
                "shares": pos["shares"],
                "cost_price": pos["cost_price"],
                "current_price": pos.get("current_price"),
                "market_value_jpy": pos.get("evaluation_jpy"),
                "pnl_jpy": pos.get("pnl_jpy"),
                "pnl_pct": pos.get("pnl_pct"),
                "currency": pos.get("market_currency") or pos.get("cost_currency", "JPY"),
            }
            for pos in snapshot.get("positions", [])
        ],
        "total_market_value_jpy": snapshot.get("total_value_jpy"),
        "total_cost_jpy": snapshot.get("total_cost_jpy"),
        "total_pnl_jpy": snapshot.get("total_pnl_jpy"),
        "total_pnl_pct": snapshot.get("total_pnl_pct"),
        "fx_rates": {
            f"{currency}/JPY": rate
            for currency, rate in snapshot.get("fx_rates", {}).items()
            if currency != "JPY"
        },
    }
    return format_snapshot(data)


def _show_list(csv_path: str) -> None:
    holdings = load_portfolio(csv_path)
    if not holdings:
        print("ポートフォリオにデータがありません。")
        return
    print(format_position_list(holdings))


def _show_snapshot(csv_path: str) -> None:
    try:
        snapshot = get_snapshot(csv_path, yahoo_client)
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(f"スナップショットを作成できません: {exc}") from exc
    if not snapshot.get("positions"):
        print("ポートフォリオにデータがありません。")
        return
    print(_format_snapshot(snapshot))
    print("価格・為替取得に利用した銘柄コードはYahoo Financeへ送信されます。")


def _confirm_or_preview(lines: list[str], confirm: bool) -> bool:
    if confirm:
        return True
    print("\n".join(lines))
    print("\n記録するには --confirm を付けて、コマンドを再実行してください。")
    return False


def _record_trade(save_position, **trade) -> tuple[dict, str]:
    history_path = Path(save_trade(sync_external=False, **trade))
    try:
        updated = save_position()
    except Exception as exc:
        try:
            history_path.unlink()
        except OSError as cleanup_error:
            raise RuntimeError(
                f"ポートフォリオ更新に失敗し、履歴も削除できませんでした: "
                f"{history_path}"
            ) from cleanup_error
        raise
    return updated, str(history_path)


def _buy(args: argparse.Namespace) -> None:
    trade_date = args.date or date.today().isoformat()
    total = args.shares * args.price
    preview = [
        "購入記録のプレビュー",
        f"銘柄: {args.symbol}",
        f"株数: {args.shares:,}",
        f"購入単価: {args.price:,.4f} {args.currency}",
        f"購入日: {trade_date}",
        f"合計: {total:,.2f} {args.currency}",
        f"メモ: {args.memo or '(なし)'}",
    ]
    if not _confirm_or_preview(preview, args.confirm):
        return

    updated, path = _record_trade(
        lambda: add_position(
            args.csv,
            args.symbol,
            args.shares,
            args.price,
            args.currency,
            trade_date,
            args.memo,
        ),
        symbol=args.symbol,
        trade_type="buy",
        shares=args.shares,
        price=args.price,
        currency=args.currency,
        date_str=trade_date,
        memo=args.memo,
        base_dir=args.history_dir,
    )
    print(f"購入記録をローカルに保存しました: {updated['symbol']} ({path})")


def _sell(args: argparse.Namespace) -> None:
    holdings = load_portfolio(args.csv)
    matching = next(
        (position for position in holdings if position["symbol"].upper() == args.symbol.upper()),
        None,
    )
    if matching is None:
        raise ValueError(f"銘柄 {args.symbol} はポートフォリオに存在しません。")
    if args.shares > matching["shares"]:
        raise ValueError(
            f"保有数 ({matching['shares']}) を超える売却数 ({args.shares}) です。"
        )

    trade_date = args.date or date.today().isoformat()
    cost_price = matching["cost_price"]
    realized_pnl = (
        (args.price - cost_price) * args.shares if args.price is not None else None
    )
    preview = [
        "売却記録のプレビュー",
        f"銘柄: {args.symbol}",
        f"株数: {args.shares:,}",
        f"取得単価: {cost_price:,.4f} {matching.get('cost_currency', 'JPY')}",
        f"売却単価: {args.price if args.price is not None else '(未指定)'}",
        f"推定実現損益: {realized_pnl if realized_pnl is not None else '(未計算)'}",
        f"売却日: {trade_date}",
    ]
    if not _confirm_or_preview(preview, args.confirm):
        return

    purchase_date = matching.get("purchase_date")
    hold_days = None
    if purchase_date:
        hold_days = (
            date.fromisoformat(trade_date) - date.fromisoformat(purchase_date)
        ).days
    pnl_rate = (
        (args.price - cost_price) / cost_price
        if args.price is not None and cost_price
        else None
    )
    result, path = _record_trade(
        lambda: sell_position(
            args.csv,
            args.symbol,
            args.shares,
            sell_price=args.price,
            sell_date=trade_date,
        ),
        symbol=args.symbol,
        trade_type="sell",
        shares=args.shares,
        price=cost_price,
        currency=matching.get("cost_currency", "JPY"),
        date_str=trade_date,
        base_dir=args.history_dir,
        sell_price=args.price,
        realized_pnl=realized_pnl,
        pnl_rate=pnl_rate,
        hold_days=hold_days,
        cost_price=cost_price,
    )
    print(
        f"売却記録をローカルに保存しました: {args.symbol} "
        f"(残り {result.get('shares', 0)}株, {path})"
    )


def _stress_test(args: argparse.Namespace) -> None:
    command = [
        sys.executable,
        str(STRESS_TEST_SCRIPT),
        "--portfolio",
        args.symbols,
        "--local-only",
        "--history-dir",
        args.history_dir,
    ]
    if args.weights:
        command.extend(["--weights", args.weights])
    if args.scenario:
        command.extend(["--scenario", args.scenario])
    if args.base_shock is not None:
        command.extend(["--base-shock", str(args.base_shock)])
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)
    print("保有比率・結果はローカル表示です。銘柄コードはYahoo Financeへ送信されます。")


def _backup(args: argparse.Namespace) -> None:
    csv_path = Path(args.csv)
    output = Path(args.output) if args.output else (
        DEFAULT_BACKUP_DIR
        / f"portfolio-backup-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.zip"
    )
    if output.exists():
        raise FileExistsError(f"バックアップ先は既に存在します: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    included: list[str] = []
    temp_path: str | None = None
    try:
        if csv_path.is_symlink():
            raise ValueError(f"バックアップ元にシンボリックリンクは使えません: {csv_path}")
        with tempfile.NamedTemporaryFile(
            dir=output.parent, prefix=f".{output.name}.", suffix=".tmp", delete=False
        ) as temp_file:
            temp_path = temp_file.name
        with ZipFile(temp_path, "w", compression=ZIP_DEFLATED) as archive:
            if csv_path.is_file():
                archive.write(csv_path, "portfolio.csv")
                included.append("portfolio.csv")
            for label, root in (
                ("history", Path(args.history_dir)),
                ("notes", Path(args.notes_dir)),
            ):
                if root.is_symlink():
                    raise ValueError(f"バックアップ元にシンボリックリンクは使えません: {root}")
                if root.is_dir():
                    for source in sorted(root.rglob("*")):
                        if source.is_symlink():
                            raise ValueError(
                                f"バックアップ元にシンボリックリンクは使えません: {source}"
                            )
                        if source.is_file():
                            member = f"{label}/{source.relative_to(root).as_posix()}"
                            archive.write(source, member)
                            included.append(member)
            archive.writestr(
                "manifest.json",
                json.dumps({"version": 1, "files": included}, ensure_ascii=False),
            )
        os.replace(temp_path, output)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
    print(f"ローカルバックアップを作成しました: {output}")
    print("バックアップには暗号化がありません。安全な場所に保管してください。")


def _restore(args: argparse.Namespace) -> None:
    if not args.confirm:
        print("復元は既存ファイルを上書きします。")
        print("内容を確認して実行するには --confirm を指定してください。")
        return

    roots = {
        "history": Path(args.history_dir),
        "notes": Path(args.notes_dir),
    }
    staged: dict[Path, bytes] = {}
    try:
        with ZipFile(args.backup, "r") as archive:
            archive_names = archive.namelist()
            names = set(archive_names)
            if len(names) != len(archive_names):
                raise ValueError("重複したファイル名があります。")
            if "manifest.json" not in names:
                raise ValueError("manifest.json がありません。")
            manifest = json.loads(archive.read("manifest.json"))
            if not isinstance(manifest, dict):
                raise ValueError("バックアップ形式が不正です。")
            files = manifest.get("files")
            if manifest.get("version") != 1 or not isinstance(files, list):
                raise ValueError("バックアップ形式が不正です。")
            if any(not isinstance(name, str) for name in files) or len(
                set(files)
            ) != len(files):
                raise ValueError("バックアップの目録に不正または重複した項目があります。")
            if names != set(files) | {"manifest.json"}:
                raise ValueError("バックアップの目録と格納内容が一致しません。")

            for name in files:
                if "\\" in name or ":" in name:
                    raise ValueError(f"不正なバックアップ内パス: {name}")
                member_path = PurePosixPath(name)
                parts = member_path.parts
                if member_path.is_absolute():
                    raise ValueError(f"不正なバックアップ内パス: {name}")
                if name == "portfolio.csv":
                    target = Path(args.csv)
                elif len(parts) >= 2 and parts[0] in roots and all(
                    part not in ("", ".", "..") for part in parts[1:]
                ):
                    target = _validated_restore_target(roots[parts[0]], parts[1:])
                else:
                    raise ValueError(f"不正なバックアップ内パス: {name}")
                staged[target] = archive.read(name)
    except (BadZipFile, OSError, json.JSONDecodeError, KeyError) as exc:
        raise ValueError(f"バックアップを読み込めません: {exc}") from exc

    previous = {
        path: path.read_bytes() if path.is_file() else None
        for path in staged
    }
    written: list[Path] = []
    try:
        for path, content in staged.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_bytes(path, content)
            written.append(path)
    except OSError as exc:
        rollback_errors: list[str] = []
        for path in reversed(written):
            try:
                old_content = previous[path]
                if old_content is None:
                    path.unlink(missing_ok=True)
                else:
                    _atomic_write_bytes(path, old_content)
            except OSError as rollback_error:
                rollback_errors.append(f"{path}: {rollback_error}")
        if rollback_errors:
            raise RuntimeError(
                "復元に失敗し、一部のロールバックにも失敗しました: "
                + "; ".join(rollback_errors)
            ) from exc
        raise RuntimeError("復元に失敗しました。既存ファイルを元に戻しました。") from exc

    print(f"バックアップを復元しました: {args.backup}")
    print(f"復元ファイル数: {len(staged)}")


def _validated_restore_target(root: Path, parts: tuple[str, ...]) -> Path:
    current = root.absolute()
    while True:
        if _is_symlink_or_junction(current):
            raise ValueError(f"復元先にシンボリックリンクは使えません: {current}")
        if current.parent == current:
            break
        current = current.parent

    target = root
    for part in parts:
        target = target / part
        if _is_symlink_or_junction(target):
            raise ValueError(f"復元先にシンボリックリンクは使えません: {target}")

    resolved_root = root.resolve()
    resolved_target = target.resolve()
    try:
        resolved_target.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"復元先がデータディレクトリの外です: {target}") from exc
    return target


def _is_symlink_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    if os.name == "nt":
        try:
            attributes = os.lstat(path).st_file_attributes
        except (AttributeError, OSError):
            return False
        reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        return bool(attributes & reparse_point)
    return False


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as temp_file:
            temp_path = temp_file.name
            temp_file.write(content)
        os.replace(temp_path, path)
    except OSError:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="個人用ポートフォリオ操作（AIアシスタントを介さず直接実行）"
    )
    parser.add_argument("--csv", default=str(DEFAULT_PORTFOLIO_PATH))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="ローカルの保有一覧を表示")
    commands.add_parser("snapshot", help="現在価格・評価額・損益を表示（銘柄コードはYahooへ送信）")

    buy = commands.add_parser("buy", help="購入記録をプレビューまたはローカル保存")
    buy.add_argument("--history-dir", default=str(DEFAULT_HISTORY_DIR))
    buy.add_argument("--symbol", required=True)
    buy.add_argument("--shares", type=int, required=True)
    buy.add_argument("--price", type=float, required=True)
    buy.add_argument("--currency", default="JPY")
    buy.add_argument("--date", default=None)
    buy.add_argument("--memo", default="")
    buy.add_argument("--confirm", action="store_true")

    sell = commands.add_parser("sell", help="売却記録をプレビューまたはローカル保存")
    sell.add_argument("--history-dir", default=str(DEFAULT_HISTORY_DIR))
    sell.add_argument("--symbol", required=True)
    sell.add_argument("--shares", type=int, required=True)
    sell.add_argument("--price", type=float, default=None)
    sell.add_argument("--date", default=None)
    sell.add_argument("--confirm", action="store_true")

    stress = commands.add_parser("stress-test", help="銘柄・比率を指定してローカルでストレステスト")
    stress.add_argument("--history-dir", default=str(DEFAULT_HISTORY_DIR))
    stress.add_argument("--symbols", required=True, help="カンマ区切りの銘柄コード")
    stress.add_argument("--weights", default=None, help="比率を銘柄順にカンマ区切りで指定")
    stress.add_argument("--scenario", default=None)
    stress.add_argument("--base-shock", type=float, default=None)

    backup = commands.add_parser("backup", help="PF・履歴・メモをローカルZIPへバックアップ")
    backup.add_argument("--history-dir", default=str(DEFAULT_HISTORY_DIR))
    backup.add_argument("--notes-dir", default=str(DEFAULT_NOTES_DIR))
    backup.add_argument("--output", default=None)

    restore = commands.add_parser("restore", help="ローカルバックアップから復元")
    restore.add_argument("--history-dir", default=str(DEFAULT_HISTORY_DIR))
    restore.add_argument("--notes-dir", default=str(DEFAULT_NOTES_DIR))
    restore.add_argument("--backup", required=True)
    restore.add_argument("--confirm", action="store_true")

    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "list":
        _show_list(args.csv)
    elif args.command == "snapshot":
        _show_snapshot(args.csv)
    elif args.command == "buy":
        if args.shares <= 0 or args.price <= 0:
            raise SystemExit("--shares と --price は正の値を指定してください。")
        _buy(args)
    elif args.command == "sell":
        if args.shares <= 0 or (args.price is not None and args.price <= 0):
            raise SystemExit("--shares と指定した --price は正の値を指定してください。")
        _sell(args)
    elif args.command == "stress-test":
        _stress_test(args)
    elif args.command == "backup":
        _backup(args)
    elif args.command == "restore":
        _restore(args)


if __name__ == "__main__":
    main()
