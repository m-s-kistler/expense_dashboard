from __future__ import annotations

from datetime import datetime
import logging
import os
from pathlib import Path


LOG_DIR = Path("logs")
LOG_ENV_VAR = "EXPENSE_DASHBOARD_LOG_FILE"


def configure_logging() -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    if LOG_ENV_VAR not in os.environ:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        os.environ[LOG_ENV_VAR] = str(
            LOG_DIR / f"expense_dashboard_{timestamp}_pid{os.getpid()}.log"
        )

    log_path = Path(os.environ[LOG_ENV_VAR])
    root_logger = logging.getLogger()

    if not any(
        isinstance(handler, logging.FileHandler)
        and Path(handler.baseFilename) == log_path.resolve()
        for handler in root_logger.handlers
    ):
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] %(message)s"
        )
        try:
            file_handler = logging.FileHandler(log_path, encoding="utf-8")
        except PermissionError:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_path = LOG_DIR / f"expense_dashboard_{timestamp}_pid{os.getpid()}_app.log"
            os.environ[LOG_ENV_VAR] = str(log_path)
            file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
        root_logger.setLevel(logging.INFO)
        logging.getLogger("streamlit").setLevel(logging.WARNING)

    return log_path
