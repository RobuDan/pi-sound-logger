# Deployment Configuration

This folder contains deployment automation scripts and configuration files for provisioning a Raspberry Pi with all dependencies required by the `pi-sound-logger` application.


---

##  `variables.env` – Deployment Variables

This file contains all configurable settings used by the `deploy.sh` master script and its child scripts.

---

###  MariaDB Configuration

Defines access credentials and connection details for the MySQL server.
Those should be matching the values from within `.env`
```bash
MYSQL_HOST=localhost         # Host of the MySQL server 
MYSQL_USER=root              # Root or admin-level user
MYSQL_PASSWORD=password      # Password for the MySQL user
MYSQL_PORT=3306              # Default MySQL port
```

---

###  Wi-Fi Configuration

Used to preconfigure network connectivity during setup.

```bash
WIFI_SSID=YourSSID           # SSID of your wireless network
WIFI_PASS=YourPassword       # Password for the wireless network
WIFI_COUNTRY=RO              # Country code for regional Wi-Fi config (e.g., RO, US, DE)
```

---

###  Python & Project Paths

Locations and naming used for installing Python and creating the virtual environment.

```bash
PROJECT_ROOT=/home/pi/pi-sound-logger   # Root path of the cloned project
VENV_NAME=venv                          # Name of the virtual environment folder
```

---

###  systemd Service Configuration

Settings used to create and register a persistent system service for the application.

```bash
SERVICE_NAME=pi-sound-logger                      # systemd service name
SERVICE_DESC=Pi Sound Logger Service              # Description of the service
SERVICE_USER=pi                                   # User under which the service runs
PYTHON_BIN=/home/pi/pi-sound-logger/venv/bin/python  # Python binary used by the service
APP_ENTRY=src/main.py                             # Application entrypoint
```

---

##  Notes

* This file is sourced during deployment (`deploy.sh`) and must be present in the `deploy/` directory.
* If `variables.env` is missing or incomplete, the script will halt and prompt for correction.
* The values should be reviewed and updated to match your system setup before deployment.
