import os

from .base import *  # noqa: F403

DEBUG = False

if not ALLOWED_HOSTS:  # noqa: F405
    raise ValueError("ALLOWED_HOSTS must be set when DJANGO_ENV=production")

if SECRET_KEY.startswith("django-insecure-"):  # noqa: F405
    raise ValueError("DJANGO_SECRET_KEY must be set to a strong random value in production")

SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", default=True)  # noqa: F405
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", default=True)  # noqa: F405
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", default=True)  # noqa: F405

_default_hsts_seconds = 31536000
SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", str(_default_hsts_seconds)))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True)  # noqa: F405
SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", default=False)  # noqa: F405

CSRF_TRUSTED_ORIGINS = parse_csv_env("CSRF_TRUSTED_ORIGINS")  # noqa: F405
if not CSRF_TRUSTED_ORIGINS:
    inferred_origins = []
    if WEB_BASE_URL.startswith("https://"):  # noqa: F405
        inferred_origins.append(WEB_BASE_URL)  # noqa: F405
    for host in ALLOWED_HOSTS:  # noqa: F405
        cleaned = host.lstrip(".")
        if cleaned in {"*", "localhost", "127.0.0.1"}:
            continue
        inferred_origins.append(f"https://{cleaned}")
    CSRF_TRUSTED_ORIGINS = dedupe_keep_order(inferred_origins)  # noqa: F405
