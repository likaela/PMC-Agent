"""Minimal bounded orchestration of existing tools, evidence and public response."""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass

from agents.evidence import EvidenceCollector
from agents.planner import AgentPlan, AgentPlanner
from agents.response_generator import ResponseGenerator
from agents.tool_registry import PRIMARY_TOOLS, TOOL_KINDS, ToolRegistry


logger = logging.getLogger(__name__)
_LABELS = {"intent": "查询意图", "material_code": "物料或产品编码", "revision": "BOM版本",
           "effective_date": "BOM生效日期", "quantity": "生产数量", "start_date": "计划开工日期",
           "valid_parameters": "有效的查询参数（数量须为正整数，日期须明确有效）"}


@dataclass
class OrchestratedTurn:
    response: dict
    context: dict
    references: list[dict]


class AgentOrchestrator:
    def __init__(self, registry: ToolRegistry, *, planner: AgentPlanner | None = None,
                 response_generator: ResponseGenerator | None = None):
        self.registry = registry
        self.planner = planner or AgentPlanner()
        self.response_generator = response_generator or ResponseGenerator()

    def run(self, message: str, context: dict) -> OrchestratedTurn | None:
        context = copy.deepcopy(context)
        scope = context.get("scenario_id") or "enterprise"
        if scope != self.registry.scope:
            raise ValueError("Conversation and tool data scope differ")
        plan, parser_source = self.planner.plan(message, context)
        # Revalidate at the execution boundary, including injected/custom planners.
        plan = AgentPlan.model_validate(plan.model_dump())
        plan.missing_parameters = AgentPlanner._missing(plan) if plan.intent != "clarification" else (plan.missing_parameters or ["intent"])
        if plan.intent == "inbound":
            return None  # Explicit compatibility delegation, not a model-selected sixth tool.
        if plan.missing_parameters:
            labels = [_LABELS.get(key, "必要业务参数") for key in plan.missing_parameters]
            response = dict(intent=plan.intent, status="needs_input", answer="请补充：" + "、".join(labels) + "。未执行事实计算。",
                            structured_data=dict(query={"query_type": plan.intent, **plan.entities.model_dump()},
                                                 missing_fields=labels, parser_source=parser_source),
                            provenance=None, warnings=[])
            return OrchestratedTurn(response, self._context(context, plan, None), [])
        collector = EvidenceCollector()
        records, kinds, steps, aliases = [], [], [], []
        for name in plan.required_tools:
            # Validate complete arguments before any execution. Planner cannot issue raw SQL/kwargs.
            args = self.registry.arguments(name, plan.entities.model_dump())
            tool_name = name
            try:
                tool = self.registry.resolve(name)
                tool_name = tool.name
                record = collector.collect(tool_name, args, tool.invoke(args))
            except Exception:
                logger.exception("受控 Agent Tool 执行失败")
                record = collector.collect(tool_name, args, dict(status="query_failed", query=args, data=None,
                    completeness={}, provenance=None, warnings=["系统查询异常，请稍后重试；未生成推断事实"]))
            records.append(record)
            kinds.append(TOOL_KINDS[name])
            aliases.append(name)
            steps.append(dict(operation=name, status=record.output["status"]))
            if record.output["status"] != "ok":
                break  # Fail closed; don't continue a plan on missing/failed facts.
        primary = PRIMARY_TOOLS[plan.intent]
        primary_record = (records[aliases.index(primary)] if primary in aliases else records[-1])
        result = primary_record.output
        if primary not in aliases:
            # A prerequisite failed: never label its BOM data as a production/purchase result.
            result = {**result, "data": None, "query": self.registry.arguments(primary, plan.entities.model_dump())}
        answer, response_source = self.response_generator.generate(records, kinds)
        provenance = result["provenance"] if len(records) == 1 else [r.provenance for r in records if r.provenance is not None]
        warnings = list(dict.fromkeys(warning for r in records for warning in r.warnings))
        status = next((r.output["status"] for r in records if r.output["status"] != "ok"), result["status"])
        response = dict(intent=plan.intent, status=status, answer=answer,
                        structured_data=dict(query_type=plan.intent, query=result["query"], data=result["data"],
                            completeness=result["completeness"], parser_source=parser_source,
                            response_source=response_source, completed_steps=steps),
                        provenance=provenance, warnings=warnings)
        return OrchestratedTurn(response, self._context(context, plan, result), [r.reference() for r in records])

    @staticmethod
    def _context(context, plan, result):
        if plan.intent != "clarification" and plan.entities.material_code:
            domain = "production" if plan.intent in {"production_capacity", "purchase_planning"} else "fact"
            saved = {"query_type": plan.intent, **plan.entities.model_dump()}
            if result:
                query, data = result["query"], result["data"] or {}
                saved["material_code"] = (query.get("resolved_material_code") or query.get("resolved_parent_material_code")
                                          or (data.get("product") if domain == "production" else None)
                                          or saved["material_code"])
            context[domain] = saved
            context["active_domain"] = domain
        return context


__all__ = ["AgentOrchestrator", "OrchestratedTurn"]
