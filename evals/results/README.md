# 评测结果目录

由 `scripts/run_eval.py` 生成（评测引擎见 `src/evaluation/`）：

- `rule_v1.json` / `deepseek_v1.json`：规则基线与 DeepSeek 的指标、成本、延迟、失败清单；
  `deepseek_v1.json` 为当前口径（模型 `deepseek-flash`，prompt `deepseek-classify-v2`，关闭思考模式）；
- `deepseek_chat_baseline_v1.json`：上一版对照（模型 `deepseek-chat`，prompt `deepseek-classify-v1`），
  仅用于模型/提示词升级前后对比，不是当前结果；
- `predictions_rule_v1.csv` / `predictions_deepseek_v1.csv`：逐条预测明细；
- `badcases_v1.csv`：主 Badcase 归因（四层：数据/提示词/规则/交互）；
- `badcases_rule_v1.csv`：规则基线错例归因（可选参考）。

同目录另有 `agent_v1.json`：反馈问答 Agent 的 15 题评测结果（检索命中/引用/拒答），
由 `scripts/run_agent_eval.py` 生成，schema 与分类评测 JSON 无关。

复跑命令见 `scripts/run_eval.py` 模块 docstring。结果 JSON/CSV 的 schema 与口径
（准确率定义、待确认比例、成本单价与延迟分位数）见 `src/evaluation/` 各模块 docstring。
