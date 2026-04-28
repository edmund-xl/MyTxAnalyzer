from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import cases, evidence, findings, networks, reports
from app.core.config import settings
from app.core.database import create_all, get_db
from app.core.logging import configure_logging
from app.models.schemas import TxAnalyzerRuntimeHealth
from app.services.network_service import NetworkService
from app.services.txanalyzer_runtime_service import TxAnalyzerRuntimeService

configure_logging()

app = FastAPI(title=settings.app_name, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    create_all()
    db = next(get_db())
    try:
        NetworkService(db).seed_from_config()
    finally:
        db.close()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/health/txanalyzer", response_model=TxAnalyzerRuntimeHealth)
def txanalyzer_health() -> TxAnalyzerRuntimeHealth:
    return TxAnalyzerRuntimeService().check()


app.include_router(networks.router, prefix="/api/networks", tags=["networks"])
app.include_router(cases.router, prefix="/api/cases", tags=["cases"])
app.include_router(evidence.router, prefix="/api", tags=["evidence"])
app.include_router(findings.router, prefix="/api", tags=["findings"])
app.include_router(reports.router, prefix="/api", tags=["reports"])
