from datetime import timedelta, date
from typing import Optional

# users/services/patient.py
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db import transaction, models

from core.service.monitoring import MonitoringService
from health_data.models import MedicalHistory
from regions.models import Province, City
from users import choices
from users.models import PatientProfile, CustomUser, PatientRelation

# 引用 wx 的 client 来获取二维码，注意避免循环引用，可以在方法内引用或使用 lazy import


class PatientService:

    #生成一个方法， 获取守护时间。
    #即用户所有的订单已过去的天数
    def get_guard_days(self, patient: PatientProfile) -> int:
        """
        【业务说明】按自然日统计患者已享受的“守护时间”总天数。

        【计算规则】
        - 仅统计已支付且有支付时间的订单（status=PAID, paid_at 非空）。
        - 每个订单贡献一个服务区间：
          - start_date = paid_at 对应的本地日期；
          - end_date = min(start_date + duration_days - 1, 今天前一天)；
          - 若 end_date < start_date，则该订单贡献 0 天。
        - 多个订单的服务区间按自然日合并去重（重叠或相邻的日期只算一次）。
        - 结果为所有合并区间长度之和（单位：天），按自然日计数。
        """
        from market.models import Order  # 避免在模块顶层引入引起不必要耦合

        today: date = timezone.localdate()
        end_limit: date = today - timedelta(days=1)
        if end_limit < today - timedelta(days=1):
            # 理论上不会发生，仅为类型检查和防御性
            end_limit = today - timedelta(days=1)

        # 无历史可统计
        if end_limit < today - timedelta(days=36500):
            # 占位防御，后面过滤仍会处理
            pass

        paid_orders = (
            Order.objects.select_related("product")
            .filter(patient=patient, status=Order.Status.PAID, paid_at__isnull=False)
            .order_by("paid_at")
        )

        ranges: list[tuple[date, date]] = []
        for order in paid_orders:
            duration = getattr(order.product, "duration_days", 0) or 0
            if duration <= 0:
                continue

            start_date = timezone.localtime(order.paid_at).date()
            theoretical_end = start_date + timedelta(days=duration - 1)
            end_date = min(theoretical_end, end_limit)

            # 该订单尚未对“过去天数”产生贡献
            if end_date < start_date:
                continue

            ranges.append((start_date, end_date))

        if not ranges:
            return 0

        # 按开始日期排序后进行区间合并（自然日去重）
        ranges.sort(key=lambda r: r[0])
        merged: list[tuple[date, date]] = []
        cur_start, cur_end = ranges[0]

        for start, end in ranges[1:]:
            # 若与当前区间相连或重叠（例如 cur_end=10, start=11），合并为单一连续段
            if start <= cur_end + timedelta(days=1):
                if end > cur_end:
                    cur_end = end
            else:
                merged.append((cur_start, cur_end))
                cur_start, cur_end = start, end

        merged.append((cur_start, cur_end))

        total_days = 0
        for s, e in merged:
            total_days += (e - s).days + 1

        return total_days
    
    
    
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
                "is_active": True,
            },
        )

        return profile
    
    def unbind_relation(self, patient: PatientProfile, relation_id: int) -> PatientRelation:
        """
        【功能】患者端解绑亲情账号（软删除）。
        """
        
        if patient is None:
            raise ValidationError("未找到患者档案，无法解绑亲情账号")

        relation = (
            PatientRelation.objects.select_related("patient")
            .filter(pk=relation_id, patient=patient, is_active=True)
            .first()
        )
        if relation is None:
            raise ValidationError("亲情账号不存在或已解绑")

        relation.is_active = False
        relation.save(update_fields=["is_active", "updated_at"])
        return relation



    def save_profile_by_self(self, user: CustomUser, data: dict, profile_id: int | None = None) -> PatientProfile:
        """患者自助保存档案（支持新建、认领、编辑）。

        【功能说明】
        - 支持患者本人创建新档案、认领已有档案、编辑已有档案。
        - 在建档/认领场景下，自动初始化或补全该患者的监测配置 MonitoringConfig。

        【参数说明】
        - user: 当前登录的 CustomUser 实例，用于绑定患者档案。
        - data: 表单数据字典，包含 name、gender、birth_date、phone 等字段。
        - profile_id: 可选，存在时表示编辑指定患者档案；为空表示建档或认领模式。

        【返回参数说明】
        - 返回更新后的 PatientProfile 实例；在建档/认领场景中，保证已关联一条 MonitoringConfig 记录。
        """
        phone = (data.get("phone") or "").strip()
        name = (data.get("name") or "").strip()
        
        if not phone or not name:
            raise ValidationError("姓名与手机号必填")

        # -------------------------------------------------------
        # 场景 A: 编辑模式 (已知 ID)
        # -------------------------------------------------------
        if profile_id:
            
            profile = PatientProfile.objects.filter(pk=profile_id).first()
            if not profile:
                raise ValidationError("档案不存在")
            
            # 权限校验：只能改属于自己的档案
            is_owner = (profile.user_id == user.id)
            is_relation = profile.relations.filter(user_id=user.id, is_active=True).exists()
            if not is_owner and not is_relation:
                raise ValidationError("无权修改此档案")
            
            # 手机号变更检查
            if profile.phone != phone:
                # 检查新手机号是否被占用
                if PatientProfile.objects.filter(phone=phone).exclude(pk=profile_id).exists():
                    raise ValidationError("该手机号已被其他档案占用")
            
            # 执行更新
            profile.name = name
            profile.phone = phone
            profile.gender = data.get("gender", profile.gender)
            profile.birth_date = data.get("birth_date", profile.birth_date)
            profile.address = (data.get("address") or "").strip()
            profile.ec_name = (data.get("ec_name") or "").strip()
            profile.ec_relation = (data.get("ec_relation") or "").strip()
            profile.ec_phone = (data.get("ec_phone") or "").strip()
            
            profile.save()
            return profile

        # -------------------------------------------------------
        # 场景 B: 建档/认领模式 (未知 ID，以手机号为锚点)
        # -------------------------------------------------------

        with transaction.atomic():
            # 1. 查重
            existing_profile = PatientProfile.objects.filter(phone=phone).first()

            if existing_profile:
                # 如果档案存在，且已被别人绑定
                if existing_profile.user and existing_profile.user != user:
                    raise ValidationError("该手机号已被其他微信账号绑定，请联系顾问处理。")

                # 认领/更新逻辑(这里实际上就是一个孤立的 patient)
                profile = existing_profile
            else:
                # 纯新建逻辑
                profile = PatientProfile(phone=phone)
                profile.source = choices.PatientSource.SELF

            # 2. 赋值/覆盖属性
            profile.user = user
            profile.name = name
            profile.gender = data.get("gender", choices.Gender.UNKNOWN)
            profile.birth_date = data.get("birth_date")
            profile.claim_status = choices.ClaimStatus.CLAIMED
            profile.address = (data.get("address") or "").strip()
            profile.ec_name = (data.get("ec_name") or "").strip()
            profile.ec_relation = (data.get("ec_relation") or "").strip()
            profile.ec_phone = (data.get("ec_phone") or "").strip()

            # 3. 销售归属处理 (仅当档案无销售时，继承 User 的潜客归属)
            if not profile.sales and getattr(user, "bound_sales", None):
                profile.sales = user.bound_sales
                # 归属转移后，清空潜客标记
                user.bound_sales = None
                user.save(update_fields=["bound_sales"])

            profile.save()

            # 4. 初始化或补全监测配置（保证患者始终拥有一条 MonitoringConfig）
            MonitoringService.init_patient_config(profile)

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
