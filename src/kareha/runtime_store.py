"""
File-backed runtime state shared across gunicorn workers.

Uses POSIX file locking (fcntl) so captcha answers and per-IP rate limits
work correctly with --workers > 1. State lives under the board's RUNTIME_DIR
(default: .runtime/).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore


def _runtime_dir(board_dir: Path, cfg: Any) -> Path:
    rel = getattr(cfg, "RUNTIME_DIR", ".runtime/") or ".runtime/"
    path = board_dir / rel.strip("/")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _state_path(board_dir: Path, cfg: Any, name: str) -> Path:
    return _runtime_dir(board_dir, cfg) / name


def _read_locked(path: Path) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        return {}
    with open(path, "r+", encoding="utf-8") as f:
        if fcntl:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.seek(0)
            raw = f.read().strip()
            return json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return {}
        finally:
            if fcntl:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _write_locked(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        if fcntl:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            json.dump(data, f, separators=(",", ":"))
        finally:
            if fcntl:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _prune_timestamps(entries: list[float], window: float, now: float) -> list[float]:
    return [t for t in entries if now - t < window]


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

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
    data = _read_locked(path)
    store: dict[str, list[float]] = data.get("ips", {})
    timestamps = _prune_timestamps(store.get(key, []), window_seconds, now)
    if len(timestamps) >= max_events:
        return False
    timestamps.append(now)
    store[key] = timestamps
    # Drop stale IPs to keep file small
    for k in list(store.keys()):
        store[k] = _prune_timestamps(store[k], window_seconds * 2, now)
        if not store[k]:
            del store[k]
    _write_locked(path, {"ips": store})
    return True


# ---------------------------------------------------------------------------
# Captcha
# ---------------------------------------------------------------------------

def captcha_put(
    board_dir: Path,
    cfg: Any,
    token: str,
    answer: str,
    expiry_seconds: float,
) -> None:
    path = _state_path(board_dir, cfg, "captcha.json")
    data = _read_locked(path)
    store: dict[str, list[Any]] = data.get("tokens", {})
    now = time.time()
    # Prune expired
    for k, v in list(store.items()):
        if not v or v[1] < now:
            del store[k]
    store[token] = [answer.upper().strip(), now + expiry_seconds]
    _write_locked(path, {"tokens": store})


def captcha_consume(board_dir: Path, cfg: Any, token: str, answer: str) -> bool:
    if not token:
        return False
    path = _state_path(board_dir, cfg, "captcha.json")
    data = _read_locked(path)
    store: dict[str, list[Any]] = data.get("tokens", {})
    now = time.time()
    entry = store.pop(token, None)
    # Prune while we have the lock
    for k, v in list(store.items()):
        if not v or v[1] < now:
            del store[k]
    _write_locked(path, {"tokens": store})
    if not entry:
        return False
    correct, exp = entry[0], entry[1]
    if exp < now:
        return False
    return (answer or "").upper().strip() == correct