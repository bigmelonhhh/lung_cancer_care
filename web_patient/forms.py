from django import forms

from core.service.sms import SMSService
from core.models import Feedback
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
