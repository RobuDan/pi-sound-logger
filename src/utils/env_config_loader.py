import os
import logging
from dotenv import load_dotenv

# Resolve the path of .env file located in project root inside config/ folder 
base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
env_path = os.path.join(base_dir, "config", ".env")

# Load environment variables from .env file
load_dotenv(dotenv_path=env_path)

class Config:
    """
    Centralized configuration loader.
    Loads required values from the config/.env file and raises errors if values are missing.
    """

    # MongoDB
    MONGO_URL = os.getenv("MONGO_URL") 
    MONGO_USERNAME = os.getenv("MONGO_USERNAME")
    MONGO_PASSWORD = os.getenv("MONGO_PASSWORD")
    DEVICE_STATUS_DB = os.getenv("DEVICE_STATUS_DB") # Shared MongoDB database used by all devices to store metadata

    # MySQL
    MYSQL_USER = os.getenv("MYSQL_USER")
    MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
    MYSQL_HOST = os.getenv("MYSQL_HOST")
    MYSQL_PORT = os.getenv("MYSQL_PORT")

    # Device (For more details, see config/README.md)
    SERIAL_NUMBER = os.getenv("SERIAL_NUMBER")

    @staticmethod
    def validate():
        """
        Ensures that all required environment variables are defined.
        """
        required = {
            "MONGO_URL": Config.MONGO_URL,
            "DEVICE_STATUS_DB": Config.DEVICE_STATUS_DB,
            "MYSQL_HOST": Config.MYSQL_HOST,
            "MYSQL_USER": Config.MYSQL_USER,
            "MYSQL_PASSWORD": Config.MYSQL_PASSWORD,
            "MYSQL_PORT": Config.MYSQL_PORT,
            "SERIAL_NUMBER": Config.SERIAL_NUMBER,
        }

        missing = [key for key, value in required.items() if not value]
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
        
def validate_or_exit():
    """
    Validates config and stops the app early if anything critical is missing.
    """
    try:
        Config.validate()
        logging.info("Configuration validated successfully.")
    except ValueError as e:
        logging.error(f"Configuration error: {e}")
        raise SystemExit(1)
