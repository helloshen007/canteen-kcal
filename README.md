# 餐盘食材与热量估算：传统检测分割 vs 多模态大模型

同一组 Nutrition5k 餐盘图片，比较 YOLO-World＋SAM 与多模态大模型输出的食材、重量及热量。两方案共用修正后的词表、营养表和测试集。

## 当前修正与证据状态

- 固定 60 张图，前 40 张标定、后 20 张测试；划分未改变。
- 按食材 ID 核对六张测试图：`ingr_0000000458` 为可见西瓜，不能因原名称 `deprecated` 而排除。另一个同名 ID 并非同一类，不能全局替换。
- 词表为 **24 类**，测试集为 **15 张单一食材、5 张多食材**。详细原图、标注来源与修正差异见 [标注审计](docs/annotation-audit.md)、[六图对照](docs/annotation-contact-sheet.jpg)、[逐图修正 CSV](docs/annotation-corrections.csv)。映射有人工核对依据，未冒称已访问被阻断的官方 GCS 原表。
- 错误 JSON、缺字段、未知食材、非法重量均视为失败，不保存成“无食材、零热量”。只有显式的 `{"items":[]}` 可作为成功空预测。失败回复单独保留，下次运行会重试；过期缓存隔离保存。
- 真值、营养表、词表和图片变化会使旧缓存失效。成功预测记录上下文、原始回复、模型、提示词和耗时。失败不参与指标，也不当作零预测。
- 原汇总表已移到 [历史存档](docs/historical-results.md)，不得用于当前性能结论。方案 B 的原始预测/回复当前缺失，不能从汇总表还原或编造。

修正后的真实 A 复验：[新结果表](docs/results.md)、[40 行逐图状态/误差](docs/results.per-image.csv)、[60 份 A 逐图预测与运行记录](evidence/revalidated/README.md)。全部 20 张测试图的 F1=0.2450、热量 MAE=62.16 kcal；B 覆盖为 0/20，尚不构成完整 A/B 比较。

## 方案与限制

A：英文食材词表 → YOLO-World 检测 → 跨类别 NMS → 检测框提示 SAM → 同类掩膜并集 → 标定集估计像素/克系数 → 共用营养表。

B：多模态服务只输出闭集食材名与克数 → 校验 JSON → 用同一营养表换算营养。服务必须支持图像输入，不能仅根据服务商名称推断模型能力。

图片为固定环境的俯拍子集，不能外推至真实中式食堂。两种方法都是估重而非称重。历史阈值 0.05 曾参考测试集选择；本轮修复沿用它以避免新增调参，并未消除原方法学局限。严格后续实验应在标定集选择阈值，再冻结测试。

## 完整复现

建议 Python 3.12，在项目根目录运行。CPU 可以运行 A，但完整提取较慢。先创建虚拟环境并安装依赖；如无需 GPU，可先从官方 CPU 源安装 torch/torchvision。

```bash
python -m venv .venv
# Linux/macOS 激活；Windows 使用 .venv\Scripts\activate
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install 'git+https://github.com/ultralytics/CLIP.git'

# 固定版本下载全部原图与 metadata.jsonl，校验元数据，不改 dish_ids.json
python -m data.prepare
# 显式生成经 ID 修正的真值及营养表
python -m data.build_gt

# 新实验目录，保留旧结果以供审计
python -m detector.extract --results-root results/revalidated
python -m detector.fit_eval 0.05 --results-root results/revalidated

# 复制 .env.example 为 .env，在本地/环境设置中填写真实配置，不提交密钥
# 先做单图单次调用（产生 API 费用）
python -m vlm.run_vlm 1 --limit 1 --results-root results/revalidated
# 确认服务正常后，20 张测试图各运行 3 次（产生 API 费用）
python -m vlm.run_vlm 3 --results-root results/revalidated

# 默认要求两方案全部测试图有有效结果，不覆盖历史表
python -m compare.report --results-root results/revalidated --output results/revalidated/report.md
# 仅复验 A 时可明确生成部分报告：会列出缺失 B，不伪装完整比较
python -m compare.report --results-root results/revalidated --allow-partial --output results/revalidated/partial-report.md

python app.py --results-root results/revalidated
python -m unittest discover -s tests -v
```

`.env` 由 `vlm` 包加载，现有环境变量优先。`VLM_PROVIDER` 使用 `openai` 或 `anthropic`，还需 `VLM_API_KEY` 和准确的 `VLM_MODEL`；OpenAI 兼容服务填写 `VLM_BASE_URL`。服务明确支持 `thinking.type=disabled` 时才设置 `VLM_DISABLE_THINKING=1`。失败日志不保存 HTTP 异常正文，避免回显密钥；原始模型文本共享前仍应检查敏感信息。

成功记录为 `vlm/<image_id>_rN.json`，展示副本为 `<image_id>.json`；无效旧缓存和失败请求在 `vlm/failures/`。只有输出、数据版本和实验配置均通过校验才跳过调用。更换模型或提示词、重建标注后，建议改用独立结果目录。

详细环境、数据、模型和故障说明见 [复现文档](docs/reproduction.md)。初次模型权重下载需联网，保留 TLS 及模型内置校验。

## 逐图结果与原始回复

本轮真实 A 复验结果和标注版本将存入 `evidence/revalidated/`，包括逐图预测、逐图评估和缺失状态，不只保留汇总表。B 缺失时明确留空，不附虚假的回复。全部模型特征和原图可从数据准备脚本及完整证据 ZIP 恢复。

```bash
python tools/export_evidence.py --results-root results/revalidated --output results/revalidated/evidence.zip
```

导出包仅包含白名单预测、原始回复、失败记录及复算材料，manifest 列明成功/失败/缺失。默认不包含密钥、`.env`、权重或虚拟环境。数据导出不等于实验成功，指标以经过校验的当前版本结果为准。

原项目介绍及个人感悟见 [文档说明](docs/文档说明.md)，其中旧实验数字已明确标记为历史。估算仅供参考，不构成医疗或膳食建议。

服务端点会以 SHA-256 摘要加入缓存/实验签名，切换接口地址不会复用同名模型的旧结果，也不在记录中暴露地址内的凭据。
