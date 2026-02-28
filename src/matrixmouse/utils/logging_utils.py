"""
matrixmouse/utils/logging_utils.py

Application-wide logging utilities.

Responsible for setting up global logging configuration.
"""

import logging
import sys
from matrixmouse.config import MatrixMouseConfig
from pathlib import Path


def setup_logging(repo_root: Path):
    """Configures root logger based on application settings.

    Should be called once in main.py before other modules start working.

    Args:
        repo_root (Path): The path to the repository root.
    """
    config = MatrixMouseConfig

    # Get log level from application config.
    log_to_file = MatrixMouseConfig.log_to_file
    log_level_str = MatrixMouseConfig.log_level.upper()
    log_level = getattr(logging, log_level_str, logging.INFO)

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

    logging.info(f"Logging initialized. Level: {log_level_str}")

