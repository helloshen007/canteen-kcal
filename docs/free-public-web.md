# 不购买托管：在自己的 Windows 电脑上对外演示

该方案不订阅服务器，不调用付费 DeepSeek：YOLO/SAM 和 Ollama 的 Qwen2.5-VL 均在自己的电脑运行，使用 Cloudflare Quick Tunnel 尝试生成临时 HTTPS 入口。当前会话尚未生成可交付的公网网址；必须在实际运行的电脑上建立入口并用外部浏览器验证后，才算上线。

## 准备

- Windows x64 电脑，建议 16GB 以上内存，Docker 可用内存建议至少 8GB；首次下载镜像和模型需要数 GB 磁盘与流量。
- 安装并启动 Docker Desktop（个人学习用途按其官方免费使用条件）。Compose 需要 2.24.4 或更新版本。
- 下载本仓库 ZIP；如 Windows 标记下载文件，先在 ZIP 属性中解除锁定，再解压到普通文件夹。

双击仓库根目录的 `start-free-web.bat`。脚本会检查 Docker 和内存，启动独立的 `canteen-free` 项目，下载并验证 YOLO/SAM/CLIP，下载本地视觉模型，并取得 Cloudflare 官方 Windows 客户端；客户端需与官方发布的 SHA-256 一致才能执行。不会修改已有付费部署或将 DeepSeek 密钥传给免费实例。

免费入口连接成功时，窗口会显示实际 `https://…trycloudflare.com` 地址。复制那个真实地址，用手机关闭 Wi-Fi 后访问，测试注册、上传与返回结果，再发给客户。不要把本机地址或 GitHub 仓库链接当作该公网地址。客户端连接失败时没有可用公网链接，不应编造一个。

## 范围

电脑和脚本窗口必须保持运行、联网且不休眠。关闭入口或重新启动后地址可能变化；第三方免费临时入口没有长期可用保证。Quick Tunnel 是否可连接还取决于当前网络。此云环境访问其 API 已收到代理 403，所以没有在此环境强行绕过网络限制。

免费配置将 API 和 worker 明确改为 Docker 内的 `http://ollama:11434/v1`。`ollama-local` 只是本地 SDK 的兼容占位值，不是收费 API 密钥。实时分析使用不同于原 DeepSeek 实验的本地模型，速度、准确度及结构化输出成功率不能沿用原实验指标；CPU 上可能需要等待几分钟。历史样例仍明确标为回放。

停止全部免费实例（保留记录和模型）：

```powershell
docker compose -p canteen-free -f compose.yaml -f deploy/free/compose.yaml stop
```

当前已检查 Compose 合并结果、免费端点隔离及原 53 项测试；Windows 启动脚本和实际公网连接仍需在用户 Windows 电脑验证。不要将“脚本已准备”描述为“公网网站已发布”。
