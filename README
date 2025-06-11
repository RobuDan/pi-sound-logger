# pi-sound-logger

![Repo Size](https://img.shields.io/github/repo-size/RobuDan/pi-sound-logger)
![Last Commit](https://img.shields.io/github/last-commit/RobuDan/pi-sound-logger)
![Issues](https://img.shields.io/github/issues/RobuDan/pi-sound-logger)
![License](https://img.shields.io/badge/License-PolyForm%20NC%201.0.0-red)
![Made with Python](https://img.shields.io/badge/Made%20with-Python-1f425f.svg)
![Platform](https://img.shields.io/badge/Platform-Raspberry%20Pi-red)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-blue?logo=linkedin&logoColor=white)](https://www.linkedin.com/in/marian-daniel-robu-3b7469227/)


##  Table of Contents

- [Description](#description)
- [Problem](#problem)
- [Motivation](#motivation)
- [Architecture Overview](#architecture-overview)
- [Key Features](#key-features)
- [Hardware Components](#hardware-components)
- [Live Platform](#live-platform)
- [Installation](#installation)
- [Development Notes](#development-notes)
- [Author / Contact](#author--contact)
- [License](#license)

---

##  Description

pi-sound-logger is a Raspberry Pi-based environmental monitoring system designed for **long-term noise observation**, in urban areas, quiet zones, and places where understanding noise pollution trends is essential for improving quality of life. It captures acoustic data, aggregates its according to environmental standards and synchronizes with a remote MongoDB database for long-term analysis. All components are built for resilience and autonomous operation on Raspberry Pi devices.

The goal of the system is to provide **precise, historical noise data** to support improvements in urban design and combat acoustic pollution.

---

##  Problem

Urban noise pollution is a growing issue, affecting not only homes but also public parks, city centers, and public transit routes. While professional systems provide powerful monitoring capabilities, they are **cost-prohibitive**, with end-unit prices often exceeding **€10,000**.

Such costs make city-scale deployment unrealistic in many cases, especially when multiple nodes are needed.

---

##  Motivation

This project stems from a previously developed high-end system using a **BK2255** device and its Open Interface API ([library link](https://github.com/hbk-world/Open-Interface-for-Sound-Level-Meter)). That solution enabled parallel extraction of acoustic parameters, state monitoring, and spectrum analysis. However, due to hardware costs, a more scalable solution was needed.

The current system substitutes the BK2255 ([device link](https://www.bksv.com/en/instruments/handheld/sound-level-meters/2255-series)) with a **Convergence Instruments NSRT-mk4** USB audio device ([device link](https://convergenceinstruments.com/product/sound-level-meter-data-logger-with-type-1-microphone-nsrt_mk4_dev//)), reducing costs by **~20x**, while preserving modular design and reliable operation.

Despite reduced parameter variety, it provides **practical, deployable monitoring** with LAeq and LAF metrics, sufficient for most environmental use cases.

> Note: Documentation for the full architecture, capabilities, and insights of the original BK2255-based system - developed as a professional solution prior to this project - is planned. 
---

##  Architecture Overview

The application is structured into modular components:
- Acquisition: Captures raw acoustic and audio data from the NSRT device.
- Aggregation: Computes values for time intervals between 1-min and 24-hour metrics, including LAeq,  LAF percentiles and LDEN (as per current development).
- Database: Dual integration with local MySQL (for raw aggregated data) and MongoDB Atlas (for cloud synchronization).
- Monitoring: Tracks device usb presence stops the acquisition and reinitializes acquisition upon reconnection.
- Utils: Provides utility functions for accessing .env and .json configuration values across the application in a consistent and centralized way.

- Async Orchestration: Operations are non-blocking using Python's asyncio, ensuring fault-tolerant execution even in cases of network or device failure.
For a deeper technical breakdown, refer to the [/docs/README.md](/docs/README.md) folder
---

##  Key Features

- Continuous monitoring of **LAeq** and **LAF** acoustic parameters A/C/Z weighting (only one active at a time)
- Aggregates environmental indicators (e.g., **LDEN**) per European and **SR6161** Romanian standards
- Stores data locally in **MySQL**, syncs to **MongoDB Atlas**
- Handles both **real-time transmission** and **offline buffering**
- Automatic device recovery and reconnection after disconnection
- Modular, testable, and production-ready async Python backend
- Developed as a **solo project** to demonstrate full-stack IoT competence

---

##  Hardware Components

- **Raspberry Pi 5**
- **NSRT-mk4_Dev** by Convergence Instruments ([library](https://github.com/xanderhendriks/nsrt-mk3-dev))
- **USB Audio Extension** for NSRT device ([product link](https://convergenceinstruments.com/product/audio-usb-interface-option/))
- **Mobile Router** for data sync and remote updates

---

##  Live Platform

This device integrates into a larger multi-node acoustic monitoring system (one of the 3 devices supported). A frontend visualization and reporting platform currently under development, but with core functionalities already implemented:

🔗 [https://monitorizare.envi.ro](https://monitorizare.envi.ro)  
🔒 Login required. Contact the author for demo access.
 [ Author / Contact ](#author--contact)

---
##  Installation
This project was designed to run on a Raspberry Pi 5 and includes an automated deployment pipeline using shell scripts.

Before you begin, make sure you have:

- A Raspberry Pi (recommended: Pi 5) running Raspberry Pi OS  
- Internet connectivity (via Ethernet or Wi-Fi)  
- A compatible Convergence Instruments device connected (NSRT-mk4 + USB Audio Option)  

---

###  Prepare Configuration Files

Start by cloning the repository and entering the project directory:

```bash
git clone https://github.com/RobuDan/pi-sound-logger.git
```
```bash
cd pi-sound-logger
```
Then, prepare the environment files:

```bash
# Copy and edit the environment variables
cp config/.env.example .env
```
> Note: Customize .env according to your deployment needs. Details on each variable are available in [config/README.md](config/README.md).
```bash
# Copy and customize deployment settings
cp deploy/variables.env.example deploy/variables.env
```
Edit variables.env to reflect your:

- MariaDB credentials

- Wi-Fi SSID and password

- System username

- Desired systemd service name

### Fix File Permissions 

```bash
# Convert Windows line endings to Unix format 
sudo apt-get install -y dos2unix
find ./deploy -name "*.sh" -exec dos2unix {} \;

# Make all deployment scripts executable
chmod +x ./deploy/*.sh
```

### Run the Deployment Script
```bash
cd deploy
./deploy.sh
```
This script performs the following tasks:

- Installs MariaDB and secures the root password

- Configures Wi-Fi access

- Installs Apache, PHP, and phpMyAdmin

- Builds Python 3.10, sets up a virtual environment, and installs dependencies

- Registers a systemd service for the logger application

- Finalizes your Pi’s acoustic monitoring setup

### Post-Installation
To check that services are running:
```bash
# Check your custom systemd logger service
sudo systemctl status <your_service_name>.service

# Check the Wi-Fi service
sudo systemctl status wpa_supplicant.service
```

To access the database interface via browser:
```bash
http://<your_pi_ip_address>/phpmyadmin
```
Once configured, the application will automatically launch on boot and begin collecting acoustic data.

---

##  Development Notes

This project was developed entirely as a solo effort, from initial design to final deployment. It builds upon my prior experience developing a high-performance acoustic monitoring system using a Brüel & Kjær 2255 (BK2255) device, which provided full-spectrum data acquisition and parameter extraction through a proprietary API.

The current version retains the architectural principles of that original system, while simplifying hardware requirements to enable cost-effective deployment using a Convergence Instruments NSRT-mk4-dev device.

Throughout development, I prioritized:

- Modular code organization for maintainability and scalability
- Asynchronous execution to support real-time performance
- Resilience and fault tolerance, especially for device availability and network interruptions
- Separation of concerns between acquisition, storage, and synchronization layers
- Emphasis was placed on modular structure, data integrity, and robust operation for long-term, unattended use.

The project was originally built as part of work conducted activity, and was successfully deployed as a fully functional, reliable monitoring system — not just a demo or public showcase.

---

## Author / Contact

**Robu Marian-Daniel**  
📧 Email: [marian-daniel.robu@outlook.com](mailto:marian-daniel.robu@outlook.com)  
🔗 LinkedIn: [marian-daniel-robu](https://www.linkedin.com/in/marian-daniel-robu-3b7469227/)  
📂 GitHub: [RobuDan](https://github.com/RobuDan)

---

## License

This project is source-available under the  
[PolyForm Noncommercial License 1.0.0](LICENSE.txt).

Commercial use (including SaaS, resale, or internal business use)  
requires a separate written agreement with the author.

-  You may **view, run, and use** the code for **personal or noncommercial** purposes.
-  Commercial use, modification, or redistribution is **strictly prohibited**.

**Important**: Large-scale or repeated deployments — even if not-for-profit — are **not considered personal use** and are **not permitted** under this license without written permission.

**Disclaimer**: This software is provided *as is*, without any warranties or guarantees. Use it at your own risk.

See the [LICENSE.txt](./LICENSE.txt) file for full legal terms.