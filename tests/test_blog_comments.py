"""Blog mode BLOG_COMMENTS config normalization."""
from kareha.config import load_config
from pathlib import Path
import tempfile
import textwrap


def test_blog_comments_normalized_from_config(tmp_path):
    cfg_file = tmp_path / "config.py"
    cfg_file.write_text(textwrap.dedent("""
        ADMIN_PASS = "testpass123"
        SECRET = "x" * 32
        BOARD_MODE = "blog"
        BLOG_COMMENTS = "disabled"
    """))
    cfg = load_config(cfg_file, mode="blog")
    assert cfg["BLOG_COMMENTS"] == "disabled"


def test_blog_comments_aliases_off(tmp_path):
    cfg_file = tmp_path / "config.py"
    cfg_file.write_text(textwrap.dedent("""
        ADMIN_PASS = "testpass123"
        SECRET = "x" * 32
        BOARD_MODE = "blog"
        BLOG_COMMENTS = "off"
    """))
    cfg = load_config(cfg_file, mode="blog")
    assert cfg["BLOG_COMMENTS"] == "disabled"