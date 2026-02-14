import os

_django_env = os.getenv("DJANGO_ENV", "development").lower()

if _django_env in {"production", "prod"}:
    from .production import *  # noqa: F401,F403
elif _django_env in {"development", "dev"}:
    from .development import *  # noqa: F401,F403
else:
    raise ValueError(
        f"Unsupported DJANGO_ENV '{_django_env}'. Use 'development' or 'production'."
    )
