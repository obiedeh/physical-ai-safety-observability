import json
import logging
from datetime import UTC, datetime
from typing import Any


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(level=level, format="%(message)s", force=True)


def log_event(logger: logging.Logger, message: str, **fields: Any) -> None:
    logger.info(
        json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "level": "info",
                "logger": logger.name,
                "message": message,
                **fields,
            },
            default=str,
            sort_keys=True,
        )
    )
