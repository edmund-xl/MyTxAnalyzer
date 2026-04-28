from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.schemas import NetworkResponse
from app.services.network_service import NetworkService

router = APIRouter()


@router.get("", response_model=list[NetworkResponse])
def list_networks(db: Session = Depends(get_db)) -> list:
    return NetworkService(db).list_networks()
