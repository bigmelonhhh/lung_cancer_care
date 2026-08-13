from base64 import b64decode
from datetime import date, datetime, timedelta
from decimal import Decimal
import json
from urllib.parse import urlencode

from django.core.cache import cache
from django.test import tag
from django.urls import reverse
from django.utils import timezone

from business_support.models import SystemDocument
from core.models import (
    CheckupLibrary,
    DailyTask,
    MonitoringTemplate,
    Questionnaire,
    QuestionnaireCode,
    QuestionnaireOption,
    QuestionnaireQuestion,
    PlanItem,
    TreatmentCycle,
    choices as core_choices,
)
from core.models.choices import CheckupCategory, PlanItemCategory, ReportType, TaskStatus
from health_data.models import (
    HealthMetric,
    MetricMeasurementContext,
    MetricType,
    QuestionnaireAnswer,
    QuestionnaireSubmission,
    ReportImage,
    ReportUpload,
)
from market.models import Order
from users.models import PatientProfile

from tests.browser.web_patient.base import PatientBrowserTestCase, expect


@tag("browser")
class PatientPagesBrowserTests(PatientBrowserTestCase):
    def _open(self, view_name, *args, params=None):
        url = self.url_for(view_name, *args)
        if params:
            url += "?" + urlencode(params)
        self.page.goto(url, wait_until="domcontentloaded")

    def _create_checkup_task(self):
        checkup = CheckupLibrary.objects.create(
            name="血常规",
            code="BLOOD_ROUTINE_BROWSER",
            category=CheckupCategory.BLOOD,
            related_report_type=ReportType.BLOOD_ROUTINE,
        )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=timezone.localdate(),
            task_type=PlanItemCategory.CHECKUP,
            title="血常规",
            status=TaskStatus.PENDING,
            interaction_payload={"checkup_id": checkup.id},
        )
        return checkup

    def _create_questionnaire_submission(self):
        questionnaire, _ = Questionnaire.objects.get_or_create(
            code=QuestionnaireCode.Q_ANXIETY,
            defaults={"name": "焦虑评估", "is_active": True},
        )
        q1 = QuestionnaireQuestion.objects.create(
            questionnaire=questionnaire,
            text="最近是否感到紧张？",
            q_type=core_choices.QuestionType.SINGLE,
            seq=1,
            is_required=True,
        )
        option = QuestionnaireOption.objects.create(
            question=q1,
            text="经常",
            score=Decimal("3.00"),
            seq=1,
        )
        submission = QuestionnaireSubmission.objects.create(
            patient=self.patient,
            questionnaire=questionnaire,
            total_score=Decimal("3.00"),
        )
        QuestionnaireAnswer.objects.create(submission=submission, question=q1, option=option)
        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=QuestionnaireCode.Q_ANXIETY,
            measured_at=timezone.make_aware(datetime(2025, 3, 10, 10, 0)),
            value_main=Decimal("3.00"),
            source="manual",
            questionnaire_submission=submission,
        )
        return submission

    def test_patient_home_dashboard_and_profile_pages_load(self):
        self._open("web_patient:patient_home")
        expect(self.page.locator("body")).to_contain_text("Browser Patient")
        expect(self.page.locator("body")).to_contain_text("问题咨询")
        expect(self.page.locator("body")).to_contain_text("健康档案")
        expect(self.page.locator("body")).to_contain_text("当前用药")
        expect(self.page.locator("body")).to_contain_text("今日计划")

        self._open("web_patient:patient_dashboard")
        expect(self.page.locator("body")).to_contain_text("我的随访")
        expect(self.page.locator("body")).to_contain_text("我的复查")
        expect(self.page.locator("body")).to_contain_text("我的用药")
        expect(self.page.locator("body")).to_contain_text("智能设备")
        expect(self.page.locator("body")).to_contain_text("亲情账号")

        self._open("web_patient:profile_page")
        expect(self.page.locator("body")).to_contain_text("康复档案")
        expect(self.page.locator("body")).to_contain_text("Browser Patient")

        self._open("web_patient:profile_card", self.patient.id)
        expect(self.page.locator("body")).to_contain_text("Browser Patient")

        self._open("web_patient:profile_edit", self.patient.id)
        expect(self.page.locator("body")).to_contain_text("姓名")
        expect(self.page.locator("body")).to_contain_text("手机号")

        self._open("web_patient:reminder_settings")
        expect(self.page.locator("body")).to_contain_text("提醒设置")

    def test_patient_home_checkup_task_opens_record_page(self):
        self._create_checkup_task()
        page_errors = []
        self.page.on("pageerror", lambda error: page_errors.append(str(error)))
        self.page.route(
            "**/static/web_patient/patient_home.js*",
            lambda route: route.abort(),
        )

        self._open("web_patient:patient_home")

        action = self.page.locator("#plan-action-checkup a")
        expect(action).to_be_visible()
        href = action.get_attribute("href") or ""
        self.assertIn(reverse("web_patient:record_checkup"), href)
        self.assertIn(f"patient_id={self.patient.id}", href)
        self.assertIn("source=home", href)
        action.click()

        self.page.wait_for_load_state("domcontentloaded")
        self.assertIn(reverse("web_patient:record_checkup"), self.page.url)
        self.assertIn("source=home", self.page.url)
        expect(self.page.locator("body")).to_contain_text("复查上报")

        self.page.go_back(wait_until="domcontentloaded")
        expect(self.page.locator("#plan-action-checkup a")).to_be_visible()
        self.assertFalse(
            any("handleTaskClick is not defined" in message for message in page_errors),
            page_errors,
        )

    def test_patient_home_medication_task_opens_modal(self):
        page_errors = []
        self.page.on("pageerror", lambda error: page_errors.append(str(error)))
        today = timezone.localdate()
        TreatmentCycle.objects.create(
            patient=self.patient,
            name="用药测试疗程",
            start_date=today,
            end_date=today,
            cycle_days=1,
            status=core_choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=today,
            task_type=PlanItemCategory.MEDICATION,
            title="用药提醒",
            status=TaskStatus.PENDING,
        )

        self._open("web_patient:patient_home")

        action = self.page.locator(
            '#plan-action-medication [data-home-task-action="medication"]'
        )
        expect(action).to_be_visible()
        action.click()

        expect(self.page.locator("#medication-modal")).to_be_visible()
        self.page.evaluate(
            "window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true }))"
        )
        self.assertFalse(
            any("handleTaskClick is not defined" in message for message in page_errors),
            page_errors,
        )

    def test_patient_home_trial_can_open_task_without_member_extras(self):
        Order.objects.filter(patient=self.patient).delete()
        cache.clear()
        today = timezone.localdate()
        TreatmentCycle.objects.create(
            patient=self.patient,
            name="免费体验疗程",
            start_date=today,
            end_date=today,
            cycle_days=1,
            status=core_choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=today,
            task_type=PlanItemCategory.MEDICATION,
            title="用药提醒",
            status=TaskStatus.PENDING,
        )

        self._open("web_patient:patient_home")

        expect(self.page.get_by_text("今日步数", exact=True)).to_have_count(0)
        expect(self.page.get_by_text("查看历史", exact=True)).to_have_count(0)
        expect(self.page.get_by_text("查看我的康复计划", exact=True)).to_have_count(0)
        expect(
            self.page.locator("[data-home-management-plan-link]")
        ).to_have_attribute("href", reverse("web_patient:management_plan"))
        action = self.page.locator(
            '#plan-action-medication [data-home-task-action="medication"]'
        )
        expect(action).to_be_visible()
        action.click()
        expect(self.page.locator("#medication-modal")).to_be_visible()
        expect(self.page.locator("#member-only-modal")).to_be_hidden()

    def test_patient_home_trial_keeps_recorded_value_after_visibility_refresh(self):
        Order.objects.filter(patient=self.patient).delete()
        cache.clear()
        today = timezone.localdate()
        TreatmentCycle.objects.create(
            patient=self.patient,
            name="免费体验疗程",
            start_date=today,
            end_date=today,
            cycle_days=1,
            status=core_choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=today,
            task_type=PlanItemCategory.MONITORING,
            title="血氧监测",
            status=TaskStatus.COMPLETED,
        )

        def fulfill_plan_refresh(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "success": True,
                        "plans": {
                            "spo2": {
                                "type": "spo2",
                                "status": "completed",
                                "subtitle": "今日已记录：99%",
                            }
                        },
                    }
                ),
            )

        self.page.route("**/api/last_metric/**", fulfill_plan_refresh)
        self.page.add_init_script(
            """
            (() => {
              const fixedNow = Date.now();
              Date.now = () => fixedNow;
              try {
                const now = new Date();
                const date = [
                  now.getFullYear(),
                  String(now.getMonth() + 1).padStart(2, '0'),
                  String(now.getDate()).padStart(2, '0')
                ].join('-');
                localStorage.setItem('home_plan_refresh_marker', JSON.stringify({
                  completedTypes: ['spo2'],
                  date,
                  expiresAt: fixedNow + 600000
                }));
              } catch (error) {}
            })();
            """
        )

        self._open("web_patient:patient_home")

        subtitle = self.page.locator("#plan-subtitle-spo2")
        expect(subtitle).to_have_text("今日已记录：99%")
        self.page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        expect(subtitle).to_have_text("今日已记录：99%")

    def test_patient_home_bfcache_refresh_rebuilds_real_task_link(self):
        self._create_checkup_task()
        refresh_state = {"status": "completed"}

        def fulfill_plan_refresh(route):
            status = refresh_state["status"]
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "success": True,
                        "plans": {
                            "checkup": {
                                "type": "checkup",
                                "status": status,
                                "subtitle": "已完成复查任务"
                                if status == "completed"
                                else "请及时完成您的复查任务",
                                "action_text": "去完成",
                                "url": "/p/record/checkup/?ids=3%2C5&label=%E5%A4%8D%E6%9F%A5+A",
                            }
                        },
                    }
                ),
            )

        self.page.route("**/api/last_metric/**", fulfill_plan_refresh)
        self._open("web_patient:patient_home")

        expect(self.page.locator("#plan-action-checkup a")).to_have_count(0)
        refresh_state["status"] = "pending"
        self.page.evaluate(
            "window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true }))"
        )

        action = self.page.locator("#plan-action-checkup a")
        expect(action).to_be_visible()
        action_classes = action.get_attribute("class") or ""
        self.assertIn("bg-blue-600", action_classes)
        self.assertIn("text-white", action_classes)
        self.assertNotIn("bg-white", action_classes.split())
        href = action.get_attribute("href") or ""
        self.assertIn("ids=3%2C5", href)
        self.assertIn("label=%E5%A4%8D%E6%9F%A5+A", href)
        self.assertIn(f"patient_id={self.patient.id}", href)
        self.assertIn("source=home", href)

    def test_record_and_health_record_pages_load(self):
        checkup = self._create_checkup_task()

        self._open("web_patient:record_temperature")
        expect(self.page.locator("body")).to_contain_text("当前体温")
        expect(self.page.locator('input[name="temperature"]')).to_be_visible()

        self._open("web_patient:record_bp")
        expect(self.page.locator("body")).to_contain_text("当前血压与心率")

        self._open("web_patient:record_spo2")
        expect(self.page.locator("body")).to_contain_text("当前血氧")

        self._open("web_patient:record_weight")
        expect(self.page.locator("body")).to_contain_text("当前体重")

        self._open("web_patient:record_checkup")
        expect(self.page.locator("body")).to_contain_text("复查上报")
        expect(self.page.locator("body")).to_contain_text("血常规")
        expect(self.page.locator("body")).to_contain_text("上传复查结果")

        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BODY_TEMPERATURE,
            measured_at=timezone.now(),
            value_main=Decimal("36.80"),
            source="manual",
        )
        self._open("web_patient:health_records")
        expect(self.page.locator("body")).to_contain_text("健康档案")
        expect(self.page.locator("body")).to_contain_text("复查档案")
        expect(self.page.locator("body")).to_contain_text("随访问卷")
        expect(self.page.locator("body")).to_contain_text("体温")
        expect(self.page.locator("body")).not_to_contain_text("血压")
        expect(self.page.locator("body")).not_to_contain_text("异常：0次")

        self._open(
            "web_patient:health_record_detail",
            params={"type": "temperature", "title": "体温", "month": "2025-03"},
        )
        expect(self.page.locator("body")).to_contain_text("体温")
        expect(self.page.locator("body")).to_contain_text("暂无记录")

        self._open(
            "web_patient:review_record_detail",
            params={"title": "血常规", "category_code": checkup.code, "month": "2025-03"},
        )
        expect(self.page.locator("body")).to_contain_text("血常规")
        expect(self.page.locator("body")).to_contain_text("暂无数据")

    def test_general_monitoring_record_archive_and_detail_flow(self):
        today = timezone.localdate()
        cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="一般监测浏览器测试疗程",
            start_date=today,
            end_date=today,
            cycle_days=1,
            status=core_choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        template, _ = MonitoringTemplate.objects.get_or_create(
            code=MetricType.BLOOD_GLUCOSE,
            defaults={
                "name": "血糖监测",
                "metric_type": MetricType.BLOOD_GLUCOSE,
                "is_active": True,
            },
        )
        plan_item = PlanItem.objects.create(
            cycle=cycle,
            category=PlanItemCategory.MONITORING,
            template_id=template.id,
            item_name=template.name,
            schedule_days=[1],
            status=core_choices.PlanItemStatus.ACTIVE,
        )
        DailyTask.objects.create(
            patient=self.patient,
            plan_item=plan_item,
            task_date=today,
            task_type=PlanItemCategory.MONITORING,
            title=template.name,
            status=TaskStatus.PENDING,
        )

        self._open("web_patient:patient_home")
        action = self.page.locator("#plan-action-glucose a")
        expect(action).to_be_visible()
        self.assertIn(
            reverse("web_patient:record_general_monitoring", args=["glucose"]),
            action.get_attribute("href") or "",
        )
        action.click()
        self.page.wait_for_load_state("domcontentloaded")
        expect(self.page.locator("body")).to_contain_text("当前血糖")
        self.page.locator("#measurement-context").select_option(
            MetricMeasurementContext.FASTING
        )
        self.page.locator("#metric-value").fill("6.2")
        self.page.locator("#submit-button").click()
        self.page.wait_for_url("**/p/home/**", timeout=10000)

        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BLOOD_KETONE,
            measured_at=timezone.now(),
            value_main=Decimal("0.5"),
            source="manual",
        )
        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.URIC_ACID,
            measured_at=timezone.now(),
            value_main=Decimal("380"),
            source="manual",
        )

        self._open("web_patient:health_records")
        expect(self.page.locator("body")).to_contain_text("血糖")
        expect(self.page.locator("body")).to_contain_text("血酮")
        expect(self.page.locator("body")).to_contain_text("尿酸")

        self._open(
            "web_patient:health_record_detail",
            params={"type": "glucose", "title": "血糖"},
        )
        expect(self.page.locator("body")).to_contain_text("血糖")
        expect(self.page.locator("body")).to_contain_text("6.2 mmol/L")
        expect(self.page.locator("body")).to_contain_text("空腹")
        expect(self.page.locator("body")).not_to_contain_text("评分")

        manual_html = self.page.evaluate(
            """buildDataBlockHtml({
                is_manual: true,
                data: [
                    {key: 'glucose', label: '血糖', value: '6.2 mmol/L'},
                    {key: 'measurement_context', label: '测量场景', value: '空腹'}
                ]
            })"""
        )
        device_html = self.page.evaluate(
            """buildDataBlockHtml({
                is_manual: false,
                data: [
                    {key: 'glucose', label: '血糖', value: '6.2 mmol/L'},
                    {key: 'measurement_context', label: '测量场景', value: '空腹'}
                ]
            })"""
        )
        self.assertIn("测量场景：空腹", manual_html)
        self.assertNotIn("测量场景", device_html)

    def test_record_checkup_upload_image_opens_clear_preview(self):
        self._create_checkup_task()
        self.page.set_viewport_size({"width": 320, "height": 700})
        self._open("web_patient:record_checkup")
        self.page.evaluate("closeModal()")

        png = b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        self.page.locator('input[type="file"]').first.set_input_files(
            {"name": "checkup.png", "mimeType": "image/png", "buffer": png}
        )

        preview_button = self.page.get_by_role("button", name="查看待上传复查原图")
        expect(preview_button).to_be_visible()
        preview_button.click()

        modal = self.page.locator("#checkup-image-modal")
        expect(modal).to_be_visible()
        modal_image = self.page.locator("#checkup-modal-image")
        modal_src = modal_image.get_attribute("src") or ""
        self.assertTrue(modal_src.startswith(("blob:", "data:")))
        self.assertEqual(
            modal_image.evaluate("element => getComputedStyle(element).filter"),
            "none",
        )

        self.page.get_by_role("button", name="关闭复查原图预览").click()
        expect(modal).to_be_hidden()

    def test_record_checkup_removing_processing_image_cancels_queue(self):
        self._create_checkup_task()
        self.page.set_viewport_size({"width": 375, "height": 760})
        self._open("web_patient:record_checkup")
        self.page.evaluate("closeModal()")
        self.page.evaluate(
            """
            () => {
                window.__compressionAbortCount = 0;
                window.imageCompression = (file, options) => new Promise((resolve, reject) => {
                    options.signal.addEventListener('abort', () => {
                        window.__compressionAbortCount += 1;
                        reject(new DOMException('Aborted', 'AbortError'));
                    }, { once: true });
                });
                window.confirm = () => true;
            }
            """
        )
        png = b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        self.page.locator('input[type="file"]').first.set_input_files(
            {"name": "checkup.png", "mimeType": "image/png", "buffer": png}
        )

        expect(self.page.get_by_text("处理中", exact=True)).to_be_visible()
        self.page.get_by_role("button", name="删除待上传的复查图片").click()
        expect(self.page.get_by_role("button", name="查看待上传复查原图")).to_have_count(0)
        self.page.wait_for_function("() => window.__compressionAbortCount === 1")
        self.assertFalse(self.page.evaluate("compressionQueue.hasPending()"))
        self.assertLessEqual(
            self.page.evaluate("document.documentElement.scrollWidth"),
            375,
        )

        self.page.locator('button[onclick="submitCheckup()"]:visible').click()
        expect(self.page.locator("#status-message")).to_contain_text("请至少上传")

    def test_plan_followup_examination_and_calendar_pages_load(self):
        self._open("web_patient:management_plan")
        expect(self.page.locator("body")).to_contain_text("我的管理计划")
        expect(self.page.locator("body")).to_contain_text("常规监测计划")
        expect(self.page.locator("body")).to_contain_text("测量体温")
        expect(self.page.locator("body")).to_contain_text("今日无计划")

        self._open("web_patient:my_medication")
        expect(self.page.locator("body")).to_contain_text("我的用药")
        expect(self.page.locator("body")).to_contain_text("暂无用药记录")
        expect(self.page.locator("body")).to_contain_text("请联系医生为您制定康复计划")

        self._open("web_patient:my_followup")
        expect(self.page.locator("body")).to_contain_text("我的随访")

        self._open("web_patient:my_examination")
        expect(self.page.locator("body")).to_contain_text("我的复查")

        self._open("web_patient:daily_survey")
        expect(self.page.locator("body")).to_contain_text("暂无问卷数据", timeout=10000)

        self._open("web_patient:health_calendar")
        expect(self.page.locator("body")).to_contain_text("健康日历")
        expect(self.page.locator("body")).to_contain_text("今日计划")

    def test_management_plan_treatment_course_sections_expand_and_collapse(self):
        today = timezone.localdate()
        current_cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="浏览器进行中疗程",
            start_date=today - timedelta(days=5),
            end_date=today + timedelta(days=15),
            cycle_days=21,
            status=core_choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        future_cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="浏览器未开始疗程",
            start_date=today + timedelta(days=20),
            end_date=today + timedelta(days=40),
            cycle_days=21,
            status=core_choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        ended_cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="浏览器已结束疗程",
            start_date=today - timedelta(days=40),
            end_date=today - timedelta(days=20),
            cycle_days=21,
            status=core_choices.TreatmentCycleStatus.COMPLETED,
        )
        for cycle in (current_cycle, future_cycle, ended_cycle):
            DailyTask.objects.create(
                patient=self.patient,
                task_date=cycle.start_date,
                task_type=PlanItemCategory.QUESTIONNAIRE,
                title=f"{cycle.name}问卷",
                status=TaskStatus.PENDING,
            )

        self.page.set_viewport_size({"width": 375, "height": 812})
        self._open("web_patient:management_plan")

        current_section = self.page.locator('[data-course-section="in_progress"]')
        future_section = self.page.locator('[data-course-section="not_started"]')
        ended_section = self.page.locator('[data-course-section="ended"]')

        expect(current_section).to_have_attribute("open", "")
        expect(future_section).not_to_have_attribute("open", "")
        expect(ended_section).not_to_have_attribute("open", "")
        expect(current_section.get_by_text(current_cycle.name, exact=True)).to_be_visible()
        expect(future_section.get_by_text(future_cycle.name, exact=True)).to_be_hidden()
        expect(ended_section.get_by_text(ended_cycle.name, exact=True)).to_be_hidden()

        future_section.locator("summary").click()
        expect(future_section).to_have_attribute("open", "")
        expect(future_section.get_by_text(future_cycle.name, exact=True)).to_be_visible()

        ended_section.locator("summary").click()
        expect(ended_section.get_by_text(ended_cycle.name, exact=True)).to_be_visible()
        ended_section.locator("summary").click()
        expect(ended_section.get_by_text(ended_cycle.name, exact=True)).to_be_hidden()

        self.assertLessEqual(
            self.page.evaluate("document.documentElement.scrollWidth"),
            375,
        )

    def _assert_specialized_course_page_sections(self, *, view_name, included_type):
        today = timezone.localdate()
        current_cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name=f"浏览器{included_type}进行中疗程",
            start_date=today - timedelta(days=5),
            end_date=today + timedelta(days=15),
            cycle_days=21,
            status=core_choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        future_cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name=f"浏览器{included_type}未开始疗程",
            start_date=today + timedelta(days=20),
            end_date=today + timedelta(days=40),
            cycle_days=21,
            status=core_choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        ended_cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name=f"浏览器{included_type}已结束疗程",
            start_date=today - timedelta(days=40),
            end_date=today - timedelta(days=20),
            cycle_days=21,
            status=core_choices.TreatmentCycleStatus.COMPLETED,
        )
        if included_type == "复查":
            included_category = PlanItemCategory.CHECKUP
            excluded_category = PlanItemCategory.QUESTIONNAIRE
            excluded_title = "不应显示的随访问卷"
        else:
            included_category = PlanItemCategory.QUESTIONNAIRE
            excluded_category = PlanItemCategory.CHECKUP
            excluded_title = "不应显示的复查"

        for cycle in (current_cycle, future_cycle, ended_cycle):
            DailyTask.objects.create(
                patient=self.patient,
                task_date=cycle.start_date,
                task_type=included_category,
                title=f"{cycle.name}{included_type}",
                status=TaskStatus.PENDING,
            )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=today,
            task_type=excluded_category,
            title=excluded_title,
            status=TaskStatus.PENDING,
        )

        self.page.set_viewport_size({"width": 375, "height": 812})
        self._open(view_name)

        current_section = self.page.locator('[data-course-section="in_progress"]')
        future_section = self.page.locator('[data-course-section="not_started"]')
        ended_section = self.page.locator('[data-course-section="ended"]')
        expect(current_section).to_have_attribute("open", "")
        expect(future_section).not_to_have_attribute("open", "")
        expect(ended_section).not_to_have_attribute("open", "")
        expect(current_section.get_by_text(current_cycle.name, exact=True)).to_be_visible()
        expect(self.page.get_by_text(included_type, exact=True).first).to_be_visible()
        expect(self.page.get_by_text(excluded_title, exact=True)).to_have_count(0)

        future_section.locator("summary").click()
        expect(future_section.get_by_text(future_cycle.name, exact=True)).to_be_visible()
        ended_section.locator("summary").click()
        expect(ended_section.get_by_text(ended_cycle.name, exact=True)).to_be_visible()
        ended_section.locator("summary").click()
        expect(ended_section.get_by_text(ended_cycle.name, exact=True)).to_be_hidden()

        self.assertLessEqual(
            self.page.evaluate("document.documentElement.scrollWidth"),
            375,
        )

    def test_my_examination_course_sections_expand_and_only_show_checkups(self):
        self._assert_specialized_course_page_sections(
            view_name="web_patient:my_examination",
            included_type="复查",
        )

    def test_my_followup_course_sections_expand_and_only_show_questionnaires(self):
        self._assert_specialized_course_page_sections(
            view_name="web_patient:my_followup",
            included_type="随访问卷",
        )

    def test_daily_survey_renders_text_inputs_and_submits_mixed_answer_payloads(self):
        today = timezone.localdate()
        cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="EQVAS浏览器测试疗程",
            start_date=today,
            end_date=today,
            cycle_days=1,
            status=core_choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        ordinary = Questionnaire.objects.create(
            name="普通填空问卷",
            code="Q_BROWSER_TEXT",
            is_active=True,
        )
        ordinary_text = QuestionnaireQuestion.objects.create(
            questionnaire=ordinary,
            text="请补充说明",
            q_type=core_choices.QuestionType.TEXT,
            seq=1,
            is_required=True,
        )
        eqvas = Questionnaire.objects.create(
            name="EQVAS量表",
            code="Q_EQVAS",
            is_active=True,
        )
        eqvas_text = QuestionnaireQuestion.objects.create(
            questionnaire=eqvas,
            text="EQ-VAS自评分",
            q_type=core_choices.QuestionType.TEXT,
            seq=1,
            is_required=True,
        )

        for questionnaire in (ordinary, eqvas):
            plan_item = PlanItem.objects.create(
                cycle=cycle,
                category=PlanItemCategory.QUESTIONNAIRE,
                template_id=questionnaire.id,
                item_name=questionnaire.name,
                schedule_days=[1],
                status=core_choices.PlanItemStatus.ACTIVE,
            )
            DailyTask.objects.create(
                patient=self.patient,
                plan_item=plan_item,
                task_date=today,
                task_type=PlanItemCategory.QUESTIONNAIRE,
                title=questionnaire.name,
                status=TaskStatus.PENDING,
            )

        submitted_payloads = []

        def capture_submission(route):
            submitted_payloads.append(json.loads(route.request.post_data))
            route.fulfill(
                status=200,
                content_type="application/json",
                body='{"success": true, "submission_id": 1}',
            )

        self.page.route("**/p/api/survey/submit/**", capture_submission)
        self._open(
            "web_patient:daily_survey",
            params={"ids": f"{ordinary.id},{eqvas.id}"},
        )

        ordinary_input = self.page.locator(
            f'textarea[name="question_{ordinary_text.id}"]'
        )
        eqvas_hint_text = (
            "请按您今天的整体健康状况评分：0分代表您能想象的最差健康状况，"
            "100分代表最好。该分数用于记录您的自身感受，并帮助医生观察健康变化趋势。"
        )
        expect(ordinary_input).to_be_visible()
        expect(self.page.get_by_text(eqvas_hint_text, exact=True)).to_have_count(0)
        ordinary_input.fill("恢复情况良好")
        self.page.get_by_role("button", name="下一题").click()

        eqvas_input = self.page.locator(
            f'input[name="question_{eqvas_text.id}"][inputmode="numeric"]'
        )
        expect(eqvas_input).to_be_visible()
        expect(self.page.get_by_text(eqvas_hint_text, exact=True)).to_be_visible()
        eqvas_input.fill("1.5")
        expect(eqvas_input).to_have_value("")

        validation_messages = []

        def capture_validation_message(dialog):
            validation_messages.append(dialog.message)
            dialog.accept()

        self.page.once("dialog", capture_validation_message)
        eqvas_input.fill("101")
        self.page.get_by_role("button", name="已完成答卷，提交").click()
        self.page.wait_for_timeout(100)
        self.assertEqual(
            validation_messages,
            ["EQ-VAS 自评分请输入 0 至 100 的整数"],
        )
        self.assertEqual(submitted_payloads, [])

        eqvas_input.fill("0")
        self.page.get_by_role("button", name="已完成答卷，提交").click()
        self.page.wait_for_timeout(200)

        self.assertEqual(len(submitted_payloads), 2)
        self.assertEqual(
            submitted_payloads[0]["answers"],
            [{"question_id": ordinary_text.id, "value_text": "恢复情况良好"}],
        )
        self.assertEqual(
            submitted_payloads[1]["answers"],
            [{"question_id": eqvas_text.id, "value_text": "0"}],
        )

    def test_daily_survey_renders_eq5d5l_as_five_single_choice_questions(self):
        today = timezone.localdate()
        cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="EQ5D5L浏览器测试疗程",
            start_date=today,
            end_date=today,
            cycle_days=1,
            status=core_choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        questionnaire = Questionnaire.objects.create(
            name="EQ5D5L量表",
            code="Q_EQ5D5L",
            is_active=True,
        )
        for seq in range(5):
            question = QuestionnaireQuestion.objects.create(
                questionnaire=questionnaire,
                text=f"维度{seq + 1}",
                q_type=core_choices.QuestionType.SINGLE,
                seq=seq,
                is_required=True,
            )
            QuestionnaireOption.objects.create(
                question=question,
                text="没有困难",
                value="1",
                score=Decimal("1"),
                seq=1,
            )
        plan_item = PlanItem.objects.create(
            cycle=cycle,
            category=PlanItemCategory.QUESTIONNAIRE,
            template_id=questionnaire.id,
            item_name=questionnaire.name,
            schedule_days=[1],
            status=core_choices.PlanItemStatus.ACTIVE,
        )
        DailyTask.objects.create(
            patient=self.patient,
            plan_item=plan_item,
            task_date=today,
            task_type=PlanItemCategory.QUESTIONNAIRE,
            title=questionnaire.name,
            status=TaskStatus.PENDING,
        )

        self._open(
            "web_patient:daily_survey",
            params={"ids": str(questionnaire.id)},
        )

        expect(self.page.locator('.question-item[data-type="SINGLE"]')).to_have_count(5)
        expect(self.page.locator('input[type="radio"]')).to_have_count(5)
        expect(self.page.locator('[data-eqvas-text-answer="true"]')).to_have_count(0)

    def test_reports_orders_device_studio_family_and_feedback_pages_load(self):
        self._open("web_patient:report_list")
        expect(self.page.locator("body")).to_contain_text("检查报告")
        expect(self.page.locator("body")).to_contain_text("暂无检查报告")

        self._open("web_patient:report_upload")
        expect(self.page.locator("body")).to_contain_text("新增报告")
        expect(self.page.locator("body")).to_contain_text("上传日期")
        expect(self.page.locator("body")).to_contain_text("提交")

        self._open("web_patient:orders")
        expect(self.page.locator("body")).to_contain_text("我的订单")
        expect(self.page.locator("body")).to_contain_text("Browser VIP")
        expect(self.page.locator("body")).to_contain_text("订单号")

        self._open("web_patient:device_list")
        expect(self.page.locator("body")).to_contain_text("我的设备")
        expect(self.page.locator("body")).to_contain_text("暂无绑定设备")
        expect(self.page.locator("body")).to_contain_text("绑定新设备")

        self._open("web_patient:my_studio")
        expect(self.page.locator("body")).to_contain_text("医生工作室")
        expect(self.page.locator("body")).to_contain_text("Browser Studio")
        expect(self.page.locator("body")).to_contain_text("工作室编号")

        self._open("web_patient:family_management")
        expect(self.page.locator("body")).to_contain_text("亲情账号")
        expect(self.page.locator("body")).to_contain_text("我的二维码")
        expect(self.page.locator("body")).to_contain_text("亲情账号列表")

        self._open("web_patient:feedback")
        expect(self.page.locator("body")).to_contain_text("反馈问题")
        expect(self.page.locator("body")).to_contain_text("反馈内容")
        expect(self.page.locator("body")).to_contain_text("提交反馈")

    def test_report_upload_image_opens_clear_preview(self):
        self.page.set_viewport_size({"width": 320, "height": 700})
        self._open("web_patient:report_upload")

        png = b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        self.page.locator("#file-input").set_input_files(
            {"name": "report.png", "mimeType": "image/png", "buffer": png}
        )

        preview_button = self.page.get_by_role("button", name="查看待上传报告原图")
        expect(preview_button).to_be_visible()
        preview_button.click()

        modal = self.page.locator("#image-modal")
        expect(modal).to_be_visible()
        modal_image = self.page.locator("#modal-image")
        modal_src = modal_image.get_attribute("src") or ""
        self.assertTrue(modal_src.startswith(("blob:", "data:")))
        self.assertEqual(
            modal_image.evaluate("element => getComputedStyle(element).filter"),
            "none",
        )

        self.page.get_by_role("button", name="关闭原图预览").click()
        expect(modal).to_be_hidden()

    def test_report_upload_handles_stale_compression_script_without_tdz(self):
        page_errors = []
        self.page.on("pageerror", lambda error: page_errors.append(str(error)))
        self.page.route(
            "**/static/web_patient/image_compression.js*",
            lambda route: route.fulfill(
                status=200,
                content_type="application/javascript",
                body="window.LCCImageCompression = { compressOne: function () {} };",
            ),
        )
        self._open("web_patient:report_upload")

        png = b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        self.page.locator("#file-input").set_input_files(
            {"name": "report.png", "mimeType": "image/png", "buffer": png}
        )
        self.page.wait_for_timeout(100)

        self.assertFalse(
            any("compressionQueue" in message for message in page_errors),
            page_errors,
        )
        self.assertIn(
            "图片处理组件加载失败",
            self.page.locator("#status-message").text_content() or "",
        )

    def test_patient_upload_pages_reject_malformed_compression_queue(self):
        self._create_checkup_task()
        page_errors = []
        self.page.on("pageerror", lambda error: page_errors.append(str(error)))
        self.page.route(
            "**/static/web_patient/image_compression.js*",
            lambda route: route.fulfill(
                status=200,
                content_type="application/javascript",
                body="""
                    window.LCCImageCompression = {
                        API_VERSION: 'clinical-readability-v2',
                        inspectImage: async function () {},
                        validateSelection: async function () { return { accepted: [], rejected: [] }; },
                        compressOne: async function () {},
                        createQueue: function () { return {}; },
                        isQueueContract: function (queue) {
                            return ['enqueue', 'cancel', 'hasPending', 'getState', 'destroy']
                                .every(function (name) { return typeof queue[name] === 'function'; });
                        }
                    };
                """,
            ),
        )
        png = b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )

        for view_name, input_selector in (
            ("web_patient:report_upload", "#file-input"),
            ("web_patient:record_checkup", 'input[type="file"]'),
        ):
            with self.subTest(view_name=view_name):
                page_errors.clear()
                self._open(view_name)
                self.page.locator(input_selector).first.set_input_files(
                    {"name": "report.png", "mimeType": "image/png", "buffer": png}
                )
                self.page.wait_for_timeout(100)
                self.assertEqual(page_errors, [])
                self.assertIn(
                    "图片处理组件加载失败",
                    self.page.locator("#status-message").text_content() or "",
                )

    def test_report_upload_handles_missing_abort_controller(self):
        page_errors = []
        self.page.on("pageerror", lambda error: page_errors.append(str(error)))
        self.page.add_init_script("window.AbortController = undefined;")
        self._open("web_patient:report_upload")

        png = b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        self.page.locator("#file-input").set_input_files(
            {"name": "report.png", "mimeType": "image/png", "buffer": png}
        )
        self.page.wait_for_timeout(100)

        self.assertEqual(page_errors, [])
        self.assertIn(
            "当前浏览器版本不支持安全图片处理",
            self.page.locator("#status-message").text_content() or "",
        )

    def test_shared_queue_fails_cleanly_when_abort_controller_constructor_breaks(self):
        self._open("web_patient:report_upload")
        result = self.page.evaluate(
            """
            async () => {
                const bytes = new Uint8Array(24);
                bytes.set([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
                const view = new DataView(bytes.buffer);
                view.setUint32(8, 13);
                bytes.set([0x49, 0x48, 0x44, 0x52], 12);
                view.setUint32(16, 1);
                view.setUint32(20, 1);
                const file = new File([bytes], 'report.png', { type: 'image/png' });
                const queue = window.LCCImageCompression.createQueue({ concurrency: 1 });
                const OriginalAbortController = window.AbortController;
                window.AbortController = class BrokenAbortController {
                    constructor() { throw new Error('constructor failed'); }
                };
                let errorCode = '';
                try {
                    await queue.enqueue({ id: 'broken-controller', file });
                } catch (error) {
                    errorCode = error.code || '';
                } finally {
                    window.AbortController = OriginalAbortController;
                }
                return {
                    errorCode,
                    state: queue.getState('broken-controller'),
                    pending: queue.hasPending(),
                };
            }
            """
        )

        self.assertEqual(result["errorCode"], "library_unavailable")
        self.assertEqual(result["state"], "failed")
        self.assertFalse(result["pending"])

    def test_shared_image_compression_validates_headers_policy_and_timeout(self):
        self._open("web_patient:report_upload")
        result = self.page.evaluate(
            """
            async () => {
                const pngHeader = (width, height) => {
                    const bytes = new Uint8Array(24);
                    bytes.set([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
                    const view = new DataView(bytes.buffer);
                    view.setUint32(8, 13);
                    bytes.set([0x49, 0x48, 0x44, 0x52], 12);
                    view.setUint32(16, width);
                    view.setUint32(20, height);
                    return bytes;
                };
                const jpeg = new File([new Uint8Array([
                    0xff, 0xd8, 0xff, 0xc0, 0x00, 0x11, 0x08,
                    0x00, 0x02, 0x00, 0x03, 0x03, 0x01, 0x11,
                    0x00, 0x02, 0x11, 0x00, 0x03, 0x11, 0x00,
                ])], 'report.png', { type: 'image/png' });
                const valid = new File([pngHeader(1200, 1800)], 'report.jpg', { type: 'image/jpeg' });
                const fake = new File([new Uint8Array([0x47, 0x49, 0x46, 0x38])], 'fake.png', { type: 'image/png' });
                const empty = new File([], 'empty.jpg', { type: 'image/jpeg' });
                const hugePixels = new File([pngHeader(8000, 6000)], 'huge.png', { type: 'image/png' });
                const exactPixels = new File([pngHeader(8000, 5000)], 'exact.png', { type: '' });
                const tooLarge = new File([pngHeader(1, 1), new Uint8Array(10 * 1024 * 1024)], 'large.png', { type: 'image/png' });
                const codes = {};
                for (const [name, file] of Object.entries({ fake, empty, hugePixels, tooLarge })) {
                    try { await window.LCCImageCompression.inspectImage(file); }
                    catch (error) { codes[name] = error.code; }
                }

                const limitResult = await window.LCCImageCompression.validateSelection(
                    Array.from({ length: 12 }, () => ({ originalSize: 1 })),
                    [valid]
                );
                const totalResult = await window.LCCImageCompression.validateSelection(
                    [{ originalSize: 60 * 1024 * 1024 }],
                    [valid]
                );
                const countBoundary = await window.LCCImageCompression.validateSelection(
                    Array.from({ length: 11 }, () => ({ originalSize: 1 })),
                    [valid]
                );
                const totalBoundary = await window.LCCImageCompression.validateSelection(
                    [{ originalSize: 60 * 1024 * 1024 - valid.size }],
                    [valid]
                );
                let captured = null;
                let capturedInput = null;
                window.imageCompression = async (file, options) => {
                    captured = options;
                    capturedInput = { name: file.name, type: file.type };
                    return new File([new Uint8Array([1, 2, 3])], file.name, { type: options.fileType });
                };
                const compressed = await window.LCCImageCompression.compressOne(valid, { timeoutMs: 1000 });

                window.imageCompression = async (file, options) => new File(
                    [new Uint8Array(Math.floor(1.5 * 1024 * 1024) + 1)],
                    file.name,
                    { type: options.fileType }
                );
                let outputLimitCode = '';
                try { await window.LCCImageCompression.compressOne(valid, { timeoutMs: 1000 }); }
                catch (error) { outputLimitCode = error.code; }

                let aborted = false;
                window.imageCompression = (file, options) => new Promise((resolve, reject) => {
                    options.signal.addEventListener('abort', () => {
                        aborted = true;
                        reject(new DOMException('Aborted', 'AbortError'));
                    }, { once: true });
                });
                let timeoutCode = '';
                try { await window.LCCImageCompression.compressOne(valid, { timeoutMs: 20 }); }
                catch (error) { timeoutCode = error.code; }

                let queueAbortCount = 0;
                let markQueueStarted;
                const queueStarted = new Promise(resolve => { markQueueStarted = resolve; });
                window.imageCompression = (file, options) => new Promise((resolve, reject) => {
                    markQueueStarted();
                    options.signal.addEventListener('abort', () => {
                        queueAbortCount += 1;
                        reject(new DOMException('Aborted', 'AbortError'));
                    }, { once: true });
                });
                const queue = window.LCCImageCompression.createQueue({ concurrency: 1 });
                const activePromise = queue.enqueue({ id: 'active', file: valid }).catch(error => error.code);
                const queuedPromise = queue.enqueue({ id: 'queued', file: valid }).catch(error => error.code);
                queue.cancel('queued');
                await queueStarted;
                queue.cancel('active');
                const queueCodes = await Promise.all([activePromise, queuedPromise]);

                return {
                    inspection: await window.LCCImageCompression.inspectImage(valid),
                    jpegInspection: await window.LCCImageCompression.inspectImage(jpeg),
                    exactPixels: await window.LCCImageCompression.inspectImage(exactPixels),
                    codes,
                    limitCode: limitResult.rejected[0].code,
                    totalMessage: totalResult.rejected[0].message,
                    countBoundaryAccepted: countBoundary.accepted.length,
                    totalBoundaryAccepted: totalBoundary.accepted.length,
                    capturedInput,
                    outputLimitCode,
                    timeoutCode,
                    aborted,
                    queueAbortCount,
                    queueCodes,
                    queuePending: queue.hasPending(),
                    queueStates: [queue.getState('active'), queue.getState('queued')],
                    policy: {
                        maxWidthOrHeight: captured.maxWidthOrHeight,
                        maxSizeMB: captured.maxSizeMB,
                        initialQuality: captured.initialQuality,
                        preserveExif: captured.preserveExif,
                        useWebWorker: captured.useWebWorker,
                        libURL: captured.libURL,
                    },
                    outputIsOriginal: compressed.file === valid,
                    resultStatus: compressed.status,
                };
            }
            """
        )

        self.assertEqual(result["inspection"]["format"], "png")
        self.assertEqual(result["inspection"]["width"], 1200)
        self.assertEqual(result["inspection"]["height"], 1800)
        self.assertEqual(result["jpegInspection"]["format"], "jpeg")
        self.assertEqual(result["jpegInspection"]["width"], 3)
        self.assertEqual(result["jpegInspection"]["height"], 2)
        self.assertEqual(result["exactPixels"]["pixels"], 40_000_000)
        self.assertEqual(result["codes"]["fake"], "invalid_image")
        self.assertEqual(result["codes"]["empty"], "invalid_image")
        self.assertEqual(result["codes"]["hugePixels"], "too_many_pixels")
        self.assertEqual(result["codes"]["tooLarge"], "too_large")
        self.assertEqual(result["limitCode"], "too_large")
        self.assertIn("60MB", result["totalMessage"])
        self.assertEqual(result["countBoundaryAccepted"], 1)
        self.assertEqual(result["totalBoundaryAccepted"], 1)
        self.assertEqual(result["capturedInput"], {"name": "report.png", "type": "image/png"})
        self.assertEqual(result["outputLimitCode"], "too_large")
        self.assertEqual(result["timeoutCode"], "timeout")
        self.assertTrue(result["aborted"])
        self.assertEqual(result["queueAbortCount"], 1)
        self.assertEqual(result["queueCodes"], ["cancelled", "cancelled"])
        self.assertFalse(result["queuePending"])
        self.assertEqual(result["queueStates"], ["cancelled", "cancelled"])
        self.assertEqual(result["policy"]["maxWidthOrHeight"], 2560)
        self.assertEqual(result["policy"]["maxSizeMB"], 1.5)
        self.assertEqual(result["policy"]["initialQuality"], 0.82)
        self.assertFalse(result["policy"]["preserveExif"])
        self.assertTrue(result["policy"]["useWebWorker"])
        self.assertIn(
            "/static/vendor/browser-image-compression/2.0.2/browser-image-compression.js",
            result["policy"]["libURL"],
        )
        self.assertNotIn("jsdelivr", result["policy"]["libURL"])
        self.assertFalse(result["outputIsOriginal"])
        self.assertEqual(result["resultStatus"], "ready")

    def test_shared_image_compression_preserves_orientation_and_limits_long_edge(self):
        self._open("web_patient:report_upload")
        result = self.page.evaluate(
            """
            async () => {
                const createImageFile = async (width, height, name) => {
                    const canvas = document.createElement('canvas');
                    canvas.width = width;
                    canvas.height = height;
                    const context = canvas.getContext('2d');
                    context.fillStyle = '#ffffff';
                    context.fillRect(0, 0, width, height);
                    context.fillStyle = '#111827';
                    context.font = '80px sans-serif';
                    context.fillText(name, 80, 160);
                    const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.9));
                    return new File([blob], name + '.jpg', { type: 'image/jpeg' });
                };
                const dimensions = async file => {
                    const bitmap = await createImageBitmap(file);
                    const value = { width: bitmap.width, height: bitmap.height };
                    bitmap.close();
                    return value;
                };
                const addValidExifDescription = async file => {
                    const source = new Uint8Array(await file.arrayBuffer());
                    const marker = new TextEncoder().encode('GPS_TEST_MARKER');
                    const tiff = new Uint8Array(26 + marker.length + 1);
                    const tiffView = new DataView(tiff.buffer);
                    tiff.set([0x49, 0x49], 0);
                    tiffView.setUint16(2, 42, true);
                    tiffView.setUint32(4, 8, true);
                    tiffView.setUint16(8, 1, true);
                    tiffView.setUint16(10, 0x010e, true);
                    tiffView.setUint16(12, 2, true);
                    tiffView.setUint32(14, marker.length + 1, true);
                    tiffView.setUint32(18, 26, true);
                    tiffView.setUint32(22, 0, true);
                    tiff.set(marker, 26);

                    const payload = new Uint8Array(6 + tiff.length);
                    payload.set([0x45, 0x78, 0x69, 0x66, 0x00, 0x00], 0);
                    payload.set(tiff, 6);
                    const segmentLength = payload.length + 2;
                    const output = new Uint8Array(source.length + payload.length + 4);
                    output.set(source.slice(0, 2), 0);
                    output.set([0xff, 0xe1, segmentLength >> 8, segmentLength & 0xff], 2);
                    output.set(payload, 6);
                    output.set(source.slice(2), 6 + payload.length);
                    return new File([output], file.name, { type: 'image/jpeg' });
                };
                const containsMarker = async file => {
                    const bytes = new Uint8Array(await file.arrayBuffer());
                    const marker = new TextEncoder().encode('GPS_TEST_MARKER');
                    for (let index = 0; index <= bytes.length - marker.length; index += 1) {
                        if (marker.every((value, offset) => bytes[index + offset] === value)) return true;
                    }
                    return false;
                };
                const landscapeSource = await addValidExifDescription(
                    await createImageFile(3000, 1000, 'landscape')
                );
                const landscape = await window.LCCImageCompression.compressOne(
                    landscapeSource,
                    { timeoutMs: 5000 }
                );
                const portrait = await window.LCCImageCompression.compressOne(
                    await createImageFile(1000, 3000, 'portrait')
                );
                return {
                    landscape: await dimensions(landscape.file),
                    portrait: await dimensions(portrait.file),
                    inputHasExifMarker: await containsMarker(landscapeSource),
                    outputHasExifMarker: await containsMarker(landscape.file),
                    externalCompressionResources: performance.getEntriesByType('resource')
                        .map(entry => entry.name)
                        .filter(url => url.includes('jsdelivr') || url.includes('unpkg')),
                };
            }
            """
        )

        self.assertLessEqual(max(result["landscape"].values()), 2560)
        self.assertGreater(result["landscape"]["width"], result["landscape"]["height"])
        self.assertLessEqual(max(result["portrait"].values()), 2560)
        self.assertGreater(result["portrait"]["height"], result["portrait"]["width"])
        self.assertTrue(result["inputHasExifMarker"])
        self.assertFalse(result["outputHasExifMarker"])
        self.assertEqual(result["externalCompressionResources"], [])

    def test_report_upload_failed_image_blocks_submit_and_can_retry_or_delete(self):
        self.page.set_viewport_size({"width": 320, "height": 700})
        self._open("web_patient:report_upload")
        self.page.evaluate(
            """
            () => {
                window.__uploadFetchCalled = false;
                window.imageCompression = () => Promise.reject(new Error('forced failure'));
                const originalFetch = window.fetch;
                window.fetch = (...args) => {
                    window.__uploadFetchCalled = true;
                    return originalFetch(...args);
                };
                window.confirm = () => true;
            }
            """
        )
        png = b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        self.page.locator("#file-input").set_input_files(
            {"name": "report.png", "mimeType": "image/png", "buffer": png}
        )

        expect(self.page.get_by_text("处理失败", exact=True)).to_be_visible()
        expect(self.page.get_by_role("button", name="重试处理报告图片")).to_be_visible()
        self.assertLessEqual(
            self.page.evaluate("document.documentElement.scrollWidth"),
            320,
        )
        self.page.locator('button[onclick="submitReport()"]:visible').click()
        expect(self.page.locator("#status-message")).to_contain_text("请先重试或删除")
        self.assertFalse(self.page.evaluate("window.__uploadFetchCalled"))

        self.page.evaluate(
            """
            () => {
                window.imageCompression = async (file, options) =>
                    new File([new Uint8Array([1, 2, 3])], file.name, { type: options.fileType });
            }
            """
        )
        self.page.get_by_role("button", name="重试处理报告图片").click()
        self.page.wait_for_function("() => uploads.length === 1 && uploads[0].status === 'ready'")
        expect(self.page.get_by_role("button", name="重试处理报告图片")).to_have_count(0)

        self.page.get_by_role("button", name="删除待上传的报告图片").click()
        expect(self.page.get_by_role("button", name="查看待上传报告原图")).to_have_count(0)
        self.assertFalse(self.page.evaluate("compressionQueue.hasPending()"))

    def test_report_upload_serializes_rapid_selections_and_blocks_early_submit(self):
        self._open("web_patient:report_upload")
        result = self.page.evaluate(
            """
            async () => {
                const pngFile = index => {
                    const bytes = new Uint8Array(24);
                    bytes.set([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
                    const view = new DataView(bytes.buffer);
                    view.setUint32(8, 13);
                    bytes.set([0x49, 0x48, 0x44, 0x52], 12);
                    view.setUint32(16, 1);
                    view.setUint32(20, 1);
                    return new File([bytes], `report-${index}.png`, { type: '' });
                };
                window.imageCompression = async (file, options) =>
                    new File([new Uint8Array([1, 2, 3])], file.name, { type: options.fileType });
                window.__earlyUploadFetch = false;
                window.fetch = () => {
                    window.__earlyUploadFetch = true;
                    return Promise.reject(new Error('unexpected upload'));
                };

                const first = handleFileChange({
                    target: { files: Array.from({ length: 7 }, (_, i) => pngFile(i)), value: 'first' },
                });
                const second = handleFileChange({
                    target: { files: Array.from({ length: 7 }, (_, i) => pngFile(i + 7)), value: 'second' },
                });
                submitReport();
                const submitMessage = document.getElementById('status-message').textContent;
                await Promise.all([first, second]);
                while (compressionQueue.hasPending()) {
                    await new Promise(resolve => setTimeout(resolve, 10));
                }
                await new Promise(resolve => setTimeout(resolve, 0));
                return {
                    submitMessage,
                    fetchCalled: window.__earlyUploadFetch,
                    uploadCount: uploads.length,
                    allReady: uploads.every(entry => entry.status === 'ready'),
                    selectionPending: validationInFlight,
                };
            }
            """
        )

        self.assertIn("等待图片处理完成", result["submitMessage"])
        self.assertFalse(result["fetchCalled"])
        self.assertEqual(result["uploadCount"], 12)
        self.assertTrue(result["allReady"])
        self.assertEqual(result["selectionPending"], 0)

    def test_report_list_image_preview_stays_open_when_original_is_clicked(self):
        upload = ReportUpload.objects.create(patient=self.patient)
        ReportImage.objects.create(
            upload=upload,
            image_url="/static/review_upload_tip.webp",
            report_date=date(2026, 7, 17),
        )
        self.page.set_viewport_size({"width": 320, "height": 700})
        self._open("web_patient:report_list")

        self.page.get_by_role("button", name="打开报告原图预览").click()
        modal = self.page.locator("#image-modal")
        expect(modal).to_be_visible()

        modal_image = self.page.locator("#modal-image")
        expect(modal_image).to_be_visible()
        modal_image.click()
        expect(modal).to_be_visible()
        self.assertEqual(
            modal_image.evaluate("element => getComputedStyle(element).filter"),
            "none",
        )

        self.page.get_by_role("button", name="关闭报告原图预览").click()
        expect(modal).to_be_hidden()

    def test_binding_onboarding_entry_document_and_chat_pages_load(self):
        SystemDocument.objects.create(
            key="User_Policy",
            title="用户协议",
            content="# 用户协议\n\n测试条款",
            is_active=True,
        )
        other_patient = PatientProfile.objects.create(
            name="Bind Target",
            phone="13900003000",
            doctor=self.doctor,
        )

        self._open("web_patient:bind_landing", other_patient.id)
        expect(self.page.locator("body")).to_contain_text("开启服务")
        expect(self.page.locator("body")).to_contain_text("我是家属/监护人")
        expect(self.page.locator("body")).to_contain_text("提交申请")

        self._open("web_patient:bind_landing", self.patient.id)
        expect(self.page.locator("body")).to_contain_text("绑定成功")
        expect(self.page.locator("body")).to_contain_text("Browser Patient")

        self._open("web_patient:onboarding")
        expect(self.page.locator("body")).to_contain_text("管理计划")

        self._open("web_patient:entry")
        expect(self.page.locator("body")).to_contain_text("管理计划")

        self._open("web_patient:document_detail", "User_Policy")
        expect(self.page.locator("body")).to_contain_text("用户协议")
        expect(self.page.locator("body")).to_contain_text("测试条款")

        self._open("web_patient:consultation_chat")
        expect(self.page.locator("body")).to_contain_text("Browser Studio")
        expect(self.page.locator('textarea[placeholder="请输入咨询内容..."]')).to_be_visible()

    def test_questionnaire_submission_detail_page_loads_answers(self):
        submission = self._create_questionnaire_submission()
        next_url = reverse("web_patient:health_records")

        self._open(
            "web_patient:questionnaire_submission_detail",
            submission.id,
            params={"next": next_url},
        )

        expect(self.page.locator("body")).to_contain_text("焦虑评估")
        expect(self.page.locator("body")).to_contain_text("最近是否感到紧张？")
        expect(self.page.locator("body")).to_contain_text("经常")
