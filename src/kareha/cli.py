"""
kareha command-line tool (entry point defined in pyproject.toml).

Subcommands:
    kareha init [dir]   - create a new board directory with example config + assets
    kareha serve [dir]  - run the development server for a board
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


def cmd_init(args: argparse.Namespace) -> int:
    target = Path(args.directory).resolve()
    target.mkdir(parents=True, exist_ok=True)

    src_root = Path(__file__).parent.parent.parent  # kareha_py/
    py_src = src_root / "src" / "kareha"

    # Directories a board needs
    for d in ("res", "src", "thumb", "include", "css"):
        (target / d).mkdir(exist_ok=True)

    # Example config (user should copy to config.py themselves)
    cfg_example = src_root / "config.py.example"
    if cfg_example.exists():
        shutil.copy(cfg_example, target / "config.py.example")

    # spam.txt
    spam = src_root / "spam.txt"
    if spam.exists():
        shutil.copy(spam, target / "spam.txt")

    # Empty reports store template (runtime reports.json is gitignored)
    reports_example = src_root / "reports.json.example"
    if reports_example.exists():
        shutil.copy(reports_example, target / "reports.json.example")

    # CSS (both modes)
    css_src = py_src / "static" / "css"
    if css_src.exists():
        for css in css_src.glob("*.css"):
            shutil.copy(css, target / "css" / css.name)

    # Icons
    icons_src = py_src / "static" / "icons"
    if icons_src.exists():
        (target / "icons").mkdir(exist_ok=True)
        for icon in icons_src.glob("*"):
            shutil.copy(icon, target / "icons" / icon.name)

    # JS
    js = py_src / "static" / "kareha.js"
    if js.exists():
        shutil.copy(js, target / "kareha.js")

    # Include examples (empty placeholders)
    for name in ("header.html", "footer.html", "rules.html"):
        (target / "include" / name).touch(exist_ok=True)

    # Copy templates for both modes
    (target / "templates").mkdir(exist_ok=True)
    for mode_name in ("image", "message"):
        pkg_templates = py_src / "templates" / mode_name
        if pkg_templates.exists():
            for tmpl in pkg_templates.glob("*.html"):
                shutil.copy(tmpl, target / "templates" / tmpl.name)
    # Note: blog reuses message templates for now; no separate blog/ dir needed

    print(f"Initialized Kareha board at {target}")
    print("Copy config.py.example to config.py (set ADMIN_PASS + SECRET), then run: kareha serve", target)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .wsgi import make_app
    from werkzeug.serving import run_simple

    board_dir = Path(args.directory).resolve()
    app = make_app(board_dir, mode=args.mode)
    shown_mode = args.mode or "(from BOARD_MODE in config.py or default)"
    print(f"Serving {board_dir} (mode={shown_mode}) on http://127.0.0.1:{args.port}")
    run_simple(
        "127.0.0.1",
        args.port,
        app,
        use_reloader=args.reload,
        use_debugger=args.debug,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="kareha")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="Create a new board directory")
    p_init.add_argument("directory", nargs="?", default=".", help="Target directory")
    p_init.set_defaults(func=cmd_init)

    p_serve = sub.add_parser("serve", help="Run development server for a board")
    p_serve.add_argument("directory", nargs="?", default=".", help="Board directory")
    p_serve.add_argument(
        "--mode",
        default=None,
        choices=["imageboard", "image", "textboard", "text", "message", "blog"],
        help="Board mode override. If omitted, BOARD_MODE from the board's config.py is used (hybrid)."
    )
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--reload", action="store_true")
    p_serve.add_argument(
        "--debug",
        action="store_true",
        help="Enable Werkzeug interactive debugger (insecure; local dev only)",
    )
    p_serve.set_defaults(func=cmd_serve)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
