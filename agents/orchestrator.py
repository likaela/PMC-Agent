"""Minimal bounded orchestration of existing tools, evidence and public response."""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass

from agents.evidence import EvidenceCollector
from agents.context_resolver import ContextResolver
from agents.planner import AgentPlan, AgentPlanner
from agents.response_generator import ResponseGenerator
from agents.tool_registry import PRIMARY_TOOLS, TOOL_KINDS, ToolRegistry
from agents import business_language as language


logger = logging.getLogger(__name__)
_LABELS = {"intent": "查询意图", "material_code": "物料或产品编码", "revision": "BOM版本",
           "effective_date": "BOM生效日期", "quantity": "生产数量", "start_date": "计划开工日期",
           "as_of": "带时区的库存分析时点", "required_qty": "FIFO明确领用数量",
           "valid_parameters": "有效的查询参数（数量须为正整数，日期须明确有效）"}


@dataclass
class OrchestratedTurn:
    response: dict
    context: dict
    references: list[dict]


class AgentOrchestrator:
    def __init__(self, registry: ToolRegistry, *, planner: AgentPlanner | None = None,
                 response_generator: ResponseGenerator | None = None, context_resolver: ContextResolver | None = None,
                 inventory_operations=None):
        self.registry = registry
        self.planner = planner or AgentPlanner()
        self.response_generator = response_generator or ResponseGenerator()
        if context_resolver is not None and registry.scope != "enterprise":
            raise ValueError("Enterprise context resolution cannot be bound to Demo")
        self.context_resolver = context_resolver
        self.inventory_operations = inventory_operations

    def run(self, message: str, context: dict, *, history_loader=None) -> OrchestratedTurn | None:
        context = copy.deepcopy(context)
        original_context = copy.deepcopy(context)
        scope = context.get("scenario_id") or "enterprise"
        if scope != self.registry.scope:
            raise ValueError("Conversation and tool data scope differ")
        if self.context_resolver is not None:
            context = self.context_resolver.prepare_context(context)
        plan, parser_source = self.planner.plan(message, context)
        # Revalidate at the execution boundary, including injected/custom planners.
        plan = AgentPlan.model_validate(plan.model_dump())
        if self.registry.scope == "enterprise":
            if plan.operation == "external_risk":
                return self._information(plan, original_context, "data_unavailable",
                    "当前支持内部库存风险、生产缺料风险、临期与呆滞分析。由于没有权威外部数据源，外部供应链风险和政策影响暂无法判断。")
            if plan.operation in {"explain", "email_draft"} and not language.refresh_requested(message):
                try:
                    reused = self._reuse(plan, original_context, history_loader)
                except Exception:
                    logger.exception("读取会话证据失败")
                    return self._information(plan, original_context, "query_failed",
                        "当前会话证据暂不可用，请稍后重试；未重新计算或生成推断事实。")
                if reused is not None:
                    return reused
                if plan.operation == "email_draft":
                    return self._information(plan, original_context, "needs_input", "当前没有匹配当前任务的采购证据，请先完成采购分析，再生成邮件草稿。")
                # No demand => no shortage cause. Do not revive unrelated or failed evidence.
                if plan.intent in {"inventory", "inventory_batches", "clarification"}:
                    return self._information(plan, original_context, "needs_input",
                        "当前只有库存记录，缺少对应需求及缺料原因证据，无法判断缺料风险；请明确生产任务或需求数量。")
            if plan.operation in {"inventory_health", "expiry", "stagnation", "safety", "fifo"}:
                if plan.intent == "clarification":
                    return self._information(plan, original_context, "needs_input",
                        "请明确要查询哪个物料的临期风险，以及相应有效期或已确认临期阈值；不推测全库范围。")
                if self.inventory_operations is not None:
                    try:
                        plan = self.inventory_operations.prepare(plan)
                    except Exception:
                        logger.exception("库存分析上下文读取失败")
                        return self._information(plan, original_context, "query_failed",
                            "库存分析服务暂不可用，请稍后重试；未生成风险或批次推断。")
        if plan.intent == "inbound":
            return None  # Explicit compatibility delegation, not a model-selected sixth tool.
        if plan.operation == "product_search":
            # Catalog browsing does not invalidate the last task's resolved evidence context.
            context = original_context
        resolution, context_references = None, []
        if self.context_resolver is not None:
            resolution = self.context_resolver.resolve(plan, message)
            plan = resolution.plan
            reference = resolution.reference()
            context_references = [reference] if reference is not None else []
            if resolution.status != "ok":
                response = dict(intent=plan.intent, status=resolution.status, answer=resolution.message,
                    structured_data=dict(query_type=plan.intent, query=plan.entities.model_dump(), data=None,
                        completeness={"bom_context": False}, parser_source=parser_source,
                        context_resolution={"status": resolution.status, "candidates": resolution.candidates,
                                            "resolutions": resolution.resolutions}),
                    provenance=resolution.provenance or None, warnings=[resolution.message])
                return OrchestratedTurn(response, self._context(context, plan, None), context_references)
        plan.missing_parameters = AgentPlanner._missing(plan) if plan.intent != "clarification" else (plan.missing_parameters or ["intent"])
        if plan.missing_parameters:
            labels = [_LABELS.get(key, "必要业务参数") for key in plan.missing_parameters]
            response = dict(intent=plan.intent, status="needs_input", answer="请补充：" + "、".join(labels) + "。未执行事实计算。",
                            structured_data=dict(query={"query_type": plan.intent, **plan.entities.model_dump()},
                                                 missing_fields=labels, parser_source=parser_source),
                            provenance=None, warnings=[])
            saved = self._context(context, plan, None)
            if resolution is not None:
                response["structured_data"]["context_evidence"] = resolution.resolutions
                response["provenance"] = resolution.provenance or None
                saved = self.context_resolver.remember(saved, plan, resolution)
            return OrchestratedTurn(response, saved, context_references)
        collector = EvidenceCollector()
        records, kinds, steps, aliases = [], [], [], []
        for name in plan.required_tools:
            # Validate complete arguments before any execution. Planner cannot issue raw SQL/kwargs.
            args = self.registry.arguments(name, {**plan.entities.model_dump(), **plan.inventory_request.model_dump(), "search_term": plan.search_term})
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
            kinds.append("inventory_risk" if name == "inventory_risk_analysis" else
                         name if name in {"inventory_risk", "inventory_fifo"} else TOOL_KINDS[name])
            aliases.append(name)
            steps.append(dict(operation=name, status=record.output["status"]))
            if record.output["status"] != "ok":
                break  # Fail closed; don't continue a plan on missing/failed facts.
        primary = plan.required_tools[0] if plan.operation in {"inventory_health", "expiry", "stagnation", "safety", "fifo", "product_search"} else PRIMARY_TOOLS[plan.intent]
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
        if plan.constraints:
            response["structured_data"]["requested_constraints"] = [entry.model_dump() for entry in plan.constraints]
            response["warnings"].append("用户MOQ/LT仅作为待确认请求记录，计算仍采用已发布参数，不覆盖企业事实。")
        saved = self._context(context, plan, result)
        if resolution is not None:
            response["structured_data"]["context_evidence"] = resolution.resolutions
            if resolution.resolutions:
                if isinstance(response["provenance"], dict):
                    response["provenance"] = {**response["provenance"], "context_resolution": resolution.provenance}
                else:
                    response["provenance"] = [*(response["provenance"] or []), resolution.provenance]
                prefix = (f"本次查询BOM版本 {plan.entities.revision} 的结构，不代表当前生产有效性。 "
                          if set(plan.required_tools) == {"bom_query"} and plan.entities.effective_date is None
                          else f"本次采用BOM版本 {plan.entities.revision}，分析生效日期 {plan.entities.effective_date}。 ")
                response["answer"] = prefix + response["answer"]
            saved = self.context_resolver.remember(saved, plan, resolution)
        return OrchestratedTurn(response, saved, context_references + [r.reference() for r in records])

    @staticmethod
    def _information(plan, context, status, answer):
        return OrchestratedTurn(dict(intent=plan.intent, status=status, answer=answer,
            structured_data=dict(query=plan.entities.model_dump(), data=None, operation=plan.operation,
                                 completed_steps=[]), provenance=None, warnings=[answer]), context, [])

    def _reuse(self, plan, context, history_loader):
        if history_loader is None:
            return None
        domain = context.get("active_domain")
        previous = context.get(domain, {}) if domain in {"production", "fact"} else {}
        email = plan.operation == "email_draft"
        kind = "purchase_planning" if email else plan.intent
        if email and domain != "production":
            return None
        if not email and kind != previous.get("query_type"):
            return None
        code = plan.entities.material_code or previous.get("material_code")
        if not code or (plan.entities.material_code and plan.entities.material_code != previous.get("material_code")):
            return None
        for turn in reversed(history_loader()):
            response = turn["response"]
            if response["intent"] != kind and not (email and response["intent"] == "clarification"):
                continue
            candidates = [ref for ref in turn["fact_references"] if ref["tool_name"] != "published_bom_context"]
            for ref in candidates:
                permitted = {"production_capacity": {"published_production_capacity_query"},
                    "purchase_planning": {"published_purchase_recommendations_query"},
                    "inventory": {"published_inventory_query", "published_inventory_risk_analysis"},
                    "inventory_batches": {"published_inventory_batch_query", "published_inventory_fifo_plan"},
                    "bom": {"published_bom_query"}, "inbound": {"published_inbound_supply_query"}}
                if ref["tool_name"] not in permitted.get(kind, set()):
                    continue
                output = ref["result"]
                query, data = output["query"], output.get("data") or {}
                actual = query.get("resolved_material_code") or query.get("resolved_parent_material_code") or data.get("product") or query.get("material_code") or query.get("product")
                if actual != code:
                    continue
                if kind == "purchase_planning" and not data.get("recommendations"):
                    continue
                # Same object is not enough: quantity/version/time also define the task.
                keys = {"revision": ("revision", "bom_version"), "quantity": ("quantity", "requested_quantity"),
                        "effective_date": ("effective_date",), "as_of": ("as_of",), "start_date": ("start_date",)}
                if any(getattr(plan.entities, field) is not None and
                       next((query[k] for k in aliases if query.get(k) is not None), None) != getattr(plan.entities, field)
                       for field, aliases in keys.items()
                       if (field != "quantity" or kind in {"production_capacity", "purchase_planning"})
                       and (field != "start_date" or kind == "purchase_planning")):
                    continue
                if kind == "inventory" and "shortage_qty" not in data and not data.get("inventory_lots"):
                    # Stock totals alone cannot explain a demand shortage.
                    return None
                collector = EvidenceCollector()
                record = collector.collect(ref["tool_name"], ref["query"], output)
                format_kind = {"published_inventory_risk_analysis": "inventory_risk",
                               "published_inventory_fifo_plan": "inventory_fifo"}.get(ref["tool_name"], kind)
                answer, source = (self.response_generator.draft_email([record], [kind]) if email
                                  else self.response_generator.generate([record], [format_kind]))
                # This is an explanation/draft, not a newly executed query result card.
                result = dict(intent=plan.intent, status=output["status"],
                    answer="依据本会话已保存的分析证据（不是最新库存重查）：\n" + answer,
                    structured_data=dict(query=copy.deepcopy(query), data=None, completed_steps=[],
                        operation=plan.operation, response_source=source, reused_result=copy.deepcopy(output),
                        reused_from_turn_id=turn["turn_id"]), provenance=copy.deepcopy(output["provenance"]),
                    warnings=list(output["warnings"]))
                return OrchestratedTurn(result, context, [record.reference()])
        return None

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
