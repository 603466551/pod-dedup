# POD 图片去重与归档管理系统

完整且优先的业务规则见 [docs/SPEC.md](docs/SPEC.md)。本仓库已实现 M1–M6 的可运行基础闭环：三个持久任务、精确 SHA/像素去重、安全文件操作、POD 原图主库与按需生产裁切、DINOv2/FAISS 候选、来源 ROI 双图库召回、可配置 VLM、人工审核、目录占用锁和审计。

> 本项目是面向 Windows 本地电脑或已挂载 NAS 的图片管理工具，不是云端 SaaS，也不会上传图片到第三方去重服务。

## 文档导航

- [使用手册](docs/USAGE.md)：日常操作、审核和裁切生产素材。
- [部署与运维](docs/DEPLOYMENT.md)：环境要求、安装、启动、更新与备份。
- [技术架构](docs/TECHNICAL_ARCHITECTURE.md)：技术选型、模型、索引和安全边界。
- [业务规格](docs/SPEC.md)：F01—F13、目录合同和验收规则；与其他文档冲突时以此为准。
- [贡献指南](CONTRIBUTING.md)：本地开发、测试和提交要求。

## 项目结构

```text
pod-dedup/
├── backend/                 FastAPI API、后台 Worker、数据库迁移和 Python 测试
│   ├── app/                 业务服务、去重/索引、数据模型及受限文件操作
│   ├── migrations/          Alembic 数据库迁移
│   └── tests/               单元测试与 MySQL 集成测试
├── frontend/                Vue 3 + TypeScript 管理界面
├── docs/                    使用、部署、技术架构和业务规格
├── scripts/                 Windows PowerShell 初始化与启动脚本
├── .env.example             可提交的环境变量模板（不含真实凭据）
├── 启动系统.cmd             供 Windows 资源管理器双击的一键启动入口
└── README.md                项目入口说明
```

## 已验证环境

- Windows、`uv`、Python 3.12、Node/npm。
- MySQL **5.7.40**（用户明确指定的兼容目标）。该版本没有 `SKIP LOCKED`，Worker 必须保持单实例。
- DINOv2 ViT-S/14 权重已在本机 Torch 缓存中验证，输出 384 维向量；FAISS 使用 CPU `IndexIDMap2(IndexFlatIP)`。

## 安装与启动

1. 复制 `.env.example` 为 `.env`，填写本机 MySQL 连接和允许浏览的图库根目录。不要提交 `.env`、密钥或真实图片。
2. 执行迁移与依赖安装：

```powershell
.\scripts\bootstrap.ps1
```

3. 分别启动 API、Worker 与前端：

```powershell
.\scripts\start_api.ps1
.\scripts\start_worker.ps1
.\scripts\start_frontend.ps1
```

也可以一键启动（首次缺少依赖时会安装；需要强制同步依赖时添加 `-SyncDependencies`）：

```powershell
.\scripts\start_all.ps1
```

若从 Windows 资源管理器启动，请双击根目录的 `启动系统.cmd`。它会保留启动状态窗口和 API、Worker、前端各自的日志窗口，避免启动错误一闪而过。

已有服务需要重新加载代码时，使用 `./scripts/start_all.ps1 -Restart`。默认模式不会中断已在运行的服务。

路径输入框既可手动粘贴绝对路径，也可点击“浏览文件夹”打开运行 API 的本机 Windows 原生文件夹选择器。

页面按「工作台 / 任务与审核 / 系统」分区。来源流程只需要“本次来源文件夹 + 历史源图库”；直接下载的 MJ POD 流程只需要“POD 待处理目录 + 历史 POD 图库”。新任务会自动打开实时进度页（2.5 秒轮询）。在“系统 → 运行日志与诊断”可下载不含真实路径、图片名或密钥的诊断 JSON，便于排错。

默认服务只监听 `127.0.0.1`。健康检查：`http://127.0.0.1:8000/api/v1/health`。

## 安全与行为边界

- 真实移动、复制、永久删除只由 `backend/app/storage/safe_ops.py` 执行。删除前会持久化操作记录和缩略图证据，并在动作前重新核验 SHA、大小、mtime。
- 字节或像素精确重复可自动删除本次文件；视觉向量、ROI、VLM 都只用于召回与证据。复杂视觉自动删除默认关闭。
- POD 待处理目录在任务创建时被持久锁接管，直到审核完成并归档；首次扫描的冻结清单持久化，稍后放入的文件不会被旧任务偷纳入。相同目录的第二任务返回 `409 TASK_RESOURCE_BUSY`。
- 来源整理与 POD 归档会把成功处理的文件统一命名为 `YYYYMMDDHHmmSSsss.ext`；同一毫秒出现不同内容时使用 `_1`、`_2` 避让。POD 分类副本与主文件保持同名。
- “仅检测模式”会产生 `WOULD_DELETE`、`WOULD_MOVE`、`WOULD_ARCHIVE` 结果，但不调用任何真实文件动作。
- POD 视觉候选进入人工审核；最后一条审核关闭后统一移动未裁切主文件。需要特定比例时，在独立生产素材流程按文件名日期（`YYYYMMDD`）范围居中裁切，结果写入 `Production/比例/执行日期/`；可动态新增比例。
- VLM 只有在 `VLM_ENABLED=true` 且 Base URL、模型、密钥齐全时才会发送请求；请求实际携带两张图片，调用审计不保存密钥。未配置、超预算或失败时保守降级。
- `GET/PUT /api/v1/settings` 管理新任务设置；密钥只能写入，读取时显示为已配置。`POST /api/v1/indexes/rebuild` 和 `/reconcile` 均返回后台任务，由 Worker 重建索引。

## 测试

后端集成测试只能使用隔离库，绝不能使用生产库：

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

## 当前限制

- OpenCV ROI 定位是保守的内容区域候选器，不是通用商品检测器；不满足可靠门槛时会记 `ROI_UNAVAILABLE` 并只用整图召回。
- DINOv2 运行在已验证的 CPU 路径；xFormers 未安装只影响性能，不影响结果。
- VLM 没有在本仓库中配置外部密钥，因此只验证了请求构造和结构化响应校验，未对第三方服务发起真实调用。
