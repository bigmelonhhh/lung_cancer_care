"""Assistant admin configuration."""

import random
import string

from django import forms
from django.contrib import admin
from django.contrib.admin.views.main import ChangeList
from django.contrib.admin.widgets import FilteredSelectMultiple
from django.db import transaction
from django.db.models import Count
from django.urls import reverse
from django.utils.html import format_html

from users import choices
from users.models import AssistantProfile, CustomUser, DoctorAssistantMap, DoctorProfile


class AssistantProfileFilterForm(forms.Form):
    name = forms.CharField(label="姓名", required=False)
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
    work_phone = forms.CharField(label="工作电话", required=False)
    studio = forms.CharField(label="服务工作室", required=False)


class AssistantProfileChangeList(ChangeList):
    """Ignore custom query params for filtering."""

    def get_filters_params(self, params=None):
        lookup_params = super().get_filters_params(params=params)
        lookup_params.pop("assistant_id", None)
        lookup_params.pop("name", None)
        lookup_params.pop("registered_start", None)
        lookup_params.pop("registered_end", None)
        lookup_params.pop("work_phone", None)
        lookup_params.pop("studio", None)
        return lookup_params


class AssistantDoctorMixin(forms.ModelForm):
    doctors = forms.ModelMultipleChoiceField(
        label="负责医生",
        required=False,
        queryset=DoctorProfile.objects.select_related("user").filter(user__is_active=True),
        widget=FilteredSelectMultiple("负责医生", is_stacked=False),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["doctors"].initial = self.instance.doctors.values_list("pk", flat=True)

    def _sync_doctors(self, instance, selected_doctors):
        current = set(instance.doctors.values_list("pk", flat=True))
        selected = set(selected_doctors.values_list("pk", flat=True))
        to_add = selected - current
        to_remove = current - selected
        if to_add:
            DoctorAssistantMap.objects.bulk_create(
                [
                    DoctorAssistantMap(assistant=instance, doctor_id=doctor_id)
                    for doctor_id in to_add
                ],
                ignore_conflicts=True,
            )
        if to_remove:
            DoctorAssistantMap.objects.filter(
                assistant=instance, doctor_id__in=to_remove
            ).delete()

    def save_m2m(self):
        if not self.instance or not self.instance.pk:
            return
        if getattr(self, "_doctors_synced", False):
            return
        selected = self.cleaned_data.get("doctors", self.fields["doctors"].queryset.none())
        self._sync_doctors(self.instance, selected)
        self._doctors_synced = True

    def save(self, commit=True):
        instance = super().save(commit)
        if commit:
            self.save_m2m()
        return instance


class AssistantCreationForm(AssistantDoctorMixin):
    phone = forms.CharField(label="登录手机号")
    password = forms.CharField(label="初始密码", widget=forms.PasswordInput)

    class Meta:
        model = AssistantProfile
        fields = ["name", "status", "work_phone", "joined_at"]

    def clean_phone(self):
        phone = self.cleaned_data["phone"].strip()
        if CustomUser.objects.filter(phone=phone).exists():
            raise forms.ValidationError("该手机号已被其他账号使用")
        return phone

    def _generate_username(self, phone: str) -> str:
        base = f"assistant_{phone}"
        if not CustomUser.objects.filter(username=base).exists():
            return base
        suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
        return f"{base}_{suffix}"

    def save(self, commit=True):
        phone = self.cleaned_data["phone"]
        password = self.cleaned_data["password"]
        with transaction.atomic():
            username = self._generate_username(phone)
            user = CustomUser(
                username=username,
                phone=phone,
                user_type=choices.UserType.ASSISTANT,
                is_active=True,
                is_staff=False,
            )
            user.set_password(password)
            user.save()

            profile = super().save(commit=False)
            profile.user = user
            if commit:
                profile.save()
                self.save_m2m()
        return profile


class AssistantChangeForm(AssistantDoctorMixin):
    phone = forms.CharField(label="登录手机号")
    is_active = forms.BooleanField(label="账号启用", required=False)
    reset_password = forms.CharField(
        label="重置密码",
        required=False,
        widget=forms.PasswordInput,
        help_text="留空表示不修改密码",
    )

    class Meta:
        model = AssistantProfile
        fields = ["name", "status", "work_phone", "joined_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.user:
            self.fields["phone"].initial = self.instance.user.phone
            self.fields["is_active"].initial = self.instance.user.is_active

    def clean_phone(self):
        phone = self.cleaned_data["phone"].strip()
        user_qs = CustomUser.objects.filter(phone=phone)
        if self.instance and self.instance.user_id:
            user_qs = user_qs.exclude(id=self.instance.user_id)
        if user_qs.exists():
            raise forms.ValidationError("该手机号已被其他账号使用")
        return phone

    def save(self, commit=True):
        profile = super().save(commit=False)
        user = profile.user
        user.phone = self.cleaned_data["phone"]
        user.is_active = self.cleaned_data.get("is_active", True)
        new_password = self.cleaned_data.get("reset_password")
        with transaction.atomic():
            if new_password:
                user.set_password(new_password)
            update_fields = ["phone", "is_active"]
            if new_password:
                update_fields.append("password")
            user.save(update_fields=update_fields)
            if commit:
                profile.save()
        return profile


@admin.register(AssistantProfile)
class AssistantProfileAdmin(admin.ModelAdmin):
    change_list_template = "admin/users/assistantprofile/change_list.html"
    list_display = (
        "assistant_name",
        "registered_phone",
        "status_display",
        "registered_date",
        "work_phone_display",
        "studio_display",
        "doctor_display",
        "patient_count_display",
        "edit_action",
    )
    list_display_links = None
    search_fields = ("name", "user__phone")
    list_filter = ("status", ("joined_at", admin.DateFieldListFilter))
    readonly_fields = ("user_username", "user_joined", "user_type_display")
    actions = ["disable_assistants"]

    def get_changelist(self, request, **kwargs):
        return AssistantProfileChangeList

    def get_form(self, request, obj=None, **kwargs):
        kwargs["form"] = AssistantChangeForm if obj else AssistantCreationForm
        return super().get_form(request, obj, **kwargs)

    def get_filter_form(self, request):
        if not hasattr(request, "_assistantprofile_filter_form"):
            request._assistantprofile_filter_form = AssistantProfileFilterForm(request.GET or None)
        return request._assistantprofile_filter_form

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return self.readonly_fields
        return ()

    def get_fieldsets(self, request, obj=None):
        if obj:
            return (
                ("账号信息", {"fields": ("phone", "is_active", "reset_password")}),
                ("档案信息", {"fields": ("name", "status", "work_phone", "joined_at")}),
                ("负责医生", {"fields": ("doctors",)}),
                ("只读信息", {"fields": self.readonly_fields}),
            )
        return (
            ("账号信息", {"fields": ("phone", "password")}),
            ("档案信息", {"fields": ("name", "status", "work_phone", "joined_at")}),
            ("负责医生", {"fields": ("doctors",)}),
        )

    def get_queryset(self, request):
        qs = (
            super()
            .get_queryset(request)
            .select_related("user")
            .prefetch_related("doctors__studio")
            .annotate(patient_count=Count("doctors__patients", distinct=True))
        )
        form = self.get_filter_form(request)
        if form.is_valid():
            data = form.cleaned_data
            if data.get("name"):
                qs = qs.filter(name__icontains=data["name"])
            if data.get("registered_start"):
                qs = qs.filter(user__date_joined__date__gte=data["registered_start"])
            if data.get("registered_end"):
                qs = qs.filter(user__date_joined__date__lte=data["registered_end"])
            if data.get("work_phone"):
                qs = qs.filter(work_phone__icontains=data["work_phone"])
            if data.get("studio"):
                qs = qs.filter(doctors__studio__name__icontains=data["studio"])
        return qs

    def changelist_view(self, request, extra_context=None):
        form = self.get_filter_form(request)
        selected_id = request.GET.get("assistant_id")
        extra_context = extra_context or {}
        extra_context.update(
            {
                "filter_form": form,
                "selected_assistant_id": selected_id,
                "title": "医生助理管理",
            }
        )
        response = super().changelist_view(request, extra_context=extra_context)
        if hasattr(response, "context_data"):
            context = response.context_data
            context["filter_form"] = form
            selected_assistant = None
            selected_studios_display = "-"
            selected_doctors_display = "-"
            selected_patient_count = "-"
            if selected_id:
                cl = context.get("cl")
                if cl:
                    selected_assistant = next(
                        (obj for obj in cl.result_list if str(obj.pk) == str(selected_id)),
                        None,
                    )
                if not selected_assistant:
                    selected_assistant = self.get_queryset(request).filter(pk=selected_id).first()
                if selected_assistant:
                    selected_studios_display = self._studio_names(selected_assistant)
                    selected_doctors_display = self._doctor_names(selected_assistant)
                    selected_patient_count = getattr(selected_assistant, "patient_count", None)
                    if selected_patient_count is None:
                        selected_patient_count = (
                            selected_assistant.doctors.values("patients__id").distinct().count()
                        )
            context.update(
                {
                    "selected_assistant": selected_assistant,
                    "selected_studios_display": selected_studios_display,
                    "selected_doctors_display": selected_doctors_display,
                    "selected_patient_count": selected_patient_count,
                    "selected_assistant_id": selected_id,
                }
            )
        return response

    def user_is_active(self, obj):
        return obj.user.is_active

    user_is_active.boolean = True
    user_is_active.short_description = "账号状态"

    def user_joined(self, obj):
        return obj.user.date_joined

    user_joined.short_description = "注册时间"

    def user_username(self, obj):
        return obj.user.username

    user_username.short_description = "用户名"

    def user_type_display(self, obj):
        return obj.user.get_user_type_display()

    user_type_display.short_description = "用户类型"

    @admin.display(description="姓名", ordering="name")
    def assistant_name(self, obj):
        url = f"?assistant_id={obj.pk}"
        return format_html('<a href="{}">{}</a>', url, obj.name or "-")

    @admin.display(description="注册手机号", ordering="user__phone")
    def registered_phone(self, obj):
        return obj.user.phone

    @admin.display(description="助理状态", ordering="status")
    def status_display(self, obj):
        return obj.get_status_display()

    @admin.display(description="注册日期", ordering="user__date_joined")
    def registered_date(self, obj):
        return obj.user.date_joined

    @admin.display(description="工作电话")
    def work_phone_display(self, obj):
        return obj.work_phone or "-"

    @admin.display(description="服务工作室")
    def studio_display(self, obj):
        return self._studio_names(obj)

    @admin.display(description="关联医院主任")
    def doctor_display(self, obj):
        return self._doctor_names(obj)

    @admin.display(description="关联患者数量", ordering="patient_count")
    def patient_count_display(self, obj):
        count = getattr(obj, "patient_count", None)
        if count is None:
            return "-"
        return count

    @admin.display(description="操作")
    def edit_action(self, obj):
        url = reverse("admin:users_assistantprofile_change", args=[obj.pk])
        return format_html('<a href="{}">编辑</a>', url)

    def _studio_names(self, obj):
        names = []
        for doctor in obj.doctors.all():
            if doctor.studio and doctor.studio.name:
                names.append(doctor.studio.name)
        if not names:
            return "-"
        return ", ".join(sorted(set(names)))

    def _doctor_names(self, obj):
        names = [doctor.name for doctor in obj.doctors.all() if doctor.name]
        if not names:
            return "-"
        return ", ".join(sorted(set(names)))

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="禁用所选助理")
    def disable_assistants(self, request, queryset):
        for profile in queryset.select_related("user"):
            profile.user.is_active = False
            profile.status = choices.AssistantStatus.INACTIVE
            profile.user.save(update_fields=["is_active"])
            profile.save(update_fields=["status"])
        self.message_user(request, "已禁用所选助理。")
