# Utils/machine_page.py – Seite «Maschine»: Antrieb, Motoren, Trommel (gilt für alle Profile, maschine.json).
# Ändern nur am Gerät und nur mit Passwort. Das Passwort wird beim ersten Speichern festgelegt und nur als
# Hash (PBKDF2) in maschine.json abgelegt.

import json

from flask import Blueprint, jsonify, render_template, request
from werkzeug.security import check_password_hash, generate_password_hash

from Utils import machine
from Utils.profile_page import MACHINE_FIELDS, _field_meta, _parse
from Utils.settings import Settings

MIN_PASSWORD_LEN = 4


def _password_hash() -> str:
    try:
        return json.loads(machine.machine_path().read_text(encoding="utf-8")).get("password_hash") or ""
    except (OSError, ValueError):
        return ""


def _save_password_hash(value: str):
    path = machine.machine_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data["password_hash"] = value
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def create_machine_blueprint(cfg_manager, on_saved=None, allow_remote: bool = False, locked_reason=None) -> Blueprint:
    """locked_reason: optional Funktion -> Text, wenn gerade nicht gespeichert werden darf (z. B. Training läuft)."""
    bp = Blueprint("machine", __name__)

    def current_values() -> dict:
        cfg = json.loads(json.dumps(cfg_manager.DEFAULT_CONFIG))
        cfg_manager.deep_update(cfg, json.loads(cfg_manager.ACTIVE_CONFIG_PATH.read_text(encoding="utf-8"))
                                if cfg_manager.ACTIVE_CONFIG_PATH.exists() else {})
        return {f"{s}.{k}": machine.section_config(s, cfg.get(s)).get(k) for s, k, *_ in MACHINE_FIELDS}, cfg

    @bp.route("/maschine")
    def machine_page():
        return render_template("maschine.html")

    @bp.route("/api/maschine", methods=["GET"])
    def get_machine():
        values, _ = current_values()
        return jsonify({"fields": _field_meta(MACHINE_FIELDS), "values": values,
                        "password_set": bool(_password_hash()),
                        "locked": locked_reason() if locked_reason else None})

    @bp.route("/api/maschine", methods=["POST"])
    def save_machine():
        if not allow_remote and request.remote_addr not in ("127.0.0.1", "::1"):
            return jsonify({"ok": False, "message": "Maschinendaten können nur direkt am x-ski geändert werden."}), 403
        reason = locked_reason() if locked_reason else None
        if reason:
            return jsonify({"ok": False, "message": reason}), 409
        data = request.get_json(silent=True) or {}
        password = str(data.get("password", ""))
        stored = _password_hash()
        if stored:
            if not check_password_hash(stored, password):
                print("🔒 Maschine: falsches Passwort")
                return jsonify({"ok": False, "message": "Falsches Passwort."}), 403
        elif len(password) < MIN_PASSWORD_LEN:
            return jsonify({"ok": False, "message": f"Bitte zuerst ein Passwort festlegen "
                                                    f"(mindestens {MIN_PASSWORD_LEN} Zeichen)."}), 400
        new_password = str(data.get("new_password", "") or "")
        if new_password and len(new_password) < MIN_PASSWORD_LEN:
            return jsonify({"ok": False, "message": f"Das neue Passwort braucht mindestens {MIN_PASSWORD_LEN} Zeichen."}), 400

        values = data.get("values", {})
        updates = {}
        try:
            for field in MACHINE_FIELDS:
                ident = f"{field[0]}.{field[1]}"
                if ident in values:
                    updates.setdefault(field[0], {})[field[1]] = _parse(field, values[ident])
            # mit den neuen Werten prüfen, bevor etwas geschrieben wird
            _, cfg = current_values()
            for section, vals in updates.items():
                cfg[section] = {**machine.section_config(section, cfg.get(section)), **vals}
            Settings.from_config(cfg, {}).validate_geometry()
        except ValueError as e:
            return jsonify({"ok": False, "message": str(e)}), 400

        if not stored:
            _save_password_hash(generate_password_hash(password))
            print("🔒 Maschine: Passwort festgelegt")
        if new_password:
            _save_password_hash(generate_password_hash(new_password))
            print("🔒 Maschine: Passwort geändert")
        values_now, _ = current_values()
        changed = {}
        for section, vals in updates.items():
            diff = {k: v for k, v in vals.items() if values_now.get(f"{section}.{k}") != v}
            if diff:
                machine.save_section(section, diff)
                changed[section] = diff
        if changed:
            print(f"⚙️ Maschine geändert: {changed}")
        if on_saved is not None:
            try:
                on_saved()
            except Exception as e:
                return jsonify({"ok": True, "message": f"Gespeichert (nicht übernommen: {e})."})
        return jsonify({"ok": True, "message": "Gespeichert – gilt ab dem nächsten Trainingsstart."
                                               if changed else "Gespeichert (keine Änderung)."})

    return bp
