import re
from datetime import date, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from core.models import TreatmentCycle, choices
from users.choices import UserType
from users.models import CustomUser, DoctorProfile, PatientProfile
from web_doctor.views import workspace


class SettingsCycleSortingSelectionTests(TestCase):
    def setUp(self):
        self.doctor_user = CustomUser.objects.create_user(
            username="doctor_cycle_sort",
            password="password123",
            user_type=UserType.DOCTOR,
            phone="13900007770",
        )
        self.doctor_profile = DoctorProfile.objects.create(user=self.doctor_user, name="张医生")

        patient_user = CustomUser.objects.create_user(
            username="patient_cycle_sort",
            password="password123",
            user_type=UserType.PATIENT,
            phone="13800007770",
            wx_openid="openid_cycle_sort",
        )
        self.patient = PatientProfile.objects.create(
            user=patient_user,
            doctor=self.doctor_profile,
            name="患者B",
            phone="13800007770",
            is_active=True,
        )
        self.client.login(username="doctor_cycle_sort", password="password123")

    def _patch_settings_dependencies(self):
        patches = [
            patch("web_doctor.views.workspace.get_active_medication_library", return_value=[]),
            patch("web_doctor.views.workspace.PlanItemService.get_cycle_plan_view", return_value={}),
            patch("web_doctor.views.workspace.MedicalHistoryService.get_last_medical_history", return_value=None),
            patch("web_doctor.views.workspace.get_active_treatment_cycle", return_value=None),
            patch("web_doctor.views.workspace.PatientService"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        patient_service_mock = workspace.PatientService.return_value
        patient_service_mock.get_patient_family_members.return_value = []

    def test_sort_cycles_prioritizes_in_progress_then_not_started_then_completed_then_terminated(self):
        today = date.today()
        cycles = [
            TreatmentCycle(
                patient=self.patient,
                name="未来疗程",
                start_date=today + timedelta(days=10),
                end_date=today + timedelta(days=30),
                cycle_days=21,
                status=choices.TreatmentCycleStatus.IN_PROGRESS,
            ),
            TreatmentCycle(
                patient=self.patient,
                name="已终止疗程",
                start_date=today - timedelta(days=5),
                end_date=today + timedelta(days=10),
                cycle_days=21,
                status=choices.TreatmentCycleStatus.TERMINATED,
            ),
            TreatmentCycle(
                patient=self.patient,
                name="进行中疗程",
                start_date=today - timedelta(days=2),
                end_date=today + timedelta(days=5),
                cycle_days=21,
                status=choices.TreatmentCycleStatus.IN_PROGRESS,
            ),
            TreatmentCycle(
                patient=self.patient,
                name="已结束疗程",
                start_date=today - timedelta(days=30),
                end_date=today - timedelta(days=10),
                cycle_days=21,
                status=choices.TreatmentCycleStatus.IN_PROGRESS,
            ),
        ]

        sorted_cycles = workspace._sort_cycles_for_settings(cycles, today=today)
        self.assertEqual(
            [c.name for c in sorted_cycles],
            ["进行中疗程", "未来疗程", "已结束疗程", "已终止疗程"],
        )

    def test_default_selected_cycle_is_first_in_sorted_list_when_in_progress_exists(self):
        self._patch_settings_dependencies()
        today = date.today()

        TreatmentCycle.objects.create(
            patient=self.patient,
            name="未来疗程",
            start_date=today + timedelta(days=10),
            end_date=today + timedelta(days=30),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        in_progress = TreatmentCycle.objects.create(
            patient=self.patient,
            name="进行中疗程",
            start_date=today - timedelta(days=2),
            end_date=today + timedelta(days=5),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        TreatmentCycle.objects.create(
            patient=self.patient,
            name="已结束疗程",
            start_date=today - timedelta(days=30),
            end_date=today - timedelta(days=10),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )

        context = workspace._build_settings_context(self.patient)
        self.assertIsNotNone(context.get("selected_cycle"))
        self.assertEqual(context["selected_cycle"].id, in_progress.id)
        self.assertEqual(context["cycle_page"].object_list[0].id, in_progress.id)

    def test_no_in_progress_keeps_original_order_and_selects_first(self):
        self._patch_settings_dependencies()
        today = date.today()

        future = TreatmentCycle.objects.create(
            patient=self.patient,
            name="未来疗程",
            start_date=today + timedelta(days=10),
            end_date=today + timedelta(days=30),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        TreatmentCycle.objects.create(
            patient=self.patient,
            name="已终止疗程",
            start_date=today - timedelta(days=5),
            end_date=today + timedelta(days=10),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.TERMINATED,
        )
        TreatmentCycle.objects.create(
            patient=self.patient,
            name="已结束疗程",
            start_date=today - timedelta(days=30),
            end_date=today - timedelta(days=10),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )

        context = workspace._build_settings_context(self.patient)
        self.assertIsNotNone(context.get("selected_cycle"))
        self.assertEqual(context["selected_cycle"].id, future.id)

        page_names = [c.name for c in context["cycle_page"].object_list]
        self.assertEqual(page_names[0], "未来疗程")

    def test_settings_page_renders_selected_in_progress_first(self):
        self._patch_settings_dependencies()
        today = date.today()

        future = TreatmentCycle.objects.create(
            patient=self.patient,
            name="未来疗程",
            start_date=today + timedelta(days=10),
            end_date=today + timedelta(days=30),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        in_progress = TreatmentCycle.objects.create(
            patient=self.patient,
            name="进行中疗程",
            start_date=today - timedelta(days=2),
            end_date=today + timedelta(days=5),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        naturally_finished = TreatmentCycle.objects.create(
            patient=self.patient,
            name="自然结束疗程",
            start_date=today - timedelta(days=30),
            end_date=today - timedelta(days=10),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        terminated = TreatmentCycle.objects.create(
            patient=self.patient,
            name="已终止疗程",
            start_date=today - timedelta(days=8),
            end_date=today + timedelta(days=8),
            cycle_days=17,
            status=choices.TreatmentCycleStatus.TERMINATED,
        )

        url = reverse("web_doctor:patient_workspace_section", args=[self.patient.id, "settings"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "当前选中：")
        self.assertContains(response, "进行中疗程")

        html = response.content.decode("utf-8")
        self.assertLess(html.find("进行中疗程"), html.find("未来疗程"))
        row_tags = re.findall(r'<div[^>]*data-cycle-select-row[^>]*>', html)
        selected_row = next(row for row in row_tags if f'data-cycle-id="{in_progress.id}"' in row)
        unselected_row = next(row for row in row_tags if f'data-cycle-id="{future.id}"' in row)

        self.assertIn("border-indigo-200", selected_row)
        self.assertIn("bg-indigo-50", selected_row)
        self.assertIn('aria-current="true"', selected_row)
        self.assertNotIn("hx-get=", selected_row)

        self.assertIn("hx-get=", unselected_row)
        self.assertIn(f"cycle_id={future.id}", unselected_row)
        self.assertIn("data-cycle-rename-row", unselected_row)
        self.assertIn("[data-quick-cycle-open]", unselected_row)
        self.assertContains(response, "data-quick-cycle-open")
        self.assertContains(response, "创建并复制疗程计划")

        history_marker = '<h4 class="text-sm font-semibold text-slate-700">历史疗程</h4>'
        current_section = html.split(history_marker, 1)[0]
        history_section = html.split(history_marker, 1)[1].split("创建新疗程", 1)[0]
        self.assertIn("进行中疗程", current_section)
        self.assertIn("未来疗程", current_section)
        self.assertNotIn("自然结束疗程", current_section)
        self.assertIn("自然结束疗程", history_section)
        self.assertIn("已终止疗程", history_section)

        history_row_tags = re.findall(r'<div[^>]*data-history-cycle-row[^>]*>', html)
        natural_history_row = next(
            row for row in history_row_tags if f'data-cycle-id="{naturally_finished.id}"' in row
        )
        terminated_history_row = next(
            row for row in history_row_tags if f'data-cycle-id="{terminated.id}"' in row
        )
        plan_table_url = reverse("web_doctor:patient_settings_plan_table", args=[self.patient.id])
        self.assertIn("hx-get=", natural_history_row)
        self.assertIn(
            f"{plan_table_url}?cycle_id={naturally_finished.id}&detail_context=history",
            natural_history_row,
        )
        self.assertIn('hx-target="#history-plan-table-slot"', natural_history_row)
        self.assertIn('hx-swap="innerHTML"', natural_history_row)
        self.assertIn("cursor-pointer", natural_history_row)
        self.assertIn("hover:bg-slate-50", natural_history_row)
        self.assertIn("[data-quick-cycle-open]", natural_history_row)
        self.assertNotIn("aria-current", natural_history_row)
        self.assertIn("hx-get=", terminated_history_row)
        self.assertIn(
            f"{plan_table_url}?cycle_id={terminated.id}&detail_context=history",
            terminated_history_row,
        )
        self.assertIn('hx-target="#history-plan-table-slot"', terminated_history_row)
        self.assertIn('hx-swap="innerHTML"', terminated_history_row)
        self.assertIn("cursor-pointer", terminated_history_row)
        self.assertIn("hover:bg-slate-50", terminated_history_row)
        self.assertIn("[data-quick-cycle-open]", terminated_history_row)
        self.assertNotIn("aria-current", terminated_history_row)
        self.assertIn('id="history-plan-table-slot"', history_section)
        self.assertNotIn("点击历史疗程查看配置详情", history_section)
        self.assertNotIn('id="history-plan-empty-template"', history_section)
        self.assertNotIn('data-history-plan-empty-state', history_section)
        self.assertIn("__historyCycleDetailHooksInstalled", html)
        rename_url = reverse(
            "web_doctor:patient_treatment_cycle_rename",
            args=[self.patient.id, naturally_finished.id],
        )
        self.assertNotIn(rename_url, html)

    def test_historical_cycle_id_is_not_selected_but_history_row_can_load_detail(self):
        self._patch_settings_dependencies()
        today = date.today()
        current = TreatmentCycle.objects.create(
            patient=self.patient,
            name="当前疗程",
            start_date=today - timedelta(days=2),
            end_date=today + timedelta(days=5),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        historical = TreatmentCycle.objects.create(
            patient=self.patient,
            name="历史疗程A",
            start_date=today - timedelta(days=30),
            end_date=today - timedelta(days=10),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.COMPLETED,
        )

        url = reverse("web_doctor:patient_workspace_section", args=[self.patient.id, "settings"])
        response = self.client.get(f"{url}?cycle_id={historical.id}")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "当前选中：")
        plan_table_url = reverse("web_doctor:patient_settings_plan_table", args=[self.patient.id])
        self.assertContains(response, f'hx-get="{plan_table_url}?cycle_id={current.id}"')
        html = response.content.decode("utf-8")
        row_tags = re.findall(r'<div[^>]*data-cycle-select-row[^>]*>', html)
        self.assertTrue(any(f'data-cycle-id="{current.id}"' in row for row in row_tags))
        self.assertFalse(any(f'data-cycle-id="{historical.id}"' in row for row in row_tags))
        history_row_tags = re.findall(r'<div[^>]*data-history-cycle-row[^>]*>', html)
        historical_row = next(row for row in history_row_tags if f'data-cycle-id="{historical.id}"' in row)
        self.assertIn(f'{plan_table_url}?cycle_id={historical.id}&detail_context=history', historical_row)
        self.assertIn('hx-target="#history-plan-table-slot"', historical_row)
        self.assertIn(f'hx-get="{plan_table_url}?cycle_id={current.id}"', html)

    def test_no_current_cycles_does_not_select_or_load_history(self):
        self._patch_settings_dependencies()
        today = date.today()
        historical = TreatmentCycle.objects.create(
            patient=self.patient,
            name="仅历史疗程",
            start_date=today - timedelta(days=30),
            end_date=today - timedelta(days=10),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )

        context = workspace._build_settings_context(self.patient, selected_cycle_id=historical.id)
        self.assertIsNone(context.get("selected_cycle"))
        self.assertEqual(context["cycle_page"].paginator.count, 0)
        self.assertEqual([c.id for c in context["history_cycles"]], [historical.id])

    def test_settings_page_renders_day_28_for_28_day_cycle(self):
        self._patch_settings_dependencies()
        today = date.today()
        cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="28天疗程",
            start_date=today,
            end_date=today + timedelta(days=27),
            cycle_days=28,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )

        url = reverse("web_doctor:patient_workspace_section", args=[self.patient.id, "settings"])
        response = self.client.get(f"{url}?cycle_id={cycle.id}")
        self.assertEqual(response.status_code, 200)
        plan_table_url = reverse("web_doctor:patient_settings_plan_table", args=[self.patient.id])
        self.assertContains(response, 'id="plan-table-slot"')
        self.assertContains(response, f'hx-get="{plan_table_url}?cycle_id={cycle.id}"')

    def test_settings_plan_table_fragment_renders_day_28_for_28_day_cycle(self):
        self._patch_settings_dependencies()
        today = date.today()
        cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="28天疗程",
            start_date=today,
            end_date=today + timedelta(days=27),
            cycle_days=28,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )

        url = reverse("web_doctor:patient_settings_plan_table", args=[self.patient.id])
        response = self.client.get(f"{url}?cycle_id={cycle.id}")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-plan-day="28"')
        self.assertContains(response, "D28")

    def test_history_plan_table_fragment_renders_history_wrapper(self):
        self._patch_settings_dependencies()
        today = date.today()
        cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="历史详情疗程",
            start_date=today - timedelta(days=30),
            end_date=today - timedelta(days=10),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.COMPLETED,
        )

        url = reverse("web_doctor:patient_settings_plan_table", args=[self.patient.id])
        response = self.client.get(f"{url}?cycle_id={cycle.id}&detail_context=history")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "历史疗程配置详情")
        self.assertContains(response, "历史详情疗程")
        self.assertContains(response, str(cycle.start_date))
        self.assertContains(response, str(cycle.end_date))
        self.assertContains(response, cycle.get_status_display())
        self.assertContains(response, "关闭配置详情")
        self.assertContains(response, "data-history-plan-close")
        self.assertContains(response, 'id="history-plan-table-container"')
        self.assertContains(response, 'id="history-plan-day-tooltip"')
        self.assertNotContains(response, 'id="plan-table-container"')
