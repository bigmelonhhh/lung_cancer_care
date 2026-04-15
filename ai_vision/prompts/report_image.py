from __future__ import annotations

import json


def build_report_image_prompt(*, allowed_categories: list[str]) -> str:
    category_list = json.dumps(allowed_categories, ensure_ascii=False)
    return f"""
你是医疗报告图像结构化抽取助手。请识别这张图片，并且只返回一个合法 JSON 对象。

任务目标：
从单张图片中抽取医疗检查/检验报告信息。你必须输出完整 JSON 结构。图片中没有、看不清、无法确认的字段，填 null；数组没有内容时返回 []。不要猜测，不要补充图片中不存在的信息，不要输出 markdown，不要输出解释。

系统允许的 report_category 值仅限以下 {len(allowed_categories)} 个：
{category_list}

返回 JSON 结构必须严格为：
{{
  "is_medical_report": boolean,
  "report_category": string | null,
  "hospital_name": string | null,
  "patient_name": string | null,
  "patient_gender": string | null,
  "patient_age": string | null,
  "sample_type": string | null,
  "report_name": string | null,
  "report_time_raw": string | null,
  "exam_time_raw": string | null,
  "items": [
    {{
      "item_name": string | null,
      "item_value": string | null,
      "abnormal_flag": "high" | "low" | "normal" | "unknown" | null,
      "reference_low": string | null,
      "reference_high": string | null,
      "unit": string | null,
      "item_code": string | null
    }}
  ],
  "exam_findings": string | null,
  "doctor_interpretation": string | null
}}

规则：
1. 如果不是医疗检查/检验报告，返回完整 JSON，其中 is_medical_report=false，report_category=null，其余字段填 null 或 []。
2. 如果是医疗报告，report_category 必须从给定的候选值中选择最匹配的一个；如果无法稳定判断，返回 null。
3. report_name 保留图片中的原始报告名称，不要用 report_category 替代。
4. 时间字段保留图片原始文本，不要自行换算格式。
5. 样本类型只在图片明确出现时提取，例如血清、血浆、全血、尿液。
6. 检验类报告要尽量提取 items。每个 item 必须来自同一行或同一条记录，严禁错配左右栏、上下行、相邻列。
7. 检查类报告通常不输出 items，而应提取 exam_findings 和 doctor_interpretation。
8. exam_findings 只记录客观描述，如“所见”“影像描述”“超声所见”“心电图描述”。
9. doctor_interpretation 只记录主观总结，如“印象”“结论”“提示”“诊断意见”“医生解读”。
10. item_code 只提取报告中的原始编码，不要生成任何标准编码。
11. 只返回一个合法 JSON 对象。
""".strip()

