"""Patient admin configuration with HTMX preview."""

from django import forms
from django.contrib import admin
from django.db.models import Q
from django.template.response import TemplateResponse
from django.urls import path, reverse

from users import choices
from users.models import PatientProfile

try:
    from health_data.models import MedicalHistory
except ImportError:  # pragma: no cover - optional app
    MedicalHistory = None


class PatientFilterForm(forms.Form):
    q = forms.CharField(label="姓名/手机号", required=False)
    gender = forms.ChoiceField(
        label="性别",
        required=False,
        choices=[("", "全部")] + list(choices.Gender.choices),
    )
    birth_start = forms.DateField(label="出生开始", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    birth_end = forms.DateField(label="出生结束", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    doctor_name = forms.CharField(label="管理医生", required=False)
    sales_name = forms.CharField(label="销售专员", required=False)
    date_range_start = forms.DateField(label="注册开始", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    date_range_end = forms.DateField(label="注册结束", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    purchase_start = forms.DateField(label="购买开始", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    purchase_end = forms.DateField(label="购买结束", required=False, widget=forms.DateInput(attrs={"type": "date"}))


class PatientProfileAdmin(admin.ModelAdmin):
    change_list_template = "admin/users/patient_profile/change_list.html"
    list_display = (
        "name",
        "gender",
        "birth_date",
        "age_display",
        "created_at",
        "service_status_display",
        "doctor",
        "sales",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "patient-preview/<int:pk>/",
                self.admin_site.admin_view(self.patient_preview_view),
                name="users_patient_preview",
            )
        ]
        return custom + urls

    def patient_preview_view(self, request, pk):
        patient = PatientProfile.objects.select_related("user", "doctor", "sales").filter(pk=pk).first()
        histories = []
        if patient and MedicalHistory:
            histories = MedicalHistory.objects.filter(patient_id=patient.pk).order_by("-record_date")[:5]
        context = {
            "patient": patient,
            "opts": self.model._meta,
            "medical_histories": histories,
            "adherence_metrics": {
                "medication": "86%",
                "monitoring": "88%",
                "followup": "90%",
            },
        }
        return TemplateResponse(request, "admin/users/patient_profile/preview.html", context)

    def get_filter_form(self, request):
        if not hasattr(request, "_patient_filter_form"):
            request._patient_filter_form = PatientFilterForm(request.GET or None)
        return request._patient_filter_form

    def get_queryset(self, request):
        qs = (
            super()
            .get_queryset(request)
            .select_related("doctor", "sales")
        )
        form = self.get_filter_form(request)
        if form.is_valid():
            data = form.cleaned_data
            if data.get("q"):
                qs = qs.filter(Q(name__icontains=data["q"]) | Q(phone__icontains=data["q"]))
            if data.get("gender") != "":
                qs = qs.filter(gender=data["gender"])
            if data.get("birth_start"):
                qs = qs.filter(birth_date__gte=data["birth_start"])
            if data.get("birth_end"):
                qs = qs.filter(birth_date__lte=data["birth_end"])
            if data.get("doctor_name"):
                qs = qs.filter(doctor__name__icontains=data["doctor_name"])
            if data.get("sales_name"):
                qs = qs.filter(sales__name__icontains=data["sales_name"])
            if data.get("date_range_start"):
                qs = qs.filter(created_at__date__gte=data["date_range_start"])
            if data.get("date_range_end"):
                qs = qs.filter(created_at__date__lte=data["date_range_end"])
            if data.get("purchase_start"):
                qs = qs.filter(membership_expire_at__date__gte=data["purchase_start"])
            if data.get("purchase_end"):
                qs = qs.filter(membership_expire_at__date__lte=data["purchase_end"])
        return qs

    def changelist_view(self, request, extra_context=None):
        form = self.get_filter_form(request)
        preview_base = reverse("admin:users_patient_preview", args=[0])
        if preview_base.endswith("0/"):
            preview_base = preview_base[:-2]
        extra_context = extra_context or {}
        extra_context.update(
            {
                "filter_form": form,
                "preview_url_base": preview_base,
            }
        )
        response = super().changelist_view(request, extra_context=extra_context)
        if hasattr(response, "context_data"):
            response.context_data["filter_form"] = form
            response.context_data["preview_url_base"] = preview_base
        return response

    def age_display(self, obj):
        return obj.age or "-"

    age_display.short_description = "年龄"

    def service_status_display(self, obj):
        return obj.get_service_status_display()

    service_status_display.short_description = "服务等级"


admin.site.register(PatientProfile, PatientProfileAdmin)
