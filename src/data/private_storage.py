"""Resolve user-local storage paths for private investment data."""

import os
from pathlib import Path


def private_data_dir() -> Path:
    """Return a per-user data directory outside the repository workspace."""
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        root = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return root / "stock-skills-personal"
