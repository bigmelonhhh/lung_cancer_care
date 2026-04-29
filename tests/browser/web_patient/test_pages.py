from datetime import datetime
from decimal import Decimal
from urllib.parse import urlencode

from django.test import tag
from django.urls import reverse
from django.utils import timezone

from business_support.models import SystemDocument
from core.models import (
    CheckupLibrary,
    DailyTask,
    Questionnaire,
    QuestionnaireCode,
    QuestionnaireOption,
    QuestionnaireQuestion,
    choices as core_choices,
)
from core.models.choices import CheckupCategory, PlanItemCategory, ReportType, TaskStatus
from health_data.models import HealthMetric, MetricType, QuestionnaireAnswer, QuestionnaireSubmission
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

        self._open("web_patient:health_records")
        expect(self.page.locator("body")).to_contain_text("健康档案")
        expect(self.page.locator("body")).to_contain_text("复查档案")
        expect(self.page.locator("body")).to_contain_text("随访问卷")

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
        expect(self.page.locator("body")).to_contain_text("完善资料，开启守护旅程")

        self._open("web_patient:entry")
        expect(self.page.locator("body")).to_contain_text("完善康复档案")
        expect(self.page.locator("body")).to_contain_text("确认提交档案")

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
