from __future__ import annotations
import os
import json
import shutil
from pathlib import Path
from typing import Tuple, Optional, Dict, Any, List


# -------------------------------------------------------------------------
# DEFAULT_CONFIG – zentrale Standardwerte für x-ski
# -------------------------------------------------------------------------
DEFAULT_CONFIG: Dict[str, Any] = {
    "hardware": {
        "pulli_diameter": 50.0,
        "rope_diameter": 3.0,
        "top_position": 2000.0,
        "pole_length": 1450.0,
        "swing_length": 1100.0
    },
    "swing_torque": {
        "swing_start_max_torque_pml": 200,
        "swing_end_max_torque_pml": 500
    },
    "control": {
        "min_torque_calib_pct": 15,
        "min_speed_calib": 100,
        "min_torque_pct": 20,
        "CurrentLimit": 80,
        "pull_speed": 1500,
        "max_torque_pct": 200,
        "simple_initial_power_pct": 50
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
        "email": "juerg.pargaetzi@parmail.ch",
        "max_hr_bpm": 180,
        "ftp_w": 140
    },
    "hr_sensor": {
        "address": "24:AC:AC:03:F5:B4"
    },
    "drive": {
        "host": "192.168.200.199",
        "port": 502,
        "unit_id": 0
    },
    "mywhoosh_ble": {
        "enabled": True,
        "device_name": "x-ski FTMS",
        "adapter": "hci0"
    },
    "ant_hr_sensor": {
        "enabled": True,
        "device_id": 62900
    }
}


class ConfigManager:
    """
    Verwaltet Laden, Speichern, Aktivieren und Reload von Konfigurationen.
    Nutzt DEFAULT_CONFIG als Basis und merged benutzerdefinierte Werte.
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
        self.DEFAULT_CONFIG = json.loads(json.dumps(default_config if default_config else DEFAULT_CONFIG))

        self.config: Dict[str, Any] = json.loads(json.dumps(self.DEFAULT_CONFIG))
        self.config_source: Optional[Path] = None

    # ---------------------- Utility ----------------------
    @staticmethod
    def deep_update(base: dict, override: dict) -> dict:
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

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(round(float(value)))
        except (TypeError, ValueError):
            return int(default)

    @staticmethod
    def _round_int(value: float) -> int:
        return int(round(float(value)))

    def _config_file(self, name: str) -> Path:
        return (self.CONFIG_DIR / name).resolve()

    def _assert_in_config_dir(self, p: Path) -> None:
        if self.CONFIG_DIR not in p.parents and p != self.CONFIG_DIR:
            raise ValueError("Ungültiger Pfad außerhalb von configs/")

    # ---------------------- Trainingszonen ----------------------
    def _calc_range_from_pct(
        self,
        base_value: float,
        low_pct: float | None = None,
        high_pct: float | None = None
    ) -> Dict[str, int | None]:
        if base_value <= 0:
            return {"low": None, "high": None}

        low_val = self._round_int(base_value * low_pct) if low_pct is not None else None
        high_val = self._round_int(base_value * high_pct) if high_pct is not None else None
        return {"low": low_val, "high": high_val}

    def _pace_from_power_w(self, power_w: float) -> str:
        """
        Concept2/SkiErg-ähnliche Pace /500m aus Leistung.
        Rückgabe als m:ss.
        """
        power_w = self._safe_float(power_w, 0.0)
        if power_w <= 0:
            return "--:--"

        pace_seconds = 500.0 * ((2.8 / power_w) ** (1.0 / 3.0))

        minutes = int(pace_seconds // 60)
        seconds = int(round(pace_seconds % 60))

        if seconds == 60:
            minutes += 1
            seconds = 0

        return f"{minutes}:{seconds:02d}"

    def _zone_meta(self) -> Dict[str, Dict[str, str]]:
        return {
            "z1": {"legacy": "easy", "label": "Easy", "display": "Z1 (Easy)", "intensity": "sehr locker"},
            "z2": {"legacy": "z2", "label": "Z2", "display": "Z2 (Z2)", "intensity": "Grundlage"},
            "z3": {"legacy": "tempo", "label": "Tempo", "display": "Z3 (Tempo)", "intensity": "moderat"},
            "z4": {"legacy": "interval", "label": "Intervall", "display": "Z4 (Intervall)", "intensity": "hart"},
            "z5": {"legacy": "high", "label": "High", "display": "Z5 (High)", "intensity": "sehr hart"},
        }

    def calc_hr_zones(self, max_hr_bpm: float) -> Dict[str, Dict[str, Any]]:
        """
        Solltabelle bei max_hr=176:
        Z1  88–106
        Z2 107–123
        Z3 124–141
        Z4 142–158
        Z5 159–176
        """
        max_hr = self._safe_float(max_hr_bpm, 0.0)
        if max_hr <= 0:
            return {}

        meta = self._zone_meta()

        z1_low = self._round_int(max_hr * 0.50)
        z1_high = self._round_int(max_hr * 0.60)
        z2_high = self._round_int(max_hr * 0.70)
        z3_high = self._round_int(max_hr * 0.80)
        z4_high = self._round_int(max_hr * 0.90)
        z5_high = self._round_int(max_hr * 1.00)

        return {
            "z1": {
                "label": meta["z1"]["label"],
                "display": meta["z1"]["display"],
                "legacy_key": meta["z1"]["legacy"],
                "low_bpm": z1_low,
                "high_bpm": z1_high,
                "low_pct": 50,
                "high_pct": 60,
            },
            "z2": {
                "label": meta["z2"]["label"],
                "display": meta["z2"]["display"],
                "legacy_key": meta["z2"]["legacy"],
                "low_bpm": z1_high + 1,
                "high_bpm": z2_high,
                "low_pct": 60,
                "high_pct": 70,
            },
            "z3": {
                "label": meta["z3"]["label"],
                "display": meta["z3"]["display"],
                "legacy_key": meta["z3"]["legacy"],
                "low_bpm": z2_high + 1,
                "high_bpm": z3_high,
                "low_pct": 70,
                "high_pct": 80,
            },
            "z4": {
                "label": meta["z4"]["label"],
                "display": meta["z4"]["display"],
                "legacy_key": meta["z4"]["legacy"],
                "low_bpm": z3_high + 1,
                "high_bpm": z4_high,
                "low_pct": 80,
                "high_pct": 90,
            },
            "z5": {
                "label": meta["z5"]["label"],
                "display": meta["z5"]["display"],
                "legacy_key": meta["z5"]["legacy"],
                "low_bpm": z4_high + 1,
                "high_bpm": z5_high,
                "low_pct": 90,
                "high_pct": 100,
            },
        }

    def calc_bike_power_zones(self, ftp_w: float) -> Dict[str, Dict[str, Any]]:
        """
        Solltabelle bei FTP=159:
        Z1  <97 W
        Z2  97–112 W
        Z3 113–136 W
        Z4 137–158 W
        Z5 >158 W
        """
        ftp = self._safe_float(ftp_w, 0.0)
        if ftp <= 0:
            return {}

        meta = self._zone_meta()

        z2_low = self._round_int(ftp * (97.0 / 159.0))
        z2_high = self._round_int(ftp * (112.0 / 159.0))
        z3_high = self._round_int(ftp * (136.0 / 159.0))
        z5_low = self._round_int(ftp * (159.0 / 159.0))

        z1_high = z2_low - 1
        z3_low = z2_high + 1
        z4_low = z3_high + 1
        z4_high = z5_low - 1

        return {
            "z1": {
                "label": meta["z1"]["label"],
                "display": meta["z1"]["display"],
                "legacy_key": meta["z1"]["legacy"],
                "low_w": 0,
                "high_w": z1_high,
                "low_pct": 0,
                "high_pct": 61,
            },
            "z2": {
                "label": meta["z2"]["label"],
                "display": meta["z2"]["display"],
                "legacy_key": meta["z2"]["legacy"],
                "low_w": z2_low,
                "high_w": z2_high,
                "low_pct": 61,
                "high_pct": 70,
            },
            "z3": {
                "label": meta["z3"]["label"],
                "display": meta["z3"]["display"],
                "legacy_key": meta["z3"]["legacy"],
                "low_w": z3_low,
                "high_w": z3_high,
                "low_pct": 71,
                "high_pct": 86,
            },
            "z4": {
                "label": meta["z4"]["label"],
                "display": meta["z4"]["display"],
                "legacy_key": meta["z4"]["legacy"],
                "low_w": z4_low,
                "high_w": z4_high,
                "low_pct": 86,
                "high_pct": 100,
            },
            "z5": {
                "label": meta["z5"]["label"],
                "display": meta["z5"]["display"],
                "legacy_key": meta["z5"]["legacy"],
                "low_w": z5_low,
                "high_w": None,
                "low_pct": 100,
                "high_pct": None,
            },
        }

    def calc_xski_power_zones(self, ftp_w: float) -> Dict[str, Dict[str, Any]]:
        """
        Praxisnäher kalibrierte x-ski-Watt-Zonen.

        Neue Solltabelle bei FTP=159:
        Z1  <38 W   -> intern 0–37
        Z2  38–45 W
        Z3  46–50 W
        Z4  51–56 W
        Z5 >56 W    -> intern 57+
        """
        ftp = self._safe_float(ftp_w, 0.0)
        if ftp <= 0:
            return {}

        meta = self._zone_meta()

        z2_low = self._round_int(ftp * (38.0 / 159.0))
        z2_high = self._round_int(ftp * (45.0 / 159.0))
        z3_high = self._round_int(ftp * (50.0 / 159.0))
        z4_high = self._round_int(ftp * (56.0 / 159.0))
        z5_low = self._round_int(ftp * (57.0 / 159.0))

        z1_high = z2_low - 1
        z3_low = z2_high + 1
        z4_low = z3_high + 1

        return {
            "z1": {
                "label": meta["z1"]["label"],
                "display": meta["z1"]["display"],
                "legacy_key": meta["z1"]["legacy"],
                "low_w": 0,
                "high_w": z1_high,
            },
            "z2": {
                "label": meta["z2"]["label"],
                "display": meta["z2"]["display"],
                "legacy_key": meta["z2"]["legacy"],
                "low_w": z2_low,
                "high_w": z2_high,
            },
            "z3": {
                "label": meta["z3"]["label"],
                "display": meta["z3"]["display"],
                "legacy_key": meta["z3"]["legacy"],
                "low_w": z3_low,
                "high_w": z3_high,
            },
            "z4": {
                "label": meta["z4"]["label"],
                "display": meta["z4"]["display"],
                "legacy_key": meta["z4"]["legacy"],
                "low_w": z4_low,
                "high_w": z4_high,
            },
            "z5": {
                "label": meta["z5"]["label"],
                "display": meta["z5"]["display"],
                "legacy_key": meta["z5"]["legacy"],
                "low_w": z5_low,
                "high_w": None,
            },
        }

    def calc_pace_reference_power_zones(self, ftp_w: float) -> Dict[str, Dict[str, Any]]:
        """
        Pace-Referenz bleibt bewusst an der bisherigen Pace-Kalibrierung.

        Referenz bei FTP=159:
        Z1  <53 W   -> intern 0–52
        Z2  53–57 W
        Z3  58–60 W
        Z4  61–65 W
        Z5 >65 W    -> intern 66+
        """
        ftp = self._safe_float(ftp_w, 0.0)
        if ftp <= 0:
            return {}

        z2_low = self._round_int(ftp * (53.0 / 159.0))
        z2_high = self._round_int(ftp * (57.0 / 159.0))
        z3_high = self._round_int(ftp * (60.0 / 159.0))
        z4_high = self._round_int(ftp * (65.0 / 159.0))
        z5_low = self._round_int(ftp * (66.0 / 159.0))

        z1_high = z2_low - 1
        z3_low = z2_high + 1
        z4_low = z3_high + 1

        return {
            "z1": {"low_w": 0, "high_w": z1_high},
            "z2": {"low_w": z2_low, "high_w": z2_high},
            "z3": {"low_w": z3_low, "high_w": z3_high},
            "z4": {"low_w": z4_low, "high_w": z4_high},
            "z5": {"low_w": z5_low, "high_w": None},
        }

    def calc_pace_zones(self, ftp_w: float) -> Dict[str, Dict[str, Any]]:
        pace_power = self.calc_pace_reference_power_zones(ftp_w)
        if not pace_power:
            return {}

        result: Dict[str, Dict[str, Any]] = {}
        meta = self._zone_meta()

        z1_high = pace_power["z1"].get("high_w")
        z2_low = pace_power["z2"].get("low_w")
        z2_high = pace_power["z2"].get("high_w")
        z3_low = pace_power["z3"].get("low_w")
        z3_high = pace_power["z3"].get("high_w")
        z4_low = pace_power["z4"].get("low_w")
        z4_high = pace_power["z4"].get("high_w")
        z5_low = pace_power["z5"].get("low_w")

        result["z1"] = {
            "label": meta["z1"]["label"],
            "display_name": meta["z1"]["display"],
            "legacy_key": meta["z1"]["legacy"],
            "display": f">{self._pace_from_power_w(z1_high)}" if z1_high else "—"
        }
        result["z2"] = {
            "label": meta["z2"]["label"],
            "display_name": meta["z2"]["display"],
            "legacy_key": meta["z2"]["legacy"],
            "display": (
                f"{self._pace_from_power_w(z2_high)}–{self._pace_from_power_w(z2_low)}"
                if z2_low is not None and z2_high is not None else "—"
            )
        }
        result["z3"] = {
            "label": meta["z3"]["label"],
            "display_name": meta["z3"]["display"],
            "legacy_key": meta["z3"]["legacy"],
            "display": (
                f"{self._pace_from_power_w(z3_high)}–{self._pace_from_power_w(z3_low)}"
                if z3_low is not None and z3_high is not None else "—"
            )
        }
        result["z4"] = {
            "label": meta["z4"]["label"],
            "display_name": meta["z4"]["display"],
            "legacy_key": meta["z4"]["legacy"],
            "display": (
                f"{self._pace_from_power_w(z4_high)}–{self._pace_from_power_w(z4_low)}"
                if z4_low is not None and z4_high is not None else "—"
            )
        }
        result["z5"] = {
            "label": meta["z5"]["label"],
            "display_name": meta["z5"]["display"],
            "legacy_key": meta["z5"]["legacy"],
            "display": f"<{self._pace_from_power_w(z5_low)}" if z5_low else "—"
        }

        return result

    def calc_skierg_spm_zones(self, ftp_w: float) -> Dict[str, Dict[str, Any]]:
        """
        SPM-Zonen für Live-Chart und Dashboard.
        Praxisnäher kalibriert:
        - bei FTP ~140 liegt ein lockerer Bereich eher um 40–44 spm
        - dadurch passen SPM, Puls und x-ski-Leistung besser zusammen
        """
        ftp_w = self._safe_float(ftp_w, 0.0)
        meta = self._zone_meta()

        if ftp_w < 130:
            return {
                "z1": {
                    "label": meta["z1"]["label"], "display": meta["z1"]["display"], "legacy_key": meta["z1"]["legacy"],
                    "low_spm": 36, "high_spm": 42, "target_spm": 40
                },
                "z2": {
                    "label": meta["z2"]["label"], "display": meta["z2"]["display"], "legacy_key": meta["z2"]["legacy"],
                    "low_spm": 43, "high_spm": 46, "target_spm": 44
                },
                "z3": {
                    "label": meta["z3"]["label"], "display": meta["z3"]["display"], "legacy_key": meta["z3"]["legacy"],
                    "low_spm": 47, "high_spm": 50, "target_spm": 48
                },
                "z4": {
                    "label": meta["z4"]["label"], "display": meta["z4"]["display"], "legacy_key": meta["z4"]["legacy"],
                    "low_spm": 51, "high_spm": 54, "target_spm": 52
                },
                "z5": {
                    "label": meta["z5"]["label"], "display": meta["z5"]["display"], "legacy_key": meta["z5"]["legacy"],
                    "low_spm": 55, "high_spm": 58, "target_spm": 56
                },
            }

        if ftp_w < 170:
            return {
                "z1": {
                    "label": meta["z1"]["label"], "display": meta["z1"]["display"], "legacy_key": meta["z1"]["legacy"],
                    "low_spm": 38, "high_spm": 44, "target_spm": 42
                },
                "z2": {
                    "label": meta["z2"]["label"], "display": meta["z2"]["display"], "legacy_key": meta["z2"]["legacy"],
                    "low_spm": 45, "high_spm": 48, "target_spm": 46
                },
                "z3": {
                    "label": meta["z3"]["label"], "display": meta["z3"]["display"], "legacy_key": meta["z3"]["legacy"],
                    "low_spm": 49, "high_spm": 52, "target_spm": 50
                },
                "z4": {
                    "label": meta["z4"]["label"], "display": meta["z4"]["display"], "legacy_key": meta["z4"]["legacy"],
                    "low_spm": 53, "high_spm": 56, "target_spm": 54
                },
                "z5": {
                    "label": meta["z5"]["label"], "display": meta["z5"]["display"], "legacy_key": meta["z5"]["legacy"],
                    "low_spm": 57, "high_spm": 60, "target_spm": 58
                },
            }

        return {
            "z1": {
                "label": meta["z1"]["label"], "display": meta["z1"]["display"], "legacy_key": meta["z1"]["legacy"],
                "low_spm": 40, "high_spm": 46, "target_spm": 44
            },
            "z2": {
                "label": meta["z2"]["label"], "display": meta["z2"]["display"], "legacy_key": meta["z2"]["legacy"],
                "low_spm": 47, "high_spm": 50, "target_spm": 48
            },
            "z3": {
                "label": meta["z3"]["label"], "display": meta["z3"]["display"], "legacy_key": meta["z3"]["legacy"],
                "low_spm": 51, "high_spm": 54, "target_spm": 52
            },
            "z4": {
                "label": meta["z4"]["label"], "display": meta["z4"]["display"], "legacy_key": meta["z4"]["legacy"],
                "low_spm": 55, "high_spm": 58, "target_spm": 56
            },
            "z5": {
                "label": meta["z5"]["label"], "display": meta["z5"]["display"], "legacy_key": meta["z5"]["legacy"],
                "low_spm": 59, "high_spm": 62, "target_spm": 60
            },
        }

    def build_training_targets(self, max_hr_bpm: float, ftp_w: float) -> Dict[str, Any]:
        hr_zones = self.calc_hr_zones(max_hr_bpm)
        bike_power_zones = self.calc_bike_power_zones(ftp_w)
        xski_power_zones = self.calc_xski_power_zones(ftp_w)
        pace_zones = self.calc_pace_zones(ftp_w)
        skierg_spm_zones = self.calc_skierg_spm_zones(ftp_w)

        zone_order = ["z1", "z2", "z3", "z4", "z5"]
        meta = self._zone_meta()

        combined_zones: Dict[str, Dict[str, Any]] = {}
        for key in zone_order:
            combined_zones[key] = {
                "zone_key": key,
                "legacy_key": meta[key]["legacy"],
                "label": meta[key]["label"],
                "display": meta[key]["display"],
                "intensity": meta[key]["intensity"],
                "hr": hr_zones.get(key, {}),
                "bike_power": bike_power_zones.get(key, {}),
                "pace": pace_zones.get(key, {}),
                "xski_power": xski_power_zones.get(key, {}),
                "spm": skierg_spm_zones.get(key, {}),
            }

        return {
            "hr_zones": hr_zones,
            "bike_power_zones": bike_power_zones,
            "xski_power_zones": xski_power_zones,
            "pace_zones": pace_zones,
            "skierg_spm_zones": skierg_spm_zones,
            "combined_zones": combined_zones
        }

    # ---------------------- Neue Funktion ----------------------
    def load_default_config(self) -> Tuple[Dict[str, Any], Optional[Path]]:
        """
        Lädt explizit die Datei x-ski.default.json aus configs/, wenn vorhanden.
        Wenn nicht vorhanden, wird DEFAULT_CONFIG verwendet.
        """
        cfg = json.loads(json.dumps(self.DEFAULT_CONFIG))
        default_path = self.CONFIG_DIR / "x-ski.default.json"
        if default_path.is_file():
            try:
                user_cfg = json.loads(default_path.read_text(encoding="utf-8"))
                self.deep_update(cfg, user_cfg)
                self.config = cfg
                self.config_source = default_path
                return self.config, self.config_source
            except Exception:
                pass
        self.config = cfg
        self.config_source = None
        return self.config, None

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
        example = self.CONFIG_DIR / example_name
        try:
            example.write_text(json.dumps(self.DEFAULT_CONFIG, indent=2, ensure_ascii=False), encoding="utf-8")
            return example
        except Exception:
            return None

    def load_from_candidates(self, cli_path: Optional[str] = None) -> Tuple[Dict[str, Any], Optional[Path]]:
        """
        Priorität:
        1) CLI-Pfad
        2) ENV-Variable
        3) aktive Datei
        4) configs/x-ski.json
        5) ./x-ski.json
        Fallback:
        -> configs/x-ski.default.json
        -> Beispiel-Datei schreiben
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
                    continue

        if not found:
            default_path = self.CONFIG_DIR / "x-ski.default.json"
            if default_path.is_file():
                try:
                    user_cfg = json.loads(default_path.read_text(encoding="utf-8"))
                    self.deep_update(cfg, user_cfg)
                    found = default_path
                except Exception:
                    pass

        if not found:
            self.write_example_if_missing()

        self.config = cfg
        self.config_source = found
        return self.config, self.config_source

    # ---------------------- Getter ----------------------
    def get_max_hr(self) -> int:
        user = self.config.get("user", {})
        return self._safe_int(user.get("max_hr_bpm", 0), 0)

    def get_ftp(self) -> float:
        user = self.config.get("user", {})
        return self._safe_float(user.get("ftp_w", 0), 0.0)

    def get_simple_initial_power_pct(self) -> float:
        control = self.config.get("control", {})
        return self._safe_float(control.get("simple_initial_power_pct", 60), 60.0)

    def get_training_targets(self) -> Dict[str, Any]:
        return self.build_training_targets(
            max_hr_bpm=self.get_max_hr(),
            ftp_w=self.get_ftp()
        )

    # ---------------------- Validierung ----------------------
    def validate_user_profile(self) -> List[str]:
        errors: List[str] = []
        user = self.config.get("user", {})
        control = self.config.get("control", {})

        max_hr = user.get("max_hr_bpm", None)
        ftp_w = user.get("ftp_w", None)
        simple_initial_power_pct = control.get("simple_initial_power_pct", None)

        try:
            max_hr_val = int(round(float(max_hr)))
            if max_hr_val < 100 or max_hr_val > 240:
                errors.append("user.max_hr_bpm liegt außerhalb des plausiblen Bereichs (100–240).")
        except (TypeError, ValueError):
            errors.append("user.max_hr_bpm ist ungültig oder fehlt.")

        try:
            ftp_val = float(ftp_w)
            if ftp_val <= 0:
                errors.append("user.ftp_w muss größer als 0 sein.")
        except (TypeError, ValueError):
            errors.append("user.ftp_w ist ungültig oder fehlt.")

        try:
            init_val = float(simple_initial_power_pct)
            if init_val < 0 or init_val > 200:
                errors.append("control.simple_initial_power_pct liegt außerhalb des plausiblen Bereichs (0–200).")
        except (TypeError, ValueError):
            errors.append("control.simple_initial_power_pct ist ungültig oder fehlt.")

        return errors

    # ---------------------- CRUD ----------------------
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
            return {
                "ok": True,
                "reloaded": str(self.ACTIVE_CONFIG_PATH),
                "training_targets": self.get_training_targets(),
                "validation_errors": self.validate_user_profile()
            }
        except Exception as e:
            raise ValueError(f"Reload fehlgeschlagen: {e}")