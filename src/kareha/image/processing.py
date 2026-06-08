"""
Image analysis and thumbnailing using only Pillow (no external convert, no subprocess).

Designed to be a drop-in replacement for the original analyze_image + make_thumbnail
logic while being much simpler and more reliable on modern systems.
"""
from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, ImageOps

# Supported image formats for actual image posts (not the icon fallbacks)
SUPPORTED_FORMATS = {"JPEG", "PNG", "GIF", "WEBP", "BMP"}

# Very small set of known non-image filetypes that get icon thumbnails (same spirit as original FILETYPES)
ICON_THUMBNAILS: dict[str, str] = {
    ".zip": "static/icons/archive-zip.png",
    ".rar": "static/icons/archive-rar.png",
    ".7z": "static/icons/archive-7z.png",
    ".mp3": "static/icons/audio-mp3.png",
    ".ogg": "static/icons/audio-ogg.png",
    ".flac": "static/icons/audio-flac.png",
    ".torrent": "static/icons/torrent.png",
}


def analyze_image(file_path: str | Path | io.BytesIO, filename: str = "") -> Tuple[str, int, int]:
    """
    Analyze an uploaded file.

    Returns (ext, width, height).
    For unknown/non-image files, returns (ext.lower(), 0, 0) so the caller can decide
    whether to allow it (ALLOW_UNKNOWN) and serve a generic icon.
    """
    path = Path(filename or getattr(file_path, "name", "unknown"))
    ext = path.suffix.lower().lstrip(".")

    # Try to open as image
    try:
        if isinstance(file_path, (str, Path)):
            with Image.open(file_path) as im:
                im = ImageOps.exif_transpose(im)
                w, h = im.size
                fmt = (im.format or "").upper()
        else:
            # BytesIO or file-like
            pos = file_path.tell() if hasattr(file_path, "tell") else None
            with Image.open(file_path) as im:
                im = ImageOps.exif_transpose(im)
                w, h = im.size
                fmt = (im.format or "").upper()
            if pos is not None:
                file_path.seek(pos)

        if fmt in SUPPORTED_FORMATS:
            return ext or fmt.lower(), w, h
        # Image but exotic format
        return ext or "unknown", w, h

    except Exception:
        # Not a readable image (or corrupted) — treat as data file
        return ext or "bin", 0, 0


def make_thumbnail(
    src_path: str | Path,
    dst_path: str | Path,
    max_w: int,
    max_h: int,
    quality: int = 85,
    force_jpeg: bool = True,
) -> bool:
    """
    Create a thumbnail using Pillow.

    Returns True on success.
    """
    try:
        with Image.open(src_path) as im:
            im = ImageOps.exif_transpose(im)

            # Convert to RGB for JPEG output (handles RGBA, palette, etc.)
            if force_jpeg and im.mode in ("RGBA", "LA", "P"):
                background = Image.new("RGB", im.size, (255, 255, 255))
                if im.mode == "P":
                    im = im.convert("RGBA")
                background.paste(im, mask=im.split()[-1] if im.mode in ("RGBA", "LA") else None)
                im = background
            elif im.mode not in ("RGB", "L"):
                im = im.convert("RGB")

            im.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)

            dst = Path(dst_path)
            dst.parent.mkdir(parents=True, exist_ok=True)

            if force_jpeg or dst.suffix.lower() in (".jpg", ".jpeg"):
                im.save(dst, "JPEG", quality=quality, optimize=True)
            else:
                im.save(dst)

        return True
    except Exception:
        return False


def compute_md5(file_path: str | Path) -> Optional[str]:
    """Return hex MD5 of the file contents (used for duplicate detection)."""
    try:
        h = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def get_file_icon(ext: str) -> Optional[str]:
    """Return a static icon path for known non-image file types."""
    key = "." + ext.lower().lstrip(".")
    return ICON_THUMBNAILS.get(key)
