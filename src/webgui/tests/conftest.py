import sys
from pathlib import Path

# src/webgui auf den Pfad, damit "from Utils..." wie im Programm funktioniert
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
