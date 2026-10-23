# VoiceBoard 架构与数据字典

## 模块边界

- `src/importer.py`：只处理 CSV 解析、规范化、校验、文件限制和反馈指纹。
- `src/classifiers/`：通过统一结果模型提供离线规则和 DeepSeek 两种分类器。
- `src/repository.py`：只负责 SQLite 建表、事务和参数化 CRUD。
- `src/services/`：编排导入、人工修订、洞察和路线图业务规则。
- `src/analytics.py`：使用 Pandas 完成可重复的优先级聚合与稳定排序。
- `pages/`：只处理 Streamlit 展示、输入和用户确认。

## 数据流

```text
CSV bytes
  → 大小/编码/字段/逐行校验
  → 数据规范化与 SHA-256 去重指纹
  → 规则分类或 DeepSeek 结构化分类
  → 用户确认
  → import_batches + feedback 同事务写入
  → 人工修订与 feedback_revisions 审计
  → 组合筛选与 Pandas 聚合
  → Top 5 决策快照
  → roadmap_items 生命周期
```

## SQLite 表

### import_batches

记录文件名、分类模式、总行数、实际写入数和创建时间，用于追溯每次导入。

### feedback

保存原文、国家、用户类型、品类、评分、反馈日期、分类、影响程度、分类来源、置信度和理由。`fingerprint` 唯一，评分与影响程度有数据库 CHECK 约束。

### feedback_revisions

保存人工修订前后的分类、影响程度、原因和时间。页面显示当前值，审计表保留决策过程。

### roadmap_items

保存需求卡标题、分类、优先级快照、筛选快照、方案、证据摘要、负责人、状态、目标版本和归档时间。`source_key` 保证同一决策快照幂等。

## 一致性与安全

- 导入批次与反馈记录在一个事务中提交；任何一行违反约束都会回滚整批。
- SQL 值全部使用参数绑定；动态列只接受代码内白名单。
- DeepSeek 输出必须通过枚举、类型和范围验证，不能进入 SQL、文件路径或命令。
- CSV 下载对以 `= + - @` 开头的字符串添加安全前缀。
- 单次上传上限 10 MB、20,000 行；分析查询同样限制为 20,000 条。
