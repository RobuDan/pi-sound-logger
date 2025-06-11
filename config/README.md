#  Configuration

This folder contains the configuration files required to run the `pi-sound-logger` application. These files should be customized before deployment.

---

##  `.env` – Environment Variables

The `.env` file is used to define environment-specific variables for database access, device identity, and retention logic. A sample file is provided as `.env.example`. Create your own `.env` file at the root of the project and fill in the appropriate values.

###  Sections

####  MongoDB Configuration

Used for syncing data and device status monitoring.

```bash
MONGO_URL=         # Your MongoDB cluster URL
MONGO_USERNAME=    # MongoDB user with write access
MONGO_PASSWORD=    # Corresponding password
DEVICE_STATUS_DB=  # A database where the device syncs its status and metadata
```

####  MySQL Configuration

Used for local data storage and aggregation before syncing.

```bash
MYSQL_HOST=         # Usually localhost
MYSQL_USER=         # MySQL username
MYSQL_PASSWORD=     # Password for MySQL
MYSQL_PORT=3306     # Default MySQL port
MySQL_DATA_RETENTION=60  # Data retention period in days
```

####  Device Identity

```bash
SERIAL_NUMBER=yourSerialNumber
```

⚠️ `SERIAL_NUMBER` is manually defined. It is not tied to any hardware UID (for consistency reasons), and follows my custom naming convention across the system (e.g., for platform indexing, monitoring, and visualization).

---

##  `parameters.json` – Device Configuration

This file determines what data types are collected from the device:

```json
{
  "AcousticSequences": ["LAeq", "LAF", "LAFmin", "LAFmax"],
  "SpectrumSequences": [],
  "AudioSequences": ["157"]
}
```

###  Notes:

* These parameter names reflect internal system conventions specific to this project.
* `"AudioSequences": ["157"]` is a custom identifier used by the system to enable audio file collection.
* Spectrum data is not collected in this version.

---

##  Final Notes

These configuration files are manually edited per deployment. They are not standardized across hardware but reflect a custom internal convention designed for flexible device integration within the system.

Ensure these files are reviewed and updated before running the application.
