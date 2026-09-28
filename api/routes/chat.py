"""自然语言生产任务入口：解析参数后复用既有 PMC 工作流。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from api.routes.pmc import _workflow_response, _workflow_state_or_404
from api.schemas.chat import ChatRequest, ChatResponse, ParsedTaskResponse
from services.task_parser_service import TaskParseError, parse_production_task
from workflows.pmc_graph import run_pmc_workflow


router = APIRouter(prefix="/api/v1", tags=["Chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    """解析用户意图；所有 PMC 数值和结论仍来自既有 LangGraph 工作流。"""

    try:
        parsed_task = parse_production_task(request.message)
    except TaskParseError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from None

    try:
        workflow_id = run_pmc_workflow(**parsed_task)
        workflow_state = _workflow_state_or_404(workflow_id)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="PMC 工作流启动失败") from None

    workflow_response = _workflow_response(workflow_id, workflow_state)
    return ChatResponse(
        parsed_task=ParsedTaskResponse(**parsed_task),
        **workflow_response.model_dump(),
    )
