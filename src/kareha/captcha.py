"""
Simple PIL-based captcha generator for Kareha boards.
Uses difficulty to control noise/distortion. Answers stored in the board's
file-backed runtime store so validation works across gunicorn workers.
"""

import base64
import random
import string
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from .runtime_store import captcha_consume, captcha_put


def _get_font(size: int = 22):
    """Try to load a bold truetype font, fall back to default."""
    candidates = [
        "DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",  # mac fallback
    ]
    for cand in candidates:
        try:
            return ImageFont.truetype(cand, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default().font_variant(size=size)
    except Exception:
        return ImageFont.load_default()


def generate_captcha_image(text: str, width: int = 140, height: int = 32, difficulty: float = 0.6) -> bytes:
    """Generate a PNG captcha image for the given text."""
    img = Image.new("RGB", (width, height), color=(250, 250, 250))
    draw = ImageDraw.Draw(img)
    font = _get_font(22)

    x = random.randint(4, 8)
    for char in text:
        y = random.randint(2, max(2, height - 24))
        color = (
            random.randint(20, 80),
            random.randint(10, 60),
            random.randint(30, 90),
        )
        draw.text((x, y), char, font=font, fill=color)
        x += random.randint(16, 20) + int(random.gauss(0, difficulty * 3))

    num_lines = int(3 + difficulty * 6)
    for _ in range(num_lines):
        x1, y1 = random.randint(0, width), random.randint(0, height)
        x2, y2 = x1 + random.randint(-15, 15), y1 + random.randint(-10, 10)
        draw.line([(x1, y1), (x2, y2)], fill=(180, 180, 180), width=1)

    num_dots = int(20 * difficulty)
    for _ in range(num_dots):
        x, y = random.randint(0, width), random.randint(0, height)
        draw.point((x, y), fill=(150, 150, 150))

    if difficulty > 0.5:
        img = img.filter(ImageFilter.GaussianBlur(radius=0.6))

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def create_captcha(
    difficulty: float = 0.6,
    length: int = 5,
    *,
    board_dir: Path | None = None,
    cfg: Any = None,
) -> tuple[str, str]:
    """
    Generate a new captcha.
    Returns (token, image_b64) for data: URL embedding.
    """
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    answer = "".join(random.choice(chars) for _ in range(length))
    img_bytes = generate_captcha_image(answer, difficulty=difficulty)
    img_b64 = base64.b64encode(img_bytes).decode("ascii")
    token = "".join(random.choices(string.ascii_letters + string.digits, k=16))

    expiry = float(getattr(cfg, "CAPTCHA_EXPIRY_SECONDS", 180) if cfg else 180)
    if board_dir is not None and cfg is not None:
        captcha_put(board_dir, cfg, token, answer, expiry)

    return token, img_b64


def validate_captcha(
    token: str,
    answer: str,
    *,
    board_dir: Path | None = None,
    cfg: Any = None,
) -> bool:
    """Return True if answer matches (consumes the token)."""
    if board_dir is not None and cfg is not None:
        return captcha_consume(board_dir, cfg, token, answer)
    return False