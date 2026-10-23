# VoiceBoard 实施计划

## 概览

按已批准的设计规格，实现一个空库启动、可导入真实 CSV、可选 DeepSeek 增强分类、以 SQLite 持久化反馈与需求卡的 Streamlit 产品工作台。实施遵循测试驱动：每个业务切片先写失败测试，再写最小实现，通过后提交独立 Git 记录。

## 架构决策

- 使用 Python 3.14 兼容依赖；虚拟环境、pip 缓存、数据库和运行缓存全部位于 `D:` 盘。
- Streamlit 页面只负责交互；导入、分类、分析、路线图和数据库访问保持独立模块。
- SQLite 使用显式建表版本和事务，不引入 ORM。
- 分类器遵守统一接口：离线规则始终可用，DeepSeek 为可选实现。
- 不自动导入样例数据；只提交空白 CSV 模板和测试夹具。
- 每完成 1–2 个垂直切片运行相关测试，每个阶段运行完整测试套件。

## 任务清单

### 阶段一：可运行基础

## 任务 1：项目骨架与质量工具

**说明：** 建立最小可运行 Streamlit 应用、依赖声明、D 盘启动脚本、环境变量示例和测试配置。

**验收标准：**
- [ ] 空库启动页面明确提示导入真实 CSV，不显示虚假 KPI。
- [ ] `.env`、数据库、虚拟环境、缓存和导出文件均被忽略。
- [ ] 一条 PowerShell 命令可在项目内 D 盘虚拟环境启动应用。

**验证：**
- [ ] `python -m pytest tests/test_app_smoke.py -q`
- [ ] `python -m compileall app.py src`

**依赖：** 无

**可能涉及文件：** `app.py`、`requirements.txt`、`.gitignore`、`.env.example`、`scripts/run.ps1`

**规模：** 中

## 任务 2：SQLite 模式与持久化仓储

**说明：** 建立导入批次、反馈、修订记录和需求卡数据表及参数化 CRUD。

**验收标准：**
- [ ] 新数据库能幂等初始化四张核心表和必要索引。
- [ ] 事务失败会完整回滚，重复指纹受唯一约束保护。
- [ ] 关闭并重新连接后记录仍存在。

**验证：**
- [ ] `python -m pytest tests/test_repository.py -q`

**依赖：** 任务 1

**可能涉及文件：** `src/db.py`、`src/repository.py`、`src/models.py`、`tests/test_repository.py`

**规模：** 中

### 检查点：基础

- [ ] 冒烟测试和仓储测试全部通过。
- [ ] 临时数据库测试不会污染实际 `data/voiceboard.db`。

### 阶段二：真实反馈导入与分类

## 任务 3：CSV 合同、校验与去重预览

**说明：** 实现模板生成、CSV 解析、字段规范化、逐行错误报告、限制检查和指纹去重。

**验收标准：**
- [ ] 合法 CSV 转换为规范记录并生成稳定指纹。
- [ ] 缺列、空文本、非法评分/日期、超限和重复均返回明确结果。
- [ ] 校验阶段不写数据库。

**验证：**
- [ ] `python -m pytest tests/test_importer.py -q`

**依赖：** 任务 1、2

**可能涉及文件：** `src/importer.py`、`src/schema.py`、`assets/feedback_template.csv`、`tests/test_importer.py`

**规模：** 中

## 任务 4：离线规则分类器

**说明：** 实现中英文关键词分类、冲突处理、待确认状态和影响程度估算。

**验收标准：**
- [ ] 六类典型反馈获得正确分类及可解释理由。
- [ ] 并列、无命中和影响程度边界行为稳定。
- [ ] CSV 人工影响程度优先于估算结果。

**验证：**
- [ ] `python -m pytest tests/test_rule_classifier.py -q`

**依赖：** 任务 3

**可能涉及文件：** `src/classifiers/base.py`、`src/classifiers/rule.py`、`src/config.py`、`tests/test_rule_classifier.py`

**规模：** 中

## 任务 5：DeepSeek 分类器

**说明：** 实现 OpenAI 兼容 HTTPS 请求、批处理、结构化响应校验、超时重试和安全错误映射。

**验收标准：**
- [ ] 合法模拟响应转换为统一分类结果。
- [ ] 缺密钥、非法 URL、非法 JSON/枚举、超时和限流均返回明确错误且不泄露密钥。
- [ ] 调用失败时用户可以用相同预览切换离线规则，不产生半批入库。

**验证：**
- [ ] `python -m pytest tests/test_deepseek_classifier.py -q`

**依赖：** 任务 3、4

**可能涉及文件：** `src/classifiers/deepseek.py`、`src/classifiers/base.py`、`src/config.py`、`tests/test_deepseek_classifier.py`

**规模：** 中

## 任务 6：数据导入垂直切片

**说明：** 将模板下载、上传预览、模式选择、确认导入、事务入库和批次结果接入 Streamlit。

**验收标准：**
- [ ] 用户必须确认后才写库，成功数、重复数和失败数可核对。
- [ ] 重复上传不会新增反馈；DeepSeek 失败不会部分写库。
- [ ] 导入完成后反馈明细能立即查询新增记录。

**验证：**
- [ ] `python -m pytest tests/test_import_service.py tests/test_import_page.py -q`
- [ ] 手动导入一份测试 CSV 并检查 SQLite 行数。

**依赖：** 任务 2–5

**可能涉及文件：** `src/services/import_service.py`、`pages/1_数据导入.py`、`src/ui.py`、`tests/test_import_service.py`、`tests/test_import_page.py`

**规模：** 中

### 检查点：导入与分类

- [ ] 完整测试套件通过。
- [ ] 空库 → 预览 → 分类 → 确认 → 持久化主路径可操作。
- [ ] 应用重启后导入数据仍存在。

### 阶段三：产品决策闭环

## 任务 7：反馈明细与人工修订

**说明：** 实现组合筛选、分页、分类来源展示，以及分类和影响程度修订并记录审计历史。

**验收标准：**
- [ ] 国家、用户类型、商品品类和日期可组合筛选。
- [ ] 人工修改即时生效且创建修订记录。
- [ ] 无结果和待确认队列有明确状态说明。

**验证：**
- [ ] `python -m pytest tests/test_feedback_service.py tests/test_feedback_page.py -q`

**依赖：** 任务 6

**可能涉及文件：** `src/services/feedback_service.py`、`pages/2_反馈明细.py`、`src/repository.py`、`tests/test_feedback_service.py`、`tests/test_feedback_page.py`

**规模：** 中

## 任务 8：优先级分析与看板

**说明：** 实现纯 Pandas 聚合、稳定排序、KPI 和优先级可视化，并可钻取原始证据。

**验收标准：**
- [ ] 得分严格等于筛选范围内频次乘平均影响程度。
- [ ] 待确认不进入正式排名，同分排序固定。
- [ ] 页面筛选后 KPI、排名和证据同步变化。

**验证：**
- [ ] `python -m pytest tests/test_analytics.py tests/test_priority_page.py -q`

**依赖：** 任务 7

**可能涉及文件：** `src/analytics.py`、`pages/3_优先级看板.py`、`src/ui.py`、`tests/test_analytics.py`、`tests/test_priority_page.py`

**规模：** 中

## 任务 9：Top 5 痛点与需求卡创建

**说明：** 展示动态 Top 5、证据与可编辑方案，并将决策快照真正写入需求卡。

**验收标准：**
- [ ] Top 5 与优先级看板使用同一分析结果。
- [ ] 创建卡片保存筛选条件、指标快照、方案和证据摘要。
- [ ] 重复点击受到幂等保护并给予明确反馈。

**验证：**
- [ ] `python -m pytest tests/test_insight_service.py tests/test_top5_page.py -q`

**依赖：** 任务 8

**可能涉及文件：** `src/services/insight_service.py`、`pages/4_Top5痛点.py`、`src/repository.py`、`tests/test_insight_service.py`、`tests/test_top5_page.py`

**规模：** 中

## 任务 10：产品路线图生命周期

**说明：** 实现需求卡查看、新增、编辑、状态流转、负责人/版本筛选、归档和恢复。

**验收标准：**
- [ ] 四种状态和字段规则受服务层校验。
- [ ] 编辑、归档和恢复均持久化并更新时间。
- [ ] 重启应用后路线图状态保持不变。

**验证：**
- [ ] `python -m pytest tests/test_roadmap_service.py tests/test_roadmap_page.py -q`

**依赖：** 任务 2、9

**可能涉及文件：** `src/services/roadmap_service.py`、`pages/5_产品路线图.py`、`src/repository.py`、`tests/test_roadmap_service.py`、`tests/test_roadmap_page.py`

**规模：** 中

### 检查点：决策闭环

- [ ] 完整测试套件通过。
- [ ] 导入 → 修订 → 排序 → Top 5 → 需求卡 → 状态流转可端到端完成。
- [ ] 页面刷新和应用重启不丢数据。

### 阶段四：交付与验收

## 任务 11：安全导出与边界状态

**说明：** 增加筛选结果、优先级和路线图 CSV 导出，完善公式注入防护、日志和错误状态。

**验收标准：**
- [ ] 三类导出内容与当前数据一致。
- [ ] 以 `= + - @` 开头的危险单元格在导出时被安全处理。
- [ ] 错误日志不包含 API Key 或完整敏感响应。

**验证：**
- [ ] `python -m pytest tests/test_exports.py tests/test_security.py -q`

**依赖：** 任务 7–10

**可能涉及文件：** `src/exports.py`、`src/logging_config.py`、`src/ui.py`、`tests/test_exports.py`、`tests/test_security.py`

**规模：** 中

## 任务 12：中文文档与项目总结 PDF

**说明：** 编写运行、数据格式、DeepSeek 配置、架构、测试和面试讲解文档，并生成可打印 PDF。

**验收标准：**
- [ ] 新用户能仅按 README 在 D 盘完成安装和启动。
- [ ] 文档明确区分项目原创能力与参考仓库。
- [ ] PDF 包含问题、方案、架构、实现、测试、运行方式和简历表述且无排版截断。

**验证：**
- [ ] 按 README 从干净虚拟环境执行安装和测试。
- [ ] 渲染并逐页检查 PDF。

**依赖：** 任务 1–11

**可能涉及文件：** `README.md`、`docs/architecture.md`、`docs/testing.md`、`docs/项目总结.md`、`docs/VoiceBoard项目总结.pdf`

**规模：** 中

## 任务 13：浏览器端到端验收

**说明：** 使用真实浏览器完成主流程和关键异常流程，记录测试证据并修复发现的问题。

**验收标准：**
- [ ] 空库主路径从模板下载到需求卡状态流转全部成功。
- [ ] 错误 CSV、无 API Key、无结果筛选和重复导入均表现正确。
- [ ] 重启后验证反馈、修订和需求卡仍存在。

**验证：**
- [ ] `python -m pytest -q`
- [ ] 浏览器验收清单全部勾选并保存截图或文字记录。

**依赖：** 任务 1–12

**可能涉及文件：** `docs/e2e-verification.md`、测试夹具及缺陷涉及文件

**规模：** 中

## 任务 14：Git 整理与 GitHub 发布

**说明：** 检查仓库敏感信息、提交历史和远程状态，创建公共 GitHub 仓库并推送。

**验收标准：**
- [ ] Git 历史按功能分层，无 API Key、数据库或本地缓存。
- [ ] GitHub 仓库为 `DevinJack1020/voiceboard` 且默认分支为 `main`。
- [ ] 远程 README、源码、测试和 PDF 均可访问。

**验证：**
- [ ] `git status --short` 为空。
- [ ] GitHub 远程分支与本地 `main` 指向同一提交。
- [ ] 仓库页面链接可打开。

**依赖：** 任务 13

**可能涉及文件：** 仓库全部受控交付物

**规模：** 小

### 最终检查点

- [ ] 所有自动化测试通过。
- [ ] 浏览器主路径和异常路径通过。
- [ ] PDF 已逐页检查。
- [ ] GitHub 推送完成且无敏感信息。
- [ ] 用户可按 README 独立运行项目。

## 风险与缓解

| 风险 | 影响 | 缓解措施 |
| --- | --- | --- |
| Python 3.14 下依赖兼容性 | 高 | 优先选择纯 Python 或已有 3.14 轮子的版本，先完成最小安装验证 |
| DeepSeek 网络、额度或响应不稳定 | 中 | 结构化校验、超时、有限重试、无半批写入和离线规则回退 |
| Streamlit 重跑导致重复写入 | 高 | 表单提交、幂等键、唯一约束和事务 |
| 中文路径和 Windows 脚本问题 | 中 | 所有命令在当前 D 盘中文路径实测，使用 `-LiteralPath` |
| 优先级结果被误解为 AI 结论 | 中 | 展示公式、证据反馈、分类来源和人工修订入口 |

## 开放问题

无。实现所需选择均已在设计规格中确定。
