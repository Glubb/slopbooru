"""
Simple PIL-based captcha generator for Kareha boards.
Uses difficulty to control noise/distortion.
"""

import base64
import random
import string
import time
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont, ImageFilter

# In-memory store: token -> (answer, expiry_ts)
_captcha_store: dict[str, tuple[str, float]] = {}


def _cleanup_store() -> None:
    """Remove expired entries."""
    now = time.time()
    expired = [k for k, (_, exp) in _captcha_store.items() if exp < now]
    for k in expired:
        _captcha_store.pop(k, None)


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
    # Last resort
    try:
        return ImageFont.load_default().font_variant(size=size)
    except Exception:
        return ImageFont.load_default()


def generate_captcha_image(text: str, width: int = 140, height: int = 32, difficulty: float = 0.6) -> bytes:
    """Generate a PNG captcha image for the given text."""
    img = Image.new("RGB", (width, height), color=(250, 250, 250))
    draw = ImageDraw.Draw(img)
    font = _get_font(22)

    # Draw characters with jitter
    x = random.randint(4, 8)
    for char in text:
        y = random.randint(2, max(2, height - 24))
        # Slight color variation
        color = (
            random.randint(20, 80),
            random.randint(10, 60),
            random.randint(30, 90),
        )
        draw.text((x, y), char, font=font, fill=color)
        x += random.randint(16, 20) + int(random.gauss(0, difficulty * 3))

    # Add noise lines / dots based on difficulty
    num_lines = int(3 + difficulty * 6)
    for _ in range(num_lines):
        x1, y1 = random.randint(0, width), random.randint(0, height)
        x2, y2 = x1 + random.randint(-15, 15), y1 + random.randint(-10, 10)
        draw.line([(x1, y1), (x2, y2)], fill=(180, 180, 180), width=1)

    num_dots = int(20 * difficulty)
    for _ in range(num_dots):
        x, y = random.randint(0, width), random.randint(0, height)
        draw.point((x, y), fill=(150, 150, 150))

    # Mild blur for higher difficulty
    if difficulty > 0.5:
        img = img.filter(ImageFilter.GaussianBlur(radius=0.6))

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def create_captcha(difficulty: float = 0.6, length: int = 5) -> tuple[str, str]:
    """
    Generate a new captcha.
    Returns (token, image_b64) where image_b64 is the base64 part for data: URL.
    The answer is stored server-side.
    """
    _cleanup_store()
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no confusing 0O1I
    answer = "".join(random.choice(chars) for _ in range(length))

    img_bytes = generate_captcha_image(answer, difficulty=difficulty)
    img_b64 = base64.b64encode(img_bytes).decode("ascii")

    token = "".join(random.choices(string.ascii_letters + string.digits, k=16))
    _captcha_store[token] = (answer, time.time() + 180)  # 3 minutes (configurable via CAPTCHA_EXPIRY_SECONDS in future)
    return token, img_b64


def validate_captcha(token: str, answer: str) -> bool:
    """Return True if the answer matches the stored one for the token (consumes the token)."""
    _cleanup_store()
    if not token or token not in _captcha_store:
        return False
    correct, _ = _captcha_store.pop(token, (None, 0))
    if correct is None:
        return False
    return answer.upper().strip() == correct.upper()
