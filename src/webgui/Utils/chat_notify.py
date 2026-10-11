# Utils/chat_notify.py – Meldungen an den Tracking-Chat (gps-live): «Training gestartet …» / «Training beendet.»
#
# Zugangsdaten aus .env (nicht im Git): TRACKING_DEVICE_ID und TRACKING_SK (fester Secret-Link des Geräts).
# Optional: TRACKING_CHAT_URL, TRACKING_MEDIA_URL, TRACKING_FOLLOW_URL. Ohne Zugangsdaten wird nichts gesendet.
# Senden läuft im Hintergrund und darf das Training nie aufhalten; Fehler werden nur gemeldet.

import threading
import time
from typing import Optional

import requests

from Utils.credentials import get_credential

DEFAULT_CHAT_URL = "https://tracking.gps-live.ch/api/chat_send/actualPosition"
DEFAULT_MEDIA_URL = "https://tracking.gps-live.ch/api/chat_send_media/actualPosition"
DEFAULT_FOLLOW_URL = "https://tracking.gps-live.ch/s/{sk}"
TIMEOUT_S = 15
MEDIA_TIMEOUT_S = 45
MEDIA_MAX_BYTES = 15 * 1024 * 1024      # der Server lehnt grössere Bilder mit 413 ab
MEDIA_RETRY_WAIT_S = 3.0


def _config() -> Optional[dict]:
    device_id, sk = get_credential("TRACKING_DEVICE_ID"), get_credential("TRACKING_SK")
    if not device_id or not sk:
        return None
    return {"url": get_credential("TRACKING_CHAT_URL", DEFAULT_CHAT_URL),
            "media_url": get_credential("TRACKING_MEDIA_URL", DEFAULT_MEDIA_URL), "device_id": device_id, "sk": sk,
            "follow": get_credential("TRACKING_FOLLOW_URL", DEFAULT_FOLLOW_URL).format(sk=sk)}


def configured() -> bool:
    return _config() is not None


def follow_url() -> Optional[str]:
    cfg = _config()
    return cfg["follow"] if cfg else None


def send(text: str, name: str = "x-ski") -> bool:
    """Meldung senden (blockiert bis zu TIMEOUT_S). True bei Erfolg. Der Secret-Link erscheint nie im Log."""
    cfg = _config()
    if cfg is None:
        return False
    try:
        r = requests.post(cfg["url"], params={"device_id": cfg["device_id"], "sk": cfg["sk"]},
                          json={"text": text, "name": name}, timeout=TIMEOUT_S)
    except requests.RequestException as e:
        print(f"⚠️ Tracking-Chat nicht erreichbar: {type(e).__name__}")
        return False
    if r.status_code >= 300:
        print(f"⚠️ Tracking-Chat hat die Meldung abgelehnt: HTTP {r.status_code} {r.text[:120]}")
        return False
    print(f"💬 Tracking-Chat: «{text.splitlines()[0]}» gesendet")
    return True


def send_image(path, name: str = "x-ski", text: str = "") -> bool:
    """Bild senden (multipart/form-data: name, file und optional text als Bildunterschrift). True bei Erfolg."""
    from pathlib import Path
    cfg = _config()
    path = Path(path)
    if cfg is None or not path.is_file():
        return False
    if path.stat().st_size > MEDIA_MAX_BYTES:
        print(f"⚠️ Tracking-Chat: Bild zu gross ({path.stat().st_size // 1024} kB, erlaubt sind 15 MB)")
        return False
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(path.suffix.lower(), "image/png")
    r = None
    for attempt in (1, 2):      # ein zweiter Versuch: der Server lieferte nach einem Neustart vereinzelt 502
        try:
            with open(path, "rb") as f:
                r = requests.post(cfg["media_url"], params={"device_id": cfg["device_id"], "sk": cfg["sk"]},
                                  data={"name": name, **({"text": text} if text else {})},
                                  files={"file": (path.name, f, mime)}, timeout=MEDIA_TIMEOUT_S)
        except requests.RequestException as e:
            print(f"⚠️ Tracking-Chat nicht erreichbar (Bild): {type(e).__name__}")
            return False
        if r.status_code < 500 or attempt == 2:
            break
        time.sleep(MEDIA_RETRY_WAIT_S)
    if r.status_code >= 300:
        print(f"⚠️ Tracking-Chat hat das Bild abgelehnt: HTTP {r.status_code} {r.text[:120]}")
        return False
    print(f"💬 Tracking-Chat: Bild «{path.name}» gesendet")
    return True


def send_async(text: str, name: str = "x-ski") -> threading.Thread:
    t = threading.Thread(target=send, args=(text, name), name="chat-notify", daemon=True)
    t.start()
    return t


def start_text() -> str:
    return f"Training gestartet. Folge mir unter:\n{follow_url()}"


END_TEXT = "Training beendet."
