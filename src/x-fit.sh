#!/bin/bash

# Pfad zum Projekt
PROJECT_DIR=~/xc-skiing-hometrainer

# Pfad zur virtuellen Umgebung
VENV_DIR="$PROJECT_DIR/.venv"

# Python-Version (anpassen, falls benötigt)
PYTHON="python3"

# Python-Skript, das gestartet werden soll
PYTHON_SCRIPT="$PROJECT_DIR/src/webgui/Test.py"

# Wechsel in das Projektverzeichnis
echo "Wechsel in das Projektverzeichnis: $PROJECT_DIR"
cd "$PROJECT_DIR/src/webgui" || { echo "Fehler: Verzeichnis $PROJECT_DIR nicht gefunden."; exit 1; }

# Aktivieren der virtuellen Umgebung
echo "Aktivieren der virtuellen Umgebung..."
source "$VENV_DIR/bin/activate"


# Starten des Python-Programms
if [ -f "$PYTHON_SCRIPT" ]; then
  echo "Starte das Python-Programm: $PYTHON_SCRIPT"
  python "$PYTHON_SCRIPT"
else
  echo "Fehler: Python-Skript $PYTHON_SCRIPT nicht gefunden."
fi

# Deaktivieren der virtuellen Umgebung
echo "Beende die virtuelle Umgebung..."
deactivate


