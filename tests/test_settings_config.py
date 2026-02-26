import contextlib
import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SETTINGS_PREFIX = "lung_cancer_care.settings"
_MISSING = object()


def _clear_settings_modules():
    for name in list(sys.modules):
        if name == SETTINGS_PREFIX or name.startswith(f"{SETTINGS_PREFIX}."):
            sys.modules.pop(name, None)


@contextlib.contextmanager
def _temp_env(**updates):
    backup = {key: os.environ.get(key, _MISSING) for key in updates}
    try:
        for key, value in updates.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, old_value in backup.items():
            if old_value is _MISSING:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value


def _import_settings(module_name):
    _clear_settings_modules()
    return importlib.import_module(module_name)


class SettingsLoaderTests(unittest.TestCase):
    def test_selector_loads_development_settings(self):
        with _temp_env(
            DJANGO_ENV="development",
            DJANGO_SECRET_KEY=None,
            ALLOWED_HOSTS=None,
            WEB_BASE_URL=None,
            CSRF_TRUSTED_ORIGINS=None,
        ):
            settings = _import_settings("lung_cancer_care.settings")
        self.assertTrue(settings.DEBUG)

    def test_selector_loads_production_settings(self):
        with _temp_env(
            DJANGO_ENV="production",
            DJANGO_SECRET_KEY="very-strong-random-secret-key-1234567890",
            ALLOWED_HOSTS="zencare.imht.site",
            WEB_BASE_URL="https://zencare.imht.site",
            CSRF_TRUSTED_ORIGINS=None,
        ):
            settings = _import_settings("lung_cancer_care.settings")
        self.assertFalse(settings.DEBUG)
        self.assertTrue(settings.SECURE_SSL_REDIRECT)

    def test_selector_rejects_unknown_env(self):
        with _temp_env(DJANGO_ENV="staging"):
            with self.assertRaisesRegex(ValueError, "Unsupported DJANGO_ENV"):
                _import_settings("lung_cancer_care.settings")


class ProductionGuardTests(unittest.TestCase):
    def test_production_requires_allowed_hosts(self):
        with _temp_env(
            DJANGO_SECRET_KEY="very-strong-random-secret-key-1234567890",
            ALLOWED_HOSTS="",
            WEB_BASE_URL="https://zencare.imht.site",
        ):
            with self.assertRaisesRegex(ValueError, "ALLOWED_HOSTS must be set"):
                _import_settings("lung_cancer_care.settings.production")

    def test_production_rejects_default_secret_key(self):
        with _temp_env(
            DJANGO_SECRET_KEY="django-insecure-for-test-only",
            ALLOWED_HOSTS="zencare.imht.site",
            WEB_BASE_URL="https://zencare.imht.site",
        ):
            with self.assertRaisesRegex(ValueError, "DJANGO_SECRET_KEY must be set"):
                _import_settings("lung_cancer_care.settings.production")

    def test_production_infers_csrf_trusted_origins(self):
        with _temp_env(
            DJANGO_SECRET_KEY="very-strong-random-secret-key-1234567890",
            ALLOWED_HOSTS="zencare.imht.site,localhost,.api.zencare.imht.site,*",
            WEB_BASE_URL="https://zencare.imht.site",
            CSRF_TRUSTED_ORIGINS=None,
        ):
            settings = _import_settings("lung_cancer_care.settings.production")

        self.assertEqual(
            settings.CSRF_TRUSTED_ORIGINS,
            ["https://zencare.imht.site", "https://api.zencare.imht.site"],
        )


class SettingsHelperTests(unittest.TestCase):
    def test_base_helper_functions(self):
        with _temp_env(
            DJANGO_SECRET_KEY="very-strong-random-secret-key-1234567890",
            ALLOWED_HOSTS="zencare.imht.site",
            WEB_BASE_URL="https://zencare.imht.site",
        ):
            base = _import_settings("lung_cancer_care.settings.base")

        with _temp_env(TEST_BOOL="TrUe", TEST_CSV=" a, b ,, c "):
            self.assertTrue(base.env_bool("TEST_BOOL"))
            self.assertEqual(base.parse_csv_env("TEST_CSV"), ["a", "b", "c"])
        self.assertEqual(base.dedupe_keep_order(["a", "b", "a", "c", "b"]), ["a", "b", "c"])


class LoggingConfigTests(unittest.TestCase):
    def test_build_logging_config_in_normal_mode(self):
        module = _import_settings("lung_cancer_care.settings.logging")
        config = module.build_logging_config(Path("/tmp"), "WARNING")

        self.assertEqual(config["root"]["level"], "WARNING")
        self.assertEqual(
            config["handlers"]["file"]["filename"],
            Path("/tmp") / "lung_cancer_care.log",
        )
        self.assertEqual(
            config["handlers"]["file"]["class"],
            "concurrent_log_handler.ConcurrentTimedRotatingFileHandler",
        )
        self.assertEqual(config["handlers"]["console"]["class"], "logging.StreamHandler")

    def test_build_logging_config_in_test_mode(self):
        module = _import_settings("lung_cancer_care.settings.logging")
        with patch.object(sys, "argv", ["manage.py", "test"]):
            config = module.build_logging_config(Path("/tmp"), "INFO")

        self.assertEqual(config["handlers"]["console"]["class"], "logging.NullHandler")
        self.assertEqual(config["handlers"]["file"]["class"], "logging.NullHandler")


if __name__ == "__main__":
    unittest.main()
