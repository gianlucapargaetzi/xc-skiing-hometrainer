"""
Lädt eine TCX-Datei zu Strava hoch.

Aufruf:  python Utils/strava_upload.py <datei.tcx>

CLIENT_ID / CLIENT_SECRET kommen aus der Umgebung bzw. der .env-Datei,
die Tokens aus strava_tokens.json im Projektverzeichnis (beides nicht versioniert).
"""

import json
import os
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from Utils.credentials import PROJECT_DIR, get_credential  # noqa: E402

TOKENS_FILE = PROJECT_DIR / "strava_tokens.json"
UPLOAD_NAME = "Indoor Skilanglauf – Double Poling (x-ski)"
UPLOAD_DESCRIPTION = "Hochgeladen von x-ski.ch"
# Strava erkennt die Sportart aus TCX-Dateien nur für Biking/Running/Hiking/Walking/Swimming.
# Deshalb wird sie beim Upload explizit gesetzt: Langlauf, als Indoor-Aktivität (trainer).
UPLOAD_SPORT_TYPE = "NordicSki"
UPLOAD_TRAINER = 1


def load_tokens():
    if not TOKENS_FILE.exists():
        raise FileNotFoundError(f"Tokens-Datei nicht gefunden: {TOKENS_FILE}")
    with open(TOKENS_FILE) as f:
        return json.load(f)


def save_tokens(tokens):
    with open(TOKENS_FILE, "w") as f:
        json.dump(tokens, f)
    os.chmod(TOKENS_FILE, 0o600)


def refresh_access_token(tokens):
    client_id = get_credential("STRAVA_CLIENT_ID")
    client_secret = get_credential("STRAVA_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET fehlen (Umgebungsvariable oder .env).")

    print("🔄 Access Token wird erneuert...")
    response = requests.post(
        "https://www.strava.com/api/v3/oauth/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"]
        },
        timeout=30,
    )
    if response.status_code != 200:
        raise Exception(f"Token-Refresh fehlgeschlagen: {response.text}")

    new_tokens = response.json()
    save_tokens(new_tokens)
    print("✅ Access Token erneuert.")
    return new_tokens


def upload_tcx(access_token, file_path):
    print(f"⬆️  TCX-Datei wird hochgeladen: {file_path}")
    with open(file_path, "rb") as tcx_file:
        response = requests.post(
            "https://www.strava.com/api/v3/uploads",
            headers={"Authorization": f"Bearer {access_token}"},
            files={"file": tcx_file},
            data={
                "data_type": "tcx",
                "sport_type": UPLOAD_SPORT_TYPE,
                "trainer": UPLOAD_TRAINER,
                "name": UPLOAD_NAME,
                "description": UPLOAD_DESCRIPTION
            },
            timeout=60,
        )
    if response.status_code not in (200, 201):
        raise Exception(f"Upload fehlgeschlagen: {response.text}")
    print("✅ Upload erfolgreich gesendet.")
    return response.json()


def main():
    if len(sys.argv) != 2:
        print("Aufruf: python Utils/strava_upload.py <datei.tcx>")
        sys.exit(1)

    tokens = load_tokens()

    if time.time() > tokens.get("expires_at", 0):
        tokens = refresh_access_token(tokens)

    result = upload_tcx(tokens["access_token"], sys.argv[1])
    print("📄 Upload-Info:", result)


if __name__ == "__main__":
    main()
