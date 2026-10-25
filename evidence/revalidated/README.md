# 当前标注版本的真实逐图证据

此目录包含实际重跑的 60 份方案 A 预测（40 calib / 20 test），不是合成测试夹具。

- `yolo_sam/`：60 份明确成功、带数据上下文的逐图预测。
- `calibration.json`：仅用 40 张标定图拟合的系数与配对数。
- `yolo_sam_per_image.csv`：20 张测试图的预测热量、真值及误差。
- `yolo_sam_summary.json`：全体与难度子集指标。
- `run.json`：数据指纹、软件版本、运行命令及覆盖范围。
- 六图标注依据：`docs/annotation-audit.md` 和 `docs/annotation-corrections.csv`。

**方案 B 的逐图预测/原始回复当前没有提供，本目录不包含推测或补造的回复。** 原先汇总表不是原始证据；本轮 A 指标也不能与原先 B 数字混作同一批新实验。

不需要模型权重或密钥即可从此目录复算 A 的部分报告：

```bash
python -m compare.report --results-root evidence/revalidated --allow-partial --output results/revalidated/from-versioned-evidence.md
```

完整检测框/分割掩膜与原始图像可通过 README 的固定数据准备、提取步骤复现，也可随完整证据 ZIP 一起交付。生成 ZIP 的命令见 README；导出 manifest 明确区分成功、失败、过期与缺失，列出文件哈希。导出成功不等于两方案全部成功。

本次 A 复验：F1 0.2450，热量 MAE 62.16 kcal，基线 MAE 70.69 kcal。旧阈值选择的方法学局限仍在，未通过重选测试集阈值美化结果。28 项回归测试、60 张图特征提取、20 张真实界面回调及修正西瓜图的 Gradio API 检查均已完成。B 调用未执行，缺少原始回复与准确模型配置。
