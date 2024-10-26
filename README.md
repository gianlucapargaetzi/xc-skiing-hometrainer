# How to install the Software for XC-FIT v1.0
## Prerequisites
This Project was designed to be run on a Raspberry Pi 5 using the provided Raspberry Pi OS.

The Software was tested with Kernel 6.6

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

3. From now on, if you want to work with any xc-skiing sources, make sure your environment is activated.
    ```
    source <cloned-repository>/.venv/bin/activate
    ```
    > You should see a **(.venv)** prefixing your console commands

4. Start the User Interface
    ```
    cd <cloned-repository>/src/webgui
    python3 WebGUIBackend.py
    ```
5. Open the GUI in your browser at `127.0.0.1:5000`

### How this repository works