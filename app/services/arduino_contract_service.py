from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def extract_json_contract_from_ino(file_path: str) -> dict[str, Any]:
    """
    Parse an Arduino .ino file and extract JSON keys written into `doc["..."]`.
    This gives the backend a lightweight contract of expected payload fields.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Arduino file not found: {file_path}")

    source = path.read_text(encoding="utf-8")
    keys = sorted(set(re.findall(r'doc\["([^"]+)"\]', source)))
    serializes_json = "serializeJson(doc, Serial)" in source

    return {
        "file_path": str(path),
        "json_keys": keys,
        "json_key_count": len(keys),
        "serializes_json": serializes_json,
    }
