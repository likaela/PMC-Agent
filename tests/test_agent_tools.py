import inspect
import unittest

from scripts.generate_kq_z112_real_mrp_report import build_kq_z112_report
from tools import agent_tools
from tools.agent_tools import (
    ALL_AGENT_TOOLS,
    production_decision_check,
    real_bom_check,
    real_mrp_check,
    real_pmc_report_check,
    real_purchase_analysis_check,
)


class AgentToolTests(unittest.TestCase):
    def build_real_tool_chain(self) -> dict[str, object]:
        bom = real_bom_check.invoke(
            {"product": "KQ-Z112", "bom_version": "V01", "quantity": 1}
        )
        mrp = real_mrp_check.invoke({"bom_requirements": bom["bom_requirements"]})
        purchase = real_purchase_analysis_check.invoke({"mrp_result": mrp["mrp_result"]})
        decision = production_decision_check.invoke(
            {
                "product": "KQ-Z112",
                "quantity": 1,
                "mrp_result": mrp["mrp_result"],
                "purchase_analysis": purchase,
            }
        )
        report = real_pmc_report_check.invoke(
            {
                "product": "KQ-Z112",
                "bom_version": bom["bom_version"],
                "quantity": 1,
                "bom_requirements": bom["bom_requirements"],
                "mrp_result": mrp["mrp_result"],
                "purchase_analysis": purchase,
                "data_quality_status": mrp["data_quality_status"],
                "production_decision": decision,
            }
        )
        return {"bom": bom, "mrp": mrp, "purchase": purchase, "decision": decision, "report": report}

    def test_required_tools_are_registered(self) -> None:
        tool_names = {tool.name for tool in ALL_AGENT_TOOLS}
        self.assertTrue(
            {
                "bom_check",
                "inventory_check",
                "purchase_check",
                "real_bom_check",
                "real_mrp_check",
                "real_purchase_analysis_check",
                "production_decision_check",
                "real_pmc_report_check",
            }.issubset(tool_names)
        )

    def test_real_mrp_tool_returns_structured_mrp_result(self) -> None:
        bom = real_bom_check.invoke(
            {"product": "KQ-Z112", "bom_version": "V01", "quantity": 1}
        )
        result = real_mrp_check.invoke({"bom_requirements": bom["bom_requirements"]})
        self.assertEqual(len(result["mrp_result"]["materials"]), 44)
        self.assertEqual(result["mrp_result"]["can_produce"], False)
        self.assertEqual(len(result["data_quality_status"]["inventory_data_error_exclusions"]), 22)

    def test_production_tool_returns_real_blocked_decision(self) -> None:
        chain = self.build_real_tool_chain()
        decision = chain["decision"]
        self.assertEqual(decision["decision_status"], "blocked")
        self.assertFalse(decision["can_start_production"])
        self.assertEqual(len(decision["blocking_materials"]), 8)

    def test_standard_agent_tool_chain_builds_structured_report(self) -> None:
        chain = self.build_real_tool_chain()
        report = chain["report"]
        self.assertEqual(report["product_information"], {"product": "KQ-Z112", "production_quantity": 1})
        self.assertEqual(report["production_decision"]["decision_status"], "blocked")
        self.assertEqual(len(report["purchase_parameter_missing_items"]), 8)
        self.assertEqual(report["purchase_recommendations"], [])

    def test_agent_tool_result_matches_deterministic_report(self) -> None:
        report = self.build_real_tool_chain()["report"]
        deterministic_report = build_kq_z112_report()
        self.assertEqual(report["production_decision"], deterministic_report["production_decision"])
        self.assertEqual(report["shortage_list"], deterministic_report["shortage_list"])
        self.assertEqual(
            report["purchase_parameter_missing_items"],
            deterministic_report["purchase_parameter_missing_items"],
        )

    def test_agent_tools_do_not_depend_on_llm_for_business_numbers(self) -> None:
        source = "\n".join(
            [
                inspect.getsource(agent_tools),
                inspect.getsource(real_mrp_check.func),
                inspect.getsource(production_decision_check.func),
            ]
        ).lower()
        self.assertNotIn("get_llm", source)
        self.assertNotIn("chatopenai", source)
        self.assertNotIn("deepseek", source)


if __name__ == "__main__":
    unittest.main()
