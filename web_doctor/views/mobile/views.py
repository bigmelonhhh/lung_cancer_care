
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from users import choices

@login_required
def mobile_home(request):
    """
    移动端医生首页
    """
    # 模拟数据
    doctor_info = {
        "name": request.user.wx_nickname or "梅周芳",
        "title": "主任医师",
        "department": "呼吸与重症科",
        "hospital": "上海第五人民医院",
        "avatar_url": None, # 模板中使用默认或首字母
    }
    
    stats = {
        "managed_patients": 120,
        "today_active": 25,
        "alerts_count": 3,
        "consultations_count": 5
    }
    
    alerts = [
        {"id": 1, "patient_name": "张鹏", "type": "体征异常", "time": "2026年1月18日 10:00"},
        # 更多数据可在此添加
    ]
    
    consultations = [
        {"id": 1, "patient_name": "张鹏", "content": "已经连续3天发烧......", "time": "2026年1月20日 10:00"},
        # 更多数据可在此添加
    ]
    
    context = {
        "doctor": doctor_info,
        "stats": stats,
        "alerts": alerts,
        "consultations": consultations,
    }
    
    return render(request, "web_doctor/mobile/index.html", context)
