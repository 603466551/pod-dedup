from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.models.images import Image, ImageFile

router = APIRouter(prefix="/images", tags=["images"])


def _files(session: Session, image_id: int) -> list[ImageFile]:
    return list(session.scalars(select(ImageFile).where(ImageFile.image_id == image_id).order_by(ImageFile.id)))


@router.get("/{image_id}")
def image_detail(image_id: int, session: Session = Depends(get_session)):
    image = session.get(Image, image_id)
    if image is None:
        raise HTTPException(404, detail={"code": "IMAGE_NOT_FOUND", "message": "图片身份不存在", "details": {}})
    return {"id": str(image.id), "kind": image.kind, "filename": image.original_filename, "width": image.width, "height": image.height, "status": image.status, "files": [{"id": str(file.id), "role": file.role, "status": file.file_status, "ratio_code": file.ratio_code, "archive_date": file.archive_date.isoformat() if file.archive_date else None} for file in _files(session, image_id)]}


@router.get("/{image_id}/preview")
def image_preview(image_id: int, session: Session = Depends(get_session)):
    file = next((entry for entry in _files(session, image_id) if entry.file_status == "PRESENT" and Path(entry.path).is_file()), None)
    if file is None:
        raise HTTPException(404, detail={"code": "IMAGE_FILE_MISSING", "message": "图片文件不存在或已删除", "details": {}})
    return FileResponse(file.path)
