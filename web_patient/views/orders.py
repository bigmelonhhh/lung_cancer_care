from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone

from market.models import Order
from users.decorators import check_patient, require_membership
from users.models import PatientRelation


@login_required
@check_patient
@require_membership
def patient_orders(request):
    """
    【页面说明】患者端订单列表 `/p/orders/`。
    【模板】`web_patient/patient_orders.html`，展示购买的服务与有效期信息。
    """

    patient = request.patient

    if not patient:
        return redirect("web_patient:onboarding")

    queryset = (
        Order.objects.select_related("product")
        .filter(patient=patient)
        .order_by("-created_at")
    )

    orders = []
    for order in queryset:
        is_paid = order.status == Order.Status.PAID and order.paid_at
        valid_start = valid_end = None
        if is_paid:
            paid_at = timezone.localtime(order.paid_at)
            valid_start = paid_at.date()
            duration_days = max(order.product.duration_days or 0, 1)
            valid_end = valid_start + timedelta(days=duration_days - 1)

        orders.append(
            {
                "order": order,
                "is_paid": bool(is_paid),
                "is_pending": order.status == Order.Status.PENDING,
                "valid_start": valid_start,
                "valid_end": valid_end,
            }
        )

    studio_name = None
    doctor = getattr(patient, "doctor", None)
    if doctor and getattr(doctor, "studio", None):
        studio_name = doctor.studio.name

    return render(
        request,
        "web_patient/patient_orders.html",
        {
            "orders": orders,
            "studio_name": studio_name,
        },
    )
