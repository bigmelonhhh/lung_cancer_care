from django.shortcuts import render
from django.urls import reverse

def patient_home(request):
    """
    【页面说明】患者端首页 (H5)
    【功能逻辑】
    1. 此页面不需要强制登录校验，支持游客访问。
    2. 如果用户未登录，顶部会显示"注册"和"我是患者家属"按钮。
    3. 点击"注册"按钮，跳转到 onboarding 页面 (web_patient:onboarding)，进行患者身份绑定流程。
    """
    
    # 获取 onboarding 页面的 URL，用于未登录时的跳转
    onboarding_url = reverse("web_patient:onboarding")
    
    context = {
        "service_days": 35,
        "is_member": True, # For "Member open" text
        "is_authenticated": False, # 模拟未登录状态，控制顶部Header显示
        "onboarding_url": onboarding_url, # 注册按钮跳转链接
        "daily_plans": [
            {
                "type": "medication",
                "title": "用药提醒",
                "subtitle": "您今天还未服药",
                "status": "pending",
                "action_text": "去服药",
                "icon_class": "bg-blue-100 text-blue-600", 
            },
            {
                "type": "temperature",
                "title": "测量体温",
                "subtitle": "请记录今日体温",
                "status": "pending",
                "action_text": "去填写",
                 "icon_class": "bg-blue-100 text-blue-600",
            },
             {
                "type": "bp_hr",
                "title": "血压心率",
                "subtitle": "请记录今日血压心率情况",
                "status": "pending",
                "action_text": "去填写",
                 "icon_class": "bg-blue-100 text-blue-600",
            },
            {
                "type": "spo2",
                "title": "血氧饱和度",
                "subtitle": "请记录今日血氧饱和度",
                "status": "pending",
                "action_text": "去填写",
                 "icon_class": "bg-blue-100 text-blue-600",
            },
             {
                "type": "weight",
                "title": "体重记录",
                "subtitle": "请记录今日体重",
                "status": "pending",
                "action_text": "去填写",
                 "icon_class": "bg-blue-100 text-blue-600",
            },
            {
                "type": "followup",
                "title": "第1次随访",
                "subtitle": "请及时完成您的第1次随访",
                "status": "pending",
                "action_text": "去完成",
                 "icon_class": "bg-blue-100 text-blue-600",
            },
             {
                "type": "checkup",
                "title": "第1次复查",
                "subtitle": "请及时完成您的第1次复查",
                "status": "pending",
                "action_text": "去完成",
                 "icon_class": "bg-blue-100 text-blue-600",
            },
        ]
    }
    return render(request, "web_patient/patient_home.html", context)
