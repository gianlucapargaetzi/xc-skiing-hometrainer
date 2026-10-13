#!/usr/bin/env python3
"""x-ski.py mit simuliertem Antrieb und simuliertem Nutzer starten (für Tests ohne Maschine).

Webserver auf Port 5097 – NIE 5000 (dort läuft das echte x-ski). Keine E-Mail, kein Strava, kein Traccar,
kein Tracking-Chat (ausser mit SIM_CHAT=1),
keine Rückkehr ins Startmenü; Trainingsdateien landen im angegebenen Ordner.

    .venv/bin/python tools/sim_xski.py <ausgabeordner> [Sekunden] -- --mode skier --route "Sertig Classic 13k.gpx"
"""
import importlib.util, json, os, sys, threading, time, types
from pathlib import Path

WEBGUI = Path(__file__).resolve().parents[1] / "src" / "webgui"
PORT = 5097
args = sys.argv[1:]
extra = args[args.index("--") + 1:] if "--" in args else ["--mode", "profile"]
args = args[:args.index("--")] if "--" in args else args
OUT = Path(args[0]).resolve(); OUT.mkdir(parents=True, exist_ok=True)
HOLD_S = float(args[1]) if len(args) > 1 else 60.0

cfg = json.loads((WEBGUI / "x-ski.json").read_text())
cfg.setdefault("traccar", {})["enabled"] = False
cfg.setdefault("strava", {})["auto_upload"] = False
cfg["user"]["email"] = ""
if os.environ.get("SIM_CHAT") != "1":
    cfg.setdefault("chat", {})["enabled"] = False     # keine Meldungen an den echten Tracking-Chat
(OUT / "cfg.json").write_text(json.dumps(cfg))
sys.path.insert(0, str(WEBGUI)); os.chdir(WEBGUI)
HOST = os.environ.get("SIM_HOST", "127.0.0.1")     # SIM_HOST=0.0.0.0: auch aus dem Netz erreichbar (Zuschauer testen)
sys.argv = ["x-ski.py", "--no-browser", "--host", HOST, "--config", str(OUT / "cfg.json"), *extra]


class StubBLE:
    def __init__(self, **kw): pass
    def reset_rower_session(self): pass
    def update_rower_metrics(self, **kw): pass


class StubANT:
    def __init__(self, **kw): pass
    def get_heart_rate(self): return 150
    def close(self): pass


sys.modules["Utils.ble_manager"] = types.SimpleNamespace(BLEManager=StubBLE)
sys.modules["Utils.ant_hr_manager"] = types.SimpleNamespace(ANTHRManager=StubANT)
spec = importlib.util.spec_from_file_location("xski", WEBGUI / "x-ski.py")
xski = importlib.util.module_from_spec(spec); sys.modules["xski"] = xski; spec.loader.exec_module(xski)
from HardwareController import DriveM751 as D   # noqa: E402

S = xski.settings


class FakeDrive(D.DriveM751):
    """Hand zieht im festen Rhythmus (Zug 0.45 s, Rückweg 0.75 s); Leistung = Drehmoment × Seilgeschwindigkeit."""
    CYCLE_S, PUSH_S, HAND = 1.2, 0.45, 2.5

    def __init__(self):
        super().__init__("127.0.0.1", 1, 1, S.max_torque_pct)
        self.t0, self.tq = None, 0.0
        self.mpc = S.dist_per_rev / 1000 / 65536
        self.pole = round((S.top_position - S.pole_length) / S.dist_per_rev * 65536)

    def _write(self, a, v):
        time.sleep(0.004)
        if a == D.REG_WATCHDOG_ENABLE and v == 1: self.t0 = time.time()
        if a == D.REG_TORQUE_REF: self.tq = v / 100

    def _state(self):
        if self.t0 is None: return 0.0, 0.0
        ph = (time.time() - self.t0) % self.CYCLE_S
        if ph < self.PUSH_S: return self.HAND, self.HAND * ph
        back, rec = self.HAND * self.PUSH_S, self.CYCLE_S - self.PUSH_S
        return -back / rec, back * (1 - (ph - self.PUSH_S) / rec)

    def _read1(self, a):
        time.sleep(0.004)
        if a in (D.REG_DRIVE_HEALTHY, D.REG_HARDWARE_ENABLE): return 1
        if a == D.REG_POWER:
            v, _ = self._state()
            return (-int(self.tq / 100 * S.motor_rated_torque_nm / S.drum_radius_m * v) if v > 0 else 0) & 0xFFFF
        if a == D.REG_THERMAL_PROTECTION_MODE: return 1
        return 0

    def wait_for_sto_off(self): pass
    def wait_for_sto_on(self): pass
    def calibrate_end_position(self, *a): pass

    def read_position(self):
        time.sleep(0.004); _, x = self._state()
        return 10_000_000 - self.pole - int(x / self.mpc)


xski.drive = FakeDrive()
xski.scope = xski.Scope(max_hr_bpm=S.max_hr_bpm, ftp_w=S.ftp_w, training_targets=S.training_targets)
xski.TRAININGS_DIR = OUT
xski.send_training_email = lambda **kw: print("(E-Mail übersprungen)")
xski.restart_launcher = lambda: print("(Rückkehr ins Startmenü übersprungen)")
xski.browser_alive["until"] = time.monotonic() + 10 * 3600
threading.Thread(target=lambda: xski.app.run(host=HOST, port=PORT, debug=False, use_reloader=False), daemon=True).start()
threading.Thread(target=xski.calibration_thread if xski.MODE == "calib" else xski.training_thread, daemon=True).start()
print(f"Simulation läuft {HOLD_S:.0f} s auf http://127.0.0.1:{PORT}/", flush=True)
time.sleep(HOLD_S)
