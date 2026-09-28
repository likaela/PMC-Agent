"""自然语言生产任务入口：解析参数后复用既有 PMC 工作流。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from api.routes.pmc import _workflow_response, _workflow_state_or_404
from api.schemas.chat import ChatRequest, ChatResponse, ParsedTaskResponse
from services.task_parser_service import TaskParseError, parse_production_task
from workflows.pmc_graph import run_pmc_workflow


router = APIRouter(prefix="/api/v1", tags=["Chat"])


def _follow_up_questions(missing_items: list[object]) -> list[str]:
    """把既有采购缺失字段转为用户可执行的问题，不推测业务参数。"""
    questions: list[str] = []
    for item in missing_items:
        item_data = item.model_dump() if hasattr(item, "model_dump") else item
        if not isinstance(item_data, dict):
            continue
        material = item_data.get("material")
        fields = item_data.get("missing_fields")
        if isinstance(material, str) and isinstance(fields, list):
            questions.append(f"请为物料 {material} 补充：{'、'.join(str(field) for field in fields)}。")
    return questions


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
    follow_up_questions = _follow_up_questions(workflow_response.missing_purchase_parameters)
    agent_message = (
        "PMC 分析已完成，但仍需业务人员补充采购参数后才能继续采购分析。"
        if follow_up_questions
        else "PMC 分析已完成，结果来自确定性业务工作流。"
    )
    return ChatResponse(
        parsed_task=ParsedTaskResponse(**parsed_task),
        agent_message=agent_message,
        follow_up_questions=follow_up_questions,
        **workflow_response.model_dump(),
    )
