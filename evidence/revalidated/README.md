# 当前标注版本的完整 A/B 逐图证据

本目录保存修正标注后的真实运行结果，不是合成测试夹具，也不是从历史汇总表倒推的数字。

- `yolo_sam/`：60 份 A 逐图预测，40 calib / 20 test。
- `vlm/*_r0.json` 至 `*_r2.json`：20 张测试图各 3 次，共 60 份 B 预测，每份都有原始 `raw` 回复、数据指纹、图片 SHA、模型/提示词/端点摘要和耗时。
- `vlm/<image_id>.json`：20 份 r0 展示副本，不作为额外调用或额外样本统计。
- `calibration.json`：仅用标定集拟合的 A 系数与配对。
- `yolo_sam_per_image.csv`、`yolo_sam_summary.json`：A 的逐图误差与汇总。
- `run.json`：环境版本、运行命令、模型版本来源、覆盖范围及局限。
- `manifest.json`：完整证据包的覆盖、重复次数、文件状态和哈希清单。
- `docs/results.per-image.csv` 和 `docs/results.json`：两方案 40 个图/方法单元的误差与完整报告。

## 本轮结果

| 方案 | 测试图 | F1 | 重量MAE(g) | 热量MAE(kcal) |
|---|---:|---:|---:|---:|
| A YOLO-World＋SAM | 20 | 0.2450 | 65.80 | 62.16 |
| B DeepSeek V4.1 Flash | 20，每图3次 | 0.9889 | 17.90 | 17.38 |

B API ID 为 `deepseek-flash`，运行时官方文档标明服务版本 DeepSeek-V4.1-Flash-1017，思考关闭，max_tokens=1500。60 次实际调用全部成功，失败记录为 0。同图重复热量标准差均值为 10.40 kcal，基线 MAE 为 70.69 kcal。正式模型文档见 `docs/deepseek-service.md`。

无需模型权重、原图或 API 密钥即可从这些文件复算完整报告：

```bash
python -m compare.report --results-root evidence/revalidated --output results/revalidated/from-versioned-evidence.md
```

原图、掩膜和原始元数据复算材料可通过 README 的固定数据步骤或完整证据 ZIP 取得。33 项回归测试通过，60 份真实 B 回复已重新解析并与逐图预测比对；断点重跑只复用有效缓存。历史阈值选择局限仍保留，不将模型服务版本变化或标注修正后的结果冒充为原历史实验。
