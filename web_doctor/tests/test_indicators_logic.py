from datetime import timedelta, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model
from users.models import PatientProfile
from core.models import (
    CheckupFieldMapping,
    CheckupLibrary,
    DailyTask,
    Questionnaire,
    QuestionnaireCode,
    StandardField,
    StandardFieldValueType,
    TreatmentCycle,
    choices,
)
from health_data.models import (
    CheckupResultValue,
    HealthMetric,
    MetricType,
    QuestionnaireSubmission,
    ReportImage,
    ReportUpload,
)
from web_doctor.views.indicators import build_indicators_context

User = get_user_model()

class IndicatorsLogicTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testpatient', password='password', wx_openid='test_openid_123')
        self.patient = PatientProfile.objects.create(user=self.user, name="Test Patient")
        self.today = timezone.localdate()

    def test_default_view_active_cycle(self):
        """测试默认视图按日期返回最近30天，不再默认选疗程"""
        # Create past cycle
        past_start = self.today - timedelta(days=60)
        past_end = self.today - timedelta(days=31)
        TreatmentCycle.objects.create(
            patient=self.patient, 
            name="Cycle 1", 
            start_date=past_start, 
            end_date=past_end,
            status=choices.TreatmentCycleStatus.COMPLETED
        )
        
        # Create active cycle
        active_start = self.today - timedelta(days=10)
        active_end = self.today + timedelta(days=20)
        TreatmentCycle.objects.create(
            patient=self.patient, 
            name="Cycle 2", 
            start_date=active_start, 
            end_date=active_end,
            status=choices.TreatmentCycleStatus.IN_PROGRESS
        )
        
        context = build_indicators_context(self.patient)

        default_start = self.today - timedelta(days=29)
        self.assertEqual(context["current_cycle_id"], "")
        self.assertEqual(context["current_start_date"], default_start.isoformat())
        self.assertEqual(context["current_end_date"], self.today.isoformat())
        self.assertEqual(context["dates"][0], default_start.strftime("%m-%d"))
        self.assertEqual(len(context["dates"]), 30)
        self.assertTrue(context['is_default_view'])
        self.assertEqual(context['current_filter_type'], 'date')

    def test_status_priority(self):
        """测试显式按疗程筛选时使用选中疗程，并保留疗程排序优先级"""
        # Case: Two cycles, one completed (but date matches today?), one in progress.
        # Actually, "completed" usually implies end_date < today, but let's simulate a case
        # where a cycle was manually terminated early but dates might still overlap or be irrelevant if we trust status.
        
        # Cycle 1: Completed, but date range covers today (e.g. terminated early)
        start1 = self.today - timedelta(days=5)
        end1 = self.today + timedelta(days=5)
        c1 = TreatmentCycle.objects.create(
            patient=self.patient,
            name="Terminated Cycle",
            start_date=start1,
            end_date=end1,
            status=choices.TreatmentCycleStatus.COMPLETED
        )

        # Cycle 2: In Progress
        start2 = self.today - timedelta(days=2)
        end2 = self.today + timedelta(days=10)
        c2 = TreatmentCycle.objects.create(
            patient=self.patient,
            name="Active Cycle",
            start_date=start2,
            end_date=end2,
            status=choices.TreatmentCycleStatus.IN_PROGRESS
        )

        context = build_indicators_context(
            self.patient,
            cycle_id=str(c2.id),
            filter_type="cycle",
        )

        self.assertEqual(context["current_filter_type"], "cycle")
        self.assertEqual(context["current_cycle_id"], c2.id)
        self.assertEqual(context["current_start_date"], start2.isoformat())
        self.assertEqual(context["current_end_date"], end2.isoformat())
        self.assertEqual(context["treatment_cycles"][0].id, c2.id)

    def test_default_view_fallback_latest_cycle(self):
        """测试默认视图与疗程无关，固定返回最近30天"""
        # Create past cycle only
        past_start = self.today - timedelta(days=60)
        past_end = self.today - timedelta(days=31)
        TreatmentCycle.objects.create(
            patient=self.patient, 
            name="Cycle 1", 
            start_date=past_start, 
            end_date=past_end,
            status=choices.TreatmentCycleStatus.COMPLETED
        )
        
        context = build_indicators_context(self.patient)

        default_start = self.today - timedelta(days=29)
        self.assertEqual(context["current_cycle_id"], "")
        self.assertEqual(context["current_filter_type"], "date")
        self.assertEqual(context["current_start_date"], default_start.isoformat())
        self.assertEqual(context["current_end_date"], self.today.isoformat())
        self.assertEqual(context["dates"][0], default_start.strftime("%m-%d"))
        self.assertEqual(len(context["dates"]), 30)

    def test_default_view_without_cycles_returns_recent_30_days(self):
        """测试无疗程时默认仍返回最近30天并回填日期"""
        context = build_indicators_context(self.patient)

        default_start = self.today - timedelta(days=29)
        self.assertEqual(context["current_cycle_id"], "")
        self.assertEqual(context["current_filter_type"], "date")
        self.assertEqual(context["current_start_date"], default_start.isoformat())
        self.assertEqual(context["current_end_date"], self.today.isoformat())
        self.assertEqual(context["dates"][0], default_start.strftime("%m-%d"))
        self.assertEqual(len(context["dates"]), 30)

    @patch("web_doctor.views.indicators.QuestionnaireSubmissionService.list_daily_cough_hemoptysis_flags", return_value=[])
    @patch("web_doctor.views.indicators.QuestionnaireSubmissionService.list_daily_questionnaire_scores", return_value=[])
    @patch("web_doctor.views.indicators.get_adherence_metrics_batch", return_value=[])
    @patch("web_doctor.views.indicators.HealthMetricService.query_metrics_by_type", return_value=SimpleNamespace(object_list=[]))
    def test_default_view_questionnaire_queries_recent_30_days(self, _mock_query, _mock_adherence, mock_scores, _mock_hemoptysis):
        """测试默认视图下问卷查询参数为最近30天"""
        context = build_indicators_context(self.patient)
        expected_start = self.today - timedelta(days=29)
        expected_end = self.today

        self.assertEqual(context["current_start_date"], expected_start.isoformat())
        self.assertEqual(context["current_end_date"], expected_end.isoformat())
        self.assertGreaterEqual(mock_scores.call_count, 1)
        for _, kwargs in mock_scores.call_args_list:
            self.assertEqual(kwargs["start_date"], expected_start)
            self.assertEqual(kwargs["end_date"], expected_end)

    def test_medication_data_future_logic(self):
        """测试服药记录数据结构及未来日期逻辑"""
        # Set range covering yesterday, today, tomorrow
        start_date = self.today - timedelta(days=1)
        end_date = self.today + timedelta(days=1)

        # 昨日有用药任务并已完成
        DailyTask.objects.create(
            patient=self.patient,
            task_date=start_date,
            task_type=choices.PlanItemCategory.MEDICATION,
            title="昨日用药",
            status=choices.TaskStatus.COMPLETED,
        )

        # 今日有用药任务但未完成
        DailyTask.objects.create(
            patient=self.patient,
            task_date=self.today,
            task_type=choices.PlanItemCategory.MEDICATION,
            title="今日用药",
            status=choices.TaskStatus.PENDING,
        )

        # 即使有用药打卡，表格状态仍以任务状态为准（今日应显示未完成）
        measured_at = timezone.make_aware(datetime.combine(self.today, datetime.min.time()))
        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.USE_MEDICATED,
            measured_at=measured_at,
            value_main=1,
        )
        
        context = build_indicators_context(
            self.patient, 
            start_date_str=start_date.isoformat(), 
            end_date_str=end_date.isoformat(),
            filter_type='date'
        )
        
        med_data = context['medication_data']
        # Expect 3 days: Yesterday, Today, Tomorrow
        self.assertEqual(len(med_data), 3)
        
        # Verify structure and dates
        yesterday_rec = med_data[0]
        today_rec = med_data[1]
        tomorrow_rec = med_data[2]
        
        self.assertEqual(yesterday_rec['date'], start_date)
        self.assertTrue(yesterday_rec['has_task'])
        self.assertEqual(yesterday_rec['status'], 'taken')
        self.assertTrue(yesterday_rec['taken'])
        
        self.assertEqual(today_rec['date'], self.today)
        self.assertTrue(today_rec['has_task'])
        self.assertEqual(today_rec['status'], 'missed')
        self.assertFalse(today_rec['taken'])
        
        self.assertEqual(tomorrow_rec['date'], end_date)
        self.assertFalse(tomorrow_rec['has_task'])
        self.assertEqual(tomorrow_rec['status'], 'future')
        self.assertFalse(tomorrow_rec['taken'])
        
        # Verify comparison logic logic works (conceptually)
        # In template: if record.date > current_date
        current_date = context['current_date']
        self.assertEqual(current_date, self.today)
        
        self.assertFalse(yesterday_rec['date'] > current_date)
        self.assertFalse(today_rec['date'] > current_date)
        self.assertTrue(tomorrow_rec['date'] > current_date)

    def test_medication_data_day_without_task_status_none(self):
        start_date = self.today
        end_date = self.today

        # 无用药任务日即使有用药记录，也应显示“无”
        measured_at = timezone.make_aware(datetime.combine(self.today, datetime.min.time()))
        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.USE_MEDICATED,
            measured_at=measured_at,
            value_main=1,
        )

        context = build_indicators_context(
            self.patient,
            start_date_str=start_date.isoformat(),
            end_date_str=end_date.isoformat(),
            filter_type='date',
        )

        med_data = context['medication_data']
        self.assertEqual(len(med_data), 1)
        rec = med_data[0]
        self.assertEqual(rec['date'], self.today)
        self.assertFalse(rec['has_task'])
        self.assertEqual(rec['status'], 'none')
        self.assertFalse(rec['taken'])

    @patch("web_doctor.views.indicators.HealthMetricService.query_metrics_by_type")
    def test_indicators_query_end_date_inclusive(self, mock_query):
        start_date = self.today - timedelta(days=1)
        end_date = self.today
        mock_query.return_value = SimpleNamespace(object_list=[])

        build_indicators_context(
            self.patient,
            start_date_str=start_date.isoformat(),
            end_date_str=end_date.isoformat(),
            filter_type="date",
        )

        _, kwargs = mock_query.call_args
        self.assertEqual(kwargs["end_date"].date(), end_date + timedelta(days=1))
        self.assertEqual(kwargs["end_date"].time(), datetime.min.time())

    @patch("web_doctor.views.indicators.QuestionnaireSubmissionService.list_daily_cough_hemoptysis_flags", return_value=[])
    @patch("web_doctor.views.indicators.get_adherence_metrics_batch", return_value=[])
    @patch("web_doctor.views.indicators.HealthMetricService.query_metrics_by_type")
    def test_questionnaire_chart_missing_flags(self, mock_query, *_mocks):
        mock_query.return_value = SimpleNamespace(object_list=[])

        questionnaire_specs = [
            (QuestionnaireCode.Q_PHYSICAL, "体能评估"),
            (QuestionnaireCode.Q_BREATH, "呼吸评估"),
            (QuestionnaireCode.Q_COUGH, "咳嗽与痰色评估"),
            (QuestionnaireCode.Q_APPETITE, "食欲评估"),
            (QuestionnaireCode.Q_PAIN, "身体疼痛评估"),
            (QuestionnaireCode.Q_SLEEP, "睡眠质量评估"),
            (QuestionnaireCode.Q_DEPRESSIVE, "抑郁评估"),
            (QuestionnaireCode.Q_ANXIETY, "焦虑评估"),
            (QuestionnaireCode.Q_KQNMLB, "口腔黏膜损伤自评量表"),
        ]
        for code, name in questionnaire_specs:
            Questionnaire.objects.get_or_create(code=code, defaults={"name": name})

        start_date = self.today - timedelta(days=2)
        end_date = self.today

        submission = QuestionnaireSubmission.objects.create(
            patient=self.patient,
            questionnaire=Questionnaire.objects.get(code=QuestionnaireCode.Q_PHYSICAL),
            total_score=Decimal("0"),
        )
        QuestionnaireSubmission.objects.filter(id=submission.id).update(
            created_at=timezone.make_aware(
                datetime.combine(start_date, datetime.min.time())
            )
        )

        context = build_indicators_context(
            self.patient,
            start_date_str=start_date.isoformat(),
            end_date_str=end_date.isoformat(),
            filter_type="date",
        )

        series = context["charts"]["physical"]["series"][0]
        self.assertEqual(len(series["missing"]), 3)
        self.assertEqual(series["missing"], [0, 1, 1])
        self.assertEqual(series["data"][0], 0.0)
        self.assertEqual(series["data"][1], 0.0)
        self.assertEqual(series["data"][2], 0.0)
        oral_series = context["charts"]["oral_mucosa"]["series"][0]
        self.assertEqual(len(oral_series["missing"]), 3)
        self.assertEqual(context["charts"]["oral_mucosa"]["y_max"], 4)

    @patch("web_doctor.views.indicators.QuestionnaireSubmissionService.list_daily_cough_hemoptysis_flags", return_value=[])
    @patch("web_doctor.views.indicators.get_adherence_metrics_batch", return_value=[])
    @patch("web_doctor.views.indicators.HealthMetricService.query_metrics_by_type")
    def test_oral_mucosa_chart_dynamic_ymax(self, mock_query, *_mocks):
        mock_query.return_value = SimpleNamespace(object_list=[])

        questionnaire, _ = Questionnaire.objects.get_or_create(
            code=QuestionnaireCode.Q_KQNMLB,
            defaults={"name": "口腔黏膜损伤自评量表"},
        )
        start_date = self.today - timedelta(days=2)
        end_date = self.today
        submission = QuestionnaireSubmission.objects.create(
            patient=self.patient,
            questionnaire=questionnaire,
            total_score=Decimal("6"),
        )
        QuestionnaireSubmission.objects.filter(id=submission.id).update(
            created_at=timezone.make_aware(
                datetime.combine(start_date, datetime.min.time())
            )
        )

        context = build_indicators_context(
            self.patient,
            start_date_str=start_date.isoformat(),
            end_date_str=end_date.isoformat(),
            filter_type="date",
        )

        oral_chart = context["charts"]["oral_mucosa"]
        self.assertEqual(oral_chart["title"], "口腔黏膜损伤自评量表")
        self.assertEqual(oral_chart["y_min"], 0)
        self.assertEqual(oral_chart["y_max"], 8)

    @patch("web_doctor.views.indicators.QuestionnaireSubmissionService.list_daily_cough_hemoptysis_flags", return_value=[])
    @patch("web_doctor.views.indicators.QuestionnaireSubmissionService.list_daily_questionnaire_scores", return_value=[])
    @patch("web_doctor.views.indicators.get_adherence_metrics_batch", return_value=[])
    @patch("web_doctor.views.indicators.HealthMetricService.query_metrics_by_type", return_value=SimpleNamespace(object_list=[]))
    def test_followup_review_catalog_uses_checkup_field_mappings(self, *_mocks):
        checkup = CheckupLibrary.objects.create(
            name="血常规",
            code="BLOOD_ROUTINE_INDICATOR",
            category=choices.CheckupCategory.BLOOD,
            is_active=True,
        )
        decimal_field = StandardField.objects.create(
            local_code="WBC_INDICATOR",
            chinese_name="白细胞计数",
            english_abbr="WBC",
            value_type=StandardFieldValueType.DECIMAL,
            default_unit="10^9/L",
            is_active=True,
        )
        text_field = StandardField.objects.create(
            local_code="CT_FINDINGS_INDICATOR",
            chinese_name="影像所见",
            value_type=StandardFieldValueType.TEXT,
            is_active=True,
        )
        CheckupFieldMapping.objects.create(
            checkup_item=checkup,
            standard_field=decimal_field,
            sort_order=1,
            is_active=True,
        )
        CheckupFieldMapping.objects.create(
            checkup_item=checkup,
            standard_field=text_field,
            sort_order=2,
            is_active=True,
        )

        context = build_indicators_context(self.patient)

        review_indicator = context["review_indicator"]
        self.assertEqual(review_indicator["selected_count"], 0)
        self.assertEqual(review_indicator["selected_mapping_ids"], [])
        self.assertEqual(review_indicator["module_title"], "复查指标")
        self.assertEqual(len(review_indicator["catalog"]), 1)
        self.assertEqual(review_indicator["catalog"][0]["checkup_name"], "血常规")
        self.assertEqual(len(review_indicator["catalog"][0]["fields"]), 2)
        self.assertTrue(review_indicator["catalog"][0]["fields"][0]["selectable"])
        self.assertEqual(
            review_indicator["catalog"][0]["fields"][0]["field_display_name"],
            "白细胞计数(WBC)",
        )
        self.assertFalse(review_indicator["catalog"][0]["fields"][1]["selectable"])
        self.assertEqual(len(review_indicator["chart"]["series"]), 0)
        self.assertEqual(len(review_indicator["charts"]), 0)
        self.assertEqual(review_indicator["chart"]["dates"], context["dates"])

    @patch("web_doctor.views.indicators.QuestionnaireSubmissionService.list_daily_cough_hemoptysis_flags", return_value=[])
    @patch("web_doctor.views.indicators.QuestionnaireSubmissionService.list_daily_questionnaire_scores", return_value=[])
    @patch("web_doctor.views.indicators.get_adherence_metrics_batch", return_value=[])
    @patch("web_doctor.views.indicators.HealthMetricService.query_metrics_by_type", return_value=SimpleNamespace(object_list=[]))
    def test_followup_review_filters_invalid_mapping_selection(self, *_mocks):
        checkup = CheckupLibrary.objects.create(
            name="肿瘤标志物",
            code="TUMOR_MARKER_INDICATOR",
            category=choices.CheckupCategory.BLOOD,
            is_active=True,
        )
        inactive_checkup = CheckupLibrary.objects.create(
            name="停用检查",
            code="INACTIVE_CHECKUP_INDICATOR",
            is_active=False,
        )
        cea_field = StandardField.objects.create(
            local_code="CEA_INDICATOR",
            chinese_name="癌胚抗原",
            english_abbr="CEA",
            value_type=StandardFieldValueType.DECIMAL,
            is_active=True,
        )
        text_field = StandardField.objects.create(
            local_code="TEXT_INDICATOR",
            chinese_name="文本指标",
            value_type=StandardFieldValueType.TEXT,
            is_active=True,
        )
        inactive_field = StandardField.objects.create(
            local_code="INACTIVE_FIELD_INDICATOR",
            chinese_name="停用指标",
            value_type=StandardFieldValueType.DECIMAL,
            is_active=False,
        )
        selectable_mapping = CheckupFieldMapping.objects.create(
            checkup_item=checkup,
            standard_field=cea_field,
            is_active=True,
        )
        text_mapping = CheckupFieldMapping.objects.create(
            checkup_item=checkup,
            standard_field=text_field,
            is_active=True,
        )
        inactive_mapping = CheckupFieldMapping.objects.create(
            checkup_item=checkup,
            standard_field=inactive_field,
            is_active=True,
        )
        hidden_mapping = CheckupFieldMapping.objects.create(
            checkup_item=inactive_checkup,
            standard_field=cea_field,
            is_active=True,
        )

        context = build_indicators_context(
            self.patient,
            start_date_str=(self.today - timedelta(days=2)).isoformat(),
            end_date_str=self.today.isoformat(),
            filter_type="date",
            review_metric_mappings=[
                str(selectable_mapping.id),
                "invalid_item",
                str(text_mapping.id),
                str(inactive_mapping.id),
                str(hidden_mapping.id),
                str(selectable_mapping.id),
            ],
        )

        review_indicator = context["review_indicator"]
        self.assertEqual(review_indicator["selected_mapping_ids"], [selectable_mapping.id])
        self.assertEqual(review_indicator["selected_count"], 1)
        self.assertEqual(len(review_indicator["chart"]["series"]), 1)
        self.assertEqual(len(review_indicator["charts"]), 1)
        self.assertEqual(len(review_indicator["chart"]["series"][0]["data"]), len(context["dates"]))

    @patch("web_doctor.views.indicators.QuestionnaireSubmissionService.list_daily_cough_hemoptysis_flags", return_value=[])
    @patch("web_doctor.views.indicators.QuestionnaireSubmissionService.list_daily_questionnaire_scores", return_value=[])
    @patch("web_doctor.views.indicators.get_adherence_metrics_batch", return_value=[])
    @patch("web_doctor.views.indicators.HealthMetricService.query_metrics_by_type", return_value=SimpleNamespace(object_list=[]))
    def test_followup_review_uses_saved_patient_preferences_when_no_request_param(self, *_mocks):
        checkup = CheckupLibrary.objects.create(
            name="血生化",
            code="BLOOD_CHEMISTRY_INDICATOR",
            category=choices.CheckupCategory.BLOOD,
            is_active=True,
        )
        field = StandardField.objects.create(
            local_code="ALT_INDICATOR",
            chinese_name="谷丙转氨酶",
            value_type=StandardFieldValueType.DECIMAL,
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

        context = build_indicators_context(self.patient)

        review_indicator = context["review_indicator"]
        self.assertEqual(review_indicator["selected_mapping_ids"], [mapping.id])
        self.assertEqual(review_indicator["selected_count"], 1)
        self.assertEqual(len(review_indicator["charts"]), 1)

    @patch("web_doctor.views.indicators.QuestionnaireSubmissionService.list_daily_cough_hemoptysis_flags", return_value=[])
    @patch("web_doctor.views.indicators.QuestionnaireSubmissionService.list_daily_questionnaire_scores", return_value=[])
    @patch("web_doctor.views.indicators.get_adherence_metrics_batch", return_value=[])
    @patch("web_doctor.views.indicators.HealthMetricService.query_metrics_by_type", return_value=SimpleNamespace(object_list=[]))
    def test_followup_review_request_param_overrides_saved_patient_preferences(self, *_mocks):
        checkup = CheckupLibrary.objects.create(
            name="血常规",
            code="BLOOD_ROUTINE_OVERRIDE_INDICATOR",
            category=choices.CheckupCategory.BLOOD,
            is_active=True,
        )
        saved_field = StandardField.objects.create(
            local_code="WBC_OVERRIDE_INDICATOR",
            chinese_name="白细胞计数",
            value_type=StandardFieldValueType.DECIMAL,
            is_active=True,
        )
        request_field = StandardField.objects.create(
            local_code="HGB_OVERRIDE_INDICATOR",
            chinese_name="血红蛋白",
            value_type=StandardFieldValueType.DECIMAL,
            is_active=True,
        )
        saved_mapping = CheckupFieldMapping.objects.create(
            checkup_item=checkup,
            standard_field=saved_field,
            is_active=True,
        )
        request_mapping = CheckupFieldMapping.objects.create(
            checkup_item=checkup,
            standard_field=request_field,
            is_active=True,
        )
        self.patient.indicator_preferences = {
            "version": 1,
            "followup_review": {"selected_mapping_ids": [saved_mapping.id]},
        }
        self.patient.save(update_fields=["indicator_preferences"])

        context = build_indicators_context(
            self.patient,
            review_metric_mappings=[str(request_mapping.id)],
        )

        review_indicator = context["review_indicator"]
        self.assertEqual(review_indicator["selected_mapping_ids"], [request_mapping.id])
        self.assertEqual(review_indicator["selected_labels"], ["血红蛋白"])

    @patch("web_doctor.views.indicators.QuestionnaireSubmissionService.list_daily_cough_hemoptysis_flags", return_value=[])
    @patch("web_doctor.views.indicators.QuestionnaireSubmissionService.list_daily_questionnaire_scores", return_value=[])
    @patch("web_doctor.views.indicators.get_adherence_metrics_batch", return_value=[])
    @patch("web_doctor.views.indicators.HealthMetricService.query_metrics_by_type", return_value=SimpleNamespace(object_list=[]))
    def test_followup_review_chart_uses_structured_checkup_values(self, *_mocks):
        start_date = self.today - timedelta(days=3)
        same_day = start_date + timedelta(days=1)
        checkup = CheckupLibrary.objects.create(
            name="血常规",
            code="BLOOD_ROUTINE_REAL_INDICATOR",
            category=choices.CheckupCategory.BLOOD,
            is_active=True,
        )
        other_checkup = CheckupLibrary.objects.create(
            name="血生化",
            code="BLOOD_CHEMISTRY_REAL_INDICATOR",
            category=choices.CheckupCategory.BLOOD,
            is_active=True,
        )
        field = StandardField.objects.create(
            local_code="WBC_REAL_INDICATOR",
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
        CheckupFieldMapping.objects.create(
            checkup_item=other_checkup,
            standard_field=field,
            is_active=True,
        )

        upload = ReportUpload.objects.create(patient=self.patient)

        def create_result(report_date, value, *, item=checkup, unit=""):
            image = ReportImage.objects.create(
                upload=upload,
                image_url=f"https://example.com/{item.id}-{report_date}-{value}.jpg",
                record_type=ReportImage.RecordType.CHECKUP,
                checkup_item=item,
                report_date=report_date,
            )
            return CheckupResultValue.objects.create(
                patient=self.patient,
                report_image=image,
                checkup_item=item,
                standard_field=field,
                report_date=report_date,
                raw_name="白细胞计数",
                normalized_name=f"wbc-{item.id}-{report_date}-{value}",
                value_numeric=Decimal(str(value)),
                raw_value=str(value),
                unit=unit,
            )

        create_result(start_date, "1.2")
        create_result(same_day, "2.3")
        create_result(same_day, "2.8", unit="*10^9/L")
        create_result(start_date + timedelta(days=2), "9.9", item=other_checkup)
        create_result(start_date - timedelta(days=1), "7.7")

        context = build_indicators_context(
            self.patient,
            start_date_str=start_date.isoformat(),
            end_date_str=self.today.isoformat(),
            filter_type="date",
            review_metric_mappings=[str(mapping.id)],
        )

        chart = context["review_indicator"]["charts"][0]
        series_data = chart["series"][0]["data"]
        self.assertEqual(series_data, [1.2, 2.8, None, None])
        self.assertEqual(chart["series"][0]["data_json"], "[1.2, 2.8, null, null]")
        self.assertIn("血常规-白细胞计数（WBC） *10^9/L", chart["title"])
        self.assertEqual(chart["empty_message"], "")
        self.assertEqual(context["review_indicator"]["focus_metric"]["current_value"], 2.8)

    @patch("web_doctor.views.indicators.QuestionnaireSubmissionService.list_daily_cough_hemoptysis_flags", return_value=[])
    @patch("web_doctor.views.indicators.QuestionnaireSubmissionService.list_daily_questionnaire_scores", return_value=[])
    @patch("web_doctor.views.indicators.get_adherence_metrics_batch", return_value=[])
    @patch("web_doctor.views.indicators.HealthMetricService.query_metrics_by_type", return_value=SimpleNamespace(object_list=[]))
    def test_followup_review_chart_keeps_configured_metric_when_no_data(self, *_mocks):
        checkup = CheckupLibrary.objects.create(
            name="肿瘤标志物",
            code="TUMOR_MARKER_EMPTY_INDICATOR",
            category=choices.CheckupCategory.BLOOD,
            is_active=True,
        )
        field = StandardField.objects.create(
            local_code="CEA_EMPTY_INDICATOR",
            chinese_name="癌胚抗原",
            english_abbr="CEA",
            value_type=StandardFieldValueType.DECIMAL,
            is_active=True,
        )
        mapping = CheckupFieldMapping.objects.create(
            checkup_item=checkup,
            standard_field=field,
            is_active=True,
        )

        context = build_indicators_context(
            self.patient,
            start_date_str=(self.today - timedelta(days=1)).isoformat(),
            end_date_str=self.today.isoformat(),
            filter_type="date",
            review_metric_mappings=[str(mapping.id)],
        )

        chart = context["review_indicator"]["charts"][0]
        self.assertEqual(chart["series"][0]["data"], [None, None])
        self.assertEqual(chart["empty_message"], "暂无复查结果数据")


@patch("web_doctor.views.indicators.get_treatment_cycles", return_value=SimpleNamespace(object_list=[]))
@patch("web_doctor.views.indicators.get_adherence_metrics_batch", return_value=[])
@patch("web_doctor.views.indicators.QuestionnaireSubmissionService.list_daily_questionnaire_scores", return_value=[])
@patch("web_doctor.views.indicators.QuestionnaireSubmissionService.list_daily_cough_hemoptysis_flags", return_value=[])
class IndicatorsYAxisMaxTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testpatient_ymax", password="password", wx_openid="test_openid_ymax_123")
        self.patient = PatientProfile.objects.create(user=self.user, name="Test Patient YMax")
        self.today = timezone.localdate()
        self.start_date = self.today - timedelta(days=2)
        self.end_date = self.today

    def _metric(self, day_offset, value_main=None, value_sub=None):
        measured_at = timezone.make_aware(
            datetime.combine(self.start_date + timedelta(days=day_offset), datetime.min.time())
        )
        return SimpleNamespace(measured_at=measured_at, value_main=value_main, value_sub=value_sub)

    def _build_context(self):
        return build_indicators_context(
            self.patient,
            start_date_str=self.start_date.isoformat(),
            end_date_str=self.end_date.isoformat(),
            filter_type="date",
        )

    @patch("web_doctor.views.indicators.HealthMetricService.query_metrics_by_type")
    def test_spo2_ymax_from_data(self, mock_query, *_mocks):
        self.patient.baseline_blood_oxygen = 90
        self.patient.save(update_fields=["baseline_blood_oxygen"])

        def side_effect(*args, **kwargs):
            metric_type = kwargs.get("metric_type")
            if metric_type == MetricType.BLOOD_OXYGEN:
                return SimpleNamespace(object_list=[self._metric(0, value_main=95)])
            return SimpleNamespace(object_list=[])

        mock_query.side_effect = side_effect
        context = self._build_context()
        self.assertEqual(context["charts"]["spo2"]["y_max"], 114)

    @patch("web_doctor.views.indicators.HealthMetricService.query_metrics_by_type")
    def test_hr_ymax_uses_baseline(self, mock_query, *_mocks):
        self.patient.baseline_heart_rate = 100
        self.patient.save(update_fields=["baseline_heart_rate"])

        def side_effect(*args, **kwargs):
            metric_type = kwargs.get("metric_type")
            if metric_type == MetricType.HEART_RATE:
                return SimpleNamespace(object_list=[self._metric(1, value_main=70)])
            return SimpleNamespace(object_list=[])

        mock_query.side_effect = side_effect
        context = self._build_context()
        self.assertEqual(context["charts"]["hr"]["y_max"], 120)

    @patch("web_doctor.views.indicators.HealthMetricService.query_metrics_by_type")
    def test_weight_ymax_defaults_when_no_data(self, mock_query, *_mocks):
        mock_query.return_value = SimpleNamespace(object_list=[])
        context = self._build_context()
        self.assertEqual(context["charts"]["weight"]["y_max"], 150)

    @patch("web_doctor.views.indicators.HealthMetricService.query_metrics_by_type")
    def test_bp_ymax_combines_sbp_dbp_and_baselines(self, mock_query, *_mocks):
        self.patient.baseline_blood_pressure_sbp = 140
        self.patient.baseline_blood_pressure_dbp = 90
        self.patient.save(update_fields=["baseline_blood_pressure_sbp", "baseline_blood_pressure_dbp"])

        def side_effect(*args, **kwargs):
            metric_type = kwargs.get("metric_type")
            if metric_type == MetricType.BLOOD_PRESSURE:
                return SimpleNamespace(object_list=[self._metric(0, value_main=130, value_sub=85)])
            return SimpleNamespace(object_list=[])

        mock_query.side_effect = side_effect
        context = self._build_context()
        self.assertEqual(context["charts"]["bp"]["y_max"], 168)

    @patch("web_doctor.views.indicators.HealthMetricService.query_metrics_by_type")
    def test_temp_ymax_rounds_to_one_decimal(self, mock_query, *_mocks):
        self.patient.baseline_body_temperature = 36.1
        self.patient.save(update_fields=["baseline_body_temperature"])

        def side_effect(*args, **kwargs):
            metric_type = kwargs.get("metric_type")
            if metric_type == MetricType.BODY_TEMPERATURE:
                return SimpleNamespace(object_list=[self._metric(0, value_main=36.6)])
            return SimpleNamespace(object_list=[])

        mock_query.side_effect = side_effect
        context = self._build_context()
        self.assertEqual(context["charts"]["temp"]["y_max"], 44.0)
