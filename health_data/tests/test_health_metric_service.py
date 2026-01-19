from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from core.service import tasks as task_service
from health_data.models import HealthMetric, MetricSource, MetricType
from health_data.services.health_metric import HealthMetricService
from users.models import PatientProfile


class HealthMetricServiceTest(TestCase):
    def setUp(self):
        # 模拟数据
        self.patient_id = 1001
        self.measured_at = timezone.now()

    @patch("health_data.models.HealthMetric.objects.create")
    def test_save_manual_temperature(self, mock_create):
        """
        测试手动保存体温指标。
        验证重点：
        1. source 是否自动被标记为 MANUAL。
        2. value_main 是否正确传入。
        3. value_sub 是否默认为 None。
        """
        # 准备数据：体温为 36.5℃
        metric_type = MetricType.BODY_TEMPERATURE
        value = Decimal("36.5")

        # 调用服务方法
        HealthMetricService.save_manual_metric(
            patient_id=self.patient_id,
            metric_type=metric_type,
            measured_at=self.measured_at,
            value_main=value
        )

        # 断言：验证 ORM 的 create 方法是否被以正确的参数调用
        mock_create.assert_called_once_with(
            patient_id=self.patient_id,
            metric_type=metric_type,
            source=MetricSource.MANUAL,  # 核心验证点
            value_main=value,
            value_sub=None,              # 核心验证点
            measured_at=self.measured_at
        )

    @patch("health_data.models.HealthMetric.objects.create")
    def test_save_manual_weight_metric(self, mock_create):
        """
        测试手动保存体重指标。
        """
        # 准备数据：体重 65.5 kg
        metric_type = MetricType.WEIGHT
        value = Decimal("65.5")

        HealthMetricService.save_manual_metric(
            patient_id=self.patient_id,
            metric_type=metric_type,
            measured_at=self.measured_at,
            value_main=value
        )

        # 断言参数
        mock_create.assert_called_once_with(
            patient_id=self.patient_id,
            metric_type=metric_type,
            source=MetricSource.MANUAL,
            value_main=value,
            value_sub=None,
            measured_at=self.measured_at
        )

    @patch("health_data.models.HealthMetric.objects.create")
    @patch("health_data.services.health_metric.task_service.complete_daily_medication_tasks")
    def test_save_manual_use_medicated_defaults_and_tasks(self, mock_complete_tasks, mock_create):
        fixed_time = timezone.now()
        mock_complete_tasks.return_value = 123

        with patch("health_data.services.health_metric.timezone.now", return_value=fixed_time):
            HealthMetricService.save_manual_metric(
                patient_id=self.patient_id,
                metric_type=MetricType.USE_MEDICATED,
                measured_at=None,
                value_main=None,
            )

        mock_complete_tasks.assert_called_once_with(self.patient_id, fixed_time)
        mock_create.assert_called_once_with(
            patient_id=self.patient_id,
            metric_type=MetricType.USE_MEDICATED,
            source=MetricSource.MANUAL,
            value_main=Decimal("1"),
            value_sub=None,
            measured_at=fixed_time,
            task_id=123,
        )

    @patch("health_data.models.HealthMetric.objects.create")
    @patch("health_data.services.health_metric.task_service.complete_daily_medication_tasks")
    def test_save_manual_use_medicated_keeps_values(self, mock_complete_tasks, mock_create):
        custom_time = timezone.now()
        mock_complete_tasks.return_value = None

        HealthMetricService.save_manual_metric(
            patient_id=self.patient_id,
            metric_type=MetricType.USE_MEDICATED,
            measured_at=custom_time,
            value_main=Decimal("2"),
        )

        mock_complete_tasks.assert_called_once_with(self.patient_id, custom_time)
        mock_create.assert_called_once()
        _, kwargs = mock_create.call_args
        self.assertEqual(kwargs["patient_id"], self.patient_id)
        self.assertEqual(kwargs["metric_type"], MetricType.USE_MEDICATED)
        self.assertEqual(kwargs["source"], MetricSource.MANUAL)
        self.assertEqual(kwargs["value_main"], Decimal("2"))
        self.assertIsNone(kwargs["value_sub"])
        self.assertEqual(kwargs["measured_at"], custom_time)
        self.assertNotIn("task_id", kwargs)

    def test_save_manual_metric_missing_measured_at_raises(self):
        with self.assertRaises(ValueError):
            HealthMetricService.save_manual_metric(
                patient_id=self.patient_id,
                metric_type=MetricType.WEIGHT,
                measured_at=None,
                value_main=Decimal("60"),
            )

    @patch("health_data.models.HealthMetric.objects.filter")
    @patch("django.apps.apps.get_model")
    def test_query_last_metric(self, mock_get_model, mock_filter):
        """
        测试查询最新指标数据 (query_last_metric)。
        涵盖：
        1. 模拟 PatientProfile 存在。
        2. 模拟数据库查询返回不同类型的 HealthMetric 数据。
        3. 验证 value_display 格式化逻辑。
        4. 验证查询所有 vs 查询单个。
        """
        # 1. 模拟 PatientProfile.objects.filter(id=...).exists() 返回 True
        mock_patient_model = MagicMock()
        mock_patient_model.objects.filter.return_value.exists.return_value = True
        mock_get_model.return_value = mock_patient_model

        # 2. 模拟 HealthMetric.objects.filter(...).order_by(...).first() 的行为
        def filter_side_effect(**kwargs):
            m_type = kwargs.get("metric_type")
            mock_qs = MagicMock()
            mock_metric = MagicMock()

            if m_type == MetricType.BLOOD_PRESSURE:
                # A. 血压 (数值型，有副值)
                mock_metric.metric_type = MetricType.BLOOD_PRESSURE
                mock_metric.value_main = Decimal("118")
                mock_metric.value_sub = Decimal("78")
                mock_metric.measured_at = timezone.now()
                mock_metric.source = MetricSource.DEVICE
                mock_metric.display_value = "118/78"
                mock_qs.order_by.return_value.first.return_value = mock_metric
            elif m_type == MetricType.BODY_TEMPERATURE:
                # B. 体温 (数值型，带单位)
                mock_metric.metric_type = MetricType.BODY_TEMPERATURE
                mock_metric.value_main = Decimal("36.50")
                mock_metric.value_sub = None
                mock_metric.measured_at = timezone.now()
                mock_metric.source = MetricSource.MANUAL
                mock_metric.display_value = "36.5 °C"
                mock_qs.order_by.return_value.first.return_value = mock_metric
            elif m_type == MetricType.WEIGHT:
                # C. 体重 (数值型，带单位)
                mock_metric.metric_type = MetricType.WEIGHT
                mock_metric.value_main = Decimal("65.50")
                mock_metric.value_sub = None
                mock_metric.measured_at = timezone.now()
                mock_metric.source = MetricSource.DEVICE
                mock_metric.display_value = "65.5 kg"
                mock_qs.order_by.return_value.first.return_value = mock_metric
            else:
                # 其他类型无数据
                mock_qs.order_by.return_value.first.return_value = None

            return mock_qs

        mock_filter.side_effect = filter_side_effect

        # --- 测试场景 1: 查询所有指标 ---
        result_all = HealthMetricService.query_last_metric(self.patient_id)

        # 验证血压格式化
        bp_data = result_all[MetricType.BLOOD_PRESSURE]
        self.assertIsNotNone(bp_data)
        self.assertEqual(bp_data["value_display"], "118/78")
        self.assertEqual(bp_data["name"], "血压")

        # 验证体温展示
        temp_data = result_all[MetricType.BODY_TEMPERATURE]
        self.assertIsNotNone(temp_data)
        self.assertIn("36.5", temp_data["value_display"])

        # 验证体重单位
        weight_data = result_all[MetricType.WEIGHT]
        self.assertEqual(weight_data["value_display"], "65.5 kg")

        # 验证无数据的指标 (例如心率)
        self.assertIsNone(result_all[MetricType.HEART_RATE])

        # --- 测试场景 2: 查询单个指标 ---
        result_single = HealthMetricService.query_last_metric(
            self.patient_id, metric_type=MetricType.BLOOD_PRESSURE
        )
        self.assertIn(MetricType.BLOOD_PRESSURE, result_single)
        self.assertNotIn(MetricType.BODY_TEMPERATURE, result_single)

        # --- 测试场景 3: 患者不存在 ---
        mock_patient_model.objects.filter.return_value.exists.return_value = False
        # 模拟抛出 DoesNotExist (Mock 的 DoesNotExist 只是一个类)
        mock_patient_model.DoesNotExist = Exception
        with self.assertRaises(Exception):
            HealthMetricService.query_last_metric(999)

    @patch("health_data.models.HealthMetric.objects.filter")
    def test_query_metrics_by_type(self, mock_filter):
        """
        测试查询历史数据列表 (query_metrics_by_type)。
        验证：
        1. 返回的对象具备分页所需属性。
        2. page_size 限制逻辑 (最大 100)。
        3. 数据排序和分页。
        """
        # 模拟 QuerySet 及其 order_by 返回值
        mock_qs = MagicMock()
        mock_filter.return_value = mock_qs

        mock_ordered_qs = MagicMock()
        mock_qs.order_by.return_value = mock_ordered_qs

        # 模拟 Paginator.page 返回的“分页对象”
        mock_page = MagicMock()

        mock_metrics_list = []
        for i in range(30):
            m = MagicMock()
            m.id = i
            m.value_main = Decimal("60")
            m.value_sub = None
            m.metric_type = MetricType.WEIGHT
            m.measured_at = timezone.now()
            m.source = MetricSource.DEVICE
            mock_metrics_list.append(m)

        mock_page.object_list = mock_metrics_list
        mock_page.number = 1
        mock_page_paginator = MagicMock()
        mock_page_paginator.count = 150
        mock_page_paginator.num_pages = 2
        mock_page.paginator = mock_page_paginator

        # 为了不依赖真实 Paginator，这里直接打补丁 Paginator，使其返回我们的 mock_page
        with patch("health_data.services.health_metric.Paginator") as mock_paginator_cls:
            mock_paginator = MagicMock()
            mock_paginator.page.return_value = mock_page
            mock_paginator_cls.return_value = mock_paginator

            # --- 调用测试 ---
            # 请求 page_size=200，预期被限制为 100
            result_page = HealthMetricService.query_metrics_by_type(
                self.patient_id,
                MetricType.WEIGHT,
                page=1,
                page_size=200,
            )

        # --- 验证 ---
        # 1. 返回的对象就是我们构造的 mock_page，且具备分页属性
        self.assertIs(result_page, mock_page)
        self.assertEqual(result_page.object_list, mock_metrics_list)
        self.assertEqual(result_page.paginator.count, 150)

        # 2. 验证 page_size 限制：Paginator 应当用 100 作为 per_page
        mock_paginator_cls.assert_called_once()
        args, kwargs = mock_paginator_cls.call_args
        # args[0] 是 queryset，args[1] 是 per_page
        self.assertEqual(args[1], 100)

        # 3. 验证 filter 参数
        mock_filter.assert_called_with(
            patient_id=self.patient_id, metric_type=MetricType.WEIGHT
        )

    def test_query_metrics_by_type_end_date_inclusive(self):
        patient = PatientProfile.objects.create(phone="13800138003")
        tz = timezone.get_current_timezone()
        start_dt = timezone.make_aware(datetime(2025, 1, 1, 0, 0), tz)
        end_dt = timezone.make_aware(datetime(2025, 1, 31, 23, 59, 59), tz)
        next_day = timezone.make_aware(datetime(2025, 2, 1, 0, 0), tz)

        in_range = HealthMetric.objects.create(
            patient=patient,
            metric_type=MetricType.WEIGHT,
            measured_at=end_dt,
        )
        HealthMetric.objects.create(
            patient=patient,
            metric_type=MetricType.WEIGHT,
            measured_at=next_day,
        )

        page = HealthMetricService.query_metrics_by_type(
            patient_id=patient.id,
            metric_type=MetricType.WEIGHT,
            start_date=start_dt,
            end_date=end_dt,
            page=1,
            page_size=10,
            sort_order="asc",
        )

        ids = [item.id for item in page.object_list]
        self.assertEqual(ids, [in_range.id])

    @patch("health_data.models.HealthMetric.objects.get")
    def test_update_manual_metric_success_partial_fields(self, mock_get):
        """
        测试 update_manual_metric 只更新部分字段：
        - 仅更新 value_main，不修改 value_sub 和 measured_at。
        - 仅允许修改 source=MANUAL 的记录。
        """
        # 模拟一条手动录入的 HealthMetric
        mock_metric = MagicMock(spec=HealthMetric)
        mock_metric.id = 1
        mock_metric.source = MetricSource.MANUAL
        mock_metric.value_main = Decimal("36.5")
        mock_metric.value_sub = Decimal("0")
        original_measured_at = self.measured_at
        mock_metric.measured_at = original_measured_at
        mock_get.return_value = mock_metric

        # 仅更新 value_main
        new_value_main = Decimal("37.5")
        result = HealthMetricService.update_manual_metric(
            metric_id=1,
            value_main=new_value_main,
        )

        # 返回值就是被更新的 metric
        self.assertIs(result, mock_metric)

        # 只更新了 value_main，且调用了 save(update_fields=["value_main"])
        self.assertEqual(mock_metric.value_main, new_value_main)
        self.assertEqual(mock_metric.value_sub, Decimal("0"))
        self.assertEqual(mock_metric.measured_at, original_measured_at)
        mock_metric.save.assert_called_once_with(update_fields=["value_main"])

    @patch("health_data.models.HealthMetric.objects.get")
    def test_update_manual_metric_device_source_raises(self, mock_get):
        """
        测试 update_manual_metric 遇到设备数据时抛出 ValueError。
        """
        mock_metric = MagicMock(spec=HealthMetric)
        mock_metric.id = 2
        mock_metric.source = MetricSource.DEVICE
        mock_get.return_value = mock_metric

        with self.assertRaises(ValueError):
            HealthMetricService.update_manual_metric(
                metric_id=2,
                value_main=Decimal("37.0"),
            )

        # 设备数据不应被保存
        mock_metric.save.assert_not_called()

    @patch("health_data.models.HealthMetric.objects.get")
    def test_delete_metric_soft_delete(self, mock_get):
        """
        测试 delete_metric 软删除行为：
        - 只标记 is_active=False。
        - 使用 update_fields=["is_active"] 保存。
        """
        mock_metric = MagicMock(spec=HealthMetric)
        mock_metric.id = 3
        mock_metric.is_active = True
        mock_get.return_value = mock_metric

        result = HealthMetricService.delete_metric(metric_id=3)

        self.assertIs(result, mock_metric)
        self.assertFalse(mock_metric.is_active)
        mock_metric.save.assert_called_once_with(update_fields=["is_active"])

    def test_count_metric_uploads_single_type_inclusive_range(self):
        """
        统计单一指标的上传次数，日期范围为闭区间。
        """
        patient = PatientProfile.objects.create(phone="13800138000")
        tz = timezone.get_current_timezone()

        HealthMetric.objects.create(
            patient=patient,
            metric_type=MetricType.BLOOD_PRESSURE,
            measured_at=timezone.make_aware(datetime(2025, 1, 1, 10, 0), tz),
        )
        HealthMetric.objects.create(
            patient=patient,
            metric_type=MetricType.BLOOD_PRESSURE,
            measured_at=timezone.make_aware(datetime(2025, 1, 2, 23, 59), tz),
        )
        HealthMetric.objects.create(
            patient=patient,
            metric_type=MetricType.BLOOD_PRESSURE,
            measured_at=timezone.make_aware(datetime(2025, 1, 3, 0, 0), tz),
        )

        count = HealthMetricService.count_metric_uploads(
            patient=patient,
            metric_type=MetricType.BLOOD_PRESSURE,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 2),
        )

        self.assertEqual(count, 2)

    def test_count_metric_uploads_end_date_inclusive_excludes_next_day(self):
        patient = PatientProfile.objects.create(phone="13800138004")
        tz = timezone.get_current_timezone()
        end_dt = timezone.make_aware(datetime(2025, 1, 31, 23, 59, 59), tz)
        next_day = timezone.make_aware(datetime(2025, 2, 1, 0, 0), tz)

        HealthMetric.objects.create(
            patient=patient,
            metric_type=MetricType.BLOOD_PRESSURE,
            measured_at=end_dt,
        )
        HealthMetric.objects.create(
            patient=patient,
            metric_type=MetricType.BLOOD_PRESSURE,
            measured_at=next_day,
        )

        count = HealthMetricService.count_metric_uploads(
            patient=patient,
            metric_type=MetricType.BLOOD_PRESSURE,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
        )

        self.assertEqual(count, 1)

    def test_count_metric_uploads_monitoring_all_excludes_non_monitoring(self):
        """
        综合监测上传次数：仅统计六类监测指标，忽略非监测与无效记录。
        """
        patient = PatientProfile.objects.create(phone="13800138001")
        tz = timezone.get_current_timezone()

        HealthMetric.objects.create(
            patient=patient,
            metric_type=MetricType.BLOOD_PRESSURE,
            measured_at=timezone.make_aware(datetime(2025, 2, 1, 9, 0), tz),
        )
        HealthMetric.objects.create(
            patient=patient,
            metric_type=MetricType.STEPS,
            measured_at=timezone.make_aware(datetime(2025, 2, 1, 12, 0), tz),
        )
        HealthMetric.objects.create(
            patient=patient,
            metric_type=MetricType.USE_MEDICATED,
            measured_at=timezone.make_aware(datetime(2025, 2, 1, 18, 0), tz),
        )
        HealthMetric.all_objects.create(
            patient=patient,
            metric_type=MetricType.BLOOD_OXYGEN,
            measured_at=timezone.make_aware(datetime(2025, 2, 1, 20, 0), tz),
            is_active=False,
        )

        count = HealthMetricService.count_metric_uploads(
            patient=patient,
            metric_type=task_service.MONITORING_ADHERENCE_ALL,
            start_date=date(2025, 2, 1),
            end_date=date(2025, 2, 1),
        )

        self.assertEqual(count, 2)

    def test_list_monitoring_metric_types_for_patient_end_date_inclusive(self):
        patient = PatientProfile.objects.create(phone="13800138005")
        tz = timezone.get_current_timezone()
        end_dt = timezone.make_aware(datetime(2025, 1, 31, 23, 59, 59), tz)
        next_day = timezone.make_aware(datetime(2025, 2, 1, 0, 0), tz)

        HealthMetric.objects.create(
            patient=patient,
            metric_type=MetricType.BLOOD_PRESSURE,
            measured_at=end_dt,
        )
        HealthMetric.objects.create(
            patient=patient,
            metric_type=MetricType.HEART_RATE,
            measured_at=next_day,
        )

        types = HealthMetricService.list_monitoring_metric_types_for_patient(
            patient=patient,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
        )

        self.assertIn(MetricType.BLOOD_PRESSURE, types)
        self.assertNotIn(MetricType.HEART_RATE, types)

    def test_count_metric_uploads_by_month_fills_missing_months(self):
        """
        按自然月统计上传次数，并补全缺失月份为 0。
        """
        patient = PatientProfile.objects.create(phone="13800138002")
        tz = timezone.get_current_timezone()

        HealthMetric.objects.create(
            patient=patient,
            metric_type=MetricType.BLOOD_PRESSURE,
            measured_at=timezone.make_aware(datetime(2025, 1, 15, 9, 0), tz),
        )
        HealthMetric.objects.create(
            patient=patient,
            metric_type=MetricType.BLOOD_PRESSURE,
            measured_at=timezone.make_aware(datetime(2025, 1, 20, 10, 0), tz),
        )
        HealthMetric.objects.create(
            patient=patient,
            metric_type=MetricType.HEART_RATE,
            measured_at=timezone.make_aware(datetime(2025, 2, 2, 11, 0), tz),
        )
        HealthMetric.objects.create(
            patient=patient,
            metric_type=MetricType.BLOOD_PRESSURE,
            measured_at=timezone.make_aware(datetime(2025, 3, 1, 8, 0), tz),
        )

        result = HealthMetricService.count_metric_uploads_by_month(
            patient=patient,
            metric_types=[MetricType.BLOOD_PRESSURE, MetricType.HEART_RATE],
            start_date=date(2025, 1, 10),
            end_date=date(2025, 3, 5),
        )

        self.assertEqual(
            result[MetricType.BLOOD_PRESSURE],
            [
                {"month": "2025-01", "count": 2},
                {"month": "2025-02", "count": 0},
                {"month": "2025-03", "count": 1},
            ],
        )
        self.assertEqual(
            result[MetricType.HEART_RATE],
            [
                {"month": "2025-01", "count": 0},
                {"month": "2025-02", "count": 1},
                {"month": "2025-03", "count": 0},
            ],
        )

    def test_count_metric_uploads_by_month_end_date_inclusive(self):
        patient = PatientProfile.objects.create(phone="13800138006")
        tz = timezone.get_current_timezone()
        jan_end = timezone.make_aware(datetime(2025, 1, 31, 23, 59, 59), tz)
        feb_start = timezone.make_aware(datetime(2025, 2, 1, 0, 0), tz)

        HealthMetric.objects.create(
            patient=patient,
            metric_type=MetricType.BLOOD_PRESSURE,
            measured_at=jan_end,
        )
        HealthMetric.objects.create(
            patient=patient,
            metric_type=MetricType.BLOOD_PRESSURE,
            measured_at=feb_start,
        )

        result = HealthMetricService.count_metric_uploads_by_month(
            patient=patient,
            metric_types=[MetricType.BLOOD_PRESSURE],
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
        )

        self.assertEqual(
            result[MetricType.BLOOD_PRESSURE],
            [{"month": "2025-01", "count": 1}],
        )

    def test_count_metric_uploads_by_month_rejects_monitoring_all(self):
        """
        不支持 MONITORING_ADHERENCE_ALL。
        """
        patient = PatientProfile.objects.create(phone="13800138003")

        with self.assertRaises(ValueError):
            HealthMetricService.count_metric_uploads_by_month(
                patient=patient,
                metric_types=[task_service.MONITORING_ADHERENCE_ALL],
                start_date=date(2025, 1, 1),
                end_date=date(2025, 1, 31),
            )
