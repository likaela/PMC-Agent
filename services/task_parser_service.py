"""自然语言生产任务解析。

本模块只提取任务参数，不读取库存、不计算 MRP，也不产生生产或采购结论。
当前 MVP 使用可离线验证的规则解析；未来若接入 LLM，只能让 LLM 输出相同的
``product / bom_version / quantity`` 契约，并必须经过本模块的字段校验。
"""

from __future__ import annotations

import re
from typing import TypedDict


DEFAULT_BOM_VERSION = "V01"


class ParsedProductionTask(TypedDict):
    """交给 LangGraph 工作流的最小生产任务契约。"""

    product: str
    bom_version: str
    quantity: int


class TaskParseError(ValueError):
    """自然语言中缺少或包含非法任务参数。"""


_PRODUCT_PATTERN = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]{1,10}-[A-Za-z0-9]+)")
_BOM_VERSION_PATTERN = re.compile(r"(?<![A-Za-z0-9])[Vv]\s*(\d{1,3})(?![A-Za-z0-9])")
_PRODUCTION_QUANTITY_PATTERN = re.compile(
    r"(?:生产|安排生产|计划生产|做)\s*(\d+)\s*(?:台|套|件|个|只|PCS|pcs)?"
)
_QUANTITY_LABEL_PATTERN = re.compile(r"(?:生产数量|数量)\s*(?:为|是|：|:)?\s*(\d+)")
_UNIT_QUANTITY_PATTERN = re.compile(r"(\d+)\s*(?:台|套|件|个|只|PCS|pcs)")


def _parse_quantity(message: str) -> int | None:
    match = (
        _PRODUCTION_QUANTITY_PATTERN.search(message)
        or _QUANTITY_LABEL_PATTERN.search(message)
        or _UNIT_QUANTITY_PATTERN.search(message)
    )
    if not match:
        return None
    return int(match.group(1))


def _parse_bom_version(message: str) -> str:
    match = _BOM_VERSION_PATTERN.search(message)
    if not match:
        return DEFAULT_BOM_VERSION
    return f"V{int(match.group(1)):02d}"


def parse_production_task(message: str) -> ParsedProductionTask:
    """从中文生产请求中抽取任务参数。

    ``bom_version`` 没有在消息中出现时，当前展示 MVP 明确使用 ``V01`` 默认版本；
    产品型号和生产数量则必须由用户提供，避免猜测业务数据。
    """

    if not isinstance(message, str) or not message.strip():
        raise TaskParseError("请输入生产任务，例如：我要生产100台KQ-Z112")

    product_match = _PRODUCT_PATTERN.search(message)
    quantity = _parse_quantity(message)
    missing_fields: list[str] = []
    if not product_match:
        missing_fields.append("产品型号")
    if quantity is None:
        missing_fields.append("生产数量")
    if missing_fields:
        raise TaskParseError(f"无法解析生产任务，缺少：{'、'.join(missing_fields)}")
    if quantity <= 0:
        raise TaskParseError("生产数量必须为正整数")

    return {
        "product": product_match.group(1).upper(),
        "bom_version": _parse_bom_version(message),
        "quantity": quantity,
    }
