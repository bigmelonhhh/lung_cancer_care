# 移动端「患者诊疗记录」查看页测试记录

## 功能范围
- 患者主页“诊疗记录”入口跳转到移动端诊疗记录查看页（携带 patient_id）
- 诊疗记录列表：卡片布局、折叠展开查看详情（备注/图片）
- 分页：每页 10 条，支持上一页/下一页
- 权限：仅医生/助理可访问；非关联医生访问返回 404
- 只读：页面不提供新增/编辑/删除入口

## 自动化测试

```bash
python manage.py test web_doctor.tests.test_mobile_patient_records -v 2
python manage.py test web_doctor.tests.test_reports_filters -v 2
python manage.py test web_doctor.tests.test_mobile_patient_home -v 2
```

## 真机测试建议（手工步骤）
- iOS Safari
  - 进入患者主页 → 点击“诊疗记录” → 首屏是否正常渲染
  - 点击任一记录卡片展开 → 图片是否可点开新页查看
  - 翻页（records_page=2）→ 是否加载下一页数据
- Android Chrome
  - 同上流程，检查折叠动画/触控区域是否正常

## 性能验收建议（手工测量）
- 首次加载：打开页面后在浏览器 DevTools Network/Performance 观察首屏完成时间，目标 ≤ 2s
- 翻页加载：点击下一页后观察完成时间，目标 ≤ 1s

