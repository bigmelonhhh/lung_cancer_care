from django.shortcuts import render
from django.http import HttpRequest, HttpResponse
from users.decorators import auto_wechat_login, check_patient

@auto_wechat_login
@check_patient
def daily_survey(request: HttpRequest) -> HttpResponse:
    """
    【页面说明】今日随访问卷 `/p/followup/daily/`
    """
    if request.method == "POST":
        # Handle form submission here
        pass

    # Step 1: Sleep Quality Survey
    sleep_survey_data = {
        "title": "睡眠质量评分",
        "questions": [
            {
                "id": "sleep_quality",
                "text": "1. 您最近的睡眠质量是…",
                "type": "radio_card",
                "options": [
                    {"value": "非常差", "label": "非常差"},
                    {"value": "差", "label": "差"},
                    {"value": "一般", "label": "一般"},
                    {"value": "好", "label": "好"},
                    {"value": "非常好", "label": "非常好"},
                ]
            },
            {
                "id": "sleep_trouble_drowsy",
                "text": "2. 困倦入睡困难",
                "type": "radio_list",
                "options": ["完全没有", "一点点", "有些", "相当多", "非常"]
            },
            {
                "id": "sleep_trouble_waking",
                "text": "3. 有醒来问题",
                "type": "radio_list",
                "options": ["完全没有", "一点点", "有些", "相当多", "非常"]
            },
            {
                "id": "sleep_hard_to_fall",
                "text": "4. 难以入睡",
                "type": "radio_list",
                "options": ["完全没有", "一点点", "有些", "相当多", "非常"]
            },
            {
                "id": "sleep_cant_fall_effort",
                "text": "5. 努力无法入睡",
                "type": "radio_list",
                "options": ["完全没有", "一点点", "有些", "相当多", "非常"]
            },
            {
                "id": "sleep_awake_all_night",
                "text": "6. 彻夜无法入睡",
                "type": "radio_list",
                "options": ["完全没有", "一点点", "有些", "相当多", "非常"]
            },
             {
                "id": "sleep_satisfaction",
                "text": "7. 对睡眠质量满意度",
                "type": "radio_list",
                "options": ["完全没有", "一点点", "有些", "相当多", "非常"]
            },
        ],
        "common_options_helper": "以下问题请回答频率：完全没有 / 一点点 / 有些 / 相当多 / 非常"
    }

    # Step 2: Pain Survey
    pain_survey_data = {
        "title": "近期疼痛情况",
        "helper_text": {
            "title": "请根据以下标准选择：",
            "items": [
                "无疼痛",
                "轻度：能做家务/正常活动，睡眠基本不受影响",
                "中度：活动或睡眠受影响，需要（或增加）止痛药",
                "重度：明显受限或无法入睡，需立即处理/尽快就医"
            ]
        },
        "questions": [
            {
                "id": "pain_chest",
                "text": "1. 近期术口/胸腔/肋间部位有无疼痛？",
                "options": [
                    {"value": "无疼痛", "label": "无疼痛"},
                    {"value": "轻度", "label": "轻度：能做家务/正常活动，睡眠基本不受影响"},
                    {"value": "中度", "label": "中度：活动或睡眠受影响，需要（或增加）止痛药"},
                    {"value": "重度", "label": "重度：明显受限或无法入睡，需立即处理/尽快就医"},
                ]
            },
            {
                "id": "pain_shoulder",
                "text": "2. 近期肩峰/肩背/肩胛部位有无疼痛？",
                "options": [
                    {"value": "无疼痛", "label": "无疼痛"},
                    {"value": "轻度", "label": "轻度：能做家务/正常活动，睡眠基本不受影响"},
                    {"value": "中度", "label": "中度：活动或睡眠受影响，需要（或增加）止痛药"},
                    {"value": "重度", "label": "重度：明显受限或无法入睡，需立即处理/尽快就医"},
                ]
            },
            {
                "id": "pain_limbs",
                "text": "3. 近期肋骨/脊柱/骨盆/四肢部位有无疼痛？",
                "options": [
                    {"value": "无疼痛", "label": "无疼痛"},
                    {"value": "轻度", "label": "轻度：能做家务/正常活动，睡眠基本不受影响"},
                    {"value": "中度", "label": "中度：活动或睡眠受影响，需要（或增加）止痛药"},
                    {"value": "重度", "label": "重度：明显受限或无法入睡，需立即处理/尽快就医"},
                ]
            },
            {
                "id": "pain_head",
                "text": "4. 近期头部有无疼痛？",
                "options": [
                    {"value": "无疼痛", "label": "无疼痛"},
                    {"value": "轻度", "label": "轻度：能做家务/正常活动，睡眠基本不受影响"},
                    {"value": "中度", "label": "中度：活动或睡眠受影响，需要（或增加）止痛药"},
                    {"value": "重度", "label": "重度：明显受限或无法入睡，需立即处理/尽快就医"},
                ]
            }
        ]
    }

    # Step 3: Cough Survey
    cough_survey_data = {
        "title": "咳嗽与痰色",
        "questions": [
            {
                "id": "cough_status",
                "text": "1. 最近的咳嗽情况如何？",
                "type": "radio",
                "options": [
                    {"value": "无咳嗽", "label": "近期无咳嗽情况。"},
                    {"value": "轻微咳嗽", "label": "偶尔有点轻微咳嗽，但不影响说话和吃饭，也不用吃药。"},
                    {"value": "频繁咳嗽", "label": "需要吃止咳药才能正常生活，或者咳嗽时较为频繁，做事受限。"},
                    {"value": "严重咳嗽", "label": "严重影响睡眠，甚至吃饭、穿衣都受到影响，感觉很痛苦。"},
                ]
            },
            {
                "id": "sputum_status",
                "text": "2. 最近痰液性状如何？",
                "type": "radio",
                "options": [
                    {"value": "无痰", "label": "无痰，或只是干咳。"},
                    {"value": "清痰", "label": "像唾沫或清痰一样，不浑浊。"},
                    {"value": "黄痰", "label": "痰有点黄，颜色略深，但不算很浓稠。"},
                    {"value": "深黄绿痰", "label": "痰呈深黄色/绿色等（颜色较深）。"},
                ]
            },
            {
                "id": "sputum_blood",
                "text": "3. 痰中是否带血？",
                "type": "radio",
                "options": [
                    {"value": "无血", "label": "完全没有，痰很干净。"},
                    {"value": "血丝", "label": "痰里夹有几条红血丝，或者偶尔带点红色。"},
                    {"value": "明显血", "label": "咳出来的是明显的血，大概有一两口那么多。"},
                    {"value": "大量血", "label": "血量很多，止不住。"},
                ]
            },
            {
                "id": "cough_temperature",
                "text": "4. 发生以上情况时体温情况如何？",
                "type": "radio",
                "options": [
                    {"value": "正常", "label": "正常，37℃左右。"},
                    {"value": "低热", "label": "有点低热（37.3℃~38.0℃）。"},
                    {"value": "高热", "label": "发高热（38.0℃以上，或者感觉发冷发热打寒战）。"},
                    {"value": "不清楚", "label": "未测量，不清楚。"},
                ]
            },
            {
                "id": "cough_spo2",
                "text": "5. 发生以上情况时血氧饱和度如何？",
                "type": "radio",
                "options": [
                    {"value": "正常", "label": "正常，95以上。"},
                    {"value": "略低", "label": "略低，90~94之间。"},
                    {"value": "很低", "label": "很低，低于90。"},
                    {"value": "不清楚", "label": "未测量，不清楚。"},
                ]
            }
        ]
    }

    # Step 4: Appetite Survey
    appetite_survey_data = {
        "title": "您最近的食欲情况如何？",
        "questions": [
            {
                "id": "appetite_intake",
                "text": "1. 您现在的进食量大约是患病前的多少？",
                "type": "radio",
                "options": [
                    {"value": "差不多", "label": "与患病前差不多或更多。"},
                    {"value": "70-90%", "label": "约为患病前的 70%~90%。"},
                    {"value": "50-60%", "label": "约为患病前的 50%~60%。"},
                    {"value": "少于一半", "label": "少于患病前的一半，或不吃。"},
                ]
            },
            {
                "id": "appetite_weight_loss",
                "text": "2. 最近一个月内，您的体重是否有下降？",
                "type": "radio",
                "options": [
                    {"value": "无下降", "label": "无下降或体重增加。"},
                    {"value": "1-3kg", "label": "下降约 1~3 kg。"},
                    {"value": ">3kg", "label": "下降 > 3 kg。"},
                    {"value": "不清楚", "label": "不清楚，近期未监测体重。"},
                ]
            },
            {
                "id": "appetite_score",
                "text": "3. 请为您的食欲打分，0分表示“完全没有食欲/看见食物就恶心”，10分表示“食欲好/很想吃饭”",
                "type": "radio",
                "options": [
                    {"value": "8-10", "label": "8~10分。"},
                    {"value": "5-7", "label": "5~7分。"},
                    {"value": "3-4", "label": "3~4分。"},
                    {"value": "0-2", "label": "0~2分。"},
                ]
            },
            {
                "id": "appetite_symptoms",
                "text": "4. 是否存在以下影响进食的症状？（可多选）",
                "type": "checkbox",
                "options": [
                    {"value": "恶心呕吐", "label": "恶心/呕吐。"},
                    {"value": "吞咽困难", "label": "吞咽困难/吞咽痛。"},
                    {"value": "口腔溃疡", "label": "口腔溃疡/口干。"},
                    {"value": "味觉改变", "label": "味觉或嗅觉改变（觉得食物有苦味/金属味）。"},
                    {"value": "呼吸急促", "label": "呼吸急促/气喘（吃几口就喘）。"},
                    {"value": "便秘腹泻", "label": "便秘或腹泻。"},
                    {"value": "疼痛", "label": "疼痛（胸痛、全身痛等）。"},
                    {"value": "一吃就饱", "label": "一吃就饱。"},
                ]
            },
            {
                "id": "appetite_activity",
                "text": "5. 您最近活动能力如何？",
                "type": "radio",
                "options": [
                    {"value": "活动自如", "label": "活动自如，能进行日常散步等活动。"},
                    {"value": "容易疲劳", "label": "容易疲劳，多数时间需要卧床休息，但能下地。"},
                    {"value": "卧床", "label": "超过一半时间必须卧床。"},
                ]
            }
        ]
    }

    # Step 5: Emotion Survey
    emotion_grid_options = ["没有", "有时", "经常", "总是"]
    emotion_survey_data = {
        "title": "心理情绪问卷",
        "subtitle": "通过过去一周（过去7天），请根据实际情况作答",
        "grid_header": emotion_grid_options,
        "questions": [
              {
                "id": "fatigue_score",
                "text": "请您回想过去一周（包括今天），如果您心里的“痛苦/烦恼”程度可以用0-10分来表示，0分代表“没有痛苦”，10分代表“极度痛苦”，您会打几分？",
                "type": "select",
                "placeholder": "请选择您的分值",
                "options": [
                    {"value": "0", "label": "0 - 精力充沛"},
                    {"value": "1", "label": "1"},
                    {"value": "2", "label": "2"},
                    {"value": "3", "label": "3"},
                    {"value": "4", "label": "4"},
                    {"value": "5", "label": "5"},
                    {"value": "6", "label": "6"},
                    {"value": "7", "label": "7"},
                    {"value": "8", "label": "8"},
                    {"value": "9", "label": "9"},
                    {"value": "10", "label": "10 - 精疲力竭"},
                ]
            },
            # Grid questions
            {"id": "emotion_q1", "text": "1. 最近是否感到紧张、焦虑或担心？", "type": "radio_grid", "options": emotion_grid_options},
            {"id": "emotion_q2", "text": "2. 是否难以停止或控制担忧？", "type": "radio_grid", "options": emotion_grid_options},
            {"id": "emotion_q3", "text": "3. 是否对许多不同事情过分担忧？", "type": "radio_grid", "options": emotion_grid_options},
            {"id": "emotion_q4", "text": "4. 是否很难放松？", "type": "radio_grid", "options": emotion_grid_options},
            {"id": "emotion_q5", "text": "5. 是否感到坐立不安或容易激动？", "type": "radio_grid", "options": emotion_grid_options},
            {"id": "emotion_q6", "text": "6. 是否容易烦躁或易怒？", "type": "radio_grid", "options": emotion_grid_options},
            {"id": "emotion_q7", "text": "7. 是否担心会有不好的事情发生？", "type": "radio_grid", "options": emotion_grid_options},
            {"id": "emotion_q8", "text": "8. 对做事是否缺乏兴趣或乐趣？", "type": "radio_grid", "options": emotion_grid_options},
            {"id": "emotion_q9", "text": "9. 是否感到心情低落、抑郁或绝望？", "type": "radio_grid", "options": emotion_grid_options},
            {"id": "emotion_q10", "text": "10. 是否入睡困难、早醒或睡眠过多？", "type": "radio_grid", "options": emotion_grid_options},
            {"id": "emotion_q11", "text": "11. 是否感到疲倦或缺乏精力？", "type": "radio_grid", "options": emotion_grid_options},
            {"id": "emotion_q12", "text": "12. 食欲是否不振或饮食过量？", "type": "radio_grid", "options": emotion_grid_options},
            {"id": "emotion_q13", "text": "13. 是否觉得自己很糟糕、失败或让家人失望？", "type": "radio_grid", "options": emotion_grid_options},
            {"id": "emotion_q14", "text": "14. 是否注意力不集中，比如看电视或阅读困难？", "type": "radio_grid", "options": emotion_grid_options},
            {"id": "emotion_q15", "text": "15. 是否动作或说话变慢，或过度烦躁坐立不安？", "type": "radio_grid", "options": emotion_grid_options},
            {"id": "emotion_q16", "text": "16. 是否出现过自伤或轻生的念头？", "type": "radio_grid", "options": emotion_grid_options},
            # Non-grid questions
            {
                "id": "emotion_impact", 
                "text": "17. 以上问题对工作/学习/家庭生活的影响程度？", 
                "type": "radio", 
                "options": [
                    {"value": "没有影响", "label": "没有影响"},
                    {"value": "轻度影响", "label": "轻度影响"},
                    {"value": "中度影响", "label": "中度影响"},
                    {"value": "重度影响", "label": "重度影响"},
                ]
            },
            {
                "id": "emotion_stressors", 
                "text": "18. 影响情绪的生活事件（可多选）", 
                "type": "checkbox", 
                "options": [
                    {"value": "经济压力", "label": "经济压力"},
                    {"value": "家庭关系", "label": "家庭关系"},
                    {"value": "工作学习压力", "label": "工作/学习压力"},
                    {"value": "疾病相关担忧", "label": "疾病相关担忧"},
                    {"value": "睡眠问题", "label": "睡眠问题"},
                    {"value": "社交冲突", "label": "社交冲突"},
                    {"value": "其他", "label": "其他"},
                ]
            },
             {
                "id": "emotion_coping", 
                "text": "19. 已采取的应对方式（可多选）", 
                "type": "checkbox", 
                "options": [
                    {"value": "运动散步", "label": "运动/散步"},
                    {"value": "与亲友交流", "label": "与亲友交流"},
                    {"value": "专业咨询", "label": "专业咨询/心理支持"},
                    {"value": "药物治疗", "label": "药物治疗"},
                    {"value": "放松训练", "label": "放松训练/冥想"},
                    {"value": "其他", "label": "其他"},
                ]
            }
        ]
    }

    # Step 6: Physical Survey
    physical_survey_data = {
        "title": "体能与呼吸困难评分",
        "questions": [
            {
                "id": "fatigue_score",
                "text": "请为您目前的疲惫程度打分，0分表示精力充沛，10分表示精疲力竭，完全动不了。",
                "type": "select",
                "placeholder": "请选择您的分值",
                "options": [
                    {"value": "0", "label": "0 - 精力充沛"},
                    {"value": "1", "label": "1"},
                    {"value": "2", "label": "2"},
                    {"value": "3", "label": "3"},
                    {"value": "4", "label": "4"},
                    {"value": "5", "label": "5"},
                    {"value": "6", "label": "6"},
                    {"value": "7", "label": "7"},
                    {"value": "8", "label": "8"},
                    {"value": "9", "label": "9"},
                    {"value": "10", "label": "10 - 精疲力竭"},
                ]
            },
            {
                "id": "activity_level",
                "text": "您近期日常活动能力如何？",
                "type": "radio",
                "options": [
                    {"value": "完全正常", "label": "完全正常，没有任何症状，和生病前一样能进行各种活动（包括跑步、提重物等）。"},
                    {"value": "轻微不适", "label": "有轻微症状（如咳嗽、轻微疼痛），不能做剧烈运动，但可以进行轻体力工作（如简单的家务、办公室工作）。"},
                    {"value": "生活能自理", "label": "生活能自理（吃饭、穿衣、洗澡），白天能起床走动，但无法进行工作。白天卧床时间少于一半。"},
                    {"value": "生活部分自理", "label": "生活只能部分自理，大部分时间需要卧床或坐在椅子上。白天卧床时间超过一半。"},
                    {"value": "完全不能自理", "label": "完全不能自理，需要别人完全照顾，全天卧床或坐在椅子上。"},
                ]
            },
             {
                "id": "breath_difficulty",
                "text": "您在活动时感到气短/呼吸困难的程度？",
                "type": "radio",
                "options": [
                    {"value": "剧烈运动气喘", "label": "我仅在剧烈运动（如快跑、爬高层楼梯）时才感到气喘。"},
                    {"value": "平地快走气喘", "label": "我在平地快走或上小斜坡时会感到气喘。"},
                    {"value": "平地慢走气喘", "label": "我在平地行走时，因为气喘必须比同龄人走得慢，或者自己走几分钟就得停下来喘口气。"},
                    {"value": "走100米气喘", "label": "我在平地走约100米，或才几分钟，就不得不停下来喘口气。"},
                    {"value": "严重气喘", "label": "我因为气喘太严重而无法离开房间，或者穿脱衣服都会气喘。"},
                ]
            }
        ]
    }

    context = {
        "sleep_survey": sleep_survey_data,
        "pain_survey": pain_survey_data,
        "cough_survey": cough_survey_data,
        "appetite_survey": appetite_survey_data,
        "emotion_survey": emotion_survey_data,
        "physical_survey": physical_survey_data,
    }

    return render(request, "web_patient/followup/daily_survey.html", context)
