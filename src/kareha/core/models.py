"""
Data models for threads and posts.

Pragmatic design: simple dataclasses that work well with both JSON storage
and future SQLite if we ever add it. No heavy validation here — the posting
layer is responsible for correctness.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Post:
    num: int
    name: str = ""
    trip: str = ""
    link: str = ""
    date: str = ""
    comment_html: str = ""
    comment_raw: str = ""
    # Image fields (only populated in image mode)
    image: Optional[str] = None
    thumbnail: Optional[str] = None
    ext: str = ""
    size: int = 0
    width: int = 0
    height: int = 0
    tn_width: int = 0
    tn_height: int = 0
    md5: str = ""

    # Moderation
    deleted: bool = False
    deleted_by: str = ""   # "user" or "admin"

    # Mod-only unique ID per IP (computed at post time, never shown publicly)
    poster_id: str = ""

    # Deletion password hash (salted with board secret). If set, user delete must match.
    delpass_hash: str = ""

    # Capcode for admin/mod posts (from CAPPED_TRIPS config). Rendered as raw HTML.
    capcode: str = ""

    # Raw IP for admin use only (for banning etc.)
    ip: str = ""

    def is_op(self) -> bool:
        # Deprecated: use thread.thread == post.num or check position in list
        return False  # now uses global nums; OP is posts[0] or thread id match


@dataclass
class Thread:
    thread: int                 # timestamp id (also the filename base)
    title: str = ""
    author: str = ""            # original poster name+ trip
    postcount: int = 0
    lasthit: int = 0
    lastmod: int = 0
    permasage: bool = False
    closed: bool = False

    posts: list[Post] = field(default_factory=list)

    # Runtime / derived
    filename: str = ""          # full path to the JSON file
    omit: int = 0
    omitimages: int = 0

    def get_post(self, num: int) -> Optional[Post]:
        for p in self.posts:
            if p.num == num:
                return p
        return None

    def add_post(self, post: Post) -> Post:
        # num must be set by caller to global unique value
        self.posts.append(post)
        self.postcount = len(self.posts)
        return post
