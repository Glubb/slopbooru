"""
Wakabamark and alternative markup processors.

This is a direct, readable Python port of the logic in wakautils.pl:
  do_wakabamark, do_spans, simple_format, html_format, etc.

The goal is high behavioral fidelity for existing posts while being
maintainable and UTF-8 clean.
"""
from __future__ import annotations

import re
from html import escape as html_escape
from typing import Callable, Iterable

import nh3

from .utils import REPLY_RANGE_RE, url_regexp

# Cross-board quote: >>>/boardname/1234 or >>>boardname/1234
CROSS_BOARD_QUOTE_RE = re.compile(
    r'(?<![\x80-\x9f\xe0-\xfc])(?:&gt;&gt;&gt;|>>>)'
    r'\s*/?\s*([a-zA-Z0-9_-]+)\s*/\s*(\d+)',
    re.I
)

__all__ = [
    "format_comment",
    "do_wakabamark",
    "do_spans",
    "simple_format",
    "html_format",
    "raw_html_format",
    "aa_format",
    "wakabamark_format",
    "sanitize_html",
]

# ---------------------------------------------------------------------------
# Public dispatcher (matches original format_comment)
# ---------------------------------------------------------------------------

def format_comment(comment: str, markup: str, thread: str, allowed_html: dict | None = None) -> str:
    """Dispatch to the correct formatter and apply final fixes (FUDGE_BLOCKQUOTES etc.)."""
    markup = markup or "waka"

    if markup == "none":
        out = simple_format(comment, thread)
    elif markup == "html":
        out = html_format(comment, thread, allowed_html)
    elif markup == "raw":
        out = raw_html_format(comment, thread, allowed_html)
    elif markup == "aa":
        out = aa_format(comment, thread)
    else:
        out = wakabamark_format(comment, thread)

    # Original fudge for old stylesheets
    # (we can make this conditional via config later)
    out = out.replace("<blockquote>", '<blockquote class="unkfunc">')
    return out


# ---------------------------------------------------------------------------
# Wakabamark (the interesting one)
# ---------------------------------------------------------------------------

def wakabamark_format(text: str, thread: str) -> str:
    text = _clean_and_decode(text)
    # Cross-board quotes first (they produce <a> that should survive processing)
    text = CROSS_BOARD_QUOTE_RE.sub(
        lambda m: f'<a href="/{m.group(1)}/{m.group(2)}/" class="quotelink" rel="nofollow">&gt;&gt;&gt;/{m.group(1)}/{m.group(2)}</a>',
        text
    )
    # Hide >> references (both raw and entity form) so they survive the quote parser
    text = re.sub(r"(?:&gt;&gt;|>>)(" + REPLY_RANGE_RE.pattern + ")", "&gtgt;\\1", text, flags=re.I)

    def handler(line: str) -> str:
        # Restore >> links after spans are processed
        return re.sub(
            r"&gtgt;(" + REPLY_RANGE_RE.pattern + ")",
            rf'<a href="/{thread}/\1" class="quotelink" rel="nofollow">&gt;&gt;\1</a>',
            line,
            flags=re.I,
        )

    result = do_wakabamark(text, handler)
    # Restore any that were hidden inside code
    result = result.replace("&gtgt;", "&gt;&gt;")
    return result


def do_wakabamark(text: str, handler: Callable[[str], str] | None = None, simplify: bool = False) -> str:
    """
    Line-oriented Wakabamark parser (lists, code, quotes, paragraphs).
    Recursive for nested list items.
    """
    lines = text.splitlines()
    res: list[str] = []
    i = 0
    n = len(lines)

    def peek() -> str | None:
        return lines[i] if i < n else None

    def take() -> str | None:
        nonlocal i
        if i < n:
            line = lines[i]
            i += 1
            return line
        return None

    while i < n:
        line = peek()
        if line is None:
            break
        if not line.strip():
            take()
            continue

        # Ordered / unordered lists
        if re.match(r"^(1\.|[\*\+\-]) ", line):
            tag = "ol" if line.startswith("1.") else "ul"
            re_item = re.compile(r"^[0-9]+\." if tag == "ol" else r"^[\*\+\-]")

            html_items: list[str] = []
            while (cur := peek()) and re_item.match(cur):
                m = re_item.match(cur)
                prefix_len = len(m.group(0)) + 1 if m else 2
                item_lines: list[str] = [cur[prefix_len:]]
                take()

                # Collect indented continuation lines
                pat = "^(?: {" + "1," + str(prefix_len) + "}|\\t)(.*)"
                while (cont := peek()) and re.match(pat, cont):
                    item_lines.append(cont[prefix_len:].strip())
                    take()
                item_text = "\n".join(item_lines) + "\n"
                html_items.append("<li>" + do_wakabamark(item_text, handler, simplify=True) + "</li>")

            res.append(f"<{tag}>" + "".join(html_items) + f"</{tag}>")
            continue

        # Code blocks (4 spaces or tab)
        if line.startswith("    ") or line.startswith("\t"):
            code: list[str] = []
            while (cur := peek()) and (cur.startswith("    ") or cur.startswith("\t")):
                code.append(cur[4:] if cur.startswith("    ") else cur[1:])
                take()
            res.append("<pre><code>" + "<br />".join(code) + "</code></pre>")
            continue

        # Blockquote (lines starting with >)
        if line.startswith("&gt;") or line.startswith(">"):
            quote: list[str] = []
            while (cur := peek()) and (cur.startswith("&gt;") or cur.startswith(">")):
                quote.append(cur)
                take()
            q = do_spans(handler, *quote)
            res.append("<blockquote>" + q + "</blockquote>")
            continue

        # Normal paragraph
        para: list[str] = []
        while (cur := peek()) and not (
            cur.strip() == ""
            or re.match(r"^(1\.|[\*\+\-] |&gt;|    |\t)", cur)
        ):
            para.append(take() or "")
        content = do_spans(handler, *para)
        if simplify and i >= n:
            res.append(content)
        else:
            res.append("<p>" + content + "</p>")

    return "".join(res)


def do_spans(handler: Callable[[str], str] | None, *lines: str) -> str:
    """Inline formatting: `code`, URLs, **bold**, *em*, ^H del, plus optional handler."""
    url_re = url_regexp()
    out_lines: list[str] = []

    for line in lines:
        hidden: list[str] = []

        # Hide inline code
        def _hide_code(m):
            hidden.append("<code>" + html_escape(m.group(2)) + "</code>")
            return f"<!--{len(hidden)-1}-->"

        line = re.sub(r"(?<![\x80-\x9f\xe0-\xfc])(`+)([^<>]+?)(?<![\x80-\x9f\xe0-\xfc])\1", _hide_code, line)

        # Auto-link URLs
        def _hide_url(m):
            url = m.group(1)
            hidden.append(f'<a href="{html_escape(url)}" rel="nofollow">{html_escape(url)}</a>')
            return f"<!--{len(hidden)-1}-->{m.group(2) or ''}"

        line = url_re.sub(_hide_url, line)

        # **bold** / __bold__
        line = re.sub(
            r"(?<![0-9a-zA-Z\*_\x80-\x9f\xe0-\xfc])(\*\*|__)(?![<>\s\*_])([^<>]+?)(?<![<>\s\*_\x80-\x9f\xe0-\xfc])\1(?![0-9a-zA-Z\*_])",
            r"<strong>\2</strong>",
            line,
        )

        # *em* / _em_
        line = re.sub(
            r"(?<![0-9a-zA-Z\*_\x80-\x9f\xe0-\xfc])(\*|_)(?![<>\s\*_])([^<>]+?)(?<![<>\s\*_\x80-\x9f\xe0-\xfc])\1(?![0-9a-zA-Z\*_])",
            r"<em>\2</em>",
            line,
        )

        # ^H overstrike (simplified – full recursive regex is nasty in Python)
        # For most posts a simple non-recursive version is fine
        line = re.sub(r"(.)\^H", r"<del>\1</del>", line)

        if handler:
            line = handler(line)

        # Unhide
        def _unhide(m):
            idx = int(m.group(1))
            return hidden[idx] if 0 <= idx < len(hidden) else m.group(0)

        line = re.sub(r"<!--(\d+)-->", _unhide, line)
        out_lines.append(line)

    return "<br />".join(out_lines)


# ---------------------------------------------------------------------------
# Other formatters
# ---------------------------------------------------------------------------

def simple_format(text: str, thread: str) -> str:
    text = _clean_and_decode(text)
    # Cross-board quotes first (root-absolute to other boards)
    text = CROSS_BOARD_QUOTE_RE.sub(
        lambda m: f'<a href="/{m.group(1)}/{m.group(2)}/" class="quotelink" rel="nofollow">&gt;&gt;&gt;/{m.group(1)}/{m.group(2)}</a>',
        text
    )
    # >> references (accept both raw and entity form)
    text = re.sub(
        r"(?:&gt;&gt;|>>)(" + REPLY_RANGE_RE.pattern + r")",
        rf'<a href="/{thread}/\1" class="quotelink" rel="nofollow">&gt;&gt;\1</a>',
        text,
        flags=re.I | re.M,
    )
    # URLs
    text = url_regexp().sub(r'<a href="\1" rel="nofollow">\1</a>\2', text)
    return "<br />".join(text.splitlines())


def aa_format(text: str, thread: str) -> str:
    return '<div class="aa">' + simple_format(text, thread) + "</div>"


def html_format(text: str, thread: str, allowed: dict | None = None) -> str:
    text = _clean_and_decode(text)
    text = sanitize_html(text, allowed or {})
    # Cross-board quotes (after sanitize so the <a> survives if allowed, or is added post)
    text = CROSS_BOARD_QUOTE_RE.sub(
        lambda m: f'<a href="/{m.group(1)}/{m.group(2)}/" class="quotelink" rel="nofollow">&gt;&gt;&gt;/{m.group(1)}/{m.group(2)}</a>',
        text
    )
    # Still allow >> links even in html mode
    text = re.sub(
        r"&gt;&gt;(" + REPLY_RANGE_RE.pattern + r")",
        rf'<a href="/{thread}/\1" class="quotelink" rel="nofollow">&gt;&gt;\1</a>',
        text,
        flags=re.I | re.M,
    )
    text = re.sub(r"\n", "<br />", text)
    return text


def raw_html_format(text: str, thread: str, allowed: dict | None = None) -> str:
    text = _clean_and_decode(text)
    text = sanitize_html(text, allowed or {})
    # Cross-board quotes
    text = CROSS_BOARD_QUOTE_RE.sub(
        lambda m: f'<a href="/{m.group(1)}/{m.group(2)}/" class="quotelink" rel="nofollow">&gt;&gt;&gt;/{m.group(1)}/{m.group(2)}</a>',
        text
    )
    # collapse whitespace like original
    text = re.sub(r"\s+", " ", text)
    return text


# ---------------------------------------------------------------------------
# Sanitizer (subset of original sanitize_html)
# ---------------------------------------------------------------------------

def sanitize_html(html: str, allowed: dict) -> str:
    """
    Sanitize user-provided HTML using nh3 (fast, secure Rust-based sanitizer).
    Falls back to full escaping if no allowlist provided.
    The `allowed` dict format: {tag: {"args": (attr1, ...), "forced": {...}, "empty": bool}}
    We map this to nh3's tags + attributes for a clean, legible allowlist.
    """
    if not allowed:
        return html_escape(html)

    # Build nh3-compatible allowlist from our ALLOWED_HTML config for legibility and ease.
    tags = set(allowed.keys())
    attributes = {}
    for tag, spec in allowed.items():
        attrs = spec.get("args", ()) or ()
        if attrs:
            attributes[tag] = set(attrs)

    # nh3.clean is strict by default; we strip unknown tags/attrs, remove dangerous stuff (scripts, etc.).
    # link rel="nofollow" etc. can be added via link_rel if desired.
    cleaned = nh3.clean(
        html,
        tags=tags,
        attributes=attributes,
        strip_comments=True,
        link_rel=None,  # we handle rel in markup if needed
    )
    return cleaned


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_and_decode(text: str) -> str:
    """Mirror original clean_string + decode_string behavior (UTF-8 focused)."""
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    # In original there was Shift-JIS decode magic; we stay UTF-8
    return text
