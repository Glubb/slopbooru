"""
Admin moderation action dispatcher (POST-only).
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .core.admin import admin_delete_post, ban_md5, moderate_thread_action
from .core.reports import update_report_status
from .core.storage import load_thread, save_thread

ALLOWED_ACTIONS = frozenset({
    "close", "permasage", "delete", "deletefile", "banmd5", "report_handled",
})


def process_admin_action(
    board_dir: Path,
    cfg: Any,
    *,
    action: str,
    thread_id_str: str = "",
    post_num_str: str = "",
    state_str: str = "1",
    report_index_str: str = "",
) -> tuple[bool, str]:
    """
    Run a single admin action. Returns (ok, error_message).
    error_message empty on success.
    """
    if action not in ALLOWED_ACTIONS:
        return False, "Unknown action"

    if action in ("close", "permasage"):
        if not thread_id_str:
            return False, "Missing thread"
        try:
            tid = int(thread_id_str)
            state = state_str in ("1", "true", "yes", "on")
            if not moderate_thread_action(board_dir, tid, action, state, cfg):
                return False, "Thread not found"
        except ValueError:
            return False, "Bad thread id"
        return True, ""

    if action in ("delete", "deletefile"):
        if not thread_id_str or not post_num_str:
            return False, "Missing thread or post"
        try:
            tid = int(thread_id_str)
            pid = int(post_num_str)
            if not admin_delete_post(
                board_dir, tid, pid, file_only=(action == "deletefile"), cfg=cfg
            ):
                return False, "Delete failed"
        except ValueError:
            return False, "Bad id"
        return True, ""

    if action == "banmd5":
        if not thread_id_str or not post_num_str:
            return False, "Missing thread or post"
        try:
            tid = int(thread_id_str)
            pid = int(post_num_str)
            res_dir = board_dir / getattr(cfg, "RES_DIR", "res/")
            thread = load_thread(res_dir, tid)
            if not thread:
                return False, "Thread not found"
            post = thread.get_post(pid)
            if not post or not post.md5:
                return False, "No MD5 on post"
            ban_md5(
                board_dir, post.md5,
                reason=f"permabanned thread {tid} post {pid}", cfg=cfg,
            )
            if post.image:
                img_path = board_dir / post.image
                if img_path.exists():
                    img_path.unlink()
                if post.thumbnail:
                    tpath = board_dir / post.thumbnail
                    if tpath.exists():
                        tpath.unlink()
                post.image = None
                post.thumbnail = None
            save_thread(thread, res_dir)
        except ValueError:
            return False, "Bad id"
        return True, ""

    if action == "report_handled":
        try:
            report_index = int(report_index_str)
            if report_index < 0 or not update_report_status(board_dir, report_index, "handled"):
                return False, "Invalid report index"
        except ValueError:
            return False, "Bad report index"
        return True, ""

    return False, "Unhandled action"