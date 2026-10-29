# 样例图片、预测与数据来源

内置三张照片来自 **Nutrition5k**（Quin Thames、Arjun Karpur、Wade Norris、Fangting Xia、Liviu Panait、Tobias Weyand、Jack Sim，CVPR 2021）。官方项目：[google-research-datasets/Nutrition5k](https://github.com/google-research-datasets/Nutrition5k)，论文：[Nutrition5k: Towards Automatic Nutritional Understanding of Generic Food](https://arxiv.org/abs/2103.03375)。

官方 README 的 “License & Contact” 将全部数据按 **Creative Commons Attribution 4.0（CC BY 4.0）** 发布：[授权条款](https://creativecommons.org/licenses/by/4.0/)。本项目的样例图片、派生分割图及包含这些图片的截图/演示视频沿用该数据来源声明，不代表原作者为本应用或模型结果背书。

本轮使用 HF 镜像 `Sebastianrtj/food-nutrients`，固定版本 `bb00a088f5b963635da23711766af90e25b9f4a9`。原 `test/<dish_id>.png` 由二阶段数据准备流程转为 RGB JPEG；`overlay.jpg` 叠加了项目实际检测框、文字与 SAM 掩膜。`a.json` / `b.json` 来自已保存的真实二阶段结果，未从汇总数字反推。

| 样例 | 可见真值食材 |
|---|---|
| `dish_1558027001` | 西瓜 |
| `dish_1558028194` | 培根、西瓜、土豆 |
| `dish_1558028772` | 西瓜、蜜瓜、哈密瓜 |

`catalog.json` 保存原图 SHA-256 与来源。本目录仅供明确标注的历史回放使用；新上传走实时推理。更多 ID 修正与元数据依据见 [标注审计](../../docs/annotation-audit.md)。模型、CLIP 及其他依赖分别遵循上游许可证，权重不随 Git 仓库分发。
