# Utils/settings.py – alle aus der Konfiguration abgeleiteten Laufzeitwerte an einem Ort

from dataclasses import dataclass, field
from typing import Any, Dict, List

# top_position = 2100 mm muss innerhalb des darstellbaren / validierbaren Bereichs liegen
MAX_TRAVEL_MM = 2500


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


@dataclass(frozen=True)
class Settings:
    # Hardware / Geometrie [mm]
    pulli_diameter: float
    rope_diameter: float
    top_position: float
    pole_length: float
    swing_length: float
    swing_start_max_torque_pml: float
    swing_end_max_torque_pml: float

    # Regelung
    min_torque_calib_pct: float
    min_speed_calib: float
    min_torque_pct: float
    current_limit: float
    pull_speed: float
    max_torque_pct: float
    simple_initial_power_pct: float

    # Athlet
    weight_kg: float
    mu: float
    s_s: float
    slope_percent: float
    firstname: str
    lastname: str
    birthdate: str
    club: str
    email: str
    max_hr_bpm: float
    ftp_w: float
    training_targets: Dict[str, Any] = field(default_factory=dict)

    # Drive (Modbus TCP)
    drive_host: str = "127.0.0.1"
    drive_port: int = 502
    drive_unit_id: int = 1

    # BLE FTMS (MyWhoosh)
    ble_enabled: bool = True
    ble_name: str = "x-ski FTMS"
    ble_adapter: str = "hci0"

    # ANT+ Herzfrequenz
    ant_hr_enabled: bool = True
    ant_hr_device_id: int = 0

    # Simulation (siehe Utils/skier_model.py)
    load_mode: str = "profile"
    cda_m2: float = 0.45
    air_density_kg_m3: float = 1.2
    motor_rated_torque_nm: float = 0.0
    force_scale: float = 1.0
    max_force_step_n: float = 20.0
    # Abstimmung auf Messungen auf Schnee (siehe README):
    power_scale: float = 1.0      # gemessene Seilleistung -> Vortriebsleistung auf Schnee
    equipment_kg: float = 0.0     # Ski, Stöcke, Kleidung
    feel_mu: float = 0.02         # Gleitreibung nur für die Stosskraft am Seil (Fahrgefühl)
    diagonal_from_slope_percent: float = 5.0  # Auto: ab hier Diagonal (Userprofil)
    diagonal_hysteresis_percent: float = 1.0  # Auto: zurück auf Double Poling unter Schwelle − Hysterese
    diagonal_arm_share: float = 0.4           # Anteil der Arme am Vortrieb im Diagonalschritt
    # Diagonal: Faktor auf die Vortriebsleistung (fiktiver Beinabstoss). Abgleich Sertig 13k vom 2026-10-07:
    # bergauf ziehst du am Seil ohnehin mehr, der Faktor ist ~1 (vorher 1/Armanteil = 2.5 -> zu schnell)
    diagonal_power_factor: float = 1.0
    # Bergab fühlt sich der Stoss mindestens so an wie in der Ebene (Anteil 0..1); sonst wäre nur der Grundzug
    # zu spüren und man könnte bergab keine Leistung abgeben und nicht beschleunigen
    downhill_feel_floor: float = 1.0
    # Gegenkraft am Zugende: der Grundzug steigt im letzten Drittel des Zugs bis auf diesen Wert, damit das
    # Seil beim Abbremsen der Hände nicht lose wird (nur spürbar, wenn die Stosskraft dort kleiner ist)
    end_pull_torque_pct: float = 15.0

    # Rückzug (Seil nach dem Stoss zurückholen): Drehmoment in %; Standard = Grundzug min_torque_pct
    recovery_torque_pct: float = 30.0

    # Strava: FIT nach dem Training automatisch hochladen
    strava_auto_upload: bool = False
    strava_athlete_id: int = 0          # Strava-Konto dieses Profils (0 = nicht verbunden)
    route_file: str = ""
    route_slope_factor: float = 1.0

    # Traccar (Live-Position)
    traccar_enabled: bool = False
    traccar_protocol: str = "osmand"
    traccar_url: str = "http://traccar:5055"
    traccar_host: str = "traccar"
    traccar_port: int = 5064
    traccar_device_id: str = ""
    traccar_interval_s: float = 5.0
    max_rope_force_n: float = 150.0
    slope_per_intensity_pct: float = 0.1
    rope_speed_alpha: float = 0.5

    @classmethod
    def from_config(cls, config: Dict[str, Any], training_targets: Dict[str, Any]) -> "Settings":
        hw = config["hardware"]
        swing = config["swing_torque"]
        ctrl = config["control"]
        user = config["user"]
        drive = config["drive"]
        ble = config.get("mywhoosh_ble", {})
        ant = config.get("ant_hr_sensor", {})
        sim = config.get("simulation", {})
        trc = config.get("traccar", {})

        return cls(
            pulli_diameter=hw["pulli_diameter"],
            rope_diameter=hw["rope_diameter"],
            top_position=hw["top_position"],
            pole_length=hw["pole_length"],
            swing_length=hw["swing_length"],
            swing_start_max_torque_pml=swing["swing_start_max_torque_pml"],
            swing_end_max_torque_pml=swing["swing_end_max_torque_pml"],
            min_torque_calib_pct=ctrl["min_torque_calib_pct"],
            min_speed_calib=ctrl["min_speed_calib"],
            min_torque_pct=ctrl["min_torque_pct"],
            current_limit=ctrl["CurrentLimit"],
            pull_speed=ctrl["pull_speed"],
            max_torque_pct=ctrl.get("max_torque_pct", 150),
            simple_initial_power_pct=safe_float(ctrl.get("simple_initial_power_pct", 50), 50.0),
            weight_kg=user["weight_kg"],
            mu=user["mu"],
            s_s=user["s_s"],
            slope_percent=user["slope_percent"],
            firstname=user.get("firstname", ""),
            lastname=user.get("lastname", ""),
            birthdate=user.get("birthdate", ""),
            club=user.get("club", ""),
            email=user.get("email", ""),
            max_hr_bpm=safe_float(user.get("max_hr_bpm", 0), 0.0),
            ftp_w=safe_float(user.get("ftp_w", 0), 0.0),
            training_targets=training_targets,
            drive_host=drive["host"],
            drive_port=drive["port"],
            drive_unit_id=drive["unit_id"],
            ble_enabled=bool(ble.get("enabled", True)),
            ble_name=ble.get("device_name", "x-ski FTMS"),
            ble_adapter=ble.get("adapter", "hci0"),
            ant_hr_enabled=bool(ant.get("enabled", True)),
            ant_hr_device_id=int(ant.get("device_id", 0) or 0),
            load_mode=str(sim.get("load_mode", "profile")).strip().lower(),
            cda_m2=safe_float(sim.get("cda_m2", 0.45), 0.45),
            air_density_kg_m3=safe_float(sim.get("air_density_kg_m3", 1.2), 1.2),
            motor_rated_torque_nm=safe_float(sim.get("motor_rated_torque_nm", 0.0), 0.0),
            force_scale=safe_float(sim.get("force_scale", 1.0), 1.0),
            max_force_step_n=safe_float(sim.get("max_force_step_n", 20.0), 20.0),
            power_scale=safe_float(sim.get("power_scale", 1.0), 1.0),
            equipment_kg=safe_float(sim.get("equipment_kg", 0.0), 0.0),
            # ohne eigene Angabe: Fahrgefühl mit derselben Gleitreibung wie das Tempo
            feel_mu=safe_float(sim.get("feel_mu", user["mu"]), user["mu"]),
            # Technikwechsel gehört zum Athleten (Userprofil); ältere Konfigurationen: Abschnitt "simulation"
            diagonal_from_slope_percent=safe_float(
                user.get("diagonal_from_slope_percent", sim.get("diagonal_from_slope_percent", 5.0)), 5.0),
            diagonal_hysteresis_percent=safe_float(
                user.get("diagonal_hysteresis_percent", sim.get("diagonal_hysteresis_percent", 1.0)), 1.0),
            diagonal_arm_share=safe_float(sim.get("diagonal_arm_share", 0.4), 0.4),
            diagonal_power_factor=safe_float(sim.get("diagonal_power_factor", 1.0), 1.0),
            downhill_feel_floor=safe_float(sim.get("downhill_feel_floor", 1.0), 1.0),
            end_pull_torque_pct=safe_float(ctrl.get("end_pull_torque_pct", 15.0), 15.0),
            recovery_torque_pct=safe_float(ctrl.get("recovery_torque_pct", ctrl["min_torque_pct"]), ctrl["min_torque_pct"]),
            strava_auto_upload=bool(config.get("strava", {}).get("auto_upload", False)),
            strava_athlete_id=int(config.get("strava", {}).get("athlete_id") or 0),
            route_file=str(sim.get("route_file", "") or ""),
            route_slope_factor=safe_float(sim.get("route_slope_factor", 1.0), 1.0),
            traccar_enabled=bool(trc.get("enabled", False)),
            traccar_protocol=str(trc.get("protocol", "osmand")).strip().lower(),
            traccar_url=str(trc.get("url", "http://traccar:5055")),
            traccar_host=str(trc.get("host", "traccar")),
            traccar_port=int(trc.get("port", 5064) or 5064),
            traccar_device_id=str(trc.get("device_id", "") or "").strip(),
            traccar_interval_s=safe_float(trc.get("interval_s", 5), 5.0),
            max_rope_force_n=safe_float(sim.get("max_rope_force_n", 150.0), 150.0),
            slope_per_intensity_pct=safe_float(sim.get("slope_per_intensity_pct", 0.1), 0.1),
            rope_speed_alpha=safe_float(sim.get("rope_speed_alpha", 0.5), 0.5),
        )

    @property
    def system_mass_kg(self) -> float:
        """Masse für den virtuellen Skifahrer: Athlet + Ausrüstung."""
        return self.weight_kg + self.equipment_kg

    @property
    def skier_mode_requested(self) -> bool:
        return self.load_mode == "skier"

    @property
    def skier_mode_available(self) -> bool:
        """Skifahrer-Modus nur mit bekanntem Motor-Nenndrehmoment (Umrechnung N -> %)."""
        return self.skier_mode_requested and self.motor_rated_torque_nm > 0

    # ---------------------- abgeleitete Geometrie ----------------------
    @property
    def drum_radius_m(self) -> float:
        """Wirksamer Radius der Seiltrommel [m]."""
        return (self.pulli_diameter + self.rope_diameter) / 2.0 / 1000.0

    @property
    def dist_per_rev(self) -> int:
        """Seilweg pro Motorumdrehung [mm]."""
        return round((self.pulli_diameter + self.rope_diameter) * 3.14159)

    @property
    def swing_start_mm(self) -> float:
        return self.top_position - self.pole_length

    @property
    def swing_end_mm(self) -> float:
        return self.swing_start_mm + self.swing_length

    @property
    def max_torque_start_mm(self) -> float:
        return self.swing_start_mm + self.swing_start_max_torque_pml

    @property
    def max_torque_end_mm(self) -> float:
        return self.swing_start_mm + self.swing_end_max_torque_pml

    def geometry_errors(self) -> List[str]:
        errors = []
        swing_start_mm = self.swing_start_mm
        swing_end_mm = self.swing_end_mm

        if self.top_position > MAX_TRAVEL_MM:
            errors.append(f"top_position ({self.top_position}) darf nicht größer als {MAX_TRAVEL_MM} sein.")

        if swing_start_mm < 0:
            errors.append(
                f"top_position - pole_length = {swing_start_mm} ist kleiner als 0. "
                "Die Stocklänge ist größer als die Montagehöhe."
            )

        if swing_end_mm > MAX_TRAVEL_MM:
            errors.append(
                f"top_position - pole_length + swing_length = {swing_end_mm} ist größer als {MAX_TRAVEL_MM}. "
                "Wichtig: Höhe minus Stocklänge plus Schwunglänge muss kleiner oder gleich MAX_TRAVEL_MM sein."
            )

        if self.swing_start_max_torque_pml < 0:
            errors.append("swing_start_max_torque_pml darf nicht negativ sein.")

        if self.swing_end_max_torque_pml < 0:
            errors.append("swing_end_max_torque_pml darf nicht negativ sein.")

        if self.swing_start_max_torque_pml > self.swing_length:
            errors.append("swing_start_max_torque_pml darf nicht größer als swing_length sein.")

        if self.swing_end_max_torque_pml > self.swing_length:
            errors.append("swing_end_max_torque_pml darf nicht größer als swing_length sein.")

        if self.load_mode not in ("profile", "skier"):
            errors.append(f"simulation.load_mode '{self.load_mode}' ist ungültig (erlaubt: profile, skier).")

        if self.weight_kg <= 0:
            errors.append("weight_kg muss größer als 0 sein.")

        if not (0.1 <= self.force_scale <= 3.0):
            errors.append("simulation.force_scale muss zwischen 0.1 und 3.0 liegen.")

        if not (0.0 <= self.route_slope_factor <= 1.5):
            errors.append("simulation.route_slope_factor muss zwischen 0 und 1.5 liegen.")

        if not (0.5 <= self.power_scale <= 5.0):
            errors.append("simulation.power_scale muss zwischen 0.5 und 5 liegen.")

        if not (0.0 <= self.equipment_kg <= 20.0):
            errors.append("simulation.equipment_kg muss zwischen 0 und 20 liegen.")

        if not (1.0 <= self.diagonal_from_slope_percent <= 20.0):
            errors.append("user.diagonal_from_slope_percent muss zwischen 1 und 20 liegen.")

        if not (0.0 <= self.diagonal_hysteresis_percent < self.diagonal_from_slope_percent):
            errors.append("user.diagonal_hysteresis_percent muss ≥ 0 und kleiner als die Umschaltschwelle sein.")

        if not (5.0 <= self.recovery_torque_pct <= 100.0):
            errors.append("control.recovery_torque_pct muss zwischen 5 und 100 liegen.")

        if not (0.2 <= self.diagonal_arm_share <= 1.0):
            errors.append("simulation.diagonal_arm_share muss zwischen 0.2 und 1.0 liegen.")
        if not (0.5 <= self.diagonal_power_factor <= 3.0):
            errors.append("simulation.diagonal_power_factor muss zwischen 0.5 und 3 liegen.")
        if not (0.0 <= self.downhill_feel_floor <= 1.0):
            errors.append("simulation.downhill_feel_floor muss zwischen 0 und 1 liegen.")
        if not (0.0 <= self.end_pull_torque_pct <= 60.0):
            errors.append("control.end_pull_torque_pct muss zwischen 0 und 60 liegen.")

        if not (0.0 <= self.feel_mu <= 0.2):
            errors.append("simulation.feel_mu muss zwischen 0 und 0.2 liegen.")

        if not (1.0 <= self.max_force_step_n <= 100.0):
            errors.append("simulation.max_force_step_n muss zwischen 1 und 100 liegen.")

        if self.swing_start_max_torque_pml > self.swing_end_max_torque_pml:
            errors.append("swing_start_max_torque_pml darf nicht größer als swing_end_max_torque_pml sein.")

        return errors

    def validate_geometry(self):
        errors = self.geometry_errors()
        if errors:
            raise ValueError("\n".join(errors))
