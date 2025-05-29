#!/bin/bash

set -e

sudo apt-get update
sudo apt-get install -y git

git clone https://github.com/RobuDan/pi-sound-logger.git