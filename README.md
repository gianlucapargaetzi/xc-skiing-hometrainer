# How to install the Software for XC-FIT v1.0
## Prerequisites
This Project was designed to be run on a Raspberry Pi 5 using the provided Raspberry Pi OS.

The Software was tested with Kernel 6.6 and 6.12.

## Install the Software Stack
To install the GUI and control backend, follow the steps below.
1. Clone this repository
    ```
    git clone https://github.com/gianlucapargaetzi/xc-skiing-hometrainer.git
    ```

2. The python sources are running in a virtual environment, which needs to be installed.
    ```
    cd <cloned-repository>/scripts
    ./install_environment.sh
    ```

3. Zugangsdaten anlegen (E-Mail-Versand, Strava). Diese werden **nicht** versioniert:
    ```
    cd <cloned-repository>
    cp .env.example .env
    chmod 600 .env
    # .env mit SMTP- und Strava-Zugangsdaten ausfüllen
    ```

4. Start the User Interface
    ```
    src/x-ski.sh        # Startmenü: Streckensimulation (mit Streckenwahl) / Belastungsprofil / Intervall
    src/x-ski_iic.sh    # direkt im Intervall-Modus
    ```
    Im Startmenü wählst du oben das **Profil** (Dateien in `src/webgui/configs/`; das zuletzt geladene bleibt
    aktiv), bearbeitest es im Formular (**Profil** im Kopfbereich) oder legst ein neues an.
    Das Startmenü (`launcher.py`) berührt den Antrieb nicht; nach der Wahl ersetzt es sich durch
    `x-ski.py` im gewählten Modus. Direkt per Kommandozeile:
    ```
    source <cloned-repository>/.venv/bin/activate
    cd <cloned-repository>/src/webgui
    python3 x-ski.py --mode skier --route sertig-classic-21k.gpx
    python3 x-ski.py --mode skier --route sertig-classic-21k.gpx --route-start-km 12.6 --route-end-km 18.2
    python3 x-ski.py --mode profile
    python3 x-ski.py --mode interval
    # optional: --no-browser, --host 127.0.0.1, --config <datei>
    ```

5. Open the GUI in your browser at `127.0.0.1:5000`

Konfigurationsänderungen über die Weboberfläche (`/api/config/save`, `/api/config/activate`,
`/api/reload_config`, `/upload_interval_file`) sind nur direkt am x-ski (localhost) erlaubt.
Mit `X_SKI_ALLOW_REMOTE_CONFIG=1` können sie auch von anderen Geräten im Netz ausgeführt werden.

## Tests
```
cd <cloned-repository>/src/webgui
../../.venv/bin/python -m pytest tests
```

## Strava-Upload
```
cd <cloned-repository>/src/webgui
../../.venv/bin/python Utils/strava_upload.py ../../trainings/skiErg_<datum>.tcx
```
Die Sportart wird dabei als `NordicSki` (Indoor) gesetzt, da Strava sie aus TCX-Dateien nicht übernimmt.

# Code Structure
```
src/
├── x-ski.sh, x-ski_iic.sh          Startskripte
├── intervals/                      Intervallprogramme (*.xciv, YAML)
├── legacy/                         alter, nicht mehr verwendeter Code (nur Referenz)
└── webgui/
    ├── x-ski.py                    Einstiegspunkt: Web-Routen, Trainingsablauf, Regelschleife
    ├── BasicWebGUI.py              Flask/SocketIO-Backend (Singleton) + BackendNode-Basisklasse
    ├── HardwareController/
    │   └── DriveM751.py            Modbus-TCP-Zugriff auf den Nidec M751 (Register, Kalibrierung, Abschalten)
    ├── IntensityController/        Vorgabe der Intensität (Simple = +/- Tasten, Intervall = Programmdatei)
    ├── ValueHandler/Scope.py       Kraft-/Geschwindigkeitskurven und Zusammenfassung ans WebGUI
    ├── Utils/
    │   ├── settings.py             Settings-Dataclass aus der Konfiguration, Geometrieprüfung
    │   ├── config_manager.py       Laden/Speichern der JSON-Konfiguration, Trainingszonen
    │   ├── force_profile.py        positionsabhängige Bremskurve (Double Poling)
    │   ├── stroke_analysis.py      Auswertung pro Zug (Kadenz, Leistung, Energie, Distanz)
    │   ├── zones.py                HF-/Kadenz-Zonen
    │   ├── tcx_export.py           TCX-Export
    │   ├── email_utils.py          Versand der Trainingsdatei per E-Mail
    │   ├── strava_upload.py        Upload zu Strava
    │   ├── credentials.py          Zugangsdaten aus Umgebung / .env
    │   ├── ble_manager.py, ble_power_meter_module.py   BLE-FTMS-Ausgang (MyWhoosh)
    │   └── ant_hr_manager.py       ANT+ Herzfrequenz
    ├── configs/                    Default-Konfiguration
    ├── templates/, static/         Weboberfläche
    └── tests/                      pytest
```

## Ablauf eines Trainings
```mermaid
sequenceDiagram
    participant T as Trainings-Thread (x-ski.py)
    participant D as DriveM751
    participant IC as IntensityController
    participant S as StrokeAnalyzer / Scope
    T->>D: wait_until_ready, Grundeinstellungen
    T->>D: STO aus/ein, calibrate_end_position
    T->>D: Watchdog ein, Drive Enable
    loop alle ~10 ms solange STO aktiv
        T->>D: toggle_watchdog, Position/Speed/Power lesen
        T->>IC: getIntensity()
        T->>D: update_torque(min + Intensität × Profil(Position))
        T->>S: Messpunkt; bei Zugende: Auswertung, WebGUI, BLE, TCX-Datensatz
    end
    T->>D: shutdown() (immer, auch bei Fehlern)
    T->>T: bei Stopp über WebGUI: TCX schreiben, E-Mail, Programmende
```

Gemessene Frequenz der Regelschleife wird alle 30 s auf der Konsole ausgegeben.

## Simulation (Abschnitt `simulation` in der Konfiguration)
Ein virtueller Skifahrer (`Utils/skier_model.py`) berechnet Tempo und Distanz aus
`m·dv/dt = F_vortrieb − µ·m·g·cosθ − m·g·sinθ − ½·ρ·CdA·v²` (Masse `user.weight_kg`, Schnee `user.mu`,
Grundsteigung `user.slope_percent`, Luftwiderstand `simulation.cda_m2`).

| `load_mode` | Widerstand am Seil | Antrieb des virtuellen Skifahrers |
|---|---|---|
| `profile` (Standard) | positionsabhängige Bremskurve × Intensität (bisher) | gemessene Leistung am Seil |
| `skier` | Kopplung an den Skifahrer: Kraft nur, wenn die Hände schneller sind als `hand_speed_ratio × v_ski` | Seilkraft × `hand_speed_ratio` |

Im Skifahrer-Modus wird die Intensität als Steigung interpretiert: 100 % = Grundsteigung,
jedes Prozent mehr/weniger = `slope_per_intensity_pct` (Standard 0.1 → 160 % = +6 %, 70 % = −3 %).
Er braucht `motor_rated_torque_nm` (Typenschild), sonst läuft automatisch der Profil-Modus.

## Strecken (GPX) und Live-Tracking
GPX-Dateien in `src/routes/` ablegen und im Kopfbereich unter **Strecke** auswählen (2D-Karte: in der
Schweiz swisstopo-Winterkarte, sonst OpenTopoMap im Winterlook). Die Steigung kommt dann aus der Strecke
(`simulation.route_slope_factor` dämpft sie, z.B. 0.5); im Skifahrer-Modus verschieben die +/- Tasten sie
zusätzlich. Mit `simulation.route_file` wird eine Strecke beim Start automatisch geladen.

Abschnitt `traccar`: Während eines Trainings auf einer Strecke wird die virtuelle Position alle `interval_s`
Sekunden an Traccar gesendet – `osmand` (HTTP, wie der Traccar Client) oder `eelink` (TCP, 15-stellige IMEI).

Intervalldateien können die Steigung auch direkt vorgeben (gilt in beiden Modi für Tempo/Distanz):
```yaml
anstieg:
  type: duration_block
  duration: 300
  intensity_start: 100
  intensity_end: 100
  slope_start: 0      # Steigung in %, optional
  slope_end: 8
hügel:
  type: interval_block
  on_duration: 60
  off_duration: 60
  block_amount: 4
  on_intensity: 160
  off_intensity: 70
  on_slope: 6         # optional
  off_slope: -2       # optional
```
