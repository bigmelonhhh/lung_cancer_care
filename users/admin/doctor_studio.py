"""Doctor studio admin configuration."""

from django import forms
from django.contrib import admin
from django.contrib.admin.views.main import ChangeList
from django.db.models import Count
from django.utils.html import format_html

from users.models import DoctorStudio


class DoctorStudioFilterForm(forms.Form):
    name = forms.CharField(label="姓名", required=False)
    title = forms.CharField(label="职称", required=False)
    hospital = forms.CharField(label="医院", required=False)
    department = forms.CharField(label="科室", required=False)
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


class DoctorStudioChangeList(ChangeList):
    """Ignore studio_id query param for queryset filtering."""

    def get_filters_params(self, params=None):
        lookup_params = super().get_filters_params(params=params)
        lookup_params.pop("studio_id", None)
        lookup_params.pop("name", None)
        lookup_params.pop("title", None)
        lookup_params.pop("hospital", None)
        lookup_params.pop("department", None)
        lookup_params.pop("registered_start", None)
        lookup_params.pop("registered_end", None)
        return lookup_params


@admin.register(DoctorStudio)
class DoctorStudioAdmin(admin.ModelAdmin):
    change_list_template = "admin/users/doctorstudio/change_list.html"
    list_per_page = 20
    list_display = (
        "expert_name",
        "studio_name",
        "hospital_display",
        "department_display",
        "title_display",
        "sales_display",
        "patient_count_display",
    )
    list_display_links = ("studio_name",)
    actions = None
    ordering = ("owner_doctor__name",)
    fields = ("name", "code", "intro")
    readonly_fields = ("code",)

    def get_changelist(self, request, **kwargs):
        return DoctorStudioChangeList

    def get_filter_form(self, request):
        if not hasattr(request, "_doctorstudio_filter_form"):
            request._doctorstudio_filter_form = DoctorStudioFilterForm(request.GET or None)
        return request._doctorstudio_filter_form

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj=obj)

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        qs = (
            super()
            .get_queryset(request)
            .select_related("owner_doctor")
            .prefetch_related("owner_doctor__sales")
            .annotate(patient_count=Count("owner_doctor__patients", distinct=True))
        )
        form = self.get_filter_form(request)
        if form.is_valid():
            data = form.cleaned_data
            if data.get("name"):
                qs = qs.filter(owner_doctor__name__icontains=data["name"])
            if data.get("title"):
                qs = qs.filter(owner_doctor__title__icontains=data["title"])
            if data.get("hospital"):
                qs = qs.filter(owner_doctor__hospital__icontains=data["hospital"])
            if data.get("department"):
                qs = qs.filter(owner_doctor__department__icontains=data["department"])
            if data.get("registered_start"):
                qs = qs.filter(owner_doctor__created_at__date__gte=data["registered_start"])
            if data.get("registered_end"):
                qs = qs.filter(owner_doctor__created_at__date__lte=data["registered_end"])
        return qs

    def changelist_view(self, request, extra_context=None):
        form = self.get_filter_form(request)
        selected_id = request.GET.get("studio_id")
        extra_context = extra_context or {}
        extra_context.update(
            {
                "filter_form": form,
                "selected_studio_id": selected_id,
                "title": "医生工作室查看",
            }
        )
        response = super().changelist_view(request, extra_context=extra_context)
        if hasattr(response, "context_data"):
            context = response.context_data
            context["filter_form"] = form
            selected_studio = None
            selected_sales_display = "-"
            selected_patient_count = "-"
            if selected_id:
                cl = context.get("cl")
                if cl:
                    selected_studio = next(
                        (obj for obj in cl.result_list if str(obj.pk) == str(selected_id)),
                        None,
                    )
                if not selected_studio:
                    try:
                        selected_studio = self.get_queryset(request).filter(pk=selected_id).first()
                    except (TypeError, ValueError):
                        selected_studio = None
                if selected_studio and selected_studio.owner_doctor:
                    sales_names = [sale.name for sale in selected_studio.owner_doctor.sales.all()]
                    if sales_names:
                        selected_sales_display = ", ".join(sales_names)
                    selected_patient_count = getattr(selected_studio, "patient_count", None)
                    if selected_patient_count is None:
                        selected_patient_count = selected_studio.owner_doctor.patients.count()
            context.update(
                {
                    "selected_studio": selected_studio,
                    "selected_sales_display": selected_sales_display,
                    "selected_patient_count": selected_patient_count,
                    "selected_studio_id": selected_id,
                }
            )
        return response

    @admin.display(description="专家姓名", ordering="owner_doctor__name")
    def expert_name(self, obj):
        name = obj.owner_doctor.name if obj.owner_doctor else "-"
        url = f"?studio_id={obj.pk}"
        return format_html('<a href="{}">{}</a>', url, name)

    @admin.display(description="工作室名称", ordering="name")
    def studio_name(self, obj):
        return obj.name or "-"

    @admin.display(description="所属医院", ordering="owner_doctor__hospital")
    def hospital_display(self, obj):
        if not obj.owner_doctor:
            return "-"
        return obj.owner_doctor.hospital or "-"

    @admin.display(description="所属科室", ordering="owner_doctor__department")
    def department_display(self, obj):
        if not obj.owner_doctor:
            return "-"
        return obj.owner_doctor.department or "-"

    @admin.display(description="职称", ordering="owner_doctor__title")
    def title_display(self, obj):
        if not obj.owner_doctor:
            return "-"
        return obj.owner_doctor.title or "-"

    @admin.display(description="销售专员")
    def sales_display(self, obj):
        if not obj.owner_doctor:
            return "-"
        names = [sale.name for sale in obj.owner_doctor.sales.all()]
        return ", ".join(names) if names else "-"

    @admin.display(description="在管患者数", ordering="patient_count")
    def patient_count_display(self, obj):
        count = getattr(obj, "patient_count", None)
        if count is None:
            return "-"
        return count
