"""新统一入口：只分流，PMC/Fact Query 各自沿用现有受控实现。"""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from agents.fact_query_agent import run_fact_query_agent
from agents.production_feasibility_agent import run_production_feasibility_agent
from api.routes.chat import chat
from api.schemas.agent import (UnifiedAgentRequest, UnifiedAgentResponse, AgentSessionResponse, AgentSessionHistory,
                               AgentSessionCreate, ScenarioId)
from api.schemas.chat import ChatClarificationResponse, ChatRequest, ChatResponse
from services.agent_intent_router import route_agent_message
from services.fact_dialogue_context_service import (
    get_fact_dialogue_context,
    remember_fact_dialogue_context,
)
from workflows.pmc_graph import get_pmc_workflow_state
from repositories.agent_conversation_repository import AgentConversationRepository, SessionNotFound, SessionConflict
from repositories.fact_store import create_fact_store
from services.persistent_agent_service import PersistentAgentService


router = APIRouter(prefix="/api/v1/agent", tags=["Unified Agent"])


def _persistent_service(scenario_id: ScenarioId | None = None) -> PersistentAgentService:
    if scenario_id is not None:
        from services.demo_scenario_agent_service import build_demo_scenario_agent
        service = build_demo_scenario_agent()
        service.enable_orchestrator()
        return service
    # 部署时显式 migrate；问答请求不改变企业事实/数据库结构。
    service = PersistentAgentService(AgentConversationRepository(create_fact_store()))
    service.enable_orchestrator()
    return service


def _session_error(error: Exception) -> JSONResponse:
    if isinstance(error, SessionNotFound):
        return JSONResponse(status_code=404, content={"code": "SESSION_NOT_FOUND", "user_message": "当前企业会话不存在，请重新创建会话。"})
    return JSONResponse(status_code=409, content={"code": "SESSION_CONFLICT", "user_message": "当前会话已有新消息，请刷新后重试。"})


@router.post("/sessions", response_model=AgentSessionResponse)
def create_agent_session(request: AgentSessionCreate | None = None):
    """创建企业会话或显式独立场景会话；不初始化或重建旧 Demo Workflow。"""
    return _persistent_service(request.scenario_id if request else None).repository.create_session()


@router.get("/sessions/{session_id}", response_model=AgentSessionHistory)
def get_agent_session(session_id: str, after: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
                      scenario_id: ScenarioId | None = Query(None)):
    """分页恢复问答、上下文及每次调用的来源证据；不重新查询/计算历史事实。"""
    try:
        return _persistent_service(scenario_id).repository.history(session_id, after=after, limit=limit)
    except SessionNotFound as error:
        return _session_error(error)


@router.post("/query", response_model=UnifiedAgentResponse)
def unified_agent_query(request: UnifiedAgentRequest) -> UnifiedAgentResponse:
    """统一自然语言入口，不改变旧 Chat、Demo 或 LangGraph 执行链。"""
    if request.session_id or request.persist_session or request.scenario_id:
        service = _persistent_service(request.scenario_id)
        session_id = request.session_id or service.repository.create_session()["session_id"]
        try:
            return UnifiedAgentResponse.model_validate(service.query(session_id, request.message))
        except (SessionNotFound, SessionConflict) as error:
            return _session_error(error)
    fact_context = get_fact_dialogue_context(request.fact_session_id)
    fact_active = bool(fact_context and request.active_context != "pmc_analysis")
    pmc_active = bool(request.workflow_id and request.active_context == "pmc_analysis")
    if fact_active or pmc_active:
        decision = route_agent_message(
            request.message,
            fact_context_active=fact_active,
            pmc_context_active=pmc_active,
        )
    else:
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
        # 显式事实查询可继续复用独立事实会话，即使上一轮显示的是 PMC；
        # 只有省略意图的追问才依据 active_context 分流。
        result = (
            run_fact_query_agent(request.message, context=fact_context)
            if fact_context else run_fact_query_agent(request.message)
        )

        query = result["query"]
        provenance = result["provenance"] if isinstance(result["provenance"], dict) else {}
        material_code = (
            query.get("resolved_material_code")
            or query.get("resolved_parent_material_code")
            or query.get("material_code")
            or query.get("parent_material_code")
        )
        session_id = request.fact_session_id if fact_context else None
        if isinstance(material_code, str) and material_code and result["query_type"]:
            session_id = remember_fact_dialogue_context(
                session_id,
                material_code=material_code,
                query_type=result["query_type"],
                revision=query.get("revision") or provenance.get("bom_version"),
                as_of=query.get("as_of") or provenance.get("snapshot_at") or provenance.get("observed_at"),
            )
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
                "fact_session_id": session_id,
            },
            provenance=result["provenance"],
            warnings=result["warnings"],
        )

    if decision["intent"] == "production_capacity":
        task_context = None
        if request.active_context == "fact_query" and fact_context and fact_context.query_type == "bom":
            task_context = {"product": fact_context.material_code, "bom_version": fact_context.revision}
        elif request.workflow_id:
            try:
                state = get_pmc_workflow_state(request.workflow_id)
            except Exception:
                state = {}
            if isinstance(state.get("product"), str) and isinstance(state.get("bom_version"), str):
                task_context = {
                    "product": state["product"],
                    "bom_version": state["bom_version"],
                    "quantity": state.get("quantity"),
                }
        result = run_production_feasibility_agent(request.message, task_context=task_context)
        return UnifiedAgentResponse(
            intent="production_capacity",
            status=result["status"],
            answer=result["answer"],
            structured_data={
                "query_type": "production_capacity",
                "query": result["query"],
                "data": result["data"],
                "completeness": result["completeness"],
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
