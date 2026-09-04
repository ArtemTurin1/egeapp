from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
import shutil
import os
import uuid
from pathlib import Path
from dependencies import get_current_user
from models import User
from config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/upload", tags=["upload"])

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

@router.post("/")
async def upload_file(file: UploadFile = File(...), user: User = Depends(get_current_user)):
    """Загрузка файла (картинка, документ) на сервер."""
    try:
        # Генерируем уникальное имя файла
        ext = os.path.splitext(file.filename or "")[1].lower()
        if not ext:
            ext = ".jpg"
        unique_filename = f"{uuid.uuid4().hex}{ext}"
        file_path = UPLOAD_DIR / unique_filename

        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        logger.info(f"Файл успешно сохранен: {file_path} ({file.filename})")

        # Возвращаем URL-путь к файлу
        file_url = f"/static/uploads/{unique_filename}"
        return {"url": file_url, "filename": file.filename}

    except Exception as e:
        logger.error(f"Upload error: {e}")
        raise HTTPException(status_code=500, detail="Ошибка загрузки файла")
