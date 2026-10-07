#!/bin/bash

PROJECT_DIR=~/xc-skiing-hometrainer
VENV_DIR="$PROJECT_DIR/.venv"
# Startmenü: zuerst den Modus wählen (Skifahrer / Belastungsprofil / Intervall),
# danach ersetzt sich der Launcher durch x-ski.py im gewählten Modus.
PYTHON_SCRIPT="$PROJECT_DIR/src/webgui/launcher.py"

echo "Wechsel in das Projektverzeichnis: $PROJECT_DIR"
cd "$PROJECT_DIR/src/webgui" || { echo "Fehler: Verzeichnis $PROJECT_DIR/src/webgui nicht gefunden."; exit 1; }

echo "Aktivieren der virtuellen Umgebung..."
source "$VENV_DIR/bin/activate" || { echo "Fehler: Virtuelle Umgebung nicht gefunden."; exit 1; }

if [ -f "$PYTHON_SCRIPT" ]; then
  echo "Starte das x-ski Startmenü: $PYTHON_SCRIPT"
  LOG_DIR="$PROJECT_DIR/logs"
  mkdir -p "$LOG_DIR"
  LOG_FILE="$LOG_DIR/x-ski_$(date +%Y-%m-%d_%H-%M-%S).log"
  echo "Konsolenausgabe wird mitgeschrieben: $LOG_FILE"
  # -u: ungepuffert, damit das Log live mitläuft
  python -u "$PYTHON_SCRIPT" "$@" 2>&1 | tee "$LOG_FILE"
else
  echo "Fehler: Python-Skript $PYTHON_SCRIPT nicht gefunden."
fi

echo "Beende die virtuelle Umgebung..."
deactivate