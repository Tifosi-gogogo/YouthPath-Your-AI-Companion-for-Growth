import json
import sys
from pathlib import Path

from PySide6.QtCore import QStandardPaths


def resource_path(relative: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return root / relative


def user_data_path() -> Path:
    path = Path(QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation))
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_json(relative: str) -> dict:
    with resource_path(relative).open(encoding="utf-8") as handle:
        return json.load(handle)
