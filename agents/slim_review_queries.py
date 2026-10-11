"""Deterministic dialogue over an explicitly selected private filtered dataset."""
import copy
import re

from agents.enterprise_book_queries import EnterpriseBookQueries
from agents.evidence import EvidenceCollector
from agents.orchestrator import OrchestratedTurn
from services.persistent_agent_service import parse_enterprise_query
from tools.book_inventory_tools import build_book_inventory_tools
from services.slim_review_presentation import SlimReviewPresentation


class SlimReviewQueries:
    def __init__(self, service):
        self.service = service
        self.tools = build_book_inventory_tools(service)
        self.presentation = SlimReviewPresentation(service.dataset)

    def run(self, message, context, history_loader):
        text = message.strip()
        try:
            if re.search(r"生产\s*(?:[-−]|负|\d+\.\d|\d+[eE][+-]?\d|\d+\s*/\s*\d+|[a-z]+\s*(?:片|个|件))", text, re.I):
                raise ValueError("Invalid quantity")
            parsed, _ = parse_enterprise_query(text, allow_llm=False)
        except ValueError:
            return EnterpriseBookQueries._invalid_quantity(context)
        dataset = self.service.dataset
        product = dataset["product"]
        # Aliases are disclosure identifiers bound to THIS dataset, not new item master entries.
        aliases = self.presentation.aliases
        requested_alias = next((a for a in aliases.values() if re.search(r"(?<![A-Za-z0-9_-])" + re.escape(a) + r"(?![A-Za-z0-9_-])", text)), None)
        # Explicit foreign products must not inherit the filtered product.
        if parsed.material_code and parsed.material_code not in (product, dataset.get("display_product_code")) and not requested_alias:
            return OrchestratedTurn(dict(intent="clarification", status="data_unavailable",
                answer="当前分析范围只适用于所选产品。请选择对应产品后继续查询。",
                structured_data=dict(data=None, completed_steps=[]), provenance=None, warnings=[]), copy.deepcopy(context), [])
        quantity = parsed.quantity
        previous = context.get("slim_analysis", {})
        if re.search(r"再生产\s*\d+", text) and not re.search(r"再多生产", text):
            return OrchestratedTurn(dict(intent="clarification", status="needs_input", answer="请确认是重新核对该数量，还是在上次数量上追加；例如“生产1片”或“再多生产1片”。",
                structured_data=dict(data=None, completed_steps=[]), provenance=None, warnings=[]), copy.deepcopy(context), [])
        explanation = bool(re.search(r"为什么|原因|来源|哪里|哪些物料限制|哪些.*影响", text))
        refresh = bool(re.search(r"重新计算|按最新|再查一次|重新查询", text))
        if explanation and previous and not refresh:
            for turn in reversed(history_loader()):
                for ref in turn["fact_references"]:
                    data = ref["result"].get("data") or {}
                    if ref["tool_name"] == "enterprise_book_demand_analysis" and data.get("slim_review") and (quantity is None or data.get("requested_quantity") == quantity):
                        return self._turn(ref["result"], context, message, reused=turn["turn_id"])
        produce_max = bool(re.search(r"生产(?:到)?(?:最大|最多)数量|按最大|生产上限", text))
        capacity = bool(re.search(r"最多|最大|限制产量", text))
        if produce_max:
            maximum_result = self.tools["enterprise_book_demand_analysis"].invoke(dict(product=product, quantity=None))
            maximum = (maximum_result.get("data") or {}).get("theoretical_max_quantity")
            if maximum is None:
                return self._turn(maximum_result, context, message)
            if maximum == 0:
                return self._turn(maximum_result, context, message)
            quantity = maximum
        elif re.search(r"再多生产|再增加|多生产", text) and quantity is not None:
            baseline = previous.get("last_target", previous.get("quantity"))
            if baseline is None:
                baseline = previous.get("maximum")
            if baseline is None:
                return OrchestratedTurn(dict(intent="clarification", status="needs_input", answer="请先查询最大数量或指定生产数量，再调整数量。",
                    structured_data=dict(data=None, completed_steps=[]), provenance=None, warnings=[]), copy.deepcopy(context), [])
            quantity += baseline
        elif capacity:
            quantity = None
        # Zero is never converted to 1. The parser validation runs before Tool.
        result = self.tools["enterprise_book_demand_analysis"].invoke(dict(product=product,
            revision=dataset["revision"], quantity=quantity))
        if requested_alias:
            code = next(c for c, a in aliases.items() if a == requested_alias)
            rows = (result.get("data") or {}).get("materials", [])
            if not any(r["material_code"] == code for r in rows):
                return OrchestratedTurn(dict(intent="inventory", status="item_not_found", answer="该物料不在当前分析范围内。",
                    structured_data=dict(data=None, completed_steps=[]), provenance=None, warnings=[]), copy.deepcopy(context), [])
            # Retain the whole calculation Evidence; disclose only the explicitly requested row.
            turn = self._turn(result, context, message)
            data = turn.response["structured_data"]["data"]
            data["materials"] = [r for r in data["materials"] if r["material_code"] == requested_alias]
            row = data["materials"][0]
            turn.response["answer"] = f"{requested_alias}：BOM单耗{row['qty_per']}片，当前分析范围库存{row['recorded_stock_qty']}片。来源为已核验记录。"
            return turn
        return self._turn(result, context, message)

    def _turn(self, result, context, message, reused=None):
        data = result.get("data") or {}
        saved = copy.deepcopy(context)
        if result["status"] == "ok":
            prior = saved.get("slim_analysis", {})
            saved["slim_analysis"] = dict(product=data["product"], revision=data["revision"],
                quantity=data["requested_quantity"] if data["requested_quantity"] is not None else prior.get("quantity"),
                maximum=data["theoretical_max_quantity"],
                last_target=data["requested_quantity"] if data["requested_quantity"] is not None
                    else data["theoretical_max_quantity"] if re.search(r"最多|最大", message)
                    else prior.get("last_target", prior.get("quantity")))
            saved["active_domain"] = "production"
            saved["production"] = dict(material_code=data["product"], revision=data["revision"],
                quantity=saved["slim_analysis"]["quantity"], query_type="production_capacity")
        original = result
        result = self.presentation.result(result)
        data = result.get("data") or {}
        if result["status"] != "ok":
            answer = "本次分析数据暂不可计算，请核对数据来源后重试。"
        else:
            maximum = data["theoretical_max_quantity"]
            answer = (f"已完成 {data['product']} 本次生产需求核对。当前分析范围：{data['total_material_count']}项物料。"
                f"当前范围最大满足数量为{maximum}片。")
            if data["synthetic"]:
                answer += "本次包含演示库存，仅用于数量模拟。"
            n = data["requested_quantity"]
            if n is not None:
                answer += f"当前分析范围{'满足' if data['inventory_sufficient_for_requested'] else '不能满足'}生产{n}片对应的物料需求。"
                if data["book_shortages"]:
                    answer += "不足物料：" + "；".join(f"{r['name'] or r['material_code']}（{r['material_code']}）缺{r['shortage_qty']}片" for r in data["book_shortages"][:5]) + "。"
            if re.search(r"限制|最大|最多", message):
                answer += "限制产量的物料：" + "、".join(f"{r['name'] or r['material_code']}（{r['material_code']}）" for r in data["limiting_materials"][:5]) + "。"
            if re.search(r"来源|哪里", message):
                answer += "BOM单耗来自已发布记录，库存数量来自已核验主库存记录；可在来源区查看本次依据。"
                if data["synthetic"]:
                    answer += "演示库存补充逐项单独记录，不是原主库存数量。"
            if reused:
                answer = "依据本会话已有证据：" + answer
            answer += "结果仅适用于当前分析范围，不代表完整产品生产放行。"
        structured = dict(query_type="production_capacity", query=result["query"], data=result["data"],
            completeness=result["completeness"], response_source="deterministic", analysis_level="slim_review",
            completed_steps=[] if reused else [dict(operation="enterprise_book_demand_analysis", status=result["status"])])
        if reused:
            structured.update(operation="explain", reused_from_turn_id=reused)
        response = dict(intent="production_capacity", status=result["status"], answer=answer,
            structured_data=structured, provenance=result["provenance"], warnings=result["warnings"])
        evidence = EvidenceCollector().collect("enterprise_book_demand_analysis", original["query"], original).reference()
        return OrchestratedTurn(response, saved, [evidence])
