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
        # Explicit foreign products must not inherit the filtered product.
        if parsed.material_code and parsed.material_code not in (product, dataset.get("display_product_code")):
            return OrchestratedTurn(dict(intent="clarification", status="data_unavailable",
                answer="当前精简场景只适用于所选产品。请切回企业空间查询其他产品。",
                structured_data=dict(data=None, completed_steps=[]), provenance=None, warnings=[]), copy.deepcopy(context), [])
        quantity = parsed.quantity
        previous = context.get("slim_analysis", {})
        explanation = bool(re.search(r"为什么|原因|来源|哪里|哪些物料限制|哪些.*影响", text))
        if explanation and quantity is None and previous:
            for turn in reversed(history_loader()):
                for ref in turn["fact_references"]:
                    if ref["tool_name"] == "enterprise_book_demand_analysis" and (ref["result"].get("data") or {}).get("slim_review"):
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
            answer = "本次精简评审数据不可计算，请检查场景数据。"
        else:
            maximum = data["theoretical_max_quantity"]
            answer = (f"{data['scenario_name']}：保留{data['total_material_count']}项／原{data['original_material_count']}项。"
                f"排除{data['excluded_material_count']}项，数据集版本{data['dataset_version']}。"
                f"{'包含明确标记的合成补充库存。' if data['synthetic'] else '使用可核验的真实主库存数量，没有合成补充。'}"
                f"精简场景最大满足数量为{maximum}片。")
            n = data["requested_quantity"]
            if n is not None:
                answer += f"本精简物料集合{'满足' if data['inventory_sufficient_for_requested'] else '不能满足'}生产{n}片对应的数量需求。"
                if data["book_shortages"]:
                    answer += "不足物料：" + "；".join(f"{r['name'] or r['material_code']}（{r['material_code']}）缺{r['shortage_qty']}片" for r in data["book_shortages"][:5]) + "。"
            if re.search(r"限制|最大|最多", message):
                answer += "限制产量的物料：" + "、".join(f"{r['name'] or r['material_code']}（{r['material_code']}）" for r in data["limiting_materials"][:5]) + "。"
            if re.search(r"来源|哪里", message):
                source = data["source_summary"]
                answer += "单耗来自授权BOM结构记录；真实数量来自已核验的授权主库存记录。原文件和校验信息保存在私有审计中，不向评委展示。"
                if data["synthetic"]:
                    answer += "合成补充量逐项单独记录，并非原Excel库存。"
            if reused:
                answer = "依据本会话已有证据：" + answer
            answer += "这是筛选物料集合的齐套结论，不是完整企业产品生产放行。"
        structured = dict(query_type="production_capacity", query=result["query"], data=result["data"],
            completeness=result["completeness"], response_source="deterministic", analysis_level="slim_review",
            completed_steps=[] if reused else [dict(operation="enterprise_book_demand_analysis", status=result["status"])])
        if reused:
            structured.update(operation="explain", reused_from_turn_id=reused)
        response = dict(intent="production_capacity", status=result["status"], answer=answer,
            structured_data=structured, provenance=result["provenance"], warnings=result["warnings"])
        evidence = EvidenceCollector().collect("enterprise_book_demand_analysis", original["query"], original).reference()
        return OrchestratedTurn(response, saved, [evidence])
