import logging
import socket
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import or_, select

from app.core.db import SessionLocal
from app.core.config import settings
from app.core.app_logging import configure_runtime_logging
from app.core.runtime import write_worker_heartbeat
from app.core.enums import TaskStatus
from app.models.tasks import Task
from app.repositories.tasks import add_event
from app.services.source_organize import organize
from app.services.source_dedup import deduplicate
from app.services.pod_dedup import deduplicate_and_archive
from app.services.pod_crop import crop_production_images
from app.services.task_control import stop_if_cancelled
from app.storage.safe_ops import reconcile_incomplete_operations
from app.indexing.catalog import SOURCE_FULL, SOURCE_PRINT, rebuild_scope_index

LOGGER = logging.getLogger("pod_dedup.worker")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
WORKER_ID = socket.gethostname()


def claim_one_task(session) -> Task | None:
    now = datetime.now(UTC).replace(tzinfo=None)
    task = session.scalar(
        select(Task)
        .where(
            or_(
                Task.status == TaskStatus.CREATED.value,
                (
                    Task.status.in_((TaskStatus.SCANNING.value, TaskStatus.SOURCE_ORGANIZING.value, TaskStatus.POD_SEARCH.value, TaskStatus.ARCHIVING.value, TaskStatus.INDEX_UPDATE.value))
                    & (Task.lease_until.is_not(None))
                    & (Task.lease_until < now)
                ),
            )
        )
        .order_by(Task.id)
        # MySQL 5.7 lacks SKIP LOCKED. M1 is deliberately single-worker, so a
        # regular row lock preserves one-at-a-time claiming without pretending
        # that concurrent workers are supported on this database version.
        .with_for_update()
    )
    if not task:
        return None
    resumed = task.status != TaskStatus.CREATED.value
    task.status = TaskStatus.SCANNING.value
    task.lease_owner = WORKER_ID
    task.lease_until = now + timedelta(minutes=5)
    task.started_at = now
    add_event(session, task, "WARNING" if resumed else "INFO", TaskStatus.SCANNING.value, "Worker恢复过期任务" if resumed else "Worker开始冻结扫描清单")
    session.commit()
    return task


def run_m1_scan(task: Task, session) -> None:
    if stop_if_cancelled(session, task):
        return
    if task.type == "INDEX_REBUILD":
        rebuilt: dict[str, int] = {}
        try:
            for scope in (SOURCE_FULL, SOURCE_PRINT, "POD_FULL"):
                if stop_if_cancelled(session, task):
                    return
                try:
                    store = rebuild_scope_index(session, scope)
                    rebuilt[scope] = int(store.index.ntotal)
                except ValueError:
                    rebuilt[scope] = 0
            task.counters = {**task.counters, "indexes": rebuilt}
            task.status = TaskStatus.DONE.value
            task.finished_at = datetime.now(UTC).replace(tzinfo=None)
            task.lease_until = None
            add_event(session, task, "INFO", task.status, "MySQL持久向量已重建FAISS索引")
        except Exception as error:
            task.status = TaskStatus.FAILED.value
            task.warnings = [*task.warnings, f"索引重建失败：{error}"]
            task.finished_at = datetime.now(UTC).replace(tzinfo=None)
            task.lease_until = None
            add_event(session, task, "ERROR", task.status, "索引重建失败")
        session.commit()
        return
    if task.type == "SOURCE_ORGANIZE":
        task.status = "SOURCE_ORGANIZING"
        session.commit()
        organize(task, session, settings.data_dir / "thumbnails")
        return
    if task.type == "SOURCE_DEDUP":
        task.status = "SCANNING"
        session.commit()
        deduplicate(task, session, settings.data_dir / "thumbnails")
        return
    if task.type == "POD_DEDUP":
        task.status = "SCANNING"
        session.commit()
        deduplicate_and_archive(task, session, settings.data_dir / "thumbnails")
        return
    if task.type == "POD_CROP":
        task.status = "ARCHIVING"
        session.commit()
        crop_production_images(task, session)
        return
    input_dir = task.pod_pending_dir if task.type == "POD_DEDUP" else task.source_batch_dir
    directory = Path(input_dir) if input_dir else None
    if not directory or not directory.exists():
        task.status = TaskStatus.PARTIAL_COMPLETED.value
        task.warnings = [*task.warnings, "待扫描目录不存在，未执行文件操作"]
    else:
        images = [path for path in directory.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS]
        task.counters = {**task.counters, "scanned": len(images)}
        task.status = TaskStatus.DONE.value
    task.finished_at = datetime.now(UTC).replace(tzinfo=None)
    task.lease_until = None
    add_event(session, task, "INFO", task.status, "M1扫描完成；未执行图片删除、移动或归档")
    session.commit()


def _mark_task_failed(task_id: int) -> None:
    """Persist an unexpected task failure in a fresh transaction.

    A task handler may have rolled back its working session, so this boundary
    must not depend on that session remaining usable.
    """
    with SessionLocal() as session:
        task = session.get(Task, task_id)
        if task is None:
            return
        task.status = TaskStatus.FAILED.value
        task.lease_until = None
        task.finished_at = datetime.now(UTC).replace(tzinfo=None)
        task.warnings = [
            *task.warnings,
            "任务执行异常，已停止后续处理；已完成的文件操作可在任务记录中核对。",
        ]
        add_event(session, task, "ERROR", task.status, "任务执行异常，Worker已继续处理其他任务")
        session.commit()


def finish_requested_cancellations() -> int:
    """Finalize requests for tasks that are not currently claimed by this Worker."""
    finished = 0
    with SessionLocal() as session:
        tasks = list(session.scalars(select(Task).where(Task.status == TaskStatus.CANCEL_REQUESTED.value)))
        for task in tasks:
            if stop_if_cancelled(session, task):
                finished += 1
    return finished


def run_one_task() -> bool:
    """Claim and execute one task without letting an unexpected error stop Worker."""
    with SessionLocal() as session:
        task = claim_one_task(session)
        if task is None:
            return False
        task_id = task.id
        try:
            run_m1_scan(task, session)
        except Exception as error:
            session.rollback()
            # Do not log the exception text: it can contain user filesystem paths.
            LOGGER.error("任务 %s 执行异常（%s），已隔离该任务", task_id, type(error).__name__)
            _mark_task_failed(task_id)
        return True


def run_forever(poll_seconds: float = 2.0) -> None:
    configure_runtime_logging()
    LOGGER.info("Worker %s 已启动", WORKER_ID)
    heartbeat_stop = threading.Event()

    def keep_heartbeat_alive() -> None:
        while not heartbeat_stop.wait(2.0):
            write_worker_heartbeat()

    heartbeat_thread = threading.Thread(target=keep_heartbeat_alive, name="worker-heartbeat", daemon=True)
    heartbeat_thread.start()
    try:
        try:
            with SessionLocal() as session:
                recovered = reconcile_incomplete_operations(session)
                if recovered:
                    LOGGER.warning("已核对 %s 条中断文件操作", recovered)
        except Exception as error:
            LOGGER.error("Worker启动恢复失败（%s）；将继续轮询任务", type(error).__name__)
        while True:
            write_worker_heartbeat()
            finish_requested_cancellations()
            run_one_task()
            write_worker_heartbeat()
            time.sleep(poll_seconds)
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=3)


if __name__ == "__main__":
    run_forever()
