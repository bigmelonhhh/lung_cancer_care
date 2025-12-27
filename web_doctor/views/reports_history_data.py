import random
from typing import List, Dict, Any

def get_mock_reports_data() -> List[Dict[str, Any]]:
    """
    获取检查报告历史记录模拟数据
    
    返回数据结构：
    [
        {
            "id": int,                 # 报告ID
            "date": str,               # 上传时间 (YYYY-MM-DD HH:MM)
            "images": List[str],       # 图片URL列表
            "interpretation": str,     # 报告解读内容
            "is_pushed": bool,         # 是否已推送给患者
            "patient_info": {          # 患者简要信息（模拟关联）
                "name": str,
                "age": int
            },
            "report_type": str,        # 检查类型（如：CT、MRI、血常规）
            "status": str              # 报告状态（已完成、待审核等）
        },
        ...
    ]
    """
    history_list = []
    
    report_types = ["CT胸部平扫", "MRI头部扫描", "血常规", "肝功能", "肿瘤标志物"]
    statuses = ["已完成", "待审核", "已打印"]
    
    for i in range(15):
        # 随机生成图片数量 (1-6张)
        img_count = random.randint(1, 6)
        # 生成占位图片URL
        images = [f"https://placehold.co/200x200?text=Report+{i}-{j}" for j in range(img_count)]
        
        # 模拟报告解读内容
        # 每3个报告有一个没有解读内容
        interpretation = (
            f"这是关于报告 {i} 的解读内容。患者情况稳定，建议继续观察。影像学表现符合术后改变。" 
            if i % 3 != 0 else ""
        )
        
        # 模拟推送状态
        is_pushed = i % 2 == 0
        
        # 模拟日期（倒序排列）
        # 简单起见，这里直接使用固定的模拟日期逻辑，实际项目中可能使用 datetime 生成
        date_str = f"2025-11-{12-i if 12-i > 0 else 1:02d} 14:22"

        history_list.append({
            "id": 1000 + i,
            "date": date_str,
            "images": images,
            "interpretation": interpretation,
            "is_pushed": is_pushed,
            "patient_info": {
                "name": "模拟患者",
                "age": random.randint(45, 75)
            },
            "report_type": random.choice(report_types),
            "status": random.choice(statuses)
        })
        
    return history_list
