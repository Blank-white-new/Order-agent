from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any

from app.speech.errors import speech_error


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise speech_error("SPEECH_PROVIDER_FAILURE") from exc
    if not all(isinstance(row, dict) for row in rows):
        raise speech_error("SPEECH_PROVIDER_FAILURE")
    return rows


def safe_repository_path(repository_root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or "\\" in relative:
        raise speech_error("SPEECH_PROVIDER_FAILURE")
    root = repository_root.resolve()
    candidate = (root / Path(*pure.parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise speech_error("SPEECH_PROVIDER_FAILURE") from exc
    return candidate
