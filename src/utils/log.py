import os
import logging
from logging.handlers import RotatingFileHandler

class FlushRotatingFileHandler(RotatingFileHandler):
    """
    
    """
    def emit(self, record):
        super().emit(record)
        self.flush()
        if hasattr(self.stream, 'fileno'):
            try:
                os.fsync(self.stream.fileno())
            except OSError:
                pass

def setup_logging():
    """
    Sets up file-based logging with rotation.
    All logs (INFO and above) are written to 'logs/app.log',
    with rotation after 5MB and up to 5 backup files.
    """
    # Determine path to 'logs/' directory two levels above current file (project root/logs/)
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    log_directory = os.path.join(base_dir, "logs")
    os.makedirs(log_directory, exist_ok=True)

    # Define log file path
    log_file_path = os.path.join(log_directory, "app.log")

    # Reset existing handlers
    root_logger = logging.getLogger()
    if root_logger.handlers:
        for handler in root_logger.handlers:
            root_logger.removeHandler(handler)

    # Set root log level
    root_logger.setLevel(logging.INFO)

    # Configure rotating file handler
    rotating_handler = FlushRotatingFileHandler(
        log_file_path, maxBytes=5 * 1024 * 1024, backupCount=5
    )
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    rotating_handler.setFormatter(formatter)

    root_logger.addHandler(rotating_handler)
