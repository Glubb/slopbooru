"""
POSIX file locking helpers for multi-worker board state.

fcntl is optional (missing on some platforms); without it we still do the
read-modify-write but without inter-process exclusion.
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore


T = TypeVar("T")


@contextmanager
def exclusive_file_lock(path: Path | str) -> Iterator[None]:
    """Hold an exclusive lock on `path` (created if missing) for the duration."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    with open(path, "a+") as f:
        if fcntl:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def update_json_file(path: Path | str, mutator: Callable[[dict[str, Any]], T]) -> T:
    """
    Atomically read-modify-write a JSON object file under an exclusive lock.

    `mutator` receives the current dict (empty if missing/invalid) and may
    mutate it in place. Its return value is passed back to the caller.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
    with os.fdopen(fd, "r+") as f:
        if fcntl:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            raw = f.read()
            try:
                data: dict[str, Any] = json.loads(raw) if raw.strip() else {}
            except json.JSONDecodeError:
                data = {}
            if not isinstance(data, dict):
                data = {}
            result = mutator(data)
            f.seek(0)
            f.truncate()
            json.dump(data, f, separators=(",", ":"))
            f.flush()
            os.fsync(f.fileno())
            return result
        finally:
            if fcntl:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def storage_lock(res_dir: Path | str):
    """Board-wide lock for thread JSON + post-number allocation."""
    return exclusive_file_lock(Path(res_dir) / ".lock")
