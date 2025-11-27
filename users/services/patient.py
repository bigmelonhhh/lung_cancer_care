from datetime import timedelta
from typing import Optional

# users/services/patient.py
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from users.models import PatientProfile, CustomUser, PatientRelation
from users import choices
from health_data.models import MedicalHistory
from regions.models import Province, City
# 引用 wx 的 client 来获取二维码，注意避免循环引用，可以在方法内引用或使用 lazy import
from wechatpy import WeChatClient 

class PatientService:
    
    
    def generate_bind_qrcode(self, profile_id: int, expire_seconds: int = 604800) -> str:
        """
        【功能4】生成或复用带参二维码（临时二维码）。
        参数值示例：bind_patient_1024
        """
        from django.utils import timezone
        from datetime import timedelta
        
        # 1. 校验档案存在
        profile = PatientProfile.objects.filter(id=profile_id).first()
        if not profile:
            raise ValidationError("患者档案不存在")

        now = timezone.now()

        # 2. 检查缓存 (如果有未过期的二维码图片链接，直接返回)
        # 预留 1 分钟缓冲期，防止临界点失效
        if (
            profile.qrcode_url
            and profile.qrcode_expire_at
            and profile.qrcode_expire_at > (now + timedelta(minutes=1))
        ):
            return profile.qrcode_url

        # 3. 调用微信接口生成
        # 避免循环引用，这里导入
        from wx.services.client import wechat_client

        scene_str = f"bind_patient_{profile_id}"
        try:
            # 创建临时二维码
            res = wechat_client.qrcode.create(
                {
                    "expire_seconds": expire_seconds,  # 7天 (微信最大值)
                    "action_name": "QR_STR_SCENE",
                    "action_info": {"scene": {"scene_str": scene_str}},
                }
            )
        except Exception as e:
            raise ValidationError(f"微信接口调用失败: {str(e)}")

        # 4. 【核心修复】使用 ticket 换取图片链接
        ticket = res.get("ticket")
        if not ticket:
            raise ValidationError("二维码生成失败(无ticket)，请稍后再试")
            
        # get_url 会返回一个 https://mp.weixin.qq.com/cgi-bin/showqrcode?ticket=... 的链接
        # 这个链接可以直接放入 <img src="..."> 中显示
        real_qrcode_img_url = wechat_client.qrcode.get_url(ticket)

        # 5. 更新数据库缓存
        profile.qrcode_url = real_qrcode_img_url
        profile.qrcode_expire_at = now + timedelta(seconds=int(expire_seconds))
        
        # 只更新这就几个字段，提高效率
        profile.save(update_fields=["qrcode_url", "qrcode_expire_at", "updated_at"])

        return real_qrcode_img_url

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

    def get_profile_for_bind(self, profile_id: int) -> PatientProfile:
        """根据 ID 获取档案，找不到抛错。"""

        profile = PatientProfile.objects.filter(pk=profile_id).first()
        if profile is None:
            raise ValidationError("患者档案不存在")
        return profile

    def process_binding(
        self,
        user: CustomUser,
        patient_id: int,
        relation_type: int,
        **kwargs,
    ) -> PatientProfile:
        """处理患者本人或家属绑定逻辑。"""

        profile = self.get_profile_for_bind(patient_id)

        if relation_type == choices.RelationType.SELF:
            if profile.user and profile.user != user:
                raise ValidationError("该档案已被其他微信账号认领")
            if hasattr(user, "patient_profile") and user.patient_profile != profile:
                raise ValidationError("您已绑定过其他患者档案")
            profile.user = user
            profile.claim_status = choices.ClaimStatus.CLAIMED
            profile.save(update_fields=["user", "claim_status", "updated_at"])
            return profile

        relation_name = kwargs.get("relation_name", "")
        receive_alert_msg = kwargs.get("receive_alert_msg", False)

        PatientRelation.objects.update_or_create(
            patient=profile,
            user=user,
            defaults={
                "relation_type": relation_type,
                "relation_name": relation_name,
                "receive_alert_msg": receive_alert_msg,
            },
        )

        return profile

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

        risk_value = (data.get("risk_factors") or "").strip()

        record_date = data.get("record_date") or timezone.now().date()
        address_detail = (data.get("address_detail") or "").strip()

        province_name = ""
        city_name = ""
        province_id = data.get("address_province")
        city_id = data.get("address_city")
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
            defaults = {
                "name": name,
                "gender": data.get("gender", choices.Gender.MALE),
                "birth_date": data.get("birth_date"),
                "address": address,
                "sales": sales_user.sales_profile,
                "source": choices.PatientSource.SALES,
                "claim_status": choices.ClaimStatus.PENDING,
                "ec_name": data.get("ec_name", ""),
                "ec_phone": data.get("ec_phone", ""),
                "ec_relation": data.get("ec_relation", ""),
            }

            profile, _created = PatientProfile.objects.update_or_create(
                phone=phone,
                defaults=defaults,
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

    def assign_doctor(
        self,
        patient: PatientProfile,
        doctor_id: Optional[int],
        sales_user: CustomUser,
    ) -> PatientProfile:
        """为患者设置主治医生。"""

        if not hasattr(sales_user, "sales_profile"):
            raise ValidationError("当前账号无销售档案")

        doctor = None
        if doctor_id:
            doctor = (
                sales_user.sales_profile.doctors.filter(pk=doctor_id).first()
            )
            if doctor is None:
                raise ValidationError("医生不存在或无权绑定")

        patient.doctor = doctor
        patient.save(update_fields=["doctor", "updated_at"])
        return patient
