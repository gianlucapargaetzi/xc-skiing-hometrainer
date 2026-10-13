import os
import sys
from pathlib import Path

# src/webgui auf den Pfad, damit "from Utils..." wie im Programm funktioniert
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Tests sehen nie die Maschinen-Einstellungen dieses Geräts (maschine.json)
os.environ["X_SKI_MACHINE_FILE"] = "/nonexistent/maschine.json"
