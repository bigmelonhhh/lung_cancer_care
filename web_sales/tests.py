from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from users import choices
from users.models import CustomUser, DoctorProfile, PatientProfile, SalesProfile


class SalesBackButtonTemplateTests(TestCase):
    """销售端详情卡片返回按钮相关测试。"""

    def setUp(self):
        self.sales_user = CustomUser.objects.create_user(
            user_type=choices.UserType.SALES,
            phone="13800000001",
        )
        self.sales_profile = SalesProfile.objects.create(
            user=self.sales_user,
            name="销售A",
        )

        self.doctor_user = CustomUser.objects.create_user(
            user_type=choices.UserType.DOCTOR,
            phone="13800000002",
        )
        self.doctor_profile = DoctorProfile.objects.create(
            user=self.doctor_user,
            name="张医生",
            hospital="市一医院",
            department="肿瘤科",
            title="主任医师",
        )
        self.doctor_profile.sales.add(self.sales_profile)

        self.patient_profile = PatientProfile.objects.create(
            phone="13800000003",
            name="王患者",
            gender=choices.Gender.FEMALE,
            sales=self.sales_profile,
            doctor=self.doctor_profile,
            qrcode_url="https://example.com/qrcode.png",
            qrcode_expire_at=timezone.now() + timedelta(days=1),
        )

    def test_patient_detail_contains_back_button(self):
        """测试患者详情局部模板包含返回按钮与快捷键配置。"""

        self.client.force_login(self.sales_user)
        response = self.client.get(
            reverse("web_sales:patient_detail", args=[self.patient_profile.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "web_sales/partials/detail_card.html")
        self.assertContains(response, 'onclick="webSalesGoBackToDashboard()"')
        self.assertContains(response, 'aria-keyshortcuts="Esc"')
        self.assertContains(response, "event.key !== 'Escape'")
        self.assertContains(response, reverse("web_sales:sales_dashboard"))

    def test_doctor_detail_contains_back_button(self):
        """测试医生详情局部模板包含返回按钮与快捷键配置。"""

        self.client.force_login(self.sales_user)
        response = self.client.get(
            reverse("web_sales:doctor_detail", args=[self.doctor_profile.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "web_sales/partials/doctor_detail_card.html")
        self.assertContains(response, 'onclick="webSalesGoBackToDashboard()"')
        self.assertContains(response, 'aria-keyshortcuts="Esc"')
        self.assertContains(response, "event.key !== 'Escape'")
        self.assertContains(response, reverse("web_sales:sales_dashboard"))

    def test_sales_dashboard_returns_partial_for_htmx_request(self):
        """测试dashboard在HTMX请求下返回首页主内容局部模板。"""

        self.client.force_login(self.sales_user)
        response = self.client.get(
            reverse("web_sales:sales_dashboard"),
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "web_sales/partials/dashboard_home.html")
        self.assertContains(response, "管理医生总数")


class SalesMobileAdaptationTemplateTests(TestCase):
    """销售端移动端适配模板与资源加载相关测试。"""

    def setUp(self):
        self.sales_user = CustomUser.objects.create_user(
            user_type=choices.UserType.SALES,
            phone="13800000011",
        )
        self.sales_profile = SalesProfile.objects.create(
            user=self.sales_user,
            name="销售B",
        )

    def test_sales_dashboard_contains_mobile_assets(self):
        """测试dashboard页面包含移动端专用 CSS/JS 引用点。"""

        self.client.force_login(self.sales_user)
        response = self.client.get(reverse("web_sales:sales_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "web_sales/dashboard.html")
        self.assertContains(response, "web_sales/web_sales_mobile.css")
        self.assertContains(response, "web_sales/web_sales_mobile.js")
        self.assertContains(response, "ws_is_mobile")

    def test_sales_dashboard_renders_mobile_template_by_cookie(self):
        """测试dashboard在 ws_is_mobile cookie 下渲染移动端模板。"""

        self.client.force_login(self.sales_user)
        self.client.cookies["ws_is_mobile"] = "1"
        response = self.client.get(reverse("web_sales:sales_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "web_sales/dashboard.mobile.html")
        self.assertContains(response, "data-ws-sidebar")

    def test_sales_dashboard_htmx_request_ignores_mobile_cookie(self):
        """测试dashboard在HTMX请求下仍返回局部模板，不受移动端cookie影响。"""

        self.client.force_login(self.sales_user)
        self.client.cookies["ws_is_mobile"] = "1"
        response = self.client.get(
            reverse("web_sales:sales_dashboard"),
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "web_sales/partials/dashboard_home.html")

    def test_sales_change_password_contains_mobile_css(self):
        """测试修改密码页包含移动端专用 CSS 引入。"""

        self.client.force_login(self.sales_user)
        response = self.client.get(reverse("web_sales:sales_change_password"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "web_sales/change_password.html")
        self.assertContains(response, "web_sales/web_sales_mobile.css")
