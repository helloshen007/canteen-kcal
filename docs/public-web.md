# 公网入口：Hugging Face Docker Space（需平台授权）

公网发布目标为 Hugging Face Spaces。它能提供外部浏览器可直接访问的 HTTPS 应用地址，无需自行购买和管理服务器。2026-10-29 核对官方文档：新建 Docker / Gradio Space 需要个人 PRO 或组织 Team/Enterprise 计划；CPU Basic 无小时硬件费不代表创建 Docker Space 无订阅费用。静态 Space 免费，但不能运行本项目的后端及模型。请先确认并授权平台费用，再配置发布凭据。官方说明：https://huggingface.co/docs/hub/spaces-overview 。当前尚未绑定发布账号，不能把准备好的部署文件称为已上线网站。

发布程序会将已入库代码复制到仓库外的临时目录，生成 Docker Space 配置，在镜像构建期间下载并校验模型，使用一个容器运行 nginx、API、Redis 和 worker。公网端口为 7860。模型密钥、账号数据库和本机会话文件不会进入上传内容。现有 Compose 部署继续保留。

## 账号与授权

1. 在 https://huggingface.co/join 注册账号并完成邮箱验证；创建 Docker Space 还需平台支持的付费计划，购买由账号所有者自行决定和操作。
2. 在 https://huggingface.co/settings/tokens 创建可创建自己 Space 的 Write 令牌。
3. 通过当前会话的安全环境设置配置 `HF_TOKEN`，不要在聊天或 GitHub 中发送令牌。

获得授权后，在项目根目录执行：

```bash
python deploy/spaces/publish.py
```

程序默认创建公开 Space `canteen-kcal`，遇到已存在的同名 Space 会停止，避免覆盖其他项目。创建后还要等待平台构建成功，并检查真实公网地址、注册登录与任务返回；构建未完成时不应将链接当成可用网站交付。

若仅检查上传包，无需任何令牌：

```bash
python deploy/spaces/publish.py --prepare-only /tmp/canteen-space-review
```

在 Space 的 Settings → Secrets 中单独配置真实 `VLM_API_KEY`，并设置原项目的 `VLM_PROVIDER`、`VLM_BASE_URL`、`VLM_MODEL` 与 `VLM_DISABLE_THINKING`。不要把当前云环境的代理占位密钥复制过去。历史回放不调用 API；实时方案 B 需要平台内实际可用的服务密钥，会产生费用。

实例可能休眠，临时磁盘在重建或重启时可能清空，因而账号、照片和历史记录不能作为长期可靠存储。该入口适合课堂与客户演示；需要长期保存记录时，使用持久存储或原 Linux Compose 部署。网页登录请使用 Space 的独立应用网址，避免 iframe 中的跨站 cookie 限制。
