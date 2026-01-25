
from django.test import TestCase, Client
from django.urls import reverse
from users.models import CustomUser, DoctorProfile, SalesProfile
from users import choices
from users.services.auth import AuthService

class MobileAuthTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.login_url = reverse("web_doctor:login")
        self.mobile_home_url = reverse("web_doctor:mobile_home")
        self.doctor_workspace_url = reverse("web_doctor:doctor_workspace")
        
        # Create a doctor user
        self.password = "password123"
        self.doctor = CustomUser.objects.create_user(
            username="doctor_test",
            phone="13800000001",
            password=self.password,
            user_type=choices.UserType.DOCTOR,
            wx_nickname="梅周芳"
        )
        DoctorProfile.objects.create(
            user=self.doctor,
            name="梅周芳",
            title="主任医师",
            hospital="上海第五人民医院",
            department="呼吸与重症科"
        )
        
        # Create a sales user
        self.sales = CustomUser.objects.create_user(
            username="sales_test",
            phone="13800000002",
            password=self.password,
            user_type=choices.UserType.SALES
        )
        SalesProfile.objects.create(
            user=self.sales,
            name="销售A"
        )

    def test_login_page_renders(self):
        """测试登录页面能否正常渲染"""
        response = self.client.get(self.login_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "login.html")

    def test_pc_login_redirects_to_workspace(self):
        """测试PC端医生登录跳转到工作台"""
        response = self.client.post(
            self.login_url,
            {"phone": self.doctor.phone, "password": self.password},
            HTTP_USER_AGENT="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )
        self.assertRedirects(response, self.doctor_workspace_url)

    def test_mobile_login_redirects_to_mobile_home(self):
        """测试移动端医生登录跳转到移动端首页"""
        response = self.client.post(
            self.login_url,
            {"phone": self.doctor.phone, "password": self.password},
            HTTP_USER_AGENT="Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1"
        )
        self.assertRedirects(response, self.mobile_home_url)

    def test_mobile_login_android_redirects_to_mobile_home(self):
        """测试Android设备医生登录跳转到移动端首页"""
        response = self.client.post(
            self.login_url,
            {"phone": self.doctor.phone, "password": self.password},
            HTTP_USER_AGENT="Mozilla/5.0 (Linux; Android 10; SM-G975F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/83.0.4103.106 Mobile Safari/537.36"
        )
        self.assertRedirects(response, self.mobile_home_url)

    def test_sales_login_redirects_to_dashboard_regardless_of_device(self):
        """测试销售登录始终跳转到销售看板，不受设备影响"""
        # PC
        response = self.client.post(
            self.login_url,
            {"phone": self.sales.phone, "password": self.password},
            HTTP_USER_AGENT="Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        )
        self.assertRedirects(response, reverse("web_sales:sales_dashboard"))
        
        self.client.logout()
        
        # Mobile
        response = self.client.post(
            self.login_url,
            {"phone": self.sales.phone, "password": self.password},
            HTTP_USER_AGENT="Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X)"
        )
        self.assertRedirects(response, reverse("web_sales:sales_dashboard"))

    def test_mobile_home_view_renders_correctly(self):
        """测试移动端首页视图渲染及数据包含"""
        self.client.force_login(self.doctor)
        response = self.client.get(self.mobile_home_url)
        
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "web_doctor/mobile/index.html")
        
        # 验证模拟数据
        self.assertContains(response, "梅周芳")
        self.assertContains(response, "主任医师")
        self.assertContains(response, "管理患者")
        self.assertContains(response, "120") # managed_patients
