from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "voiceboard.db"


def database_path() -> Path:
    """Return the configured SQLite path and keep it on the local filesystem."""
    configured = os.getenv("VOICEBOARD_DB_PATH")
    return Path(configured).expanduser().resolve() if configured else DEFAULT_DB_PATH

