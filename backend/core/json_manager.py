# json_manager.py — atomic JSON read/write helpers for all Flux modules.
# Use these everywhere instead of open() + json.load() directly.

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def read_json(path: Path | str) -> dict | list:
    """Read and parse a JSON file. Returns {} on missing file or parse error."""
    path = Path(path)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}
    except OSError:
        return {}


def write_json(path: Path | str, data: dict | list, indent: int = 2) -> bool:
    """Write *data* to *path* atomically (temp file → rename).

    Atomic write prevents corruption when multiple users access the same
    file over OneDrive or a network share simultaneously.
    Returns True on success, False on error.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        fd, tmp_path = tempfile.mkstemp(
            dir=path.parent,
            prefix=".flux_tmp_",
            suffix=".json",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=indent)
        except Exception:
            os.unlink(tmp_path)
            return False

        # Atomic replace (works on Windows with os.replace)
        os.replace(tmp_path, path)
        return True

    except OSError:
        return False


def update_json(path: Path | str, key: str, value: Any) -> bool:
    """Read JSON dict, set *key* to *value*, write back atomically."""
    data = read_json(path)
    if not isinstance(data, dict):
        data = {}
    data[key] = value
    return write_json(path, data)


def append_to_list(path: Path | str, list_key: str, item: Any) -> bool:
    """Read JSON dict, append *item* to data[list_key], write back atomically."""
    data = read_json(path)
    if not isinstance(data, dict):
        data = {}
    lst = data.get(list_key, [])
    if not isinstance(lst, list):
        lst = []
    lst.append(item)
    data[list_key] = lst
    return write_json(path, data)
