import logging
import sys

_FORMAT = logging.Formatter(
    fmt="%(asctime)s %(levelname)-7s %(name)s — %(message)s", datefmt="%H:%M:%S"
)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def setup_logging(level: str = "INFO", json_output: bool = False) -> None:
    handler = logging.StreamHandler(sys.stdout)
    if json_output:
        import json as _json
        from datetime import UTC, datetime

        class _JsonFormatter(logging.Formatter):
            def format(self, record: logging.LogRecord) -> str:
                return _json.dumps(
                    {
                        "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
                        "level": record.levelname.lower(),
                        "logger": record.name,
                        "message": record.getMessage(),
                    },
                    default=str,
                )

        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(_FORMAT)
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
