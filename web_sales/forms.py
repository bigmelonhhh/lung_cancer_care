"""Forms for web_sales domain."""

from typing import Any

from django import forms
from django.contrib.auth.forms import PasswordChangeForm

from users.models import PatientProfile


class PatientEntryForm(forms.ModelForm):
    """患者录入表单，包含档案与病史字段。"""

    RISK_FACTOR_CHOICES = [
        ("家族遗传", "家族遗传"),
        ("吸烟", "吸烟"),
        ("职业暴露", "职业暴露"),
        ("空气污染", "空气污染"),
        ("肺部慢病", "肺部慢病"),
        ("其它", "其它"),
    ]

    address_province = forms.CharField(required=False)
    address_city = forms.CharField(required=False)
    address_detail = forms.CharField(required=False)

    diagnosis = forms.CharField(required=False)
    pathology = forms.CharField(required=False)
    tnm_stage = forms.CharField(required=False)
    gene_mutation = forms.CharField(required=False)
    surgery_info = forms.CharField(required=False, widget=forms.Textarea)
    doctor_note = forms.CharField(required=False, widget=forms.Textarea)

    risk_factors = forms.MultipleChoiceField(
        choices=RISK_FACTOR_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = PatientProfile
        fields = [
            "name",
            "gender",
            "birth_date",
            "phone",
            "ec_name",
            "ec_relation",
            "ec_phone",
        ]
        widgets = {
            "birth_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        base_classes = (
            "mt-1 w-full rounded-2xl border border-slate-200 px-4 py-2.5 "
            "focus:outline-none focus:ring-2 focus:ring-blue-100"
        )
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxSelectMultiple):
                widget.attrs.setdefault(
                    "class",
                    "grid grid-cols-1 md:grid-cols-3 gap-3 text-sm text-slate-700",
                )
            else:
                widget.attrs.setdefault("class", base_classes)
        self.fields["phone"].widget.attrs["placeholder"] = "11 位手机号"

    def clean_risk_factors(self) -> str:
        values = self.cleaned_data.get("risk_factors") or []
        return ",".join(v for v in values if v)

    def validate_unique(self) -> None:
        """跳过唯一性校验，交由 Service 层处理/合并。"""

        return


class SalesPasswordChangeForm(PasswordChangeForm):
    """销售端密码修改表单，注入 Tailwind 样式。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        base_classes = (
            "w-full rounded-xl border border-slate-200 px-4 py-2.5 "
            "text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-200 "
            "focus:border-blue-500 bg-white"
        )
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", base_classes)
            field.widget.attrs.setdefault("placeholder", field.label)
