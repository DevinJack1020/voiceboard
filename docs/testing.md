# VoiceBoard 测试说明

## 自动化测试层次

- 纯逻辑：CSV 规范化、规则分类、DeepSeek 响应校验、优先级排序和安全导出。
- SQLite 集成：建表幂等、唯一指纹、事务回滚、筛选、修订审计、需求卡持久化。
- 服务层：导入确认、DeepSeek 失败不落库、Top 5 决策快照和路线图生命周期。
- Streamlit 冒烟：首页及七个页面在空数据库下无异常并提供真实空状态。
- 评测与 Badcase：指标纯函数（准确率/召回/混淆矩阵/待确认/修订率估计/影响度）、成本与延迟汇总、Badcase 四层归因、结果 JSON/CSV 读取容错，以及「评测与 Badcase」页的空状态与有数据状态。
- 反馈问答 Agent：SQLite 关键词检索命中、引用只来自检索结果、无证据拒答、country/category/日期过滤，以及问答页的空状态。
- 浏览器验收：使用独立 E2E 数据库完成导入、筛选、Top 5、需求卡、状态更新和重启持久化。

## 运行命令

```powershell
cd "D:\Desktop\就业\github项目\voiceboard"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q app.py pages src
```

## 关键边界

- 缺少必填列、非法日期、评分超界、影响程度超界。
- 同一文件内重复、数据库已有重复和 Streamlit 重跑。
- 分类关键词并列、无命中和全部待确认。
- DeepSeek 缺密钥、非 HTTPS、非官方主机、超时、限流、非法 JSON 和非法枚举。
- 空数据库、筛选无结果、路线图为空和归档数据。
- SQL 注入式筛选值和电子表格公式注入式正文。

浏览器验收完成后，具体结果记录在 `docs/e2e-verification.md`。
