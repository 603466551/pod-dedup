# 贡献指南

感谢参与。该项目会移动、复制或永久删除用户的本地图片，因此任何改动都必须以“误删保护优先”为原则。

## 开发环境

请先按照 [部署与运维](docs/DEPLOYMENT.md) 完成 Python、Node.js、MySQL 和 `.env` 配置。不要使用生产数据库或真实图片目录运行测试。

## 验证命令

后端测试必须指向隔离的测试数据库：

```powershell
$env:MYSQL_TEST_DATABASE_URL = 'mysql+pymysql://test_user:CHANGE_ME@127.0.0.1:3306/pod_dedup_test?charset=utf8mb4'
Push-Location backend
uv run alembic upgrade head
uv run pytest -q
Pop-Location
```

前端构建：

```powershell
Push-Location frontend
npm run build
Pop-Location
```

## 提交要求

- 先阅读 [业务规格](docs/SPEC.md)。其中 F01—F13、“必须”、“不得”和验收规则优先。
- 不提交 `.env`、密钥、真实路径、用户图片、数据库转储、模型缓存或构建产物。
- 修改文件行为时，真实移动、复制、永久删除只能由 `backend/app/storage/safe_ops.py` 执行。
- 业务行为变更必须补充或更新自动化测试。
- 保持改动小且可审阅；提交说明应描述用户可见影响和验证方式。
- 视觉模型的分数或单次 VLM 回答不得单独触发永久删除。
