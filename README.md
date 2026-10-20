# 食堂餐盘识别 + 热量估算(减脂打卡助手)

同一问题:输入食堂餐盘照片 + 目标(减脂/维持/增肌),输出每道菜的名称、重量、热量、三大营养素和膳食建议。
三种方案并排对比:**A** YOLO+SAM(传统) · **B** 多模态大模型 · **C** 融合(A 提供位置与量,B 负责校正与说明)

## 流程
A: YOLO 检测(含餐盘) → SAM 框提示分割 → 面积占比 × 餐盘直径换真实面积 → ×堆积高度×密度得重量 → 查 `dish_nutrition.csv`(含油量系数) → 规则建议
B: 图片 + 提示词(三种写法可对比) → JSON → 解析并统一格式
C: A 的结果作为上下文喂给 B

## 运行
```bash
pip install -r requirements.txt
python -m tests.test_logic                 # 逻辑单测(无需模型)
python train/train_yolo.py                 # 标注好数据后微调
export VLM_PROVIDER=anthropic VLM_API_KEY=xxx VLM_MODEL=xxx   # 方案B;Windows 用 set
python -m compare.run_batch --repeat 5     # 批量跑三种方法
python -m compare.evaluate                 # 对比表
python app.py                              # Gradio 并排界面
```
## 目录
`data/` 图片、标注、营养表、真值 · `train/` 微调 · `detector/` 方案A · `vlm/` 方案B · `hybrid/` 融合 · `compare/` 评估 · `docs/` 文档截图

> 营养表数值为占位估计,需对照《中国食物成分表》核对;建议仅供参考,不构成医疗建议。
