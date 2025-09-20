from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from ...core.config import get_settings, AppInfo
from ...db.session import get_db

router = APIRouter()


@router.get("/health")
async def health(db: Session = Depends(get_db)):
    settings = get_settings()
    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    return {
        "status": "ok",
        "db_ok": db_ok,
        "app": AppInfo(
            name=settings.app_name,
            environment=settings.environment,
            version="0.1.0",
        ).model_dump(),
    }
