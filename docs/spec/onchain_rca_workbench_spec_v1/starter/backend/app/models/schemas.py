from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

class SeedType(StrEnum):
    transaction = "transaction"
    address = "address"
    contract = "contract"
    alert = "alert"

class AnalysisDepth(StrEnum):
    quick = "quick"
    full = "full"
    full_replay = "full_replay"

class CaseStatus(StrEnum):
    CREATED = "CREATED"
    ENV_CHECKING = "ENV_CHECKING"
    REPORT_DRAFTED = "REPORT_DRAFTED"
    FAILED = "FAILED"

class CaseCreate(BaseModel):
    title: str | None = None
    network_key: str
    seed_type: SeedType
    seed_value: str
    time_window_hours: int = Field(default=6, ge=1, le=168)
    depth: AnalysisDepth = AnalysisDepth.quick
    modules: list[str] = Field(default_factory=list)
    language: str = "zh-CN"

class CaseResponse(BaseModel):
    id: UUID
    title: str | None
    network_key: str
    seed_type: SeedType
    seed_value: str
    status: CaseStatus
    created_at: datetime
    updated_at: datetime

    @classmethod
    def mock_from_create(cls, payload: CaseCreate) -> "CaseResponse":
        now = datetime.now(timezone.utc)
        return cls(
            id=uuid4(),
            title=payload.title,
            network_key=payload.network_key,
            seed_type=payload.seed_type,
            seed_value=payload.seed_value,
            status=CaseStatus.CREATED,
            created_at=now,
            updated_at=now,
        )
