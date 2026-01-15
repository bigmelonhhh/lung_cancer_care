from datetime import timedelta, date
from typing import Optional

# users/services/patient.py
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db import transaction, models

from health_data.models import MedicalHistory
from regions.models import Province, City
from users import choices
from users.models import PatientProfile, CustomUser, PatientRelation

# 引用 wx 的 client 来获取二维码，注意避免循环引用，可以在方法内引用或使用 lazy import



class PatientService:

    def get_guard_days(self, patient: PatientProfile) -> tuple[int, int]:
        """
        【业务说明】计算患者的“已服务天数”和“剩余服务天数”。

        【计算规则】
        1. 数据源：仅统计已支付且有支付时间的订单（status=PAID, paid_at 非空）。
        2. 区间生成：
           - start_date = paid_at 对应的本地日期。
           - end_date = start_date + duration_days - 1。
        3. 区间合并：
           - 对所有订单生成的 [start_date, end_date] 进行自然日合并，去除重叠部分。
           - 连续的日期也会合并（如10号结束，11号开始，视为连续）。
        4. 切分统计：
           - 以“今天”为界进行切分。
           - 已服务天数 (Served Days)：合并区间在“今天之前”的部分（截止到昨天）。
           - 剩余天数 (Remaining Days)：合并区间在“今天及以后”的部分。

        【参数】
        - patient: PatientProfile 对象，需统计的患者档案。

        【返回值】
        - tuple[int, int]: (已服务天数, 剩余服务天数)

        【使用示例】
        >>> served_days, remaining_days = patient_service.get_guard_days(patient)
        >>> print(f"已守护 {served_days} 天，剩余权益 {remaining_days} 天")
        """
        from market.models import Order  # 避免在模块顶层引入引起不必要耦合

        today: date = timezone.localdate()
        yesterday: date = today - timedelta(days=1)

        paid_orders = (
            Order.objects.select_related("product")
            .filter(patient=patient, status=Order.Status.PAID, paid_at__isnull=False)
            .order_by("paid_at")
        )

        # 1. 生成原始服务区间 (不截断)
        raw_ranges: list[tuple[date, date]] = []
        for order in paid_orders:
            duration = getattr(order.product, "duration_days", 0) or 0
            if duration <= 0:
                continue

            start_date = timezone.localtime(order.paid_at).date()
            end_date = start_date + timedelta(days=duration - 1)
            raw_ranges.append((start_date, end_date))

        if not raw_ranges:
            return 0, 0

        # 2. 区间合并
        raw_ranges.sort(key=lambda r: r[0])
        merged_ranges: list[tuple[date, date]] = []
        
        curr_start, curr_end = raw_ranges[0]
        for next_start, next_end in raw_ranges[1:]:
            # 若与当前区间相连或重叠（例如 curr_end=10, next_start=11），合并为单一连续段
            if next_start <= curr_end + timedelta(days=1):
                if next_end > curr_end:
                    curr_end = next_end
            else:
                merged_ranges.append((curr_start, curr_end))
                curr_start, curr_end = next_start, next_end
        merged_ranges.append((curr_start, curr_end))

        # 3. 统计天数 (切分过去与未来)
        served_days = 0
        remaining_days = 0

        for start, end in merged_ranges:
            # --- 计算已服务天数 ( < today ) ---
            # 有效结束时间取 min(区间结束, 昨天)
            served_end = min(end, yesterday)
            if served_end >= start:
                served_days += (served_end - start).days + 1

            # --- 计算剩余天数 ( >= today ) ---
            # 有效开始时间取 max(区间开始, 今天)
            remaining_start = max(start, today)
            if end >= remaining_start:
                remaining_days += (end - remaining_start).days + 1

        return served_days, remaining_days
    
    
    
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
        """
        【业务说明】处理患者本人或家属扫描二维码后的绑定逻辑。
        该函数会根据传入的 `relation_type` 区分是患者本人认领档案，还是家属建立亲情关系。

        【使用示例】
        # 家属绑定
        patient_service.process_binding(
            user=request.user,
            patient_id=123,
            relation_type=choices.RelationType.CHILD,
            relation_name="女儿",
            phone="13800138001",
            receive_alert_msg=True
        )
        # 患者本人认领
        patient_service.process_binding(
            user=request.user,
            patient_id=123,
            relation_type=choices.RelationType.SELF
        )

        【参数】
        - `user` (CustomUser): 当前发起绑定操作的已登录用户实例。
        - `patient_id` (int): 被绑定的患者档案的 ID。
        - `relation_type` (int): 关系类型，参考 `users.choices.RelationType` 枚举。
        - `**kwargs`:
            - `relation_name` (str, optional): 自定义的家属关系称呼，例如“大女儿”。
            - `phone` (str, optional): 家属的手机号。
            - `receive_alert_msg` (bool, optional): 家属是否愿意接收提醒通知。

        【返回值】
        - `PatientProfile`: 操作成功后返回对应的患者档案实例。

        【异常】
        - `ValidationError`: 如果患者档案不存在，或绑定关系不符合业务规则（如重复认领），则会抛出此异常。
        """

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
        phone = kwargs.get("phone", None)
        name = kwargs.get("name", "")

        PatientRelation.objects.update_or_create(
            patient=profile,
            user=user,
            defaults={
                "relation_type": relation_type,
                "relation_name": relation_name,
                "phone": phone,
                "name": name,
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

    def get_patient_family_members(self, patient: PatientProfile) -> models.QuerySet[PatientRelation]:
        """
        【业务说明】获取指定患者档案的所有有效家属关系列表。
        【使用示例】 `family_list = patient_service.get_patient_family_members(patient_profile)`
        【参数】
        - `patient` (PatientProfile): 患者档案实例。
        【返回值】
        - `QuerySet[PatientRelation]`: 一个包含所有有效家属关系（非本人、is_active=True）的查询集。
        """
        return patient.relations.filter(is_active=True).exclude(
            relation_type=choices.RelationType.SELF
        )

    def save_patient_profile(self, user: CustomUser, data: dict, profile_id: int | None = None) -> PatientProfile:
        """
        【业务说明】通用方法：创建、认领或更新患者档案（支持患者、家属、医生、管理员等多种角色）。
        - 编辑模式 (profile_id 已知): 根据传入的 `user` 角色（患者/家属、医生、管理员）进行权限校验，通过后更新档案。
        - 建档/认领模式 (profile_id 未知): 患者本人基于手机号进行操作，可认领未绑定微信的档案，或创建全新档案。

        【参数说明】
        - `user`: 当前进行操作的登录用户 (CustomUser)，用于权限判断。
        - `data`: 包含档案信息的字典，必须包含 `name` 和 `phone`。
        - `profile_id`: 可选，存在时表示编辑模式。

        【返回值】
        - `PatientProfile`: 创建或更新成功后的患者档案实例。
        """
        phone = (data.get("phone") or "").strip()
        name = (data.get("name") or "").strip()
        remark = (data.get("remark") or "").strip()
        
        if not phone or not name:
            raise ValidationError("姓名与手机号必填")
        if len(remark) > 500:
            raise ValidationError("备注不能超过500字")

        # -------------------------------------------------------
        # 场景 A: 编辑模式 (已知 ID)
        # -------------------------------------------------------
        if profile_id:
            
            profile = PatientProfile.objects.filter(pk=profile_id).first()
            if not profile:
                raise ValidationError("档案不存在")
            
            # --- 扩展后的权限校验 ---
            can_edit = False
            # 场景一：操作者是患者本人或家属
            if user.user_type == choices.UserType.PATIENT:
                if profile.user_id == user.id or profile.relations.filter(user_id=user.id, is_active=True).exists():
                    can_edit = True
            
            # 场景二：操作者是医生
            elif user.user_type == choices.UserType.DOCTOR:
                # 检查该医生是否是此患者的主治医生
                if profile.doctor and profile.doctor.user_id == user.id:
                    can_edit = True

            # 场景三：操作者是平台管理员
            elif user.is_staff:
                can_edit = True
            
            if not can_edit:
                raise ValidationError("您没有权限修改此患者的档案。")
            
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
            profile.remark = remark
            profile.baseline_body_temperature = data.get(
                "baseline_body_temperature", profile.baseline_body_temperature
            )
            profile.baseline_blood_oxygen = data.get(
                "baseline_blood_oxygen", profile.baseline_blood_oxygen
            )
            profile.baseline_weight = data.get(
                "baseline_weight", profile.baseline_weight
            )
            profile.baseline_blood_pressure_sbp = data.get(
                "baseline_blood_pressure_sbp", profile.baseline_blood_pressure_sbp
            )
            profile.baseline_blood_pressure_dbp = data.get(
                "baseline_blood_pressure_dbp", profile.baseline_blood_pressure_dbp
            )
            profile.baseline_heart_rate = data.get(
                "baseline_heart_rate", profile.baseline_heart_rate
            )
            profile.baseline_steps = data.get(
                "baseline_steps", profile.baseline_steps
            )
            
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
            profile.remark = remark
            profile.baseline_body_temperature = data.get("baseline_body_temperature")
            profile.baseline_blood_oxygen = data.get("baseline_blood_oxygen")
            profile.baseline_weight = data.get("baseline_weight")
            profile.baseline_blood_pressure_sbp = data.get("baseline_blood_pressure_sbp")
            profile.baseline_blood_pressure_dbp = data.get("baseline_blood_pressure_dbp")
            profile.baseline_heart_rate = data.get("baseline_heart_rate")
            profile.baseline_steps = data.get("baseline_steps")

            # 3. 销售归属处理 (仅当档案无销售时，继承 User 的潜客归属)
            if not profile.sales and getattr(user, "bound_sales", None):
                profile.sales = user.bound_sales
                # 归属转移后，清空潜客标记
                user.bound_sales = None
                user.save(update_fields=["bound_sales"])

            profile.save()

        return profile

    def assign_doctor(
        self,
        patient: PatientProfile,
        doctor_id: Optional[int],
        sales_user: CustomUser,
    ) -> PatientProfile:
        """
        【功能说明】
        - 为患者设置主治医生，并同步更新工作室归属记录。

        【使用方法】
        - patient_service.assign_doctor(patient, doctor_id, sales_user)

        【参数说明】
        - patient: PatientProfile 实例。
        - doctor_id: int | None，绑定医生 ID。
        - sales_user: CustomUser，执行绑定的销售账号。

        【返回值说明】
        - PatientProfile 实例。
        """

        if not hasattr(sales_user, "sales_profile"):
            raise ValidationError("当前账号无销售档案")

        doctor = None
        if doctor_id:
            doctor = (
                sales_user.sales_profile.doctors.filter(pk=doctor_id).first()
            )
            if doctor is None:
                raise ValidationError("医生不存在或无权绑定")

        with transaction.atomic():
            patient.doctor = doctor
            patient.save(update_fields=["doctor", "updated_at"])

            if doctor and doctor.studio:
                from chat.services.chat import ChatService

                ChatService().transfer_patient_to_studio(
                    patient=patient,
                    target_studio=doctor.studio,
                    operator=sales_user,
                    reason="绑定主治医生",
                )
        return patient

    def get_active_studio_assignment(self, patient: PatientProfile):
        """
        【功能说明】
        - 获取患者当前有效的工作室归属记录（end_at 为空视为有效）。

        【使用方法】
        - patient_service.get_active_studio_assignment(patient)

        【参数说明】
        - patient: PatientProfile 实例。

        【返回值说明】
        - PatientStudioAssignment | None
        """
        if patient is None:
            raise ValidationError("患者档案不能为空。")

        from chat.models import PatientStudioAssignment

        return (
            PatientStudioAssignment.objects.filter(patient=patient, end_at__isnull=True)
            .order_by("-start_at")
            .first()
        )

# TODO : 依从性计算。用药， 数据监测。
