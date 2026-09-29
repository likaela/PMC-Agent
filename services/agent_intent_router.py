"""统一自然语言入口的受控意图分流；不执行任何 PMC 或事实计算。"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict

from config import get_llm, get_llm_configuration_status


RoutedIntent = Literal["pmc_analysis", "fact_query"]


class IntentExtraction(BaseModel):
    """LLM 仅允许返回入口意图；字段由下游已校验解析器提取。"""

    model_config = ConfigDict(extra="forbid")

    intent: RoutedIntent


class RouteDecision(TypedDict):
    intent: RoutedIntent | Literal["clarification"]
    parser_source: Literal["llm", "rule_fallback", "rule_override", "ambiguous"]


_ROUTER_PROMPT = """
你只做意图分类，不回答问题、不计算业务数值、不调用数据源。
pmc_analysis：生产任务、开工判断、生产原因追问、产量调整或方案推演。
fact_query：查询已发布的库存、批次、BOM、在途事实。
只返回符合 schema 的 intent，不返回事实、数量、采购或生产结论。
"""
_PMC_PATTERN = re.compile(r"生产|开工|减(?:少|量)|调整.*(?:台|件|个)|产量|齐套|缺料|生产方案|哪些物料.*影响")
_FACT_PATTERN = re.compile(r"库存|批次|库位|BOM|物料清单|物料组成|在途|到货|采购订单", re.IGNORECASE)


def _rule_classify(message: str) -> RoutedIntent | Literal["ambiguous"] | None:
    pmc = bool(_PMC_PATTERN.search(message))
    fact = bool(_FACT_PATTERN.search(message))
    if pmc and fact:
        return "ambiguous"
    if pmc:
        return "pmc_analysis"
    if fact:
        return "fact_query"
    return None


def _invoke_llm_classification(message: str) -> IntentExtraction:
    llm = get_llm().with_structured_output(IntentExtraction, method="json_mode")
    response = llm.invoke([("system", _ROUTER_PROMPT), ("human", message)])
    if isinstance(response, IntentExtraction):
        return response
    if isinstance(response, BaseModel):
        return IntentExtraction.model_validate(response.model_dump())
    if isinstance(response, Mapping):
        return IntentExtraction.model_validate(dict(response))
    raise ValueError("模型未返回受控意图对象")


def route_agent_message(message: str) -> RouteDecision:
    """分类失败时仅回退规则；双重意图不猜测，要求用户澄清。"""
    rule = _rule_classify(message)
    if rule == "ambiguous":
        return {"intent": "clarification", "parser_source": "ambiguous"}

    if get_llm_configuration_status()["status"] == "ok":
        try:
            llm_intent = _invoke_llm_classification(message).intent
            if rule is not None and llm_intent != rule:
                return {"intent": rule, "parser_source": "rule_override"}
            return {"intent": llm_intent, "parser_source": "llm"}
        except Exception:
            pass

    if rule is not None:
        return {"intent": rule, "parser_source": "rule_fallback"}
    return {"intent": "clarification", "parser_source": "rule_fallback"}


__all__ = ["IntentExtraction", "RouteDecision", "RoutedIntent", "route_agent_message"]
