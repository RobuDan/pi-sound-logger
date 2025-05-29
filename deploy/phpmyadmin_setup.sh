#!/bin/bash
# Installs PHP, phpMyAdmin, and Apache for MariaDB administration on Raspberry Pi

set -e

cd "$(dirname "$0")"

echo "[INFO] Installing Apache, PHP, and phpMyAdmin..."

# Install Apache and PHP
sudo apt-get update
sudo apt-get install -y apache2 php php-mysql

# Install phpMyAdmin (non-interactive, recommends apache2, no prompt)
sudo apt-get install -y phpmyadmin

# Ensure Apache is enabled and running
sudo systemctl enable apache2
sudo systemctl restart apache2

# Ensure the phpmyadmin include is in apache2.conf
APACHE_CONF="/etc/apache2/apache2.conf"
PHPMYADMIN_INCLUDE="Include /etc/phpmyadmin/apache.conf"

if ! grep -Fxq "$PHPMYADMIN_INCLUDE" "$APACHE_CONF"; then
    echo "$PHPMYADMIN_INCLUDE" | sudo tee -a "$APACHE_CONF" > /dev/null
    echo "[INFO] Added phpMyAdmin config include to $APACHE_CONF"
else
    echo "[INFO] phpMyAdmin include already present in $APACHE_CONF"
fi

# Symlink phpmyadmin to /var/www/html for easy browser access
if [ ! -L "/var/www/html/phpmyadmin" ]; then
    sudo ln -s /usr/share/phpmyadmin /var/www/html/phpmyadmin
    echo "[INFO] Symlinked /usr/share/phpmyadmin to /var/www/html/phpmyadmin"
else
    echo "[INFO] Symlink already exists."
fi

# Restart Apache again to ensure all changes are live
sudo systemctl restart apache2

# Print local IP so user knows where to connect
echo
echo "[SUCCESS] phpMyAdmin is installed and configured."
echo "Visit: http://$(hostname -I | awk '{print $1}')/phpmyadmin"
echo "Login using your MariaDB credentials (e.g., user: root, password: as set in variables.env)."

# Warn about security (optional for production)
echo "[NOTICE] For production, change the root password, restrict remote access, and/or create a limited DB user!"
