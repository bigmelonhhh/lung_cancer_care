from datetime import date, datetime, timedelta
from decimal import Decimal
from django.template.loader import render_to_string
from django.test import TestCase
from django.utils import timezone
from unittest.mock import MagicMock, patch

from core.models import (
    CheckupFieldMapping,
    CheckupLibrary,
    DailyTask,
    MonitoringTemplate,
    PlanItem,
    Questionnaire,
    QuestionnaireCode,
    StandardField,
    StandardFieldValueType,
    TreatmentCycle,
)
from core.models import choices as core_choices
from health_data.models import (
    CheckupResultValue,
    ClinicalEvent,
    HealthMetric,
    MetricType,
    QuestionnaireSubmission,
    ReportImage,
    ReportUpload,
)
from market.models import Order, Product
from users.models import CustomUser, PatientProfile, DoctorStudio, DoctorProfile
from users import choices as user_choices
from chat.models import ConversationSession, ConversationType, Conversation
from web_doctor.views.management_stats import ManagementStatsView

class TestManagementStatsChatIntegration(TestCase):
    def setUp(self):
        # Create user and patient
        self.user = CustomUser.objects.create_user(
            username='testuser', 
            password='password',
            wx_openid='test_openid'
        )
        self.patient = PatientProfile.objects.create(user=self.user, name="Test Patient")
        
        # Create doctor and studio
        self.doctor_user = CustomUser.objects.create_user(
            username='doctor',
            password='password',
            user_type=user_choices.UserType.DOCTOR,
            phone="13800138000"
        )
        self.doctor_profile = DoctorProfile.objects.create(user=self.doctor_user, name="Test Doctor")
        self.studio = DoctorStudio.objects.create(name="Test Studio", owner_doctor=self.doctor_profile)
        
        # Create Conversation
        self.conversation = Conversation.objects.create(
            patient=self.patient,
            studio=self.studio,
            type=ConversationType.PATIENT_STUDIO
        )
        
        self.view = ManagementStatsView()
        
        self.start_date = date(2025, 1, 1)
        self.end_date = date(2025, 3, 31)

    def test_generate_query_stats_empty(self):
        """Test with no data"""
        stats = self.view._generate_query_stats(self.patient, self.start_date, self.end_date)
        
        self.assertEqual(stats['total_count'], 0)
        self.assertEqual(len(stats['line_chart']['xAxis']), 3) # Jan, Feb, Mar
        self.assertEqual(stats['line_chart']['series'][0]['data'], [0, 0, 0])
        self.assertEqual(len(stats['pie_chart']['series']), 0)

    def test_generate_query_stats_with_data(self):
        """Test with some conversation sessions"""
        # Create sessions
        # 1. Jan 15, 08:00 (Slot 7-10)
        ConversationSession.objects.create(
            conversation=self.conversation,
            patient=self.patient,
            conversation_type=ConversationType.PATIENT_STUDIO,
            start_at=timezone.make_aware(datetime(2025, 1, 15, 8, 0)),
            end_at=timezone.make_aware(datetime(2025, 1, 15, 8, 30)),
            message_count=5
        )
        
        # 2. Feb 10, 14:00 (Slot 13-18)
        ConversationSession.objects.create(
            conversation=self.conversation,
            patient=self.patient,
            conversation_type=ConversationType.PATIENT_STUDIO,
            start_at=timezone.make_aware(datetime(2025, 2, 10, 14, 0)),
            end_at=timezone.make_aware(datetime(2025, 2, 10, 14, 30)),
            message_count=5
        )
        
        # 3. Feb 20, 15:00 (Slot 13-18)
        ConversationSession.objects.create(
            conversation=self.conversation,
            patient=self.patient,
            conversation_type=ConversationType.PATIENT_STUDIO,
            start_at=timezone.make_aware(datetime(2025, 2, 20, 15, 0)),
            end_at=timezone.make_aware(datetime(2025, 2, 20, 15, 30)),
            message_count=5
        )

        stats = self.view._generate_query_stats(self.patient, self.start_date, self.end_date)
        
        self.assertEqual(stats['total_count'], 3)
        
        # Line chart: Jan=1, Feb=2, Mar=0
        self.assertEqual(stats['line_chart']['xAxis'], ['2025-01', '2025-02', '2025-03'])
        self.assertEqual(stats['line_chart']['series'][0]['data'], [1, 2, 0])
        
        # Pie chart: 
        # 7-10: 1
        # 13-18: 2
        series = stats['pie_chart']['series']
        self.assertEqual(len(series), 2)
        
        slot_7_10 = next((item for item in series if item['name'] == '07:00-10:00'), None)
        self.assertIsNotNone(slot_7_10)
        self.assertEqual(slot_7_10['value'], 1)
        
        slot_13_18 = next((item for item in series if item['name'] == '13:00-18:00'), None)
        self.assertIsNotNone(slot_13_18)
        self.assertEqual(slot_13_18['value'], 2)

    def test_generate_query_stats_missing_args(self):
        """Test with missing arguments"""
        stats = self.view._generate_query_stats(None, None, None)
        self.assertEqual(stats['total_count'], 0)

    @patch('chat.services.chat.ChatService.get_patient_chat_session_stats')
    def test_generate_query_stats_exception(self, mock_get_stats):
        """Test exception handling"""
        mock_get_stats.side_effect = Exception("DB Error")
        
        stats = self.view._generate_query_stats(self.patient, self.start_date, self.end_date)
        self.assertEqual(stats['total_count'], 0)
        self.assertEqual(len(stats['line_chart']['xAxis']), 0)

    def test_generate_charts_data_includes_oral_mucosa_questionnaire(self):
        questionnaire = Questionnaire.objects.create(
            code=QuestionnaireCode.Q_KQNMLB,
            name="口腔黏膜损伤自评量表",
            is_active=True,
        )
        submission = QuestionnaireSubmission.objects.create(
            patient=self.patient,
            questionnaire=questionnaire,
            total_score=Decimal("2"),
        )
        QuestionnaireSubmission.objects.filter(pk=submission.pk).update(
            created_at=timezone.make_aware(datetime(2025, 2, 10, 9, 0))
        )

        charts = self.view._generate_questionnaire_count_charts(
            self.patient,
            self.start_date,
            self.end_date,
        )

        self.assertEqual(charts[0]["dates"], ["2025-01", "2025-02", "2025-03"])
        self.assertEqual(charts[0]["series"][0]["data"], [0, 1, 0])
        self.assertEqual(charts[0]["title"], "口腔黏膜损伤自评量表统计次数: 1次")

    def test_questionnaire_count_charts_use_active_submission_catalog(self):
        Questionnaire.objects.update(is_active=False)
        active = Questionnaire.objects.create(
            code="Q_DYNAMIC_STATS",
            name="运营新增问卷 A",
            is_active=True,
        )
        Questionnaire.objects.create(
            code="Q_DISABLED_STATS",
            name="停用问卷",
            is_active=False,
        )
        for submitted_at in (
            datetime(2025, 1, 10, 9, 0),
            datetime(2025, 1, 20, 9, 0),
        ):
            submission = QuestionnaireSubmission.objects.create(
                patient=self.patient,
                questionnaire=active,
                total_score=Decimal("5"),
            )
            QuestionnaireSubmission.objects.filter(pk=submission.pk).update(
                created_at=timezone.make_aware(submitted_at)
            )

        charts = self.view._generate_questionnaire_count_charts(
            self.patient,
            self.start_date,
            self.end_date,
        )

        self.assertEqual([item["questionnaire_id"] for item in charts], [active.id])
        self.assertEqual(charts[0]["series"][0]["data"], [2, 0, 0])
        self.assertEqual(charts[0]["submission_count"], 2)

    def test_get_context_data_uses_actual_overview_counts_for_selected_package(self):
        product = Product.objects.create(
            name="年度服务包",
            price=Decimal("199.00"),
            duration_days=90,
        )
        Order.objects.create(
            patient=self.patient,
            product=product,
            amount=Decimal("199.00"),
            status=Order.Status.PAID,
            paid_at=timezone.make_aware(datetime(2025, 1, 1, 9, 0)),
        )
        cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="测试疗程",
            start_date=self.start_date,
            end_date=self.end_date,
            cycle_days=90,
        )

        medication = PlanItem.objects.create(
            cycle=cycle,
            category=core_choices.PlanItemCategory.MEDICATION,
            template_id=1,
            item_name="靶向药",
            schedule_days=[1, 2, 3],
        )
        monitor_template, _ = MonitoringTemplate.objects.get_or_create(
            code=MetricType.BLOOD_PRESSURE,
            defaults={
                "name": "血压",
                "metric_type": MetricType.BLOOD_PRESSURE,
            },
        )
        monitoring = PlanItem.objects.create(
            cycle=cycle,
            category=core_choices.PlanItemCategory.MONITORING,
            template_id=monitor_template.id,
            item_name="血压",
            schedule_days=[1, 2],
        )
        for day_offset in range(3):
            DailyTask.objects.create(
                patient=self.patient,
                plan_item=medication,
                task_date=self.start_date + timedelta(days=day_offset),
                task_type=core_choices.PlanItemCategory.MEDICATION,
                title="用药",
                status=core_choices.TaskStatus.COMPLETED,
                completed_at=timezone.make_aware(
                    datetime.combine(
                        self.start_date + timedelta(days=day_offset),
                        datetime.min.time(),
                    )
                ),
            )
        DailyTask.objects.create(
            patient=self.patient,
            plan_item=monitoring,
            task_date=self.start_date,
            task_type=core_choices.PlanItemCategory.MONITORING,
            title="血压",
            status=core_choices.TaskStatus.COMPLETED,
            completed_at=timezone.make_aware(datetime(2025, 1, 1, 10, 0)),
        )
        DailyTask.objects.create(
            patient=self.patient,
            plan_item=monitoring,
            task_date=self.start_date + timedelta(days=1),
            task_type=core_choices.PlanItemCategory.MONITORING,
            title="血压",
            status=core_choices.TaskStatus.PENDING,
        )

        for hour in (8, 20):
            HealthMetric.objects.create(
                patient=self.patient,
                metric_type=MetricType.USE_MEDICATED,
                measured_at=timezone.make_aware(datetime(2025, 1, 1, hour, 0)),
            )
        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BLOOD_PRESSURE,
            measured_at=timezone.make_aware(datetime(2025, 1, 1, 11, 0)),
        )
        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BLOOD_PRESSURE,
            measured_at=timezone.make_aware(datetime(2025, 1, 2, 11, 0)),
        )

        ConversationSession.objects.create(
            conversation=self.conversation,
            patient=self.patient,
            conversation_type=ConversationType.PATIENT_STUDIO,
            start_at=timezone.make_aware(datetime(2025, 1, 3, 8, 0)),
            end_at=timezone.make_aware(datetime(2025, 1, 3, 8, 30)),
        )
        questionnaire = Questionnaire.objects.create(code="Q_STATS", name="随访问卷")
        submission = QuestionnaireSubmission.objects.create(
            patient=self.patient,
            questionnaire=questionnaire,
        )
        submission.created_at = timezone.make_aware(datetime(2025, 1, 3, 9, 0))
        submission.save(update_fields=["created_at"])
        ClinicalEvent.objects.create(
            patient=self.patient,
            event_date=date(2025, 1, 4),
            event_type=3,
        )
        ClinicalEvent.objects.create(
            patient=self.patient,
            event_date=date(2025, 1, 5),
            event_type=2,
        )

        context = self.view.get_context_data(self.patient)
        overview = context["stats_overview"]

        self.assertEqual(overview["medication_taken"], 2)
        self.assertEqual(overview["medication_compliance"], "100%")
        self.assertEqual(overview["indicators_monitoring"], 2)
        self.assertEqual(overview["indicators_recorded"], 2)
        self.assertEqual(overview["monitoring_compliance"], "50%")
        self.assertEqual(overview["online_consultation"], 1)
        self.assertEqual(overview["follow_up"], 1)
        self.assertEqual(overview["checkup"], 1)
        self.assertEqual(overview["hospitalization"], 1)
        self.assertEqual(sum(context["charts"]["medication"]["series"][0]["data"]), 2)

    def test_get_context_data_shows_dash_for_medication_compliance_without_uploads(self):
        product = Product.objects.create(
            name="年度服务包",
            price=Decimal("199.00"),
            duration_days=90,
        )
        Order.objects.create(
            patient=self.patient,
            product=product,
            amount=Decimal("199.00"),
            status=Order.Status.PAID,
            paid_at=timezone.make_aware(datetime(2025, 1, 1, 9, 0)),
        )
        cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="测试疗程",
            start_date=self.start_date,
            end_date=self.end_date,
            cycle_days=90,
        )
        medication = PlanItem.objects.create(
            cycle=cycle,
            category=core_choices.PlanItemCategory.MEDICATION,
            template_id=1,
            item_name="靶向药",
            schedule_days=[1, 2],
        )
        for day_offset in range(2):
            DailyTask.objects.create(
                patient=self.patient,
                plan_item=medication,
                task_date=self.start_date + timedelta(days=day_offset),
                task_type=core_choices.PlanItemCategory.MEDICATION,
                title="用药",
                status=core_choices.TaskStatus.PENDING,
            )

        overview = self.view.get_context_data(self.patient)["stats_overview"]

        self.assertEqual(overview["medication_taken"], 0)
        self.assertEqual(overview["medication_compliance"], "-")

    def _create_followup_mapping(self):
        checkup = CheckupLibrary.objects.create(
            name="血常规",
            code="BLOOD_ROUTINE_STATS",
            is_active=True,
        )
        field = StandardField.objects.create(
            local_code="WBC_STATS",
            chinese_name="白细胞计数",
            english_abbr="WBC",
            value_type=StandardFieldValueType.DECIMAL,
            default_unit="10^9/L",
            is_active=True,
        )
        mapping = CheckupFieldMapping.objects.create(
            checkup_item=checkup,
            standard_field=field,
            is_active=True,
        )
        self.patient.indicator_preferences = {
            "version": 1,
            "followup_review": {"selected_mapping_ids": [mapping.id]},
        }
        self.patient.save(update_fields=["indicator_preferences"])
        return checkup, field, mapping

    def _create_result_value(self, checkup, field, report_date, value, image_url):
        upload = ReportUpload.objects.create(patient=self.patient)
        image = ReportImage.objects.create(
            upload=upload,
            image_url=image_url,
            record_type=ReportImage.RecordType.CHECKUP,
            checkup_item=checkup,
            report_date=report_date,
        )
        return CheckupResultValue.objects.create(
            patient=self.patient,
            report_image=image,
            checkup_item=checkup,
            standard_field=field,
            report_date=report_date,
            raw_name=field.chinese_name,
            raw_value=str(value),
            value_numeric=Decimal(str(value)),
            unit=field.default_unit,
        )

    def test_generate_followup_review_charts_counts_distinct_days_by_month(self):
        checkup, field, _ = self._create_followup_mapping()
        self._create_result_value(checkup, field, date(2025, 1, 10), "5.1", "https://example.com/1.png")
        self._create_result_value(checkup, field, date(2025, 2, 10), "5.2", "https://example.com/2.png")
        self._create_result_value(checkup, field, date(2025, 2, 11), "5.3", "https://example.com/3.png")

        charts = self.view._generate_followup_review_charts(
            self.patient,
            self.start_date,
            self.end_date,
        )

        self.assertEqual(len(charts), 1)
        self.assertEqual(charts[0]["dates"], ["2025-01", "2025-02", "2025-03"])
        self.assertEqual(charts[0]["series"][0]["data"], [1, 2, 0])
        self.assertEqual(charts[0]["series"][0]["name"], "统计次数")
        self.assertEqual(charts[0]["title"], "复查指标-血常规-白细胞计数统计次数: 3次")

    def test_generate_followup_review_charts_deduplicates_same_metric_same_day(self):
        checkup, field, _ = self._create_followup_mapping()
        self._create_result_value(checkup, field, date(2025, 2, 10), "5.1", "https://example.com/1.png")
        self._create_result_value(checkup, field, date(2025, 2, 10), "5.2", "https://example.com/2.png")

        charts = self.view._generate_followup_review_charts(
            self.patient,
            self.start_date,
            self.end_date,
        )

        self.assertEqual(charts[0]["series"][0]["data"], [0, 1, 0])
        self.assertEqual(charts[0]["title"], "复查指标-血常规-白细胞计数统计次数: 1次")

    def test_generate_followup_review_charts_empty_without_preferences(self):
        charts = self.view._generate_followup_review_charts(
            self.patient,
            self.start_date,
            self.end_date,
        )

        self.assertEqual(charts, [])

    def test_stats_details_template_renders_oral_mucosa_and_followup_review(self):
        chart = {
            "id": "chart-test",
            "title": "测试统计次数: 0次",
            "dates": ["2025-01"],
            "y_min": 0,
            "y_max": 10,
            "series": [{"name": "测试", "data": [0], "color": "#3B82F6"}],
        }
        charts = {
            key: {**chart, "id": f"chart-{key}"}
            for key in [
                "medication",
                "temp",
                "spo2",
                "bp",
                "hr",
                "weight",
                "step",
                "stamina",
                "dyspnea",
                "cough",
                "sputum",
                "pain",
                "sleep",
                "depressed",
                "anxiety",
                "oral_mucosa",
            ]
        }
        charts["oral_mucosa"]["title"] = "口腔黏膜损伤自评量表统计次数: 0次"
        questionnaire_chart = {
            **charts["oral_mucosa"],
            "questionnaire_id": 99,
            "code": QuestionnaireCode.Q_KQNMLB,
            "name": "口腔黏膜损伤自评量表",
            "icon_key": "oral_mucosa",
            "color": "#14B8A6",
            "data_script_id": "questionnaire-count-chart-data-99",
        }

        html = render_to_string(
            "web_doctor/partials/management_stats/stats_details.html",
            {
                "charts": charts,
                "questionnaire_count_charts": [questionnaire_chart],
                "followup_review_charts": [
                    {
                        **chart,
                        "id": "chart-followup-review-stats-1",
                        "title": "复查指标-血常规-白细胞计数统计次数: 2次",
                    }
                ],
            },
        )

        self.assertIn("口腔黏膜损伤自评量表统计次数", html)
        self.assertIn("复查指标", html)
        self.assertIn("复查指标-血常规-白细胞计数统计次数", html)
