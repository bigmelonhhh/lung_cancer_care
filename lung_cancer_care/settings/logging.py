from pathlib import Path
import sys


def build_logging_config(log_dir: Path, log_level: str = "INFO"):
    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {
                "()": "lung_cancer_care.logging_utils.JsonFormatter",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "json",
            },
            "file": {
                # TimedRotatingFileHandler is not process-safe with gunicorn/celery multi-process writes.
                "class": "concurrent_log_handler.ConcurrentTimedRotatingFileHandler",
                "filename": log_dir / "lung_cancer_care.log",
                "when": "midnight",
                "interval": 1,
                "backupCount": 20,
                "formatter": "json",
                "encoding": "utf-8",
            },
        },
        "root": {
            "handlers": ["console", "file"],
            "level": log_level,
        },
        "loggers": {
            "django": {
                "handlers": ["console", "file"],
                "level": log_level,
                "propagate": False,
            },
            "django.server": {
                "handlers": ["console", "file"],
                "level": "WARNING",
                "propagate": False,
            },
            "django.request": {
                "handlers": ["console", "file"],
                "level": "ERROR",
                "propagate": False,
            },
            "lung_cancer_care": {
                "handlers": ["console", "file"],
                "level": log_level,
                "propagate": False,
            },
            "lung_cancer_care.request": {
                "handlers": ["console", "file"],
                "level": log_level,
                "propagate": False,
            },
            "django.db.backends": {
                "handlers": ["console"],
                "level": "INFO",
                "propagate": False,
            },
        },
    }

    # Avoid noisy console/file logging in tests.
    if "test" in sys.argv:
        config["handlers"]["console"] = {"class": "logging.NullHandler"}
        config["handlers"]["file"] = {"class": "logging.NullHandler"}

    return config
