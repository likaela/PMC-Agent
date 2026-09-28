"""自然语言 Chat API 的公开契约。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from api.schemas.pmc import PmcWorkflowResponse


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    message: str = Field(min_length=1, examples=["我要生产100台KQ-Z112，帮我看看能不能开工"])


class ParsedTaskResponse(BaseModel):
    product: str
    bom_version: str
    quantity: int


class ChatResponse(PmcWorkflowResponse):
    """解析结果加上既有 PMC 工作流的受控公开响应。"""

    parsed_task: ParsedTaskResponse
