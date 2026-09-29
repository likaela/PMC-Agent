"""受控事实查询 Agent：模型仅选 Tool/提取显式参数，事实与答复均由 Python 管控。"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict

from config import get_llm, get_llm_configuration_status
from fact_layer.query_models import FactQueryResult
from tools.fact_query_registry import FactQueryKind, get_fact_query_tool


class FactQueryIntent(BaseModel):
    """模型只允许返回查询路由和用户消息中实际出现的标识。"""

    model_config = ConfigDict(extra="forbid")

    query_type: Literal["inventory", "inventory_batches", "bom", "inbound"]
    material_code: str | None = None
    revision: str | None = None
    as_of: str | None = None


class FactQueryAgentResponse(TypedDict):
    status: str
    query: dict[str, Any]
    data: dict[str, Any] | None
    completeness: dict[str, bool]
    provenance: dict[str, Any] | list[dict[str, Any]] | None
    warnings: list[str]
    query_type: str | None
    tool_name: str | None
    parser_source: str
    answer: str


_INTENT_PROMPT = """
你只负责把用户的事实查询路由到 inventory、inventory_batches、bom 或 inbound，
并从原文逐字提取 material_code、revision、as_of。不能补全缺失的料号、版本或时间。
不能查询数据库、计算库存、推断到货、生成生产判断或回答业务事实。
只输出符合结构化 schema 的字段。
"""
_CODE_PATTERN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9][A-Za-z0-9_-]{2,}(?![A-Za-z0-9])")
_REVISION_PATTERN = re.compile(r"(?<![A-Za-z0-9])V\d+(?![A-Za-z0-9])", re.IGNORECASE)
_TIMESTAMP_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?"
)
_RESERVED_CODES = {"BOM", "FIFO", "MRP", "PMC"}


def _rule_intent(message: str) -> FactQueryIntent | None:
    lowered = message.lower()
    if "批次" in message or "库位" in message or "batch" in lowered:
        kind: FactQueryKind = "inventory_batches"
    elif "在途" in message or "到货" in message or "采购订单" in message or "inbound" in lowered:
        kind = "inbound"
    elif "bom" in lowered or "物料清单" in message or "物料组成" in message:
        kind = "bom"
    elif "库存" in message or "现存" in message or "stock" in lowered:
        kind = "inventory"
    else:
        return None

    revision_match = _REVISION_PATTERN.search(message)
    timestamp_match = _TIMESTAMP_PATTERN.search(message)
    tokens = _CODE_PATTERN.findall(message)
    material_code = next(
        (
            token
            for token in tokens
            if token.upper() not in _RESERVED_CODES
            and not _REVISION_PATTERN.fullmatch(token)
            and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", token)
            and (timestamp_match is None or token not in timestamp_match.group())
        ),
        None,
    )
    return FactQueryIntent(
        query_type=kind,
        material_code=material_code,
        revision=revision_match.group() if kind == "bom" and revision_match else None,
        as_of=timestamp_match.group() if kind != "bom" and timestamp_match else None,
    )


def _invoke_structured_llm(message: str) -> FactQueryIntent:
    model = get_llm().with_structured_output(FactQueryIntent, method="json_mode")
    response = model.invoke([("system", _INTENT_PROMPT), ("human", message)])
    if isinstance(response, FactQueryIntent):
        return response
    if isinstance(response, BaseModel):
        return FactQueryIntent.model_validate(response.model_dump())
    if isinstance(response, Mapping):
        return FactQueryIntent.model_validate(dict(response))
    raise ValueError("查询意图输出不是结构化对象")


def _is_literal_from_message(value: str | None, message: str) -> bool:
    return value is None or (bool(value.strip()) and value.strip().lower() in message.lower())


def _choose_intent(message: str) -> tuple[FactQueryIntent | None, str]:
    rule = _rule_intent(message)
    if get_llm_configuration_status()["status"] == "ok":
        try:
            llm_intent = _invoke_structured_llm(message)
            if (
                (rule is None or llm_intent.query_type == rule.query_type)
                and all(
                    _is_literal_from_message(value, message)
                    for value in (llm_intent.material_code, llm_intent.revision, llm_intent.as_of)
                )
            ):
                # 本地已识别的显式编码/版本/时点优先，避免模型截断料号。
                if rule is not None:
                    return FactQueryIntent(
                        query_type=llm_intent.query_type,
                        material_code=rule.material_code or llm_intent.material_code,
                        revision=rule.revision or llm_intent.revision,
                        as_of=rule.as_of or llm_intent.as_of,
                    ), "llm"
                return llm_intent, "llm"
        except Exception:
            pass
    return rule, "rule_fallback"


def _query_arguments(intent: FactQueryIntent) -> dict[str, str | None]:
    if intent.query_type == "bom":
        return {
            "parent_material_code": intent.material_code or "",
            "revision": intent.revision or "",
        }
    return {"material_code": intent.material_code or "", "as_of": intent.as_of}


def _failed_result(query: dict[str, object]) -> FactQueryResult:
    return {
        "status": "query_failed",
        "query": query,
        "data": None,
        "completeness": {},
        "provenance": None,
        "warnings": ["事实查询暂不可用，未返回推断值"],
    }


def _validated_result(value: object, query: dict[str, object]) -> FactQueryResult:
    if not isinstance(value, Mapping):
        return _failed_result(query)
    required = ("status", "query", "data", "completeness", "provenance", "warnings")
    if not set(required).issubset(value):
        return _failed_result(query)
    if not isinstance(value["query"], Mapping) or not isinstance(value["completeness"], Mapping):
        return _failed_result(query)
    if value["data"] is not None and not isinstance(value["data"], Mapping):
        return _failed_result(query)
    if not isinstance(value["warnings"], list):
        return _failed_result(query)
    if value["status"] not in {
        "ok", "item_not_found", "item_alias_ambiguous", "data_unavailable", "invalid_query", "query_failed"
    }:
        return _failed_result(query)
    return {key: value[key] for key in required}  # type: ignore[return-value]


def _known(value: object) -> str:
    return "未知" if value is None else str(value)


def _answer_from_result(kind: FactQueryKind, result: FactQueryResult) -> str:
    status = result["status"]
    if status in {"item_not_found", "data_unavailable", "invalid_query"}:
        detail = {
            "item_not_found": "没有精确匹配的物料标识",
            "data_unavailable": "没有符合查询条件的已发布事实",
            "invalid_query": "查询条件不完整或时点格式无效",
        }[status]
        return f"当前事实库没有对应信息：{detail}。请核对物料编码、BOM 版本或查询时点。"
    if status == "item_alias_ambiguous":
        return "当前事实库的物料别名对应多个标准料号，需要先确认物料身份，不能推测查询结果。"
    if status != "ok" or result["data"] is None:
        return "事实查询暂不可用，当前无法给出可靠结果，请稍后重试。"

    data = result["data"]
    query = result["query"]
    code = str(query.get("resolved_material_code") or query.get("resolved_parent_material_code") or query.get("material_code") or query.get("parent_material_code") or "该物料")
    provenance = result["provenance"]
    source = ""
    if isinstance(provenance, Mapping):
        source_file = provenance.get("source_file")
        batch_id = provenance.get("import_batch_id")
        if source_file or batch_id:
            source = f" 来源：{_known(source_file)}；导入批次：{_known(batch_id)}。"

    if kind == "inventory":
        answer = (
            f"{code} 的已发布在库数量为 {_known(data.get('on_hand_qty'))}；"
            f"可用数量为 {_known(data.get('available_qty'))}；"
            f"预留数量为 {_known(data.get('reserved_qty'))}。"
        )
    elif kind == "inventory_batches":
        batches = data.get("batches")
        if not isinstance(batches, list):
            return "事实查询结果不完整，当前无法给出可靠批次信息。"
        snippets = [
            f"批次 {_known(row.get('batch_no'))}、库位 {_known(row.get('location'))}、在库 {_known(row.get('on_hand_qty'))}"
            for row in batches[:10]
            if isinstance(row, Mapping)
        ]
        remainder = f"；其余 {len(batches) - 10} 条见结构化结果" if len(batches) > 10 else ""
        answer = f"{code} 有 {len(batches)} 条已发布库存明细：" + "；".join(snippets) + remainder + "。"
    elif kind == "bom":
        lines = data.get("lines")
        if not isinstance(lines, list):
            return "事实查询结果不完整，当前无法给出可靠 BOM 信息。"
        snippets = [
            f"{_known(row.get('child_item', {}).get('material_code') if isinstance(row.get('child_item'), Mapping) else None)} × {_known(row.get('qty_per'))}"
            for row in lines[:10]
            if isinstance(row, Mapping)
        ]
        remainder = f"；其余 {len(lines) - 10} 条见结构化结果" if len(lines) > 10 else ""
        answer = f"{code} 的已发布 BOM 版本 {_known(data.get('revision'))} 共 {len(lines)} 条明细：" + "；".join(snippets) + remainder + "。"
    else:
        answer = (
            f"{code} 的已发布采购事实：订购数量 {_known(data.get('ordered_qty'))}；"
            f"已收数量 {_known(data.get('received_qty'))}；"
            f"在途数量 {_known(data.get('in_transit_qty'))}。"
        )
    warnings = result["warnings"]
    warning_text = " 提示：" + "；".join(str(warning) for warning in warnings) + "。" if warnings else ""
    return answer + source + warning_text


def run_fact_query_agent(message: str) -> FactQueryAgentResponse:
    """独立入口：识别意图、调用一个受控 Tool、保留原始结构化结果。"""
    if not isinstance(message, str) or not message.strip():
        result: FactQueryResult = {
            "status": "invalid_query",
            "query": {"message": ""},
            "data": None,
            "completeness": {},
            "provenance": None,
            "warnings": ["查询内容不能为空"],
        }
        return {**result, "query_type": None, "tool_name": None, "parser_source": "rule_fallback", "answer": _answer_from_result("inventory", result)}
    intent, parser_source = _choose_intent(message.strip())
    if intent is None:
        result: FactQueryResult = {
            "status": "invalid_query",
            "query": {"message": message},
            "data": None,
            "completeness": {},
            "provenance": None,
            "warnings": ["请明确查询库存、库存批次、BOM 或在途事实"],
        }
        return {**result, "query_type": None, "tool_name": None, "parser_source": parser_source, "answer": _answer_from_result("inventory", result)}

    tool = get_fact_query_tool(intent.query_type)
    arguments = _query_arguments(intent)
    try:
        result = _validated_result(tool.invoke(arguments), arguments)
    except Exception:
        result = _failed_result(arguments)
    return {
        **result,
        "query_type": intent.query_type,
        "tool_name": tool.name,
        "parser_source": parser_source,
        "answer": _answer_from_result(intent.query_type, result),
    }


__all__ = ["FactQueryAgentResponse", "FactQueryIntent", "run_fact_query_agent"]
