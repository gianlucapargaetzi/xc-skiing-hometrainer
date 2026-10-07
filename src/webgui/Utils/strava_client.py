# Utils/strava_client.py – Anmeldung bei Strava (OAuth) und Upload von Trainingsdateien
#
# Ablauf: authorize_url() -> Nutzer erlaubt den Zugriff bei Strava -> Strava leitet mit ?code=… zurück
# -> exchange_code() speichert die Tokens. Danach erneuert valid_access_token() den Zugang selbst.
# Jedes Strava-Konto hat eine eigene Token-Datei (strava_tokens/<Athleten-Nummer>.json); das Profil merkt
# sich die Nummer seines Kontos (strava.athlete_id). So landet ein Training nie im falschen Konto.
# Zugangsdaten (Client ID/Secret) kommen aus .env; beides ist nicht in Git.

import json
import os
import time
import urllib.parse
from pathlib import Path
from typing import Optional

import requests

from Utils.credentials import PROJECT_DIR, get_credential

TOKENS_DIR = PROJECT_DIR / "strava_tokens"
LEGACY_TOKENS_FILE = PROJECT_DIR / "strava_tokens.json"   # frühere, gemeinsame Token-Datei
API = "https://www.strava.com/api/v3"
OAUTH_AUTHORIZE = "https://www.strava.com/oauth/authorize"
OAUTH_TOKEN = "https://www.strava.com/oauth/token"
SCOPE = "read,activity:write"
TIMEOUT_S = 30


class StravaError(Exception):
    pass


def _client():
    cid, secret = get_credential("STRAVA_CLIENT_ID"), get_credential("STRAVA_CLIENT_SECRET")
    if not cid or not secret:
        raise StravaError("STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET fehlen in der .env-Datei.")
    return cid, secret


def authorize_url(redirect_uri: str) -> str:
    cid, _ = _client()
    return OAUTH_AUTHORIZE + "?" + urllib.parse.urlencode({
        "client_id": cid, "response_type": "code", "redirect_uri": redirect_uri,
        "approval_prompt": "auto", "scope": SCOPE,
    })


def tokens_path(athlete_id) -> Path:
    return TOKENS_DIR / f"{int(athlete_id)}.json"


def _save(tokens: dict):
    athlete_id = (tokens.get("athlete") or {}).get("id")
    if not athlete_id:
        raise StravaError("Strava hat kein Konto zurückgemeldet.")
    TOKENS_DIR.mkdir(mode=0o700, exist_ok=True)
    path = tokens_path(athlete_id)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(tokens), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def load_tokens(athlete_id) -> Optional[dict]:
    if not athlete_id:
        return None
    try:
        return json.loads(tokens_path(athlete_id).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, TypeError):
        return None


def exchange_code(code: str, granted_scope: str = "") -> dict:
    """Code aus der Strava-Rückleitung gegen Tokens tauschen und speichern."""
    if "activity:write" not in (granted_scope or "activity:write"):
        raise StravaError("Bei Strava wurde das Hochladen von Aktivitäten nicht erlaubt – bitte nochmals verbinden "
                          "und «Aktivitäten hochladen» angehakt lassen.")
    cid, secret = _client()
    r = requests.post(OAUTH_TOKEN, data={"client_id": cid, "client_secret": secret, "code": code.strip(),
                                         "grant_type": "authorization_code"}, timeout=TIMEOUT_S)
    if r.status_code != 200:
        raise StravaError(f"Anmeldung bei Strava fehlgeschlagen: {r.text[:200]}")
    tokens = r.json()
    tokens["scope"] = granted_scope or SCOPE
    _save(tokens)
    return tokens


def valid_access_token(athlete_id) -> str:
    tokens = load_tokens(athlete_id)
    if not tokens or "refresh_token" not in tokens:
        raise StravaError("Dieses Profil ist nicht mit Strava verbunden.")
    if time.time() < tokens.get("expires_at", 0) - 120:
        return tokens["access_token"]
    cid, secret = _client()
    r = requests.post(OAUTH_TOKEN, data={"client_id": cid, "client_secret": secret, "grant_type": "refresh_token",
                                         "refresh_token": tokens["refresh_token"]}, timeout=TIMEOUT_S)
    if r.status_code != 200:
        raise StravaError("Strava-Zugang abgelaufen oder widerrufen – bitte im Profil neu verbinden.")
    new = r.json()
    tokens.update({k: new[k] for k in ("access_token", "refresh_token", "expires_at", "expires_in") if k in new})
    _save(tokens)
    return tokens["access_token"]


def status(athlete_id) -> dict:
    tokens = load_tokens(athlete_id)
    athlete = (tokens or {}).get("athlete") or {}
    connected = bool(tokens and tokens.get("refresh_token"))
    if connected:
        try:
            valid_access_token(athlete_id)  # prüft bei Bedarf bei Strava, ob der Zugang noch gilt
        except StravaError:
            connected = False
    return {"connected": connected,
            "athlete": f"{athlete.get('firstname', '')} {athlete.get('lastname', '')}".strip() if connected else "",
            "can_upload": connected and "activity:write" in (tokens or {}).get("scope", SCOPE)}


def upload_activity(path, name: str, athlete_id, description: str = "", sport_type: str = "NordicSki",
                    trainer: bool = False, external_id: Optional[str] = None, wait_s: float = 60.0) -> dict:
    """Datei hochladen und warten, bis Strava sie verarbeitet hat.
    Rückgabe: {"activity_id": …, "url": …} oder {"duplicate": True, "url": …}."""
    token = valid_access_token(athlete_id)
    path = Path(path)
    data_type = {".fit": "fit", ".tcx": "tcx", ".gpx": "gpx"}[path.suffix.lower()]
    with open(path, "rb") as f:
        r = requests.post(f"{API}/uploads", headers={"Authorization": f"Bearer {token}"},
                          files={"file": (path.name, f)},
                          data={"data_type": data_type, "name": name, "description": description,
                                "sport_type": sport_type, "trainer": "1" if trainer else "0",
                                "external_id": external_id or path.stem},
                          timeout=TIMEOUT_S)
    if r.status_code not in (200, 201):
        raise StravaError(f"Upload abgelehnt: {r.text[:200]}")
    upload = r.json()
    deadline = time.time() + wait_s
    while not upload.get("activity_id") and not upload.get("error") and time.time() < deadline:
        time.sleep(2)
        r = requests.get(f"{API}/uploads/{upload['id']}", headers={"Authorization": f"Bearer {token}"},
                         timeout=TIMEOUT_S)
        upload = r.json()
    if upload.get("error"):
        err = str(upload["error"])
        if "duplicate" in err.lower():
            # "… duplicate of <a href='/activities/123'>…" -> Link auf die bestehende Aktivität
            import re
            m = re.search(r"/activities/(\d+)", err)
            return {"duplicate": True, "url": f"https://www.strava.com/activities/{m.group(1)}" if m else None}
        raise StravaError(f"Strava konnte die Datei nicht verarbeiten: {err[:200]}")
    if not upload.get("activity_id"):
        return {"pending": True, "url": None}
    return {"activity_id": upload["activity_id"], "url": f"https://www.strava.com/activities/{upload['activity_id']}"}


def migrate_legacy_tokens() -> Optional[int]:
    """Frühere gemeinsame Datei strava_tokens.json in strava_tokens/<id>.json überführen. Gibt die id zurück."""
    if not LEGACY_TOKENS_FILE.exists():
        return None
    tokens = json.loads(LEGACY_TOKENS_FILE.read_text(encoding="utf-8"))
    athlete_id = (tokens.get("athlete") or {}).get("id")
    if not athlete_id:
        return None
    _save(tokens)
    LEGACY_TOKENS_FILE.unlink()
    return int(athlete_id)
