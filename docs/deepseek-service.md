# DeepSeek 视觉服务配置

本轮核对的官方 API 模型 ID 为 **`deepseek-flash`**，对应服务版本 **DeepSeek-V4.1-Flash-1017**。`DeepSeek V4.1 Flash` 是展示名称，不直接用作 API 模型 ID。

## 非秘密配置示例

将以下内容填写到环境设置或本地 `.env`。密钥留在安全设置中，不提交到仓库，也不放入聊天、日志或截图。

```dotenv
VLM_PROVIDER=openai
VLM_BASE_URL=https://api.deepseek.com
VLM_MODEL=deepseek-flash
VLM_API_KEY=
VLM_DISABLE_THINKING=1
```

官方文档确认 `deepseek-flash` 支持图片输入。当前代码使用标准 OpenAI Chat Completions 格式，在 `user` 消息的内容数组内发送 `image_url`，其中 URL 为本地 JPEG 的 base64 data URL；无需特殊 `/beta` 端点。本项目 640×480 图片低于官方的尺寸和请求体限制。

服务端思考模式默认开启。本项目对该官方 DeepSeek 接口默认关闭思考，显式 `VLM_DISABLE_THINKING=0` 可以恢复；本轮通过 `thinking.type=disabled` 关闭思考，避免小输出预算被推理过程占用；对应本项目的配置是 `VLM_DISABLE_THINKING=1`。图片保留默认 detail，不使用会将图像缩小到 512×512 的 `low` 模式。

## 复现与当前验证范围

```bash
# 一张测试图、一次调用；会产生 API 费用
python -m vlm.run_vlm 1 --limit 1 --results-root results/revalidated
# 完整实验：20 张测试图，每张重复 3 次；会产生 API 费用
python -m vlm.run_vlm 3 --results-root results/revalidated
```

单图实际调用已验证成功，随后完整 20 图 × 3 次实验也已完成：60 次成功、0 次失败。每次原始回复、模型配置和数据指纹随逐图 JSON 一并保留，结果见 `docs/results.md` 与 `evidence/revalidated/vlm/`。本轮 B 的 F1 为 0.9889、热量 MAE 为 17.38 kcal、同图热量标准差均值为 10.4 kcal。

`deepseek-flash` 是可随服务升级而改变后端的模型别名。复现实验时应重新核对官方模型表，并保留当时的服务版本、原始回复与本次结果。旧别名 `deepseek-v4-flash` 和 `deepseek-v4-flash-vision-exp` 虽仍被兼容接受，其旧模型已退役；不能据此把历史汇总表视为本轮实测结果。

## 官方依据

- [首次调用说明](https://api-docs.deepseek.com/)：API 模型 ID 与当前 Flash 服务版本。
- [模型与价格表](https://api-docs.deepseek.com/quick_start/pricing)：Flash 支持 Vision，Pro 不支持。
- [Vision 指南](https://api-docs.deepseek.com/guides/vision)：标准 OpenAI 兼容图片消息、base64 方式及输入限制。
- [Chat Completions 参数](https://api-docs.deepseek.com/api/create-chat-completion)：`thinking`、`reasoning_effort` 和 `max_tokens` 语义。

程序只在 `api.deepseek.com` 上将已核实的展示名称 `DeepSeek V4.1 Flash` 转换为 API ID `deepseek-flash`，不会在其他服务商接口猜测模型名。
