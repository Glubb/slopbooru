"""
Pragmatic file-based storage for Kareha-Py.

Current model (as per approved plan):
- One JSON file per thread under RES_DIR (e.g. res/1234567890.json)
- Contains full Thread + list of Posts (with both raw and rendered comment)
- Optional rendered HTML cache files can be written on "rebuild" for static hosting feel.

This is deliberately simple, human-inspectable, and easy to back up.
It can later be swapped for SQLite with minimal changes to the rest of the code.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from ..filelock import storage_lock
from .models import Post, Thread

LEGACY_TIMESTAMP = 100_000_000


def _thread_path(res_dir: Path | str, thread_id: int) -> Path:
    return Path(res_dir) / f"{thread_id}.json"


def _thread_created_from_data(data: dict[str, Any]) -> int:
    created = int(data.get("created") or 0)
    if created:
        return created
    tid = int(data.get("thread") or 0)
    if tid >= LEGACY_TIMESTAMP:
        return tid
    return int(data.get("lastmod") or data.get("lasthit") or 0)


def load_thread(res_dir: Path | str, thread_id: int) -> Optional[Thread]:
    path = _thread_path(res_dir, thread_id)
    if not path.exists():
        return None

    data = json.loads(path.read_text(encoding="utf-8"))
    thread = Thread(
        thread=data["thread"],
        title=data.get("title", ""),
        author=data.get("author", ""),
        postcount=data.get("postcount", 0),
        lasthit=data.get("lasthit", 0),
        lastmod=data.get("lastmod", 0),
        created=_thread_created_from_data(data),
        permasage=data.get("permasage", False),
        closed=data.get("closed", False),
        pinned=data.get("pinned", False),
        filename=str(path),
    )

    for p in data.get("posts", []):
        # Ignore unknown keys from older/newer files
        known = {f.name for f in Post.__dataclass_fields__.values()}
        thread.posts.append(Post(**{k: v for k, v in p.items() if k in known}))

    return thread


def save_thread(thread: Thread, res_dir: Path | str) -> None:
    res_dir = Path(res_dir)
    res_dir.mkdir(parents=True, exist_ok=True)

    path = _thread_path(res_dir, thread.thread)
    thread.filename = str(path)
    if not thread.created:
        thread.created = _thread_created_from_data({
            "thread": thread.thread,
            "lastmod": thread.lastmod,
            "lasthit": thread.lasthit,
            "created": 0,
        })

    data: dict[str, Any] = {
        "thread": thread.thread,
        "title": thread.title,
        "author": thread.author,
        "postcount": thread.postcount,
        "lasthit": thread.lasthit,
        "lastmod": thread.lastmod,
        "created": thread.created,
        "permasage": thread.permasage,
        "closed": thread.closed,
        "pinned": thread.pinned,
        "posts": [p.__dict__ for p in thread.posts],
    }

    # Atomic write
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def list_threads(res_dir: Path | str, sort_by: str = "lasthit") -> list[dict[str, Any]]:
    """
    Lightweight listing (only metadata, no full post bodies).
    Returns list of dicts suitable for front-page rendering.
    """
    res_dir = Path(res_dir)
    if not res_dir.exists():
        return []

    results = []
    for p in sorted(res_dir.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            results.append({
                "thread": data["thread"],
                "title": data.get("title", ""),
                "author": data.get("author", ""),
                "postcount": data.get("postcount", 0),
                "lasthit": data.get("lasthit", 0),
                "lastmod": data.get("lastmod", 0),
                "created": _thread_created_from_data(data),
                "permasage": data.get("permasage", False),
                "closed": data.get("closed", False),
                "pinned": data.get("pinned", False),
            })
        except Exception:
            continue

    # Pinned threads always sort first. Then lasthit/id descending.
    # Thread id is the tie-breaker so same-second posts keep newest-first order.
    if sort_by == "lasthit":
        results.sort(
            key=lambda x: (bool(x.get("pinned")), x.get("lasthit", 0), x.get("thread", 0)),
            reverse=True,
        )
    elif sort_by == "thread":
        results.sort(
            key=lambda x: (bool(x.get("pinned")), x.get("thread", 0)),
            reverse=True,
        )
    elif sort_by == "created":
        results.sort(
            key=lambda x: (bool(x.get("pinned")), x.get("created", 0), x.get("thread", 0)),
            reverse=True,
        )

    return results


def _used_post_nums(res_dir: Path) -> set[int]:
    used: set[int] = set()
    for p in res_dir.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            for post in data.get("posts", []):
                n = post.get("num", 0)
                if n > 0:
                    used.add(n)
        except Exception:
            continue
    return used


def get_next_post_num(res_dir: Path | str) -> int:
    """Get the next unique global post number for the board (unlocked).

    Prefer allocate_post_num() when assigning a number that will be stored.
    """
    res_dir = Path(res_dir)
    counter_file = res_dir / "postnum"
    last_assigned = 0
    if counter_file.exists():
        try:
            last_assigned = int(counter_file.read_text().strip())
        except Exception:
            pass

    used = _used_post_nums(res_dir)

    effective_last = last_assigned if last_assigned < LEGACY_TIMESTAMP else 0
    low_used = [u for u in used if u < LEGACY_TIMESTAMP]
    max_low_used = max(low_used) if low_used else 0

    start = max(effective_last, max_low_used) + 1
    num = start if start >= 1 else 1

    while num in used:
        num += 1
    return num


def save_post_num(res_dir: Path | str, num: int) -> None:
    """Persist the highest assigned post number so far (unlocked)."""
    res_dir = Path(res_dir)
    res_dir.mkdir(parents=True, exist_ok=True)
    current = 0
    counter_file = res_dir / "postnum"
    if counter_file.exists():
        try:
            current = int(counter_file.read_text().strip())
        except Exception:
            pass
    effective_current = current if current < LEGACY_TIMESTAMP else 0
    new_last = max(effective_current, num)
    counter_file.write_text(str(new_last))


def allocate_post_num(res_dir: Path | str) -> int:
    """Assign the next post number under the board storage lock."""
    res_dir = Path(res_dir)
    with storage_lock(res_dir):
        num = get_next_post_num(res_dir)
        save_post_num(res_dir, num)
        return num


def collect_media_paths(res_dir: Path | str, *, skip_thread: int | None = None) -> set[str]:
    """Relative image/thumbnail paths still referenced by remaining threads."""
    res_dir = Path(res_dir)
    refs: set[str] = set()
    for p in res_dir.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if skip_thread is not None and data.get("thread") == skip_thread:
                continue
            for post in data.get("posts", []):
                for key in ("image", "thumbnail"):
                    val = post.get(key)
                    if val and isinstance(val, str) and not val.startswith("static/"):
                        refs.add(val)
        except Exception:
            continue
    return refs


def unlink_media(board_dir: Path | str, rel_path: str | None) -> None:
    if not rel_path or rel_path.startswith("static/"):
        return
    path = Path(board_dir) / rel_path
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass


def delete_thread(
    res_dir: Path | str,
    thread_id: int,
    *,
    board_dir: Path | str | None = None,
) -> None:
    """Remove a thread JSON file and unreferenced media belonging only to it."""
    res_dir = Path(res_dir)
    thread = load_thread(res_dir, thread_id)
    path = _thread_path(res_dir, thread_id)
    media: list[str] = []
    if thread:
        for post in thread.posts:
            if post.image:
                media.append(post.image)
            if post.thumbnail:
                media.append(post.thumbnail)
    if path.exists():
        path.unlink()
    if board_dir and media:
        still_used = collect_media_paths(res_dir)
        for rel in media:
            if rel not in still_used:
                unlink_media(board_dir, rel)
