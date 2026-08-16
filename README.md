# Kareha (Python port)

A pragmatic Python 3 rewrite of the classic Kareha image/message board software (originally Perl).

**This is vibecoded.** Built by prompting an AI and iterating until it worked. Treat it like a hobby port, not a sacred text.

## Current Status

**The project is in a usable state.** You can create boards, post threads and replies (with images in image mode), view them, and do basic deletion. Production hardening includes POST-only deletion/admin actions, enforced IP bans, multi-worker captcha/rate limits, and Caddy-ready reverse proxy support.

## Quick Start

```bash
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
- Deletion (POST-only, password hashed with board SECRET)
- Admin panel (cookie auth, POST-only mod actions, CSRF)
- IP bans (`banned_ips.txt`, enforced at post time)
- Captcha + per-IP rate limits (file-backed, works with gunicorn `--workers N`)

## Configuration

See `config.py.example` and `src/kareha/config_defaults.py` for all options.

Most important:
- `ADMIN_PASS` and `SECRET` (required)
- mode via CLI `--mode imageboard|textboard|blog` (or make_app mode=)
- `TRUSTED_PROXY_COUNT = 1` when behind Caddy/nginx (default)

## Running in Production

### Gunicorn (single board)

```bash
gunicorn -w 4 --bind 127.0.0.1:8000 \
  "kareha.wsgi:make_app(board_dir='/path/to/board', mode='imageboard')"
```

Use multiple workers safely — captcha and rate limits share state via `.runtime/` under the board directory.

For a board mounted at a subpath (e.g. `/myboard/`):

```bash
gunicorn -w 4 --bind 127.0.0.1:8001 \
  "kareha.wsgi:make_app(board_dir='/path/to/myboard', mode='imageboard', base_path='/myboard')"
```

### Caddy reverse proxy

Caddy should pass the real client IP and HTTPS scheme. The app uses `ProxyFix` with `TRUSTED_PROXY_COUNT=1` (default).

See `deploy/caddy/Caddyfile.example` for a full template. Minimal example for one board at `/myboard/` proxied to port 8001:

```caddy
your.domain {
    header {
        X-Content-Type-Options nosniff
        Referrer-Policy same-origin
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
    }

    # Static assets — serve directly so Content-Type is correct (nosniff-safe)
    handle_path /myboard/css/* {
        root * /path/to/myboard/css
        file_server
    }
    handle_path /myboard/src/* {
        root * /path/to/myboard/src
        file_server
    }
    handle_path /myboard/thumb/* {
        root * /path/to/myboard/thumb
        file_server
    }

    # Dynamic pages + POST handlers
    handle_path /myboard/* {
        reverse_proxy 127.0.0.1:8001 {
            header_up X-Forwarded-For {remote_host}
            header_up X-Forwarded-Proto {scheme}
        }
    }
}
```

**Important:** `base_path='/myboard'` in `make_app()` must match the Caddy URL prefix. Caddy's `handle_path` strips the prefix before proxying, so the app sees `/`, `/admin`, `/123/`, etc.

Optional extra hardening in Caddy (rate-limit POST spam at the edge):

```caddy
@posting {
    path /myboard/*
    method POST
}
rate_limit @posting 10r/m
```

### systemd

Copy and edit `deploy/systemd/slopbooru-board.service.example`. Set `board_dir`, `mode`, `base_path`, and port per board.

## Security notes

- User deletion and all admin moderation actions use **POST** (passwords/tokens never in URLs or access logs).
- Admin login uses HttpOnly cookies; passwords are not accepted via query strings.
- Uploaded files and board data (`res/`, `thumb/`, `config.py`, `.runtime/`) should never be committed — see `.gitignore`.
- Set strong `ADMIN_PASS` and a long random `SECRET` before going live.

## Repository layout

This repo contains both the **Python package** and **example board scaffolding**. Keep them separate in your head:

| Path | Role |
|------|------|
| `src/kareha/` | Canonical application code (WSGI, posting, admin, templates) |
| `src/kareha/static/` | Bundled CSS themes, `kareha.js`, and file-type icons (source of truth) |
| `src/kareha/templates/` | Jinja templates served for every board (not copied into board dirs) |
| `config.py.example` | Template for a board's `config.py` (secrets — never commit the real file) |
| `spam.txt`, `reports.json.example` | Copied into new boards by `kareha init` |
| `res/`, `thumb/` | Board runtime (thread JSON, thumbnails) — gitignored except `.gitkeep` |
| `src/` (repo root) | **Upload directory** when the repo root is used as a board (`IMG_DIR`); not the Python package |
| `css/`, `kareha.js`, `include/` | Board-local copies seeded from the package on `kareha init` / first `serve` — gitignored |

**Using this repo as a dev board:** run `kareha serve .` from the repo root after copying `config.py.example` → `config.py`. Runtime data and seeded static files stay local and out of git.

**Production boards:** use `kareha init /path/to/board` (or your own directory layout) and point gunicorn at that path — see [Running in Production](#running-in-production).

## Notes

- Storage uses per-thread JSON files (easy to inspect/backup).
- No legacy Perl encrypted logs are read.
- This is a from-scratch pragmatic port, not a line-by-line translation.
- Vibecoded: expect sharp edges, file-based storage, and the occasional "why is it like that."

Original Kareha by the Wakaba/Kareha authors. This port aims to keep the spirit alive in modern Python.