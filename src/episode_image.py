"""Helpers voor episode-afbeeldingen (downloaden, vierkant maken, opslaan)."""

from __future__ import annotations

import logging
import os
import uuid
from io import BytesIO
from pathlib import Path
from urllib.request import Request, urlopen

from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                  "Version/17.0 Safari/605.1.15",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}

EPISODE_IMAGE_SIZE = int(os.getenv("EPISODE_IMAGE_SIZE", "1400"))
EPISODE_IMAGE_QUALITY = int(os.getenv("EPISODE_IMAGE_QUALITY", "88"))


def process_episode_image(image_url: str, image_dir: Path) -> Path:
    """Download image URL en sla op als vierkante JPEG in image_dir."""
    image_dir.mkdir(parents=True, exist_ok=True)

    req = Request(image_url, headers=_BROWSER_HEADERS)
    with urlopen(req, timeout=20) as resp:
        raw = resp.read()

    img = Image.open(BytesIO(raw))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    elif img.mode == "L":
        img = img.convert("RGB")

    # Apple toont episode-artwork betrouwbaarder met grote vierkante images.
    square = ImageOps.fit(
        img,
        (EPISODE_IMAGE_SIZE, EPISODE_IMAGE_SIZE),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )

    filename = f"{uuid.uuid4().hex}.jpg"
    out = image_dir / filename
    square.save(out, format="JPEG", quality=EPISODE_IMAGE_QUALITY, optimize=True)
    logger.info("Episode-image opgeslagen: %s (%dx%d)", out, EPISODE_IMAGE_SIZE, EPISODE_IMAGE_SIZE)
    return out
