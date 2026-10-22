"""Application settings (tool locations and preferences). Contains no secrets."""

import json
from pathlib import Path

from .fsutil import atomic_write_json

DEFAULTS = {
    "keytool_path": "",
    "java_path": "",
    "apksigner_path": "",
    "clipboard_clear_seconds": 60,   # 0 disables clearing
    "last_profile_id": "",
}


def load_settings(path: Path) -> dict:
    data = dict(DEFAULTS)
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            data.update({k: v for k, v in raw.items() if k in DEFAULTS and isinstance(v, type(DEFAULTS[k]))})
    except (OSError, ValueError):
        pass
    return data


def save_settings(path: Path, data: dict) -> None:
    atomic_write_json(Path(path), {k: data.get(k, v) for k, v in DEFAULTS.items()})
