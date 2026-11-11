#!/usr/bin/env python3
"""Run personal portfolio operations directly in a local terminal.

Do not invoke this script through an AI assistant: its output may contain
holdings, transaction details, and investment notes.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.portfolio.portfolio_io import (  # noqa: E402
    DEFAULT_CSV_PATH,
    add_position,
    load_portfolio,
    sell_position,
)
from src.data import yahoo_client  # noqa: E402
from src.data.history.save_trade import save_trade  # noqa: E402
from src.output.portfolio_formatter import format_position_list, format_snapshot  # noqa: E402
from src.core.portfolio.portfolio_query import get_snapshot  # noqa: E402

DEFAULT_HISTORY_DIR = PROJECT_ROOT / "data" / "history"
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
    snapshot = get_snapshot(csv_path, yahoo_client)
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

    updated = add_position(
        args.csv,
        args.symbol,
        args.shares,
        args.price,
        args.currency,
        trade_date,
        args.memo,
    )
    path = save_trade(
        symbol=args.symbol,
        trade_type="buy",
        shares=args.shares,
        price=args.price,
        currency=args.currency,
        date_str=trade_date,
        memo=args.memo,
        base_dir=args.history_dir,
        sync_external=False,
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

    result = sell_position(
        args.csv,
        args.symbol,
        args.shares,
        sell_price=args.price,
        sell_date=trade_date,
    )
    path = save_trade(
        symbol=args.symbol,
        trade_type="sell",
        shares=args.shares,
        price=cost_price,
        currency=matching.get("cost_currency", "JPY"),
        date_str=trade_date,
        base_dir=args.history_dir,
        sell_price=args.price,
        realized_pnl=result.get("realized_pnl"),
        pnl_rate=result.get("pnl_rate"),
        hold_days=result.get("hold_days"),
        cost_price=cost_price,
        sync_external=False,
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="個人用ポートフォリオ操作（AIアシスタントを介さず直接実行）"
    )
    parser.add_argument("--csv", default=os.path.normpath(DEFAULT_CSV_PATH))
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


if __name__ == "__main__":
    main()
