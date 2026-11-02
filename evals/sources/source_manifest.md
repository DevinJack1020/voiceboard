# 来源清单与核验说明（feedback_eval_v1）

本文件记录 `evals/feedback_eval_v1.csv` 每一条的来源、许可与可核验方式。
逐条引用写在 CSV 的 `source_ref` 列（格式 `仓库@文件路径:L行号`，行号按“含表头”的文本行计算，与 Excel/VSCode 打开后的行号一致）。

- 数据抓取/快照日期：**2026-11-02**
- 运行环境限制：本机可访问 `github.com` / `codeload.github.com` / `api.github.com` / `cdn.jsdelivr.net` / `gitee.com`；
  `raw.githubusercontent.com` 与 `huggingface.co` 不可访问。因此下载统一使用 **codeload zip** 或 **jsDelivr 单文件** 两种方式（下列命令均可复现）。
- 原始数据不入库：本仓库只保留 80 条去标识抽样；如需复核全文，请按下方命令自行下载原始数据（注意各来源许可与使用边界）。

## 0. 快速核验（推荐）

```bash
# 1) 查看本集全部 source_ref
python -c "import pandas as pd; d=pd.read_csv('evals/feedback_eval_v1.csv',encoding='utf-8'); [print(r.eval_id, r.source_ref) for r in d.itertuples()]"

# 2) 下载全部英文来源（codeload zip）
python - <<'PY'
import urllib.request, zipfile, io, os
urls = {
 "aliexpress": "https://codeload.github.com/nebekisa/ecommerce-app-review-analysis/zip/refs/heads/main",
 "play_shopping": "https://codeload.github.com/Sravya-T01/ecommerce-sentiment-analysis-distilbert/zip/refs/heads/main",
 "amazon_app": "https://codeload.github.com/dungtran209/Review-Mining-for-Amazon-App-on-Google-CH-Play/zip/refs/heads/master",
}
for name, url in urls.items():
    data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "voiceboard-eval-data/1.0"}), timeout=120).read()
    zipfile.ZipFile(io.BytesIO(data)).extractall("raw/" + name)
    print("ok", name)
PY

# 3) 下载中文语料（jsDelivr 单文件）
curl -L -o raw/online_shopping_10_cats.zip \
  "https://cdn.jsdelivr.net/gh/SophonPlus/ChineseNlpCorpus@master/datasets/online_shopping_10_cats/online_shopping_10_cats.zip"
unzip -o raw/online_shopping_10_cats.zip -d raw/

# 4) 按 source_ref 定位原始行（示例：FB001）
sed -n '285p' raw/aliexpress/ecommerce-app-review-analysis-main/cleaned_reviews_data.csv
```

## 1. AliExpress / Alibaba App 的 Google Play 公开评论（28 条）

| 项 | 内容 |
| --- | --- |
| 仓库 | <https://github.com/nebekisa/ecommerce-app-review-analysis> |
| 分支/快照 | `main`（2026-11-02 下载） |
| 数据文件 | `cleaned_reviews_data.csv`（19 列；1500 行：AliExpress 500 / Alibaba 500 / Jiji 500） |
| 获取方式 | `https://codeload.github.com/nebekisa/ecommerce-app-review-analysis/zip/refs/heads/main` |
| 采集方式 | 仓库作者用 Google Play 抓取脚本（仓库内 `scraper.py`）抓取的公开评论；含 `ReviewText`、`Rating`、`ReviewDate`、`AppName` 等字段 |
| 许可 | 仓库**未附 LICENSE 文件**；内容为 Google Play 公开可见用户评论。**仅研究/非商业用途**，使用时须注明来源；不重新分发原始 1500 条数据 |
| 本集使用 | 28 条（AliExpress / Alibaba；不含 Jiji——其属分类信息平台，非电商交易反馈）；`source` 列 = `Google Play · AliExpress/Alibaba App 评论` |

逐条行号（`eval_id→行号`，对应 `cleaned_reviews_data.csv`）：

FB001→L285，FB002→L27，FB008→L257，FB009→L340，FB016→L965，FB018→L136，FB019→L537，FB020→L382，FB022→L790，FB026→L392
FB027→L287，FB028→L129，FB032→L841，FB042→L876，FB044→L484，FB045→L732，FB051→L946，FB052→L796，FB053→L656，FB065→L385
FB066→L493，FB067→L165，FB073→L220，FB074→L355，FB075→L581，FB076→L646，FB077→L661，FB078→L134

## 2. 印度电商 App 的 Google Play 公开评论（29 条）

| 项 | 内容 |
| --- | --- |
| 仓库 | <https://github.com/Sravya-T01/ecommerce-sentiment-analysis-distilbert> |
| 分支/快照 | `main`（2026-11-02 下载） |
| 数据文件 | `data/reviews.csv`（26,764 行；13 列，含 `content`、`score`、`at`、`appID`）；`data/apps.csv`（15 个 App 元数据） |
| 获取方式 | `https://codeload.github.com/Sravya-T01/ecommerce-sentiment-analysis-distilbert/zip/refs/heads/main` |
| 采集方式 | 从 Google Play 抓取的公开评论（15 个 App：Flipkart、Amazon India、Myntra、Purplle、AJIO、Nykaa、Shopsy、Snapdeal、JioMart、bigbasket、Zepto、Blinkit、Swiggy、Domino's、OLX） |
| 许可 | 仓库代码为 **MIT License**（© 2025 Sravya-T01）；评论内容为 Google Play 公开数据。**仅研究/非商业用途**，注明来源 |
| 本集使用 | 29 条，仅取 Shopping 类 App（Flipkart、Amazon India、Myntra、Purplle、AJIO、Nykaa、Shopsy、Snapdeal），**排除**食品/生鲜/分类信息类 App（Domino's、Swiggy、Zepto、Blinkit、bigbasket、OLX）；`source` 列 = `Google Play · 印度电商 App 评论` |

逐条行号（`eval_id→行号`，对应 `data/reviews.csv`）：

FB004→L23558，FB005→L12914，FB007→L256，FB014→L20388，FB015→L19130，FB021→L18703，FB029→L177，FB030→L18106
FB031→L23646，FB033→L3464，FB034→L4511，FB037→L23041，FB038→L13614，FB039→L358，FB040→L157，FB046→L2198，FB047→L16456
FB048→L6367，FB049→L11734，FB050→L13249，FB054→L3225，FB055→L6605，FB056→L18849，FB060→L7247，FB061→L14682
FB062→L8789，FB063→L18521，FB064→L8717，FB068→L21615

> 行号对应下载时的仓库快照；若上游仓库后续更新，行号可能漂移，可用 `feedback_text` 前 40 字符全文检索定位。

## 3. Amazon Shopping App 的 Google Play 公开评论（5 条）

| 项 | 内容 |
| --- | --- |
| 仓库 | <https://github.com/dungtran209/Review-Mining-for-Amazon-App-on-Google-CH-Play> |
| 分支/快照 | `master`（2026-11-02 下载） |
| 数据文件 | `amazon_data.csv`（4,000 行；4 列：`Name`、`Date`、`Rate`、`Comment`） |
| 获取方式 | `https://codeload.github.com/dungtran209/Review-Mining-for-Amazon-App-on-Google-CH-Play/zip/refs/heads/master` |
| 采集方式 | 仓库内 notebook 抓取的 Amazon Shopping App Google Play 公开评论 |
| 许可 | 仓库**未附 LICENSE 文件**；Google Play 公开评论。**仅研究/非商业用途**，注明来源 |
| 本集使用 | 5 条；`source` 列 = `Google Play · Amazon Shopping App 评论` |

逐条行号（`eval_id→行号`，对应 `amazon_data.csv`）：

FB003→L1485，FB006→L395，FB017→L231，FB041→L64，FB043→L42

## 4. 中文在线购物评论语料 `online_shopping_10_cats`（16 条）

| 项 | 内容 |
| --- | --- |
| 仓库 | <https://github.com/SophonPlus/ChineseNlpCorpus> |
| 分支/快照 | `master`（2026-11-02 下载） |
| 数据文件 | `datasets/online_shopping_10_cats/online_shopping_10_cats.zip` → 解压后 `online_shopping_10_cats.csv`（62,774 行；3 列：`cat`、`label`、`review`） |
| 获取方式 | `https://cdn.jsdelivr.net/gh/SophonPlus/ChineseNlpCorpus@master/datasets/online_shopping_10_cats/online_shopping_10_cats.zip` |
| 内容 | 10 类中文在线购物评论（书籍、平板、手机、水果、洗发水、热水器、蒙牛、衣服、计算机、酒店），正/负向各约 3 万；`label=1` 正向、`0` 负向 |
| 许可 | 仓库**未附 LICENSE 文件**；该仓库定位为中文 NLP 研究语料合集，数据整理自公开网络。**仅研究/非商业用途**，注明来源 |
| 本集使用 | 16 条（全部来自“书籍”类，因该类评论最常含物流/售后/退款等平台环节描述）；`source` 列 = `中文购物评论语料 online_shopping_10_cats` |
| 元数据妥协 | 语料**无星级、无日期**：`rating` 由 `label` 映射（1→5★ / 0→1★），`created_at` 统一占位 `2018-01-01`（语料公开年份），均已在 CSV `label_note` 逐条注明 |

逐条行号（`eval_id→行号`，对应解压后的 `online_shopping_10_cats.csv`）：

FB010→L115，FB011→L116，FB012→L312，FB023→L2427，FB024→L2817，FB025→L3617，FB035→L223，FB036→L2178，FB057→L2234
FB058→L2572，FB059→L2568，FB069→L2111，FB070→L2172，FB071→L2571，FB079→L48，FB080→L1693

## 5. 人工构造的提示注入对抗探针（2 条，非真实评论）

| 项 | 内容 |
| --- | --- |
| 文件 | `authored:injection-01`（FB013，真实诉求=物流丢件，注入内容要求输出“支付”）、`authored:injection-02`（FB072，真实诉求=退款未到，注入内容要求输出“商品质量”） |
| 来源 | 本项目（eval-data）编写，**不是**任何公开数据集的真实评论 |
| 用途 | 检验分类器是否会被反馈文本中的指令劫持；同时验证中英混合注入 |
| 边界 | 不计入真实数据；评测报告中应单列“抗注入”指标；只需真实样本时可过滤 `source` 以 `authored` 开头的行 |
| 许可 | 项目内原创，随本仓库分发 |

## 6. 许可与再分发边界（汇总）

1. 四个真实来源均**未明确授权商业使用**；本评测集仅用于 VoiceBoard 的研究/教学/作品集演示。
2. 本仓库不提交任何来源的原始大数据文件，只保留 80 条去标识抽样文本；请勿将本集用于训练商业模型或再分发原始数据。
3. 若需对外发布，请先核对各来源最新许可；或替换为有明确再分发许可（如 CC0/CC-BY）的数据源。
4. 使用本集时建议保留 `source` / `source_ref` 列及本文件，以便上游可追溯。
