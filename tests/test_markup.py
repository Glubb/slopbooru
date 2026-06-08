"""Tests for the Wakabamark + other markup ports.

These aim for behavioral fidelity with the original Perl implementation
on representative input (not byte-for-byte HTML, but structure and semantics).
"""
import pytest

from kareha.markup import (
    format_comment,
    do_wakabamark,
    simple_format,
    wakabamark_format,
)


class TestBasicFormatting:
    def test_bold_and_italic(self):
        out = do_wakabamark("**bold** and *italic* and __also bold__")
        assert "<strong>bold</strong>" in out
        assert "<em>italic</em>" in out

    def test_inline_code(self):
        out = do_wakabamark("Use `code` here")
        assert "<code>code</code>" in out

    def test_links_are_linked(self):
        out = do_wakabamark("See https://example.com/page")
        assert '<a href="https://example.com/page"' in out
        assert "rel=\"nofollow\"" in out

    def test_blockquote(self):
        out = do_wakabamark("> this is quoted\n> second line")
        assert "<blockquote>" in out
        assert "this is quoted" in out

    def test_code_block(self):
        out = do_wakabamark("    def foo():\n        pass")
        assert "<pre><code>" in out
        assert "def foo():" in out

    def test_unordered_list(self):
        out = do_wakabamark("* one\n* two\n  * nested")
        assert "<ul>" in out
        assert "<li>one" in out
        assert "<li>nested" in out

    def test_ordered_list(self):
        out = do_wakabamark("1. first\n2. second")
        assert "<ol>" in out
        assert "<li>first" in out


class TestWakabamarkIntegration:
    def test_wakabamark_format_adds_p_tags(self):
        out = wakabamark_format("Hello world", "123")
        assert out.startswith("<p>")

    def test_reply_links_are_created(self):
        out = wakabamark_format("See >>1 and >>5-7", "12345")
        assert 'href="/12345/1"' in out
        assert 'href="/12345/5-7"' in out
        assert "&gt;&gt;1" in out

    def test_reply_links_hidden_in_code(self):
        """ >> references inside code blocks should not become links. """
        out = wakabamark_format("    >>123 is not a link here", "1")
        # The >> should still be literal inside <code>
        assert "&gt;&gt;123" in out or ">>123" in out
        assert 'href="/1/123"' not in out


class TestOtherMarkups:
    def test_simple_format_links_replies(self):
        out = simple_format(">>42 and >>10-12", "999")
        assert 'href="/999/42"' in out
        assert 'href="/999/10-12"' in out

    def test_aa_wraps_in_div(self):
        out = format_comment("some aa art", "aa", "1")
        assert '<div class="aa">' in out

    def test_html_mode_sanitizes_but_keeps_links(self):
        out = format_comment('<script>evil</script> <b>ok</b>', "html", "1")
        assert "<script>" not in out
        assert "<b>ok</b>" in out or "&lt;b&gt;ok" in out  # depending on sanitizer strictness

    def test_format_comment_dispatch(self):
        assert "strong" in format_comment("**x**", "waka", "1")
        assert "aa" in format_comment("art", "aa", "1").lower()


class TestEdgeCases:
    def test_empty_input(self):
        assert format_comment("", "waka", "1") == ""

    def test_very_long_line_still_works(self):
        long = "x" * 2000
        out = format_comment(long, "waka", "1")
        assert "x" in out
