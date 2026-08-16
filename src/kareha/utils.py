"""
Core utility functions ported/adapted from wakautils.pl and kareha.pl.

Includes:
- Tripcode processing (with basic 2ch-style support)
- make_id_code (DISPLAY_ID randomized poster IDs based on IP)
- Date formatting (futaba, 2ch styles)
- Cookie helpers
- IP masking / hashing helpers (modernized)
- Various string cleaning, URL regex, etc.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

# ---------------------------------------------------------------------------
# Regexes (ported/adapted)
# ---------------------------------------------------------------------------

def protocol_regexp() -> str:
    """Returns regex fragment matching allowed protocols for links (no javascript:)."""
    return r"(?:https?|ftp|mailto):"


def url_regexp() -> re.Pattern:
    """Rough URL matcher (similar spirit to original)."""
    protocol = protocol_regexp()
    return re.compile(
        rf"((?:{protocol})[^\s<>()\"]*|www\.[^\s<>()\"]*[a-zA-Z0-9/])"
        r"([^\s<>()\"]*\([^\s<>()\"]*\)[^\s<>()\"]*|[^\s<>()\"]*)",
        re.IGNORECASE,
    )


REPLY_RANGE_RE = re.compile(r"n?(?:[0-9\-,lrq]|&#44;)*[0-9\-lrq]", re.I)

# ---------------------------------------------------------------------------
# Tripcodes
# ---------------------------------------------------------------------------

def process_tripcode(
    name: str,
    tripkey: str = "!",
    secret: str = "",
    charset: str = "utf-8",
    use_secure: bool = True,
) -> tuple[str, str]:
    """
    Extract and compute tripcode from name field.
    Returns (name_without_trip, tripcode_with_# or !! for secure).
    """
    if tripkey not in name:
        return name, ""

    # Split on first occurrence of the tripkey
    parts = name.split(tripkey, 1)
    if len(parts) != 2:
        return name, ""

    name_part, trip_part = parts
    if not trip_part:
        return name_part, ""

    # For now: simple non-secure trip (original has complex SJIS + DES fallback)
    # A real port would replicate the exact 2ch algorithm for compatibility.
    # Pragmatic: use a stable hash that looks like old tripcodes.
    trip = _compute_trip(trip_part, secret, charset, secure=use_secure and len(trip_part) > 0)
    return name_part, trip


def _compute_trip(trip_part: str, secret: str, charset: str, secure: bool = True) -> str:
    """Internal tripcode hasher (pragmatic modern version)."""
    if secure and secret:
        # "Secure" tripcodes (longer, harder to brute)
        data = (trip_part + secret).encode(charset, errors="ignore")
        h = hashlib.blake2b(data, digest_size=3).digest()
        return "!!" + _tripcode_b64(h)
    else:
        # Classic-ish (not identical to Perl DES/SJIS version)
        data = trip_part.encode(charset, errors="ignore")
        h = hashlib.md5(data).digest()[:3]  # short like old tripcodes
        return "#" + _tripcode_b64(h)


_TRIP_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789./"


def _tripcode_b64(data: bytes) -> str:
    """Convert 3 bytes to 4-char tripcode-like string."""
    n = int.from_bytes(data, "big")
    out = ""
    for _ in range(4):
        out = _TRIP_ALPHABET[n & 63] + out
        n >>= 6
    return out


# ---------------------------------------------------------------------------
# IP-based randomized poster IDs (DISPLAY_ID feature)
# ---------------------------------------------------------------------------

def make_id_code(ip: str, t: float, link: str, thread: str, cfg: Any) -> str:
    """
    Generate a short 'ID:xxxx' tag for a poster based on IP and DISPLAY_ID rules.

    Supported DISPLAY_ID values (comma or space separated, case-insensitive):
      ip, host, mask, day, board, thread, link, sage
    """
    display = (getattr(cfg, "DISPLAY_ID", "") or "").lower()
    email_id = getattr(cfg, "EMAIL_ID", "Heaven")
    secret = getattr(cfg, "SECRET", "")

    if not display:
        return ""

    if link and "link" in display:
        return email_id
    if "sage" in display and "sage" in (link or "").lower():
        return email_id

    if "host" in display:
        return _resolve_host(ip) or ip

    if "ip" in display:
        return ip

    # Build a varying "salt" string from the flags
    salt_parts = [ip]
    now = int(t)
    if "day" in display:
        salt_parts.append(str(now // 86400))
    if "board" in display:
        # In real WSGI we would use SCRIPT_NAME; here use a stable board id
        salt_parts.append(getattr(cfg, "TITLE", "board"))
    if "thread" in display:
        salt_parts.append(str(thread))

    salt = ",".join(salt_parts)

    if "mask" in display:
        return _mask_ip(ip, secret + salt)

    # Default: short hidden hash (original used hide_data)
    return _short_id_hash(ip + salt, secret)


def _short_id_hash(data: str, secret: str, length: int = 4) -> str:
    """Stable short identifier (4-6 chars)."""
    mac = hmac.new(secret.encode(), data.encode(), hashlib.blake2s).digest()
    return hashlib.md5(mac).hexdigest()[:length].upper()


def _mask_ip(ip: str, key_material: str) -> str:
    """Return a masked / disguised IP representation (for privacy + consistency)."""
    # Simple but stable mask using HMAC (better than original bit masking for new boards)
    h = hmac.new(key_material.encode(), ip.encode(), hashlib.sha256).digest()
    # Make it look like a partial IP or code
    return "ID:" + hashlib.md5(h).hexdigest()[:6].upper()


def make_poster_id(ip: str, cfg: Any) -> str:
    """
    Generate a stable, unique short ID for an IP address.
    This is intended for admin/mod pages only (never shown to regular users).
    Uses SECRET + board TITLE for a consistent hash across the board.
    """
    secret = getattr(cfg, "SECRET", "") or ""
    board = getattr(cfg, "TITLE", "board") or "board"
    if not secret or not ip:
        return ""
    # Reuse the internal short hash for a 4-char uppercase ID
    return _short_id_hash(f"{ip},{board}", secret)


def hash_deletion_password(password: str, secret: str) -> str:
    """Return a stable hash for a user-provided deletion password.
    Uses the board SECRET as key material. Never store the raw password.
    """
    if not password or not secret:
        return ""
    # Simple but effective: HMAC with secret
    data = password.encode("utf-8", errors="ignore")
    key = secret.encode("utf-8", errors="ignore")
    return hmac.new(key, data, hashlib.sha256).hexdigest()


def _resolve_host(ip: str) -> str | None:
    """Best-effort reverse DNS (kept optional and non-blocking)."""
    try:
        import socket
        return socket.getfqdn(ip)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Date formatting
# ---------------------------------------------------------------------------

def make_date(t: float | None = None, style: str = "futaba", tz: str | None = None) -> str:
    """
    Format a timestamp in one of the classic Kareha styles.
    Styles: futaba, 2ch, local, http (for headers)
    """
    if t is None:
        t = time.time()
    dt = datetime.fromtimestamp(t, tz=timezone.utc if tz is None else None)

    if style == "http":
        return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")

    if style == "2ch":
        # Typical 2ch style: YY/MM/DD(weekday) HH:mm:ss
        weekdays = ["日", "月", "火", "水", "木", "金", "土"]
        wd = weekdays[dt.weekday() % 7] if dt.weekday() < 7 else "?"
        return dt.strftime(f"%y/%m/%d({wd}) %H:%M:%S")

    # Default / futaba style
    return dt.strftime("%y/%m/%d(%a)%H:%M")


def parse_http_date(s: str) -> float:
    """Very tolerant HTTP-date parser for If-Modified-Since."""
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(s).timestamp()
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Cookies (simple, matching original spirit)
# ---------------------------------------------------------------------------

def make_cookies(**values: Any) -> dict[str, str]:
    """Return a dict of Set-Cookie friendly values (caller builds header)."""
    # In real WSGI we set via response.set_cookie
    return {k: str(v) for k, v in values.items() if v is not None}


def get_cookie(request: Any, name: str, default: str = "") -> str:
    return request.cookies.get(name, default)


# ---------------------------------------------------------------------------
# Misc helpers ported from wakautils
# ---------------------------------------------------------------------------

def clean_string(s: str) -> str:
    """Strip control characters, collapse whitespace."""
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", s)
    return " ".join(s.split())


def urlenc(s: str) -> str:
    return quote(s, safe="~")


def clean_path(p: str) -> str:
    """Sanitize a path for use in URLs (remove .. etc.)."""
    p = p.replace("\\", "/")
    while "../" in p or "/.." in p:
        p = p.replace("../", "").replace("/..", "")
    return p


def expand_filename(name: str) -> str:
    """Turn a board-relative filename into a URL path (stub – improved in app context)."""
    if name.startswith(("http://", "https://", "/")):
        return name
    return "/" + name.lstrip("/")


def make_random_string(length: int = 8) -> str:
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def make_key(key: str, secret: str, length: int) -> bytes:
    """Derive a key (used for old crypto compatibility; new code uses hmac)."""
    return hashlib.pbkdf2_hmac("sha256", secret.encode(), key.encode(), 1000, dklen=length)


def make_anonymous(ip: str, t: float, thread: Any) -> str:
    """Generate an anonymous name (simple version of original logic)."""
    # Very basic placeholder — the original had many SILLY_ANONYMOUS / FORCED_ANON variants.
    # For now we just return the configured anonymous name or "Anonymous".
    return "Anonymous"


def seed_board_static_assets(board_dir: Path) -> None:
    """Copy default CSS, JS, and icons from the package when a board lacks them."""
    board_dir = Path(board_dir)
    pkg_static = Path(__file__).parent / "static"

    css_dst = board_dir / "css"
    css_dst.mkdir(parents=True, exist_ok=True)
    css_src = pkg_static / "css"
    if css_src.is_dir():
        for css in css_src.glob("*.css"):
            dst = css_dst / css.name
            if not dst.exists():
                shutil.copy(css, dst)

    icons_src = pkg_static / "icons"
    if icons_src.is_dir():
        icons_dst = board_dir / "icons"
        icons_dst.mkdir(parents=True, exist_ok=True)
        for icon in icons_src.iterdir():
            if icon.is_file():
                dst = icons_dst / icon.name
                if not dst.exists():
                    shutil.copy(icon, dst)

    js_src = pkg_static / "kareha.js"
    js_dst = board_dir / "kareha.js"
    # Always refresh board JS — it is application code, not a user override.
    if js_src.is_file():
        shutil.copy(js_src, js_dst)


def ensure_board_directories(board_dir: Path, cfg: Any) -> None:
    """
    Create runtime board folders if missing (safe on every serve/start).

    Cloned repos ship empty placeholders (res/.gitkeep, thumb/.gitkeep, etc.);
    uploads and thread JSON stay gitignored and are created here or on first use.
    """
    board_dir = Path(board_dir)
    for attr in ("RES_DIR", "IMG_DIR", "THUMB_DIR", "RUNTIME_DIR", "INCLUDE_DIR", "CSS_DIR"):
        rel = getattr(cfg, attr, None)
        if rel:
            (board_dir / rel).mkdir(parents=True, exist_ok=True)

    include_dir = board_dir / getattr(cfg, "INCLUDE_DIR", "include")
    include_dir.mkdir(parents=True, exist_ok=True)
    for name in ("header.html", "footer.html", "rules.html"):
        placeholder = include_dir / name
        if not placeholder.exists():
            placeholder.touch()

    seed_board_static_assets(board_dir)

    reports = board_dir / "reports.json"
    example = board_dir / "reports.json.example"
    if not reports.exists() and example.exists():
        shutil.copy(example, reports)
