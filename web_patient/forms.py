from django import forms
from django.utils import timezone
from datetime import datetime

from business_support.service.sms import SMSService
from business_support.models import Feedback
from users import choices
from users.models import PatientProfile
from health_data.models import MetricMeasurementContext, MetricType


BASE_INPUT_CLASS = (
    "w-full px-4 py-3 rounded-2xl border border-slate-200 "
    "focus:ring-2 focus:ring-sky-500 focus:border-sky-500 text-base text-slate-900"
)
INLINE_INPUT_CLASS = (
    "text-right placeholder-slate-400 focus:outline-none bg-transparent w-full text-slate-900"
)


class GeneralMonitoringMetricForm(forms.Form):
    value = forms.DecimalField(
        label="监测值",
        min_value=0,
        max_digits=10,
        decimal_places=2,
    )
    measurement_context = forms.ChoiceField(
        label="测量场景",
        required=False,
        choices=(("", "请选择"), *MetricMeasurementContext.choices),
    )
    record_time = forms.DateTimeField(
        required=False,
        input_formats=("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"),
    )
    record_time_touched = forms.CharField(required=False)
    selected_date = forms.DateField(required=False, input_formats=("%Y-%m-%d",))

    def __init__(self, *args, metric_definition, **kwargs):
        self.metric_definition = metric_definition
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        context = cleaned_data.get("measurement_context") or None
        if self.metric_definition.metric_type == MetricType.BLOOD_GLUCOSE:
            if context not in MetricMeasurementContext.values:
                self.add_error("measurement_context", "请选择血糖测量场景")
        else:
            cleaned_data["measurement_context"] = None

        now_local = timezone.localtime(timezone.now())
        if (
            cleaned_data.get("record_time_touched") == "1"
            and cleaned_data.get("record_time")
        ):
            measured_at = cleaned_data["record_time"]
            if timezone.is_naive(measured_at):
                measured_at = timezone.make_aware(
                    measured_at,
                    timezone.get_current_timezone(),
                )
        else:
            measured_at = now_local

        selected_date = cleaned_data.get("selected_date")
        if selected_date:
            local_time = timezone.localtime(measured_at).time().replace(tzinfo=None)
            measured_at = timezone.make_aware(
                datetime.combine(selected_date, local_time),
                timezone.get_current_timezone(),
            )
        cleaned_data["measured_at"] = measured_at
        return cleaned_data


class BloodPressureHeartRateForm(forms.Form):
    """血压/心率共用录入页的服务端输入校验。"""

    MODE_BOTH = "both"
    MODE_BLOOD_PRESSURE = "bp"
    MODE_HEART_RATE = "heart"
    MODE_CHOICES = (
        (MODE_BOTH, "血压和心率"),
        (MODE_BLOOD_PRESSURE, "血压"),
        (MODE_HEART_RATE, "心率"),
    )

    mode = forms.ChoiceField(choices=MODE_CHOICES)
    ssy = forms.IntegerField(required=False, min_value=50, max_value=250)
    szy = forms.IntegerField(required=False, min_value=30, max_value=150)
    heart = forms.IntegerField(required=False, min_value=30, max_value=200)

    def clean(self):
        cleaned_data = super().clean()
        mode = cleaned_data.get("mode")
        if mode in {self.MODE_BOTH, self.MODE_BLOOD_PRESSURE}:
            if cleaned_data.get("ssy") is None:
                self.add_error("ssy", "请输入50-250之间的收缩压")
            if cleaned_data.get("szy") is None:
                self.add_error("szy", "请输入30-150之间的舒张压")
            if (
                cleaned_data.get("ssy") is not None
                and cleaned_data.get("szy") is not None
                and cleaned_data["ssy"] <= cleaned_data["szy"]
            ):
                self.add_error("szy", "收缩压应高于舒张压")
        if mode in {self.MODE_BOTH, self.MODE_HEART_RATE}:
            if cleaned_data.get("heart") is None:
                self.add_error("heart", "请输入30-200之间的心率")
        return cleaned_data


class PatientEntryVerificationForm(forms.Form):
    name = forms.CharField(
        label="患者姓名",
        max_length=50,
        widget=forms.TextInput(
            attrs={
                "placeholder": "请输入患者姓名",
                "class": BASE_INPUT_CLASS,
            }
        ),
    )
    gender = forms.ChoiceField(
        label="性别",
        choices=choices.Gender.choices,
        initial=choices.Gender.UNKNOWN,
        widget=forms.Select(
            attrs={
                "class": BASE_INPUT_CLASS,
            }
        ),
    )
    birth_date = forms.DateField(
        label="出生日期",
        required=False,
        widget=forms.DateInput(
            attrs={
                "type": "date",
                "class": BASE_INPUT_CLASS,
            }
        ),
    )
    phone = forms.CharField(
        label="手机号",
        max_length=15,
        widget=forms.TextInput(
            attrs={
                "placeholder": "请输入常用手机号",
                "inputmode": "numeric",
                "class": BASE_INPUT_CLASS,
            }
        ),
    )
    verify_code = forms.CharField(
        label="短信验证码",
        max_length=6,
        widget=forms.TextInput(
            attrs={
                "placeholder": "请输入短信验证码",
                "inputmode": "numeric",
                "class": BASE_INPUT_CLASS,
            }
        ),
    )

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        if not name:
            raise forms.ValidationError("请填写姓名")
        return name

    def clean_phone(self):
        phone = (self.cleaned_data.get("phone") or "").strip()
        if not phone:
            raise forms.ValidationError("请填写手机号")
        return phone

    def clean_verify_code(self):
        code = (self.cleaned_data.get("verify_code") or "").strip()
        if not code:
            raise forms.ValidationError("请输入短信验证码")

        phone = self.cleaned_data.get("phone")
        if not phone:
            raise forms.ValidationError("请先填写手机号")

        success, message = SMSService.verify_code(phone, code)
        if not success:
            raise forms.ValidationError(message or "验证码无效")
        return code


class PatientSelfEntryForm(forms.ModelForm):
    class Meta:
        model = PatientProfile
        fields = [
            "name",
            "gender",
            "birth_date",
            "phone",
            "address",
            "ec_name",
            "ec_relation",
            "ec_phone",
        ]
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "placeholder": "请输入姓名",
                    "class": INLINE_INPUT_CLASS,
                }
            ),
            "birth_date": forms.DateInput(
                attrs={
                    "type": "date",
                    "class": INLINE_INPUT_CLASS,
                }
            ),
            "phone": forms.TextInput(
                attrs={
                    "readonly": "readonly",
                    "class": f"{INLINE_INPUT_CLASS} cursor-not-allowed",
                }
            ),
            "address": forms.TextInput(
                attrs={
                    "placeholder": "请输入联系地址",
                    "class": INLINE_INPUT_CLASS,
                }
            ),
            "ec_name": forms.TextInput(
                attrs={
                    "placeholder": "请输入紧急联系人姓名",
                    "class": INLINE_INPUT_CLASS,
                }
            ),
            "ec_relation": forms.TextInput(
                attrs={
                    "placeholder": "请输入与患者关系",
                    "class": INLINE_INPUT_CLASS,
                }
            ),
            "ec_phone": forms.TextInput(
                attrs={
                    "placeholder": "请输入紧急联系人电话",
                    "class": INLINE_INPUT_CLASS,
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["gender"].widget = forms.RadioSelect(attrs={"class": "sr-only"})
        for name, field in self.fields.items():
            if name == "gender":
                continue
            css = field.widget.attrs.get("class", "")
            if INLINE_INPUT_CLASS not in css:
                field.widget.attrs["class"] = f"{INLINE_INPUT_CLASS} {css}".strip()


class FeedbackForm(forms.ModelForm):
    class Meta:
        model = Feedback
        fields = ["feedback_type", "content", "contact_phone"]
        widgets = {
            "feedback_type": forms.HiddenInput(),
            "content": forms.Textarea(
                attrs={
                    "rows": 5,
                    "maxlength": 140,
                    "placeholder": "请描述遇到的问题或建议，我们会尽快跟进~",
                    "class": "w-full rounded-3xl border border-slate-200 px-5 py-4 text-base text-slate-900 focus:ring-2 focus:ring-sky-500 focus:border-sky-500",
                }
            ),
            "contact_phone": forms.TextInput(
                attrs={
                    "placeholder": "便于联系您（选填）",
                    "inputmode": "tel",
                    "class": "w-full rounded-2xl border border-slate-200 px-4 py-3 text-base text-slate-900 focus:ring-2 focus:ring-sky-500 focus:border-sky-500",
                }
            ),
        }

    def clean_content(self):
        content = (self.cleaned_data.get("content") or "").strip()
        if not content:
            raise forms.ValidationError("请填写反馈内容")
        if len(content) > 140:
            raise forms.ValidationError("反馈内容不能超过 140 字")
        return content

    def clean_contact_phone(self):
        phone = (self.cleaned_data.get("contact_phone") or "").strip()
        if phone and len(phone) > 20:
            raise forms.ValidationError("联系方式长度过长")
        return phone
