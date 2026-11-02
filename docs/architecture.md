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

## AI 分类链路与失败路径

```text
上传 CSV（10 MB / 20,000 行校验）
  → 选择分类模式 rule | deepseek
  → DeepSeek 模式：先校验单批 ≤ 100 条（超出直接拒绝）
      → https://api.deepseek.com/chat/completions
         JSON 模式、thinking disabled、temperature=0、max_tokens=300
         连接 5s / 读取 30s 超时；仅超时与 429/5xx 重试 1 次；禁止重定向
      → 解析 choices[0].message.content 为 JSON
      → 校验 category 枚举 / impact_level 1–5 整数 / confidence 0–1 / reason 非空
          ├─ 通过 → ClassificationResult(source='deepseek')
          └─ 不通过或网络失败 → DeepSeekAPIError → 预览失败，整批不写入
  → rule 模式：关键词评分
      ├─ 唯一最高分 → 分类 + 命中关键词理由
      └─ 无命中 / 多类并列 → 「待确认」（confidence 0.0 / 0.4）
  → 用户在预览中确认 → import_batches + feedback 同事务写入
  → 人工修订 → feedback 当前值更新为 manual + feedback_revisions 审计
```

失败路径清单：

| 失败场景 | 系统行为 | 用户可执行的下一步 |
| --- | --- | --- |
| 未配置 API Key | 构造分类器时即报错，无网络请求 | 填写 Key 或改用离线规则 |
| 单批超过 100 条 | 预览前拒绝，提示拆分文件或改用规则 | 拆分 CSV / 换规则模式 |
| 网络超时 / 5xx / 429 | 重试 1 次后仍失败则整批拒绝 | 稍后重试或改用离线规则 |
| 401 / 402 | 不重试，直接提示 Key 无效 / 余额不足 | 检查配置 |
| 模型返回非 JSON / 非法枚举 / 越界数值 | 校验失败，整批拒绝 | 改用离线规则并记录 Badcase |
| 数据库约束冲突 | 事务回滚，不留下半批数据 | 修正 CSV 后重新导入 |
| 重复反馈 | 指纹去重，从预览中排除 | 无需处理 |

评测与指标口径见 [AI 设计说明](./ai-design.md) 与 [一页评测报告](./eval-report.md)。
