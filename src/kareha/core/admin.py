"""
Admin / Moderation logic.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import time
from pathlib import Path
from typing import Any

from .storage import list_threads, load_thread, save_thread

_DENY_FROM_RE = re.compile(r"^\s*Deny\s+from\s+(\S+)", re.I)


def check_admin_pass(provided: str, cfg: Any) -> bool:
    """Timing-safe admin password check (equal-length SHA-256 digests)."""
    admin_pass = getattr(cfg, "ADMIN_PASS", "CHANGEME") or ""
    provided = provided or ""
    left = hashlib.sha256(provided.encode("utf-8")).digest()
    right = hashlib.sha256(admin_pass.encode("utf-8")).digest()
    return hmac.compare_digest(left, right)


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
            "created": t.get("created", 0),
            "closed": t.get("closed", False),
            "permasage": t.get("permasage", False),
            "pinned": t.get("pinned", False),
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
    Supported actions: 'close', 'permasage', 'pin'
    """
    res_dir = board_dir / getattr(cfg or {}, "RES_DIR", "res/")
    thread = load_thread(res_dir, thread_id)
    if not thread:
        return False

    if action == "close":
        thread.closed = bool(state)
    elif action == "permasage":
        thread.permasage = bool(state)
    elif action == "pin":
        thread.pinned = bool(state)
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
    """Admin deletion (bypasses user password check)."""
    from .deletion import delete_post as _delete_post
    return _delete_post(
        board_dir, thread_id, post_num, password="", file_only=file_only, admin=True, cfg=cfg
    )


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
    Create a time-limited signed token (exp:nonce + HMAC). Does not contain the password.
    Invalidated when ADMIN_PASS or SECRET changes (HMAC key derives from both).
    """
    exp = int(time.time()) + max_age
    nonce = secrets.token_hex(8)
    payload = f"{exp}:{nonce}".encode("ascii")
    key = _get_admin_key(cfg)
    sig = hmac.new(key, payload, hashlib.sha256).digest()
    raw = payload + b":" + sig
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def verify_admin_token(token: str, cfg: Any, max_age: int = 86400) -> bool:
    """Verify a token from the admin_auth cookie (supports exp:nonce and legacy exp-only tokens)."""
    if not token:
        return False
    try:
        padding = "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(token + padding)
        if b":" not in raw:
            return False
        key = _get_admin_key(cfg)
        if raw.count(b":") == 1:
            # Legacy token: payload is expiry integer only
            exp_bytes, sig = raw.split(b":", 1)
            exp = int(exp_bytes)
            if exp < int(time.time()):
                return False
            expected = hmac.new(key, exp_bytes, hashlib.sha256).digest()
            return hmac.compare_digest(sig, expected)
        payload, sig = raw.rsplit(b":", 1)
        exp_str, _nonce = payload.decode("ascii").split(":", 1)
        exp = int(exp_str)
        if exp < int(time.time()):
            return False
        expected = hmac.new(key, payload, hashlib.sha256).digest()
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False


def is_admin_cookie_authenticated(request: Any, cfg: Any) -> bool:
    """True if the admin_auth cookie holds a valid signed token."""
    if not hasattr(request, "cookies"):
        return False
    return verify_admin_token(request.cookies.get("admin_auth", ""), cfg)


def check_admin_login_form(request: Any, cfg: Any) -> bool:
    """True if this POST carries a valid admin password (login form only — never query strings)."""
    if getattr(request, "method", "") != "POST":
        return False
    provided = (request.form.get("admin") or "").strip() if hasattr(request, "form") else ""
    return bool(provided) and check_admin_pass(provided, cfg)


def load_banned_ips(board_dir: Path, cfg: Any) -> set[str]:
    """Load banned IPs from BANNED_IP_FILE and legacy ADMIN_BAN_FILE (.htaccess)."""
    banned: set[str] = set()
    banned_file = board_dir / getattr(cfg, "BANNED_IP_FILE", "banned_ips.txt")
    if banned_file.exists():
        for line in banned_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            ip = line.split("#", 1)[0].strip()
            if ip:
                banned.add(ip)
    legacy = board_dir / getattr(cfg, "ADMIN_BAN_FILE", ".htaccess")
    if legacy.exists():
        for line in legacy.read_text(encoding="utf-8", errors="ignore").splitlines():
            m = _DENY_FROM_RE.match(line)
            if m:
                banned.add(m.group(1).strip())
    return banned


def is_ip_banned(ip: str, board_dir: Path, cfg: Any) -> bool:
    if not ip:
        return False
    return ip in load_banned_ips(board_dir, cfg)


def ban_ip(board_dir, ip: str, reason: str = "", cfg: Any = None) -> None:
    """Append IP to enforced ban list and legacy .htaccess-style log."""
    if not ip:
        return
    date = time.strftime("%Y-%m-%d %H:%M")
    # Enforced list
    banned_file = board_dir / getattr(cfg or {}, "BANNED_IP_FILE", "banned_ips.txt")
    banned_file.parent.mkdir(parents=True, exist_ok=True)
    with open(banned_file, "a", encoding="utf-8") as f:
        f.write(f"{ip}  # {reason or 'Banned via admin portal'} ({date})\n")
    # Legacy Apache log (parsed on load for backwards compatibility)
    ban_file = board_dir / getattr(cfg or {}, "ADMIN_BAN_FILE", ".htaccess")
    template = getattr(cfg or {}, "ADMIN_BAN_TEMPLATE",
                       "# Banned IP: <var $reason> (<var $date>)\nDeny from <var $ip>\n")
    entry = (template
             .replace("<var $reason>", reason or "Banned via admin portal")
             .replace("<var $date>", date)
             .replace("<var $ip>", ip))
    with open(ban_file, "a", encoding="utf-8") as f:
        f.write(entry + "\n")


def ban_md5(board_dir, md5: str, reason: str = "", cfg: Any = None) -> None:
    """Append an MD5 to the banned images list."""
    banned_file = board_dir / getattr(cfg or {}, "BANNED_MD5_FILE", "banned_md5.txt")
    banned_file.parent.mkdir(parents=True, exist_ok=True)
    import time
    with open(banned_file, "a", encoding="utf-8") as f:
        f.write(f"{md5}  # {reason or 'Banned via admin portal'} ({time.strftime('%Y-%m-%d %H:%M')})\n")
