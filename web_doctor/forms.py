from django import forms
from django.contrib.auth.forms import PasswordChangeForm


class PatientHealthBaselineForm(forms.Form):
    """医生端患者生命体征基线录入与清洗。"""

    blood_oxygen = forms.IntegerField(required=False, min_value=0, max_value=100)
    sbp = forms.IntegerField(required=False, min_value=0, max_value=300)
    dbp = forms.IntegerField(required=False, min_value=0, max_value=300)
    heart_rate = forms.IntegerField(required=False, min_value=0, max_value=300)
    weight = forms.DecimalField(required=False, min_value=0, max_digits=5, decimal_places=1)
    height = forms.DecimalField(required=False, min_value=0, max_digits=5, decimal_places=1)
    temperature = forms.DecimalField(required=False, min_value=0, max_digits=4, decimal_places=1)
    steps = forms.IntegerField(required=False, min_value=0)
    blood_glucose = forms.DecimalField(required=False, min_value=0, max_digits=5, decimal_places=1)
    blood_ketone = forms.DecimalField(required=False, min_value=0, max_digits=4, decimal_places=1)
    uric_acid = forms.IntegerField(required=False, min_value=0)

    _PROFILE_FIELD_BY_INPUT = {
        "blood_oxygen": "baseline_blood_oxygen",
        "sbp": "baseline_blood_pressure_sbp",
        "dbp": "baseline_blood_pressure_dbp",
        "heart_rate": "baseline_heart_rate",
        "weight": "baseline_weight",
        "height": "baseline_height",
        "temperature": "baseline_body_temperature",
        "steps": "baseline_steps",
        "blood_glucose": "baseline_blood_glucose",
        "blood_ketone": "baseline_blood_ketone",
        "uric_acid": "baseline_uric_acid",
    }

    def clean(self):
        cleaned_data = super().clean()
        for input_name, profile_field in self._PROFILE_FIELD_BY_INPUT.items():
            cleaned_data[profile_field] = cleaned_data.get(input_name)
        return cleaned_data


class DoctorPasswordChangeForm(PasswordChangeForm):
    """为医生端统一注入 Tailwind 样式。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        base_classes = (
            "w-full rounded-xl border border-slate-200 px-4 py-2.5 "
            "text-slate-800 focus:outline-none focus:ring-2 focus:ring-sky-200 "
            "focus:border-sky-500 bg-white"
        )
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", base_classes)
            field.widget.attrs.setdefault("placeholder", field.label)
