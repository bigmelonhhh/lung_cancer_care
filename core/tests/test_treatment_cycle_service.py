"""treatment_cycle service 测试：分页/排序与确认人查询。"""

from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from core.models import PlanItem, TreatmentCycle, choices
from core.service.treatment_cycle import get_cycle_confirmer, get_treatment_cycles
from users import choices as user_choices
from users.models import CustomUser, PatientProfile


class TreatmentCycleServiceTest(TestCase):
    """测试 get_treatment_cycles 分页与排序逻辑。"""

    def setUp(self) -> None:
        self.patient = PatientProfile.objects.create(
            phone="13900000000",
            name="分页患者",
        )

        # 创建 15 条疗程，start_date 依次递增，便于验证倒序排序
        base_date = date(2025, 1, 1)
        for i in range(15):
            TreatmentCycle.objects.create(
                patient=self.patient,
                name=f"疗程{i}",
                start_date=base_date + timedelta(days=i),
                cycle_days=21,
                status=choices.TreatmentCycleStatus.IN_PROGRESS,
            )

    def test_get_treatment_cycles_default_first_page(self):
        """默认第一页，每页 10 条，按 start_date 倒序。"""

        page = get_treatment_cycles(self.patient)

        # 默认分页大小
        self.assertEqual(page.paginator.per_page, 10)
        self.assertEqual(page.number, 1)
        self.assertEqual(len(page.object_list), 10)

        # 第一条应是最新的疗程（start_date 最大）
        first_cycle = page.object_list[0]
        self.assertEqual(first_cycle.name, "疗程14")

    def test_get_treatment_cycles_second_page(self):
        """第二页应包含剩余 5 条记录。"""

        page = get_treatment_cycles(self.patient, page=2)

        self.assertEqual(page.number, 2)
        self.assertEqual(len(page.object_list), 5)

        # 第二页第一条应是按倒序的第 11 条
        first_cycle_second_page = page.object_list[0]
        self.assertEqual(first_cycle_second_page.name, "疗程4")


class TreatmentCycleConfirmerTest(TestCase):
    """测试疗程确认人查询逻辑。"""

    def setUp(self) -> None:
        self.patient = PatientProfile.objects.create(
            phone="13900000006",
            name="确认人患者",
        )
        self.cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="确认人疗程",
            start_date=date(2025, 1, 1),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        self.doctor = CustomUser.objects.create_user(
            username="doctor_confirm",
            password="password",
            user_type=user_choices.UserType.DOCTOR,
            phone="13900000007",
        )
        self.assistant = CustomUser.objects.create_user(
            username="assistant_confirm",
            password="password",
            user_type=user_choices.UserType.ASSISTANT,
            phone="13900000008",
        )

    def test_get_cycle_confirmer_returns_latest_updated_by(self):
        plan_early = PlanItem.objects.create(
            cycle=self.cycle,
            category=choices.PlanItemCategory.MEDICATION,
            template_id=1,
            item_name="化疗用药A",
            schedule_days=[1],
            status=choices.PlanItemStatus.ACTIVE,
            updated_by=self.doctor,
        )
        PlanItem.objects.filter(pk=plan_early.id).update(
            updated_at=timezone.now() - timedelta(days=1)
        )
        PlanItem.objects.create(
            cycle=self.cycle,
            category=choices.PlanItemCategory.MEDICATION,
            template_id=2,
            item_name="化疗用药B",
            schedule_days=[2],
            status=choices.PlanItemStatus.ACTIVE,
            updated_by=self.assistant,
        )

        confirmer = get_cycle_confirmer(self.cycle.id)

        self.assertIsNotNone(confirmer)
        self.assertEqual(confirmer.id, self.assistant.id)

    def test_get_cycle_confirmer_returns_none_when_missing(self):
        PlanItem.objects.create(
            cycle=self.cycle,
            category=choices.PlanItemCategory.MEDICATION,
            template_id=3,
            item_name="化疗用药C",
            schedule_days=[3],
            status=choices.PlanItemStatus.ACTIVE,
            updated_by=None,
        )

        confirmer = get_cycle_confirmer(self.cycle.id)

        self.assertIsNone(confirmer)
