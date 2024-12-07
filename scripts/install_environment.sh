#!/bin/bash
Color_Off='\033[0m'       # Text Reset

# Regular Colors
Black='\033[0;30m'        # Black
Red='\033[0;31m'          # Red
Green='\033[0;32m'        # Green
Yellow='\033[0;33m'       # Yellow
Blue='\033[0;34m'         # Blue
Purple='\033[0;35m'       # Purple
Cyan='\033[0;36m'         # Cyan
White='\033[0;37m'        # White

# Bold
BBlack='\033[1;30m'       # Black
BRed='\033[1;31m'         # Red
BGreen='\033[1;32m'       # Green
BYellow='\033[1;33m'      # Yellow
BBlue='\033[1;34m'        # Blue
BPurple='\033[1;35m'      # Purple
BCyan='\033[1;36m'        # Cyan
BWhite='\033[1;37m'       # White





cd ..
REPO_DIR=$PWD
VENV_DIR=$PWD/.venv/


if [ -d "$VENV_DIR" ]; then
    echo -e "${BGreen}Environment already exists. Aborting Script.${Color_Off}"
    exit 0
fi

echo -e "${BGreen}Creating a virtual python environment.${Color_Off}"
python3 -m venv .venv
source $VENV_DIR/bin/activate

echo -e "${BGreen}Installing necessary packages.${Color_Off}"
python3 -m pip install customtkinter
python3 -m pip install tk
python3 -m pip install numpy
python3 -m pip install matplotlib
python3 -m pip install scipy
python3 -m pip install ezgpx
python3 -m pip install python-socketio
python3 -m pip install Flask-SocketIO
python3 -m pip install minimalmodbus
python3 -m pip install pyModbusTCP
python3 -m pip install bleak
python3 -m pip install asyncio
python3 -m pip install PyYAML
python3 -m pip install pysoem
