"""
Core posting logic for Kareha-Py.

This is the Python equivalent of the original post_stuff / make_reply / trim_threads flow,
but adapted to our pragmatic storage model and modern Python.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

from .. import config as config_module
from ..image import analyze_image, compute_md5, make_thumbnail, get_file_icon
from ..markup import format_comment
from ..spam import spam_engine
from ..utils import make_id_code, process_tripcode, make_anonymous, make_date
from .models import Post, Thread
from .storage import load_thread, save_thread, list_threads, get_next_post_num, save_post_num


class PostError(Exception):
    """Raised when a post is rejected for any reason (validation, spam, etc.)."""
    pass


def _get_cfg():
    # In real usage this will come from the app context.
    # For now we provide sensible defaults so the module can be tested standalone.
    return getattr(config_module, "current_config", None) or {}


def post_stuff(
    board_dir: Path,
    *,
    thread_id: Optional[int] = None,
    name: str = "",
    link: str = "",
    title: str = "",
    comment: str = "",
    captcha: str = "",
    password: str = "",
    markup: str = "waka",
    file_path: Optional[str] = None,
    upload_filename: Optional[str] = None,
    ip: str = "127.0.0.1",
    mode: str = "imageboard",
    honeypot_email: str = "",
    honeypot_url: str = "",
) -> int:
    """
    Main entry point for creating a new post (thread or reply).

    Returns the post number (or thread id for new threads).
    Raises PostError on any failure (validation, spam, etc.).
    """
    cfg = _get_cfg()
    res_dir = Path(board_dir) / getattr(cfg, "RES_DIR", "res/")

    # Basic validation
    if not comment.strip() and not file_path:
        raise PostError("No text entered.")

    if len(comment) > getattr(cfg, "MAX_COMMENT_LENGTH", 8192):
        raise PostError("Comment too long.")

    if len(name) > getattr(cfg, "MAX_FIELD_LENGTH", 100):
        raise PostError("Name too long.")

    # Spam check (very important)
    spam_files = [Path(board_dir) / f for f in getattr(cfg, "SPAM_FILES", ["spam.txt"])]

    # Real fields for the spam pattern matcher
    params = {"name": name, "link": link, "title": title, "comment": comment}

    is_spam = False

    # 1. Honeypot check (hidden fields that should always be empty for humans)
    if honeypot_email or honeypot_url:
        is_spam = True

    # 2. Run classic spam.txt patterns if honeypots passed
    if not is_spam:
        is_spam = spam_engine(params, spam_files, trap_fields=[])

    if is_spam:
        raise PostError("Spam detected.")

    # Captcha stub (real implementation later)
    if getattr(cfg, "ENABLE_CAPTCHA", False):
        # For now we just warn in logs; real captcha comes in PR 5/6 polish
        pass

    now = int(time.time())

    # Tripcode + anonymous name
    tripkey = getattr(cfg, "TRIPKEY", "!")
    secret = getattr(cfg, "SECRET", "")
    name, trip = process_tripcode(name, tripkey, secret)
    if not name and not trip:
        name = make_anonymous(ip, now, thread_id or now)

    # ID code (DISPLAY_ID feature the user specifically wanted)
    date = make_date(now, getattr(cfg, "DATE_STYLE", "futaba"))
    display_id = getattr(cfg, "DISPLAY_ID", "")
    if display_id:
        id_code = make_id_code(ip, now, link, str(thread_id or now), cfg)
        if id_code:
            date += f" ID:{id_code}"

    # Handle file upload (image mode only)
    image_info = None
    if file_path:
        m = (mode or "").lower()
        is_image = m in ("image", "imageboard")
        if not is_image or not getattr(cfg, "ALLOW_IMAGE_THREADS" if not thread_id else "ALLOW_IMAGE_REPLIES", True):
            raise PostError("Image posting not allowed in this context.")

        ext, width, height = analyze_image(file_path, upload_filename or "")
        if width == 0 and height == 0:
            # Non-image file — use icon if known
            icon = get_file_icon(ext)
            if icon:
                image_info = {
                    "image": icon,
                    "ext": ext,
                    "size": Path(file_path).stat().st_size,
                    "width": 0, "height": 0,
                }
        else:
            # Real image
            max_kb = getattr(cfg, "MAX_KB", 8192)
            if Path(file_path).stat().st_size > max_kb * 1024:
                raise PostError(f"File too large (max {max_kb} KB / {max_kb // 1024} MB).")

            # MD5 duplicate check (using our storage layer)
            md5 = compute_md5(file_path)
            if md5:
                # Very naive scan for now (fine for small boards)
                for meta in list_threads(res_dir):
                    t = load_thread(res_dir, meta["thread"])
                    if t:
                        for p in t.posts:
                            if p.md5 and p.md5 == md5:
                                raise PostError(f"Duplicate file posted in thread {t.thread}")

            # Copy + thumbnail
            filebase = f"{now}{int(time.time()*1000) % 1000:03d}"
            img_dir = Path(board_dir) / getattr(cfg, "IMG_DIR", "src/")
            thumb_dir = Path(board_dir) / getattr(cfg, "THUMB_DIR", "thumb/")
            img_dir.mkdir(parents=True, exist_ok=True)
            thumb_dir.mkdir(parents=True, exist_ok=True)

            final_image = img_dir / f"{filebase}.{ext}"
            final_thumb = thumb_dir / f"{filebase}s.jpg"

            # Copy the original safely (much more robust than rename for uploads from temp files)
            import shutil
            import os

            shutil.copy2(file_path, final_image)

            # Fix permissions - NamedTemporaryFile often creates 600 files which can cause serving issues
            os.chmod(final_image, 0o644)

            if not final_image.exists():
                raise PostError("Failed to save the uploaded file to disk.")

            # Thumbnail
            max_w = getattr(cfg, "MAX_W", 200)
            max_h = getattr(cfg, "MAX_H", 200)
            quality = getattr(cfg, "THUMBNAIL_QUALITY", 85)
            thumb_success = make_thumbnail(final_image, final_thumb, max_w, max_h, quality)

            if thumb_success:
                try:
                    os.chmod(final_thumb, 0o644)
                except Exception:
                    pass

            # Store relative paths (e.g. "src/xxx.jpg") so templates and URLs stay clean
            rel_image = f"{getattr(cfg, 'IMG_DIR', 'src/')}{filebase}.{ext}".lstrip('/')
            rel_thumb = f"{getattr(cfg, 'THUMB_DIR', 'thumb/')}{filebase}s.jpg".lstrip('/') if thumb_success else None

            image_info = {
                "image": rel_image,
                "thumbnail": rel_thumb,
                "ext": ext,
                "size": final_image.stat().st_size,
                "width": width,
                "height": height,
                "md5": md5 or "",
            }

            if not thumb_success:
                print(f"[WARNING] Failed to generate thumbnail for {final_image}")  # visible in terminal

    # Create or append to thread
    if thread_id:
        thread = load_thread(res_dir, thread_id)
        if not thread:
            raise PostError("Thread not found.")
        if thread.closed:
            raise PostError("Thread is closed.")

        num = get_next_post_num(res_dir)
        post = Post(
            num=num,
            name=name,
            trip=trip,
            link=link,
            date=date,
            comment_html=format_comment(comment, markup, str(thread_id), getattr(cfg, "ALLOWED_HTML", {})),
            comment_raw=comment,
            **(image_info or {}),
        )
        thread.add_post(post)
        thread.lasthit = now
        thread.lastmod = now
        save_thread(thread, res_dir)
        save_post_num(res_dir, num)
        return num
    else:
        # New thread
        if getattr(cfg, "REQUIRE_THREAD_TITLE", False) and not title.strip():
            raise PostError("Title required.")

        num = get_next_post_num(res_dir)
        new_thread = Thread(
            thread=num,
            title=title or "Untitled",
            author=name + trip,
            lasthit=now,
            lastmod=now,
        )
        post = Post(
            num=num,
            name=name,
            trip=trip,
            link=link,
            date=date,
            comment_html=format_comment(comment, markup, str(num), getattr(cfg, "ALLOWED_HTML", {})),
            comment_raw=comment,
            **(image_info or {}),
        )
        new_thread.add_post(post)
        save_thread(new_thread, res_dir)
        save_post_num(res_dir, num)
        return num


def trim_threads(board_dir: Path, cfg: Any = None) -> None:
    """Stub for now — real trimming logic (MAX_THREADS, AUTOCLOSE_*, etc.) will go here."""
    # Placeholder for PR 5 completion
    pass
