# Utils/access.py – wer steuern darf, wer nur zuschaut
#
# Gesteuert wird von GENAU EINEM Gerät: dem ersten, das den PIN eingibt (Seite «Maschine»). Jedes andere Gerät
# ist Zuschauer und kann mit dem PIN die Steuerung übernehmen (mit Rückfrage, solange das Steuergerät sich
# meldet; ohne Rückfrage, wenn es CONTROLLER_STALE_S still ist – z. B. Tablet im Ruhezustand).
#  - Ausnahmen am Gerät selbst (localhost): Pause und Stop gehen immer (Sicherheit), und solange noch kein PIN
#    festgelegt ist, steuert der Browser am Pi wie früher (damit der PIN überhaupt festgelegt werden kann).
#  - Die Anmeldung gilt bis zum nächsten Start von x-ski (x-ski.sh / Neustart); der Wechsel Startmenü <-> Training
#    behält sie (Datei in /dev/shm, X_SKI_KEEP_ACCESS beim Zurückwechseln).
# Zuschauer:
#  - alle ändernden Anfragen (POST, PUT, DELETE …) werden abgelehnt – egal welche Seite sie schickt
#  - während eines Trainings zeigt er automatisch dieselbe Seite wie das Steuergerät (/api/screen)
#  - ohne Training (Startmenü) sieht er nur «Warten auf Training»
# Ausnahme: X_SKI_ALLOW_REMOTE_CONFIG=1 erlaubt das Steuern ohne PIN von überall.

import json
import os
import secrets
import threading
import time
from pathlib import Path

from flask import jsonify, request

LOCAL_ADDRESSES = ("127.0.0.1", "::1", "::ffff:127.0.0.1")
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
# Socket.IO überträgt auch reine Anzeige-Daten per POST (Long-Polling) – der Server wertet keine
# Steuerbefehle über Socket.IO aus
ALWAYS_ALLOWED_PREFIXES = ("/socket.io",)
SCREEN_MAX_AGE_S = 15.0     # älter: der Browser am Gerät meldet sich nicht mehr -> Zuschauer bleibt, wo er ist
COOKIE = "xski_access"
CONTROLLER_STALE_S = 120.0   # so lange still -> anderes Gerät übernimmt ohne Rückfrage
# am Gerät (localhost) immer erlaubt, auch ohne PIN: anhalten und beenden
LOCAL_EMERGENCY_PATHS = ("/api/session/pause", "/api/session/end", "/stop")
PIN_MAX_FAILS = 5            # so viele falsche PIN pro Adresse ...
PIN_LOCK_S = 60.0            # ... dann so lange gesperrt
_lock = threading.Lock()


def is_local() -> bool:
    return request.remote_addr in LOCAL_ADDRESSES


def access_path() -> Path:
    return Path(os.environ.get("X_SKI_ACCESS_FILE") or "/dev/shm/x-ski-access.json")


def _load() -> dict:
    try:
        data = json.loads(access_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data.setdefault("controller", None)
    data.setdefault("fails", {})
    return data


def _save(data: dict):
    path = access_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def reset_access():
    """Beim Start von x-ski: Anmeldung vergessen – das nächste Gerät mit PIN wird Steuergerät."""
    with _lock:
        _save({"controller": None, "fails": {}})


def _pin_set() -> bool:
    from Utils.machine_page import pin_set
    return pin_set()


def _controller_token(data: dict) -> str:
    c = data.get("controller") or {}
    return c.get("token", "")


def is_controller() -> bool:
    token = request.cookies.get(COOKIE, "")
    return bool(token) and token == _controller_token(_load())


def can_control(allow_remote: bool = False) -> bool:
    if allow_remote or is_controller():
        return True
    return is_local() and not _pin_set()        # ohne PIN: Browser am Pi wie früher


def _set_cookie(resp, token: str):
    resp.set_cookie(COOKIE, token, httponly=True, samesite="Strict", max_age=30 * 24 * 3600)
    return resp


def install_access_control(app, allow_remote: bool = False, training: bool = False):
    """Sperre und Zuschauer-Schnittstellen in einer Flask-App einrichten. Muss vor den übrigen
    before_request-Funktionen aufgerufen werden, damit die Sperre zuerst greift.
    training: True im Trainingsprogramm (x-ski.py), False im Startmenü – dort sehen Zuschauer nur
    «Warten auf Training» und folgen den Seiten des Geräts nicht (Profil, Auswertung bleiben privat)."""
    screen = {"path": None, "t": 0.0}

    def can_ctl() -> bool:
        return can_control(allow_remote)

    app.config["XSKI_CAN_CONTROL"] = can_ctl
    last_touch = {"t": 0.0}

    @app.before_request
    def viewers_cannot_control():
        # Lebenszeichen des Steuergeräts (höchstens alle 10 s in die Datei)
        if request.cookies.get(COOKIE) and time.monotonic() - last_touch["t"] > 10.0:
            with _lock:
                data = _load()
                if is_controller():
                    data["controller"]["last"] = time.time()
                    _save(data)
                    last_touch["t"] = time.monotonic()
        if request.method in SAFE_METHODS or can_ctl():
            return None
        if request.path.startswith(ALWAYS_ALLOWED_PREFIXES) or request.path in ("/api/login", "/api/logout"):
            return None
        if is_local() and request.path in LOCAL_EMERGENCY_PATHS:
            return None              # am Gerät gehen Pause und Stop immer
        message = "Nur Ansicht: zum Steuern mit dem PIN anmelden."
        return jsonify({"ok": False, "success": False, "message": message, "error": message}), 403

    @app.route("/api/role")
    def api_role():
        """Darf dieser Browser steuern? (für die Anzeige: Knöpfe sperren, Anmelden anbieten)"""
        data = _load()
        c = data.get("controller") or {}
        busy = bool(c) and time.time() - c.get("last", 0) <= CONTROLLER_STALE_S
        return jsonify({"control": can_ctl(), "pin_login": _pin_set(), "local": is_local(),
                        "controller": c.get("addr") if busy and not is_controller() else None})

    @app.route("/api/login", methods=["POST"])
    def api_login():
        """Anmelden mit dem PIN. Das erste Gerät wird Steuergerät; steuert schon ein anderes (und meldet sich
        noch), braucht es «takeover», dann verliert das bisherige die Steuerung."""
        from Utils.machine_page import check_pin
        if is_controller():
            return jsonify({"ok": True})
        if not _pin_set():
            return jsonify({"ok": False, "message": "Es ist noch kein PIN festgelegt (Seite «Maschine» am Gerät)."}), 409
        addr = request.remote_addr or "?"
        body = request.get_json(silent=True) or {}
        pin, takeover = str(body.get("pin", "")), bool(body.get("takeover"))
        with _lock:
            data = _load()
            count, until = data["fails"].get(addr, [0, 0.0])
            if time.time() < until:
                return jsonify({"ok": False, "message": f"Zu viele falsche Versuche – bitte {until - time.time():.0f} s "
                                                        "warten."}), 429
            if not check_pin(pin):
                count += 1
                data["fails"][addr] = [0, time.time() + PIN_LOCK_S] if count >= PIN_MAX_FAILS else [count, 0.0]
                _save(data)
                print(f"🔑 Falscher PIN von {addr} ({count}/{PIN_MAX_FAILS})", flush=True)
                return jsonify({"ok": False, "message": "Falscher PIN."}), 403
            data["fails"].pop(addr, None)
            c = data.get("controller") or {}
            if c and time.time() - c.get("last", 0) <= CONTROLLER_STALE_S and not takeover:
                where = "dem Browser am x-ski" if c.get("addr") in LOCAL_ADDRESSES else c.get("addr")
                return jsonify({"ok": False, "busy": True,
                                "message": f"Gesteuert wird gerade von {where}. Steuerung übernehmen?"}), 409
            token = secrets.token_urlsafe(32)
            data["controller"] = {"token": token, "addr": addr, "since": time.time(), "last": time.time()}
            _save(data)
        print(f"🔑 Steuerung: {addr}{' (übernommen)' if c else ''}", flush=True)
        return _set_cookie(jsonify({"ok": True}), token)

    @app.route("/api/logout", methods=["POST"])
    def api_logout():
        with _lock:
            data = _load()
            if is_controller():
                data["controller"] = None
                _save(data)
                print(f"🔑 Steuerung abgegeben ({request.remote_addr})", flush=True)
        resp = jsonify({"ok": True})
        resp.delete_cookie(COOKIE)
        return resp

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
