"""Evidence-to-language projections. No quantity, stock or cost calculations."""

from __future__ import annotations

import re


WARNING_LABELS = {
    "unit_missing": "物料计量单位尚未确认",
    "price_missing": "部分物料价格尚未确认",
    "effective_date_missing": "该BOM的生效日期尚未确认",
    "available_qty_missing": "尚缺少权威可用库存数据",
    "inventory_unknown": "该物料目前没有足够的库存事实",
    "data_unavailable": "当前信息不足，暂时无法作出可靠判断",
}


def human_warning(value: str) -> str:
    if "当前没有明确的已发布业务时点" in value:
        return "当前没有明确的已发布业务时点，请确认生产分析日期和库存快照时间；不会自动采用今天或BOM起始日期"
    for key, label in WARNING_LABELS.items():
        if key in value:
            return label
    # Unknown technical/audit fields belong in the evidence, not in ordinary prose.
    if re.search(r"[A-Za-z]+_[A-Za-z_]+|[a-fA-F0-9]{64}|[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}|[A-Za-z]:[\\/]", value):
        return "相关业务信息尚未完整确认，请查看数据完整性与来源详情"
    return value


def material_categories(data: dict) -> list[str]:
    # Labels must occur literally in published names, not be inferred from codes.
    names = [str((line.get("child_item") or {}).get("name") or "")
             for line in data.get("lines", [])]
    return [label for label in ("PCB", "电容", "电阻", "LED", "二极管", "磁珠", "MOS", "芯片", "晶振", "连接器")
            if any(label.lower() in name.lower() for name in names)]


def bom_overview(data: dict, completeness: dict) -> str:
    product = (data.get("parent_item") or {}).get("material_code") or "该产品"
    text = f"已找到 {product} 的已发布 BOM。当前版本为 {data.get('revision') or '尚未确认'}，共包含 {data.get('line_count')} 项物料。"
    if data.get("effective_from") is not None:
        text += f"生效日期为 {data['effective_from']}。"
    else:
        text += "该BOM的生效日期尚未确认，不代表当前有效生产版本。"
    categories = material_categories(data)
    if categories:
        text += "按已发布物料名称，主要包括" + "、".join(categories) + "。"
    text += "完整明细已提供在下方物料表中。"
    if completeness.get("unit") is False or completeness.get("parent_unit") is False:
        text += "物料计量单位尚未确认，因此这份BOM目前可用于结构查询，暂不能据此进行可靠的生产数量计算。"
    if completeness.get("price") is False:
        text += "部分物料价格尚未确认，暂不能进行完整成本计算。"
    return text


def business_decision(kind: str, result: dict) -> dict:
    """Presentation permission is NOT a replacement for a production verdict."""
    data = result.get("data") or {}
    if kind != "production_capacity":
        return {"status": "INFORMATIONAL", "reason": None}
    if result.get("status") != "ok":
        return {"status": "NOT_APPROVED", "reason": "NOT_APPROVED_DUE_TO_INSUFFICIENT_EVIDENCE"}
    verdict = data.get("inventory_sufficient_for_requested")
    if verdict is False:
        return {"status": "NOT_APPROVED", "reason": "CANNOT_PRODUCE_DUE_TO_SHORTAGE"}
    # Stock sufficiency alone is not an enterprise approval or arrival commitment.
    return {"status": "INFORMATIONAL", "reason": "INVENTORY_SUFFICIENT" if verdict is True else None}


def incomplete_production(result: dict) -> str:
    query, data = result.get("query", {}), result.get("data") or {}
    product = query.get("product") or query.get("material_code") or "该产品"
    quantity = query.get("quantity") or query.get("requested_quantity")
    task = f"生产{quantity}台 {product}" if quantity is not None else f"{product} 的生产计划"
    text = f"当前不能批准{task}。"
    reminders = []
    structure = data.get("bom_structure")
    if structure:
        text += f"已确认该产品存在 {structure['data']['revision']} BOM，共 {structure['data']['line_count']} 项物料。"
        complete = structure["completeness"]
        if complete.get("unit") is False or complete.get("parent_unit") is False:
            reminders.append("物料计量单位尚未确认")
        if complete.get("effective_from") is False:
            reminders.append("该BOM的生效日期尚未确认")
    reasons = list(dict.fromkeys([*reminders, *(human_warning(w) for w in result.get("warnings", []))]))
    if reasons:
        text += "目前需要确认的关键业务信息：" + "；".join(reasons) + "。"
    text += "这并不代表已经确认库存不足，而是当前证据不足，暂时无法安全放行生产计划。请补齐相应已确认业务条件后，再核验齐套、缺料物料和缺口数量。"
    return text


def source_overview(kind: str, result: dict) -> str:
    data = result.get("data") or {}
    structure = data.get("bom_structure")
    if structure:
        return source_overview("bom", structure)
    query = result.get("query", {})
    product = (data.get("parent_item") or {}).get("material_code") or data.get("product") or query.get("material_code") or query.get("product") or "当前查询对象"
    revision = data.get("revision") or query.get("revision")
    if kind == "bom" or revision:
        return f"来自企业已发布的 {product} {revision or ''} BOM及本次分析所引用的事实。详细文件、行级审计及数据完整性信息保留在来源详情中。"
    return f"来自企业已发布的 {product} 查询事实。数据时点及文件审计信息保留在来源详情中；未使用未发布数据。"


__all__ = ["human_warning", "bom_overview", "business_decision", "incomplete_production", "source_overview"]
