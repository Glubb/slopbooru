"""
Spam filtering engine (compatible with the classic Kareha spam.txt format).

Supports:
- Plain strings (exact substring match)
- /regex/ patterns
- /regex/imsx style flags
- #-style comments and blank lines

The engine is intentionally simple and fast, matching the original spirit.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List, Pattern


def _compile_pattern(line: str) -> Pattern | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    # /regex/flags form
    m = re.match(r"^/(.*)/([a-zA-Z]*)$", line)
    if m:
        pat, flags = m.groups()
        flag_map = {"i": re.I, "m": re.M, "s": re.S, "x": re.X}
        f = 0
        for c in flags.lower():
            f |= flag_map.get(c, 0)
        try:
            return re.compile(pat, f)
        except re.error:
            return None

    # Bare /regex/
    m = re.match(r"^/(.*)/$", line)
    if m:
        try:
            return re.compile(m.group(1))
        except re.error:
            return None

    # Plain string -> literal substring match (case-insensitive for friendliness)
    escaped = re.escape(line)
    return re.compile(escaped, re.I)


def compile_spam_checker(spam_files: Iterable[str | Path]) -> callable:
    """
    Returns a function(text) -> bool that returns True if the text is considered spam.
    """
    patterns: List[Pattern] = []

    for f in spam_files:
        path = Path(f)
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            p = _compile_pattern(raw)
            if p:
                patterns.append(p)

    def is_spam(text: str) -> bool:
        if not text:
            return False
        for pat in patterns:
            if pat.search(text):
                return True
        return False

    return is_spam


def spam_engine(query_params: dict, spam_files: Iterable[str | Path], trap_fields: Iterable[str] = ()) -> bool:
    """
    High-level check used by the posting path.

    - If any trap field is non-empty → spam.
    - Otherwise run the compiled patterns over the submitted fields.
    """
    # Honeypot / trap fields
    for field in trap_fields:
        if query_params.get(field):
            return True

    checker = compile_spam_checker(spam_files)

    # Concatenate all submitted text fields
    full_text = "\n".join(str(v) for v in query_params.values() if isinstance(v, (str, bytes)))
    return checker(full_text)
