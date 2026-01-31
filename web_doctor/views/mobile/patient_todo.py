import logging

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from patient_alerts.services.todo_list import TodoListService
from users import choices
from web_doctor.views.workspace import _get_workspace_patients

logger = logging.getLogger(__name__)


def _json_error(message: str, *, status: int) -> JsonResponse:
    return JsonResponse({"success": False, "message": message}, status=status)


def _parse_int_param(
    value: str | None,
    *,
    name: str,
    default: int,
    min_value: int,
    max_value: int | None = None,
) -> int:
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 参数无效") from exc
    if parsed < min_value:
        raise ValueError(f"{name} 参数无效")
    if max_value is not None and parsed > max_value:
        raise ValueError(f"{name} 参数无效")
    return parsed


@require_GET
def mobile_patient_todo_list(request: HttpRequest) -> HttpResponse:
    try:
        if not getattr(request.user, "is_authenticated", False):
            return _json_error("未登录", status=401)

        if getattr(request.user, "user_type", None) not in (
            choices.UserType.DOCTOR,
            choices.UserType.ASSISTANT,
        ):
            return _json_error("无权访问该资源", status=403)

        page = _parse_int_param(
            request.GET.get("page"),
            name="page",
            default=1,
            min_value=1,
        )
        pagesize = _parse_int_param(
            request.GET.get("pagesize"),
            name="pagesize",
            default=10,
            min_value=1,
            max_value=50,
        )

        patient_id = request.GET.get("patient_id")
        patient = None
        patient_no = None
        if patient_id:
            pid = _parse_int_param(
                patient_id,
                name="patient_id",
                default=0,
                min_value=1,
            )
            patients_qs = _get_workspace_patients(request.user, query=None).select_related(
                "user"
            )
            patient = patients_qs.filter(pk=pid).first()
            if patient is None:
                return _json_error("未找到患者", status=404)
            patient_no = f"P{patient.id:06d}"

        todo_page = TodoListService.get_todo_page(
            user=request.user,
            page=page,
            size=pagesize,
            status="all",
            patient_id=getattr(patient, "id", None) or None,
        )

        if request.headers.get("HX-Request"):
            return render(
                request,
                "web_doctor/mobile/partials/patient_todo_list_content.html",
                {
                    "todo_page": todo_page,
                    "page": page,
                    "pagesize": pagesize,
                    "patient": patient,
                    "patient_no": patient_no,
                },
            )

        return render(
            request,
            "web_doctor/mobile/patient_todo_list.html",
            {
                "todo_page": todo_page,
                "page": page,
                "pagesize": pagesize,
                "patient": patient,
                "patient_no": patient_no,
            },
        )
    except ValueError as exc:
        logger.warning("移动端患者待办参数错误: %s", str(exc))
        return _json_error(str(exc), status=400)
    except Exception as exc:
        logger.error("移动端患者待办加载失败: %s", str(exc), exc_info=True)
        return _json_error("系统异常，请稍后重试", status=500)
