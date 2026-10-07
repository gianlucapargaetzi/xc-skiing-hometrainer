#!/bin/bash

PROJECT_DIR=~/xc-skiing-hometrainer
VENV_DIR="$PROJECT_DIR/.venv"
PYTHON_SCRIPT="$PROJECT_DIR/src/webgui/x-ski.py"

echo "Wechsel in das Projektverzeichnis: $PROJECT_DIR"
cd "$PROJECT_DIR/src/webgui" || { echo "Fehler: Verzeichnis $PROJECT_DIR/src/webgui nicht gefunden."; exit 1; }

echo "Aktivieren der virtuellen Umgebung..."
source "$VENV_DIR/bin/activate" || { echo "Fehler: Virtuelle Umgebung nicht gefunden."; exit 1; }

if [ -f "$PYTHON_SCRIPT" ]; then
  echo "Starte das Python-Programm im IIC-Modus: $PYTHON_SCRIPT"
  LOG_DIR="$PROJECT_DIR/logs"
  mkdir -p "$LOG_DIR"
  LOG_FILE="$LOG_DIR/x-ski_iic_$(date +%Y-%m-%d_%H-%M-%S).log"
  echo "Konsolenausgabe wird mitgeschrieben: $LOG_FILE"
  # -u: ungepuffert, damit das Log live mitläuft
  python -u "$PYTHON_SCRIPT" --controller iic 2>&1 | tee "$LOG_FILE"
else
  echo "Fehler: Python-Skript $PYTHON_SCRIPT nicht gefunden."
fi

echo "Beende die virtuelle Umgebung..."
deactivate