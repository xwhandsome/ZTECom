from __future__ import annotations

import os
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent
ALGORITHM_DIR = PACKAGE_DIR.parent
REPO_ROOT = ALGORITHM_DIR.parent
DATA_DIR = REPO_ROOT / "data"
KB_DIR = DATA_DIR / "kb"
DEFAULT_DB_PATH = DATA_DIR / "agent_state.sqlite3"
DEFAULT_CONDA_PREFIX = Path(os.environ.get("CONDA_PREFIX", r"E:\app\anaconda\envs\RAG"))


def ensure_data_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    KB_DIR.mkdir(parents=True, exist_ok=True)
