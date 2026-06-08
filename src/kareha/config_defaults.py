"""
Default configuration values for Kareha (Python port).

These mirror the structure and names from the original Perl config_defaults.pl
as closely as practical. User config.py can override any of them.

Supported modes (set via BOARD_MODE in config.py, or overridden via --mode / make_app(mode=...)):
  - "imageboard" (or "image"): full imageboard with thumbnails, file uploads, grid catalog, 4chan-like layout (default)
  - "textboard" (or "text", "message"): text-only board (no images on posts; still provides the classic grid catalog)
  - "blog": admin-only new entries (cookie-based), supports images on entries (configurable on comments via BLOG_COMMENTS),
            flat dated list on front + special linear catalog
"""
from __future__ import annotations

from dataclasses import dataclass, field, Field, MISSING
from typing import Any

# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------
ADMIN_PASS: str = "CHANGEME"          # REQUIRED - change this
SECRET: str = "CHANGEME"              # REQUIRED - long random secret for signing/hashing

# Board mode / personality. This is the primary way to choose the board type.
# It can be set here in config.py, or overridden by passing mode= to make_app()
# or --mode on the `kareha serve` CLI (the argument wins).
# Aliases are accepted: "image" for imageboard, "text"/"message" for textboard.
BOARD_MODE: str = "imageboard"

CAPPED_TRIPS: dict[str, str] = field(default_factory=dict)
# Special trip codes (raw like '!!secret' or the computed trip) that render
# the provided HTML instead of a normal trip (used for ## Admin / ## Mod badges).
# See config.py.example for usage. The first entry is used as default "Admin"
# capcode for blog-mode posts when the admin cookie is present.

# ---------------------------------------------------------------------------
# Page look & behavior
# ---------------------------------------------------------------------------
TITLE: str = "Kareha image board"
SUBTITLE: str = ""
SHOWTITLETXT: bool = True
SHOWTITLEIMG: int = 0
TITLEIMG: str = "title.jpg"
THREADS_DISPLAYED: int = 10
THREADS_LISTED: int = 40
REPLIES_PER_THREAD: int = 3   # Number of replies shown per thread on the front page (4chan-like)
S_ANONAME: str = "Anonymous"
DEFAULT_STYLE: str = "Burichan"
FAVICON: str = "kareha.ico"

# ---------------------------------------------------------------------------
# Limitations & auto-close
# ---------------------------------------------------------------------------
ALLOW_TEXT_THREADS: bool = True
ALLOW_TEXT_REPLIES: bool = True
AUTOCLOSE_POSTS: int = 0
AUTOCLOSE_DAYS: int = 0
AUTOCLOSE_SIZE: int = 0
MAX_RES: int = 20
MAX_THREADS: int = 0
MAX_POSTS: int = 500
MAX_MEGABYTES: int = 0
MAX_FIELD_LENGTH: int = 100
MAX_COMMENT_LENGTH: int = 8192
MAX_LINES_SHOWN: int = 15
ALLOW_ADMIN_EDIT: bool = False

# ---------------------------------------------------------------------------
# Image-specific (only relevant in image mode)
# ---------------------------------------------------------------------------
ALLOW_IMAGE_THREADS: bool = True
ALLOW_IMAGE_REPLIES: bool = True
IMAGE_REPLIES_PER_THREAD: int = 0
MAX_KB: int = 8192   # 8 MB (was 1000 = 1 MB)
MAX_W: int = 200
MAX_H: int = 200
THUMBNAIL_SMALL: bool = True
THUMBNAIL_QUALITY: int = 85
ALLOW_UNKNOWN: bool = False
MUNGE_UNKNOWN: str = ".unknown"
FORBIDDEN_EXTENSIONS: tuple[str, ...] = (
    "php", "php3", "php4", "phtml", "shtml", "cgi", "pl", "pm", "py", "r",
    "exe", "dll", "scr", "pif", "asp", "cfm", "jsp", "vbs"
)

# Allowed media for general boards (popular, safe filetypes; no executables)
ALLOWED_EXTENSIONS: tuple[str, ...] = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".webm", ".mp4", ".mkv", ".mov",
    ".mp3", ".ogg", ".flac", ".wav"
)

# Blog mode (admin-only uploads) can be more permissive (archives, docs, etc.)
BLOG_ALLOWED_EXTENSIONS: tuple[str, ...] = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".webm", ".mp4", ".mkv", ".mov",
    ".mp3", ".ogg", ".flac", ".wav",
    ".pdf", ".zip", ".7z", ".rar", ".tar", ".gz", ".txt", ".md"
)
STUPID_THUMBNAILING: bool = False
MAX_IMAGE_WIDTH: int = 16384
MAX_IMAGE_HEIGHT: int = 16384
MAX_IMAGE_PIXELS: int = 50_000_000

# ---------------------------------------------------------------------------
# Captcha (simplified modern implementation)
# ---------------------------------------------------------------------------
ENABLE_CAPTCHA: bool = False
CAPTCHA_HEIGHT: int = 18
CAPTCHA_DIFFICULTY: float = 0.6   # 0.0 easy ... 1.0 hard (affects distortion/noise)
CAPTCHA_EXPIRY_SECONDS: int = 180  # 3 minutes (shorter for better security vs 10min)

# Simple in-memory rate limiting (per IP). For production with Caddy, combine with Caddy's rate limiting.
RATE_LIMIT_POSTS_PER_MIN: int = 5
RATE_LIMIT_WINDOW_SECONDS: int = 60

# ---------------------------------------------------------------------------
# Tweaks & features
# ---------------------------------------------------------------------------
CHARSET: str = "utf-8"
TRIM_METHOD: int = 0
REQUIRE_THREAD_TITLE: bool = False
DATE_STYLE: str = "futaba"          # futaba, 2ch, etc.

# Blog mode ( --mode blog ): only admins (cookie) can create new entries.
# Entries support file uploads / images when ALLOW_IMAGE_THREADS (default on for blog).
# BLOG_COMMENTS controls replies:
#   "enabled"   - full comments (images allowed if ALLOW_IMAGE_REPLIES)
#   "disabled"  - hide reply form entirely
#   "text_only" - show reply form but force no file upload (text comments only)
BLOG_COMMENTS: str = "enabled"
DISPLAY_ID: str = ""                # '', 'ip', 'mask', 'thread', 'link' etc. (IP-based randomized IDs)
EMAIL_ID: str = "Heaven"
SILLY_ANONYMOUS: str = ""
FORCED_ANON: bool = False
TRIPKEY: str = "!"
ALTERNATE_REDIRECT: bool = False
APPROX_LINE_LENGTH: int = 150
COOKIE_PATH: str = "root"
STYLE_COOKIE: str = "wakabastyle"
ENABLE_DELETION: bool = True
PAGE_GENERATION: str = "paged"      # paged | monthly | single
DELETE_FIRST: str = "remove"
MARKUP_FORMATS: tuple[str, ...] = ("waka",)   # image mode default; message uses more
DEFAULT_MARKUP: str = "waka"
FUDGE_BLOCKQUOTES: bool = True
USE_XHTML: bool = True
KEEP_MAINPAGE_NEWLINES: bool = False
SPAM_TRAP: bool = True

# Anti-abuse: repetitive / near-duplicate posts (even if text is slightly randomized)
DUPLICATE_WINDOW: int = 300          # seconds within which similar posts from same IP are rejected
DUPLICATE_THRESHOLD: float = 0.80    # similarity ratio (0.0-1.0) using difflib that counts as "repetitive"

# Ban images by MD5 (e.g. illegal or unwanted content). One hash per line in the file.
BANNED_MD5_FILE: str = "banned_md5.txt"

# ---------------------------------------------------------------------------
# Paths (relative to board root)
# ---------------------------------------------------------------------------
RES_DIR: str = "res/"
CSS_DIR: str = "css/"
IMG_DIR: str = "src/"
THUMB_DIR: str = "thumb/"
INCLUDE_DIR: str = "include/"
LOG_FILE: str = "log.txt"
PAGE_EXT: str = ".html"
HTML_SELF: str = "index.html"
HTML_BACKLOG: str = ""
RSS_FILE: str = ""
JS_FILE: str = "kareha.js"
SPAM_FILES: tuple[str, ...] = ("spam.txt",)

# Admin
ADMIN_SHOWN_LINES: int = 10
ADMIN_SHOWN_POSTS: int = 10
ADMIN_MASK_IPS: bool = True
ADMIN_EDITABLE_FILES: tuple[str, ...] = SPAM_FILES + (BANNED_MD5_FILE,)
ADMIN_BAN_FILE: str = ".htaccess"   # or None to disable .htaccess style bans
ADMIN_BAN_TEMPLATE: str = """# Banned IP: <var $reason> (<var $date>)\nDeny from <var $ip>\n"""

# Filetype icons (for non-image uploads in image mode)
FILETYPES: dict[str, str] = {
    "zip": "static/icons/archive-zip.png",
    "rar": "static/icons/archive-rar.png",
    "7z":  "static/icons/archive-7z.png",
    "mp3": "static/icons/audio-mp3.png",
    "ogg": "static/icons/audio-ogg.png",
    "flac": "static/icons/audio-flac.png",
    # add more as needed; thumbnails will use these when unknown
}

# Allowed HTML for "html" and "waka" markups (tag -> {args, forced, empty})
ALLOWED_HTML: dict[str, dict[str, Any]] = {
    "a": {"args": ("href",), "forced": {"rel": "nofollow"}, "empty": False},
    "b": {"args": (), "forced": {}, "empty": False},
    "i": {"args": (), "forced": {}, "empty": False},
    "u": {"args": (), "forced": {}, "empty": False},
    "strong": {"args": (), "forced": {}, "empty": False},
    "em": {"args": (), "forced": {}, "empty": False},
    "span": {"args": ("class",), "forced": {}, "empty": False},
    "br": {"args": (), "forced": {}, "empty": True},
    "p": {"args": (), "forced": {}, "empty": False},
    "blockquote": {"args": (), "forced": {}, "empty": False},
    "ul": {"args": (), "forced": {}, "empty": False},
    "ol": {"args": (), "forced": {}, "empty": False},
    "li": {"args": (), "forced": {}, "empty": False},
    "code": {"args": (), "forced": {}, "empty": False},
    "pre": {"args": (), "forced": {}, "empty": False},
}

# ---------------------------------------------------------------------------
# Mode-specific adjustments (applied after loading)
# ---------------------------------------------------------------------------
def apply_mode_defaults(mode: str, cfg: dict[str, Any]) -> None:
    """Mutate cfg with mode-specific sane defaults (called by config loader).

    Accepts either a raw value (with aliases) or a canonical BOARD_MODE.
    """
    m = (mode or "imageboard").lower().strip()
    if m in ("message", "text", "textboard"):
        if str(cfg.get("TITLE", "")).startswith("Kareha "):
            cfg["TITLE"] = "Kareha text board"
        cfg["DEFAULT_STYLE"] = "Headline"
        cfg["MARKUP_FORMATS"] = ("none", "waka", "html", "aa")
        cfg["DEFAULT_MARKUP"] = "waka"
        cfg["REQUIRE_THREAD_TITLE"] = True
        cfg["AUTOCLOSE_POSTS"] = 1000
        cfg["TRIM_METHOD"] = 1
        cfg["DATE_STYLE"] = "2ch"
        cfg["PAGE_GENERATION"] = "single"
        cfg["RSS_FILE"] = "index.rss"
        cfg["HTML_BACKLOG"] = "backlog.html"
        # textboard: text only (images forced off regardless of user config)
        cfg["ALLOW_IMAGE_THREADS"] = False
        cfg["ALLOW_IMAGE_REPLIES"] = False
    elif m == "blog":
        if str(cfg.get("TITLE", "")).startswith("Kareha "):
            cfg["TITLE"] = "Blog"
        cfg["DEFAULT_STYLE"] = "Burichan"
        cfg["MARKUP_FORMATS"] = ("waka",)
        cfg["DEFAULT_MARKUP"] = "waka"
        cfg["REQUIRE_THREAD_TITLE"] = True
        cfg["AUTOCLOSE_POSTS"] = 0
        cfg["PAGE_GENERATION"] = "single"
        # blog: admin-only entries (images allowed by default via ALLOW_IMAGE_THREADS),
        # comments gated by BLOG_COMMENTS ("enabled" | "disabled" | "text_only").
        # Unlike textboard, we do not force images off here; user config or base defaults apply.
        # (BLOG_COMMENTS="text_only" will still suppress file fields on reply forms.)
    else:
        # imageboard (default) - ensure images on (leave TITLE as user/default provided)
        cfg["MARKUP_FORMATS"] = ("waka",)
        cfg["DEFAULT_MARKUP"] = "waka"
        cfg["PAGE_GENERATION"] = "paged"
        cfg["ALLOW_IMAGE_THREADS"] = True
        cfg["ALLOW_IMAGE_REPLIES"] = True


@dataclass
class BoardConfig:
    """Frozen runtime config object. All values are simple types or tuples."""
    # We populate this dynamically from the module + user overrides.
    # For convenience in code we expose attributes.
    pass


# Helper to turn the module-level constants into a dict (for BoardConfig)
def get_defaults_dict() -> dict[str, Any]:
    """Return a fresh dict of all the module-level settings above."""
    d = {}
    for k, v in globals().items():
        if k.isupper() and not k.startswith("_"):
            if isinstance(v, Field):
                if v.default is not MISSING:
                    d[k] = v.default
                elif v.default_factory is not MISSING:
                    d[k] = v.default_factory()
                else:
                    d[k] = None
            else:
                d[k] = v
    return d
