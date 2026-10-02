"""Resolve missing enterprise BOM context from published metadata only.

The BOM evaluation date is an explicit user business date, or the UTC date of an
authoritative published inventory observation. effective_from is an interval
boundary, not permission to assume a historical/future BOM is current. No clock,
latest-revision shortcut, or inferred purchasing start date is used here.
"""

from __future__ import annotations

import copy
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from agents.planner import AgentPlan, TaskEntities
from repositories.agent_context_repository import AgentContextRepository


logger = logging.getLogger(__name__)
_SOURCE_KEYS = ("source_file", "content_sha256", "import_batch_id", "sheet_name")
_RELATIVE_DATE = re.compile(r"[上下]个?月|[上下]周|[上下]星期|明天|后天|今天|昨天|前天|本月|本周|下午|上午|月底|月初|今年|明年|去年|\d+天[前后]")
_DATE_LITERAL = re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?![\dT])")


def _date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _time(value: object) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Inventory observation lacks a timezone")
    return parsed.astimezone(UTC)


def _source(row: dict) -> dict:
    return {key: str(row[key]) for key in _SOURCE_KEYS if row.get(key) is not None}


@dataclass
class ContextResolution:
    plan: AgentPlan
    status: str = "ok"
    message: str | None = None
    resolutions: list[dict] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)
    provenance: dict = field(default_factory=dict)

    def reference(self) -> dict | None:
        if not self.resolutions and not self.candidates and not self.message:
            return None
        # This is a metadata resolver operation, not a registered business Tool.
        result = dict(status="ok" if self.status == "ok" else "data_unavailable",
            query={"product": self.plan.entities.material_code, "revision": self.plan.entities.revision,
                   "effective_date": self.plan.entities.effective_date},
            data={"resolutions": copy.deepcopy(self.resolutions), "candidates": copy.deepcopy(self.candidates)},
            completeness={"bom_context": self.status == "ok"}, provenance=copy.deepcopy(self.provenance),
            warnings=[self.message] if self.message else [])
        return dict(tool_name="published_bom_context", query=result["query"], result=result)


class ContextResolver:
    def __init__(self, repository: AgentContextRepository):
        self.repository = repository

    @staticmethod
    def prepare_context(context: dict) -> dict:
        """Revalidate auto-derived fields each turn; retain explicit user selections."""
        context = copy.deepcopy(context)
        for domain, previous in context.get("resolved_business_context", {}).items():
            saved = context.get(domain, {})
            if saved.get("material_code") == previous.get("material_code"):
                for key, value in previous.get("fields", {}).items():
                    if saved.get(key) == value:
                        saved[key] = None
        return context

    def resolve(self, plan: AgentPlan, message: str) -> ContextResolution:
        plan = AgentPlan.model_validate(plan.model_dump())
        result = ContextResolution(plan)
        if not set(plan.required_tools) & {"bom_query", "production_analysis", "purchase_plan"} or not plan.entities.material_code:
            return result
        try:
            return self._resolve(result, message)
        except Exception:
            logger.exception("已发布 BOM 上下文解析失败")
            result.status = "data_unavailable"
            result.message = "当前无法读取完整的已发布BOM上下文，请确认事实库及生效日期后重试。"
            return result

    def _resolve(self, result: ContextResolution, message: str) -> ContextResolution:
        entities = result.plan.entities.model_dump()
        product = self.repository.resolve_product(entities["material_code"])
        if product is None or product.get("ambiguous"):
            result.status = "data_unavailable"
            result.message = "当前没有该产品可精确关联的已发布BOM，请确认产品编码或明确别名。"
            return result
        rows = self.repository.bom_versions(str(product["material_code"]))
        if not rows:
            result.status = "data_unavailable"
            result.message = "当前没有该产品的已发布BOM，请提供或确认BOM版本与生效日期。"
            return result
        specified_revision = entities["revision"]
        if specified_revision is not None:
            rows = [row for row in rows if row["version"] == specified_revision]
            if not rows:
                result.status = "data_unavailable"
                result.message = "当前没有用户指定版本的已发布BOM，请确认BOM版本。"
                return result
        if entities["effective_date"] is None and _RELATIVE_DATE.search(message):
            result.status = "needs_input"
            result.message = "请确认具体的业务日期；暂不将相对日期替换为库存快照日期。"
            return result
        unlabeled_dates = set(_DATE_LITERAL.findall(message)) - {entities["effective_date"], entities["start_date"]}
        if unlabeled_dates and entities["effective_date"] is None:
            if len(unlabeled_dates) != 1 or entities["start_date"] is not None or re.search(r"截至|截止|库存日期|库存时点", message):
                result.status = "needs_input"
                result.message = "请明确各日期的业务含义；库存时点需要带时区的时间，BOM分析日期需要明确指定。"
                return result
            user_date = next(iter(unlabeled_dates))
            try:
                _date(user_date)
            except ValueError:
                result.status = "needs_input"
                result.message = "请提供有效的业务日期，格式为 YYYY-MM-DD。"
                return result
        else:
            user_date = None
        # Separate BOM business date from inventory observation date and purchasing start date.
        snapshot = None
        inventory_time = _time(entities["as_of"]) if entities["as_of"] else None
        if inventory_time is None:
            snapshot = self.repository.latest_inventory_time()
            if snapshot is not None:
                inventory_time = _time(snapshot["snapshot_at"])
        target = entities["effective_date"] or entities["start_date"] or user_date
        if target is not None:
            basis = {"source": "user_business_date", "value": target,
                     "field": "effective_date" if entities["effective_date"] else "start_date" if entities["start_date"] else "explicit_date"}
        elif entities["as_of"]:
            basis = {"source": "user_inventory_time", "as_of": entities["as_of"]}
        else:
            basis = {"source": "published_inventory_context", **_source(snapshot or {})}
        if target is None and inventory_time is not None:
            target = inventory_time.date().isoformat()
            basis["snapshot_at"] = inventory_time.isoformat()
        if target is None:
            result.status = "needs_input"
            result.message = "当前没有明确的已发布业务时点，请补充BOM生效日期；不会自动采用今天或某版本的起始日期。"
            return result
        target_date = _date(target)
        active = []
        for row in rows:
            first = _date(row["effective_from"])
            last = _date(row["effective_to"]) if row["effective_to"] is not None else None
            if last is not None and last < first:
                raise ValueError("Invalid published BOM period")
            if first <= target_date and (last is None or target_date <= last):
                active.append(row)
        result.candidates = [{"revision": str(row["version"]), "effective_from": _date(row["effective_from"]).isoformat(),
                              "effective_to": _date(row["effective_to"]).isoformat() if row["effective_to"] is not None else None,
                              "provenance": _source(row)} for row in active]
        result.provenance = dict(product=str(product["material_code"]), evaluated_on=target_date.isoformat(),
                                 bom_candidates=copy.deepcopy(result.candidates), date_basis=basis)
        if snapshot:
            result.provenance["inventory_date_basis"] = {"snapshot_at": inventory_time.isoformat(), **_source(snapshot)}
        elif entities["as_of"]:
            result.provenance["inventory_date_basis"] = {"user_as_of": entities["as_of"]}
        if len(active) > 1:
            result.status = "needs_input"
            result.message = "当前存在多个有效BOM版本，请确认。"
            return result
        if not active:
            result.status = "data_unavailable"
            result.message = "当前分析时点不存在符合条件的有效已发布BOM，请提供或确认版本与生效日期。"
            return result
        selected = active[0]
        source = {**_source(selected), "effective_from": _date(selected["effective_from"]).isoformat(),
                  "effective_to": _date(selected["effective_to"]).isoformat() if selected["effective_to"] is not None else None,
                  "evaluated_on": target_date.isoformat()}
        if entities["revision"] is None:
            entities["revision"] = str(selected["version"])
            result.resolutions.append(dict(source="published_bom_context", field="revision", value=entities["revision"], provenance=source))
        if entities["effective_date"] is None:
            entities["effective_date"] = target_date.isoformat()
            result.resolutions.append(dict(source="published_bom_context", field="effective_date", value=entities["effective_date"],
                                           provenance={**source, "date_basis": result.provenance["date_basis"]}))
        if entities["as_of"] is None and snapshot and set(result.plan.required_tools) & {"production_analysis", "purchase_plan"}:
            entities["as_of"] = inventory_time.isoformat()
            result.resolutions.append(dict(source="published_inventory_context", field="as_of", value=entities["as_of"],
                                           provenance=_source(snapshot)))
        if set(result.plan.required_tools) & {"production_analysis", "purchase_plan"} and entities["as_of"] is None:
            result.status = "data_unavailable"
            result.message = "当前没有已发布库存快照，无法确定库存分析时点；不会使用默认日期估算。"
            return result
        result.plan.entities = TaskEntities.model_validate(entities)
        return result

    @staticmethod
    def remember(context: dict, plan: AgentPlan, resolution: ContextResolution) -> dict:
        if plan.intent in {"bom", "production_capacity", "purchase_planning"} and plan.entities.material_code:
            domain = "fact" if plan.intent == "bom" else "production"
            fields = {row["field"]: row["value"] for row in resolution.resolutions}
            context.setdefault("resolved_business_context", {})[domain] = {
                "material_code": context.get(domain, {}).get("material_code"),
                "fields": fields, "evidence": copy.deepcopy(resolution.resolutions)}
        return context


__all__ = ["ContextResolver", "ContextResolution"]
