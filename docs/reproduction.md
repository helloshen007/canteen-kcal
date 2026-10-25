# 从原始数据复现与交付逐图证据

本文命令均在仓库根目录执行。使用 Python 3.12；有 GPU 时可使用与显卡驱动兼容的 PyTorch，否则使用 CPU。完整特征提取在 CPU 上需要较长时间。预先确认磁盘能容纳 Python 环境、三套模型权重和数据缓存。

## 1. 环境与依赖

```bash
python -m venv .venv
# Linux/macOS；Windows PowerShell 的 Python 路径使用 .\.venv\Scripts\python.exe
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install "git+https://github.com/ultralytics/CLIP.git"
```

后续命令中的 `python` 指上述虚拟环境解释器。按需要激活环境，或替换为完整解释器路径。首次推理会下载 YOLO-World、SAM 和 CLIP 权重，不要关闭 TLS、签名或 CLIP 校验。数据下载需要访问 `huggingface.co` 及实际重定向的下载域名；模型还会访问 GitHub releases 和 CLIP 权重源。代理 403 应修正允许的目的域名，不应关闭验证或反复重跑相同请求。

## 2. 固定清单、原图和元数据

```bash
python -m data.prepare
```

该入口读取已提交的 `data/dish_ids.json`，下载固定版本的数据集 `Sebastianrtj/food-nutrients` 的 `metadata.jsonl` 和同一份 60 张原图，保存到已忽略的 `data/raw/`，转换 JPEG 到 `data/images/`。不会重新选择样本或覆盖编号清单。只需原始元数据时可用 `python -m data.prepare --metadata-only`。

兼容入口 `data.fetch_nutrition5k` 已改为使用固定清单，不再重新选样或改写编号；传入不同样本数会报错。`data.fetch_metadata` 下载同一固定版本并校验元数据，但不等同于生成真值。

## 3. 核对标注并生成真值

```bash
python -m data.build_gt
```

该步骤从原始 `metadata.jsonl` 和固定样本清单重新生成 `data/ground_truth.csv`、`data/ingredient_nutrition.csv`。按原始元数据中的食材 ID 修正规范名称；原始 ID 可在元数据和导出的元数据子集中追溯，规则不会仅依赖旧名称；规则见 `data/labels.py`。不能把所有名为 `deprecated` 的食材当作不可见调料，也不能把所有 `deprecated` 全局替换为 watermelon：这个旧名称在源数据中对应不止一种食材 ID。

六张已核对的测试图中的西瓜对应 `ingr_0000000458`。西瓜保留源数据的克数和营养标注，计入可见食材真值；不凭图片重新猜克数。其他未经核验的 deprecated ID 必须保留为待审核，不能静默按零重量、零热量处理。

生成后检查：60 张、40 张标定与 20 张测试的划分保持不变，可见食材词表已更新。标注修正会改变词表、真值、营养表及数据指纹，因此原特征和原预测不能直接算作本次重跑结果。

## 4. 方案 A：重新提特征、标定和评估

使用新的结果目录，避免把旧实验和本次实验混在一起：

```bash
python -m detector.extract --results-root results/revalidated
python -m detector.fit_eval 0.05 --results-root results/revalidated
```

检测 JSON、掩膜 NPZ 在 `features/`；逐图预测在 `yolo_sam/`。提取使用重新生成的共享词表；标定仅使用 calib，不用测试真值拟合面积到重量的系数。0.05 是既有阈值，不在这次测试集上另选一个更好看的阈值。

缓存需匹配当前真值/营养表/词表上下文及原图，缺失掩膜、旧指纹或坏 JSON 不能作为成功缓存跳过。对旧实验做任何清理前应先备份原目录；优先保留两个独立的结果目录。

## 5. 方案 B：配置、单图验证、批量调用和重试

在本地 `.env` 或环境设置中填写实际服务配置：

```dotenv
VLM_PROVIDER=openai
VLM_BASE_URL=https://api.deepseek.com
VLM_MODEL=deepseek-flash
VLM_DISABLE_THINKING=1
VLM_API_KEY=仅在本地填写的密钥
```

服务商名称本身不证明模型支持图像。本轮已通过官方文档和实际接口核实 `deepseek-flash` 支持图片输入，对应 DeepSeek-V4.1-Flash-1017，使用 `https://api.deepseek.com` 并关闭思考模式；详见 `docs/deepseek-service.md`。密钥不入库、不放进证据 ZIP，不出现在录屏中。

```bash
# 首张图一次调用，仍会产生 API 费用
python -m vlm.run_vlm 1 --limit 1 --results-root results/revalidated
# 确认成功后，20 张测试图各重复 3 次
python -m vlm.run_vlm 3 --results-root results/revalidated
```

成功预测应明确记录 `status=success`、`parse_ok=true`、原始 `raw` 回复、实验配置和当前数据上下文。回复解析失败、结构错误或无效重量不保存为“正常零热量预测”。失败/隔离记录与成功文件分开保存到 `vlm/failures/`，其中保留原始回复和安全的错误类别，便于区分 API 失败、解析失败、旧缓存和真正的空食材输出。

修正服务/模型配置或修复失败原因后，重跑相同命令可以重试失败项；不能仅凭文件存在就跳过。旧的“零食材”文件须先用其 raw 回复重新校验；无法证明成功的旧记录应隔离，并重新调用。真值和词表已经变更时，旧的成功 B 缓存也不能当作新实验结果。

## 6. 汇总、核对与证据包

```bash
python -m compare.report --results-root results/revalidated --output results/revalidated/report.md
python tools/export_evidence.py --results-root results/revalidated --output results/revalidated/evidence.zip --include-images
```

报告只统计有效的当前上下文结果；失败、旧缓存、缺失样本与成功结果必须分开说明。缺少 B 原始预测时，不从历史汇总表倒推出逐图结果，也不生成看起来完整的新 A/B 指标。

证据包使用明确的文件白名单：固定清单、真值、营养表、标注规则、原始元数据的固定样本子集（保留源文件哈希）、逐图检测 JSON/NPZ、逐图预测、原始回复和失败记录。`manifest.json` 包含数据指纹、每张测试图的有效/缺失状态、重复次数、原始回复是否存在及每个文件的 SHA-256。特征/预测上下文过期会被标记，不算有效覆盖。`--expected-repeats` 默认 3，可与实际实验重复次数保持一致。

导出可以在实验尚未完整成功时执行，目的是保留诊断证据；命令成功导出 ZIP 不等于两方案实验完成。请查看 manifest 中的 `coverage_complete` 和 `vlm_repetitions_complete`，以及 legacy、invalid、failed、stale_context 等状态。

证据包不包含 `.env`、密钥、模型权重或虚拟环境。脚本会拒收包含非空凭据字段的 JSON。原始模型文本会按原样保留，分享前仍应人工审查其中是否有敏感内容。应同时提交说明使用的模型版本、数据来源/版本、提示词、重复次数、阈值和必要的运行环境信息。

## 7. 验证

```bash
python -m unittest discover -s tests -v
```

回归测试验证数据处理、失败输出、重试和缓存规则，不能替代真实模型运行。新结果必须与本次修正后的真值绑定；历史表仅作为旧实验记录保留，并明确标注其评估口径已经失效的部分。

服务端点会以 SHA-256 摘要加入缓存/实验签名，切换接口地址不会复用同名模型的旧结果，也不在记录中暴露地址内的凭据。

本轮完整复验已完成：A/B 均为 20/20 张，B 60 次真实调用、0 失败；全部 raw 随逐图 JSON 入库。使用 `--results-root evidence/revalidated` 可以不调用 API、仅从已保存证据复算指标。
