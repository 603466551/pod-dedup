# POD 图片去重与归档管理系统

**Codex 最终开发规格 · V1.0 · 2026-09-20**  
**状态：需求已确认，可直接作为实施基线。**  
**优先级：本文件中「必须 / 不得 / 验收」高于代码中的默认行为；示例数据不是固定业务阈值。**

> 致 Codex：请按本文件逐阶段实现**真实可运行的软件**，不要只生成原型页面、伪算法或 TODO。完成每个里程碑后实际运行测试并报告结果；不得自行改变文件移动、删除、人工审核和分类归档规则。遇到第三方模型/网络环境无法使用时，提供可运行的降级路径并明确标记「视觉能力未就绪」，不得以模拟的相似度/假VLM结果声称完整 V1 已交付。

## 0. 已由用户最后确认的决策（冲突时以本节为准）

| 编号 | 最终规则 |
|---|---|
| F01 | **POD 分类目录日期取本批实际开始归档的本地日期**，不是来源采集日期或首次任务创建日期；同一归档批次只取一次日期，跨午夜、宕机恢复不变。默认时区 `Asia/Shanghai`，设置项可改。 |
| F02 | **不同输出比例是不同生产版本**：即使核心印花相同，也要保留，不跨比例自动删除；可以记录同款关系。用户认为正常操作中几乎不会混入，系统仍需保护。 |
| F03 | **来源图与 POD 在实际整理/归档时统一重命名**为执行端本地时间 `YYYYMMDDHHmmSSsss.ext`；同一毫秒目标已被不同内容占用时加 `_1`、`_2` 避让。生产裁切图沿用原始 POD 主文件最终名称；外部原文件名保留在任务与文件操作审计中。 |
| F04 | 视觉上同款但新旧 POD **分辨率或清晰度明显不同**时，不能默认删除新图；进入人工审核，人工决定留哪张。字节完全一致、像素完全一致且没有重要版本差异时，自动删除本次新图。 |
| F05 | 来源图「**同核心印花、不同场景**」如果有可靠证据且**没有新增重要设计细节**，允许按经过验证的高确定规则自动删除新来源图，以节省抠图 Token；不能确定时保留。 |
| F06 | `POD待处理/` 是循环使用的**临时工作目录**。同一个目录同一时刻只能由一个未结案的 POD 去重/归档任务接管；任务开始冻结本批文件清单，不把后续新文件偷纳入旧任务。 |
| F07 | 首页 **三个独立按钮**：`开始来源去重`、`整理已处理来源图`、`开始POD去重`；点击第三个按钮时**自动先做一次来源整理**。 |
| F08 | 外部 AI 抠图工具继续负责图片生成；成功来源图被外部工具移入 `本批/已处理/`，失败仍在本批目录。新系统 V1 不调用图片生成模型，AI抠图页面仅预留入口。 |
| F09 | POD 去重完成后，疑似重复**统一人工审核**；本批最后一条审核结束即**自动统一归档**，无需「确认归档」。等待人工的任务不阻塞其它**不共用被占用目录**的任务。 |
| F10 | 用户不要求回收站；确认删除就是**永久删除**。必须先持久化判断证据、缩略图、操作记录，再核验文件身份并删除。不能保证恢复已删高清原图。 |
| F11 | POD 图片流程（MJ 直入）不选择比例：去重/审核通过的待处理 POD 全部先**移动**到图库根目录，作为未裁切的原始主文件；待处理目录正常清空。`Production/` 目录不得作为历史 POD 原图扫描或去重对象。 |
| F13 | POD 裁切与生产素材：按历史 POD 主文件名的 `YYYYMMDD` 日期范围筛选，居中裁切到目标比例，不拉伸、不缩放、不修改原图、不做二次去重；结果独立写入 `Production/比例/执行日期/`。比例列表可由用户动态新增，例如 `2:3`。 |
| F12 | 复杂视觉自动删除遵循**保守模式**。初次安装默认仅精确同文件/像素可自动删除；实现可配置并经样本验证后启用的高确定视觉删除规则。相似度数字或 VLM 单次回答不独自触发永久删除。 |

---

## 1. 产品定义、现有流程、范围

### 1.1 项目一句话

本地/已挂载 NAS **场景来源图片 → 去重 → 现有 AI 抠图软件 → POD 原图去重入库 → 人工审核 → 按需裁切生产素材** 的 Web 管理工具，核心是保守、可追溯、可持续改进的「同款 POD 印花」判重，而不是普通整图相似照片清理。

### 1.2 用户日常操作

```text
源图/260920/ 新采集图片
  → 新系统【开始来源去重】
  → 现有 AI 工具：输入 源图/260920/；输出 POD待处理/
      成功来源 → 源图/260920/已处理/；失败来源 → 源图/260920/ 顶层
  → 新系统【开始POD去重】
      自动整理已处理来源 → POD 本批内部+历史去重
      → 疑似重复统一人工审 → 自动归档
  → Photoshop 批量套图与上架（系统 V1 不处理）
```

用户可以随时独立点【整理已处理来源图】，无需等待 POD 去重。

### 1.3 V1 必须交付

真实的三个按钮、目录浏览、持久任务、来源去重与已处理整理、POD 原图去重、本批内部去重、两库辅助来源检索、核心印花区域判别、可配置 VLM、人工审图、自动归档、按范围居中裁切生产素材、动态比例列表、历史增量索引、操作审计、错误重试、基础统计、可运行测试。

### 1.4 V1 不做

AI 图像**生成** API、多模型生成接力、自动采集、定时全链路、PS 套图、自动上架、复杂素材搜索与领取、图片质量综合打分、反馈后即时微调大模型、网盘上传式去重、微服务/多机分布式 Agent。AI抠图页面仅占位并提示继续使用现有工具。

### 1.5 验收中的重要用语

- `DONE`：该任务承诺的实际文件操作已落地，相关数据库与索引可查询。
- `PARTIAL_COMPLETED`：本轮可处理项已完成，但存在个别失败/未处理项；不谎报全成功。
- `WAIT_REVIEW`：本轮自动检测结束，部分 POD 必须由用户决定；本任务暂不开始统一分类复制。
- `VISUAL_UNAVAILABLE`：模型未安装、VLM未配或超限，降级保留，不允许把「只做Hash」显示成完整视觉去重。

---

## 2. 文件夹合同（不得擅自调整）

### 2.1 来源图库

```text
D:\POD\源图\
├── 早期源图A.jpg                   # 已完成AI、已归档，平铺在根目录
├── 早期源图B.png
├── 260920\                         # 本次新增来源临时目录
│   ├── newA.jpg                     # 待抠图，源去重只扫本目录顶层
│   ├── failedB.jpg                  # 外部AI失败，继续留顶层
│   └── 已处理\
│       ├── finishedC.jpg            # 外部AI成功，待本系统整理
│       └── finishedD.jpg
└── 260919\                         # 旧批次仍有失败来源可以留着
    └── failedOld.jpg
```

- 历史来源比对只读取根目录**平铺文件及有效数据库历史身份**；不可递归把其它日期未成功的来源作为「已生产历史」。
- 来源去重只扫本次临时目录**顶层图片**，排除 `已处理/` 和其它子目录。
- 源图成功整理：`已处理/*` 移到源图库根目录时统一按 `YYYYMMDDHHmmSSsss.ext` 命名；同毫秒不同图用 `_1/_2` 避让，同图按可靠规则直接删除新文件。
- 空 `已处理/` 自动删；整个日期目录**彻底为空**才删。失败图片永远不得因「清空目录」被删除。
- 初次建立历史库：扫描已有根目录并建索引即可；无须专门迁移流程；用户可把旧待处理来源当第一次任务输入。

### 2.2 POD 图库

```text
D:\POD\POD待处理\
├── new001.png                         # 外部工具输出；当前批次缓冲区
└── new002.png

D:\POD\POD图库\
├── new001.png                         # 归档主文件；根目录不按日期分层
├── new002.png
└── Production\
    └── 1x1\
        └── 261008\                   # 本次裁切执行日期
            └── 20261008112203854_1x1.png # 由根目录原图居中裁切生成
```

- POD 原图入库不配置输出比例；主文件归档时统一按 `YYYYMMDDHHmmSSsss.ext` 命名，并保持原像素；同毫秒不同图才加 `_1/_2`，不重采样、不拉伸、不改材质和印花。
- 生产裁切可选择内置比例或新增 `2:3` 等自定义比例；裁切图位于 `Production/比例/执行日期/`，文件名为 `原图名_比例.ext`，只裁掉边缘以满足比例，不缩放、不改写根目录原图。
- POD 待处理目录可重复使用；每批处理结束后，已经成功处理的文件不留在此目录，失败/仍在审核中的原文件按本节状态保留。
- 分类日期 `archive_date` 在**开始统一归档时**按执行端配置时区生成一次并写入任务；人工审图跨天使用审完后开始归档之日；中途崩溃次日恢复仍沿用已冻结日期。
- 分类副本不能再作为独立历史 POD 入库、不能重复算素材数量；删除历史 POD 同步清理它全部已登记主文件和分类副本，不能只删根目录。

### 2.3 文件名冲突与格式

- 只处理 `.jpg/.jpeg/.png/.webp/.bmp/.tif/.tiff`（由设置控制）；其它文件不删、不动、记录跳过。解码失败保留并标错。
- 归档目标先生成执行端本地时间名 `YYYYMMDDHHmmSSsss.ext`；目标同名同内容可视为幂等成功，目标同名异内容递增 `_1/_2`，扩展名不变；大小写按 Windows 文件系统不区分处理。
- 分类副本使用归档后**主文件的最终名称**，保持一图两条文件记录而非新建第二个业务图片ID。
- 如果宽高与指定比例偏差超过可配置容差（默认相对偏差 2%），该项 `RATIO_MISMATCH`，保留待处理文件，页面明确显示；不能默默变形或复制到错误比例目录。比例相同、实际像素分辨率不同仍然可以是不同质量版本。

---

## 3. 判重的业务定义（优先于任何算法得分）

### 3.1 来源图 SOURCE

核心判断：「新场景图产品表面的**实际可印刷核心印花**，历史是否已经采集/生产过？新图是否提供历史缺失的重要设计信息？」

| 场景 | 结果 |
|---|---|
| 同模特、同背景、同袋子形状，**印花不同** | **不重复；绝不能因整图相似自动删除** |
| 相同印花，展示场景/角度不同，印花关键信息都已掌握 | 希望来源阶段识别；高可靠确定后可删除，降低后续AI费用 |
| 新图展示旧图被遮挡的完整文字/花纹、重要新增细节 | 保留，即便很可能同款，也可能对生成有价值 |
| 仅文件名、压缩、格式变化且解码内容相同 | 直接确认重复 |
| 判断不了产品印花是否同款 | 保留、不强制来源人工审，交给后续POD去重兜底 |

### 3.2 POD

核心判断：「人眼看这两张纯平面图，是不是同一款 POD 印花设计？」

- 同文件或同像素：重复，可自动删除本次新文件（不损失不同分辨率的新版本）。
- 压缩/缩放后相同设计：判重；但**新旧分辨率/实际质量明显不同**时即使确认同款也**人工选择留哪张**。
- 相同主题花卉、背景相似不够；文字不同、重要元素不同、构图关键变化不得自动删。
- AI生成细微变化但人眼同款：候选/人工审或已验证高确定规则处理。
- **不同比例不自动删**，不论印花相同与否；可标 `SAME_DESIGN_DIFFERENT_RATIO` 供查阅。批次配置比例与实际尺寸不符时不自动归档。
- **刻意用同一来源重做另一比例的特殊操作**：来源去重按钮本来会把同一来源判重复；用户要主动复制已归档来源到新批次，**跳过本轮来源去重**，直接交外部AI生成另一比例，再执行POD去重/分类归档。界面帮助提示该例外；不得偷偷改变普通来源去重规则。

### 3.3 判定与处理严格分离

```text
RETRIEVED_CANDIDATE ≠ DUPLICATE
DUPLICATE ≠ DELETE
HUMAN_DUPLICATE + KEEP_BOTH → 仍是「重复关系」，不是「不重复」
```

精确重复与复杂视觉重复分级；无证据或预算耗尽时不可自动删除。用户最终选择保留两张，系统不再对**同一内容版本**反复审核同一对。

---

## 4. 页面与三个按钮

### 4.1 页面结构

```text
左侧：图片去重（核心）｜任务中心｜人工审核｜图片/去重记录｜日志｜系统设置｜AI抠图（占位）

图片去重页：
A 本次来源文件夹 [浏览]  历史源图库 [浏览/默认记忆]   [开始来源去重]
B 自动复用A配置                                  [整理已处理来源图]
C 本次POD待处理 [浏览] 历史POD图库 [浏览/默认记忆]
  输出比例 [3:4▼]                                    [开始POD去重]
```

浏览器提交的是**执行端可访问真实文件路径**，不需要把成千图片上传网页。目录浏览 API 限制到系统配置允许的根路径，禁止 `..` 路径穿越和路径混叠。

### 4.2 按钮合同

| 按钮 | 主输入 | 必须动作 | 本轮终态 |
|---|---|---|---|
| 来源去重 | 本批顶层来源/历史来源/历史 POD | 本批内部+两库候选、保守判断、只删确认重复、保留待AI来源 | DONE / PARTIAL_COMPLETED |
| 整理已处理 | 本批/已处理 与历史源根 | 去重、同名避让、安全移动、增量索引、空目录清理 | DONE / PARTIAL_COMPLETED |
| POD去重 | 本批POD待处理/历史POD/比例/本批来源上下文 | **自动来源整理**→本批+历史去重→需审统一审核→统一移动主文件/复制分类 | DONE / PARTIAL_COMPLETED / WAIT_REVIEW |

第三按钮的来源整理如果个别来源图失败：记录警告并继续处理不受影响的 POD；源图库根目录无法访问等关键错误则停止并说明，不能误以为整理成功。

### 4.3 人工审核页

对每个新POD显示历史匹配图，支持高清预览、放大、切换多个匹配对象，展示证据/比对原因（不是只有分数）。动作：

1. `重复，保留新图并删除旧图`；
2. `重复，保留旧图并删除新图`；
3. `重复，但两张都保留`；
4. `不是重复，两张都保留`；
5. `暂不确定，稍后处理`（仍待审核）。

删除必二次确认；判断与删除分别记录。待审关系按同一任务内的图片关联组件合并显示：两张并列，三张以上按网格同时比较；镜像候选 `A→B` 与 `B→A` 不得要求用户重复判断。用户可选择保留一张或多张图片，再明确删除未保留图片；后端仍保存每一条底层图片关系的独立审核结论和删除证据。候选组仅用于方便同时判断，不能把链式候选自动推断为组内全部重复。**同一新图匹配多张旧图时，需处理所有仍有意义的关系**；若某次审核决定删除新图，其余关系因该图不再归档而标注 `RESOLVED_BY_DELETION`，但人工已给出的判断仍保留。

人工审完本批最后一条**自动触发统一归档**；无任何需审项时直接归档；等待某批人工不会阻塞别的、不共享源/待处理目录的任务。

---

## 5. 最终技术栈与运行环境

| 层 | 决定 |
|---|---|
| 目标环境 | Windows 10/11 x64；首版 API+Worker 在本机运行，管理本机及已挂载NAS共享目录 |
| Python | 3.11 或 3.12 x64，使用 `uv` 管理；**不以已装的Python 3.14作为默认执行版本**，先确保Torch/FAISS等组合可安装 |
| API | FastAPI + Pydantic v2 + Uvicorn |
| UI | Vue 3 + Vite + TypeScript + Element Plus + Pinia + Vue Router |
| 数据库 | **MySQL 8.0+，utf8mb4**，SQLAlchemy 2.x + Alembic + PyMySQL；不新引入MongoDB/H2/PG |
| 后台任务 | 独立 Python Worker + MySQL 持久任务/租约；V1不强制Redis/Celery/LangGraph |
| 基础图像 | hashlib、Pillow、OpenCV、NumPy、ImageHash（仅候选召回辅助） |
| 视觉向量 | PyTorch + **DINOv2 ViT-S/14 384维作为首个可运行候选**；模型/预处理可替换并版本化，不假定它是最终最优 |
| 检索 | `faiss-cpu`；初版 `IndexIDMap2(IndexFlatIP)` + 归一化向量，保守准确；历史量提升后可选HNSW并验证等价性/删除重建行为 |
| 印花区域 | OpenCV/可替换定位器接口；第一可运行方案：可配置产品区域定位（如支持产品提示词的本地检测器）+ 边界裁剪 + 必要时VLM补充定位；不是图片生成 |
| VLM | 可配置支持多模态输入的 Provider/Model；优先实现兼容 OpenAI Chat Completions 形态的适配器，**按目标Provider验证图片入参**，不能假设所有API完全一致 |
| 硬件 | GPU特征提取可选（用户有 RTX 3070 8GB），CPU后备；FAISS CPU即可 |

**开发交付必须冻结实际测试通过的依赖版本与锁文件，不使用未验证的“最新版”组合。** 如果外部模型权重下载失败，要在启动检查/设置页给出清晰提示和手动安装说明；不能静默采用随机向量。

参考官方资料：FastAPI background tasks（重活建议独立执行器）https://fastapi.tiangolo.com/tutorial/background-tasks/ ；DINOv2 https://github.com/facebookresearch/dinov2 ；FAISS Python wheel https://pypi.org/project/faiss-cpu/ 。

---
## 6. 工程仓库结构及模块合同

创建单仓库 `pod-dedup/`：

```text
pod-dedup/
├── AGENTS.md                        # Codex简要执行规则及本规格路径
├── README.md                        # Windows安装、启动、VLM配置、故障排查
├── .env.example                     # 不含真实密钥/个人本机绝对路径
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
│       ├── main.ts
│       ├── router/index.ts
│       ├── api/{http,tasks,reviews,settings,files}.ts
│       ├── stores/{tasks,settings}.ts
│       ├── views/{Dedup,TaskList,TaskDetail,Reviews,Images,Logs,Settings,AIPlaceholder}.vue
│       └── components/{DirectoryPicker,ImageCompare,ProgressPanel,ConfirmDelete}.vue
├── backend/
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── alembic.ini
│   ├── migrations/versions/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/{tasks,reviews,images,fs,settings,logs,health}.py
│   │   ├── models/{images,tasks,features,pairs,reviews,operations,settings}.py
│   │   ├── schemas/{tasks,reviews,images,settings,errors}.py
│   │   ├── repositories/
│   │   ├── services/{source_dedup,source_organize,pod_dedup,review,archive}.py
│   │   ├── workers/{runner,lease,recovery}.py
│   │   ├── dedup/
│   │   │   ├── common/{fingerprint,phash,embedding,retrieval,judgement}.py
│   │   │   ├── source/{region_locator,dual_retriever,judge}.py
│   │   │   ├── pod/{retriever,judge}.py
│   │   │   ├── vlm/{base,openai_compatible,prompts,parser}.py
│   │   │   └── feedback/reuse.py
│   │   ├── indexing/{catalog,feature_store,faiss_store,reconcile}.py
│   │   ├── storage/{paths,scan,safe_ops,preview,recovery}.py
│   │   └── core/{config,db,logging,enums,clock,errors}.py
│   └── tests/{unit,integration,fixtures}/
├── data/{faiss,thumbnails,logs}/     # 本地可配置，不入git
├── docs/
│   ├── SPEC.md                      # 即本规格；唯一完整需求基线
│   ├── API.md
│   └── OPERATIONS.md
└── scripts/{start_api.ps1,start_worker.ps1,start_frontend.ps1,bootstrap.ps1}.ps1
```

**统一入口与边界**：

- API **只**做参数校验/预检、落任务、反馈任务ID；不在 HTTP 请求中批量运算；初版任务状态每2秒轮询即可。
- Worker 领取可执行任务，调用相应 service；每张文件独立 checkpoint。
- 去重引擎只返回证据和判定；**不直接删除文件**。
- 真实路径操作只有 `storage/safe_ops.py` 可以执行；所有移动、复制、删除必须带 file_operation 记录及前后核验。
- 索引服务维护有效 IMAGE ID→FAISS ID；FAISS 是可重建缓存，MySQL/真实文件是事实源。
- VLM适配器只负责视觉分析，不得借用 AI 图像生成接口；API Key 不回显、不写日志。

---

## 7. MySQL 8.0 数据模型（可直接编写 Alembic）

### 7.1 共通约定

- 主键推荐 `BIGINT UNSIGNED AUTO_INCREMENT`；API 对外返回字符串或 JSON 安全的 ID；记录时间为UTC `DATETIME(6)`，展示时按设置时区转换；归档日期 `DATE` 单独存。
- `created_at`、`updated_at`、`version`（乐观锁）用于审计/并发；业务枚举由 Python `Enum` 严格校验，数据库使用 `VARCHAR`，不依赖不同MySQL版本的CHECK行为。
- 多行文本/配置 `JSON`；文件路径 `TEXT`，规范化路径的 SHA256 `BINARY(32)` 做**唯一键**，避免超长路径索引限制；同一真实文件不因大小写/斜杠不同建两条有效记录。
- `sha256` 存 `BINARY(32)`；可审计界面转换十六进制；**禁止将 SHA256 设为 images 全局唯一**，不同批次的同内容文件必须能分别记下处理/删除历史。
- `image_files` 只代表系统登记的物理文件；主文件和分类副本不能建成两个业务POD身份。
- 索引和模型版本必须有 `model_id + preprocess_version`；换特征模型必须隔离命名空间。

### 7.2 核心表与字段

**`images`——稳定图片身份**

| 字段（MySQL类型建议） | 用途 |
|---|---|
| `id BIGINT UNSIGNED PK` | 不受文件移动/改名影响的业务身份 |
| `kind VARCHAR(12) NOT NULL` | `SOURCE` / `POD` |
| `original_filename VARCHAR(512) NOT NULL` | 首次登记名称 |
| `sha256 BINARY(32) NULL` | 文件内容精确Hash |
| `pixel_digest BINARY(32) NULL` | 规范化解码后宽高/模式/像素流精确摘要；二次逐像素验证 |
| `width INT`, `height INT`, `file_size BIGINT` | 尺寸/大小 |
| `source_image_id BIGINT NULL` | 仅在外部工具给出可靠映射时填；不得猜测 |
| `status VARCHAR(24)` | `PENDING/LIBRARY/DELETED/MISSING/INVALID` |
| `created_at`, `updated_at` | UTC时间 |

**`image_files`——真实主文件/副本**

| 字段 | 用途 |
|---|---|
| `id`, `image_id` | FK `images.id` |
| `role VARCHAR(20)` | `SOURCE_PENDING/SOURCE_PROCESSED/SOURCE_LIBRARY/POD_PENDING/POD_MASTER/POD_CLASSIFIED` |
| `path TEXT`, `normalized_path_digest BINARY(32)` | 原路径/规范化索引键 |
| `size_bytes BIGINT`, `mtime_ns BIGINT`, `sha256 BINARY(32)` | 执行动作前核验的快照 |
| `file_status VARCHAR(20)` | `PRESENT/IN_TRANSFER/MISSING/DELETED` |
| `archive_date DATE NULL`, `ratio_code VARCHAR(8) NULL` | 副本归档元数据 |
| `created_at`, `updated_at` | 时间 |

索引：`UNIQUE(normalized_path_digest)` 用于全状态文件路径资源冲突；被删除的历史路径需要重新使用时，采用保留旧记录+单独活跃路径映射，或基于 `active_path_key` 可空唯一键；**不得因此丢弃删除审计**。建议 `active_path_key=BINARY(32) NULL`，只在PRESENT/IN_TRANSFER时赋值，失效后置NULL，唯一约束 `UNIQUE(active_path_key)`。

**`tasks`——三种父任务**

`id, type VARCHAR(24), status VARCHAR(30), source_batch_dir TEXT NULL, source_library_dir TEXT NULL, pod_pending_dir TEXT NULL, pod_library_dir TEXT NULL, ratio_code VARCHAR(8) NULL, archive_date DATE NULL, settings_snapshot JSON, counters JSON, warnings JSON, idempotency_key VARCHAR(80) UNIQUE, lease_owner VARCHAR(80) NULL, lease_until DATETIME(6) NULL, started_at, finished_at, created_at, updated_at, version INT`。

**`task_items`——每张图每次任务动作**

`id, task_id FK, image_id FK NULL（扫描发现后填）, observed_path TEXT, observed_path_digest BINARY(32), stage VARCHAR(30), status VARCHAR(30), error_code VARCHAR(50) NULL, error_message TEXT NULL, retry_count INT DEFAULT 0, snapshot_sha256 BINARY(32) NULL, snapshot_size BIGINT NULL, snapshot_mtime_ns BIGINT NULL, created_at, updated_at, version INT`。

约束：`UNIQUE(task_id, observed_path_digest)`（单批源路径唯一）；若文件移动后 task_item 保留 observed_path，不覆盖该来源证据。

**`image_features`——可重建向量来源数据**

`id, image_id FK, feature_scope VARCHAR(28)`（`SOURCE_FULL/SOURCE_PRINT/POD_FULL`）, `region_seq SMALLINT DEFAULT 0, bbox_json JSON NULL, model_id VARCHAR(128), model_revision VARCHAR(128), preprocess_version VARCHAR(64), dimension SMALLINT, vector_blob LONGBLOB, vector_sha256 BINARY(32), faiss_vector_id BIGINT, is_valid BOOLEAN, created_at`。

- `vector_blob` 存 little-endian float32、L2归一化向量；大图片**不存进MySQL**。
- 唯一键 `(image_id, feature_scope, region_seq, model_id, model_revision, preprocess_version)`；建索引 `(feature_scope, model_id, model_revision, is_valid)`。

**`duplicate_pairs`——业务判断和证据**

`id, task_id FK, image_new_id FK, image_match_id FK, pair_type VARCHAR(20)`（`SOURCE_SOURCE/SOURCE_POD/POD_POD`）, `content_sig_new BINARY(32), content_sig_match BINARY(32), similarity_json JSON, evidence_json JSON, machine_decision VARCHAR(32), rule_id VARCHAR(80), rule_version VARCHAR(40), model_id VARCHAR(128) NULL, review_required BOOLEAN, resolution_status VARCHAR(32), created_at, updated_at`。

- 同批图间 pair 按稳定 ID 排序形成规范 pair-key；不要用像素得分代替关系ID；人工结论与自动决策分开。
- `content_sig_*` 防止旧审核结论错误套用到被外部软件替换的新图片。
- 可用 `(task_id, image_new_id, image_match_id, pair_type)` 作为业务去重索引，结合对称归一化避免A↔B重复创建。

**`reviews`——人工审核决策**

`id, pair_id FK, task_id FK, status VARCHAR(20), duplicate_decision VARCHAR(24)`（`DUPLICATE/NOT_DUPLICATE/UNCERTAIN`）, `action_decision VARCHAR(28)`（`DELETE_NEW/DELETE_MATCH/KEEP_BOTH/NONE`）, `reviewed_by VARCHAR(80), reviewed_at DATETIME(6), note TEXT, created_at, updated_at, version INT`。

- 同一对在本任务中不重复出现有效待审行；自动删图后其它待审关系标 `RESOLVED_BY_DELETION`，不能平白伪造人工判断。

**`file_operations`——文件改变的不可删审计**

`id, task_id FK NULL, task_item_id FK NULL, image_id FK, operation VARCHAR(16)`（`MOVE/COPY/DELETE/RENAME`）, `origin_path TEXT NULL, target_path TEXT NULL, origin_sha256 BINARY(32), expected_size BIGINT, temp_path TEXT NULL, operation_key VARCHAR(120) UNIQUE, state VARCHAR(20)`（`PREPARED/EXECUTING/VERIFIED/DONE/FAILED`）, `reason VARCHAR(80), duplicate_pair_id FK NULL, thumbnail_path TEXT NULL, error_text TEXT NULL, actor VARCHAR(80), prepared_at, finished_at, created_at, updated_at`。

**推荐同时实现的轻量辅助表**

- `task_events`：`task_id, item_id, level, stage, message, details_json, created_at`。
- `model_calls`：`task_id, pair_id, provider, model, request_kind, elapsed_ms, token_usage_json, estimated_cost NULL, outcome, safe_error, created_at`；不保存API Key和未经处理的完整敏感请求。
- `settings`：`key PK, value_json, updated_at`；密钥从环境变量/加密配置读取，API只返回 `is_configured` 和脱敏名。
- `index_builds`：索引命名空间、模型、特征维度、生成批次、构建时间、checksum、当前活动版本。

### 7.3 关联原则

```text
tasks 1:N task_items N:1 images
images 1:N image_files
images 1:N image_features
tasks 1:N duplicate_pairs 1:0..1 reviews
images 1:N file_operations
```

- SOURCE/POD都可以被不同去重任务引用，但外部抠图工具没有可靠映射时，`source_image_id` 为NULL，不允许仅凭时间戳猜。
- 删除是文件与业务身份状态变化，**不可级联物理删除审计/判定历史**。

---

## 8. 枚举、状态机与任务锁

### 8.1 父任务类型

`SOURCE_DEDUP`, `SOURCE_ORGANIZE`, `POD_DEDUP`。POD任务内部来源整理记录为阶段和关联 `SOURCE_ORGANIZE` 子执行事件，**不隐形地重复领取相同目录**。

### 8.2 父任务状态

```text
CREATED -> VALIDATING -> SCANNING
SOURCE_DEDUP:       -> SOURCE_SEARCH -> DECIDING -> FILE_ACTIONS -> DONE|PARTIAL_COMPLETED
SOURCE_ORGANIZE:    -> SOURCE_ORGANIZING -> INDEX_UPDATE -> DONE|PARTIAL_COMPLETED
POD_DEDUP:         -> SOURCE_ORGANIZING -> SCANNING -> POD_SEARCH -> DECIDING
                  -> WAIT_REVIEW(如有) -> ARCHIVING -> INDEX_UPDATE -> DONE|PARTIAL_COMPLETED
```

通用 `PAUSING/PAUSED/FAILED/CANCELLED`。**有任意已报告未处理错误而其它项已成功的父任务为 PARTIAL_COMPLETED，不显示全部成功**。用户暂停在单图安全点，完成正在进行的文件事务后停；恢复从子任务阶段继续，不重跑已完成图。

### 8.3 子任务状态

| 类型 | 允许的核心子状态 |
|---|---|
| 来源去重 | `PENDING/CHECKING/PASSED/AUTO_DELETED/ERROR/SKIPPED` |
| 来源整理 | `PENDING/MOVING/ARCHIVED_SOURCE/DUPLICATE_DELETED/ERROR` |
| POD去重 | `PENDING/CHECKING/AUTO_DELETED/WAIT_REVIEW/READY_TO_ARCHIVE/ARCHIVING/ARCHIVED/DELETED_BY_REVIEW/RATIO_MISMATCH/ERROR` |

错误重试必须以存活文件及操作日志核验为前提。`WAIT_REVIEW`不是 AI生成失败；外部 AI 的成败由文件夹观察，不人为伪造生成状态。

### 8.4 任务资源互斥

- MySQL 持久锁资源键：`POD_PENDING:<canonical_path_hash>`、`SOURCE_PROCESSED:<canonical_path_hash>`、必要时 `SOURCE_BATCH:<canonical_path_hash>`。
- `POD_PENDING` 锁覆盖**从冻结清单、去重、等待人工直到全部文件归档/异常终结**，不能在 WAIT_REVIEW 释放后让另一任务接管同目录。
- 若锁定目录里出现了**快照外新增文件**，本任务不处理；UI警示「本任务进行中，不要继续往该目录输出」，新增文件留原位等待本任务结案及下批扫描。
- 不同目录任务互不阻塞，但两个任务涉及同一真实物理文件时，存储层再次核验/阻止冲突；来源整理跨批次向同一图库根目录写入时执行目标命名排他。
- Worker 以事务与 lease 领取任务；超时恢复不能并发双执行，`version`/lease owner验证防重入；重启依据文件操作日志而不是简单从头运行。

---
## 9. 去重引擎：实际可执行的分层算法

### 9.1 重要：各技术不等价

| 技术 | 具体职责 | 不可做的事 |
|---|---|---|
| SHA256 | 字节级完全相同，文件名无关 | 不能识别重新编码、尺寸变化 |
| 像素精确核验 | 按EXIF转正、统一色彩模式后比较**宽高+全部像素**，不同容器可确认同像素 | 不能识别有损压缩、重缩放同设计 |
| pHash/dHash | 低成本整图相似**候选**，只辅助召回 | **绝不能**独立判来源场景同印花，更不能靠75%删图 |
| 视觉Embedding | 大库Top-K召回相似图片/印花 | 分数不代表「人眼同款」结论，更不等于删除许可 |
| 区域识别/局部匹配 | 定位产品表面图案、降低模特和场景影响 | 不能把「产品同款」直接当「印花同款」 |
| VLM对图判断 | 比文字、花型、元素排列、遮挡/新增信息、是否同设计 | 一次回答不绝对可靠；无结构化证据不可直接删 |
| 人工审核 | 复杂POD对的最终判重与保留选择 | 不必强制审核所有来源图模糊项 |

### 9.2 特征库设计

分别维护三个兼容版本的检索空间（均按 `model_id + preprocess_version` 隔离）：

```text
SOURCE_FULL       历史来源图整图向量
SOURCE_PRINT      历史来源图可见印花区域向量（可一张图多区域）
POD_FULL          历史纯平面POD向量
```

在 DINOv2 首版中统一预处理、抽取视觉向量、L2归一化；`IndexFlatIP` 的返回是归一化向量余弦内积。每个 query 用可配置 `top_k`（例如默认20，作为检索开销参数而非准确率承诺），合并整图/印花/POD各路候选、去重并取有效存在的文件；如后过滤导致不足可加大检索池。**来源ROI向量与POD向量同特征模型才能做数值比较，但两种图域不同，结果只当候选。**

`SOURCE_PRINT` ROI定位：

1. 先执行本地图像/对象区域定位器，从预置可配置产品提示词识别商品主体，候选包括束口袋、桌布、床品、挂毯、化妆包、方巾、束发带等；**检测到产品框不代表已经识别全部印花**。
2. 可提取一个或多个「可见印花区域」裁剪，保存 ROI 的原图归一化框、可信标志、定位方法/版本；不得覆盖用户源图。裁剪区域需要含足够图案，不应只取人物背景。
3. 本地定位失败时：若启用且仍有VLM预算，询问模型「印花所在区域及可见的主要元素」并做坐标合法性/范围检查；否则保留整图召回路线且记录 ROI_UNAVAILABLE，不能因此自动删。
4. 对ROI与历史 `SOURCE_PRINT` 和 `POD_FULL` 分别查询；同场景不同印花可通过整图召回进入对图比对；不同场景同印花主要依赖 ROI 路线。
5. **不要为了来源去重调用图片生成/重绘**，不把用户现有高价 AI 抠图替换成预先生成另一张POD图。

### 9.3 来源去重执行算法（伪代码，业务约束）

```python
for new_source in frozen_batch_images:
    ensure_file_stable_and_hash_snapshot(new_source)
    if exact_sha_match(new_source, historical_sources_or_in_batch):
        decide_exact_duplicate_and_delete_new_with_evidence()
        continue
    if exact_pixel_match_with_full_verification(new_source, historical_sources_or_in_batch):
        decide_exact_duplicate_and_delete_new_with_evidence()
        continue

    candidates = union_unique(
        search_source_full_topk(new_source),
        search_source_print_topk(locate_visible_print(new_source)),
        search_pod_full_topk(locate_visible_print(new_source)),
        search_current_batch_source_features(new_source),
    )
    for candidate in candidates:
        # reuse human labels only if both image content signatures match
        result = compare_print_design_and_incremental_details(new_source, candidate)
        if result == VERIFIED_SAME_WITHOUT_NEW_DETAILS and visual_auto_delete_policy_is_enabled():
            delete_new_with_immutable_evidence()
            break
        if result in {DIFFERENT, UNCERTAIN, SAME_BUT_ADDITIONAL_DETAILS}:
            keep_new_for_external_ai()
    if not deleted: mark_source_passed()
```

**已确认源图自动删除规则 `SOURCE_VISUAL_HIGH_CONFIRMED`**：先通过至少一个有效的印花区域定位/局部结构证据召回，再经结构化VLM核对主体元素、图案位置、颜色、文字和遮挡差异，并满足另一独立视觉佐证（经验证的局部对应/第二独立判据）；没有「新增重要细节」，且该规则版本通过实际审核验证并由用户在设置中启用。缺少任何要素→`UNCERTAIN`→保留。不能仅 `整图Embedding高 + VLM说是` 就永久删除。

**历史POD辅助来源去重**：只将当前存在、已归档的 POD 主文件作为历史；跨图域只召回+比较，不因同主题/相同产品款式删来源；如果新来源具备历史POD没有的可见完整文字/图案信息则保留。

**本批内部来源去重**：在冻结的新来源清单里找同图，精确重复可选保留首次扫描的那个；视觉同款但两个场景提供互补印花细节则两个都留。未成功外部抠图的失败图不得因此加入「历史成功来源索引」。

### 9.4 POD去重执行算法

```python
for new_pod in frozen_pod_batch:
    if exact_sha_match(new_pod, valid_historical_and_current_batch):
        auto_delete_new_with_evidence()
        continue
    if exact_pixels_after_canonical_decode_match(...):
        auto_delete_new_with_evidence()
        continue

    candidates = search_pod_historical_and_batch_topk(new_pod)
    for old in candidates:
        if output_ratio(new_pod) != output_ratio(old):
            record_same_design_other_ratio_if_supported()
            continue  # 不跨比例自动删除；不阻塞正常归档
        same_design = detailed_print_compare(new_pod, old)
        if same_design == CERTAINLY_DIFFERENT:
            remember_negative_relation()
            continue
        if same_design == CERTAINLY_SAME and material_quality_difference(new_pod, old):
            queue_review_to_choose_version()
            continue
        if same_design == CERTAINLY_SAME and verified_visual_delete_rule_enabled():
            auto_delete_new_with_evidence()
            break
        if same_design in {SAME_DESIGN_BUT_SMALL_VARIATION, UNCERTAIN}:
            queue_review()
            continue
    if not deleted and no_review_required: mark_ready_to_archive()
```

**分辨率差异规则**：精准字节/精准像素相同可以删新；视觉上同款、但新旧`width×height`不同（特别是更高像素）或图像清晰度无法可靠认定等价→人工审核。用户有权保留新图删旧图；历史POD被人工删除时清理主文件和所有分类副本。

**本批内部近似重复**：多张候选可形成同款组，不能只找历史库；只删已有可靠相同且无质量版本冲突的新图；群组里一个样本被删除后，关系引用的另一张必须仍有效，否则选择有效保留者；无法处理的群组待审。

### 9.5 阈值策略与默认开关

```yaml
source:
  exact_auto_delete: true
  visual_auto_delete: false          # 规则验证后用户手动开启
  source_uncertain_action: KEEP      # 不强制来源人工审核
  compare_historical_pod: true
pod:
  exact_auto_delete: true
  visual_auto_delete: false          # 实现可配置能力，初期保守
  suspected_action: REVIEW
  archive_requires_reviews_closed: true
retrieval:
  top_k_per_index: 20
  thresholds: null                  # 各模型按实测校准；不得把0.8写死作判重真值
```

- `visual_auto_delete=false` 不代表视觉功能未实现：**仍需实现并运行视觉候选、VLM、人工审核和双图库路径**；仅仅不允许未验证视觉结论触发永久删除。
- POD的「候选范围阈值」「人工审核范围」「经验证自动删规则」分别配置并保存任务快照；阈值变化不追溯改变历史动作。
- 对 VLM 失败/预算耗尽/图片损坏：来源保留；POD若存在无法排除的已召回疑似候选→人工审核，否则记录降级警告并待归档；**不能把 VLM 故障当作机器已确认不重复**。
- 用户原图直接删、不放回收站；可选 `dry_run`/「仅检测不删除」用于安装调试和验证，正式执行可关闭；它不是替用户永久打开回收站。

### 9.6 VLM适配器、Prompt及结构化响应

入参是原图/ROI、历史候选图/ROI，`pair_type`、可选分数和用户任务上下文；**图片必须真正传给支持视觉的模型**。来源与POD两套Prompt不可混用。

来源比较的任务说明（核心意思，不直接当唯一判断方法）：

```text
你是POD印花重复检查器，只比较商品表面的可印刷图案。
忽略人物、拍摄场景、产品外轮廓、阴影、展示道具。
逐项比较印花主题、具体形状、元素数量与排列、颜色、文字及文字位置。
特别检查新来源图是否显示历史图没有的完整文字、被遮挡花纹、重要边缘内容。
若同场景但印花不同→different；同印花但新图有重要新增细节→same_with_new_details；
无充分证据→uncertain。不要把同类玫瑰主题直接判作同设计。
```

POD比较说明：

```text
两张图均为平面POD印花。判断人眼是否认为同一款设计。
比较文字、元素、布局、背景、重复规律；说明异同。
若同款但分辨率/清晰度不同，返回 same_design，quality_delta 要求人工选版本；
若不同输出比例，不建议删除任何一张。证据不足返回 uncertain。
```

**必须校验的结构化返回**（字段示例）：

```json
{
  "verdict": "same|different|same_with_new_details|uncertain",
  "print_region_valid": true,
  "same_core_print": true,
  "same_text": true,
  "important_differences": [],
  "new_visible_details": [],
  "quality_delta": "none|new_better|old_better|uncertain",
  "evidence": ["可核验的具体图案或文字依据"],
  "reason": "简短中文说明"
}
```

`verdict`和布尔值矛盾、JSON不可解析、证据空泛、图像无法查看时一律视为 `uncertain`；将请求的模型和Prompt版本留日志；**不能完全相信模型自报置信度**。Provider兼容层支持 API 超时/有限重试、配额/成本上限，密钥脱敏。

### 9.7 人工反馈与「越用越准」

V1：保留两张图的内容摘要、pair_type、机器理由、用户重复结论、删除选择、模型/Prompt/规则版本；若同一内容签名的同一对再次出现可直接复用审核结论。已人工否定的对，不再反复要求审核。

后续：人工标注积累以后独立评估误报/漏报、重调阈值、可选训练轻量图片对判别器/微调视觉模型；**V1不承诺每点击一次审核就实时训练模型**，也不自动放宽永久删除权限。

---

## 10. 历史图库索引：首次建库、增量和重建

### 10.1 首次建库

- 系统设置固定历史源根目录、历史POD根目录后，提供 `建立/检查索引` 操作；三按钮第一次执行也可触发缺失索引的建库流程并展示进度，不让用户手动写SQL。
- 只扫描**两个根目录顶层历史主文件**；不递归其它日期失败来源、已处理文件夹或POD分类副本。
- 记录图片身份、有效主文件路径、SHA256、尺寸、像素摘要；下载/加载模型可用时生成对应特征，更新FAISS索引。
- 旧已经生成过的POD主文件直接建历史POD库，不再交外部AI重新生成；旧源图归档根直接建历史来源库。

### 10.2 增量

- 每个任务开始可对目录做廉价清单核对（路径+文件大小+mtime）；只有新增/疑似变更的文件再计算SHA256；只有内容变更/特征模型版本变更才重算Embedding。
- 从 `已处理/` 移到源图根的图片 **内容不变时沿用图片ID/特征**，只是更新路径和历史有效角色；POD从待处理进入主图库同理。
- 手动在Windows中删除文件时，下一次同步标 `MISSING`，从有效检索范围排除；不能因为索引里旧路径存在而判历史图有效。
- 索引活跃态以MySQL有效 `image_files` 为准；FAISS检索结果必须回表校验有效历史身份和存在状态。
- 模型升级新建命名空间，历史特征分批重新生成；新索引完成/核验后再激活；旧索引可作为回滚备份。

### 10.3 FAISS与重建

- `faiss_vector_id` 与 `image_features.id` 或稳定映射对应；`IndexIDMap2(IndexFlatIP)` 初版可完整重建。
- FAISS发生与MySQL不一致时优先回表过滤；后台基于持久化向量 `vector_blob` 重建新索引文件，写到临时文件、校验数量/ID/维度、原子切换活动文件。
- 业务数据不能只存在FAISS文件中；索引损坏不影响原始图片、人工结论和文件审计。
- 如果 10 万以上向量搜索成为瓶颈，可追加可选 HNSW 优化；必须证明本项目所用FAISS构造器的 add/删除/重建策略安全，不得直接替换导致丢匹配结果。

---
## 11. 文件操作的强制安全协议

### 11.1 危险路径预检查

拒绝以下场景并在界面给出中文错误：

- 来源批次目录与源图库根是同一个实际目录；来源批次目录落在 `已处理/` 内；POD待处理与POD主图库同目录，或待处理位于主图库的分类副本目录内。
- 源图库、POD图库、待处理目录互相指向相同实际位置（含Windows大小写/分隔符不同和符号链接/连接点映射）；不允许用户选磁盘根、共享盘根或任意父目录做「本次来源」。
- 当目录暂不可用、NAS断开、无法读取/写入，或者另一个活跃任务持有该目录锁。
- 待处理输入文件仍在写入、大小/mtime短期持续变化；此时跳过并标注 `FILE_NOT_STABLE`，不要搬移或删除。
- 服务端目录浏览只允许配置的有效根路径及其子路径，拒绝路径穿越；默认API仅监听 `127.0.0.1`，对外暴露必须另行配置身份验证。

### 11.2 永久删除

```text
判定规则已允许删除
→ 生成被删文件小缩略图并与历史匹配图建立证据关联
→ 将 duplicate_pairs、file_operations(PREPARED) 和关联任务阶段持久化提交
→ 重新读取当前文件的身份（当前规范化路径、大小、mtime、SHA256）
→ 不匹配原任务快照：中止删除，标记FILE_CHANGED、等待重新判断
→ 按POD主文件/分类副本关系收集所有应删文件路径
→ 按持久日志逐个删除，逐个验证实际不存在
→ 更新 image_files/图片有效状态/索引/操作状态 DONE
```

- `DELETE_NEW` 默认删除本次待处理新POD；人工 `DELETE_MATCH` 可删除历史主文件及分类副本；不能因不同分辨率未经审图就删除高像素新版本。
- 不设用户文件回收站；缩略图仅供审计，不可承诺还原已删高清原图。
- 如果必须删多份，某一份失败，保持 `PARTIAL` 和后续恢复计划，不能把主图/副本状态标为全部已删。
- 遇到文件ID/Hash与判断时不同绝不“强行继续”。

### 11.3 安全移动、复制与同名

- 同卷/同文件系统可使用受控的原子重命名；跨卷/到NAS：在目标目录写入临时文件 `.<uuid>.partial` → flush/fsync（若可用）→ 核对大小+SHA256 → 原子改正式名 → 删除源文件 → 更新 `image_files` 和操作日志。
- 目标已经存在且内容相同：核对是不是同一业务图片；可以视为幂等成功，不重复生成 `_1`。以 `YYYYMMDDHHmmSSsss.ext` 生成的目标若异内容：新图 `_1/_2` 递增，**不覆盖**；竞争情况下用独占创建或持久命名锁保证两Worker不争同名。
- **分类归档**：先将保留图移动为 POD 根目录主文件，再通过上述安全复制生成分类副本；两者SHA256应相同。副本创建成功后才将该 POD item 标 `ARCHIVED`。
- 根主图已移动、副本复制失败：POD item 为 `ERROR/ARCHIVING`，主图保留，恢复后只补副本；不把主图回拷成第二张待处理图。
- 来源整理移动后数据库更新前崩溃：查源文件和目标文件的内容校验及 file_operation，不制造重复 `_1_1`。

### 11.4 幂等与恢复

持久 operation key 推荐 `task_id:item_id:action_kind:logical_target_role`；同一步重复调用先读取上次状态和物理文件现状，不再盲目执行。后台启动时执行 `reconcile_incomplete_operations()`，对 PREPARED/EXECUTING/VERIFIED 的记录按源/目标/Hash恢复，异常不影响其它项。

MySQL事务**不能**让 Windows/NAS 文件操作也自动回滚；必须实现上面文件校验+日志恢复逻辑。Codex不得只写“使用数据库事务保证文件安全”而省略实际恢复代码和测试。

---

## 12. API：明确请求/响应与错误合同

API前缀 `/api/v1`；成功均返回对象，统一错误结构 `{ "code": "...", "message": "中文错误", "details": {} }`；长任务创建返回 HTTP 202 和 `task_id`。

### 12.1 创建三类任务

`POST /api/v1/tasks/source-dedup`

```json
{
  "source_batch_dir": "D:\\POD\\源图\\260920",
  "source_library_dir": "D:\\POD\\源图",
  "pod_library_dir": "D:\\POD\\POD图库",
  "dry_run": false,
  "idempotency_key": "ui-generated-unique-key"
}
```

`POST /api/v1/tasks/source-organize`

```json
{
  "source_batch_dir": "D:\\POD\\源图\\260920",
  "source_library_dir": "D:\\POD\\源图",
  "idempotency_key": "ui-generated-unique-key"
}
```

`POST /api/v1/tasks/pod-dedup`

```json
{
  "source_batch_dir": "D:\\POD\\源图\\260920",
  "source_library_dir": "D:\\POD\\源图",
  "pod_pending_dir": "D:\\POD\\POD待处理",
  "pod_library_dir": "D:\\POD\\POD图库",
  "ratio_code": "3x4",
  "idempotency_key": "ui-generated-unique-key"
}
```

**创建返回**（仅示例ID，不是要求数据库真的从1001开始）：

```json
{
  "task_id": "1001",
  "type": "POD_DEDUP",
  "status": "CREATED",
  "warnings": []
}
```

`source_batch_dir` 在点击POD去重时用于自动整理来源。若当天日期目录已被前一次整理成功删除，允许目录不存在且明确标记「无待整理来源」，**不能因此阻断只做POD去重**；但用户配置指向历史根目录等危险情况仍拒绝。

### 12.2 任务/预检

| 方法+路径 | 返回/行为 |
|---|---|
| `POST /api/v1/tasks/validate` | 请求含type及路径；只预检查，不操作图片；返回 `ok/errors/warnings/scanned_preview_count` |
| `GET /api/v1/tasks?type=&status=&page=` | 分页父任务、基础统计 |
| `GET /api/v1/tasks/{task_id}` | `type/status/stage/counts/archive_date/errors/warnings` |
| `GET /api/v1/tasks/{task_id}/items?page=` | 单张图片阶段、错误和匹配关系 |
| `POST /api/v1/tasks/{task_id}/pause` | 请求暂停；在下一文件安全点进入PAUSED |
| `POST /api/v1/tasks/{task_id}/resume` | 继续原任务 |
| `POST /api/v1/tasks/{task_id}/retry-failed` | 重试失败项目，保持已完成项目不动 |
| `POST /api/v1/tasks/{task_id}/cancel` | 取消后停止新动作；已完成文件动作不自动撤回 |

### 12.3 审核/图片/索引/配置

| 方法+路径 | 返回/行为 |
|---|---|
| `GET /api/v1/reviews?status=pending&task_id=` | 待审核图对+相关多候选，分页 |
| `GET /api/v1/reviews/{id}` | 原图预览元数据、匹配图、证据、图片实际像素信息 |
| `POST /api/v1/reviews/{id}/decision` | 提交 `duplicate_decision/action_decision/confirm_delete`；删除时要求 `confirm_delete:true`；事务中锁住审核行防重提 |
| `GET /api/v1/images/{id}` | 图片主文件、分类副本、相关记录 |
| `GET /api/v1/images/{id}/preview` | 受控流式缩略图/图片，处理文件缺失、权限和尺寸；不暴露任意服务器文件 |
| `GET /api/v1/duplicate-records` | 机器/人工判断及删除证据 |
| `GET /api/v1/operations` | 可分页文件操作审计 |
| `GET /api/v1/settings` / `PUT /api/v1/settings` | 目录、阈值、VLM、模型、资源限制；密钥只接收写入不明文回显 |
| `GET /api/v1/fs/directories?parent=...` | 受控目录浏览；执行端可访问路径 |
| `POST /api/v1/indexes/reconcile` | 创建历史库核对/增量索引任务 |
| `POST /api/v1/indexes/rebuild` | 建索引版本，不破坏业务图片 |
| `GET /api/v1/health` | 数据库、Worker、图库访问、视觉模型与VLM配置就绪情况 |

**人工审核请求示例**：

```json
{
  "duplicate_decision": "DUPLICATE",
  "action_decision": "DELETE_MATCH",
  "confirm_delete": true,
  "note": "新图分辨率更高，保留新图"
}
```

若两图保留：`duplicate_decision=DUPLICATE`、`action_decision=KEEP_BOTH`；若不同：`NOT_DUPLICATE` + `KEEP_BOTH`；不能在前端把这两种选择提交成同一个布尔值。

### 12.4 API防重/一致性

- 创建任务必须可使用 `idempotency_key`，重复点击同一key返回相同任务，不创建两个清理任务。
- 审核提交使用版本号或乐观锁防止连续点两次删错；若内容文件已在审核等待中变更，返回 HTTP409要求重新分析。
- 所有严重冲突（目录已锁、文件变了、比例错）返回明确的中文错误和可定位 task/item；不只在服务端打印 traceback。

---

## 13. 系统配置及示例 `.env.example`

在README中说明实际路径依用户电脑而定，**不得把以下D盘示例写死在代码**。配置读取次序：任务快照 > 用户设置 > 环境默认；所有缺失必填项提示用户配置。

```dotenv
APP_ENV=development
APP_HOST=127.0.0.1
APP_PORT=8000
APP_TIMEZONE=Asia/Shanghai
DATABASE_URL=mysql+pymysql://pod_user:CHANGE_ME@127.0.0.1:3306/pod_dedup?charset=utf8mb4
DATA_DIR=./data
SOURCE_LIBRARY_DIR=
POD_LIBRARY_DIR=
POD_PENDING_DIR=
WORKER_CONCURRENCY=1
MODEL_DEVICE=auto
EMBED_MODEL_ID=facebook/dinov2-small
EMBED_MODEL_REVISION=PIN_TESTED_REVISION
SOURCE_VISUAL_AUTO_DELETE=false
POD_VISUAL_AUTO_DELETE=false
SOURCE_EXACT_AUTO_DELETE=true
POD_EXACT_AUTO_DELETE=true
VLM_ENABLED=false
VLM_BASE_URL=
VLM_MODEL=
VLM_API_KEY=
VLM_MAX_CALLS_PER_TASK=100
VLM_MAX_ESTIMATED_COST_PER_TASK=
DEFAULT_RATIO=3x4
RATIO_REL_TOLERANCE=0.02
```

具体模型接入名称/权重地址由真正跑通的模型适配器和锁文件确定；不要把示例 `facebook/dinov2-small` 当成无需测试即可用的保证。要求提供**真实可运行的安装检查/模型下载说明**。

设置页分组：文件目录、去重/删除策略、Embedding/印花定位、VLM、任务/并发、分类日期与比例、日志与索引。修改配置只影响新任务；任务中途不被全局修改反向篡改。

---

## 14. 前端最小可用交互细节

| 页面 | 最低可验收界面 |
|---|---|
| 图片去重 | 3区块3按钮、目录选择与自动记忆、比例单选/下拉、仅检测模式、执行预检、任务创建反馈 |
| 任务中心 | 三种任务、进度阶段、总/已处理/删除/待审/错误、按状态查询、恢复/失败重试 |
| 任务详情 | 逐图处理结果、匹配对象与相似证据、异常重试入口、文件是否真正移动/删除 |
| 人工审核 | 双图并排/放大、历史图多候选、文字和图案差异证据、4类决策+暂缓、删除确认 |
| 去重/图片记录 | 自动/人工删除记录、删除图片缩略图、保留对象、主/副本关系 |
| 日志中心 | 任务、VLM调用、文件操作、人工操作四类可检索信息；无明文密钥 |
| 设置 | MySQL连接状态、模型/VLM配置及测试、图库路径、阈值/高确定规则开关、索引状态 |
| AI抠图 | 显示「V1沿用现有AI抠图工具，此模块预留」，不能展示假调用成功 |

对于未配置视觉服务：页面醒目标示「目前仅精确去重/视觉能力未就绪」，而非让用户误以为已检查不同场景同印花。

基础统计先做任务级扫描数、精确/视觉自动删除数、疑似待审数、人工删除数、最终归档数、失败数；不做精细经营报表。

---

## 15. 第一版实施顺序、不可跳过的验收门槛

> 下列 M1—M6 **全部完成才是V1完成**。M1/M2只可标为「基础阶段完成」，不得写「全部功能已实现」。开发时允许使用单测fixture与可配置假的测试Provider，但生产路径绝不可返回随机相似度、固定“重复”结果或静态演示图片。

### M1 工程基础（真实可启动）

- 仓库、锁文件、`.env.example`、Windows PowerShell启动脚本、README；Vue+FastAPI+MySQL+独立Worker启动。
- Alembic首版迁移、三类任务创建/进度API、目录浏览、路径风险预检、任务中心。
- 测试：API重启后任务记录仍存在；错误目录被阻止；浏览器关闭不取消后台扫描。

### M2 文件操作闭环（无需视觉模型即可真实使用）

- 图片扫描、SHA256+精准像素检查；来源精确去重；来源已处理安全移动、同名避让；POD精确去重、人工审核架子、主文件移动与分类复制；任务、子任务、操作日志。
- 历史根扫描与去重图片身份；待处理目录循环使用；归档日期、分辨率差异/跨比例保护。
- 测试：完整走三按钮；主/副本关联；同名不同图不覆盖；出错文件不丢；错误不能报DONE。

### M3 视觉索引与 POD 候选

- 安装可运行视觉模型、持久化特征、FAISS三索引（源全图/源印花/POD）、增量和重建；POD本批内部+历史近似检索，真实图对进入审核。
- 测试：不同文件名/重新压缩的候选能召回；相同主题但不同文字不得自动删；分类副本不算新POD。

### M4 来源核心印花与双图库检索

- 可用的印花区域定位与失败回退；同场景不同印花区分；同印花不同场景尽量召回；来源ROI↔历史POD的联合候选。
- 测试：同场景换印花不能自动删；同印花不同场景至少能被检索并进入准确后判；新来源提供完整新文字时保留。

### M5 VLM、规则和反馈

- 真正图片VLM接口、结构化比较与异常降级、可配置上限、严格自动删除规则开关、反馈保存/复用、审核证据和删除缩略图。
- 测试：VLM故障不删；相似度高但文字不同不删；人工确认不同不重复骚扰；同款高像素新图进入人工审核；高确定视觉自动删除需显式启用并有审计。

### M6 稳定性验收

- 断电/强停恢复测试、文件变更拒删、NAS写入中断、同待处理目录并发、双点击/重复审核幂等、旧索引重建、流程说明和最终操作演示。
- 测试：新旧文件真实状态一致；没有重复重名副本、无被悄悄覆盖、无主/副本孤儿、任务可从异常点恢复。

### 15.1 必需的自动化验收案例

| 编号 | 操作 | 预期 |
|---|---|---|
| A01 | 来源同文件改名、SHA一致 | 自动删本批新文件，记录双方和被删缩略图 |
| A02 | 同像素PNG/JPG无损变换 | 逐像素核验一致才自动删 |
| A03 | 同场景同人但不同印花 | 不因整图相似删 |
| A04 | 同印花不同场景 | 本地ROI/双图库召回；高确定且无新信息时才有可能视觉自动删 |
| A05 | 新来源比旧图多显示完整文字 | 留新图 |
| A06 | 来源不同内容在同一毫秒归档 | 移动时生成时间名 `_1`，不覆盖 |
| A07 | 外部AI成功/失败混合 | `已处理`归根；失败留本次顶层；未空日期目录不删 |
| A08 | POD本批内部重复，历史无记录 | 同样查重 |
| A09 | POD相同印花但不同文字 | 不仅因分数高自动删 |
| A10 | POD相同设计新图更高分辨率 | 人工决定删旧或删新；不能默认删新 |
| A11 | POD不同输出比例同设计 | 两个都留，必要时记录同款，不自动跨比例删 |
| A12 | POD 根目录同一毫秒时间名已有异内容文件 | 新图 `_1`，分类副本跟新名 |
| A13 | 审核「重复、两图保留」 | 判重关系仍重复，但都能归档/保持历史 |
| A14 | 审核删除历史POD | 删除历史主文件+全部分类副本；记录且更新索引 |
| A15 | 审核最后一个疑似项 | 不点确认归档；任务自动统一归档 |
| A16 | 旧任务待审核，新任务使用另一个目录 | 新任务可运行；同一POD待处理目录拒绝并发接管 |
| A17 | 第三按钮自动整理，单独第二按钮也可用 | 两种场景都正确，幂等 |
| A18 | 去重/归档中途强停再启动 | 前面已做项不重做；未做项继续；日志与物理文件一致 |
| A19 | NAS目标突然不可用 | 不把源图删掉；不把失败复制标成功 |
| A20 | 文件扫描后被人为替换，原拟删除 | SHA校验不符拒删，重排检测 |
| A21 | 未配置VLM/超预算 | 来源保留、POD疑似待审，告警不伪报视觉通过 |
| A22 | 前端选源图库根目录当本批 | 预检阻止 |
| A23 | 分类日期：20日来源、21日审核归档 | 归入21日；22日恢复未完归档仍用冻结21日 |
| A24 | 用户对同一内容版本图对已判非重复 | 再遇相同pair可复用，不再次要求判同一对 |
| A25 | 删除主图时分类目录已有多个历史副本 | 全部已登记副本清理；未登记者纳入一致性异常报告 |

### 15.2 测试技术与交付证据

- 后端 `pytest` 单测、MySQL测试库+临时Windows可访问测试目录集成测试；文件删除测试**只在隔离临时目录执行**，不能对用户生产目录跑清理测试。
- 前端至少基本组件/API响应测试和一次浏览器手动联调验证。
- 对模型部分：使用小型测试fixture验证数据流；另外至少一次真实模型调用/真实图片向量索引验证（有可用API密钥时）；无法访问网络/模型时必须在交付报告中列出**未完成的外部依赖验证**，而非宣称通过。
- 每个里程碑交付：已完成代码、启动命令、测试命令和结果、已知限制、下一里程碑计划。
- 验收性能目标不凭空承诺 X 张/秒或误删率数值；完成后用用户日常来源目录实测并记录基准，始终以**误删保护优先**。

---

## 16. Codex 实施指令（可直接作为任务输入）

```text
请完整阅读 docs/SPEC.md（本文件），以其作为唯一业务规格。不要改动已确认的F01-F12规则。
先输出按M1-M6排列的简短实施计划和环境检测结果，再从M1开始连续实现；
每个里程碑必须提交可启动代码与自动化测试，不允许仅生成文档、TODO、空API或静态页面。
项目使用 Windows 本地路径、MySQL 8、Python 3.11/3.12 + FastAPI + 独立Worker、
Vue3/TypeScript/Element Plus、Pillow/OpenCV、DINOv2可替换适配器、FAISS CPU和可配置VLM。
不得要求用户先购买/连接新数据库，不得把成千图片上传到网盘做去重。
所有永久删图必须经过已批准规则、当前文件身份再核验、持久化记录、缩略图取证，
禁止仅凭pHash/Embedding分数或VLM单次回答永久删除。
先做三按钮真实业务闭环，再完成来源印花区域+历史来源/POD双图库检索；
Hash基础版不能冒充完整V1。模型不可用时给出明确降级状态，不编造模型结果。
依照API合同、状态机、数据结构和A01-A25验收测试实现；
对规格没有明确禁止的内部实现细节可自主选择，但必须记录理由、保持接口行为兼容。
如果发现足以造成不可恢复删除的真实业务冲突，停止相关危险动作并询问用户，
不要隐含猜测并继续删图。
完成后输出README安装指南、.env.example、数据库迁移、脚本、测试报告和已知限制。
```

### 16.1 不允许Codex自行“简化掉”的内容

- 来源核心印花去重不能退化成整图 pHash 75% 清理。
- 双图库来源去重不能退化成只查历史源图。
- POD不能只查历史，不查本批内部。
- 三按钮不能改成只剩一个或单纯AI批量生成入口。
- 不能省略人工审核完成后自动归档、主副本联动删除、恢复/审计。
- 不能为了演示把AI生成模型替代现有外部抠图工具。
- 不能把用户的图片根路径、密钥、邮箱/账户直接写进README或仓库。

---

## 附录 A. 图片生成语义（仅供未来 AI 抠图接入参考）

当前 V1 **不**调用图片生成模型。外部工具将商品展示/场景图提取为纯平面 POD 印花，常用提示词语义如下：保留原有花卉、动物、文字、纹样、颜色与布局；展平褶皱/透视；去除袋子轮廓、抽绳、包边、道具、模特、光影与材质；补全遮挡和边缘，尽量忠实原款，不擅自换色/改字/重排；按任务指定比例铺满画布，不留白边；不自动换白色背景。

**这只是判重项目中的来源图与成品图业务定义，不是本V1必须生成的图片或Prompt功能。**

## 附录 B. 规格来源与变更原则

- 本文件合并此前全部对话的最终决定，以第0章的F01—F12覆盖早期相反想法；当前 F03 已按用户后续确认恢复为「来源与 POD 统一时间戳重命名」，其余如按来源日期归档、不同输出比例按同款直接删仍不采用。
- 早期曾讨论「由新系统直接调用AI生成、质量评分、多候选、多模型接力」，现阶段已被明确**移出V1**；不得混入核心需求。
- 已取消普通云盘上传去重、单一感知哈希百分比定删方式；pHash只是低成本候选召回之一。
- 对模型效果没有虚构的百分比准确率承诺；复杂视觉自动删默认关闭直到实际审核验证，系统必须能显示因模型不可用而漏掉的判断能力。
- 本规格覆盖已经确认的操作决策，剩余只是可由工程师按不误删原则决定并记录的内部技术实现；如出现新的业务冲突，向用户说明影响再改变规格版本。
