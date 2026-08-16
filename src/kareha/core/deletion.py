"""
Basic deletion logic.
"""
from __future__ import annotations

import hmac
from pathlib import Path
from typing import Any

from ..filelock import storage_lock
from ..utils import hash_deletion_password
from .storage import collect_media_paths, load_thread, save_thread, unlink_media


def _unlink_pending(board_dir: Path, res_dir: Path, pending: list[str]) -> None:
    still_used = collect_media_paths(res_dir)
    for rel in pending:
        if rel and rel not in still_used:
            unlink_media(board_dir, rel)


def delete_post(
    board_dir: Path,
    thread_id: int,
    post_num: int,
    password: str = "",
    file_only: bool = False,
    *,
    secret: str = "",
    admin: bool = False,
    cfg: Any = None,
) -> bool:
    """
    Delete a post (full or file-only).

    - Admin path: pass admin=True to bypass password check.
    - User path: if delpass_hash is set, password must match via HMAC-safe compare.
    """
    res_dir = board_dir / getattr(cfg, "RES_DIR", "res/") if cfg else board_dir / "res"
    with storage_lock(res_dir):
        thread = load_thread(res_dir, thread_id)
        if not thread:
            return False

        post = thread.get_post(post_num)
        if not post:
            return False

        if not file_only and not admin:
            provided = (password or "").strip()
            board_secret = secret or getattr(cfg, "SECRET", "") or ""
            if post.delpass_hash:
                expected = hash_deletion_password(provided, board_secret)
                if not expected or not hmac.compare_digest(expected, post.delpass_hash):
                    return False
            elif not provided:
                return False

        pending: list[str] = []
        if post.image:
            pending.append(post.image)
        if post.thumbnail:
            pending.append(post.thumbnail)

        if file_only:
            post.image = None
            post.thumbnail = None
        else:
            post.deleted = True
            post.deleted_by = "admin" if admin else "user"
            post.comment_html = "<em>[deleted]</em>"
            post.comment_raw = "[deleted]"
            post.image = None
            post.thumbnail = None

        save_thread(thread, res_dir)
        _unlink_pending(Path(board_dir), res_dir, pending)
        return True
