from django.test import TestCase
from django.contrib.auth import get_user_model
from users.models import PatientProfile
from ..models import MedicalHistory
from ..services.medical_history_service import MedicalHistoryService

User = get_user_model()

class MedicalHistoryServiceTest(TestCase):
    def setUp(self):
        # 准备测试数据
        # 1. 创建一个医生用户（记录人）
        self.doctor = User.objects.create_user(username='doctor_who', password='password', wx_openid="mock_doc_openid")
        
        # 2. 创建一个患者用户和对应的 Profile
        self.patient_user = User.objects.create_user(username='patient_01', password='password', wx_openid="mock_patient_openid")
        # 假设 PatientProfile 必须关联一个 user，根据你的实际模型调整
        self.patient = PatientProfile.objects.create(user=self.patient_user, name="张三")

    def test_add_medical_history(self):
        """测试新增病史记录功能"""
        data = {
            "tumor_diagnosis": "I期肺腺癌(骨、脑转移)",
            "risk_factors": "癌症家族史，吸烟",
            "clinical_diagnosis": "右肺上叶后段恶性肿瘤",
            "genetic_test": "EGFR 19外显子缺失",
            "past_medical_history": "高血压5年",
            "surgical_information": "肺穿刺活检术"
        }
        
        history = MedicalHistoryService.add_medical_history(self.doctor, self.patient, data)
        
        # 验证数据库中是否创建成功
        self.assertEqual(MedicalHistory.objects.count(), 1)
        
        # 验证字段内容
        self.assertEqual(history.tumor_diagnosis, data["tumor_diagnosis"])
        self.assertEqual(history.risk_factors, data["risk_factors"])
        
        # 验证记录人和患者关联
        self.assertEqual(history.created_by, self.doctor)
        self.assertEqual(history.patient, self.patient)

    def test_get_medical_history_list_pagination(self):
        """测试获取历史记录的分页功能"""
        # 模拟插入 15 条记录
        for i in range(15):
            data = {
                "tumor_diagnosis": f"第 {i} 次诊断记录",
                "risk_factors": "无"
            }
            MedicalHistoryService.add_medical_history(self.doctor, self.patient, data)
            
        # 查询第 1 页，每页 10 条
        page1 = MedicalHistoryService.get_medical_history_list(self.patient, page=1, page_size=10)
        self.assertEqual(len(page1.object_list), 10)
        self.assertTrue(page1.has_next())
        # 验证排序：最新的记录（第14次）应该在第一个
        self.assertEqual(page1.object_list[0].tumor_diagnosis, "第 14 次诊断记录")
        
        # 查询第 2 页
        page2 = MedicalHistoryService.get_medical_history_list(self.patient, page=2, page_size=10)
        self.assertEqual(len(page2.object_list), 5)
        self.assertFalse(page2.has_next())
        # 验证第2页的数据
        self.assertEqual(page2.object_list[0].tumor_diagnosis, "第 4 次诊断记录")
