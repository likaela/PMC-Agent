"""生产方案推演 API 的公开契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from api.schemas.pmc import PmcWorkflowResponse


class ScenarioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    product: str = Field(min_length=1, examples=["KQ-Z112"])
    bom_version: str = Field(min_length=1, examples=["V01"])
    quantity: int = Field(gt=0, examples=[100])


class ScenarioItemResponse(BaseModel):
    name: str
    quantity: int
    workflow_result: PmcWorkflowResponse
    improvement: str
    scenario_status: Literal["recalculated", "conditional_purchase_plan"]
    conditional_next_status: Literal["procurement_pending"] | None = None


class ScenarioResponse(BaseModel):
    original_result: PmcWorkflowResponse
    scenarios: list[ScenarioItemResponse]
    summary: str
