# Kareha (Python port)

A pragmatic Python 3 rewrite of the classic Kareha image/message board software (originally Perl).

## Current Status

**The project is in a usable state.** You can create boards, post threads and replies (with images in image mode), view them, and do basic deletion.

## Quick Start

```bash
# From the kareha_py directory
pip install -e .

kareha init myboard
cd myboard

# Copy config.py.example to config.py and set at least these two:
# ADMIN_PASS = "something strong"
# SECRET = "long random string here"

kareha serve .
```

Then open http://127.0.0.1:8000

To use textboard or blog instead of imageboard, pass `--mode textboard` or `--mode blog` to `kareha serve` (aliases: text/message for textboard; image for imageboard). Blog is text-only with posting-focused UI.

## Features Implemented

- imageboard (current, with images), textboard (text only), blog (text only, post-focused flat entries) modes
- Wakabamark + other markups (waka, none, html, aa, raw)
- Tripcodes + `DISPLAY_ID` (IP-based randomized poster IDs)
- File uploads + Pillow thumbnailing
- Spam filtering (original `spam.txt` format supported)
- Basic deletion (user password or admin)
- Working posting pipeline (text + images)

## Configuration

See `config.py.example` and `src/kareha/config_defaults.py` for all options.

Most important:
- `ADMIN_PASS` and `SECRET` (required)
- mode via CLI `--mode imageboard|textboard|blog` (or make_app mode=) ; imageboard supports images+layout, others are text-only

## Running in Production

```bash
gunicorn -w 2 "kareha.wsgi:make_app(board_dir='.', mode='imageboard')"
```

## Notes

- Storage uses per-thread JSON files (easy to inspect/backup).
- No legacy Perl encrypted logs are read.
- This is a from-scratch pragmatic port, not a line-by-line translation.

Original Kareha by the Wakaba/Kareha authors. This port aims to keep the spirit alive in modern Python.
