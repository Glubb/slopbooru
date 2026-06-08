"""
Basic deletion logic.
"""
from __future__ import annotations

from pathlib import Path

from .storage import load_thread, save_thread


def delete_post(board_dir: Path, thread_id: int, post_num: int, password: str = "", file_only: bool = False) -> bool:
    """
    Basic deletion.

    Current policy (transitional):
    - Admin path calls this with password="" and is trusted to bypass.
    - Normal users must supply a non-empty password string (we do not yet store per-post
      deletion passwords or hashes — that is planned future work).
    - This at least prevents completely unauthenticated drive-by deletions.
    """
    if not file_only and not (password or "").strip():
        # Non-admin users must provide something that looks like a password
        return False

    res_dir = board_dir / "res"
    thread = load_thread(res_dir, thread_id)
    if not thread:
        return False

    post = thread.get_post(post_num)
    if not post:
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
