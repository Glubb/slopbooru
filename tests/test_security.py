"""Security-related unit tests."""
from pathlib import Path

import pytest

from kareha.core.admin import (
    ban_ip,
    check_admin_pass,
    create_admin_token,
    is_ip_banned,
    load_banned_ips,
    verify_admin_token,
)
from kareha.http_helpers import get_client_ip, safe_user_error
from kareha.markup import do_wakabamark
from kareha.core.posting import PostError
from kareha.runtime_store import captcha_consume, captcha_put, check_rate_limit


class _Cfg:
    RUNTIME_DIR = ".runtime/"
    BANNED_IP_FILE = "banned_ips.txt"
    ADMIN_BAN_FILE = ".htaccess"
    TRUSTED_PROXY_COUNT = 1
    RATE_LIMIT_POSTS_PER_MIN = 3
    RATE_LIMIT_WINDOW_SECONDS = 60
    SECRET = "test-secret"
    ADMIN_PASS = "test-admin"
    RES_DIR = "res/"


class _Req:
    def __init__(self, *, remote_addr="10.0.0.5", headers=None):
        self.remote_addr = remote_addr
        self.headers = headers or {}


def test_javascript_urls_not_auto_linked(tmp_path):
    out = do_wakabamark("click javascript:alert(1) here")
    assert 'href="javascript:' not in out


def test_safe_user_error_hides_internals():
    assert safe_user_error(RuntimeError("db connection leaked")) == (
        "Something went wrong. Please try again."
    )
    assert safe_user_error(PostError("Spam detected.")) == "Spam detected."


def test_get_client_ip_trusts_forwarded_for():
    cfg = _Cfg()
    req = _Req(
        remote_addr="127.0.0.1",
        headers={"X-Forwarded-For": "203.0.113.50, 127.0.0.1"},
    )
    assert get_client_ip(req, cfg) == "203.0.113.50"


def test_get_client_ip_without_proxy_uses_remote_addr():
    cfg = _Cfg()
    cfg.TRUSTED_PROXY_COUNT = 0
    req = _Req(remote_addr="198.51.100.9")
    assert get_client_ip(req, cfg) == "198.51.100.9"


def test_ip_ban_enforcement(tmp_path):
    cfg = _Cfg()
    ban_ip(tmp_path, "203.0.113.99", reason="test", cfg=cfg)
    assert "203.0.113.99" in load_banned_ips(tmp_path, cfg)
    assert is_ip_banned("203.0.113.99", tmp_path, cfg)


def test_admin_token_roundtrip():
    cfg = _Cfg()
    token = create_admin_token(cfg, max_age=3600)
    assert verify_admin_token(token, cfg)


def test_admin_pass_unequal_length_does_not_raise():
    cfg = _Cfg()
    assert check_admin_pass("short", cfg) is False
    assert check_admin_pass("test-admin", cfg) is True


def test_runtime_store_captcha_and_rate_limit(tmp_path):
    cfg = _Cfg()
    captcha_put(tmp_path, cfg, "tok123", "ABCDE", 120)
    assert captcha_consume(tmp_path, cfg, "tok123", "abcde")
    assert not captcha_consume(tmp_path, cfg, "tok123", "abcde")

    ip = "10.1.2.3"
    assert check_rate_limit(tmp_path, cfg, "posts", ip, max_events=2, window_seconds=60)
    assert check_rate_limit(tmp_path, cfg, "posts", ip, max_events=2, window_seconds=60)
    assert not check_rate_limit(tmp_path, cfg, "posts", ip, max_events=2, window_seconds=60)