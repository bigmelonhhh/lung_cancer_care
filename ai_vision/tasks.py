try:
    from celery import shared_task
except ImportError:  # pragma: no cover - fallback for environments without celery installed
    def shared_task(*_args, **_kwargs):
        def decorator(func):
            func.delay = func
            return func

        return decorator

from ai_vision.services import extract_report_image


@shared_task(name="ai_vision.extract_report_image")
def extract_report_image_task(image_id: int) -> dict:
    return extract_report_image(image_id)
