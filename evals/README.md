# VoiceBoard 真实反馈评测集 v1

给 VoiceBoard 分类器（DeepSeek 零样本 / 可解释规则基线）用的小型真实反馈评测集：
**80 条**跨境电商与电商平台的公开用户反馈，**逐条人工标注**主痛点类别与影响度。

> **诚实声明（请先读）**
> - 80 条中 **78 条是从公开真实评论中逐字摘录**的真实反馈；**2 条是人工构造的“提示注入”对抗探针**（用于检验模型抗注入能力，`source` 列以 `authored-adversarial` 开头、`label_note` 明确标注，**绝不冒充真实数据**）。
> - 标注为**单标注者**完成，**没有**第二标注者、双盲或一致性（Cohen's κ）检验，这是本数据集最大的局限，结论请按“小样本、单标注”谨慎解读。
> - 数据仅用于研究、教学与作品集演示，**不用于商业用途**，不重新分发原始大数据集（本仓库只保留 80 条抽样）。

## 文件

| 文件 | 说明 |
| --- | --- |
| `feedback_eval_v1.csv` | 主数据，80 行 × 12 列，UTF-8 |
| `labeling-guideline.md` | 六类定义、主痛点判定、难例规则、影响度 1–5 判定、标注流程与局限 |
| `sources/source_manifest.md` | 每个来源的仓库/文件/许可/下载命令，逐条行号映射与核验方法 |
| `README.md` | 本文件：来源、许可边界、抽样、分布、去标识、复跑、扩展与已知偏差 |

## 字段说明

| 列 | 含义 |
| --- | --- |
| `eval_id` | 稳定 ID，`FB001`–`FB080` |
| `feedback_text` | 真实评论文本（去标识、清理私有区乱码字符，未改写语义、未截断；最长 476 字符） |
| `country` | 国家/市场。**来源不一定提供该字段，按 App 主要市场推断**（见下文“元数据推断”） |
| `user_type` | 评论者角色，本集统一为 `买家`（消费者视角推断） |
| `product_category` | 平台/商品类目（如 `跨境B2C电商平台`、`图书`） |
| `rating` | 原始星级 1–5。Google Play / 商品评论为接口原值；中文语料无星级，由语料正负情感标签映射（见下文） |
| `created_at` | 原始评论日期 `YYYY-MM-DD`。中文语料无逐条日期，统一占位 `2018-01-01`（见下文） |
| `golden_category` | 人工标注主痛点：`物流`/`支付`/`商品质量`/`搜索推荐`/`客服`/`退换货`/`待确认` |
| `golden_impact_level` | 人工标注影响度 1–5（5 最严重），独立于 `rating` |
| `source` | 来源数据集标签（5 种，见下表） |
| `source_ref` | 可核验引用：`仓库@文件:L行号`（行号含表头，与 CSV 打开时的行号一致） |
| `label_note` | 标注依据/难例标记/元数据说明 |

## 类别分布

| 类别 | 条数 | 要求 |
| --- | ---: | --- |
| 物流 | 13 | ≥8 ✅ |
| 支付 | 12 | ≥8 ✅ |
| 商品质量 | 11 | ≥8 ✅ |
| 搜索推荐 | 11 | ≥8 ✅ |
| 客服 | 12 | ≥8 ✅ |
| 退换货 | 13 | ≥8 ✅ |
| 待确认 | 8 | ≥6 ✅ |
| **合计** | **80** | |

其它分布：英文 62 条、中文/中英混合 18 条（16 条中文语料 + 2 条注入探针含中文）；
星级 1★ 54、2★ 16、3★ 1、4★ 1、5★ 8；影响度 1:4、2:12、3:21、4:35、5:8；
难例 7 条（多意图 3、代码切换 1、超短 1、反讽/混合 1、边界 1）+ 注入探针 2 条。

## 来源与许可

| # | 来源 | 仓库 / 链接 | 许可与使用边界 | 本集条数 |
| --- | --- | --- | --- | ---: |
| 1 | AliExpress / Alibaba App 的 Google Play 公开评论（由该仓库作者抓取） | <https://github.com/nebekisa/ecommerce-app-review-analysis>（文件 `cleaned_reviews_data.csv`） | 仓库**未附许可证文件**；内容是 Google Play 上公开可见的用户评论（仓库内含 `scraper.py`）。**仅研究/非商业使用**，需注明出处；不重新分发原始 1500 条数据 | 28 |
| 2 | 印度电商 App（Flipkart、Amazon India、Myntra、Purplle、AJIO、Nykaa、Shopsy、Snapdeal 等）的 Google Play 公开评论 | <https://github.com/Sravya-T01/ecommerce-sentiment-analysis-distilbert>（`data/reviews.csv`） | 仓库代码为 **MIT License**（© 2025 Sravya-T01）；评论内容为 Google Play 公开数据。仅研究/非商业使用并注明出处 | 29 |
| 3 | Amazon Shopping App 的 Google Play 公开评论 | <https://github.com/dungtran209/Review-Mining-for-Amazon-App-on-Google-CH-Play>（`amazon_data.csv`） | 仓库**未附许可证文件**；Google Play 公开评论（仓库内含抓取 notebook）。仅研究/非商业使用并注明出处 | 5 |
| 4 | 中文在线购物评论语料 `online_shopping_10_cats`（书籍/平板/手机/水果/洗发水/热水器/衣服/计算机/酒店 等 10 类，6 万余条正负向） | <https://github.com/SophonPlus/ChineseNlpCorpus>（`datasets/online_shopping_10_cats/online_shopping_10_cats.zip` 内 CSV） | 仓库**未附许可证文件**；该语料为公开网络购物评论的整理合集，仓库定位为中文 NLP 研究语料。仅研究/非商业使用并注明出处 | 16 |
| 5 | 人工构造“提示注入”对抗探针（**非真实评论**） | 本仓库内联：`authored:injection-01`、`authored:injection-02` | 由本项目编写，用于检验模型是否会被评论文本中的指令劫持；**已明确标注，不参与“真实数据”统计** | 2 |

许可总声明：上述来源均未被明确授权商业使用；本数据集仅用于 VoiceBoard 的研究/教学/作品集评测。
若需对外发布或商用，请先行核对各来源最新许可条款，或替换为有明确再分发许可的数据源。
本仓库不包含任何来源的原始大数据文件，仅保留 80 条抽样文本（去标识后）。

## 抽样方法

不是随机抽样，而是**按类别覆盖 + 难例覆盖**的目标性抽样：

1. **候选池**：从上述来源全量（约 5.3 万条英文 App 评论 + 6.3 万条中文购物评论）中，
   用六类线索词表（物流/支付/质量/搜索推荐/客服/退换货）+ 长度 20–480 字符 + 去重 + 去除含 URL/邮箱/@handle/长数字/PII 的文本 + 要求日期有效，得到候选池；
2. **人工筛选**：逐条阅读候选文本，按 `labeling-guideline.md` 判定主痛点与影响度，并优先选择“单意图清晰”的样本；
3. **难例专项**：单独筛出多意图、反讽/正负混合、代码切换（英印混排）、超短、提示注入样文本；
4. **平衡**：六类各 ≥8（实际 11–13）、待确认 ≥6（实际 8）；
5. **去偏**：同一 App 每类最多取若干条，保证来源/平台多样性（AliExpress、Alibaba、Amazon、Flipkart、Myntra、AJIO、Nykaa、Purplle、Shopsy、Snapdeal、Amazon India、当当中文评论）。

抽样偏差说明：本集是为“痛点分类评测”构造的**覆盖性样本**，**各类比例不代表线上真实反馈分布**（例如真实 App 评论中物流/客服占比通常更高）。

## 去标识处理

- 不包含评论者用户名、头像、用户 ID、设备信息（这些字段未采集）。
- 对文本执行 PII 正则替换：邮箱、`@handle`、电话、7 位以上连续数字、`#订单号` → `[已移除]`；本集 80 条经扫描后**无需替换即已无 PII**（最终文本中无匹配）。
- 保留品牌/平台/承运商名称（如 Xiaomi、PayPal、USPS）——它们是问题描述的一部分，不属个人身份信息。
- 清理了 1 条源文本中的 Unicode 私有区乱码字符（U+E844，源数据编码残渣），未改写语义。
- 未对文本做截断（最长 476 字符）；未做翻译。

## 标注方法

- 标注者：`eval-data`（AI Agent，按本仓库规约逐条人工判读），标注日期：2026-11-02。
- 单标注者、单轮标注；**无**第二标注者、**无**双盲、**未**计算一致性系数。
- 每条均写 `label_note` 说明判定依据；难例标 `【难例·xx】`；注入探针标 `【难例·提示注入（人工构造，非真实评论）】`。
- 详细定义、优先级与边界案例见 `labeling-guideline.md`。

## 元数据推断（必须知道的妥协）

| 字段 | 处理方式 |
| --- | --- |
| `country` | 抓取数据不含评论者国家。按 App 主要市场推断：AliExpress/Alibaba → `多国（跨境）`；Amazon Shopping America → `美国`；印度电商 App → `印度`；中文语料 → `中国`。**不是用户自报** |
| `user_type` | 全部为消费端评论，推断为 `买家`，非自报身份 |
| `product_category` | 按平台/商品类目标注（`跨境B2C电商平台`/`跨境B2B批发平台`/`综合电商平台`/`时尚电商平台`/`美妆电商平台`/`图书`） |
| 中文语料的 `rating` | 语料只提供正/负情感标签，映射 `1→5★`、`0→1★`（**非平台星级**），已在对应 `label_note` 逐条注明 |
| 中文语料的 `created_at` | 语料无逐条时间，统一占位 `2018-01-01`（语料公开年份，**非真实日期**），已逐条注明 |

因此本集**不用于**时间趋势分析、国家分布分析或星级-痛点相关性结论；`golden_impact_level` 为人工直接判定，不依赖 `rating` 推导。

## 校验与复跑

**数据完整性**（2026-11-02 实测）：

```python
import pandas as pd
df = pd.read_csv("evals/feedback_eval_v1.csv", encoding="utf-8", dtype=str)
# shape = (80, 12)；无空值；文本唯一；golden_category 仅 7 类；
# rating / golden_impact_level 均为 1–5 整数；created_at 全部可解析
```

**应用导入兼容**（使用项目自身导入器）：

```python
from src.importer import parse_feedback_csv
preview = parse_feedback_csv(open("evals/feedback_eval_v1.csv", "rb").read())
# records=80, errors=0, duplicate_count=0, can_import=True
```

**规则基线复现**（可解释关键词基线，CPU 秒级）：

```python
import pandas as pd
from src.classifiers.rule import RuleClassifier

df = pd.read_csv("evals/feedback_eval_v1.csv", encoding="utf-8", dtype=str)
clf = RuleClassifier()
pred = [clf.classify(row.to_dict()).category for _, row in df.iterrows()]
gold = df["golden_category"].tolist()
acc = sum(g == p for g, p in zip(gold, pred)) / len(gold)

# 本集实测：类别准确率 48/80 = 60.0%
# 预测分布：待确认 31、退换货 13、搜索推荐 11、商品质量 9、支付 7、物流 5、客服 4
```

**DeepSeek 零样本复跑**：评测脚本在 `evals/results/` 与引擎侧脚本中（由 eval-engine 维护），
需要仓库根目录 `.env` 中的 `DEEPSEEK_API_KEY`。评测时**不要把 `golden_category` / `golden_impact_level` 传给分类器**（标签泄漏）。
建议分别报告：真实集 78 条的类别准确率/宏 F1，以及注入探针 2 条的抗注入通过率。

## 已知偏差与局限

1. **单标注者、无一致性检验**：无法区分标注噪声与模型错误；建议后续双人独立标注 + Cohens κ ≥ 0.7。
2. **负向偏多**：1–2 星占 70/80。这是“痛点分类”评测的合理筛选，但会高估模型在正向/中性反馈上的表现（正向样本少）。
3. **来源可得性偏差**：印度电商 App 评论 29 条、跨境电商 App 28 条；中文部分仅找到公开的**图书/平台**购物评论语料（无公开的中文跨境电商 App 评论集），因此中文样本以图书购买场景为主——这是数据可得性的妥协，已如实记录。
4. **待确认类含技术故障**（App 卡死/闪退/加购异常）：VoiceBoard 六类不覆盖技术问题，标为待确认；这与业务定义一致，但会拉低待确认类的“主题一致性”。
5. **元数据为推断/占位**（见上表），不应用于元数据分析。
6. **英文文本含拼写/语法错误**（原样保留）：模型可能依赖噪声特征；仅 1 条英文含印地语罗马字混排，代码切换样本偏少。
7. **2 条注入探针为人工构造**：不计入真实数据；如评测方只需真实样本，可过滤 `source` 以 `authored` 开头的行。

## 扩展方法（v1 → v2）

1. **加量**：从同源继续按规约抽样至 150–200 条，每类 ≥15，待确认 ≥15；保持 `eval_id` 稳定、新增用 `FB081+`。
2. **补中文/跨境 App 评论**：优先接入中文 App Store/Google Play 评论（如淘宝、京东、SHEIN、Temu、Shopee 中文评论）或公开客服推文（如 Customer Support on Twitter，CC BY-NC-SA 4.0），补齐中文支付/搜索推荐。
3. **双人标注**：两名标注者独立标注 100% 样本，争议仲裁；报告 κ 与不一致案例分析。
4. **难例扩充**：每题 10–20 条多意图/反讽/代码切换/注入变体；注入探针独立成文件（如 `injection_probes_v1.csv`），避免混入真实集统计。
5. **版本化与抽检**：每次扩充记录抽样随机种子与来源快照（repo commit / 抓取日期），保证可复现。

## 引用来源（建议在报告/README 中保留）

```
eval-data (2026). VoiceBoard feedback evaluation set v1 (80 examples).
Sources:
1. nebekisa/ecommerce-app-review-analysis — Google Play reviews of AliExpress/Alibaba/Jiji.
   https://github.com/nebekisa/ecommerce-app-review-analysis
2. Sravya-T01/ecommerce-sentiment-analysis-distilbert (MIT) — Google Play reviews of Indian shopping apps.
   https://github.com/Sravya-T01/ecommerce-sentiment-analysis-distilbert
3. dungtran209/Review-Mining-for-Amazon-App-on-Google-CH-Play — Google Play reviews of Amazon Shopping app.
   https://github.com/dungtran209/Review-Mining-for-Amazon-App-on-Google-CH-Play
4. SophonPlus/ChineseNlpCorpus — online_shopping_10_cats Chinese shopping reviews.
   https://github.com/SophonPlus/ChineseNlpCorpus
5. authored-adversarial prompt-injection probes (this project, clearly labelled, not real reviews).
```
