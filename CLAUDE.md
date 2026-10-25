# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Design Philosophy

**このシステムは「自然言語ファースト」で設計されている。**

ユーザーはスラッシュコマンドやパラメータを覚える必要はない。日本語で意図を伝えるだけで、適切なスキルが自動的に選択・実行される。

- 「いい日本株ある？」→ スクリーニングが走る
- 「トヨタってどう？」→ 個別レポートが出る
- 「PF大丈夫かな」→ ヘルスチェックが実行される
- 「改善点ある？」→ システム自身を分析して提案する

スキル（`/screen-stocks` 等）はあくまで内部実装であり、ユーザーインターフェースではない。自然言語からの意図推論が第一の入口であり、コマンドは補助手段に過ぎない。

新機能を追加する際は、**ユーザーがどんな言葉でその機能を呼び出すか**を常に考え、`intent-routing.md` にその表現を反映すること。

## Project Overview

割安株スクリーニングシステム。Yahoo Finance API（yfinance）を使って日本株・米国株・ASEAN株・香港株・韓国株・台湾株等60地域から割安銘柄をスクリーニングする。Claude Code Skills として動作し、自然言語で話しかけるだけで適切な機能が実行される。

## Commands

各スキルのコマンド詳細は [docs/skill-catalog.md](docs/skill-catalog.md) を参照。

### 代表コマンド
```bash
# 依存関係の同期
uv sync

# スクリーニング
uv run python .claude/skills/screen-stocks/scripts/run_screen.py --region japan --preset alpha --top 10

# 個別レポート
uv run python .claude/skills/stock-report/scripts/generate_report.py 7203.T

# ポートフォリオ
uv run python .claude/skills/stock-portfolio/scripts/run_portfolio.py snapshot

# テスト
uv run python -m pytest tests/ -q

# 依存追加
uv add <package>
uv add --dev <package>
```

## Architecture

詳細は [docs/architecture.md](docs/architecture.md)（3層構成・Mermaid図）、[docs/neo4j-schema.md](docs/neo4j-schema.md)（グラフスキーマ）、[docs/skill-catalog.md](docs/skill-catalog.md)（8スキル）を参照。

### レイヤー概要
<!-- BEGIN AUTO-GENERATED ARCHITECTURE -->
```
Skills (.claude/skills/*/SKILL.md → scripts/*.py) — 9スキル
Core   (src/core/) — health/, portfolio/, ports/, research/, risk/, screening/, action_item_bridge, action_item_detector, common, health_check, health_etf, health_labels, market_dashboard, models, proactive_engine, return_estimate, ticker_utils, value_trap
Data   (src/data/) — context/, graph_query/, graph_store/, grok_client/, history/, yahoo_client/, embedding_client, lesson_community, lesson_conflict, linear_client, note_manager, user_profile
Output (src/output/) — adjust_formatter, analyze_formatter, forecast_formatter, formatter, health_formatter, portfolio_formatter, rebalance_formatter, research_formatter, review_formatter, screening_summary_formatter, simulate_formatter, stress_formatter

Config: config/screening_presets.yaml (16 presets), config/exchanges.yaml (60+ regions)
Rules:  .claude/rules/ (graph-context, intent-routing, workflow, development, screening, portfolio, testing)
Docs:   docs/ (architecture, neo4j-schema, skill-catalog, api-reference, data-models)
```
<!-- END AUTO-GENERATED ARCHITECTURE -->

## Post-Implementation Rule

**機能実装後は必ずドキュメント・ルールを更新すること。** 詳細は `.claude/rules/workflow.md` の「7. ドキュメント・ルール更新」を参照。

自動生成: `docs/api-reference.md`、`CLAUDE.md` Architecture、`development.md` テスト数、`docs/skill-catalog.md` 概要（pre-commit hook で自動実行）
手動更新: `intent-routing.md`、該当 `SKILL.md`、`rules/*.md`、`README.md`
