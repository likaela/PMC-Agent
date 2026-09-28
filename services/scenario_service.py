"""生产方案推演服务。

该服务仅比较既有 PMC 工作流已经给出的结果。它不读取 Excel、不修改 BOM/MRP/采购
规则，也不编造采购参数或到货状态。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


WorkflowRunner = Callable[[str, str, int], Mapping[str, Any]]


def _as_dict(result: Mapping[str, Any]) -> dict[str, Any]:
    return dict(result)


def _blocking_count(result: Mapping[str, Any]) -> int:
    blocking_materials = result.get("blocking_materials", [])
    return len(blocking_materials) if isinstance(blocking_materials, list) else 0


def _reduction_improvement(
    original_result: Mapping[str, Any],
    reduced_result: Mapping[str, Any],
) -> str:
    original_status = original_result.get("decision_status")
    reduced_status = reduced_result.get("decision_status")
    original_blockers = _blocking_count(original_result)
    reduced_blockers = _blocking_count(reduced_result)
    if reduced_status == "ready" and original_status != "ready":
        return "降低数量后的既有 PMC 工作流结果为 ready，可作为优先开工候选方案。"
    if reduced_blockers < original_blockers:
        return f"阻塞物料由 {original_blockers} 项降至 {reduced_blockers} 项，仍需按结果处理剩余缺料。"
    return "降低数量后未改善到可开工状态，仍需结合既有缺料与采购结果处理。"


def _purchase_completion_scenario(
    quantity: int,
    original_result: Mapping[str, Any],
) -> dict[str, Any]:
    missing = original_result.get("missing_purchase_parameters", [])
    has_missing_parameters = isinstance(missing, list) and bool(missing)
    if has_missing_parameters:
        improvement = (
            "需先由业务人员补充采购参数；参数完整并形成采购方案后，"
            "应重新运行既有 PMC 工作流确认 procurement_pending 或后续状态。"
        )
        next_status = "procurement_pending"
    else:
        improvement = "采购参数已完整；是否可开工仍以既有 PMC 工作流的采购到货与 MRP 结果为准。"
        next_status = None
    return {
        "name": "保持数量，等待采购补全",
        "quantity": quantity,
        "workflow_result": _as_dict(original_result),
        "improvement": improvement,
        "scenario_status": "conditional_purchase_plan",
        "conditional_next_status": next_status,
    }


def simulate_production_scenarios(
    product: str,
    bom_version: str,
    quantity: int,
    workflow_runner: WorkflowRunner,
) -> dict[str, Any]:
    """运行原方案与备选方案。

    减量方案使用原数量的一半（最小为 1），并重新调用已有 PMC 工作流。保持数量
    的采购方案不伪造采购参数，仅给出下一步需要业务确认的条件性建议。
    """

    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
        raise ValueError("生产数量必须为正整数")

    original_result = _as_dict(workflow_runner(product, bom_version, quantity))
    scenarios: list[dict[str, Any]] = []
    if quantity > 1:
        reduced_quantity = max(1, quantity // 2)
        reduced_result = _as_dict(workflow_runner(product, bom_version, reduced_quantity))
        scenarios.append(
            {
                "name": "降低生产数量",
                "quantity": reduced_quantity,
                "workflow_result": reduced_result,
                "improvement": _reduction_improvement(original_result, reduced_result),
                "scenario_status": "recalculated",
                "conditional_next_status": None,
            }
        )
    scenarios.append(_purchase_completion_scenario(quantity, original_result))

    summary = (
        "已基于既有 PMC 工作流完成原方案与备选方案推演；"
        "采购相关方案必须在业务人员补充真实参数后重新确认。"
    )
    return {"original_result": original_result, "scenarios": scenarios, "summary": summary}
