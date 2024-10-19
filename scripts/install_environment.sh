#!/bin/bash

cd ..
REPO_DIR=$PWD
VENV_DIR=$PWD/.venv/


if [ -d "$VENV_DIR" ]; then
    echo "Environment already exists!"
    exit 0
fi

python3 -m venv .venv
source $VENV_DIR/bin/activate
python3 -m pip install customtkinter
python3 -m pip install tk
python3 -m pip install numpy
python3 -m pip install matplotlib
python3 -m pip install ezgpx
python3 -m pip install python-socketio
python3 -m pip install Flask-SocketIO
python3 -m pip install minimalmodbus
python3 -m pip install pyModbusTCP