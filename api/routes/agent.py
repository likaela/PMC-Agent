"""新统一入口：只分流，PMC/Fact Query 各自沿用现有受控实现。"""

from __future__ import annotations

from fastapi import APIRouter

from agents.fact_query_agent import run_fact_query_agent
from api.routes.chat import chat
from api.schemas.agent import UnifiedAgentRequest, UnifiedAgentResponse
from api.schemas.chat import ChatClarificationResponse, ChatRequest, ChatResponse
from services.agent_intent_router import route_agent_message


router = APIRouter(prefix="/api/v1/agent", tags=["Unified Agent"])


@router.post("/query", response_model=UnifiedAgentResponse)
def unified_agent_query(request: UnifiedAgentRequest) -> UnifiedAgentResponse:
    """统一自然语言入口，不改变旧 Chat、Demo 或 LangGraph 执行链。"""
    decision = route_agent_message(request.message)
    if decision["intent"] == "clarification":
        return UnifiedAgentResponse(
            intent="clarification",
            status="needs_input",
            answer="请明确您要进行生产分析，还是查询某个物料的库存、批次、BOM 或在途信息。",
            structured_data={"parser_source": decision["parser_source"]},
            provenance=None,
            warnings=[],
        )

    if decision["intent"] == "fact_query":
        result = run_fact_query_agent(request.message)
        return UnifiedAgentResponse(
            intent="fact_query",
            status=result["status"],
            answer=result["answer"],
            structured_data={
                "query_type": result["query_type"],
                "query": result["query"],
                "data": result["data"],
                "completeness": result["completeness"],
                "tool_name": result["tool_name"],
                "parser_source": result["parser_source"],
            },
            provenance=result["provenance"],
            warnings=result["warnings"],
        )

    # 复用既有 Chat 路由函数，保留 workflow_id 上下文、Scenario 和 Explanation。
    chat_response = chat(ChatRequest(message=request.message, workflow_id=request.workflow_id))
    if isinstance(chat_response, ChatClarificationResponse):
        response_status = "needs_input"
        warnings = ["生产任务缺少必要参数，请按提示补充"]
    else:
        assert isinstance(chat_response, ChatResponse)
        if chat_response.public_error:
            response_status = "unavailable"
        elif chat_response.missing_purchase_parameters:
            response_status = "needs_input"
        else:
            response_status = "ok"
        warnings = list(chat_response.follow_up_questions)
    return UnifiedAgentResponse(
        intent="pmc_analysis",
        status=response_status,
        answer=chat_response.agent_message,
        structured_data=chat_response.model_dump(mode="json"),
        provenance=None,
        warnings=warnings,
    )


__all__ = ["router", "unified_agent_query"]
