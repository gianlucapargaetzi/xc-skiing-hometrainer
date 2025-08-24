from __future__ import annotations
import os
import json
import shutil
from pathlib import Path
from typing import Tuple, Optional, Dict, Any, List

# -----------------------------------------------------------------------------
# DEFAULT_CONFIG – zentrale Standardwerte für x-ski
# -----------------------------------------------------------------------------
DEFAULT_CONFIG: Dict[str, Any] = {
    "hardware": {
        "pulli_diameter": 50.0,   # mm
        "rope_diameter": 3.0,     # mm
        "top_position": 2000.0,   # mm
        "pole_length": 1450.0,    # mm
        "swing_length": 1100.0    # mm
    },
    "swing_torque": {
        "swing_start_max_torque_pml": 200,
        "swing_end_max_torque_pml": 500
    },
    "control": {
        "min_torque_calib_pct": 15,
        "min_speed_calib": 100,   # 2.0 U/s = 20 (x10)
        "min_torque_pct": 20,
        "CurrentLimit": 80,       # A
        "pull_speed": 1500        # 5.0 U/s = 50 (x10)
    },
    "user": {
        "weight_kg": 75.0,
        "mu": 0.020,
        "s_s": 1.10,
        "slope_percent": 0.0,
        "firstname": "x-ski",
        "lastname": "Demonstration",
        "birthdate": "2000-01-01",
        "club": "x-ski.ch",
        "email": "juerg.pargaetzi@parmail.ch"
    },
    "hr_sensor": {
        "address": "24:AC:AC:03:F5:B4"  # Polar Verity Sense Beispiel
    },
    "drive": {
        "host": "192.168.200.199",
        "port": 502,
        "unit_id": 0
    }
}


class ConfigManager:
    """
    Kapselt alle Konfigurations-Funktionen (Laden, Speichern, Aktivieren,
    Auflisten, Live-Reload). Verwaltet ein Default-Config und eine aktive Datei
    (z.B. x-ski.json) im Projektverzeichnis.

    Typische Nutzung:
        manager = ConfigManager(script_dir=Path(__file__).parent, default_config=DEFAULT_CONFIG)
        config, source = manager.load_from_candidates(cli_path=cli_arg)
        manager.activate("mein_setup.json")
        manager.reload_active()
    """

    def __init__(
        self,
        script_dir: Path,
        active_filename: str = "x-ski.json",
        config_dirname: str = "configs",
        default_config: Optional[Dict[str, Any]] = None,
        env_var: str = "X_SKI_CONFIG",
    ) -> None:
        self.SCRIPT_DIR = Path(script_dir).resolve()
        self.CONFIG_DIR = (self.SCRIPT_DIR / config_dirname).resolve()
        self.CONFIG_DIR.mkdir(exist_ok=True)
        self.ACTIVE_CONFIG_PATH = (self.SCRIPT_DIR / active_filename).resolve()
        self.ENV_VAR = env_var
        # tiefe Kopie der Defaults; wenn None, auf globales DEFAULT_CONFIG zurückfallen
        self.DEFAULT_CONFIG = json.loads(json.dumps(default_config if default_config is not None else DEFAULT_CONFIG))

        # interne Zustände
        self.config: Dict[str, Any] = json.loads(json.dumps(self.DEFAULT_CONFIG))
        self.config_source: Optional[Path] = None

    # ---------------------- Utility ----------------------
    @staticmethod
    def deep_update(base: dict, override: dict) -> dict:
        """Rekursives Merge von override in base (in-place), gibt base zurück."""
        for k, v in override.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                ConfigManager.deep_update(base[k], v)
            else:
                base[k] = v
        return base

    @staticmethod
    def _is_safe_name(name: str) -> bool:
        p = Path(name)
        return (p.name == name) and p.suffix.lower() == ".json"

    def _config_file(self, name: str) -> Path:
        return (self.CONFIG_DIR / name).resolve()

    def _assert_in_config_dir(self, p: Path) -> None:
        if self.CONFIG_DIR not in p.parents and p != self.CONFIG_DIR:
            raise ValueError("Ungültiger Pfad außerhalb von configs/")

    # ---------------------- Laden / Initialisieren ----------------------
    def _candidate_paths(self) -> List[Optional[Path]]:
        env_cfg = os.getenv(self.ENV_VAR)
        return [
            Path(env_cfg) if env_cfg else None,
            self.ACTIVE_CONFIG_PATH,
            self.CONFIG_DIR / "x-ski.json",
            Path.cwd() / "x-ski.json",
        ]

    def write_example_if_missing(self, example_name: str = "x-ski.example.json") -> Optional[Path]:
        """Schreibt ein Beispiel in configs/, wenn keine Quelle gefunden wurde."""
        example = self.CONFIG_DIR / example_name
        try:
            example.write_text(
                json.dumps(self.DEFAULT_CONFIG, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            return example
        except Exception:
            return None

    def load_from_candidates(self, cli_path: Optional[str] = None) -> Tuple[Dict[str, Any], Optional[Path]]:
        """
        Lädt die Konfiguration anhand folgender Priorität:
        1) explizit via cli_path
        2) Umgebungsvariable (ENV_VAR)
        3) aktive Datei (active_filename im Projektroot)
        4) configs/x-ski.json
        5) ./x-ski.json (aktuelles Arbeitsverzeichnis)

        Merged immer über die DEFAULT_CONFIG. Gibt (config, source_path) zurück.
        Wenn keine Quelle gefunden wurde, wird ein Beispiel in configs/ geschrieben
        und source_path ist None.
        """
        candidates: List[Optional[Path]] = [Path(cli_path) if cli_path else None]
        candidates.extend(self._candidate_paths())

        cfg = json.loads(json.dumps(self.DEFAULT_CONFIG))
        found: Optional[Path] = None
        for p in candidates:
            if p and p.is_file():
                try:
                    user_cfg = json.loads(p.read_text(encoding="utf-8"))
                    self.deep_update(cfg, user_cfg)
                    found = p
                    break
                except Exception:
                    # ignorieren und weiterprobieren
                    continue

        if not found:
            self.write_example_if_missing()

        # Zustand setzen
        self.config = cfg
        self.config_source = found
        return self.config, self.config_source

    # ---------------------- CRUD im configs/-Ordner ----------------------
    def list_files(self) -> Dict[str, Any]:
        files = sorted([f.name for f in self.CONFIG_DIR.glob("*.json")])
        active_source: Optional[str] = None
        try:
            if self.ACTIVE_CONFIG_PATH.exists():
                active_data = json.loads(self.ACTIVE_CONFIG_PATH.read_text(encoding="utf-8"))
                for f in files:
                    p = (self.CONFIG_DIR / f)
                    try:
                        cand = json.loads(p.read_text(encoding="utf-8"))
                        if cand == active_data:
                            active_source = f
                            break
                    except Exception:
                        pass
        except Exception:
            pass
        return {"files": files, "active": active_source}

    def get(self, name: str) -> Dict[str, Any]:
        if not self._is_safe_name(name):
            raise ValueError("Ungültiger Dateiname")
        p = self._config_file(name)
        self._assert_in_config_dir(p)
        if not p.exists():
            raise FileNotFoundError("Datei nicht gefunden")
        return {"name": name, "content": p.read_text(encoding="utf-8")}

    def save(self, name: str, content: str) -> Dict[str, Any]:
        if not self._is_safe_name(name):
            raise ValueError("Ungültiger Dateiname (muss auf .json enden)")
        try:
            json.loads(content)
        except Exception as e:
            raise ValueError(f"JSON ungültig: {e}")
        p = self._config_file(name)
        self._assert_in_config_dir(p)
        p.write_text(content, encoding="utf-8")
        return {"ok": True, "saved": name}

    def activate(self, name: str) -> Dict[str, Any]:
        if not self._is_safe_name(name):
            raise ValueError("Ungültiger Dateiname")
        src = self._config_file(name)
        self._assert_in_config_dir(src)
        if not src.exists():
            raise FileNotFoundError("Datei nicht gefunden")
        shutil.copyfile(src, self.ACTIVE_CONFIG_PATH)
        return {"ok": True, "active": self.ACTIVE_CONFIG_PATH.name, "source": name}

    # ---------------------- Reload ----------------------
    def reload_active(self) -> Dict[str, Any]:
        if not self.ACTIVE_CONFIG_PATH.exists():
            raise FileNotFoundError("Aktive Konfiguration (x-ski.json) nicht gefunden")
        try:
            new_cfg = json.loads(self.ACTIVE_CONFIG_PATH.read_text(encoding="utf-8"))
            new_merged = json.loads(json.dumps(self.DEFAULT_CONFIG))
            self.deep_update(new_merged, new_cfg)
            self.config = new_merged
            return {"ok": True, "reloaded": str(self.ACTIVE_CONFIG_PATH)}
        except Exception as e:
            raise ValueError(f"Reload fehlgeschlagen: {e}")
