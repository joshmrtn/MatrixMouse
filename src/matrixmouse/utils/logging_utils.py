"""
matrixmouse/utils/logging_utils.py

Application-wide logging utilities.

Responsible for setting up global logging configuration.
"""

import logging
import sys
from pathlib import Path


def setup_logging(log_level: str, log_to_file: bool, repo_root: Path):
    """Configures root logger based on application settings.

    Should be called in main.py before other modules start working.

    Args:
        log_level (str): The log level to set the logger to.
        log_to_file (bool): whether file logging is enabled.
        repo_root (Path): Path to the repository root. 
    """
    # Convert log_level to the logging level object or use INFO as fallback.
    log_level = getattr(logging, log_level, logging.INFO)

    # Set up logging format.
    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)s] [%(name)s] - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Clear existing handlers to prevent duplicates.
    if root_logger.handlers:
        root_logger.handlers.clear()

    # Console handler (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handler
    if log_to_file:
        log_path = repo_root / ".matrixmouse" / "agent.log"
        file_handler = logging.FileHandler(log_path)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
        logging.info(f"File logging enabled: {log_path}")

    logging.info(f"Logging initialized.")

