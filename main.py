"""PMC Agent 入口：业务数值必须来自已注册的确定性工具。"""

from __future__ import annotations

import sys

from langchain.agents import create_agent

from config import get_llm
from tools.agent_tools import ALL_AGENT_TOOLS


SYSTEM_PROMPT = """
你是制造业 PMC 智能助手。所有业务数值和生产结论必须以 Tool 的结构化返回为准。

真实数据标准流程：real_bom_check → real_mrp_check → real_purchase_analysis_check
→ production_decision_check → real_pmc_report_check。

规则：
- 不得自行计算 BOM、库存可用量、齐套率、缺料、采购量、风险等级或生产结论。
- 数据不足时必须调用相应 Tool；若 Tool 无法提供所需采购参数，应向用户逐项询问。
- 不得编造库存、供应商、安全库存、采购提前期、风险或到货状态。
- 最终报告只能解释 Tool 已返回的结果，不能新增业务事实。
"""


def build_agent():
    """构建保留既有工具并加入真实业务工具链的 Agent。"""
    return create_agent(model=get_llm(), tools=ALL_AGENT_TOOLS, system_prompt=SYSTEM_PROMPT)


def run_demo() -> None:
    """保留原 Demo 启动方式，仅在直接运行文件时才调用模型。"""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    agent = build_agent()
    result = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "我要生产1000台ABC-1000，现在库存够不够？如果缺料，请给出采购建议。",
                }
            ]
        }
    )
    answer = result["messages"][-1].content
    print("\n" + "=" * 60)
    print("        PMC智能生产分析报告")
    print("=" * 60)
    print(answer)
    print("=" * 60)


if __name__ == "__main__":
    run_demo()
