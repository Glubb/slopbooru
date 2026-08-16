"""
File-backed runtime state shared across gunicorn workers.

Uses a single locked read-modify-write so captcha answers and per-IP rate
limits stay correct with --workers > 1. State lives under the board's
RUNTIME_DIR (default: .runtime/).
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .filelock import update_json_file


def _runtime_dir(board_dir: Path, cfg: Any) -> Path:
    rel = getattr(cfg, "RUNTIME_DIR", ".runtime/") or ".runtime/"
    path = board_dir / rel.strip("/")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _state_path(board_dir: Path, cfg: Any, name: str) -> Path:
    return _runtime_dir(board_dir, cfg) / name


def _prune_timestamps(entries: list[float], window: float, now: float) -> list[float]:
    return [t for t in entries if now - t < window]


def check_rate_limit(
    board_dir: Path,
    cfg: Any,
    bucket: str,
    key: str,
    *,
    max_events: int,
    window_seconds: float,
) -> bool:
    """
    Return True if under limit, False if rate limited.
    `bucket` distinguishes post vs report counters (separate JSON files).
    """
    now = time.time()
    path = _state_path(board_dir, cfg, f"rate_{bucket}.json")

    def mutate(data: dict[str, Any]) -> bool:
        store: dict[str, list[float]] = data.setdefault("ips", {})
        timestamps = _prune_timestamps(store.get(key, []), window_seconds, now)
        if len(timestamps) >= max_events:
            store[key] = timestamps
            data["ips"] = store
            return False
        timestamps.append(now)
        store[key] = timestamps
        for k in list(store.keys()):
            store[k] = _prune_timestamps(store[k], window_seconds * 2, now)
            if not store[k]:
                del store[k]
        data["ips"] = store
        return True

    return update_json_file(path, mutate)


def captcha_put(
    board_dir: Path,
    cfg: Any,
    token: str,
    answer: str,
    expiry_seconds: float,
) -> None:
    path = _state_path(board_dir, cfg, "captcha.json")
    now = time.time()

    def mutate(data: dict[str, Any]) -> None:
        store: dict[str, list[Any]] = data.setdefault("tokens", {})
        for k, v in list(store.items()):
            if not v or v[1] < now:
                del store[k]
        store[token] = [answer.upper().strip(), now + expiry_seconds]
        data["tokens"] = store

    update_json_file(path, mutate)


def captcha_consume(board_dir: Path, cfg: Any, token: str, answer: str) -> bool:
    if not token:
        return False
    path = _state_path(board_dir, cfg, "captcha.json")
    now = time.time()
    submitted = (answer or "").upper().strip()

    def mutate(data: dict[str, Any]) -> bool:
        store: dict[str, list[Any]] = data.setdefault("tokens", {})
        entry = store.pop(token, None)
        for k, v in list(store.items()):
            if not v or v[1] < now:
                del store[k]
        data["tokens"] = store
        if not entry:
            return False
        correct, exp = entry[0], entry[1]
        if exp < now:
            return False
        return submitted == correct

    return update_json_file(path, mutate)
