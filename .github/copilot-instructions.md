# Copilot Instructions

## Project

This repository is a Python stock-screening and investment-analysis system. Claude Code skills live in `.claude/skills/`; their Python implementation is in those skill scripts and `src/`.

## Development

- Support Python 3.10+ and manage dependencies with `uv`.
- Route all Yahoo Finance data access through `src/data/yahoo_client.py`; do not call `yfinance` directly elsewhere.
- Follow the existing module layout and patterns. See `.claude/rules/development.md` and `.claude/rules/workflow.md` for detailed conventions.
- Run focused tests for the change; the full suite is `uv run python -m pytest tests/ -q`.
- Update relevant skills, rules, or user-facing docs when behavior or features change. See the documentation checklist in `.claude/rules/workflow.md`.
- Do not overwrite or discard unrelated working-tree changes.

## GitHub Issues and Pull Requests

- Use `gh` for GitHub operations only when the user asks for them. Check `gh auth status` and confirm the current repository before creating or modifying remote resources.
- When asked to create an issue or PR, use the repository templates and include the relevant context, implementation summary, and validation results.
- Do not push commits, create issues or PRs, or merge unless the user explicitly requests that action.
- Merge only when explicitly requested and required checks/reviews have passed and there are no merge conflicts. If the repository blocks the merge or a check fails, stop and report the blocker instead of bypassing protections.
- Never expose, commit, or place credentials or tokens in repository files or command output.
