from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

MemoryType = Literal["FACT", "PREFERENCE", "EPISODE"]
MemoryStatus = Literal["ACTIVE", "SUPERSEDED", "UNCERTAIN", "DELETED"]


class TranscriptCreate(BaseModel):
    timestamp: datetime
    raw_asr: str = Field(min_length=1)
    formatted_text: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryCreate(BaseModel):
    type: MemoryType
    title: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    content: dict[str, Any]
    status: MemoryStatus = "ACTIVE"
    confidence: float | None = Field(default=None, ge=0, le=1)
