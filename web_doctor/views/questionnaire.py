from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from users.models import PatientProfile
from core.models import TreatmentCycle
from datetime import date, timedelta
import random

@login_required
def questionnaire_detail(request, patient_id):
    patient = get_object_or_404(PatientProfile, id=patient_id)
    
    # 获取选中的日期，默认为今天
    selected_date_str = request.GET.get('date')
    selected_date = date.today()
    if selected_date_str:
        try:
            selected_date = date.fromisoformat(selected_date_str)
        except ValueError:
            pass

    # 随访问卷详情页面列表接口 模拟左侧历史记录数据 (疗程 -> 日期列表)
    # 假设有三个疗程
    history = [
        {
            "name": "第三疗程（当前疗程）",
            "is_current": True,
            "dates": [
                date.today(),
                date.today() - timedelta(days=13),
                date.today() - timedelta(days=26),
            ]
        },
        {
            "name": "第二疗程",
            "is_current": False,
            "dates": [
                date.today() - timedelta(days=40),
                date.today() - timedelta(days=46),
                date.today() - timedelta(days=59),
            ]
        },
         {
            "name": "第一疗程",
            "is_current": False,
            "dates": [
                date.today() - timedelta(days=80),
                date.today() - timedelta(days=86),
                date.today() - timedelta(days=102),
            ]
        }
    ]
    
    # 检查当前选中的日期是否存在于历史记录中，如果不在（比如默认是今天但今天没数据），
    # 则强制选中最近的一天
    # 简单起见，这里假设上面 history[0]['dates'][0] 就是今天或者最近的一天
    
    # 模拟六大模块的详细对比数据
    # 如果该日期有数据，生成 mock data；否则为空
    # TODO 根据左侧菜单选择的某个疗程下的日期-查询六大模块的基本信息+表格数据展示
    has_data = True # 简化逻辑，假设选中的日期都有数据
    
    # 定义问题对比数据结构
    def mock_comparison(prev_date, current_score, prev_score, questions):
        change_text = "持平"
        change_type = "neutral" # up, down, neutral
        if current_score > prev_score:
            change_text = f"较上次提升{current_score - prev_score}分"
            change_type = "up" # bad for symptoms
        elif current_score < prev_score:
            change_text = f"较上次下降{prev_score - current_score}分"
            change_type = "down" # good for symptoms
            
        return {
            "current_score": current_score,
            "prev_score": prev_score,
            "change_text": change_text,
            "change_type": change_type,
            "ai_summary": f"AI洞察：患者整体评分略有{'下降' if change_type=='down' else '上升'}。关键风险点在于**疼痛/不舒服**维度出现显著恶化**，从上次访视的“中度”转变为本次的“极度疼痛”，建议临床团队立即关注并评估原因。其他维度（行动、焦虑等）基本持平。",
            "prev_date": prev_date,
            "questions": questions
        }

    # 1. 体能与呼吸
    physical_data = mock_comparison(
        prev_date=selected_date - timedelta(days=7),
        current_score=9,
        prev_score=8,
        questions=[
            {
                "text": "您近期日常活动能力如何？",
                "current_answer": "有轻微症状（如咳嗽、轻微疼痛），不能做剧烈运动，但可以进行轻体力工作（如简单的家务、办公室工作）。",
                "prev_answer": "完全正常，没有任何症状，和生病前一样能进行各种活动（包括跑步、提重物等）。",
                "change": "下降1分",
                "change_type": "bad"
            },
             {
                "text": "您在活动时感到气短/呼吸困难的程度？",
                "current_answer": "我在平地快走或上小斜坡时会感到气喘。",
                "prev_answer": "我在平地走约 100 米，或才几分钟，就不得不停下来喘口气。",
                "change": "下降1分",
                "change_type": "bad"
            }
        ]
    )
    
    # 2. 咳嗽与痰色
    cough_data = mock_comparison(
        prev_date=selected_date - timedelta(days=7),
        current_score=9,
        prev_score=8,
        questions=[
            {
                "text": "最近的咳嗽情况如何？",
                "current_answer": "偶尔有点轻微咳嗽，但不影响说话和吃饭，也不用吃药。",
                "prev_answer": "严重影响睡眠，甚至吃饭、穿衣服都受影响，感觉很痛苦。",
                "change": "提升1分",
                "change_type": "good"
            },
            {
                "text": "最近痰液性状情况如何？",
                "current_answer": "像唾沫或蛋清一样，不浑浊。",
                "prev_answer": "像脓一样的深黄色或绿色，很粘稠，甚至是一坨一坨的。",
                "change": "下降1分",
                "change_type": "bad"
            },
             {
                "text": "痰中是否带血？",
                "current_answer": "痰里夹杂几条红血丝，或者痰带点粉红色。",
                "prev_answer": "痰里夹杂几条红血丝，或者痰带点粉红色。",
                "change": "持平",
                "change_type": "neutral"
            },
             {
                "text": "发生以上情况时体温情况如何？",
                "current_answer": "有点低烧（37.3℃ - 38.0℃）。",
                "prev_answer": "发高烧（38.0℃以上，或者感觉身体发冷打寒战）。",
                "change": "无分项",
                "change_type": "neutral"
            },
             {
                "text": "发生以上情况时血氧情况如何？",
                "current_answer": "略低，90-94之间。",
                "prev_answer": "未测量，不清楚。",
                "change": "无分项",
                "change_type": "neutral"
            }
        ]
    )

    # 3. 食欲
    appetite_data = mock_comparison(
        prev_date=selected_date - timedelta(days=7),
        current_score=4,
        prev_score=5,
        questions=[
            {
                "text": "最近的食欲如何？",
                "current_answer": "食欲稍微差一点，比平时吃得少，或者吃的时候觉得没那么香。",
                "prev_answer": "完全不想吃东西，或者吃一点就觉得恶心想吐。",
                "change": "提升1分",
                "change_type": "good"
            }
        ]
    )

    # 4. 疼痛
    pain_data = mock_comparison(
        prev_date=selected_date - timedelta(days=7),
        current_score=3,
        prev_score=0,
        questions=[
            {
                "text": "您感到疼痛的程度？",
                "current_answer": "轻微疼痛，可以忍受，不用吃止痛药也能正常生活。",
                "prev_answer": "一点也不痛。",
                "change": "恶化3分",
                "change_type": "bad"
            }
        ]
    )
    
    # 5. 睡眠
    sleep_data = mock_comparison(
        prev_date=selected_date - timedelta(days=7),
        current_score=2,
        prev_score=2,
        questions=[
             {
                "text": "您最近的睡眠质量如何？",
                "current_answer": "睡得还可以，偶尔会醒，但能很快睡着。",
                "prev_answer": "睡得还可以，偶尔会醒，但能很快睡着。",
                "change": "持平",
                "change_type": "neutral"
            }
        ]
    )
    
    # 6. 心理
    psych_data = mock_comparison(
        prev_date=selected_date - timedelta(days=7),
        current_score=1,
        prev_score=4,
        questions=[
             {
                "text": "您最近的心情/心理状态如何？",
                "current_answer": "偶尔觉得有点烦或者担心，但跟家里人聊聊天就好了。",
                "prev_answer": "经常觉得很害怕、很紧张，或者心情非常低落，不想理人。",
                "change": "改善3分",
                "change_type": "good"
            }
        ]
    )

    context = {
        "patient": patient,
        "selected_date": selected_date,
        "history": history,
        "data": {
            "physical": physical_data,
            "cough": cough_data,
            "appetite": appetite_data,
            "pain": pain_data,
            "sleep": sleep_data,
            "psych": psych_data,
        }
    }
    
    return render(request, "web_doctor/partials/indicators/questionnaire_detail.html", context)
