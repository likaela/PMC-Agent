"""统一 Agent 入口的稳定公开契约。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class UnifiedAgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    message: str = Field(min_length=1, examples=["查询 MAT-001 库存"])
    workflow_id: str | None = Field(default=None, min_length=1)


class UnifiedAgentResponse(BaseModel):
    intent: Literal["pmc_analysis", "fact_query", "clarification"]
    status: str
    answer: str
    structured_data: dict[str, Any] | None
    provenance: dict[str, Any] | list[dict[str, Any]] | None
    warnings: list[str] = Field(default_factory=list)


__all__ = ["UnifiedAgentRequest", "UnifiedAgentResponse"]
