"""Posting, deletion, trim, permasage, MD5 ban, and mass-action tests."""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from kareha import config as config_module
from kareha.admin_actions import process_mass_action
from kareha.config import make_config_object
from kareha.config_defaults import get_defaults_dict
from kareha.core.admin import check_admin_pass
from kareha.core.deletion import delete_post
from kareha.core.posting import PostError, post_stuff
from kareha.core.storage import allocate_post_num, list_threads, load_thread, save_thread


def _cfg(board_dir: Path, **overrides):
    d = get_defaults_dict()
    d["ADMIN_PASS"] = "test-admin-pass"
    d["SECRET"] = "test-secret-at-least-32-chars!!"
    d["ENABLE_CAPTCHA"] = False
    d["MAX_THREADS"] = 0
    d["MAX_POSTS"] = 0
    d["AUTOCLOSE_POSTS"] = 0
    d["AUTOCLOSE_DAYS"] = 0
    d["RATE_LIMIT_POSTS_PER_MIN"] = 1000
    d["DUPLICATE_WINDOW"] = 0
    d.update(overrides)
    obj = make_config_object(d)
    config_module.current_config = obj
    (board_dir / "res").mkdir(exist_ok=True)
    (board_dir / "src").mkdir(exist_ok=True)
    (board_dir / "thumb").mkdir(exist_ok=True)
    return obj


def _tiny_png(path: Path) -> Path:
    img = Image.new("RGB", (8, 8), color=(20, 40, 80))
    img.save(path, "PNG")
    return path


def test_post_thread_and_reply(tmp_path):
    _cfg(tmp_path)
    tid = post_stuff(tmp_path, comment="hello thread", name="anon")
    assert tid >= 1
    reply = post_stuff(tmp_path, thread_id=tid, comment="a reply")
    assert reply > tid
    thread = load_thread(tmp_path / "res", tid)
    assert thread is not None
    assert thread.postcount == 2
    assert thread.posts[0].comment_raw == "hello thread"
    assert thread.posts[1].comment_raw == "a reply"


def test_delete_requires_password(tmp_path):
    cfg = _cfg(tmp_path)
    tid = post_stuff(tmp_path, comment="to delete", password="hunter2")
    assert not delete_post(tmp_path, tid, tid, password="wrong", cfg=cfg, secret=cfg.SECRET)
    assert delete_post(tmp_path, tid, tid, password="hunter2", cfg=cfg, secret=cfg.SECRET)
    thread = load_thread(tmp_path / "res", tid)
    assert thread.get_post(tid).deleted
    assert "[deleted]" in thread.get_post(tid).comment_raw


def test_admin_delete_bypasses_password(tmp_path):
    cfg = _cfg(tmp_path)
    tid = post_stuff(tmp_path, comment="admin zap", password="secretpw")
    assert delete_post(tmp_path, tid, tid, password="", admin=True, cfg=cfg)
    thread = load_thread(tmp_path / "res", tid)
    assert thread.get_post(tid).deleted


def test_md5_ban_rejects_image(tmp_path):
    cfg = _cfg(tmp_path)
    png = _tiny_png(tmp_path / "pic.png")
    import hashlib
    md5 = hashlib.md5(png.read_bytes()).hexdigest()
    (tmp_path / cfg.BANNED_MD5_FILE).write_text(f"{md5}  # banned\n")
    try:
        post_stuff(tmp_path, comment="banned pic", file_path=str(png), upload_filename="pic.png")
        assert False, "expected PostError"
    except PostError as e:
        assert "banned" in str(e).lower()


def test_permasage_does_not_bump(tmp_path):
    _cfg(tmp_path)
    tid = post_stuff(tmp_path, comment="op")
    thread = load_thread(tmp_path / "res", tid)
    thread.permasage = True
    original_hit = thread.lasthit
    thread.lasthit = 1
    save_thread(thread, tmp_path / "res")
    post_stuff(tmp_path, thread_id=tid, comment="sage reply")
    thread = load_thread(tmp_path / "res", tid)
    assert thread.permasage
    assert thread.lasthit == 1
    assert thread.lastmod >= original_hit
    assert thread.postcount == 2


def test_trim_max_threads(tmp_path):
    _cfg(tmp_path, MAX_THREADS=2)
    a = post_stuff(tmp_path, comment="one")
    post_stuff(tmp_path, comment="two")
    c = post_stuff(tmp_path, comment="three")
    ids = {m["thread"] for m in list_threads(tmp_path / "res")}
    assert len(ids) == 2
    assert c in ids
    assert a not in ids or b not in ids


def test_autoclose_posts(tmp_path):
    _cfg(tmp_path, AUTOCLOSE_POSTS=2)
    tid = post_stuff(tmp_path, comment="op")
    post_stuff(tmp_path, thread_id=tid, comment="second")
    thread = load_thread(tmp_path / "res", tid)
    assert thread.closed
    try:
        post_stuff(tmp_path, thread_id=tid, comment="too late")
        assert False, "expected closed"
    except PostError as e:
        assert "closed" in str(e).lower()


def test_allocate_post_num_monotonic(tmp_path):
    _cfg(tmp_path)
    res = tmp_path / "res"
    n1 = allocate_post_num(res)
    n2 = allocate_post_num(res)
    assert n2 == n1 + 1


def test_mass_delete_does_not_revert(tmp_path):
    cfg = _cfg(tmp_path)
    tid = post_stuff(tmp_path, comment="op")
    r1 = post_stuff(tmp_path, thread_id=tid, comment="keep me")
    r2 = post_stuff(tmp_path, thread_id=tid, comment="delete me")
    ok, err = process_mass_action(tmp_path, cfg, tid, "delete_posts", [r2])
    assert ok, err
    thread = load_thread(tmp_path / "res", tid)
    assert not thread.get_post(r1).deleted
    assert thread.get_post(r2).deleted


def test_admin_pass_different_length_is_false_not_error():
    class C:
        ADMIN_PASS = "longpassword"
    assert check_admin_pass("x", C()) is False
    assert check_admin_pass("longpassword", C()) is True
    assert check_admin_pass("", C()) is False
