# users/services/patient.py
from django.core.exceptions import ValidationError
from django.db import transaction
from django.conf import settings
from users.models import PatientProfile, SalesProfile, CustomUser
from users import choices
# 引用 wx 的 client 来获取二维码，注意避免循环引用，可以在方法内引用或使用 lazy import
from wechatpy import WeChatClient 

class PatientService:
    
    def create_profile_by_sales(self, sales_user: CustomUser, data: dict) -> PatientProfile:
        """
        销售直接创建患者档案（无 customer_id）。
        """
        # 1. 校验销售身份
        if not hasattr(sales_user, 'sales_profile'):
            raise ValidationError("当前账号无销售档案")
            
        sales_profile = sales_user.sales_profile

        # 2. 创建档案 (user=None)
        profile = PatientProfile.objects.create(
            name=data['name'],
            phone=data['phone'],
            gender=data.get('gender', choices.Gender.UNKNOWN),
            age=data.get('age'),
            disease_detail=data.get('disease_detail', ''), # 假设有这个字段
            sales=sales_profile,
            source=choices.PatientSource.SALES,
            claim_status=choices.ClaimStatus.PENDING # 待认领
        )
        return profile

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
        【功能4】生成带参二维码（临时二维码）。
        参数值示例：bind_patient_1024
        """
        # 避免循环引用，这里导入
        from wx.services.client import wechat_client 
        
        # 场景值：bind_patient_{id}
        scene_str = f"bind_patient_{profile_id}"
        
        # 生成有效期 7 天的临时二维码
        res = wechat_client.qrcode.create({
            'expire_seconds': 604800, 
            'action_name': 'QR_STR_SCENE',
            'action_info': {'scene': {'scene_str': scene_str}}
        })
        return res['url'] # 返回二维码图片地址，或者 ticket

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