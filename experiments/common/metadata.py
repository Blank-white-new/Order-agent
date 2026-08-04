from __future__ import annotations

import ctypes
import hashlib
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT_BASE_SHA = "e5aea50d3f9e01940420c50260a0ffeb0f651fc5"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_paths(paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted((Path(path) for path in paths), key=lambda value: value.as_posix()):
        digest.update(path.as_posix().encode("utf-8"))
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, encoding="utf-8"
    ).strip()


def _memory_bytes() -> int | None:
    if os.name == "nt":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.ullTotalPhys)
    return None


def collect_metadata(
    *,
    dataset_sha256: str,
    random_seed: int,
    warmup_count: int,
    measurement_count: int,
    provider_mode: str,
    asr_provider: str,
    tts_provider: str,
    extra: dict | None = None,
) -> dict:
    payload = {
        "experiment_base_sha": EXPERIMENT_BASE_SHA,
        "git_sha": _git("rev-parse", "HEAD"),
        "git_branch": _git("branch", "--show-current"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version.replace("\n", " "),
        "python_executable": sys.executable,
        "os": platform.platform(),
        "cpu": platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER", "unknown"),
        "logical_cpu_count": os.cpu_count(),
        "memory_bytes": _memory_bytes(),
        "provider_mode": provider_mode,
        "llm_enabled": False,
        "asr_provider": asr_provider,
        "tts_provider": tts_provider,
        "dataset_sha256": dataset_sha256,
        "random_seed": random_seed,
        "warmup_count": warmup_count,
        "measurement_count": measurement_count,
    }
    if extra:
        payload.update(extra)
    return payload
