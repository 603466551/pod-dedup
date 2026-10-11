<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import axios from "axios";
import { createTask, listTasks, type Task } from "./api/tasks";

const form = reactive({ sourceBatch: "", sourceLibrary: "", podPending: "", podLibrary: "", cropRatio: "1x1", cropStartDate: "", cropEndDate: "", dryRun: false });
const tasks = ref<Task[]>([]);
type ReviewImage = { id: string; filename: string; width: number | null; height: number | null; status: string };
type ReviewRelation = { review_id: string; pair_id: string; version: number; new_image_id: string; match_image_id: string; machine_decision: string; evidence: Record<string, unknown> };
type ReviewGroup = { id: string; task_id: string; seed_review_id: string; images: ReviewImage[]; relations: ReviewRelation[] };
type TaskItem = { id: string; filename?: string; stage: string; status: string; error_code?: string | null; updated_at?: string | null };
type Operation = { id: string; task_id: string | null; operation: string; state: string; reason: string; error?: string | null };
type DuplicateRecord = { id: string; task_id: string; pair_type: string; machine_decision: string; resolution_status: string; new_image?: { filename: string } | null; match_image?: { filename: string } | null; human_decision?: { status: string; duplicate?: string | null; action?: string | null } | null };
type TaskEvent = { id: string; level: string; stage: string; message: string; created_at?: string | null };
type VlmCall = { id: string; task_id: string; provider: string; model: string; status: string; error_code?: string | null };

const reviewGroups = ref<ReviewGroup[]>([]);
const selectedTask = ref<Task | null>(null);
const taskItems = ref<TaskItem[]>([]);
const showAllTaskItems = ref(false);
const taskEvents = ref<TaskEvent[]>([]);
const taskProgress = ref<{ total: number; processed: number; status_counts: Record<string, number>; archive?: { completed: number; total: number; failed: number } } | null>(null);
const operations = ref<Operation[]>([]);
const duplicateRecords = ref<DuplicateRecord[]>([]);
const vlmCalls = ref<VlmCall[]>([]);
const health = ref<Record<string, any>>({});
const runtimeLogs = ref<string[]>([]);
const activePrimary = ref<"workspace" | "tasks" | "system">("workspace");
const activeSection = ref("dedup");
const activeWorkflow = ref<"source" | "pod" | "crop">("source");
const groupKeepIds = reactive<Record<string, string[]>>({});
const groupConfirmDeletes = reactive<Record<string, boolean>>({});
const groupSubmitting = reactive<Record<string, boolean>>({});
const cancellingTaskIds = reactive<Record<string, boolean>>({});
const loading = ref(false);
type DirectoryField = "sourceBatch" | "sourceLibrary" | "podPending" | "podLibrary";
const choosingDirectory = ref<DirectoryField | null>(null);
const lockedDirectories = reactive({ sourceLibrary: false, podLibrary: false });
const settingsForm = reactive({ retrievalTopK: 20, retrievalMinSimilarity: 0.85, appTimezone: "Asia/Shanghai", ratioTolerance: 0.02, sourceVisualRuleValidated: false, sourceVisualAutoDelete: false, vlmEnabled: false, vlmBaseUrl: "", vlmModel: "", vlmApiKey: "", vlmMaxCalls: 100 });
const directoryLabels: Record<DirectoryField, string> = { sourceBatch: "本次来源文件夹", sourceLibrary: "历史源图库", podPending: "POD待处理目录", podLibrary: "历史POD图库" };
const formStorageKey = "pod-dedup.workflow-inputs.v1";
const productionRatios = ref<string[]>(["1x1", "3x4", "4x3", "9x16", "16x9"]);
const newRatio = ref("");
const visibleTaskItems = computed(() => showAllTaskItems.value ? taskItems.value : taskItems.value.slice(0, 10));

function idempotencyKey(): string { return crypto.randomUUID(); }
function formatTime(value?: string | null): string { return value ? value.replace("T", " ").slice(0, 19) : "—"; }
function selectSection(primary: "workspace" | "tasks" | "system", section: string): void { activePrimary.value = primary; activeSection.value = section; }
const pendingReviewCount = computed(() => reviewGroups.value.reduce((total, group) => total + group.relations.length, 0));
function relationScore(relation: ReviewRelation): string { return String(relation.evidence?.cosine_similarity ?? "—"); }
function relationVlmStatus(relation: ReviewRelation): string { return String(relation.evidence?.vlm_status ?? "未调用或已返回结构化结果"); }
function imageLabel(group: ReviewGroup, imageId: string): string { return group.images.find((image) => image.id === imageId)?.filename ?? "图片记录缺失"; }
function groupVersions(group: ReviewGroup): Record<string, number> { return Object.fromEntries(group.relations.map((relation) => [relation.review_id, relation.version])); }
function keepIds(group: ReviewGroup): string[] { return groupKeepIds[group.id] ?? group.images.map((image) => image.id); }
async function toggleDirectoryLock(field: "sourceLibrary" | "podLibrary"): Promise<void> {
  const locking = !lockedDirectories[field];
  if (locking && !form[field].trim()) {
    ElMessage.warning(`请先填写${directoryLabels[field]}，再锁定`);
    return;
  }
  const key = field === "sourceLibrary" ? "source_library_locked" : "pod_library_locked";
  const pathKey = field === "sourceLibrary" ? "source_library_dir" : "pod_library_dir";
  try {
    await axios.put("/api/v1/settings", { [key]: locking, [pathKey]: form[field].trim() });
    lockedDirectories[field] = locking;
    ElMessage.success(locking ? "目录已锁定并保存到系统" : "目录已解锁；已保存的默认目录仍会保留");
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail?.message ?? "目录锁定设置保存失败");
  }
}

function restoreForm(): void {
  try {
    const saved = JSON.parse(localStorage.getItem(formStorageKey) ?? "{}");
    if (typeof saved.sourceBatch === "string") form.sourceBatch = saved.sourceBatch;
    if (typeof saved.sourceLibrary === "string") form.sourceLibrary = saved.sourceLibrary;
    if (typeof saved.podPending === "string") form.podPending = saved.podPending;
    if (typeof saved.podLibrary === "string") form.podLibrary = saved.podLibrary;
    if (typeof saved.cropRatio === "string") form.cropRatio = saved.cropRatio;
    if (typeof saved.cropStartDate === "string") form.cropStartDate = saved.cropStartDate;
    if (typeof saved.cropEndDate === "string") form.cropEndDate = saved.cropEndDate;
    if (typeof saved.dryRun === "boolean") form.dryRun = saved.dryRun;
  } catch { /* Invalid browser preferences must never block the application. */ }
}
watch(form, (value) => localStorage.setItem(formStorageKey, JSON.stringify(value)), { deep: true });

async function chooseDirectory(field: DirectoryField): Promise<void> {
  if ((field === "sourceLibrary" || field === "podLibrary") && lockedDirectories[field]) {
    ElMessage.info("该历史图库已锁定，请先点击字段标题后的“解锁”");
    return;
  }
  choosingDirectory.value = field;
  try {
    const response = await axios.post("/api/v1/fs/choose-directory", { initial_path: form[field] || null });
    if (response.data.path) form[field] = response.data.path;
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail?.message ?? "无法打开文件夹选择器，请手动输入路径");
  } finally { choosingDirectory.value = null; }
}

async function refresh(): Promise<void> {
  try {
    tasks.value = await listTasks();
    const pendingGroups = (await axios.get("/api/v1/reviews/groups")).data.items as ReviewGroup[];
    reviewGroups.value = pendingGroups;
    for (const group of pendingGroups) {
      if (!groupKeepIds[group.id]) groupKeepIds[group.id] = group.images.map((image) => image.id);
    }
    const { data: systemSettings } = await axios.get("/api/v1/settings");
    settingsForm.retrievalTopK = systemSettings.retrieval_top_k;
    settingsForm.retrievalMinSimilarity = systemSettings.retrieval_candidate_min_similarity;
    settingsForm.sourceVisualRuleValidated = systemSettings.source_visual_rule_validated;
    settingsForm.sourceVisualAutoDelete = systemSettings.source_visual_auto_delete;
    settingsForm.appTimezone = systemSettings.app_timezone;
    settingsForm.ratioTolerance = systemSettings.ratio_rel_tolerance;
    settingsForm.vlmEnabled = systemSettings.vlm_enabled;
    settingsForm.vlmBaseUrl = systemSettings.vlm_base_url ?? "";
    settingsForm.vlmModel = systemSettings.vlm_model ?? "";
    settingsForm.vlmMaxCalls = systemSettings.vlm_max_calls_per_task;
    productionRatios.value = systemSettings.production_ratio_codes ?? productionRatios.value;
    lockedDirectories.sourceLibrary = Boolean(systemSettings.source_library_locked);
    lockedDirectories.podLibrary = Boolean(systemSettings.pod_library_locked);
    if (lockedDirectories.sourceLibrary || !form.sourceLibrary) form.sourceLibrary = systemSettings.source_library_dir ?? "";
    if (lockedDirectories.podLibrary || !form.podLibrary) form.podLibrary = systemSettings.pod_library_dir ?? "";
    if (!form.podPending) form.podPending = systemSettings.pod_pending_dir ?? "";
    operations.value = (await axios.get("/api/v1/operations")).data.items as Operation[];
    duplicateRecords.value = (await axios.get("/api/v1/duplicate-records")).data.items as DuplicateRecord[];
    vlmCalls.value = (await axios.get("/api/v1/logs/vlm-calls")).data.items as VlmCall[];
    health.value = (await axios.get("/api/v1/health")).data;
    runtimeLogs.value = (await axios.get("/api/v1/logs/runtime?lines=100")).data.items as string[];
    if (selectedTask.value) await loadTaskProgress(selectedTask.value.task_id, false);
  } catch { /* The health view itself will reveal unavailable services. */ }
}

async function saveSettings(): Promise<void> {
  try {
    const payload: Record<string, unknown> = { retrieval_top_k: settingsForm.retrievalTopK, retrieval_candidate_min_similarity: settingsForm.retrievalMinSimilarity, app_timezone: settingsForm.appTimezone, ratio_rel_tolerance: settingsForm.ratioTolerance, source_visual_rule_validated: settingsForm.sourceVisualRuleValidated, source_visual_auto_delete: settingsForm.sourceVisualAutoDelete, vlm_enabled: settingsForm.vlmEnabled, vlm_base_url: settingsForm.vlmBaseUrl || null, vlm_model: settingsForm.vlmModel || null, vlm_max_calls_per_task: settingsForm.vlmMaxCalls };
    if (form.sourceLibrary) payload.source_library_dir = form.sourceLibrary;
    if (form.podLibrary) payload.pod_library_dir = form.podLibrary;
    if (form.podPending) payload.pod_pending_dir = form.podPending;
    if (settingsForm.vlmApiKey) payload.vlm_api_key = settingsForm.vlmApiKey;
    await axios.put("/api/v1/settings", payload);
    settingsForm.vlmApiKey = "";
    ElMessage.success("设置已保存，仅影响新任务");
    await refresh();
  } catch (error: any) { ElMessage.error(error?.response?.data?.detail?.message ?? "设置保存失败"); }
}

async function addProductionRatio(): Promise<void> {
  if (!newRatio.value.trim()) return;
  try {
    const { data } = await axios.put("/api/v1/settings", { production_ratio_codes: [...productionRatios.value, newRatio.value] });
    productionRatios.value = data.production_ratio_codes;
    form.cropRatio = productionRatios.value.at(-1) ?? form.cropRatio;
    newRatio.value = "";
    ElMessage.success("新比例已保存，可用于后续裁切任务");
  } catch (error: any) { ElMessage.error(error?.response?.data?.detail?.message ?? "新增比例失败"); }
}

function onSourceVisualValidationChange(validated: boolean): void { if (!validated) settingsForm.sourceVisualAutoDelete = false; }

async function decideGroup(group: ReviewGroup, decision: "DUPLICATE_KEEP_ALL" | "NOT_DUPLICATE_KEEP_ALL" | "DELETE_UNSELECTED"): Promise<void> {
  const selectedKeepIds = keepIds(group);
  if (decision === "DELETE_UNSELECTED" && !groupConfirmDeletes[group.id]) { ElMessage.warning("请先勾选永久删除二次确认"); return; }
  if (decision === "DELETE_UNSELECTED" && (selectedKeepIds.length === 0 || selectedKeepIds.length === group.images.length)) {
    ElMessage.warning("请至少保留一张图片，并取消至少一张图片的“保留”选择");
    return;
  }
  if (groupSubmitting[group.id]) return;
  groupSubmitting[group.id] = true;
  let submitted = false;
  try {
    await axios.post(`/api/v1/reviews/${group.seed_review_id}/group-decision`, { decision, keep_image_ids: selectedKeepIds.map(Number), confirm_delete: Boolean(groupConfirmDeletes[group.id]), versions: groupVersions(group) });
    submitted = true;
    ElMessage.success("候选审核组已完成，列表已更新");
    await refresh();
  } catch (error: any) {
    if (submitted) {
      ElMessage.warning("审核已提交，但刷新列表失败；请稍后刷新页面确认最新状态");
      return;
    }
    if (["REVIEW_GROUP_NOT_PENDING", "REVIEW_VERSION_CONFLICT"].includes(error?.response?.data?.detail?.code)) {
      ElMessage.info("审核组已被其它操作更新，已刷新最新列表"); await refresh();
    } else ElMessage.error(error?.response?.data?.detail?.message ?? "审核提交失败，请刷新后重试");
  } finally { groupSubmitting[group.id] = false; }
}

function deferGroup(): void { ElMessage.info("该候选组保持待审核状态，未执行文件操作"); }

async function submit(kind: "source-dedup" | "source-organize" | "pod-dedup" | "pod-crop"): Promise<void> {
  const required: DirectoryField[] = kind === "pod-dedup" ? ["podPending", "podLibrary"] : kind === "pod-crop" ? ["podLibrary"] : ["sourceBatch", "sourceLibrary"];
  const missing = required.filter((field) => !form[field].trim()).map((field) => directoryLabels[field]);
  if (missing.length) { ElMessage.error(`请先选择或填写：${missing.join("、")}`); return; }
  loading.value = true;
  try {
    const sourceCommon = { source_batch_dir: form.sourceBatch, source_library_dir: form.sourceLibrary, idempotency_key: idempotencyKey() };
    const payload = kind === "source-dedup" ? { ...sourceCommon, dry_run: form.dryRun } : kind === "source-organize" ? sourceCommon : kind === "pod-dedup" ? { pod_pending_dir: form.podPending, pod_library_dir: form.podLibrary, dry_run: form.dryRun, idempotency_key: idempotencyKey() } : { pod_library_dir: form.podLibrary, ratio_code: form.cropRatio, start_date: form.cropStartDate, end_date: form.cropEndDate, dry_run: form.dryRun, idempotency_key: idempotencyKey() };
    const type = kind === "source-dedup" ? "SOURCE_DEDUP" : kind === "source-organize" ? "SOURCE_ORGANIZE" : kind === "pod-dedup" ? "POD_DEDUP" : "POD_CROP";
    const validation = (await axios.post("/api/v1/tasks/validate", { type, ...payload })).data;
    if (validation.warnings?.length) ElMessage.warning(validation.warnings.join("；"));
    const task = await createTask(kind, payload);
    ElMessage.success(`任务 ${task.task_id} 已创建`);
    await refresh();
    await showTask(task);
    selectSection("tasks", "current-task");
  } catch (error: any) { ElMessage.error(error?.response?.data?.detail?.message ?? "任务创建失败，请检查目录与服务状态"); }
  finally { loading.value = false; }
}

async function showTask(task: Task): Promise<void> { selectedTask.value = task; showAllTaskItems.value = false; await loadTaskProgress(task.task_id, true); }
function taskCanBeCancelled(task: Task | null): boolean {
  return Boolean(task && !["DONE", "PARTIAL_COMPLETED", "FAILED", "CANCELLED"].includes(task.status));
}
async function cancelTask(task: Task): Promise<void> {
  if (!taskCanBeCancelled(task) || cancellingTaskIds[task.task_id]) return;
  if (!window.confirm(`取消任务 #${task.task_id}？系统将停止后续处理；已经完成的移动、删除或裁切不会回滚。`)) return;
  cancellingTaskIds[task.task_id] = true;
  try {
    await axios.post(`/api/v1/tasks/${task.task_id}/cancel`);
    ElMessage.success("已请求取消任务；当前单图操作结束后将停止");
    await refresh();
    await loadTaskProgress(task.task_id, false);
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail?.message ?? "取消任务失败，请刷新后重试");
  } finally { cancellingTaskIds[task.task_id] = false; }
}
async function loadTaskProgress(taskId: string, showError: boolean): Promise<void> {
  try {
    const { data } = await axios.get(`/api/v1/tasks/${taskId}/progress`);
    selectedTask.value = data.task as Task;
    taskProgress.value = data.summary;
    taskItems.value = data.items as TaskItem[];
    taskEvents.value = data.events as TaskEvent[];
  } catch { if (showError) ElMessage.error("无法读取任务进度"); }
}
function downloadDiagnostic(): void { window.location.assign(`/api/v1/logs/diagnostic${selectedTask.value ? `?task_id=${selectedTask.value.task_id}` : ""}`); }
async function rebuildIndexes(): Promise<void> {
  try {
    const task = await axios.post("/api/v1/indexes/rebuild", { idempotency_key: idempotencyKey() });
    ElMessage.success(`索引重建任务 ${task.data.task_id} 已创建`); await refresh();
  } catch (error: any) { ElMessage.error(error?.response?.data?.detail?.message ?? "索引重建任务创建失败"); }
}

let refreshTimer: number | undefined;
onMounted(() => { restoreForm(); void refresh(); refreshTimer = window.setInterval(() => void refresh(), 2500); });
onUnmounted(() => { if (refreshTimer) window.clearInterval(refreshTimer); });
</script>

<template>
  <el-container class="app-shell">
    <el-header class="topbar">
      <div class="brand"><span class="brand-mark">P</span><span>POD 图片去重与归档</span></div>
      <nav class="primary-nav">
        <el-button text :class="{ active: activePrimary === 'workspace' }" @click="selectSection('workspace', 'dedup')">工作台</el-button>
        <el-button text :class="{ active: activePrimary === 'tasks' }" @click="selectSection('tasks', 'task-list')">任务与审核</el-button>
        <el-button text :class="{ active: activePrimary === 'system' }" @click="selectSection('system', 'health')">系统</el-button>
      </nav>
      <div class="top-status"><el-tag size="small" :type="health.database === 'ready' ? 'success' : 'warning'">MySQL {{ health.database ?? '检测中' }}</el-tag><el-tag size="small" :type="health.worker === 'READY' ? 'success' : 'warning'">Worker {{ health.worker ?? '检测中' }}</el-tag></div>
    </el-header>
    <el-container>
      <el-aside width="208px" class="side-nav">
        <div v-if="activePrimary === 'workspace'" class="menu-group"><p>图片去重</p><el-menu :default-active="activeSection"><el-menu-item index="dedup" @click="selectSection('workspace', 'dedup')">去重工作台</el-menu-item></el-menu></div>
        <div v-if="activePrimary === 'tasks'" class="menu-group"><p>任务中心</p><el-menu :default-active="activeSection"><el-menu-item index="task-list" @click="selectSection('tasks', 'task-list')">全部任务</el-menu-item><el-menu-item index="current-task" @click="selectSection('tasks', 'current-task')">当前任务进度</el-menu-item><el-menu-item index="reviews" @click="selectSection('tasks', 'reviews')">人工审核 <el-badge v-if="pendingReviewCount" :value="pendingReviewCount" /></el-menu-item><el-menu-item index="records" @click="selectSection('tasks', 'records')">去重与操作记录</el-menu-item></el-menu></div>
        <div v-if="activePrimary === 'system'" class="menu-group"><p>系统管理</p><el-menu :default-active="activeSection"><el-menu-item index="health" @click="selectSection('system', 'health')">服务健康</el-menu-item><el-menu-item index="logs" @click="selectSection('system', 'logs')">运行日志与诊断</el-menu-item><el-menu-item index="settings" @click="selectSection('system', 'settings')">系统设置</el-menu-item><el-menu-item index="ai" @click="selectSection('system', 'ai')">AI抠图说明</el-menu-item></el-menu></div>
      </el-aside>
      <el-main class="content">
        <section v-if="activeSection === 'dedup'">
          <div class="page-heading"><div><h1>去重工作台</h1><p>任务在后台 Worker 中执行。提交后会自动进入“当前任务进度”。</p></div></div>
          <el-alert title="外部 AI 抠图继续使用现有工具；本系统不会调用图片生成模型。POD 候选进入人工审核，最后一条审核结束后统一归档。" type="info" :closable="false" />
          <el-card class="panel workflow-panel">
            <el-tabs v-model="activeWorkflow">
              <el-tab-pane label="来源图片流程" name="source"><el-alert title="来源去重只使用本次来源文件夹和历史源图库。" type="info" :closable="false" /><el-form label-position="top" class="form-grid"><el-form-item label="本次来源文件夹（必填）"><el-input v-model="form.sourceBatch" clearable placeholder="执行端可访问的绝对路径"><template #append><el-button :loading="choosingDirectory === 'sourceBatch'" @click="chooseDirectory('sourceBatch')">浏览</el-button></template></el-input></el-form-item><el-form-item><template #label>历史源图库（必填）<el-button link size="small" class="directory-lock" :type="lockedDirectories.sourceLibrary ? 'success' : 'info'" @click="toggleDirectoryLock('sourceLibrary')">{{ lockedDirectories.sourceLibrary ? '已锁定 · 解锁' : '锁定' }}</el-button></template><el-input v-model="form.sourceLibrary" :disabled="lockedDirectories.sourceLibrary" clearable placeholder="执行端可访问的绝对路径"><template #append><el-button :disabled="lockedDirectories.sourceLibrary" :loading="choosingDirectory === 'sourceLibrary'" @click="chooseDirectory('sourceLibrary')">浏览</el-button></template></el-input></el-form-item><el-checkbox v-model="form.dryRun">仅检测模式（不移动、不删除）</el-checkbox><div class="actions"><el-button type="primary" :loading="loading" @click="submit('source-dedup')">开始来源去重</el-button><el-button :loading="loading" @click="submit('source-organize')">整理已处理来源图</el-button></div></el-form></el-tab-pane>
              <el-tab-pane label="POD 图片流程（MJ 直入）" name="pod"><el-alert title="本流程只负责把所有比例的原始 POD 去重后归档到历史 POD 图库根目录；不裁切、不按比例过滤。" type="success" :closable="false" /><el-form label-position="top" class="form-grid"><el-form-item label="POD待处理目录（必填）"><el-input v-model="form.podPending" clearable placeholder="执行端可访问的绝对路径"><template #append><el-button :loading="choosingDirectory === 'podPending'" @click="chooseDirectory('podPending')">浏览</el-button></template></el-input></el-form-item><el-form-item><template #label>历史POD图库（必填）<el-button link size="small" class="directory-lock" :type="lockedDirectories.podLibrary ? 'success' : 'info'" @click="toggleDirectoryLock('podLibrary')">{{ lockedDirectories.podLibrary ? '已锁定 · 解锁' : '锁定' }}</el-button></template><el-input v-model="form.podLibrary" :disabled="lockedDirectories.podLibrary" clearable placeholder="执行端可访问的绝对路径"><template #append><el-button :disabled="lockedDirectories.podLibrary" :loading="choosingDirectory === 'podLibrary'" @click="chooseDirectory('podLibrary')">浏览</el-button></template></el-input></el-form-item><el-checkbox v-model="form.dryRun">仅检测模式（不移动、不删除）</el-checkbox><div class="actions"><el-button type="success" :loading="loading" @click="submit('pod-dedup')">开始POD去重并入库</el-button></div></el-form></el-tab-pane>
              <el-tab-pane label="POD 裁切与生产素材" name="crop"><el-alert title="按历史原图文件名的日期范围筛选，居中裁切到目标比例；原图不会修改，结果写入 Production 目录。" type="warning" :closable="false" /><el-form label-position="top" class="form-grid"><el-form-item label="时间范围（YYYYMMDD）"><div class="actions"><el-input v-model="form.cropStartDate" placeholder="开始，例如 20261001" /><span>至</span><el-input v-model="form.cropEndDate" placeholder="结束，例如 20261008" /></div></el-form-item><el-form-item label="输出比例"><div class="actions"><el-select v-model="form.cropRatio"><el-option v-for="item in productionRatios" :key="item" :label="item.replace('x', ':')" :value="item" /></el-select><el-input v-model="newRatio" placeholder="新增，如 2:3" @keyup.enter="addProductionRatio" /><el-button @click="addProductionRatio">新增比例</el-button></div></el-form-item><el-alert title="输出目录：历史POD图库\Production\比例\执行日期\；不做二次去重。" type="info" :closable="false" /><el-checkbox v-model="form.dryRun">仅检测模式（不写入裁切图）</el-checkbox><div class="actions"><el-button type="warning" :loading="loading" @click="submit('pod-crop')">开始裁切生产素材</el-button></div></el-form></el-tab-pane>
            </el-tabs>
          </el-card>
        </section>

        <section v-if="activeSection === 'task-list'"><div class="page-heading"><div><h1>任务中心</h1><p>每 2.5 秒自动刷新。点击“查看进度”查看逐图处理和事件。</p></div><el-button @click="refresh">立即刷新</el-button></div><el-table :data="tasks" class="panel"><el-table-column prop="task_id" label="任务ID" width="90" /><el-table-column prop="type" label="类型" width="150" /><el-table-column prop="status" label="状态" width="150" /><el-table-column label="创建时间" width="176"><template #default="scope">{{ formatTime(scope.row.created_at) }}</template></el-table-column><el-table-column label="开始 / 结束" width="235"><template #default="scope">{{ formatTime(scope.row.started_at) }}<br>{{ formatTime(scope.row.finished_at) }}</template></el-table-column><el-table-column label="进度"><template #default="scope">已处理 {{ scope.row.counters.processed ?? 0 }} · 删除 {{ scope.row.counters.deleted ?? 0 }} · 归档 {{ scope.row.counters.archived ?? 0 }} · 待审 {{ scope.row.counters.waiting_review ?? 0 }} · 错误 {{ scope.row.counters.errors ?? 0 }}</template></el-table-column><el-table-column label="操作" width="170"><template #default="scope"><el-button link type="primary" @click="showTask(scope.row); selectSection('tasks', 'current-task')">查看进度</el-button><el-button v-if="taskCanBeCancelled(scope.row)" link type="danger" :loading="cancellingTaskIds[scope.row.task_id]" @click="cancelTask(scope.row)">取消</el-button></template></el-table-column></el-table></section>

        <section v-if="activeSection === 'current-task'"><div class="page-heading"><div><h1>当前任务进度</h1><p>自动刷新；上方汇总统计与下方最近更新记录分别展示，不按同一顺序逐行对应。</p></div><div class="actions"><el-button v-if="selectedTask && taskCanBeCancelled(selectedTask)" type="danger" :loading="cancellingTaskIds[selectedTask.task_id]" @click="cancelTask(selectedTask)">取消任务</el-button><el-button @click="selectedTask && loadTaskProgress(selectedTask.task_id, true)">刷新当前任务</el-button></div></div><el-empty v-if="!selectedTask" description="请先在任务中心选择一个任务" /><template v-else><el-card class="panel"><el-descriptions :column="3" border><el-descriptions-item label="任务">#{{ selectedTask.task_id }} · {{ selectedTask.type }}</el-descriptions-item><el-descriptions-item label="状态">{{ selectedTask.status }}</el-descriptions-item><el-descriptions-item label="创建时间">{{ formatTime(selectedTask.created_at) }}</el-descriptions-item><el-descriptions-item label="开始时间">{{ formatTime(selectedTask.started_at) }}</el-descriptions-item><el-descriptions-item label="结束时间">{{ formatTime(selectedTask.finished_at) }}</el-descriptions-item><el-descriptions-item label="当前项数">{{ taskProgress?.total ?? 0 }}</el-descriptions-item></el-descriptions><div class="progress-counts"><el-tag v-for="(count, status) in taskProgress?.status_counts ?? {}" :key="status">{{ status }} {{ count }}</el-tag></div><el-alert v-if="selectedTask.warnings.length" :title="selectedTask.warnings.join('；')" type="warning" :closable="false" /></el-card><el-card class="panel"><template #header>任务事件</template><el-timeline><el-timeline-item v-for="event in taskEvents" :key="event.id" :timestamp="formatTime(event.created_at)" :type="event.level === 'ERROR' ? 'danger' : event.level === 'WARNING' ? 'warning' : 'primary'"><b>{{ event.stage }}</b> · {{ event.message }}</el-timeline-item></el-timeline></el-card><el-card class="panel"><template #header><div class="task-items-header"><span>清单判定完成（{{ taskProgress?.processed ?? 0 }}/{{ taskProgress?.total ?? 0 }}）</span><el-button v-if="taskItems.length > 10" link type="primary" @click="showAllTaskItems = !showAllTaskItems">{{ showAllTaskItems ? '收起详情' : `查看全部 ${taskItems.length} 项` }}</el-button></div></template><p class="table-hint">以下为最近更新记录；人工审核结束后的统一归档会持续更新文件状态，不会改变上方的清单判定完成数。</p><p v-if="taskProgress?.archive" class="table-hint">统一归档（{{ taskProgress.archive.completed }}/{{ taskProgress.archive.total }}）<template v-if="taskProgress.archive.failed"> · 归档失败 {{ taskProgress.archive.failed }}</template></p><el-table :data="visibleTaskItems"><el-table-column prop="filename" label="最近更新文件" /><el-table-column prop="stage" label="阶段" width="180" /><el-table-column prop="status" label="当前状态" width="180" /><el-table-column label="最近更新时间" width="176"><template #default="scope">{{ formatTime(scope.row.updated_at) }}</template></el-table-column><el-table-column prop="error_code" label="错误代码" /></el-table></el-card></template></section>

        <section v-if="activeSection === 'reviews'"><div class="page-heading"><div><h1>人工审核</h1><p>关联候选合并展示；图片对数量仍以红色数字统计。选择保留图后可批量删除其余图片。</p></div><el-button @click="refresh">刷新审核列表</el-button></div><el-empty v-if="!reviewGroups.length" description="当前没有待审核候选组" /><el-card v-for="group in reviewGroups" :key="group.id" class="panel review-card"><template #header>候选审核组 · 任务 #{{ group.task_id }} · {{ group.images.length }} 张图片 · {{ group.relations.length }} 条候选关系</template><el-alert title="这是机器候选关联组，不代表组内图片已被系统判定为全部重复；删除仅按你的选择执行。" type="info" :closable="false" /><div class="comparison review-grid"><figure v-for="image in group.images" :key="image.id"><img :src="`/api/v1/images/${image.id}/preview`" :alt="image.filename" /><figcaption>{{ image.filename }}（{{ image.width }}×{{ image.height }}）<br><el-checkbox v-model="groupKeepIds[group.id]" :label="image.id" :disabled="groupSubmitting[group.id]">保留此图</el-checkbox></figcaption></figure></div><el-descriptions :column="1" size="small" border><el-descriptions-item v-for="relation in group.relations" :key="relation.review_id" label="候选关系">{{ imageLabel(group, relation.new_image_id) }} ↔ {{ imageLabel(group, relation.match_image_id) }} · {{ relation.machine_decision }} · 相似度 {{ relationScore(relation) }} · VLM：{{ relationVlmStatus(relation) }}</el-descriptions-item></el-descriptions><el-checkbox v-model="groupConfirmDeletes[group.id]" :disabled="groupSubmitting[group.id]">我确认永久删除未勾选“保留”的图片，无法恢复高清原图</el-checkbox><div class="actions"><el-button type="danger" :loading="groupSubmitting[group.id]" :disabled="groupSubmitting[group.id]" @click="decideGroup(group, 'DELETE_UNSELECTED')">重复，删除未保留图片</el-button><el-button :disabled="groupSubmitting[group.id]" @click="decideGroup(group, 'DUPLICATE_KEEP_ALL')">重复，全部保留</el-button><el-button :disabled="groupSubmitting[group.id]" @click="decideGroup(group, 'NOT_DUPLICATE_KEEP_ALL')">不是重复，全部保留</el-button><el-button :disabled="groupSubmitting[group.id]" @click="deferGroup">暂不确定</el-button></div></el-card></section>

        <section v-if="activeSection === 'records'"><div class="page-heading"><div><h1>去重与文件操作记录</h1><p>审计记录与任务日志可按任务查看；此处显示最近记录。</p></div></div><el-card class="panel"><template #header>重复关系</template><el-table :data="duplicateRecords"><el-table-column prop="task_id" label="任务" /><el-table-column prop="pair_type" label="关系" /><el-table-column label="图片对"><template #default="scope">{{ scope.row.new_image?.filename ?? '-' }} ↔ {{ scope.row.match_image?.filename ?? '-' }}</template></el-table-column><el-table-column prop="machine_decision" label="机器判断" /><el-table-column prop="resolution_status" label="处理结果" /><el-table-column label="人工决定"><template #default="scope">{{ scope.row.human_decision?.duplicate ?? '-' }} / {{ scope.row.human_decision?.action ?? '-' }}</template></el-table-column></el-table></el-card><el-card class="panel"><template #header>文件操作</template><el-table :data="operations"><el-table-column prop="task_id" label="任务" /><el-table-column prop="operation" label="操作" /><el-table-column prop="reason" label="原因" /><el-table-column prop="state" label="状态" /><el-table-column prop="error" label="异常" /></el-table></el-card><el-card class="panel"><template #header>VLM 调用审计</template><el-table :data="vlmCalls"><el-table-column prop="task_id" label="任务" /><el-table-column prop="provider" label="Provider" /><el-table-column prop="model" label="模型" /><el-table-column prop="status" label="调用状态" /><el-table-column prop="error_code" label="异常码" /></el-table></el-card></section>

        <section v-if="activeSection === 'health'"><div class="page-heading"><div><h1>服务健康</h1><p>用于确认 API、MySQL、后台 Worker、模型和索引是否处于可工作状态。</p></div><el-button @click="refresh">刷新</el-button></div><el-card class="panel"><el-descriptions :column="3" border><el-descriptions-item label="API">{{ health.api ?? '检测中' }}</el-descriptions-item><el-descriptions-item label="MySQL">{{ health.database ?? '检测中' }}</el-descriptions-item><el-descriptions-item label="Worker">{{ health.worker ?? '检测中' }}</el-descriptions-item><el-descriptions-item label="DINOv2">{{ health.visual ?? '检测中' }}</el-descriptions-item><el-descriptions-item label="FAISS / 源整图">{{ health.faiss?.SOURCE_FULL ?? '检测中' }}</el-descriptions-item><el-descriptions-item label="FAISS / 源印花">{{ health.faiss?.SOURCE_PRINT ?? '检测中' }}</el-descriptions-item><el-descriptions-item label="FAISS / POD">{{ health.faiss?.POD_FULL ?? '检测中' }}</el-descriptions-item><el-descriptions-item label="VLM">{{ health.vlm ?? '检测中' }}</el-descriptions-item><el-descriptions-item label="运行日志">{{ health.runtime_log ?? '检测中' }}（保留 {{ health.log_retention_days ?? 14 }} 天）</el-descriptions-item><el-descriptions-item label="历史源图库目录">{{ health.directories?.source_library ?? '未配置' }}</el-descriptions-item><el-descriptions-item label="POD待处理目录">{{ health.directories?.pod_pending ?? '未配置' }}</el-descriptions-item><el-descriptions-item label="历史POD图库目录">{{ health.directories?.pod_library ?? '未配置' }}</el-descriptions-item></el-descriptions><p v-if="health.worker_last_seen">Worker 最近心跳：{{ formatTime(health.worker_last_seen) }}</p></el-card></section>

        <section v-if="activeSection === 'logs'"><div class="page-heading"><div><h1>运行日志与诊断</h1><p>下载的诊断 JSON 不包含真实路径、图片名或密钥，可直接发给我定位问题。</p></div><div class="actions"><el-button @click="refresh">刷新日志</el-button><el-button type="primary" @click="downloadDiagnostic">下载{{ selectedTask ? `任务 #${selectedTask.task_id} ` : '' }}诊断日志</el-button></div></div><el-card class="panel"><template #header>最近运行日志</template><pre class="runtime-log">{{ runtimeLogs.join('\n') || '尚未写入运行日志。启动 API 或 Worker 后刷新此处。' }}</pre></el-card></section>

        <section v-if="activeSection === 'settings'"><div class="page-heading"><div><h1>系统设置</h1><p>设置仅影响新创建的任务；VLM 密钥只写入，不会回显。</p></div></div><el-form label-position="top" class="settings-form panel" @submit.prevent="saveSettings"><el-form-item label="分类日期时区（IANA）"><el-input v-model="settingsForm.appTimezone" placeholder="Asia/Shanghai" /></el-form-item><el-form-item label="比例相对容差"><el-input-number v-model="settingsForm.ratioTolerance" :min="0" :max="0.2" :step="0.005" /></el-form-item><el-form-item label="每索引候选数"><el-input-number v-model="settingsForm.retrievalTopK" :min="1" :max="100" /></el-form-item><el-form-item label="候选最低相似度（只限制审核候选量，不是删除阈值）"><el-input-number v-model="settingsForm.retrievalMinSimilarity" :min="-1" :max="1" :step="0.01" /></el-form-item><el-alert title="来源视觉自动删除默认关闭；相似度或一次 VLM 回答都不会单独删除图片。" type="warning" :closable="false" /><el-checkbox v-model="settingsForm.sourceVisualRuleValidated" @change="onSourceVisualValidationChange">我确认已用实际人工审核样本验证来源高确定规则</el-checkbox><el-checkbox v-model="settingsForm.sourceVisualAutoDelete" :disabled="!settingsForm.sourceVisualRuleValidated">启用来源高确定视觉自动删除（永久删除）</el-checkbox><el-checkbox v-model="settingsForm.vlmEnabled">启用 VLM 结构化对图</el-checkbox><el-form-item label="VLM Base URL"><el-input v-model="settingsForm.vlmBaseUrl" placeholder="兼容 OpenAI Chat Completions 的地址" /></el-form-item><el-form-item label="VLM 模型"><el-input v-model="settingsForm.vlmModel" /></el-form-item><el-form-item label="每任务 VLM 成功调用上限"><el-input-number v-model="settingsForm.vlmMaxCalls" :min="0" :max="10000" /></el-form-item><el-form-item label="VLM API Key（只写入，不回显）"><el-input v-model="settingsForm.vlmApiKey" type="password" show-password /></el-form-item><div class="actions"><el-button type="primary" @click="saveSettings">保存设置</el-button><el-button @click="rebuildIndexes">建立/重建三类索引</el-button></div></el-form></section>

        <section v-if="activeSection === 'ai'"><div class="page-heading"><div><h1>AI抠图说明</h1></div></div><el-alert title="V1 沿用现有外部 AI 抠图工具。本系统不调用图片生成模型；成功图由外部工具移入“已处理”后，可在来源图片流程中选择“整理已处理来源图”。" type="info" :closable="false" /></section>
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.app-shell { min-height: 100vh; background: #f3f5f7; color: #1f2937; }
.topbar { display: flex; align-items: center; gap: 28px; height: 58px; padding: 0 24px; background: #fff; border-bottom: 1px solid #e5e7eb; }
.brand { display: flex; align-items: center; gap: 10px; min-width: 250px; font-size: 17px; font-weight: 650; color: #1b2533; }.brand-mark { display: grid; place-items: center; width: 27px; height: 27px; color: #fff; background: #26824b; border-radius: 7px; }.primary-nav { display: flex; gap: 6px; height: 100%; align-items: center; }.primary-nav .el-button { height: 58px; border-radius: 0; color: #4b5563; }.primary-nav .el-button.active { color: #21713f; border-bottom: 3px solid #2d8a4e; }.top-status { display: flex; gap: 8px; margin-left: auto; }
.side-nav { min-height: calc(100vh - 58px); padding: 18px 10px; background: #fff; border-right: 1px solid #e5e7eb; }.menu-group p { margin: 8px 12px; color: #9ca3af; font-size: 12px; }.side-nav :deep(.el-menu) { border-right: 0; }.side-nav :deep(.el-menu-item) { height: 42px; line-height: 42px; margin: 3px 0; border-radius: 6px; }.side-nav :deep(.el-menu-item.is-active) { color: #21713f; background: #e9f6ed; }
.content { padding: 26px 30px 50px; max-width: 1800px; }.page-heading { display: flex; justify-content: space-between; align-items: center; gap: 18px; margin-bottom: 18px; }.page-heading h1 { margin: 0 0 6px; font-size: 22px; }.page-heading p { margin: 0; color: #6b7280; font-size: 14px; }.panel { margin: 16px 0; background: #fff; border-radius: 8px; box-shadow: 0 1px 3px rgb(0 0 0 / 5%); }.workflow-panel { max-width: 920px; }.form-grid { padding-top: 12px; }.directory-lock { margin-left: 8px; vertical-align: baseline; }.actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 16px; }.progress-counts { display: flex; flex-wrap: wrap; gap: 8px; margin: 16px 0; }.task-items-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; }.review-card :deep(.el-card__body) { padding-top: 14px; }.comparison { display: flex; gap: 18px; flex-wrap: wrap; margin: 16px 0; }.comparison figure { width: min(430px, 100%); margin: 0; background: #fafafa; padding: 10px; border: 1px solid #edf0f2; }.review-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); align-items: start; }.review-grid figure { width: auto; }.comparison img { width: 100%; max-height: 440px; object-fit: contain; background: #fff; }.comparison figcaption { margin-top: 8px; overflow-wrap: anywhere; color: #4b5563; }.runtime-log { max-height: 520px; overflow: auto; padding: 16px; margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; background: #17202d; color: #d9e2ef; border-radius: 6px; font: 12px/1.6 Consolas, monospace; }.settings-form { max-width: 840px; padding: 20px; } .settings-form :deep(.el-checkbox) { display: flex; margin: 14px 0; }
@media (max-width: 850px) { .brand { min-width: auto; }.top-status { display: none; }.side-nav { width: 160px !important; }.content { padding: 18px; }.topbar { padding: 0 12px; gap: 8px; } }
</style>
