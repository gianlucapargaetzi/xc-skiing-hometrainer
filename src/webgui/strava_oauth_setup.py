import http.server
import socketserver
import webbrowser
import requests
import json

# 🔧 HIER DEINE DATEN EINTRAGEN
CLIENT_ID = "170200"
CLIENT_SECRET = "2b76e91504a61240d1b090b3702d498d6b59060b"
REDIRECT_URI = "http://localhost:8080/callback"
TOKENS_FILE = "strava_tokens.json"

# 🌐 Schritt 1: Autorisierungslink öffnen
auth_url = (
    f"https://www.strava.com/oauth/authorize?client_id={CLIENT_ID}"
    f"&response_type=code&redirect_uri={REDIRECT_URI}"
    f"&approval_prompt=force&scope=activity:write,activity:read"
)

print("🔗 Öffne Strava zur Autorisierung...")
webbrowser.open(auth_url)

# 🖥️ Schritt 2: Lokaler Webserver für Callback
class StravaHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if "/callback" in self.path and "code=" in self.path:
            code = self.path.split("code=")[1].split("&")[0]

            # 💬 Info an Browser
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h1>Erfolgreich! Du kannst das Fenster jetzt schliessen.</h1>")

            print("🔄 Tausche Code gegen Tokens...")
            response = requests.post(
                "https://www.strava.com/oauth/token",
                data={
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                    "code": code,
                    "grant_type": "authorization_code"
                }
            )

            if response.status_code == 200:
                tokens = response.json()
                with open(TOKENS_FILE, "w") as f:
                    json.dump(tokens, f)
                print("✅ Tokens gespeichert in:", TOKENS_FILE)
            else:
                print("❌ Fehler beim Token-Austausch:", response.text)

            # Server danach beenden
            self.server.shutdown()

PORT = 8080
with socketserver.TCPServer(("", PORT), StravaHandler) as httpd:
    print(f"🌐 Warte auf Callback auf http://localhost:{PORT}/callback ...")
    httpd.serve_forever()
