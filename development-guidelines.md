# 肺癌院外管理系统 - 开发指南 (Development Guidelines)

**版本**：2.0  
**最后更新**：2025-11-27

本文档用于约束和指导本项目的日常开发，旨在构建一个**高内聚、低耦合、易维护**的 Django 系统。

---

## 1. 环境与依赖管理

- **虚拟环境**：统一使用 Conda 环境。开发前务必执行：

  ```bash
  conda activate lung_cancer_care
  ```

- **依赖管理**：
  - 所有第三方依赖必须写入 `requirements.txt`。
  - 禁止在服务器上手动 `pip install` 临时包而不记录。
  - 依赖升级或新增时，需在 PR/Commit 中简要说明原因。

## 2. 后端架构原则 (MTV + Service Layer)

本项目严格遵循 “Thin Views, Fat Forms, Fat Services” 的分层架构原则。严禁业务逻辑泄露到 View 层或 Model 层。

### 2.1 Model (数据层)

- **职责**：仅负责定义数据库结构、字段级约束（`unique`, `choices`）和最基础的数据获取方法（`__str__`）。
- **规范**：
  - 一个表对应一个 `model.py` 文件（若 App 模型较多，使用 `models/` 目录拆分）。
  - 字段必须包含 `verbose_name` 和 `help_text`（用于生成文档和前端提示）。
- **禁止**：在 `save()` 方法中编写复杂的跨表业务逻辑或发送网络请求。

### 2.2 Form (表单/验证层) - 新增核心层

- **职责**：负责所有用户输入的接收、清洗、格式转换和基础验证。
- **规范**：
  - 所有前端提交的数据（POST/PUT），必须先通过 Form 或 ModelForm 进行验证。
  - 样式注入：Form 负责定义 Widget 的 Tailwind CSS 类名（如 `class="w-full border..."`），保持 View 和 Template 的整洁。
  - 数据清洗：利用 `clean_<field>` 方法处理数据格式（如将列表转为逗号分隔字符串、日期格式化）。
- **禁止**：在 View 中直接使用 `request.POST.get()` 获取业务数据。

### 2.3 Service (业务逻辑层) - 核心

- **职责**：系统的“大脑”。负责业务流程编排、跨表事务、权限深度校验、第三方接口调用。
- **规范**：
  - 原子性：涉及多个模型写入的操作，必须使用 `with transaction.atomic():` 包裹。
  - 解耦：View 层只能调用 Service 方法，不能直接操作复杂的 Model 写入。
  - 返回值：成功返回业务对象，失败抛出 `django.core.exceptions.ValidationError`。
  - 命名：动词 + 名词，清晰表意（如 `create_patient_archive`, `bind_doctor_qrcode`）。

### 2.4 View (视图层)

- **职责**：极简主义的“路由器”。
- **流程**：
  1. 接收 Request。
  2. 实例化 Form 进行验证。
  3. 调用 Service 处理业务。
  4. 返回 Response (HTML/JSON/HTMX)。
- **异常处理**：捕获 Service 抛出的 `ValidationError`，并通过 messages 框架反馈给用户。

## 3. 前端与交互规范

### 3.1 HTMX 优先

- 页面内的局部交互（如级联选择、即时保存、详情加载）优先使用 HTMX，减少全页刷新。
- **OOB (Out-Of-Band) 模式**：
  - 对于复杂的表单回填或多区域更新，禁止返回 JSON 让前端 JS 解析。
  - 必须返回带有 `hx-swap-oob="true"` 属性的 HTML 片段，直接替换目标 DOM 元素。

### 3.2 Tailwind CSS

- 样式类直接写在 Template 或 Form Widget 中。
- 避免编写自定义 CSS 文件（除非处理极其特殊的动画或第三方库覆盖）。
- 遵循 `web_sales/templates/layouts/` 中的基础布局规范。

### 3.3 长表单体验 (防手滑机制)

- **强制要求**：对于字段较多（>5 个）的录入型表单（如患者建档、病历录入），必须实现本地草稿自动保存。
- **实现逻辑**：
  1. 监听 input/change 事件 -> 存入 `localStorage`。
  2. 页面加载 -> 检查 storage -> 提示回填。
  3. 提交成功 (Success) -> 务必清除对应的 `localStorage`。

## 4. 特定业务场景规范

### 4.1 微信生态集成

- **解耦原则**：业务层（View/Service）严禁直接引用 `wechatpy` 库。
- **调用方式**：必须通过 `wx.services` 或 `users.services` 中封装好的方法进行调用（如获取用户信息、生成二维码）。
- **二维码**：View 层只负责从 Service 获取二维码链接（URL），不关心它是微信生成的还是缓存的。

### 4.2 危险因素 (Risk Factors) 数据

- **存储**：数据库中以 JSON 或逗号分隔字符串存储。
- **录入**：前端必须使用结构化表单（Checkbox/Select），禁止让用户直接输入非结构化文本。

## 5. 代码风格与测试

- **代码格式**：统一遵循 PEP8，建议配置 IDE 的 Black/Isort 自动格式化。
- **注释规范**：注释以“说明意图”为主，避免翻译代码；复杂逻辑必须补充可读性说明。
- **测试策略**：
  - 功能开发完成后，必须针对核心 Service 方法编写单元测试。
  - 重点测试：权限边界（A 销售查 B 销售的患者）、异常分支（微信接口超时、重复录入）。

### 5.1 注释范例

```python
def get_daily_plan_summary(patient, task_date=None):
    """
    【功能说明】
    - 汇总患者当天计划任务，用于患者端展示。

    【使用方法】
    - get_daily_plan_summary(patient)
    - get_daily_plan_summary(patient, date(2025, 1, 1))

    【参数说明】
    - patient: PatientProfile 实例。
    - task_date: date | None，默认当天。

    【返回值说明】
    - List[dict]，每个元素包含 task_type/status/title。
    """
    # 监测类需要逐条展示，其它类型按类目聚合一条
    tasks_by_type = {}
    ...
```

## 6. 提交规范 (Git)

- 禁止：直接修改生产环境代码。
- 禁止：提交 migrations 文件（除非是经过评审的 Schema 变更）。
- 流程：Feature Branch -> Pull Request -> Code Review -> Merge。
