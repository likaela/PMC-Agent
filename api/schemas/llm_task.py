"""LLM 任务理解层的受控公开契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LlmTaskExtraction(BaseModel):
    """DeepSeek 的原始结构化输出；字段仍须经本地规则校验。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    intent: Literal["analysis"] = "analysis"
    product: str | None = None
    bom_version: str | None = None
    quantity: int | None = None
    reduced_quantity: int | None = None
    missing_fields: list[str] = Field(default_factory=list)


class ProductionTaskIntent(BaseModel):
    """校验后可安全交给既有 PMC Workflow 的任务意图。"""

    model_config = ConfigDict(extra="forbid")

    intent: Literal["analysis"] = "analysis"
    product: str
    bom_version: str
    quantity: int
    reduced_quantity: int | None = None
    missing_fields: list[str] = Field(default_factory=list)
    parser_source: Literal["llm", "rule_fallback"]

    def to_workflow_task(self) -> dict[str, object]:
        """只暴露既有工作流需要的三个参数。"""
        return {
            "product": self.product,
            "bom_version": self.bom_version,
            "quantity": self.quantity,
        }
