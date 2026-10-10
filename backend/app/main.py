import logging
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.app_logging import configure_runtime_logging
from app.api.health import router as health_router
from app.api.fs import router as fs_router
from app.api.reviews import router as reviews_router
from app.api.operations import router as operations_router
from app.api.indexes import router as indexes_router
from app.api.logs import router as logs_router
from app.api.images import router as images_router
from app.api.settings import router as settings_router
from app.api.duplicate_records import router as duplicate_records_router
from app.api.tasks import router as tasks_router

configure_runtime_logging().getChild("api").info("API initialized")
LOGGER = logging.getLogger("pod_dedup.api")
app = FastAPI(title="POD图片去重与归档管理系统", version="0.1.0")
app.include_router(health_router, prefix="/api/v1")
app.include_router(fs_router, prefix="/api/v1")
app.include_router(reviews_router, prefix="/api/v1")
app.include_router(operations_router, prefix="/api/v1")
app.include_router(indexes_router, prefix="/api/v1")
app.include_router(logs_router, prefix="/api/v1")
app.include_router(images_router, prefix="/api/v1")
app.include_router(settings_router, prefix="/api/v1")
app.include_router(duplicate_records_router, prefix="/api/v1")
app.include_router(tasks_router, prefix="/api/v1")


@app.middleware("http")
async def audit_request(request: Request, call_next):
    started = perf_counter()
    try:
        response = await call_next(request)
    except Exception as error:
        LOGGER.error("http method=%s path=%s error_type=%s", request.method, request.url.path, type(error).__name__)
        raise
    LOGGER.info("http method=%s path=%s status=%s elapsed_ms=%d", request.method, request.url.path, response.status_code, (perf_counter() - started) * 1000)
    return response


@app.exception_handler(Exception)
async def unexpected_error(_: Request, error: Exception):
    LOGGER.error("unhandled_error type=%s", type(error).__name__)
    return JSONResponse(
        status_code=500,
        content={"code": "INTERNAL_ERROR", "message": "服务内部错误，请查看任务日志。", "details": {}},
    )
