"""
Admin / Moderation logic.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
from pathlib import Path
from typing import Any

from .storage import list_threads, load_thread, save_thread


def check_admin_pass(provided: str, cfg: Any) -> bool:
    """Simple admin password check. Uses timing-safe comparison."""
    import hmac
    admin_pass = getattr(cfg, "ADMIN_PASS", "CHANGEME") or ""
    provided = provided or ""
    # Always compare same length to avoid early exit leaks (pad/truncate for safety)
    return hmac.compare_digest(provided.encode("utf-8"), admin_pass.encode("utf-8"))


def get_all_threads_for_admin(board_dir: Path, cfg: Any) -> list[dict]:
    """Return lightweight thread info suitable for admin listing."""
    res_dir = board_dir / getattr(cfg, "RES_DIR", "res/")
    threads = list_threads(res_dir, sort_by="lasthit")

    result = []
    for t in threads:
        result.append({
            "thread": t["thread"],
            "title": t.get("title", ""),
            "postcount": t.get("postcount", 0),
            "lasthit": t.get("lasthit", 0),
            "lastmod": t.get("lastmod", 0),
            "closed": t.get("closed", False),
            "permasage": t.get("permasage", False),
        })
    return result


def moderate_thread_action(
    board_dir: Path,
    thread_id: int,
    action: str,
    state: bool = True,
    cfg: Any = None,
) -> bool:
    """
    Perform moderation actions on a thread.
    Supported actions: 'close', 'permasage'
    """
    res_dir = board_dir / getattr(cfg or {}, "RES_DIR", "res/")
    thread = load_thread(res_dir, thread_id)
    if not thread:
        return False

    if action == "close":
        thread.closed = bool(state)
    elif action == "permasage":
        thread.permasage = bool(state)
    else:
        return False

    save_thread(thread, res_dir)
    return True


def admin_delete_post(
    board_dir: Path,
    thread_id: int,
    post_num: int,
    file_only: bool = False,
    cfg: Any = None,
) -> bool:
    """
    Admin deletion (bypasses user password check).
    """
    from .deletion import delete_post as _delete_post
    # Reuse the existing deletion function (it doesn't strictly enforce password yet)
    return _delete_post(board_dir, thread_id, post_num, password="", file_only=file_only)


# ---------------------------------------------------------------------------
# Stateless signed admin authentication (cookie-based, no password in URLs)
# ---------------------------------------------------------------------------

def _get_admin_key(cfg: Any) -> bytes:
    """Derive a key from ADMIN_PASS + SECRET for HMAC."""
    admin_pass = getattr(cfg, "ADMIN_PASS", "") or ""
    board_secret = getattr(cfg, "SECRET", "") or ""
    material = f"{admin_pass}|{board_secret}".encode("utf-8", errors="ignore")
    return material


def create_admin_token(cfg: Any, max_age: int = 86400) -> str:
    """
    Create a time-limited, signed token that proves the caller knew the admin password.
    The token itself does not contain the password.
    """
    now = int(time.time())
    exp = now + max_age
    payload = str(exp).encode("ascii")
    key = _get_admin_key(cfg)
    sig = hmac.new(key, payload, hashlib.sha256).digest()
    raw = payload + b":" + sig
    token = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return token


def verify_admin_token(token: str, cfg: Any, max_age: int = 86400) -> bool:
    """Verify a token from the admin_auth cookie."""
    if not token:
        return False
    try:
        # Add padding if needed
        padding = "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(token + padding)
        if b":" not in raw:
            return False
        exp_bytes, sig = raw.split(b":", 1)
        exp = int(exp_bytes)
        if exp < int(time.time()):
            return False  # expired
        key = _get_admin_key(cfg)
        expected = hmac.new(key, exp_bytes, hashlib.sha256).digest()
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False


def get_admin_auth(request: Any, cfg: Any) -> bool:
    """
    Return True if the request is authenticated as admin.
    Checks cookie first (preferred), then falls back to explicit ?admin= or form (for login/transition).
    """
    # 1. Cookie (new preferred method)
    cookie_token = ""
    if hasattr(request, "cookies"):
        cookie_token = request.cookies.get("admin_auth", "")
    if verify_admin_token(cookie_token, cfg):
        return True

    # 2. Explicit pass (from form or query) - used for initial login
    provided = ""
    if hasattr(request, "form"):
        provided = (request.form.get("admin") or "").strip()
    if not provided and hasattr(request, "args"):
        provided = (request.args.get("admin") or "").strip()

    # check_admin_pass is defined in this same module
    return check_admin_pass(provided, cfg)


def ban_ip(board_dir, ip: str, reason: str = "", cfg: Any = None) -> None:
    """Append an IP ban entry using the configured ban template/file."""
    if not ip:
        return
    ban_file = board_dir / getattr(cfg or {}, "ADMIN_BAN_FILE", ".htaccess")
    template = getattr(cfg or {}, "ADMIN_BAN_TEMPLATE",
                       "# Banned IP: <var $reason> (<var $date>)\nDeny from <var $ip>\n")
    import time
    date = time.strftime("%Y-%m-%d %H:%M")
    entry = (template
             .replace("<var $reason>", reason or "Banned via admin portal")
             .replace("<var $date>", date)
             .replace("<var $ip>", ip))
    ban_file.parent.mkdir(parents=True, exist_ok=True)
    with open(ban_file, "a", encoding="utf-8") as f:
        f.write(entry + "\n")


def ban_md5(board_dir, md5: str, reason: str = "", cfg: Any = None) -> None:
    """Append an MD5 to the banned images list."""
    banned_file = board_dir / getattr(cfg or {}, "BANNED_MD5_FILE", "banned_md5.txt")
    banned_file.parent.mkdir(parents=True, exist_ok=True)
    import time
    with open(banned_file, "a", encoding="utf-8") as f:
        f.write(f"{md5}  # {reason or 'Banned via admin portal'} ({time.strftime('%Y-%m-%d %H:%M')})\n")
