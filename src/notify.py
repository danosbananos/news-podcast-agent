"""Push-notificaties via ntfy.sh voor server-events."""

import logging
import os
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")
NTFY_URL = os.getenv("NTFY_URL", "https://ntfy.sh")


def send(title: str, message: str, *, priority: str = "default", tags: str = "") -> bool:
    """Stuur een push-notificatie via ntfy.

    Args:
        title: Korte titel van de notificatie
        message: Body-tekst
        priority: "min", "low", "default", "high", "urgent"
        tags: Komma-gescheiden emoji tags (bijv. "warning,podcast")

    Returns:
        True als verzonden, False als ntfy niet geconfigureerd of mislukt.
    """
    if not NTFY_TOPIC:
        logger.debug("Ntfy niet geconfigureerd (NTFY_TOPIC niet gezet), notificatie overgeslagen")
        return False

    url = f"{NTFY_URL}/{NTFY_TOPIC}"
    headers = {
        "Title": title,
        "Priority": priority,
    }
    if tags:
        headers["Tags"] = tags

    try:
        req = Request(url, data=message.encode("utf-8"), headers=headers, method="POST")
        with urlopen(req, timeout=10) as resp:
            logger.info("Ntfy notificatie verzonden: '%s' (status %d)", title, resp.status)
            return True
    except Exception as e:
        logger.warning("Ntfy notificatie mislukt: %s", e)
        return False
