from django.test import TestCase
from django.urls import reverse
from django.conf import settings
from django.contrib.auth import get_user_model
from users.choices import UserType


class OnboardingViewTests(TestCase):
  """患者端 Onboarding 引导页视图测试"""

  def test_onboarding_anonymous_redirects_to_login(self):
    """未登录用户访问应重定向至登录页"""
    url = reverse("web_patient:onboarding")
    response = self.client.get(url)
    self.assertEqual(response.status_code, 302)
    self.assertIn("/login/", response.url)

  def test_onboarding_patient_renders_copy_and_layout(self):
    """患者登录访问：验证文案与布局（删除项不出现）"""
    User = get_user_model()
    user = User.objects.create_user(
      username="patient_user",
      password="secure-pass-123",
      user_type=UserType.PATIENT,
      wx_openid="openid_test_user",
    )
    self.client.force_login(user)

    url = reverse("web_patient:onboarding")
    response = self.client.get(url)
    self.assertEqual(response.status_code, 200)
    self.assertTemplateUsed(response, "web_patient/onboarding.html")

    # 文案断言：标题、副标题、说明、按钮文案
    self.assertContains(response, "温馨提示")
    self.assertContains(response, "完善资料，开启守护旅程")
    self.assertContains(response, "为了完整体验服务，请先填写患者档案。我们将提供专业的康复咨询服务。")
    self.assertContains(response, "填写患者资料")

    # 按钮链接断言：跳转至 entry
    entry_url = reverse("web_patient:entry")
    self.assertContains(response, entry_url)

    # 布局删除断言：不再出现两列网格布局类
    self.assertNotContains(response, "grid-cols-2")

    # 会话失效提示在已登录用户下不应出现
    self.assertNotContains(response, "当前会话已失效")
