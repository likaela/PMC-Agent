"""生产方案推演入口：每个重新计算场景复用既有 PMC 工作流。"""

from __future__ import annotations

from api.routes.pmc import start_public_pmc_workflow
from api.schemas.scenario import ScenarioRequest, ScenarioResponse
from services.scenario_service import simulate_production_scenarios

from fastapi import APIRouter, HTTPException, status


router = APIRouter(prefix="/api/v1/scenarios", tags=["Scenario"])


def run_public_scenario_analysis(product: str, bom_version: str, quantity: int) -> dict[str, object]:
    """以公开 PMC 响应作为 Scenario Service 的既有工作流输入。"""
    try:
        return simulate_production_scenarios(
            product,
            bom_version,
            quantity,
            workflow_runner=lambda current_product, current_version, current_quantity: start_public_pmc_workflow(
                current_product,
                current_version,
                current_quantity,
            ).model_dump(),
        )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="生产方案推演失败") from None


@router.post("/analyze", response_model=ScenarioResponse)
def analyze_scenarios(request: ScenarioRequest) -> ScenarioResponse:
    """返回原方案、减量方案与条件性采购补全方案。"""
    return ScenarioResponse.model_validate(
        run_public_scenario_analysis(request.product, request.bom_version, request.quantity)
    )
