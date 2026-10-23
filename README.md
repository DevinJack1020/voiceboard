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
DEEPSEEK_MODEL=deepseek-chat
```

`.env` 已加入 `.gitignore`。密钥不会写入 SQLite、日志或 Git。应用只允许访问 DeepSeek 官方 HTTPS 主机、禁止 HTTP 重定向，并校验模型返回的分类、影响程度、置信度和理由。API 失败时整批不会写入，可改用离线规则重新处理。

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

测试覆盖 CSV 边界、数据库事务、六类规则、DeepSeek 非法响应、组合筛选、人工修订、优先级、Top 5、需求卡生命周期、公式注入和 Streamlit 空状态。

完整浏览器主流程和重启持久化均已通过，测试证据见 [浏览器端到端验收记录](./docs/e2e-verification.md)。

## 项目结构

```text
voiceboard/
├── app.py                         # 首页与真实数据库状态
├── pages/                         # 五个 Streamlit 工作页面
├── src/
│   ├── classifiers/               # 离线规则与 DeepSeek 实现
│   ├── services/                  # 导入、反馈、洞察、路线图业务层
│   ├── analytics.py               # 透明优先级计算
│   ├── importer.py                # CSV 合同、校验与去重
│   ├── repository.py              # SQLite 参数化 CRUD
│   └── exports.py                 # 安全 CSV 导出
├── tests/                         # 单元、集成和 Streamlit 冒烟测试
├── assets/feedback_template.csv   # 只有表头的空白模板
├── docs/                          # 架构、测试与设计资料
└── scripts/run.ps1                # Windows 一键启动
```

## 项目原创性与参考

本项目参考了 [Intelligent Customer Feedback Analytics](https://github.com/darshxn10x/intelligent-feedback-analytics) 的“反馈分析 + SQLite”方向。参考仓库采用 MIT License。VoiceBoard 未直接复制其源码，而是独立设计并实现了跨境电商分类、透明优先级、人工修订审计、Top 5 产品方案和需求路线图闭环。

## 简历表述参考

> 独立开发 VoiceBoard 跨境电商反馈与路线图平台：基于 Streamlit、Pandas 与 SQLite 实现真实 CSV 导入、六类反馈分类、DeepSeek 可选增强、组合筛选及“频次 × 影响”优先级模型；打通 Top 5 痛点到需求卡、负责人、版本和状态流转的产品决策闭环，并通过自动化测试与浏览器验收验证持久化和异常路径。

完整中文总结见 [VoiceBoard项目总结.pdf](./VoiceBoard项目总结.pdf)。
