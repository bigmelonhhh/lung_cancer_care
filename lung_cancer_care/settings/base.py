"""
Base Django settings shared by all environments.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

from .logging import build_logging_config

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def parse_csv_env(var_name):
    return [item.strip() for item in os.getenv(var_name, "").split(",") if item.strip()]


def env_bool(var_name, default=False):
    value = os.getenv(var_name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def dedupe_keep_order(items):
    seen = set()
    result = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


DJANGO_ENV = os.getenv("DJANGO_ENV", "development").lower()
LOG_LEVEL = os.getenv("DJANGO_LOG_LEVEL", "INFO").upper()
ALLOWED_HOSTS = parse_csv_env("ALLOWED_HOSTS")

WEB_BASE_URL = os.getenv("WEB_BASE_URL", "http://localhost:8001").rstrip("/")
TEST_PATIENT_ID = os.getenv("TEST_PATIENT_ID") or None
WECHAT_VERIFY_FILENAME = (os.getenv("WECHAT_VERIFY_FILENAME") or "").strip()
WECHAT_DAILY_TASK_TEMPLATE_ID = os.getenv(
    "WECHAT_DAILY_TASK_TEMPLATE_ID",
    "aNWInDmh-VbJsLXqxF2Msf7uLbFROre76xw_951y2V0",
)

# SECURITY WARNING: keep the secret key used in production secret!
_default_secret_key = "django-insecure-$idrzn%uju_mymafcg9h76u&bq!*2uhs2-yk-!(9i#!+e5x*3="
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", _default_secret_key)

DEBUG = True

# HTTPS/security defaults; production overrides strict values.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = env_bool("USE_X_FORWARDED_HOST", default=True)
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", default=False)
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", default=False)
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", default=False)
SECURE_CONTENT_TYPE_NOSNIFF = env_bool("SECURE_CONTENT_TYPE_NOSNIFF", default=True)
SECURE_REFERRER_POLICY = os.getenv("SECURE_REFERRER_POLICY", "same-origin")
X_FRAME_OPTIONS = os.getenv("X_FRAME_OPTIONS", "DENY")
SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False)
SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", default=False)
CSRF_TRUSTED_ORIGINS = parse_csv_env("CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "lung_cancer_care.admin_site.LungCancerAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_extensions",
    "users",
    "web_doctor",
    "web_sales",
    "web_patient",
    "market",
    "wx",
    "health_data",
    "regions",
    "business_support",
    "core",
    "patient_alerts",
    "chat",
]

ADMIN_APP_ORDER = [
    "core",
    "users",
    "web_doctor",
    "web_patient",
    "market",
    "web_sales",
    "health_data",
    "business_support",
    "wx",
    "regions",
    "patient_alerts",
    "chat",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "users.middleware.PatientContextMiddleware",
    "lung_cancer_care.middleware.RequestLogMiddleware",
]

ROOT_URLCONF = "lung_cancer_care.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "lung_cancer_care.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.getenv("MYSQL_DATABASE"),
        "USER": os.getenv("MYSQL_USER"),
        "PASSWORD": os.getenv("MYSQL_PASSWORD"),
        "HOST": os.getenv("MYSQL_HOST"),
        "PORT": os.getenv("MYSQL_PORT"),
    }
}

REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = os.getenv("REDIS_PORT", "6379")
REDIS_DB = os.getenv("REDIS_DB", "0")
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
_redis_auth = f":{REDIS_PASSWORD}@" if REDIS_PASSWORD else ""

CELERY_BROKER_URL = f"redis://{_redis_auth}{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"

EMBED_URL = os.getenv("EMBED_URL", "")
EMBED_TOKEN = os.getenv("EMBED_TOKEN", "")

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": f"redis://{_redis_auth}{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}",
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [
    BASE_DIR / "static",
]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "/media/"

CERTS_DIR = BASE_DIR / "certs"
WX_APPID = os.getenv("WX_APPID")
WX_PAY_PUB_KEY_PATH = CERTS_DIR / "wx_v2_certs/pub_key.pem"
WX_PAY_CERT_PATH = CERTS_DIR / "wx_v2_certs/apiclient_cert.pem"
WX_PAY_KEY_PATH = CERTS_DIR / "wx_v2_certs/apiclient_key.pem"
WX_MCH_ID = os.getenv("WX_MCH_ID")
WX_MCH_KEY = os.getenv("WX_MCH_KEY")
WX_PAY_NOTIFY_URL = os.getenv("WX_PAY_NOTIFY_URL")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "users.CustomUser"

LOGIN_URL = "web_doctor:login"
LOGIN_REDIRECT_URL = "web_doctor:doctor_dashboard"
LOGOUT_REDIRECT_URL = "web_doctor:login"

LOGGING = build_logging_config(LOG_DIR, LOG_LEVEL)

SMS_CONFIG = {
    "API_URL": os.environ.get("SMS_API_URL", "http://124.172.234.157:8180/service.asmx/SendMessageStr"),
    "ORG_ID": os.environ.get("SMS_ORG_ID"),
    "USERNAME": os.environ.get("SMS_USERNAME"),
    "PASSWORD": os.environ.get("SMS_PASSWORD"),
    "SIGNATURE": "【岱劲信息】",
}

SMARTWATCH_CONFIG = {
    "APP_KEY": os.environ.get("SMARTWATCH_APP_KEY"),
    "APP_SECRET": os.environ.get("SMARTWATCH_APP_SECRET"),
    "API_BASE_URL": "https://apibff.scheartmed.com",
}

# shell_plus
SHELL_PLUS = "ipython"
SHELL_PLUS_IMPORTS = []
SHELL_PLUS_PRINT_SQL = False
