# 部署与运维

本项目当前支持在 Windows 本机或已挂载 NAS 的 Windows 执行端运行。它默认只监听 `127.0.0.1`，不包含 Docker、云部署、多机 Worker 或公网访问方案。

## 1. 环境要求

- Windows 10/11 x64。
- Python 3.12。
- [uv](https://docs.astral.sh/uv/)。
- Node.js 与 npm。
- MySQL 5.7.40，Windows 服务名默认是 `MySQL57`。
- 可访问的本地磁盘或已挂载 NAS 路径；运行 API 的 Windows 用户必须具备目标目录的读取、移动、复制与删除权限。

MySQL 5.7 没有 `SKIP LOCKED`，因此同一个数据库只能运行一个 Worker 实例。

## 2. 首次安装

1. 复制环境变量模板：

   ```powershell
   Copy-Item .env.example .env
   ```

2. 编辑 `.env`，仅填写本机 MySQL 连接和需要的默认目录。不要把 `.env`、数据库密码、VLM Key、真实图片路径或图片文件提交到 Git。

3. 同步后端 Python 依赖：

   ```powershell
   .\scripts\bootstrap.ps1
   ```

4. 安装前端依赖（`start_all.ps1` 也会在缺失时执行此步骤）：

   ```powershell
   Push-Location frontend
   npm install
   Pop-Location
   ```

5. 确认数据库服务已运行：

   ```powershell
   Get-Service MySQL57
   ```

   若状态为 `Stopped`，请以管理员身份运行 PowerShell 后执行 `Start-Service MySQL57`。

## 3. 启动与停止

建议从资源管理器双击项目根目录的 `启动系统.cmd`。它会调用 `scripts/start_all.ps1`，保留状态窗口，并为 API、Worker 与前端分别打开日志窗口。

也可从 PowerShell 执行：

```powershell
.\scripts\start_all.ps1
```

启动成功后访问：<http://127.0.0.1:5173>。

健康检查地址：<http://127.0.0.1:8000/api/v1/health>。

如需重新加载本项目的 API、Worker 和前端：

```powershell
.\scripts\start_all.ps1 -Restart
```

关闭 API、Worker、前端对应的日志窗口即可停止它们；这不会停止 MySQL。不要同时运行多个 Worker。

## 4. 数据与备份

需要备份的内容包括：

- MySQL 数据库：任务、审核记录、文件操作审计、图片元数据和向量；
- `DATA_DIR`（默认 `data/`）：缩略图证据和 FAISS 索引；
- 历史来源图库与历史 POD 图库中的实际原图及生产裁切结果；
- 本机 `.env`，应存放在受控的私密备份中，而不是 Git 仓库。

恢复时应先恢复 MySQL 和图片目录，再恢复 `DATA_DIR`。如果 FAISS 索引不可用，可从已持久化的向量重建索引；不要因索引缺失而跳过人工审核或降低删除保护。

## 5. 更新项目

在确认本地没有未提交工作后：

```powershell
git pull
.\scripts\bootstrap.ps1
Push-Location frontend
npm install
npm run build
Pop-Location
```

更新可能包含数据库迁移；下一次启动 API 时会执行 `alembic upgrade head`。建议在更新前备份数据库与图片目录，并先在隔离环境验证。

## 6. 安全运行边界

- `safe_ops.py` 是唯一允许执行真实移动、复制或永久删除的模块。
- 删除前会保存操作记录与缩略图证据，并重新核验 SHA-256、文件大小和修改时间。
- 默认仅精确重复可自动删除；视觉相似只用于候选召回和人工审核。
- `Production/` 是派生裁切结果，不作为 POD 原图历史库的去重输入。
- 不要将 API 监听地址直接暴露到公网；如有局域网访问需求，须先完成认证、授权、路径隔离和安全评估。
