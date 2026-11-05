"""Generate and verify repository docs before committing source changes."""

import re
import subprocess
import sys
from pathlib import Path


GENERATED_DOCS = [
    "docs/api-reference.md",
    "CLAUDE.md",
    ".claude/rules/development.md",
    "docs/skill-catalog.md",
]


def _run(*command: str) -> int:
    return subprocess.run(command, check=False).returncode


def main() -> int:
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()

    if not any(path.startswith("src/") for path in staged):
        return 0

    if Path("scripts/generate_docs.py").is_file():
        result = _run("uv", "run", "python", "scripts/generate_docs.py", "all")
        if result:
            return result
        _run("git", "add", *GENERATED_DOCS)
        result = _run(
            "uv", "run", "python", "scripts/generate_docs.py", "data-models-verify"
        )
        if result:
            print("⚠️  docs/data-models.md is out of sync. Please update manually.")
        return result

    doc_pattern = re.compile(r"(CLAUDE\.md|README\.md|SKILL\.md|rules/|config/|docs/)")
    if any(doc_pattern.search(path) for path in staged):
        return 0

    print("src/ に変更がありますが、ドキュメントが更新されていません。")
    print("対象: CLAUDE.md, SKILL.md, rules/, config/, README.md, docs/")
    print("バイパス: git commit --no-verify")
    return 1


if __name__ == "__main__":
    sys.exit(main())
