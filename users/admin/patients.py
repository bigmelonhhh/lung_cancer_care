"""Patient admin configuration."""

from __future__ import annotations

from datetime import timedelta

from django import forms
from django.contrib import admin
from django.contrib.admin.views.main import ChangeList
from django.db.models import DateTimeField, IntegerField, OuterRef, Q, Subquery
from django.utils import timezone
from django.utils.html import format_html

from core.models import choices as core_choices
from core.service import tasks as task_service
from health_data.models import MedicalHistory
from market.models import Order
from users import choices
from users.models import PatientProfile


class PatientProfileFilterForm(forms.Form):
    name = forms.CharField(label="姓名", required=False)
    gender = forms.ChoiceField(
        label="性别",
        required=False,
        choices=[("", "全部")] + list(choices.Gender.choices),
    )
    birth_start = forms.DateField(
        label="出生开始",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    birth_end = forms.DateField(
        label="出生结束",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    disease = forms.CharField(label="当前病程", required=False)
    hospital = forms.CharField(label="所在医院", required=False)
    doctor_name = forms.CharField(label="管理医生", required=False)
    registered_start = forms.DateField(
        label="注册开始",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    registered_end = forms.DateField(
        label="注册结束",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    purchase_start = forms.DateField(
        label="购买开始",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    purchase_end = forms.DateField(
        label="购买结束",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    membership_level = forms.ChoiceField(
        label="会员等级",
        required=False,
        choices=(
            ("", "全部"),
            ("active", "付费会员"),
            ("expired", "已过期"),
            ("none", "免费会员"),
        ),
    )
    studio = forms.CharField(label="绑定工作室", required=False)
    sales = forms.CharField(label="CRC专员", required=False)


class PatientProfileChangeList(ChangeList):
    """Ignore custom query params for filtering."""

    def get_filters_params(self, params=None):
        lookup_params = super().get_filters_params(params=params)
        lookup_params.pop("patient_id", None)
        lookup_params.pop("name", None)
        lookup_params.pop("gender", None)
        lookup_params.pop("birth_start", None)
        lookup_params.pop("birth_end", None)
        lookup_params.pop("disease", None)
        lookup_params.pop("hospital", None)
        lookup_params.pop("doctor_name", None)
        lookup_params.pop("registered_start", None)
        lookup_params.pop("registered_end", None)
        lookup_params.pop("purchase_start", None)
        lookup_params.pop("purchase_end", None)
        lookup_params.pop("membership_level", None)
        lookup_params.pop("studio", None)
        lookup_params.pop("sales", None)
        return lookup_params


@admin.register(PatientProfile)
class PatientProfileAdmin(admin.ModelAdmin):
    change_list_template = "admin/users/patient_profile/change_list.html"
    list_display = (
        "patient_name",
        "gender_display",
        "birth_date_display",
        "current_disease_display",
        "registered_date",
        "membership_level_display",
        "membership_start_display",
        "membership_end_display",
        "hospital_display",
        "studio_display",
        "doctor_display",
        "sales_display",
    )
    list_display_links = None
    list_per_page = 20
    search_fields = ("name", "phone")

    def get_changelist(self, request, **kwargs):
        return PatientProfileChangeList

    def get_filter_form(self, request):
        if not hasattr(request, "_patientprofile_filter_form"):
            request._patientprofile_filter_form = PatientProfileFilterForm(request.GET or None)
        return request._patientprofile_filter_form

    def get_queryset(self, request):
        latest_history = MedicalHistory.objects.filter(patient_id=OuterRef("pk")).order_by(
            "-created_at"
        )
        latest_order = Order.objects.filter(
            patient_id=OuterRef("pk"),
            status=Order.Status.PAID,
            paid_at__isnull=False,
        ).order_by("-paid_at")
        qs = (
            super()
            .get_queryset(request)
            .select_related("doctor", "doctor__studio", "sales")
            .prefetch_related("doctor__sales")
            .annotate(
                latest_tumor_diagnosis=Subquery(
                    latest_history.values("tumor_diagnosis")[:1]
                ),
                latest_clinical_diagnosis=Subquery(
                    latest_history.values("clinical_diagnosis")[:1]
                ),
                last_paid_at=Subquery(
                    latest_order.values("paid_at")[:1], output_field=DateTimeField()
                ),
                last_paid_duration=Subquery(
                    latest_order.values("product__duration_days")[:1],
                    output_field=IntegerField(),
                ),
            )
        )
        form = self.get_filter_form(request)
        if form.is_valid():
            data = form.cleaned_data
            if data.get("name"):
                qs = qs.filter(name__icontains=data["name"])
            if data.get("gender"):
                qs = qs.filter(gender=data["gender"])
            if data.get("birth_start"):
                qs = qs.filter(birth_date__gte=data["birth_start"])
            if data.get("birth_end"):
                qs = qs.filter(birth_date__lte=data["birth_end"])
            if data.get("disease"):
                qs = qs.filter(
                    Q(latest_tumor_diagnosis__icontains=data["disease"])
                    | Q(latest_clinical_diagnosis__icontains=data["disease"])
                )
            if data.get("hospital"):
                qs = qs.filter(doctor__hospital__icontains=data["hospital"])
            if data.get("doctor_name"):
                qs = qs.filter(doctor__name__icontains=data["doctor_name"])
            if data.get("registered_start"):
                qs = qs.filter(created_at__date__gte=data["registered_start"])
            if data.get("registered_end"):
                qs = qs.filter(created_at__date__lte=data["registered_end"])
            if data.get("purchase_start"):
                qs = qs.filter(last_paid_at__date__gte=data["purchase_start"])
            if data.get("purchase_end"):
                qs = qs.filter(last_paid_at__date__lte=data["purchase_end"])
            if data.get("studio"):
                qs = qs.filter(doctor__studio__name__icontains=data["studio"])
            if data.get("sales"):
                qs = qs.filter(
                    Q(sales__name__icontains=data["sales"])
                    | Q(doctor__sales__name__icontains=data["sales"])
                )
                qs = qs.distinct()
            if data.get("membership_level"):
                qs = self._filter_by_membership(qs, data["membership_level"])
        return qs

    def changelist_view(self, request, extra_context=None):
        form = self.get_filter_form(request)
        selected_id = request.GET.get("patient_id")
        extra_context = extra_context or {}
        extra_context.update(
            {
                "filter_form": form,
                "selected_patient_id": selected_id,
                "title": "患者列表",
            }
        )
        response = super().changelist_view(request, extra_context=extra_context)
        if hasattr(response, "context_data"):
            context = response.context_data
            context["filter_form"] = form
            selected_patient = None
            selected_history = None
            adherence_display = None
            if selected_id:
                cl = context.get("cl")
                if cl:
                    selected_patient = next(
                        (obj for obj in cl.result_list if str(obj.pk) == str(selected_id)),
                        None,
                    )
                if not selected_patient:
                    selected_patient = self.get_queryset(request).filter(pk=selected_id).first()
                if selected_patient:
                    selected_history = (
                        MedicalHistory.objects.filter(patient=selected_patient)
                        .order_by("-created_at")
                        .first()
                    )
                    adherence_display = self._build_adherence_display(selected_patient)
            context.update(
                {
                    "selected_patient": selected_patient,
                    "selected_medical_history": selected_history,
                    "selected_current_disease": self._current_disease(
                        selected_patient, selected_history
                    )
                    if selected_patient
                    else "-",
                    "selected_membership_level": self._membership_level(selected_patient)
                    if selected_patient
                    else "-",
                    "selected_membership_start": self._membership_start_date(selected_patient)
                    if selected_patient
                    else None,
                    "selected_membership_end": self._membership_end_date(selected_patient)
                    if selected_patient
                    else None,
                    "selected_hospital": self._hospital_name(selected_patient)
                    if selected_patient
                    else "-",
                    "selected_studio": self._studio_name(selected_patient)
                    if selected_patient
                    else "-",
                    "selected_doctor": self._doctor_name(selected_patient)
                    if selected_patient
                    else "-",
                    "selected_sales": self._sales_names(selected_patient)
                    if selected_patient
                    else "-",
                    "adherence_display": adherence_display or {},
                }
            )
        return response

    @admin.display(description="姓名", ordering="name")
    def patient_name(self, obj):
        url = f"?patient_id={obj.pk}"
        return format_html('<a href="{}">{}</a>', url, obj.name or "-")

    @admin.display(description="性别", ordering="gender")
    def gender_display(self, obj):
        return obj.get_gender_display()

    @admin.display(description="出生日期", ordering="birth_date")
    def birth_date_display(self, obj):
        return obj.birth_date or "-"

    @admin.display(description="当前病程")
    def current_disease_display(self, obj):
        return self._current_disease(obj, None)

    @admin.display(description="注册日期", ordering="created_at")
    def registered_date(self, obj):
        return obj.created_at

    @admin.display(description="会员等级")
    def membership_level_display(self, obj):
        return self._membership_level(obj)

    @admin.display(description="购买会员日期")
    def membership_start_display(self, obj):
        return self._membership_start_date(obj) or "-"

    @admin.display(description="会员到期日期")
    def membership_end_display(self, obj):
        return self._membership_end_date(obj) or "-"

    @admin.display(description="所在医院")
    def hospital_display(self, obj):
        return self._hospital_name(obj)

    @admin.display(description="绑定工作室")
    def studio_display(self, obj):
        return self._studio_name(obj)

    @admin.display(description="管理医生")
    def doctor_display(self, obj):
        return self._doctor_name(obj)

    @admin.display(description="CRC专员")
    def sales_display(self, obj):
        return self._sales_names(obj)

    def has_delete_permission(self, request, obj=None):
        return False

    def _current_disease(self, obj, history):
        if history:
            return history.tumor_diagnosis or history.clinical_diagnosis or "-"
        return (
            getattr(obj, "latest_tumor_diagnosis", None)
            or getattr(obj, "latest_clinical_diagnosis", None)
            or "-"
        )

    def _membership_start_date(self, obj):
        if not obj:
            return None
        paid_at = getattr(obj, "last_paid_at", None)
        if not paid_at:
            return None
        return timezone.localtime(paid_at).date()

    def _membership_end_date(self, obj):
        if not obj:
            return None
        paid_at = getattr(obj, "last_paid_at", None)
        duration = getattr(obj, "last_paid_duration", None) or 0
        if not paid_at or duration <= 0:
            return None
        start_date = timezone.localtime(paid_at).date()
        return start_date + timedelta(days=duration - 1)

    def _membership_level(self, obj):
        if not obj:
            return "-"
        end_date = self._membership_end_date(obj)
        if not end_date:
            return "免费会员"
        today = timezone.localdate()
        if end_date >= today:
            return "付费会员"
        return "已过期"

    def _hospital_name(self, obj):
        if obj and obj.doctor and obj.doctor.hospital:
            return obj.doctor.hospital
        return "-"

    def _studio_name(self, obj):
        if obj and obj.doctor and obj.doctor.studio and obj.doctor.studio.name:
            return obj.doctor.studio.name
        return "-"

    def _doctor_name(self, obj):
        if obj and obj.doctor and obj.doctor.name:
            return obj.doctor.name
        return "-"

    def _sales_names(self, obj):
        if obj and obj.sales and obj.sales.name:
            return obj.sales.name
        if obj and obj.doctor:
            names = [sale.name for sale in obj.doctor.sales.all() if sale.name]
            if names:
                return ", ".join(sorted(set(names)))
        return "-"

    def _filter_by_membership(self, qs, level):
        records = list(qs.values_list("id", "last_paid_at", "last_paid_duration"))
        if not records:
            return qs.none()
        end_dates = {}
        for patient_id, paid_at, duration in records:
            if not paid_at or not duration:
                continue
            start_date = timezone.localtime(paid_at).date()
            end_date = start_date + timedelta(days=duration - 1)
            end_dates[patient_id] = end_date
        today = timezone.localdate()
        if level == "active":
            matched_ids = [pid for pid, end in end_dates.items() if end >= today]
        elif level == "expired":
            matched_ids = [pid for pid, end in end_dates.items() if end < today]
        else:
            matched_ids = [pid for pid, _, _ in records if pid not in end_dates]
        return qs.filter(pk__in=matched_ids)

    def _format_rate(self, metrics):
        if not metrics or metrics.get("rate") is None:
            return "-"
        return f"{metrics['rate']:.0%}"

    def _build_adherence_display(self, patient):
        medication = task_service.get_adherence_metrics(
            patient_id=patient.id,
            adherence_type=core_choices.PlanItemCategory.MEDICATION,
        )
        monitoring = task_service.get_adherence_metrics(
            patient_id=patient.id,
            adherence_type=task_service.MONITORING_ADHERENCE_ALL,
        )
        checkup = task_service.get_adherence_metrics(
            patient_id=patient.id,
            adherence_type=core_choices.PlanItemCategory.CHECKUP,
        )
        questionnaire = task_service.get_adherence_metrics(
            patient_id=patient.id,
            adherence_type=core_choices.PlanItemCategory.QUESTIONNAIRE,
        )
        other_total = checkup["total"] + questionnaire["total"]
        other_completed = checkup["completed"] + questionnaire["completed"]
        other_rate = None if other_total == 0 else other_completed / other_total
        return {
            "medication": self._format_rate(medication),
            "monitoring": self._format_rate(monitoring),
            "other": "-" if other_rate is None else f"{other_rate:.0%}",
        }
