#!/bin/bash
# MariaDB setup: always set root password and plugin; no DB or extra user created.
set -e

cd "$(dirname "$0")"

if [ -f variables.env ]; then
    source variables.env
fi

# Defaults for dev if not set
MYSQL_HOST="${MYSQL_HOST:-localhost}"
MYSQL_USER="${MYSQL_USER:-root}"
MYSQL_PASSWORD="${MYSQL_PASSWORD:-password}"
MYSQL_PORT="${MYSQL_PORT:-3306}"

echo "[INFO] Installing MariaDB..."
sudo apt-get update
sudo apt-get install -y default-mysql-server

sudo systemctl enable mariadb
sudo systemctl restart mariadb

echo "[INFO] Securing MariaDB..."

# Set root password and authentication plugin to mysql_native_password
echo "[INFO] Setting root@localhost authentication method and password..."
sudo mariadb -e "ALTER USER 'root'@'localhost' IDENTIFIED VIA mysql_native_password USING PASSWORD('${MYSQL_PASSWORD}'); FLUSH PRIVILEGES;"

# If user is not root, create as global superuser
if [ "$MYSQL_USER" != "root" ]; then
    echo "[INFO] Creating global admin user: $MYSQL_USER"
    sudo mariadb -u root -p"${MYSQL_PASSWORD}" <<EOF
CREATE USER IF NOT EXISTS '${MYSQL_USER}'@'${MYSQL_HOST}' IDENTIFIED BY '${MYSQL_PASSWORD}';
GRANT ALL PRIVILEGES ON *.* TO '${MYSQL_USER}'@'${MYSQL_HOST}' WITH GRANT OPTION;
FLUSH PRIVILEGES;
EOF
fi

# Remove anonymous users, disable remote root, remove test DB
sudo mariadb -u root -p"${MYSQL_PASSWORD}" <<EOF
DELETE FROM mysql.user WHERE User='';
DELETE FROM mysql.user WHERE User='root' AND Host!='localhost';
DROP DATABASE IF EXISTS test;
DELETE FROM mysql.db WHERE Db='test' OR Db='test\\_%';
FLUSH PRIVILEGES;
EOF

# Ensure event_scheduler=ON (needed for events/triggers)
CONF_FILE="/etc/mysql/mariadb.conf.d/50-server.cnf"
if ! grep -q "^event_scheduler=ON" "$CONF_FILE"; then
    sudo sed -i '/^\[mysqld\]/a event_scheduler=ON' "$CONF_FILE"
    echo "[INFO] event_scheduler=ON added to $CONF_FILE"
fi

sudo systemctl restart mariadb

SCHEDULER_STATUS=$(sudo mysql -u root -p"${MYSQL_PASSWORD}" -NBe "SHOW VARIABLES LIKE 'event_scheduler';" | awk '{print $2}')
if [[ "$SCHEDULER_STATUS" == "ON" ]]; then
    echo "[SUCCESS] event_scheduler is ON."
fi

echo "[ALL DONE] MariaDB setup complete!"
