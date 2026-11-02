# VoiceBoard｜跨境电商用户反馈与产品路线图平台

VoiceBoard 是一个面向跨境电商产品经理的真实数据工作台。它把用户上传的 CSV 反馈持久化到 SQLite，再完成分类、筛选、优先级计算、Top 5 痛点识别和产品路线图管理。

这不是固定数据演示：首次启动为空数据库，页面上的数量、排名、证据和需求卡全部来自你实际导入的数据。关闭或重启应用后，数据仍保存在本地数据库中。

## 核心工作流

```text
上传真实 CSV
    ↓
字段校验、逐行错误、指纹去重
    ↓
离线规则 / DeepSeek 分类与影响评估
    ↓
SQLite 持久化与人工修订审计
    ↓
国家 / 用户类型 / 商品品类筛选
    ↓
频次 × 平均影响程度 → Top 5 痛点
    ↓
需求卡 → 负责人 / 状态 / 目标版本 → 产品路线图
```

## 已实现能力

- 标准 CSV 模板下载、10 MB / 20,000 行限制、UTF-8 解析和逐行错误提示。
- 物流、支付、商品质量、搜索推荐、客服、退换货六类反馈；不确定结果进入“待确认”。
- 无需联网的可解释规则分类，以及可选的真实 DeepSeek JSON API 分类。
- DeepSeek 单批限制为 100 条，防止误传大文件造成意外 API 费用。
- 按国家、用户类型、商品品类组合筛选；支持反馈分页和人工修订。
- 严格使用“出现频次 × 平均影响程度”的动态优先级排名。
- Top 5 痛点、原始反馈证据、可编辑产品方案和一键需求卡创建。
- 需求卡负责人、待评估/已规划/开发中/已上线状态、目标版本、归档与恢复。
- 筛选反馈、优先级和路线图 CSV 导出，包含电子表格公式注入防护。
- SQLite 事务、唯一指纹、参数化 SQL、DeepSeek HTTPS 主机限制和结构化输出校验。

## 在 Windows D 盘运行

项目已经位于：

```text
D:\Desktop\就业\github项目\voiceboard
```

首次运行：

```powershell
cd "D:\Desktop\就业\github项目\voiceboard"
python -m venv .venv
$env:PIP_CACHE_DIR="D:\Desktop\就业\github项目\.tool-cache\pip"
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1
```

浏览器打开 `http://localhost:8501`。虚拟环境、依赖缓存和数据库都位于 D 盘。

以后再次运行只需：

```powershell
cd "D:\Desktop\就业\github项目\voiceboard"
powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1
```

## CSV 数据格式

从“数据导入”页下载空白模板。必填字段：

| 字段 | 说明 | 示例 |
| --- | --- | --- |
| `feedback_text` | 用户反馈正文 | 包裹两周还没到 |
| `country` | 国家或市场 | SG |
| `user_type` | 用户类型 | 新用户 |
| `product_category` | 商品品类 | 电子产品 |
| `rating` | 1–5 星整数 | 1 |
| `created_at` | 可解析日期 | 2026-10-20 |

可选字段：`feedback_id`、`impact_level`。若提供 1–5 的 `impact_level`，它优先于自动估算。

系统不会静默导入错误行。缺列、空文本、非法评分、非法日期或影响程度错误都会阻止整批确认写入。同一反馈的规范化正文、维度和日期会生成唯一指纹，重复上传不会重复入库。

## 配置 DeepSeek

离线规则无需任何密钥。若要启用 DeepSeek：

1. 将 `.env.example` 复制为 `.env`。
2. 只填写你自己的 `DEEPSEEK_API_KEY`。
3. 通过 `scripts/run.ps1` 启动。
4. 在“数据导入”页选择 DeepSeek。

```dotenv
DEEPSEEK_API_KEY=你的密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
```

`.env` 已加入 `.gitignore`。密钥不会写入 SQLite、日志或 Git。应用只允许访问 DeepSeek 官方 HTTPS 主机、禁止 HTTP 重定向，并校验模型返回的分类、影响程度、置信度和理由。API 失败时整批不会写入，可改用离线规则重新处理。

## AI 可靠性设计

VoiceBoard 把模型输出当作不可信数据处理，把分类做成一条有明确失败路径的产品链路，而不是黑盒调用：

1. **结构化输出校验**：模型必须返回 JSON，且 `category` 属于六类 + 待确认、`impact_level` 为 1–5 整数、`confidence` 为 0–1 数字、`reason` 非空。任一条响应不合法立即失败，整批拒绝写入，不会产生半批脏数据。
2. **「待确认」安全阀**：规则未命中关键词或多类得分并列时进入待确认，不强行归档；待确认不参与正式优先级排名，避免噪声污染 Top 5。
3. **人工修订与审计**：人工修正后 `feedback_revisions` 表记录修改前后的分类、影响程度、原因和时间，`classification_source` 标记为 `manual`，错误可追溯、可回滚、可统计修订率。
4. **可解释规则兜底**：无需网络或 API Key 的离线规则分类器始终可用；DeepSeek 超时、额度不足或 Key 无效时，页面提示改用离线规则重新处理。

调用成本与安全边界：DeepSeek 单批最多 100 条；连接超时 5 秒、读取超时 30 秒；仅对超时和 429/5xx 重试 1 次；Base URL 只接受 `https://api.deepseek.com` 且禁止重定向；API Key 只来自会话输入或环境变量，不写入数据库、日志或错误信息。

详细设计动机与面试追问口径见 [AI 设计说明](./docs/ai-design.md)，量化效果见 [一页评测报告](./docs/eval-report.md)。

## 分类评测

VoiceBoard 自带一套可复现的小型分类评测，用于回答「DeepSeek 零样本相比规则基线到底提升了多少」，而不是凭感觉说 AI 有价值。

- **评测集**：`evals/feedback_eval_v1.csv`，80 条公开真实电商反馈——78 条逐字摘录自 Google Play 公开评论与中文购物评论语料，2 条是人工构造的提示注入对抗探针（`source=authored-adversarial`，明确标注、不冒充真实数据）。六类各 11–13 条、待确认 8 条，逐条 `source_ref` 可核验来源行号。
- **标注**：单标注者（AI Agent）标注主痛点与影响度，**无第二标注者、无双盲、无一致性检验**；负向样本偏多（1–2 星占 70/80），类别比例不代表线上真实分布。局限在评测报告中明确写出。
- **评测脚本** `scripts/run_eval.py`，支持规则基线、DeepSeek 真实调用与离线复算三种模式：

```powershell
# 规则基线（离线、零成本）
.\.venv\Scripts\python.exe scripts/run_eval.py --mode rule --dataset evals/feedback_eval_v1.csv --out evals/results/rule_v1.json --predictions-out evals/results/predictions_rule_v1.csv

# DeepSeek 真实评测（需要 .env 中的 DEEPSEEK_API_KEY；失败整批中止，不写正式结果）
.\.venv\Scripts\python.exe scripts/run_eval.py --mode deepseek --dataset evals/feedback_eval_v1.csv --model deepseek-flash --out evals/results/deepseek_v1.json --predictions-out evals/results/predictions_deepseek_v1.csv --badcases-out evals/results/badcases_v1.csv
```

- **输出**：`evals/results/{rule,deepseek}_v1.json`（指标 / token 成本 / p50、p95 延迟 / 失败清单）、`predictions_*.csv`（逐条预测与耗时）、`badcases_v1.csv`（Badcase 四层归因：数据 / 提示词 / 规则 / 交互）。
- **可复现性**：结果 JSON 记录 `run_id`、模型名、`prompt_version`、评测时间、数据集与 n；复算模式不调用 API，可离线重算指标。
- **结果摘要（v1，80 条，2026-11-02，模型 `deepseek-flash`（非思考模式），prompt `deepseek-classify-v2`）**：业务类准确率 86.11%、端到端 85.00%（规则基线分别为 56.94%、60.00%）；关键类召回 物流 92.31% / 支付 75.00% / 商品质量 100%；待确认率 8.75%，人工修订率估计 20.00%（规则基线 47.50%）。80 条约 26,430 tokens、成本约 ¥0.0379（100 条约 ¥0.0474），单条延迟 p50 896ms / p95 1,278ms，0 失败。主 Badcase 12 条：数据层 2、提示词层 9、规则层 0、交互层 1；规则基线 32 条错例中规则层 31、数据层 1。
- **结果查看**：应用内「评测与 Badcase」页，或直接看 [一页评测报告](./docs/eval-report.md)。这些是 80 条离线小样本结果，不代表线上效果。

## 优先级口径

```text
frequency = 当前筛选范围内该分类反馈数
average_impact = 当前筛选范围内该分类平均影响程度
priority_score = frequency × average_impact
```

显示值保留一位小数，排序使用未舍入值。同分时依次比较平均影响程度、频次和固定分类顺序。“待确认”不会进入正式排名。

## 测试

安装开发依赖并运行：

```powershell
$env:PIP_CACHE_DIR="D:\Desktop\就业\github项目\.tool-cache\pip"
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q app.py pages src
```

测试覆盖 CSV 边界、数据库事务、六类规则、DeepSeek 非法响应、组合筛选、人工修订、优先级、Top 5、需求卡生命周期、公式注入和 Streamlit 空状态；评测指标/成本/延迟、Badcase 四层归因、`feedback_revisions` 修订率统计，以及反馈问答 Agent 的检索命中、引用来源、无证据拒答与过滤条件。

完整浏览器主流程和重启持久化均已通过，测试证据见 [浏览器端到端验收记录](./docs/e2e-verification.md)。

## 项目结构

```text
voiceboard/
├── app.py                         # 首页与真实数据库状态
├── pages/                         # 七个 Streamlit 工作页面
├── src/
│   ├── classifiers/               # 离线规则与 DeepSeek 实现
│   ├── evaluation/                # 指标、成本、延迟与 Badcase 归因纯函数
│   ├── agent/                     # 反馈问答的检索与回答合成
│   ├── services/                  # 导入、反馈、洞察、路线图、评测业务层
│   ├── analytics.py               # 透明优先级计算
│   ├── importer.py                # CSV 合同、校验与去重
│   ├── repository.py              # SQLite 参数化 CRUD
│   └── exports.py                 # 安全 CSV 导出
├── evals/                         # 分类评测集、标注规约与评测结果
├── tests/                         # 单元、集成和 Streamlit 冒烟测试
├── assets/feedback_template.csv   # 只有表头的空白模板
├── docs/                          # 架构、设计、评测与边界说明
└── scripts/                       # Windows 一键启动、分类评测、问答评测
```

页面依次为：数据导入、反馈明细、优先级看板、Top 5 痛点、产品路线图、评测与 Badcase、反馈问答。AI 相关文档：[AI 设计说明](./docs/ai-design.md)、[一页评测报告](./docs/eval-report.md)、[反馈问答边界](./docs/agent-scope.md)、[架构与数据字典](./docs/architecture.md)。

## 项目原创性与参考

本项目参考了 [Intelligent Customer Feedback Analytics](https://github.com/darshxn10x/intelligent-feedback-analytics) 的“反馈分析 + SQLite”方向。参考仓库采用 MIT License。VoiceBoard 未直接复制其源码，而是独立设计并实现了跨境电商分类、透明优先级、人工修订审计、Top 5 产品方案和需求路线图闭环。

## 简历表述参考

> 独立开发 VoiceBoard 跨境电商反馈与路线图平台：基于 Streamlit、Pandas 与 SQLite 实现真实 CSV 导入、六类反馈分类、DeepSeek 可选增强、组合筛选及“频次 × 影响”优先级模型；打通 Top 5 痛点到需求卡、负责人、版本和状态流转的产品决策闭环，并通过自动化测试与浏览器验收验证持久化和异常路径。

完整中文总结见 [VoiceBoard项目总结.pdf](./VoiceBoard项目总结.pdf)。
