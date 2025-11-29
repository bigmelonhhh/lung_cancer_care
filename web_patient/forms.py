from django import forms

from core.service.sms import SMSService
from users import choices
from users.models import PatientProfile


BASE_INPUT_CLASS = (
    "w-full px-4 py-3 rounded-2xl border border-slate-200 "
    "focus:ring-2 focus:ring-sky-500 focus:border-sky-500 text-base text-slate-900"
)
INLINE_INPUT_CLASS = (
    "text-right placeholder-slate-400 focus:outline-none bg-transparent w-full text-slate-900"
)


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
