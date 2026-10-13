# Utils/access.py – Steuern nur am Gerät, Zuschauen von überall
#
# Der Browser direkt am x-ski (localhost) steuert. Jeder andere Browser im Netz ist Zuschauer:
#  - alle ändernden Anfragen (POST, PUT, DELETE …) werden abgelehnt – egal welche Seite sie schickt
#  - während eines Trainings zeigt er automatisch dieselbe Seite wie der Browser am Gerät (/api/screen)
#  - ohne Training (Startmenü) sieht er nur «Warten auf Training»
# Ausnahme: X_SKI_ALLOW_REMOTE_CONFIG=1 erlaubt das Steuern auch von anderen Geräten (wie bisher für die
# Einstellungen).

import time

from flask import jsonify, request

LOCAL_ADDRESSES = ("127.0.0.1", "::1", "::ffff:127.0.0.1")
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
# Socket.IO überträgt auch reine Anzeige-Daten per POST (Long-Polling) – der Server wertet keine
# Steuerbefehle über Socket.IO aus
ALWAYS_ALLOWED_PREFIXES = ("/socket.io",)
SCREEN_MAX_AGE_S = 15.0     # älter: der Browser am Gerät meldet sich nicht mehr -> Zuschauer bleibt, wo er ist


def is_local() -> bool:
    return request.remote_addr in LOCAL_ADDRESSES


def install_access_control(app, allow_remote: bool = False, training: bool = False):
    """Sperre und Zuschauer-Schnittstellen in einer Flask-App einrichten. Muss vor den übrigen
    before_request-Funktionen aufgerufen werden, damit die Sperre zuerst greift.
    training: True im Trainingsprogramm (x-ski.py), False im Startmenü – dort sehen Zuschauer nur
    «Warten auf Training» und folgen den Seiten des Geräts nicht (Profil, Auswertung bleiben privat)."""
    screen = {"path": None, "t": 0.0}

    def can_control() -> bool:
        return allow_remote or is_local()

    app.config["XSKI_CAN_CONTROL"] = can_control

    @app.before_request
    def viewers_cannot_control():
        if request.method in SAFE_METHODS or can_control():
            return None
        if request.path.startswith(ALWAYS_ALLOWED_PREFIXES):
            return None
        message = "Nur Ansicht: gesteuert wird direkt am x-ski."
        return jsonify({"ok": False, "success": False, "message": message, "error": message}), 403

    @app.route("/api/role")
    def api_role():
        """Darf dieser Browser steuern? (für die Anzeige: Knöpfe sperren, Hinweis zeigen)"""
        return jsonify({"control": can_control()})

    @app.route("/api/screen", methods=["GET", "POST"])
    def api_screen():
        """POST (nur am Gerät, durch die Sperre oben): aktuell angezeigte Seite melden.
        GET: welche Seite zeigt der Browser am Gerät? Zuschauer wechseln automatisch dorthin."""
        if request.method == "POST":
            path = str((request.get_json(silent=True) or {}).get("path", ""))
            # nur Pfade dieser Anwendung, keine fremden Adressen
            if path.startswith("/") and not path.startswith("//") and len(path) < 500:
                screen.update(path=path, t=time.monotonic())
            return jsonify({"ok": True})
        fresh = screen["path"] is not None and time.monotonic() - screen["t"] <= SCREEN_MAX_AGE_S
        return jsonify({"path": screen["path"] if fresh and training else None, "training": training})
