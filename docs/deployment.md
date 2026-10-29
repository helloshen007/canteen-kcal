# Linux 与 Docker 部署

在 Linux 云环境实际运行 nginx、FastAPI、RQ worker 与 Redis 四个容器。Dockerfile 默认安装 CPU PyTorch，不依赖显卡；页面无需前端构建，也无需外部字体服务。建议至少 4 GiB 内存，推荐 8 GiB 及以上，并为镜像、模型和数据保留 10 GiB 以上空间。若 Docker 使用 vfs 驱动，构建快照会占更多空间，建议预留 30 GiB；本轮实际清理了本项目旧镜像及构建缓存后继续验证，未删除数据卷。

## 启动可体验的应用

先在 Linux 安装 Docker Engine 与 Compose v2，安装方法见 [Docker 官方文档](https://docs.docker.com/engine/install/)。在可使用 Docker 的普通用户下执行：

```bash
git clone https://github.com/helloshen007/canteen-kcal.git
cd canteen-kcal
cp .env.example .env
docker compose up --build -d
docker compose ps
```

浏览器访问宿主机的 8080 端口。默认只绑定回环地址；若运行在远程服务器，可从个人电脑通过 SSH 转发：

```bash
ssh -L 8080:127.0.0.1:8080 用户名@服务器地址
```

然后在电脑浏览器访问本机 8080 端口。注册账号后点击首页样例，即可体验经 Redis、worker、数据库返回的历史双方案对比；该路径不需要模型下载或 API 密钥。

## 打开实时模型分析

下载并核验三份官方模型资源，写入持久化模型卷：

```bash
docker compose run --rm worker python -m web.prepare_models
docker compose exec -T worker python -m web.prepare_models --verify-only
```

下载源与本轮权重 SHA-256 位于 `web/model-manifest.json`；首次下载约 0.75 GB。准备命令保持 HTTPS 和摘要校验，下载失败不会把半份文件当作有效权重。若已在本地保存同一权重，可复制进模型卷后执行核验，不能只按文件名判断版本一致。

在本地 `.env` 填写真实 `VLM_API_KEY`，确认服务和模型配置。本轮使用：

```dotenv
VLM_PROVIDER=openai
VLM_BASE_URL=https://api.deepseek.com
VLM_MODEL=deepseek-flash
VLM_DISABLE_THINKING=1
```

重新运行 `docker compose up -d`，Compose 会将修改后的配置应用到服务。不要把密钥写进命令行、Git、截图或视频，也不要把可能展开密钥的完整 `docker compose config` 输出公开。

工作台显示双方案已配置后，上传一张新照片，点击“开始双方案分析”。这会实际执行 YOLO-World＋SAM 并调用大模型，产生 API 费用。服务就绪信息只检查配置和本地文件存在性，真实可用性由一次完整任务验证。

## 目录、数据卷与权限

| 项目 | 容器位置 | 说明 |
|---|---|---|
| state 卷 | `/app/var` | SQLite、上传图片、分割图、失败原文、持久化会话密钥 |
| models 卷 | `/app/models` | YOLO、SAM、CLIP 权重和下载结果 |
| queue 卷 | `/data`（Redis） | AOF 持久化，保留未消费任务 |
| tmpfs | `/tmp` | 临时缓存，容器退出后无需保留 |

API 与 worker 使用 UID/GID 1000；nginx 使用 UID/GID 101。应用和代理的根文件系统只读，写入仅发生在数据卷或 tmpfs。API 的模型卷只读，worker 可准备权重。API、Redis 端口不发布到宿主机，只有 nginx 入口发布。默认 SQLite + 单 worker 的布局适合本项目规模。

`docker compose down` 保留命名卷，下次启动会恢复账号、记录、图片和会话密钥。`down -v` 会删除卷中的数据，仅在明确要重置环境时使用。备份应同时保留数据库和 `state/jobs`，并妥善保管其中的照片、密码哈希及会话密钥；这些内容不应作为公开代码证据上传。

## 公网入口与 HTTPS

默认 SSH 转发即可远程演示。若使用自有域名公开服务，在服务器的 TLS 入口配置证书，再反向代理到回环地址 8080；设置 `.env` 中 `COOKIE_SECURE=1` 并重建服务配置。外层 nginx 的主要转发项如下，域名及证书路径需要替换为自己的：

```nginx
server {
    listen 443 ssl;
    server_name 你的域名;
    ssl_certificate /你的证书路径/fullchain.pem;
    ssl_certificate_key /你的证书路径/privkey.pem;
    client_max_body_size 11m;
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

容器中的 nginx 保留 HTTPS 转发信息，FastAPI 据此处理同源校验和 cookie。若只有临时测试环境，可用 `APP_BIND=0.0.0.0` 暴露测试端口；公开登录服务应配置 HTTPS。

## 云环境代理与受信任证书

普通网络无需额外设置。本轮云环境的 HTTP(S) 代理有自有信任根，需要让 Docker 构建及 worker 访问相同的已授权代理。项目支持可选 BuildKit secret：

```bash
docker build --secret id=build_ca,src=/已受信任的CA文件 \
  --build-arg HTTP_PROXY --build-arg HTTPS_PROXY --build-arg NO_PROXY \
  -t canteen-kcal:stage3 .
```

如果代理主机名只在开发环境内解析，还需要在私有 Compose override 中配置 `build.extra_hosts` 和运行时 `extra_hosts`；worker 的代理环境应将 `redis,api,worker,nginx,localhost,127.0.0.1` 加入 NO_PROXY。本轮临时网络配置放在工作区之外，未把环境专用代理地址、CA 文件或凭据加入仓库。不要用 `curl -k`、关闭证书验证或修改模型内置摘要检查来绕过问题。

## 检查运行与排错

```bash
docker compose ps
docker compose logs --tail 50 api worker nginx
docker compose exec -T api python -m unittest discover -s tests -v
python tools/smoke_web.py
```

最后一条需本机 Python 安装 httpx，默认只创建临时测试账号并走历史回放，验证实际 nginx/API/队列、用户隔离与记录操作，不发起模型请求。显式添加 `--live` 才会上传样例并调用模型，产生费用。

| 现象 | 排查方向 |
|---|---|
| 页面提示后台服务不可用、任务排队 | 查看 Redis/worker 健康状态及 `docker compose logs --tail 50 worker` |
| A 提示模型未准备 | 执行模型准备和 `--verify-only`；检查模型卷路径和 UID 权限 |
| B 提示未配置或回复失败 | 在服务器本地核对 VLM 配置；更正后重试失败方案，保留原失败回复 |
| 任务超时或容器中断 | 读取任务状态；失败项可重试，已成功的方法保留，队列中未领取任务可在恢复后继续消费 |
| 登录后写入被拒绝 | 检查浏览器 Origin、nginx Host/X-Forwarded-Proto 与 HTTPS 配置是否一致 |
| 首次构建或下载被代理拒绝 | 检查目标域名、受信任 CA 及容器代理解析，不关闭 TLS |

代码更新后使用 `git pull`、`docker compose up --build -d`。旧的二阶段 Gradio 演示仍可按原复现文档单独启动，与此 Web 入口独立。
