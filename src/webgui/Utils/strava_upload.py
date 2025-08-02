import requests
import json
import time
import os

# Konfiguration
CLIENT_ID = "170200"
CLIENT_SECRET = "2b76e91504a61240d1b090b3702d498d6b59060b"
TOKENS_FILE = "strava_tokens.json"
TCX_FILE_PATH = "deine_aktivitaet.tcx"  # Pfad zur TCX-Datei
UPLOAD_NAME = "Automatischer Upload"
UPLOAD_DESCRIPTION = "Hochgeladen von x-ski.ch"

def load_tokens():
    if not os.path.exists(TOKENS_FILE):
        raise FileNotFoundError("Tokens-Datei nicht gefunden.")
    with open(TOKENS_FILE) as f:
        return json.load(f)

def save_tokens(tokens):
    with open(TOKENS_FILE, "w") as f:
        json.dump(tokens, f)

def refresh_access_token(tokens):
    print("🔄 Access Token wird erneuert...")
    response = requests.post(
        "https://www.strava.com/api/v3/oauth/token",
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"]
        }
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
                "name": UPLOAD_NAME,
                "description": UPLOAD_DESCRIPTION
            }
        )
    if response.status_code not in (200, 201):
        raise Exception(f"Upload fehlgeschlagen: {response.text}")
    print("✅ Upload erfolgreich gesendet.")
    return response.json()

def main():
    # Tokens laden
    tokens = load_tokens()

    # Token ggf. erneuern
    if time.time() > tokens.get("expires_at", 0):
        tokens = refresh_access_token(tokens)

    access_token = tokens["access_token"]

    # Datei hochladen
    result = upload_tcx(access_token, TCX_FILE_PATH)
    print("📄 Upload-Info:", result)

if __name__ == "__main__":
    main()
