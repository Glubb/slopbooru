"""
Basic deletion logic.
"""
from __future__ import annotations

import hmac
from pathlib import Path
from typing import Any

from ..utils import hash_deletion_password
from .storage import load_thread, save_thread


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

    if file_only:
        post.image = None
        post.thumbnail = None
    else:
        post.deleted = True
        post.comment_html = "<em>[deleted]</em>"
        post.comment_raw = "[deleted]"

    save_thread(thread, res_dir)
    return True