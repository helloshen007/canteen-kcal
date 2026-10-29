# Canteen Lab：第三阶段 Web 应用

二阶段的 `app.py` 是已保存结果的 Gradio 对照页面；第三阶段入口为 `web.api:app`，可上传新图片、在后台运行两种方案，并按账号保存记录。

开发环境使用 Python 3.12，在仓库根目录安装 `requirements.txt` 和原项目 CLIP 依赖。Web 页面无需 Node.js，也不依赖外部字体服务。

```bash
python -m pip install -r requirements.txt
python -m pip install 'git+https://github.com/ultralytics/CLIP.git@7ffa84b3bfa40c42ecc1c77147a855e69cb2dd40'
# 仅在本机回环地址开放开发 Redis
docker run --name canteen-dev-redis -p 127.0.0.1:6379:6379 -d redis:7-alpine
# 三个独立终端，均在仓库根目录
uvicorn web.api:app --host 127.0.0.1 --port 8000
python -m web.worker
python -m unittest discover -s tests -v
```

先在浏览器访问端口 8000，注册账号，再点击样例即可体验真实历史结果回放。回放不需要模型权重或 API 密钥；仍经过数据库、Redis 和 worker。上传新图片始终执行实时分析，需要另外准备本地模型与服务器端多模态配置：

```bash
python -m web.prepare_models
# 在本地 .env 或系统环境中配置 VLM_*，不要提交 .env
```

默认本地持久化目录为 `var/`，默认模型目录为 `models/`，均已忽略。可用 `CANTEEN_STATE_DIR`、`CANTEEN_MODEL_DIR` 和 `REDIS_URL` 覆盖。API 文档位于 `/docs`，OpenAPI 定义位于 `/openapi.json`。密钥不会返回给浏览器。

主要接口：注册/登录/退出，上传创建任务、读取任务、分页历史、修改标题备注、删除完成记录、仅重试失败方案，以及私有原图/分割图读取。JWT 使用 HttpOnly、SameSite=Strict cookie；退出时撤销当前用户已发出的令牌。用户名不区分大小写，每个账号同时最多三个未完成任务。数据库仅存加盐 PBKDF2 密码哈希。

实时处理会把照片按比例缩放并补边至 640×480，A/B 接收完全相同的 PNG。该尺寸沿用原俯拍数据的标定尺度，不能保证任意拍摄角度、厚度或盘子大小下的重量准确。A 使用冻结的标定系数；B 只输出食材与克数，由同一营养表换算热量。失败保留为失败，结果字段保持空值，不填零。

内置三张样例的图片、原预测和原始回复来自 `evidence/revalidated` 对应实验；照片来源为 Nutrition5k 的固定 HF 镜像。样例目录仅用于明确标记的历史回放，不计作新推理或新指标。
