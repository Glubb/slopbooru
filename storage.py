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

from .models import Post, Thread


def _thread_path(res_dir: Path | str, thread_id: int) -> Path:
    return Path(res_dir) / f"{thread_id}.json"


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
        permasage=data.get("permasage", False),
        closed=data.get("closed", False),
        filename=str(path),
    )

    for p in data.get("posts", []):
        thread.posts.append(Post(**p))

    return thread


def save_thread(thread: Thread, res_dir: Path | str) -> None:
    res_dir = Path(res_dir)
    res_dir.mkdir(parents=True, exist_ok=True)

    path = _thread_path(res_dir, thread.thread)
    thread.filename = str(path)

    data: dict[str, Any] = {
        "thread": thread.thread,
        "title": thread.title,
        "author": thread.author,
        "postcount": thread.postcount,
        "lasthit": thread.lasthit,
        "lastmod": thread.lastmod,
        "permasage": thread.permasage,
        "closed": thread.closed,
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
                "permasage": data.get("permasage", False),
                "closed": data.get("closed", False),
            })
        except Exception:
            continue

    # Sort (lasthit descending by default, like original bumped order)
    if sort_by == "lasthit":
        results.sort(key=lambda x: x.get("lasthit", 0), reverse=True)
    elif sort_by == "thread":
        results.sort(key=lambda x: x.get("thread", 0), reverse=True)

    return results


def get_next_post_num(res_dir: Path | str) -> int:
    """Get the next unique global post number for the board.
    Starts from 1 (or after highest previously assigned low number), goes up.
    Never reuses any number that appears in existing posts (cannot reuse).
    High legacy numbers (from old timestamp-based ids ~1e9) are ignored for
    computing the "next low", but still protected against reuse via the used set.
    Both new thread OPs and replies call this so replies advance the global count.
    """
    res_dir = Path(res_dir)
    counter_file = res_dir / "postnum"
    last_assigned = 0
    if counter_file.exists():
        try:
            last_assigned = int(counter_file.read_text().strip())
        except Exception:
            pass

    # Collect all currently used post numbers from data (for no-reuse guarantee)
    used = set()
    for p in res_dir.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            for post in data.get("posts", []):
                n = post.get("num", 0)
                if n > 0:
                    used.add(n)
        except Exception:
            continue

    # Effective high-water from counter: drop legacy huge values so we can start/continue low
    LEGACY = 100_000_000
    effective_last = last_assigned if last_assigned < LEGACY else 0

    # Max from actually used *low* numbers (the ones that represent real assigned post ids)
    low_used = [u for u in used if u < LEGACY]
    max_low_used = max(low_used) if low_used else 0

    # Next candidate goes up from the effective high water of low numbers
    start = max(effective_last, max_low_used) + 1
    num = start if start >= 1 else 1

    # Final safety: if somehow collides (manual data edit, race, or the high legacy itself), skip
    while num in used:
        num += 1
    return num


def save_post_num(res_dir: Path | str, num: int) -> None:
    """Persist the highest assigned post number so far (for hint on next run).
    Legacy high values in the counter are dropped when a low number is assigned,
    allowing the board to use low sequential numbers going forward.
    """
    res_dir = Path(res_dir)
    res_dir.mkdir(parents=True, exist_ok=True)
    current = 0
    counter_file = res_dir / "postnum"
    if counter_file.exists():
        try:
            current = int(counter_file.read_text().strip())
        except Exception:
            pass
    # When saving a (new low) num, ignore any legacy high in current counter
    LEGACY = 100_000_000
    effective_current = current if current < LEGACY else 0
    new_last = max(effective_current, num)
    counter_file.write_text(str(new_last))


def delete_thread(res_dir: Path | str, thread_id: int) -> None:
    path = _thread_path(res_dir, thread_id)
    if path.exists():
        path.unlink()
