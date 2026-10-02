"""Thin, scoped aliases for existing published-fact tools; no business algorithms."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType


TOOL_KINDS = MappingProxyType({
    "inventory_query": "inventory",
    "batch_inventory_query": "inventory_batches",
    "bom_query": "bom",
    "production_analysis": "production_capacity",
    "purchase_plan": "purchase_planning",
})
PRIMARY_TOOLS = MappingProxyType({kind: name for name, kind in TOOL_KINDS.items()})
REQUIRED_PARAMETERS = MappingProxyType({
    "inventory_query": ("material_code",),
    "batch_inventory_query": ("material_code",),
    "bom_query": ("material_code", "revision"),
    "production_analysis": ("material_code", "revision", "effective_date"),
    "purchase_plan": ("material_code", "revision", "effective_date", "quantity", "start_date"),
})


class ToolRegistry:
    def __init__(self, *, resolver: Callable | None = None, scope: str = "enterprise") -> None:
        if scope != "enterprise" and resolver is None:
            raise ValueError("An isolated scope requires its own bound tool resolver")
        self.scope = scope
        self._resolver = resolver

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(TOOL_KINDS)

    def resolve(self, name: str):
        kind = TOOL_KINDS[name]  # Closed whitelist; never eval/import a model-provided name.
        if self._resolver is not None:
            return self._resolver(kind)
        if kind in {"inventory", "inventory_batches", "bom"}:
            from tools.fact_query_registry import get_fact_query_tool
            return get_fact_query_tool(kind)
        if kind == "production_capacity":
            from tools.production_feasibility_query_tool import published_production_capacity_query
            return published_production_capacity_query
        from tools.published_purchase_tools import published_purchase_recommendations_query
        return published_purchase_recommendations_query

    @staticmethod
    def arguments(name: str, entities: Mapping) -> dict:
        if name not in TOOL_KINDS:
            raise ValueError("Unregistered tool")
        missing = [key for key in REQUIRED_PARAMETERS[name] if entities.get(key) is None]
        if missing:
            raise ValueError("Missing required tool parameters")
        code, revision = entities.get("material_code"), entities.get("revision")
        if name in {"inventory_query", "batch_inventory_query"}:
            return dict(material_code=code, as_of=entities.get("as_of"))
        if name == "bom_query":
            return dict(parent_material_code=code, revision=revision)
        if name == "production_analysis":
            return dict(product=code, bom_version=revision, effective_date=entities.get("effective_date"),
                        requested_quantity=entities.get("quantity"), as_of=entities.get("as_of"))
        return dict(product=code, revision=revision, effective_date=entities.get("effective_date"),
                    quantity=entities.get("quantity"), start_date=entities.get("start_date"),
                    as_of=entities.get("as_of"))


__all__ = ["ToolRegistry", "TOOL_KINDS", "PRIMARY_TOOLS", "REQUIRED_PARAMETERS"]
