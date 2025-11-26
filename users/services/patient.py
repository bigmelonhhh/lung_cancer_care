from datetime import timedelta

# users/services/patient.py
from django.core.exceptions import ValidationError
from django.db import transaction
from django.conf import settings
from django.utils import timezone
from users.models import PatientProfile, SalesProfile, CustomUser
from users import choices
from health_data.models import MedicalHistory
from regions.models import Province, City
# 引用 wx 的 client 来获取二维码，注意避免循环引用，可以在方法内引用或使用 lazy import
from wechatpy import WeChatClient 

class PatientService:
    
    

    def create_profile_by_self(self, user: CustomUser, data: dict) -> PatientProfile:
        """
        【功能3】患者自创患者档案（有 customer_id）。
        """
        if hasattr(user, 'patient_profile'):
            raise ValidationError("您已拥有患者档案")

        profile = PatientProfile.objects.create(
            user=user, # 绑定当前用户
            name=data['name'],
            phone=data['phone'],
            source=choices.PatientSource.SELF,
            claim_status=choices.ClaimStatus.CLAIMED
        )
        return profile

    def generate_bind_qrcode(self, profile_id: int) -> str:
        """
        【功能4】生成或复用带参二维码（临时二维码）。
        参数值示例：bind_patient_1024
        """

        profile = PatientProfile.objects.filter(id=profile_id).first()
        if not profile:
            raise ValidationError("患者不存在")

        now = timezone.now()
        if (
            profile.qrcode_url
            and profile.qrcode_expire_at
            and profile.qrcode_expire_at - timedelta(minutes=1) > now
        ):
            return profile.qrcode_url

        # 避免循环引用，这里导入
        from wx.services.client import wechat_client

        scene_str = f"bind_patient_{profile_id}"
        res = wechat_client.qrcode.create(
            {
                "expire_seconds": 604800,
                "action_name": "QR_STR_SCENE",
                "action_info": {"scene": {"scene_str": scene_str}},
            }
        )
        qrcode_url = res.get("url")
        expire_seconds = res.get("expire_seconds") or 600
        if not qrcode_url:
            raise ValidationError("二维码生成失败，请稍后再试")

        profile.qrcode_url = qrcode_url
        profile.qrcode_expire_at = now + timedelta(seconds=int(expire_seconds))
        profile.save(update_fields=["qrcode_url", "qrcode_expire_at", "updated_at"])

        return qrcode_url

    def bind_user_to_profile(self, openid: str, profile_id: int) -> bool:
        """
        【功能5】扫描二维码后的绑定逻辑。
        """
        # 1. 找到对应的 User (如果没有则创建，逻辑复用 Auth)
        # 这里需要简单引用一下，或者直接查库
        user = CustomUser.objects.filter(wx_openid=openid).first()
        if not user:
             # 极端情况：用户未关注直接扫码，微信会先推 subscribe 再推 scan（或合并）
             # 建议这里复用 AuthService 的逻辑确保 User 存在
             return False 

        # 2. 找到档案
        profile = PatientProfile.objects.filter(id=profile_id).first()
        if not profile:
            return False
            
        # 3. 校验：该档案是否已被别人认领
        if profile.user and profile.user != user:
            raise ValidationError("该档案已被其他微信账号绑定")
        
        # 4. 校验：该微信是否已有其他档案
        if hasattr(user, 'patient_profile') and user.patient_profile != profile:
            raise ValidationError("您已绑定过其他患者档案，无法重复绑定")

        # 5. 执行绑定
        if profile.user != user:
            profile.user = user
            profile.claim_status = choices.ClaimStatus.CLAIMED
            profile.save(update_fields=['user', 'claim_status'])
            return True
            
        return True # 已经是本人绑定，算成功

    def create_full_patient_record(self, sales_user: CustomUser, data: dict) -> PatientProfile:
        """
        销售端完整录入患者档案（含病史）。
        """

        if not hasattr(sales_user, "sales_profile"):
            raise ValidationError("当前账号无销售档案")

        name = (data.get("name") or "").strip()
        phone = (data.get("phone") or "").strip()
        if not name or not phone:
            raise ValidationError("姓名与联系电话为必填项")

        risk_factors = data.get("risk_factors") or []
        if isinstance(risk_factors, str):
            risk_list = [risk_factors]
        else:
            risk_list = list(risk_factors)
        risk_value = ",".join([item.strip() for item in risk_list if item])

        record_date = data.get("record_date") or timezone.now().date()
        address_detail = (data.get("address_detail") or "").strip()

        province_name = ""
        city_name = ""
        province_id = data.get("province_id")
        city_id = data.get("city_id")
        try:
            province_obj = (
                Province.objects.filter(id=int(province_id)).first()
                if province_id
                else None
            )
        except (TypeError, ValueError):
            province_obj = None
        if province_obj:
            province_name = province_obj.name

        try:
            city_obj = (
                City.objects.filter(id=int(city_id)).first()
                if city_id
                else None
            )
        except (TypeError, ValueError):
            city_obj = None
        if city_obj:
            city_name = city_obj.name

        address = " ".join(
            part for part in [province_name, city_name, address_detail] if part
        )

        with transaction.atomic():
            profile = PatientProfile.objects.create(
                name=name,
                phone=phone,
                gender=data.get("gender", choices.Gender.UNKNOWN),
                birth_date=data.get("birth_date"),
                address=address,
                sales=sales_user.sales_profile,
                source=choices.PatientSource.SALES,
                claim_status=choices.ClaimStatus.PENDING,
                ec_name=data.get("ec_name", ""),
                ec_phone=data.get("ec_phone", ""),
                ec_relation=data.get("ec_relation", ""),
            )

            MedicalHistory.objects.create(
                patient=profile,
                record_date=record_date,
                diagnosis=data.get("diagnosis", ""),
                pathology=data.get("pathology", ""),
                tnm_stage=data.get("tnm_stage", ""),
                gene_mutation=data.get("gene_mutation", ""),
                surgery_info=data.get("surgery_info", ""),
                doctor_note=data.get("doctor_note", ""),
                risk_factors=risk_value,
            )

        return profile
