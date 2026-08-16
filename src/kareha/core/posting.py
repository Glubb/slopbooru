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
from ..filelock import storage_lock
from ..image import analyze_image, compute_md5, make_thumbnail, get_file_icon
from ..markup import format_comment
from ..spam import spam_engine
from ..utils import make_id_code, make_poster_id, hash_deletion_password, process_tripcode, make_anonymous, make_date
from .admin import is_ip_banned
from .models import Post, Thread
from .storage import (
    delete_thread,
    get_next_post_num,
    list_threads,
    load_thread,
    save_post_num,
    save_thread,
)


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
    force_capcode: str = "",
) -> int:
    """
    Main entry point for creating a new post (thread or reply).

    Returns the post number (or thread id for new threads).
    Raises PostError on any failure (validation, spam, etc.).
    """
    cfg = _get_cfg()
    res_dir = Path(board_dir) / getattr(cfg, "RES_DIR", "res/")

    if is_ip_banned(ip, board_dir, cfg):
        raise PostError("You are banned from posting on this board.")

    # Basic validation
    if not comment.strip() and not file_path:
        raise PostError("No text entered.")

    if len(comment) > getattr(cfg, "MAX_COMMENT_LENGTH", 8192):
        raise PostError("Comment too long.")

    if len(name) > getattr(cfg, "MAX_FIELD_LENGTH", 100):
        raise PostError("Name too long.")

    # --- Anti-repetitive / randomized spam protection ---
    # Even if the post is slightly randomized, we normalize and compare against recent posts by IP.
    import re
    from difflib import SequenceMatcher
    now = int(time.time())
    ip = ip or "0.0.0.0"
    norm = re.sub(r'[^a-z0-9]', '', (comment or '').lower())
    if norm:
        # simple in-memory recent cache (pruned) — lives for the life of the worker process
        global _recent_posts
        if '_recent_posts' not in globals():
            _recent_posts = {}
        last = _recent_posts.get(ip)
        window = getattr(cfg, "DUPLICATE_WINDOW", 300)
        thresh = getattr(cfg, "DUPLICATE_THRESHOLD", 0.80)
        if last:
            last_norm, last_ts = last
            if now - last_ts < window:
                sim = SequenceMatcher(None, norm, last_norm).ratio()
                if sim >= thresh:
                    raise PostError("Repetitive or duplicate post detected (even with randomization).")
        _recent_posts[ip] = (norm, now)
        # prune old entries
        for k in list(_recent_posts.keys()):
            if now - _recent_posts[k][1] > window * 2:
                del _recent_posts[k]

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
    original_name = name
    name, trip = process_tripcode(name, tripkey, secret)
    if not name and not trip:
        name = make_anonymous(ip, now, thread_id or now)

    # CAPPED_TRIPS support for admin/mod capcodes (e.g. special trips become " ## Admin")
    # Supports keys as either the raw entered trip (e.g. '!!secret') or the computed trip.
    capcode = ""
    capped_trips = getattr(cfg, "CAPPED_TRIPS", {})
    matched = False
    if trip and trip in capped_trips:
        capcode = capped_trips[trip]
        matched = True
    else:
        # Check the raw entered tripcode (e.g. user types "Admin!!secret" or just "!!secret")
        if tripkey in original_name:
            raw_trip_part = original_name.split(tripkey, 1)[1]
            raw_trip = f"{tripkey}{raw_trip_part}"
            if raw_trip in capped_trips:
                capcode = capped_trips[raw_trip]
                trip = ""  # prevent showing both the computed trip and the capcode
                matched = True
    if matched:
        pass  # capcode set silently for prod (debug prints removed)

    if force_capcode:
        capcode = force_capcode

    # ID code (DISPLAY_ID feature the user specifically wanted)
    date = make_date(now, getattr(cfg, "DATE_STYLE", "futaba"))
    display_id = getattr(cfg, "DISPLAY_ID", "")
    if display_id:
        id_code = make_id_code(ip, now, link, str(thread_id or now), cfg)
        if id_code:
            date += f" ID:{id_code}"

    # Always assign a unique poster ID based on IP for admin/mod visibility only.
    # This is computed here so it's stored with the post and available on mod pages.
    poster_id = make_poster_id(ip, cfg)

    # Deletion password hash (for item 5)
    delpass = password or ""
    delpass_hash = hash_deletion_password(delpass, secret) if delpass else ""

    # Handle file upload
    image_info = None
    if file_path:
        board_mode = getattr(cfg, "BOARD_MODE", "imageboard")
        if board_mode == "textboard":
            raise PostError("Image posting not allowed in this context.")
        # imageboard and blog are controlled by ALLOW_IMAGE_THREADS / ALLOW_IMAGE_REPLIES
        # (blog new entries by admins; replies respect the flags; text_only for blog comments
        #  only hides the file input in the form)
        allow_key = "ALLOW_IMAGE_THREADS" if not thread_id else "ALLOW_IMAGE_REPLIES"
        if not getattr(cfg, allow_key, True):
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

            # MD5 duplicate check (using our storage layer) - now does storage deduplication
            md5 = compute_md5(file_path)

            # Image ban list by MD5 (anti-abuse for illegal/unwanted content)
            if md5 and _md5_is_banned(board_dir, cfg, md5):
                raise PostError("This image has been banned.")

            duplicate_post = None
            if md5:
                for meta in list_threads(res_dir):
                    t = load_thread(res_dir, meta["thread"])
                    if t:
                        for p in t.posts:
                            if p.md5 and p.md5 == md5:
                                duplicate_post = p
                                break
                        if duplicate_post:
                            break

            if duplicate_post:
                # Dedup storage: reuse the existing file + thumbnail paths + metadata
                image_info = {
                    "image": duplicate_post.image,
                    "thumbnail": duplicate_post.thumbnail,
                    "ext": duplicate_post.ext,
                    "size": duplicate_post.size,
                    "width": duplicate_post.width,
                    "height": duplicate_post.height,
                    "tn_width": duplicate_post.tn_width,
                    "tn_height": duplicate_post.tn_height,
                    "md5": duplicate_post.md5,
                }
            else:
                # Copy + thumbnail (new unique file)
                filebase = f"{now}{int(time.time()*1000) % 1000:03d}"
                img_dir = Path(board_dir) / getattr(cfg, "IMG_DIR", "src/")
                thumb_dir = Path(board_dir) / getattr(cfg, "THUMB_DIR", "thumb/")
                img_dir.mkdir(parents=True, exist_ok=True)
                thumb_dir.mkdir(parents=True, exist_ok=True)

                final_image = img_dir / f"{filebase}.{ext}"
                final_thumb = thumb_dir / f"{filebase}s.jpg"

                import shutil
                import os

                shutil.copy2(file_path, final_image)
                os.chmod(final_image, 0o644)

                if not final_image.exists():
                    raise PostError("Failed to save the uploaded file to disk.")

                max_w = getattr(cfg, "MAX_W", 200)
                max_h = getattr(cfg, "MAX_H", 200)
                quality = getattr(cfg, "THUMBNAIL_QUALITY", 85)
                thumb_success, tn_w, tn_h = make_thumbnail(
                    final_image, final_thumb, max_w, max_h, quality
                )

                if thumb_success:
                    try:
                        os.chmod(final_thumb, 0o644)
                    except Exception:
                        pass

                rel_image = f"{getattr(cfg, 'IMG_DIR', 'src/')}{filebase}.{ext}".lstrip('/')
                rel_thumb = f"{getattr(cfg, 'THUMB_DIR', 'thumb/')}{filebase}s.jpg".lstrip('/') if thumb_success else None

                image_info = {
                    "image": rel_image,
                    "thumbnail": rel_thumb,
                    "ext": ext,
                    "size": final_image.stat().st_size,
                    "width": width,
                    "height": height,
                    "tn_width": tn_w,
                    "tn_height": tn_h,
                    "md5": md5 or "",
                }

    # Create or append to thread (single lock: number + JSON write)
    with storage_lock(res_dir):
        if thread_id:
            thread = load_thread(res_dir, thread_id)
            if not thread:
                raise PostError("Thread not found.")
            if thread.closed or _should_autoclose(thread, res_dir, cfg, now):
                if not thread.closed:
                    thread.closed = True
                    save_thread(thread, res_dir)
                raise PostError("Thread is closed.")

            max_posts = int(getattr(cfg, "MAX_POSTS", 0) or 0)
            if max_posts and thread.postcount >= max_posts and not thread.pinned:
                thread.closed = True
                save_thread(thread, res_dir)
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
                poster_id=poster_id,
                delpass_hash=delpass_hash,
                capcode=capcode,
                ip=ip,
                **(image_info or {}),
            )
            thread.add_post(post)
            if not thread.permasage:
                thread.lasthit = now
            thread.lastmod = now
            if (not thread.pinned) and (
                _should_autoclose(thread, res_dir, cfg, now)
                or (max_posts and thread.postcount >= max_posts)
            ):
                thread.closed = True
            save_thread(thread, res_dir)
            save_post_num(res_dir, num)
            return num

        # New thread
        board_mode = getattr(cfg, "BOARD_MODE", "")
        if (getattr(cfg, "REQUIRE_THREAD_TITLE", False) or board_mode == "blog") and not title.strip():
            raise PostError("Title required.")

        num = get_next_post_num(res_dir)
        new_thread = Thread(
            thread=num,
            title=title or "Untitled",
            author=name + trip,
            lasthit=now,
            lastmod=now,
            created=now,
        )
        post = Post(
            num=num,
            name=name,
            trip=trip,
            link=link,
            date=date,
            comment_html=format_comment(comment, markup, str(num), getattr(cfg, "ALLOWED_HTML", {})),
            comment_raw=comment,
            poster_id=poster_id,
            delpass_hash=delpass_hash,
            capcode=capcode,
            ip=ip,
            **(image_info or {}),
        )
        new_thread.add_post(post)
        save_thread(new_thread, res_dir)
        save_post_num(res_dir, num)
        trim_threads(board_dir, cfg)
        return num


def _md5_is_banned(board_dir: Path, cfg: Any, md5: str) -> bool:
    banned_file = Path(board_dir) / getattr(cfg, "BANNED_MD5_FILE", "banned_md5.txt")
    if not banned_file.exists():
        return False
    try:
        banned = {
            line.strip().split()[0].lower()
            for line in banned_file.read_text(encoding="utf-8", errors="ignore").splitlines()
            if line.strip() and not line.strip().startswith("#")
        }
    except OSError:
        return False
    return md5.lower() in banned


def thread_created_ts(thread: Thread) -> int:
    if thread.created:
        return int(thread.created)
    if thread.thread >= 100_000_000:
        return int(thread.thread)
    return int(thread.lastmod or thread.lasthit or 0)


def _should_autoclose(thread: Thread, res_dir: Path, cfg: Any, now: int) -> bool:
    if getattr(thread, "pinned", False):
        return False
    ac_posts = int(getattr(cfg, "AUTOCLOSE_POSTS", 0) or 0)
    if ac_posts and thread.postcount >= ac_posts:
        return True
    ac_days = int(getattr(cfg, "AUTOCLOSE_DAYS", 0) or 0)
    if ac_days:
        created = thread_created_ts(thread)
        if created and now - created >= ac_days * 86400:
            return True
    ac_size = int(getattr(cfg, "AUTOCLOSE_SIZE", 0) or 0)
    if ac_size:
        path = Path(thread.filename) if thread.filename else Path(res_dir) / f"{thread.thread}.json"
        try:
            if path.exists() and path.stat().st_size >= ac_size * 1024:
                return True
        except OSError:
            pass
    return False


def _dir_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            continue
    return total


def trim_threads(board_dir: Path, cfg: Any = None) -> None:
    """
    Enforce MAX_THREADS / MAX_MEGABYTES by deleting overflow threads.

    TRIM_METHOD 0 (default): drop least-recently-bumped (tail of lasthit order).
    TRIM_METHOD 1: drop oldest by creation time.
    Caller should already hold storage_lock when used from post_stuff.
    """
    cfg = cfg or _get_cfg()
    res_dir = Path(board_dir) / getattr(cfg, "RES_DIR", "res/")
    max_threads = int(getattr(cfg, "MAX_THREADS", 0) or 0)
    trim_method = int(getattr(cfg, "TRIM_METHOD", 0) or 0)

    metas = list_threads(res_dir, sort_by="lasthit")
    unpinned = [m for m in metas if not m.get("pinned")]
    to_delete: list[int] = []

    if max_threads > 0 and len(unpinned) > max_threads:
        overflow = len(unpinned) - max_threads
        if trim_method == 1:
            oldest = sorted(unpinned, key=lambda x: (x.get("created") or 0, x.get("thread") or 0))
            to_delete.extend(int(m["thread"]) for m in oldest[:overflow])
        else:
            to_delete.extend(int(m["thread"]) for m in unpinned[max_threads:])

    max_mb = int(getattr(cfg, "MAX_MEGABYTES", 0) or 0)
    if max_mb > 0:
        limit = max_mb * 1024 * 1024
        img_dir = Path(board_dir) / getattr(cfg, "IMG_DIR", "src/")
        thumb_dir = Path(board_dir) / getattr(cfg, "THUMB_DIR", "thumb/")
        # Drop least-recently-bumped unpinned threads until under the cap.
        remaining = [m for m in unpinned if int(m["thread"]) not in to_delete]
        while remaining and (
            _dir_size_bytes(res_dir) + _dir_size_bytes(img_dir) + _dir_size_bytes(thumb_dir)
        ) > limit:
            victim = remaining.pop()
            tid = int(victim["thread"])
            if tid not in to_delete:
                to_delete.append(tid)
            if len(remaining) <= 1:
                break

    for tid in to_delete:
        delete_thread(res_dir, tid, board_dir=board_dir)
