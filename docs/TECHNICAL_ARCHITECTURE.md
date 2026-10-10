# POD 图片去重与归档管理系统：技术架构与运行说明

> 本文描述当前仓库已经运行的实现，而非未来设想。业务规则以 [SPEC.md](SPEC.md) 为准；其中“精确重复可自动处理、视觉相似默认保守”的规则优先于任何模型或阈值说明。

## 1. 一句话概览

系统使用三层能力处理图片：

```text
输入图片
  │
  ├─ 精确指纹：SHA-256 + 解码后的像素摘要
  │      └─ 命中时可按规则自动删除本次文件
  │
  └─ 视觉向量：DINOv2 ViT-S/14 → 384维单位向量
         └─ FAISS IndexIDMap2(IndexFlatIP) Top-K 候选
                └─ MySQL/实际文件状态复核 → 人工审核或强校验
```

**FAISS 只负责快速找相似候选，不能单独决定删除。** MySQL 中的任务、文件操作、人工审核和持久化向量才是事实记录；真实文件仍由受限的安全文件操作模块处理。

## 2. 进程、服务与“关机后是否还在”

### 2.1 当前启动的组成

| 组件 | 启动方式 | 是否 Windows 服务 | 关机/终端关闭后 | 磁盘上保留什么 |
|---|---|---:|---|---|
| MySQL 5.7.40 | Windows `MySQL57` 服务 | 是 | 进程会停止；若服务设为自动启动，开机后会自行恢复 | 数据库数据、表、任务、操作审计、向量原始数据 |
| 后端 API | `scripts/start_api.ps1` → Uvicorn | 否 | 进程退出；下次需重新运行脚本 | 无常驻内存状态；数据库仍在 |
| Worker | `scripts/start_worker.ps1` → Python | 否 | 进程退出；下次需重新运行脚本 | 任务检查点、操作证据、FAISS 索引文件仍在 |
| 前端开发服务器 | `scripts/start_frontend.ps1` → Vite | 否 | 进程退出；下次需重新运行脚本 | `node_modules` 与构建缓存仍在 |
| DINOv2 / FAISS | 被 Worker 进程按需加载的 Python 库 | 否 | 内存中的模型和索引释放 | 模型权重、Torch 缓存、FAISS `.index` 文件仍在 |

结论：**向量模型和 FAISS 不是 Windows 服务，也不是一直后台运行的独立程序。** Worker 需要做视觉检索时才会将 DINOv2 模型载入内存；Worker 结束或电脑关机后内存释放。模型权重和索引文件仍保留在磁盘，下次启动 Worker 后会再次载入或重建。

MySQL 也会在关机时停止；区别在于它已注册为 Windows 服务，是否开机自启由 Windows 服务启动类型决定。API、Worker、前端目前均未注册为 Windows 服务或计划任务。

### 2.2 启动时实际发生的事情

```powershell
.\scripts\bootstrap.ps1      # 校验根目录 .env，按 uv.lock 安装/同步 Python 依赖
.\scripts\start_api.ps1      # 执行 Alembic 迁移，再启动 FastAPI/Uvicorn
.\scripts\start_worker.ps1   # 启动任务轮询、恢复中断文件操作、按需执行去重
.\scripts\start_frontend.ps1 # 启动 Vue/Vite 开发服务器
```

`bootstrap.ps1` 不会启动模型、FAISS 或后台服务。DINOv2 使用本地 Torch Hub 仓库和已安装的权重；当前代码在运行时找不到本地权重会明确报“视觉能力未就绪”，不会静默下载或使用随机向量。

## 3. 当前安装的软件与库

### 3.1 系统与运行时

| 项目 | 当前角色 |
|---|---|
| Windows 10/11 x64 | 本地运行环境与文件系统 |
| Python 3.12.x | 后端、Worker、模型推理 |
| `uv` | 锁定并同步 Python 依赖 |
| MySQL 5.7.40 | 任务、审计、图片元数据、向量原始数据持久化 |
| Node.js / npm | Vue 前端开发与构建 |

### 3.2 后端直接依赖（当前虚拟环境实测版本）

下表是项目直接声明的后端依赖和当前安装版本；完整的间接依赖由 [backend/uv.lock](../backend/uv.lock) 锁定。

| 库 | 当前版本 | 用途 |
|---|---:|---|
| `fastapi` | 0.115.14 | HTTP API |
| `uvicorn` | 0.32.1 | ASGI API 服务器 |
| `pydantic` / `pydantic-settings` | 2.13.5 / 2.15.0 | 请求、配置校验 |
| `sqlalchemy` | 2.0.54 | ORM 与数据库事务 |
| `pymysql` | 1.2.3 | MySQL 驱动 |
| `alembic` | 1.14.1 | 数据库迁移 |
| `pillow` | 11.3.0 | 图片解码、EXIF 方向归一化、像素摘要、裁剪 |
| `opencv-python-headless` | 4.14.0.94 | ROI 边缘、轮廓、ORB/RANSAC 本地验证 |
| `numpy` | 2.5.3 | 向量和图像数组计算 |
| `torch` | 2.7.1 | DINOv2 本地推理 |
| `faiss-cpu` | 1.15.1 | 本地向量索引与近邻检索 |
| `tzdata` | 2026.4 | 时区数据 |
| `httpx` | 0.28.1 | 开发/集成测试 HTTP 客户端 |
| `pytest` / `pytest-cov` | 8.4.2 / 6.3.0 | 测试与覆盖率 |

查看完整 Python 环境而不修改任何内容：

```powershell
Push-Location backend
uv pip list
Pop-Location
```

### 3.3 前端依赖（当前 `npm ls --depth=0`）

| 库 | 当前版本 | 用途 |
|---|---:|---|
| `vue` | 3.5.43 | 前端界面 |
| `vue-router` | 4.6.4 | 页面路由 |
| `pinia` | 2.3.1 | 状态管理 |
| `element-plus` | 2.14.6 | 管理界面组件 |
| `axios` | 1.20.0 | 调用后端 API |
| `vite` | 6.4.3 | 前端开发服务器与构建 |
| `typescript` | 5.6.3 | 类型检查 |
| `vue-tsc` | 2.2.12 | Vue 类型检查 |
| `@vitejs/plugin-vue` | 5.2.4 | Vite Vue 编译支持 |
| `@element-plus/icons-vue` | 2.3.2 | UI 图标 |

## 4. 精确去重：SHA-256 与 `pixel_digest`

实现文件：[backend/app/storage/fingerprint.py](../backend/app/storage/fingerprint.py)。

### 4.1 SHA-256：字节完全相同

```python
content = hashlib.sha256(path.read_bytes()).digest()
```

它回答的是：“这两个文件的每一个字节是否完全相同？”改名或移动不影响结果；JPEG 再压缩、修改元数据、重新保存都会使其不同。

### 4.2 `pixel_digest`：视觉像素完全相同

```python
with Image.open(path) as image:
    normalized = ImageOps.exif_transpose(image).convert("RGBA")
    payload = f"{normalized.width}x{normalized.height}:RGBA".encode() + normalized.tobytes()
    digest = hashlib.sha256(payload).digest()
```

它回答的是：“这两张图片在校正方向并统一颜色模式后，尺寸和每个像素是否完全相同？”

- 能识别不同文件编码、但解码像素完全一致的图片。
- 能消除 EXIF 旋转差异。
- 不会将缩放、裁剪、加水印、重压缩后有像素误差的图片当作精确重复。
- SHA-256 与 `pixel_digest` 任一命中，才进入精确重复处理。

精确删除前，`safe_ops.py` 会再次读取当前文件并核验 SHA-256、大小、mtime；动作前还会持久化 `file_operations` 记录和缩略图证据。实际移动、复制、永久删除只允许在 [backend/app/storage/safe_ops.py](../backend/app/storage/safe_ops.py) 中执行。

## 5. 向量模型：本地 DINOv2 ViT-S/14

核心实现：[backend/app/dedup/common/embedding.py](../backend/app/dedup/common/embedding.py)。

### 5.1 当前模型和预处理

| 项目 | 当前实现 |
|---|---|
| 模型 | `facebook/dinov2_vits14` |
| 模型版本标识 | `dinov2_vits14_pretrain` |
| 向量维度 | 384 |
| 输入 | RGB 图片 |
| 尺寸 | 双三次插值缩放至 `224×224` |
| 标准化 | ImageNet RGB mean/std |
| 输出 | float32 向量，L2 归一化 |
| 推理方式 | PyTorch 本地推理，不调用云端图片 API |

关键逻辑如下：

```python
image = image.convert("RGB").resize((224, 224), Image.Resampling.BICUBIC)
tensor = torch.from_numpy(values.transpose(2, 0, 1)).float().unsqueeze(0)
with torch.inference_mode():
    vector = model(tensor).cpu().numpy().reshape(-1).astype(np.float32)
return vector / np.linalg.norm(vector)
```

向量不是“图片指纹”。它是模型对图片视觉内容的数值表达：相似构图、图案、主体或风格通常会更接近，但不能保证同款，也不能作为唯一删除依据。

## 6. FAISS：本地向量索引，而不是向量数据库服务

核心实现：[backend/app/indexing/faiss_store.py](../backend/app/indexing/faiss_store.py)。

当前索引构造：

```python
faiss.IndexIDMap2(faiss.IndexFlatIP(dimension))
```

含义如下：

| 组件 | 含义 |
|---|---|
| `IndexFlatIP` | 精确暴力内积搜索；不采用近似搜索，不牺牲召回率换速度 |
| `IndexIDMap2` | 为每条向量绑定稳定的 `image_features.id`，检索结果可回查 MySQL |
| L2 归一化 | 已归一化的向量内积等于余弦相似度 |
| Top-K | 默认取最相近 20 条作为候选池 |

索引文件按向量范围保存到可配置数据目录，例如：

```text
data/faiss/SOURCE_FULL/facebook_dinov2_vits14.index
data/faiss/SOURCE_PRINT/facebook_dinov2_vits14.index
data/faiss/POD_FULL/facebook_dinov2_vits14.index
```

这些 `.index` 是磁盘文件，关机后仍存在；但 FAISS 没有单独服务进程。Worker 读取或重建这些文件后，在自己的内存中搜索。

### 6.1 为什么还要把向量存进 MySQL

每条特征保存在 `image_features`：

```text
image_id + feature_scope + region_seq
+ model_id + model_revision + preprocess_version
+ dimension + vector_blob + vector_sha256 + faiss_vector_id
```

作用：

1. FAISS 索引损坏可从 MySQL 的 `vector_blob` 重建。
2. 换模型时可让新旧向量共存，不覆盖历史特征。
3. 检索结果会回查图片记录，确认模型版本、有效状态、文件角色和实际文件存在。
4. 因此失效、手动删除或移动的文件不会仅因旧 FAISS 结果而被当成有效历史图。

检索复核代码在 [backend/app/dedup/common/retriever.py](../backend/app/dedup/common/retriever.py)：FAISS 返回 feature ID 和分数，随后 MySQL/文件系统过滤出仍为 `PRESENT` 的合法候选。

## 7. 三条视觉检索路线

| 向量范围 | 输入 | 对比目标 | 主要用途 |
|---|---|---|---|
| `SOURCE_FULL` | 来源整图 | 历史来源整图 | 相同场景、相近构图候选 |
| `SOURCE_PRINT` | 来源图中的印花 ROI | 历史来源印花 ROI | 不同场景下相同印花候选 |
| `POD_FULL` | POD 成品整图 | 历史 POD 主文件 | POD 相似设计候选 |

来源图 ROI 定位实现见 [backend/app/dedup/source/roi.py](../backend/app/dedup/source/roi.py)：当前是保守的 OpenCV 内容区域算法，不是通用商品检测模型。它执行灰度化、Canny 边缘、形态学闭运算、轮廓筛选，并要求候选区域具备合理面积、中心位置和纹理密度。ROI 无法可靠定位时会记录 `ROI_UNAVAILABLE`，随后只走整图候选路线。

## 8. 候选、审核与删除之间的边界

### 8.1 来源图

1. 先做 SHA-256 / `pixel_digest` 精确判定。
2. 不精确重复时，DINOv2 + FAISS 从整图和 ROI 路线召回候选。
3. 相似度达到默认候选阈值 `0.85` 时记录候选证据。
4. 默认不因视觉候选删除。
5. 若明确打开来源视觉自动删除，还必须同时满足：VLM 判定同图、印花区域有效、无重要新增细节、ORB/RANSAC 本地印花对应验证有效、规则已标记验证通过。

核心服务：[backend/app/services/source_dedup.py](../backend/app/services/source_dedup.py)。

### 8.2 POD 图

1. 冻结待处理目录清单，避免运行中新增文件混入旧任务。
2. 先做成品比例保护；不同输出比例不会跨比例自动删除。
3. 精确重复可自动删除，并留下操作证据。
4. DINOv2/FAISS 相似候选创建人工审核；候选不自动删除。
5. 审核完成后，将保留图归档为 POD 主文件，再安全复制分类副本。

核心服务：[backend/app/services/pod_dedup.py](../backend/app/services/pod_dedup.py)。

## 9. 是否能换更好的模型

**可以，但当前不是修改一个环境变量就能完成。** 现有数据模型已经按 `model_id`、`model_revision`、`preprocess_version`、`dimension` 隔离特征；这为新旧模型并存、双索引对比和回滚提供了基础。

当前限制：实际运行时 [embedding.py](../backend/app/dedup/common/embedding.py) 固定使用 `LocalDinoV2Embedder` 和 `dinov2_vits14`。配置中的 `EMBED_MODEL_ID` 目前是配置预留项，尚未连接成可动态选择不同模型的工厂。

### 9.1 推荐的安全升级方式

1. **建立标注集**：从已审核任务抽取“同设计”和“不同设计”图片对，按来源图、POD、不同比例、文字变化等类别标注。
2. **新增适配器，不替换旧模型**：例如增加 DINOv2 ViT-B/14、SigLIP 2 或经过领域验证的印花模型；每个适配器声明自己的输入预处理、输出维度和模型版本。
3. **独立命名空间和索引**：新模型写入新特征行、新 FAISS 文件；不得覆写旧的 384 维 DINOv2 S/14 向量。
4. **批量回填历史图库**：为历史来源与 POD 主文件生成新向量，并完整重建新索引。
5. **影子评估**：同一批任务同时比较旧/新模型的 Top-K 召回率、人工审核确认率、误报率、GPU/CPU耗时。
6. **分阶段启用**：先只将新模型结果展示为候选；达到项目定义的精度后，才调整候选阈值。不要因为模型更大就扩大自动删除范围。

### 9.2 可选方向与取舍

| 方向 | 潜在收益 | 代价 / 注意事项 |
|---|---|---|
| DINOv2 ViT-B/14 | 比 S/14 更大的视觉骨干，768维特征 | 约 8,600 万参数；推理、回填和索引占用更高 |
| DINOv2 ViT-L/14 | 更强视觉表征 | 约 3 亿参数；对本机 GPU/内存压力更大 |
| SigLIP 2 | 图文语义、文字与商品属性候选可能更有帮助 | 必须为本项目图片对做评测；不应仅凭通用基准替换 |
| 多尺度 ROI 向量 | 对局部印花、文字和裁剪变化更稳健 | 候选数量、索引大小和评估复杂度增加 |
| 专门的商品/印花检测器 | ROI 更接近真实商品印花区域 | 需要额外模型、标注和误检评估 |

模型尺寸或通用基准更好，不等于对本项目的“同印花/不同文字/不同成品比例”更准确。升级必须以本系统的人工审核结果为准。

## 10. 运维检查命令

```powershell
# MySQL 服务状态
Get-Service MySQL57

# 后端健康检查（API 已启动时）
Invoke-WebRequest http://127.0.0.1:8000/api/v1/health

# 查看直接安装的 Python 包
Push-Location backend
uv pip list
Pop-Location

# 查看前端顶层依赖
Push-Location frontend
npm ls --depth=0
Pop-Location
```

不要把 `.env` 内容、MySQL 密码、VLM Key、真实图片目录或用户图片提交到仓库、测试输出或文档中。

## 11. 关键代码地图

| 主题 | 文件 |
|---|---|
| 指纹与删除前重核验 | [backend/app/storage/fingerprint.py](../backend/app/storage/fingerprint.py)、[backend/app/storage/safe_ops.py](../backend/app/storage/safe_ops.py) |
| DINOv2 向量提取 | [backend/app/dedup/common/embedding.py](../backend/app/dedup/common/embedding.py) |
| FAISS 索引 | [backend/app/indexing/faiss_store.py](../backend/app/indexing/faiss_store.py) |
| 特征持久化与索引重建 | [backend/app/indexing/feature_store.py](../backend/app/indexing/feature_store.py)、[backend/app/indexing/reconcile.py](../backend/app/indexing/reconcile.py) |
| 候选检索后的有效性复核 | [backend/app/dedup/common/retriever.py](../backend/app/dedup/common/retriever.py) |
| OpenCV ROI | [backend/app/dedup/source/roi.py](../backend/app/dedup/source/roi.py) |
| 来源去重 | [backend/app/services/source_dedup.py](../backend/app/services/source_dedup.py) |
| POD 去重、审核、归档 | [backend/app/services/pod_dedup.py](../backend/app/services/pod_dedup.py)、[backend/app/api/reviews.py](../backend/app/api/reviews.py) |
| 任务 Worker | [backend/app/workers/runner.py](../backend/app/workers/runner.py) |
| 数据模型 | [backend/app/models/images.py](../backend/app/models/images.py)、[backend/app/models/tasks.py](../backend/app/models/tasks.py) |
