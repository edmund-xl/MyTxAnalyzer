from fastapi import FastAPI

from app.api import cases, evidence, findings, networks, reports

app = FastAPI(title="On-chain RCA Workbench API", version="0.1.0")

@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

app.include_router(networks.router, prefix="/api/networks", tags=["networks"])
app.include_router(cases.router, prefix="/api/cases", tags=["cases"])
app.include_router(evidence.router, prefix="/api", tags=["evidence"])
app.include_router(findings.router, prefix="/api", tags=["findings"])
app.include_router(reports.router, prefix="/api", tags=["reports"])
