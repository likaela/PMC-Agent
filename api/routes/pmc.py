"""PMC 分析、状态查询和采购参数恢复路由。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, HTTPException, status

from api.schemas.pmc import (
    AnalyzeRequest,
    HealthResponse,
    PmcWorkflowResponse,
    PurchaseParameterResumeRequest,
)
from workflows.pmc_graph import (
    get_pmc_workflow_state,
    resume_pmc_workflow,
    run_pmc_workflow,
)


router = APIRouter(prefix="/api/v1/pmc", tags=["PMC"])


def _workflow_state_or_404(workflow_id: str) -> dict[str, object]:
    workflow_state = get_pmc_workflow_state(workflow_id)
    if not workflow_state:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="workflow 不存在或已失效")
    return workflow_state


def _workflow_response(workflow_id: str, workflow_state: Mapping[str, object]) -> PmcWorkflowResponse:
    """从内部工作流 State 构建受控的公开响应。"""
    decision = workflow_state.get("production_decision")
    decision_data = decision if isinstance(decision, Mapping) else {}
    blockers = decision_data.get("blocking_materials", [])
    missing = workflow_state.get("missing_purchase_parameters", [])
    report = workflow_state.get("report")
    return PmcWorkflowResponse(
        workflow_id=workflow_id,
        workflow_status=str(workflow_state.get("workflow_status", "unknown")),
        decision_status=decision_data.get("decision_status"),
        can_start_production=decision_data.get("can_start_production"),
        blocking_materials=blockers if isinstance(blockers, list) else [],
        missing_purchase_parameters=missing if isinstance(missing, list) else [],
        report=report if isinstance(report, dict) else {},
        errors=workflow_state.get("errors", []) if isinstance(workflow_state.get("errors"), list) else [],
    )


@router.post("/analyze", response_model=PmcWorkflowResponse)
def analyze_pmc(request: AnalyzeRequest) -> PmcWorkflowResponse:
    """启动一次新的内存 PMC 工作流。"""
    try:
        workflow_id = run_pmc_workflow(request.product, request.bom_version, request.quantity)
        workflow_state = _workflow_state_or_404(workflow_id)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="PMC 工作流启动失败") from None
    return _workflow_response(workflow_id, workflow_state)


@router.get("/{workflow_id}", response_model=PmcWorkflowResponse)
def get_pmc_workflow(workflow_id: str) -> PmcWorkflowResponse:
    """读取当前进程 MemorySaver 中的工作流公开快照。"""
    return _workflow_response(workflow_id, _workflow_state_or_404(workflow_id))


@router.post("/{workflow_id}/purchase-parameters", response_model=PmcWorkflowResponse)
def resume_purchase_parameters(
    workflow_id: str,
    request: PurchaseParameterResumeRequest,
) -> PmcWorkflowResponse:
    """从暂停点恢复：只补采购参数，不重跑 BOM 或 MRP。"""
    _workflow_state_or_404(workflow_id)
    updates: dict[str, dict[str, Any]] = {
        material: values.model_dump(exclude_none=True)
        for material, values in request.updates.items()
    }
    try:
        workflow_state = resume_pmc_workflow(workflow_id, updates)
    except Exception:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="PMC 工作流恢复失败") from None
    return _workflow_response(workflow_id, workflow_state)


health_router = APIRouter(tags=["System"])


@health_router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """无外部依赖的服务存活检查。"""
    return HealthResponse()
