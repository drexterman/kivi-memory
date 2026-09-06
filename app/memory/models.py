from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

MemoryType = Literal["FACT", "PREFERENCE", "EPISODE"]
Certainty = Literal["explicit", "inferred", "uncertain"]


class MemoryCandidate(BaseModel):
    should_remember: bool
    type: MemoryType | None
    title: str
    subject: str
    attribute: str | None = None
    value: str | None = None
    summary: str | None = None
    certainty: Certainty
    reason: str
    evidence: str = Field(min_length=1)


class MemoryDecision(BaseModel):
    decision: Literal["CREATE", "UPDATE", "RETAIN", "REJECT", "UNCERTAIN"]
    reason: str
    memory_id: int | None = None
    superseded_memory_id: int | None = None
